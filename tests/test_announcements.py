"""What the lecturer announces reaches the plan: updates, new items, questions when unclear."""
import json

from test_live_recording import send, tone, wait_for


def course(client):
    return client.post("/api/courses", json={"number": "CS 239", "instructor": "Miryung Kim"}).json()["id"]


def lecture_on(client, transcriber, llm, cid, day, said, announced):
    transcriber.segments = [{"start": 0.0, "end": 20.0, "text": said}]
    llm.announced = [json.dumps({"items": announced})]
    rid = client.post("/api/recordings/start", json={"course_id": cid, "date": day}).json()["id"]
    send(client, rid, 0, tone(1))
    client.post(f"/api/recordings/{rid}/stop")
    return wait_for(lambda: client.get(f"/api/recordings/{rid}").json(), lambda r: r["notes_status"] in ("done", "failed"))


def proposals(client):
    return client.get("/api/inbox").json()["proposals"]


def test_a_moved_deadline_updates_the_plan(client, llm, transcriber):
    cid = course(client)
    dl = client.post("/api/deadlines", json={"title": "Midterm report due", "due": "2026-11-11", "course_id": cid}).json()
    said = "One change: the midterm report is now due the 13th, not the 11th."
    lecture_on(client, transcriber, llm, cid, "2026-11-02", said, [
        # the model says October (it was a November lecture, and no month was said): the next 13th it is
        {"kind": "deadline", "title": "Midterm report due", "quote": "the midterm report is now due the 13th", "when": {"type": "date", "month": 10, "day": 13}, "clear": True}])
    (p,) = proposals(client)
    assert p["summary"] == "Update “Midterm report due”: 2026-11-11 → 2026-11-13 (said in the 2026-11-02 lecture)"
    assert p["ops"] == [{"op": "update", "kind": "deadlines", "id": dl["id"], "data": {"due": "2026-11-13"}}]
    assert p["quote"] == "the midterm report is now due the 13th"
    assert any(n["title"] == "From the lecture, for your plan" for n in client.get("/api/notifications").json())


def test_a_reading_for_a_class_is_due_the_day_before_it(client, llm, transcriber):
    cid = course(client)
    client.post("/api/events", json={"title": "CS 239 class", "course_id": cid, "start": "2026-09-28T10:00", "end": "2026-09-28T11:50",
                                     "repeat": "MO,WE", "until": "2026-12-04"})
    lecture_on(client, transcriber, llm, cid, "2026-10-07", "Please read the Mamba paper for next Monday.", [
        {"kind": "task", "title": "Read the Mamba paper", "quote": "read the Mamba paper for next Monday", "when": {"type": "weekday", "weekday": "MO", "next_week": True}, "clear": True}])
    (p,) = proposals(client)
    assert p["ops"][0]["data"] == {"title": "Read the Mamba paper", "due": "2026-10-11", "course_id": cid}  # Mon Oct 12's class


def test_an_unclear_date_is_asked_about_not_guessed(client, llm, transcriber):
    cid = course(client)
    said = "The proposal will be due the fourteenth or so, I'll confirm."
    lecture_on(client, transcriber, llm, cid, "2026-10-05", said, [
        {"kind": "deadline", "title": "Project proposal due", "quote": "The proposal will be due the fourteenth or so", "when": {"type": "unknown"}, "clear": False},
        {"kind": "deadline", "title": "Survey due", "quote": "the survey is due Friday", "when": {"type": "weekday", "weekday": "FR"}, "clear": True}])  # not said
    assert proposals(client) == []
    (q,) = client.get("/api/questions").json()
    assert q["text"] == "Prof. Kim said in the 2026-10-05 lecture: “The proposal will be due the fourteenth or so” When is “Project proposal due”?"
    assert q["purpose"] == "other"


def test_no_class_skips_that_day_of_the_weekly_class(client, llm, transcriber):
    cid = course(client)
    ev = client.post("/api/events", json={"title": "CS 239 class", "course_id": cid, "start": "2026-09-28T10:00", "end": "2026-09-28T11:50",
                                          "repeat": "MO,WE", "until": "2026-12-04"}).json()
    lecture_on(client, transcriber, llm, cid, "2026-10-05", "There's no class this Wednesday, I'm traveling.", [
        {"kind": "no_class", "title": "No class", "quote": "no class this Wednesday", "when": {"type": "weekday", "weekday": "WE"}, "clear": True}])
    (p,) = proposals(client)
    assert p["ops"] == [{"op": "update", "kind": "events", "id": ev["id"], "data": {"skip": "2026-10-07"}}]
