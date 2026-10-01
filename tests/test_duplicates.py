"""One duplicate rule, used by every reader and by the check of the plan."""
from app import merge


def test_the_rule():
    s = merge.same
    assert s("deadlines", {"title": "Paper registration", "due": "2026-10-05"}, "deadlines", {"title": "Register your paper", "due": "2026-10-05"})
    assert not s("deadlines", {"title": "Paper registration", "due": "2026-10-05"}, "deadlines", {"title": "Paper registration", "due": "2026-10-06"})
    # a date inside the other's week
    assert s("events", {"title": "Midterm assessment", "start": "2026-10-26", "window": "2026-10-26/2026-10-30"},
             "events", {"title": "Midterm assessment", "start": "2026-10-28"})
    # a session and what's due at it
    assert s("events", {"title": "Mid-Project Check-in: Phase 1 Due", "start": "2026-10-29"},
             "deadlines", {"title": "Submit Phase 1 deliverables", "due": "2026-10-29"})
    # but not a session and an unrelated deadline that day, nor different courses
    assert not s("events", {"title": "Guest lecture", "start": "2026-09-30"}, "deadlines", {"title": "Guest lecture notes", "due": "2026-09-30"})
    assert not s("deadlines", {"title": "Final report", "due": "2026-12-02", "course_id": 1},
                 "deadlines", {"title": "Final report", "due": "2026-12-02", "course_id": 2})
    # a weekly class is not a one-off on one of its days
    assert not s("events", {"title": "CS 239 class", "start": "2026-09-28T16:00", "repeat": "MO,WE"},
                 "events", {"title": "CS 239 class", "start": "2026-09-28T16:00"})


def test_bruin_learn_or_chat_adding_a_due_item_fills_in_the_session_instead(client):
    client.post("/api/events", json={"title": "Mid-Project Check-in: Phase 1 Due", "start": "2026-10-29", "course_id": None})
    con, clock = client.app.state.db, client.app.state.clock
    assert merge.propose_or_fill(con, clock, None, "deadlines", {"title": "Submit Phase 1 deliverables", "due": "2026-10-29T23:59"}) is not None
    (p,) = client.get("/api/inbox").json()["proposals"]
    assert p["ops"][0]["op"] == "update" and p["ops"][0]["kind"] == "events"  # details for the session, not a second item


def test_duplicates_already_in_the_plan_are_offered_for_merging(client):
    ev = client.post("/api/events", json={"title": "Mid-Project Check-in: Phase 1 Due", "start": "2026-10-29"}).json()
    dl = client.post("/api/deadlines", json={"title": "Submit Phase 1 deliverables", "due": "2026-10-29"}).json()
    client.post("/api/deadlines", json={"title": "Proposal one-pager", "due": "2026-10-21"})
    assert merge.offer_duplicates(client.app.state.db, client.app.state.clock) == 1
    (p,) = client.get("/api/inbox").json()["proposals"]
    assert p["summary"] == "Same thing twice: keep “Mid-Project Check-in: Phase 1 Due”, remove “Submit Phase 1 deliverables”"
    assert p["ops"] == [{"op": "delete", "kind": "deadlines", "id": dl["id"]}]
    assert merge.offer_duplicates(client.app.state.db, client.app.state.clock) == 0  # not offered twice
