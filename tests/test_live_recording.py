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


def test_jottings_keep_their_moment_and_a_retry_isnt_added_twice(client):
    rid = start(client)
    j1 = client.post(f"/api/recordings/{rid}/jottings", json={"at": 63.4, "text": "important: KV cache", "key": "a"}).json()
    client.post(f"/api/recordings/{rid}/jottings", json={"at": 63.4, "text": "important: KV cache", "key": "a"})  # retried
    client.post(f"/api/recordings/{rid}/jottings", json={"at": 12, "text": "", "key": "b"})  # a Mark
    rec = client.get(f"/api/recordings/{rid}").json()  # what a reload sees
    assert [(j["at"], j["text"]) for j in rec["jottings"]] == [(12.0, ""), (63.4, "important: KV cache")]
    client.delete(f"/api/recordings/{rid}/jottings/{j1['id']}")
    assert [j["text"] for j in client.get(f"/api/recordings/{rid}").json()["jottings"]] == [""]
    assert client.post(f"/api/recordings/{rid}/jottings", json={"text": "no moment"}).status_code == 422


def notes(client):
    return [(n["title"], n["body"]) for n in client.get("/api/notifications").json()]


def test_it_stops_itself_after_quiet_and_trims_the_silence(client, transcriber, monkeypatch):
    monkeypatch.setattr(recordings, "QUIET_STOP", 5)  # 10 minutes in the app
    import wave
    heard = []
    original = transcriber.file
    transcriber.file = lambda path: (heard.append(wave.open(str(path)).getnframes() / SECOND), original(path))[1]
    transcriber.segments = [{"start": 0.0, "end": 3.0, "text": "And that's all for today."}]
    rid = start(client)
    for seq in range(3):
        send(client, rid, seq, tone(1))
    codes = [send(client, rid, seq, silence(1)).status_code for seq in range(3, 12)]
    assert codes[-1] == 409 and 200 in codes  # stopped once 5 s of silence had come
    rec = wait_for(lambda: client.get(f"/api/recordings/{rid}").json(), lambda r: r["status"] == "done")
    assert rec["transcript"][0]["text"] == "And that's all for today."
    assert heard == [8.0]  # 3 s of sound + 5 s; the rest of the silence trimmed
    assert any(t.startswith("Stopped recording") and "quiet" in b for t, b in notes(client))


def test_it_stops_when_audio_stops_coming_or_the_class_is_over(client, llm, clock, transcriber):
    course = a_course(client, llm)
    transcriber.segments = [{"start": 0.0, "end": 1.0, "text": "Hello."}]
    lost = start(client)
    send(client, lost, 0, tone(1))
    clock.advance(minutes=29)
    client.post("/api/scheduler/tick")
    assert client.get(f"/api/recordings/{lost}").json()["status"] == "recording"  # 29 min: maybe the Wi-Fi, keep waiting
    clock.advance(minutes=2)
    client.post("/api/scheduler/tick")
    wait_for(lambda: client.get(f"/api/recordings/{lost}").json(), lambda r: r["status"] == "done")
    assert any("no audio arrived for 30 minutes" in b for _, b in notes(client))
    # a class on now (the clock is 10:31 on a Wednesday): recording it stops 15 min after it ends at 11:00
    client.post("/api/events", json={"title": "CS 259 class", "course_id": course, "start": "2026-09-28T10:00",
                                     "end": "2026-09-28T11:00", "repeat": "MO,WE", "until": "2026-12-04"})
    rid = start(client, course)
    assert client.get(f"/api/recordings/{rid}").json()["ends_at"] == "2026-09-30T11:00"
    clock.advance(minutes=45)  # 11:16
    send(client, rid, 0, tone(1))  # audio is still coming in
    client.post("/api/scheduler/tick")
    wait_for(lambda: client.get(f"/api/recordings/{rid}").json(), lambda r: r["status"] == "done")
    assert any("the class ended 15 minutes ago" in b for _, b in notes(client))
