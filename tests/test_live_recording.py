"""Live Recordings: audio in numbered pieces, Captions while it runs, Stop → the final pass."""
import time
from array import array

from app import recordings
from test_recordings import a_course

SECOND = 16000


def tone(seconds, loud=3000):
    return array("h", [loud if i % 2 else -loud for i in range(int(seconds * SECOND))]).tobytes()


def silence(seconds):
    return bytes(int(seconds * SECOND) * 2)


def wait_for(get, check, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        got = get()
        if check(got):
            return got
        time.sleep(0.1)
    return got


def start(client, course=None, **body):
    r = client.post("/api/recordings/start", json={"course_id": course, **body})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def send(client, rid, seq, data):
    return client.post(f"/api/recordings/{rid}/chunk?seq={seq}", content=data)


def test_pieces_arrive_once_and_in_order(client, transcriber):
    rid = start(client)
    assert send(client, rid, 0, tone(1)).json()["next"] == 1
    assert send(client, rid, 0, tone(1)).json()["next"] == 1  # sent twice (a retry): kept once
    r = send(client, rid, 2, tone(1))
    assert r.status_code == 409 and r.json()["detail"]["next"] == 1  # piece 1 is missing: send it first
    assert send(client, rid, 1, tone(1)).json()["seconds"] == 2.0


def test_captions_follow_and_a_line_is_cut_at_a_quiet_moment(client, transcriber):
    transcriber.caption = lambda pcm: f"{len(pcm) / (2 * SECOND):.0f}s of speech"
    rid = start(client)
    audio = tone(8) + silence(0.3) + tone(4)  # a pause at 8 s
    for seq, i in enumerate(range(0, len(audio), 2 * SECOND)):
        send(client, rid, seq, audio[i:i + 2 * SECOND])
    state = wait_for(lambda: client.get(f"/api/recordings/{rid}/live").json(), lambda s: s["count"] >= 1)
    line = state["lines"][0]
    assert line["start"] == 0 and 8.0 <= line["end"] <= 8.3  # cut in the pause, not mid-word
    assert line["text"] == "8s of speech" and state["partial"]  # the rest is still provisional
    assert client.get(f"/api/recordings/{rid}/live?since=1").json()["lines"] == []


def test_captions_failing_doesnt_stop_the_recording(client, transcriber):
    def broken(pcm):
        raise RuntimeError("The speech worker didn't start within 90 s.")
    transcriber.caption = broken
    rid = start(client)
    send(client, rid, 0, tone(1))
    state = wait_for(lambda: client.get(f"/api/recordings/{rid}/live").json(), lambda s: s["captions_error"])
    assert "didn't start" in state["captions_error"]
    assert send(client, rid, 1, tone(1)).json()["seconds"] == 2.0  # the audio is still saved


def test_stop_makes_the_transcript_and_leaves_no_audio(client, llm, transcriber, tmp_path):
    course = a_course(client, llm)
    transcriber.segments = [{"start": 0.0, "end": 2.0, "text": "Welcome to the class."}]
    rid = start(client, course, kind="paper_session")
    send(client, rid, 0, tone(1))
    send(client, rid, 1, tone(1))
    assert client.post(f"/api/recordings/{rid}/stop").status_code == 202
    rec = client.get(f"/api/recordings/{rid}").json()
    assert (rec["status"], rec["kind"], rec["transcript"][0]["text"]) == ("done", "paper_session", "Welcome to the class.")
    assert transcriber.files[-1].suffix == ".wav"
    assert not list((tmp_path / "recording-audio").iterdir())  # ADR 0001
    assert send(client, rid, 2, tone(1)).status_code == 409  # stopped


def test_a_restart_mid_lecture_keeps_the_audio(client, tmp_path):
    rid = start(client)
    send(client, rid, 0, tone(1))
    client.app.state.live.pop(rid).stop.set()  # the server restarts
    recordings.recover(client.app.state.db, tmp_path / "recording-audio")
    assert (tmp_path / "recording-audio" / f"{rid}.pcm").exists()
    assert send(client, rid, 1, tone(1)).json()["seconds"] == 2.0  # the browser carries on


def test_start_suggests_the_class_on_now_or_a_replay_to_watch(client, llm):
    course = a_course(client, llm)
    assert client.get("/api/recordings/suggest").json()["course_id"] is None  # nothing on, nothing to watch
    client.post("/api/tasks", json={"title": "Watch the CS 259 recording", "course_id": course})
    s = client.get("/api/recordings/suggest").json()
    assert (s["course_id"], s["source"]) == (course, "device")  # a replay: the device's audio
    # the fake clock is Wed Sep 30, 10:00: a class on now, meeting on Zoom
    client.post("/api/events", json={"title": "CS 259 class", "course_id": course, "start": "2026-09-28T09:30",
                                     "end": "2026-09-28T11:00", "repeat": "MO,WE", "until": "2026-12-04",
                                     "location": "https://ucla.zoom.us/j/1"})
    s = client.get("/api/recordings/suggest").json()
    assert (s["course_id"], s["source"], s["why"]) == (course, "device", "CS 259 class is on now (online)")
