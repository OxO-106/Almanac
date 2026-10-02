"""Lecture notes: built on the Jottings, shaped by the Lecture kind, every Jotting kept."""
from test_lecture_kinds import ding
from test_live_recording import send, start, tone, wait_for


def lecture(client, transcriber, segments, course=None, kind=None, jots=()):
    transcriber.segments = segments
    rid = start(client, course, **({"kind": kind} if kind else {}))
    send(client, rid, 0, tone(1))
    for at, text in jots:
        client.post(f"/api/recordings/{rid}/jottings", json={"at": at, "text": text})
    client.post(f"/api/recordings/{rid}/stop")
    return wait_for(lambda: client.get(f"/api/recordings/{rid}").json(), lambda r: r["notes_status"] in ("done", "failed"))


def test_notes_are_built_on_the_jottings_and_keep_every_one(client, llm, transcriber):
    llm.notes = ["## Grouped-query attention\n✎ KV cache!! \n- Keys and values are shared across groups of heads.\n\n## Announced\n- Nothing announced."]
    rec = lecture(client, transcriber, [{"start": 0.0, "end": 30.0, "text": "Grouped-query attention shares keys and values across groups."},
                                        {"start": 30.0, "end": 60.0, "text": "That shrinks the KV cache a lot."}],
                  jots=[(31, "KV cache!!"), (45, "ask about MQA vs GQA")])
    assert rec["notes_status"] == "done"
    assert rec["notes"].startswith("## Grouped-query attention\n✎ KV cache!!")
    # the one the model dropped goes above the point about what was said at 0:45
    assert "✎ ask about MQA vs GQA\n- Keys and values are shared across groups of heads." in rec["notes"]
    (req,) = llm.notes_requests
    sent = req["messages"][1]["content"]
    assert "[0:31] KV cache!!" in sent and "[0:30] That shrinks the KV cache a lot." in sent
    assert "## Announced" in req["messages"][0]["content"]


def test_a_long_lecture_is_written_in_parts_then_combined(client, llm, transcriber):
    segments = [{"start": m * 60.0, "end": m * 60.0 + 60, "text": f"Minute {m} of the lecture."} for m in range(90)]
    llm.notes = ["part one notes", "part two notes", "part three notes", "## Combined\n✎ remember this"]
    rec = lecture(client, transcriber, segments, jots=[(2700, "remember this"), (5100, "")])
    assert len(llm.notes_requests) == 4  # parts of 40, 40 and 10 minutes, then combining them
    part2 = llm.notes_requests[1]["messages"][1]["content"]
    assert "[45:00] remember this" in part2 and "(marked)" not in part2
    assert "[40:00] Minute 40" in part2 and "[39:00]" not in part2  # part 2 is 40:00-80:00
    assert "[85:00] (marked)" in llm.notes_requests[2]["messages"][1]["content"]
    combine = llm.notes_requests[3]["messages"][1]["content"]
    assert "--- Notes, part 1 ---\npart one notes" in combine and "--- Notes, part 3 ---\npart three notes" in combine
    assert rec["notes"] == "## Combined\n✎ remember this\n\n## More of your jottings\n✎ (marked) (85:00)"  # no point to put the mark on


def test_a_paper_session_knows_its_papers_and_the_reading_list(client, llm, transcriber):
    c = ding(client, llm)
    transcriber.segments = [{"start": 0.0, "end": 9.0, "text": "Today's paper is GQA."}]
    rid = client.post("/api/recordings/start", json={"course_id": c, "date": "2026-10-05"}).json()["id"]
    send(client, rid, 0, tone(1))
    client.post(f"/api/recordings/{rid}/stop")
    wait_for(lambda: client.get(f"/api/recordings/{rid}").json(), lambda r: r["notes_status"] == "done")
    system, user = (m["content"] for m in llm.notes_requests[-1]["messages"])
    assert "paper session" in system and '"Almanac: "' in system
    assert "Papers for this lecture on the reading list: GQA: Training Generalized Multi-Query Transformer" in user
    assert "Course: CS 239" in user and "Robin Ding" in user


def test_notes_that_fail_can_be_written_again(client, llm, transcriber):
    def fail(*a, **k):
        raise TimeoutError("the model didn't answer in time")
    real = llm.chat
    llm.chat = lambda messages, schema=None, **kw: fail() if messages[0]["content"].startswith("You write study notes") else real(messages, schema, **kw)
    rec = lecture(client, transcriber, [{"start": 0.0, "end": 5.0, "text": "Hello."}])
    assert rec["notes_status"] == "failed" and "didn't answer" in rec["notes_error"] and rec["transcript"]
    llm.chat = real
    llm.notes = ["## Hello\n- A greeting."]
    client.post(f"/api/recordings/{rec['id']}/notes/retry")
    assert client.get(f"/api/recordings/{rec['id']}").json()["notes"] == "## Hello\n- A greeting."


def test_only_the_students_jottings_are_marked_as_theirs():
    from app.lecture_notes import _keep_jottings
    notes = "## Logistics\n✎ office hours per request\n  - By request.\n✎ [12:43] Mokir got the Nobel Prize for replacing a technology\n✎ (marked)\n  - The Turing Award."
    out = _keep_jottings(notes, [{"at": 115, "text": "office hours per request"}, {"at": 170, "text": ""}])
    assert out == "## Logistics\n✎ office hours per request\n  - By request.\n- [12:43] Mokir got the Nobel Prize for replacing a technology\n✎ (marked)\n  - The Turing Award."


def test_the_models_guesses_about_meaning_are_taken_out(client, llm, transcriber):
    llm.notes = ['## Patents\n- Apple\'s patent for "penny-free climbs" (likely referring to touch interfaces) is an example.']
    rec = lecture(client, transcriber, [{"start": 0.0, "end": 9.0, "text": "Apple patent for penny-free climbs."}])
    assert rec["notes"] == '## Patents\n- Apple\'s patent for "penny-free climbs" is an example.'
