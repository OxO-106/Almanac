from datetime import datetime

from app.clock import LA


def at(clock, text):
    clock.set(datetime.fromisoformat(text).replace(tzinfo=LA))


def tick(client):
    return client.post("/api/scheduler/tick").json()


def notes(client):
    return client.get("/api/notifications", params={"after": 0}).json()


def test_the_briefing_is_built_at_9am_and_notified_once(client, clock):
    at(clock, "2026-09-30T08:59")
    tick(client)
    assert client.get("/api/briefing").json() is None
    at(clock, "2026-09-30T09:00")
    assert "briefing" in tick(client)["ran"]
    b = client.get("/api/briefing").json()
    assert b["date"] == "2026-09-30"
    (n,) = notes(client)
    assert n["kind"] == "briefing" and n["title"] == "Good morning: your Wed Sep 30"
    at(clock, "2026-09-30T09:30")
    assert tick(client)["ran"] == []
    assert len(notes(client)) == 1


def test_the_briefing_lists_today_what_is_carried_over_and_whats_coming(client, clock):
    at(clock, "2026-10-05T08:00")
    client.post("/api/tasks", json={"title": "Register paper", "do_date": "2026-10-05"})
    client.post("/api/tasks", json={"title": "Missed read", "do_date": "2026-10-02"})
    client.post("/api/events", json={"title": "CS 239 class", "start": "2026-09-28T16:00", "repeat": "MO,WE"})
    client.post("/api/deadlines", json={"title": "Team list", "due": "2026-10-07"})
    client.post("/api/deadlines", json={"title": "Far away", "due": "2026-10-20"})
    client.post("/api/questions", json={"text": "Which paper?"})
    at(clock, "2026-10-05T09:00")
    tick(client)
    b = client.get("/api/briefing").json()
    assert [t["title"] for t in b["today"]] == ["Register paper"]
    assert [t["title"] for t in b["carried_over"]] == ["Missed read"]
    assert [e["title"] for e in b["events"]] == ["CS 239 class"]
    assert [d["title"] for d in b["coming_up"]] == ["Team list"]
    assert b["questions"] == 1
    assert notes(client)[0]["body"] == "1 to do, 1 carried over, 1 event, 1 deadline in the next 3 days, 1 question waiting in Chat."


def test_a_pc_that_was_off_gets_one_briefing_and_no_burst_of_stale_notifications(client, clock):
    at(clock, "2026-09-30T09:00")
    tick(client)
    at(clock, "2026-10-02T11:30")  # off overnight twice; back on late in the morning
    assert "briefing" in tick(client)["ran"]
    assert client.get("/api/briefing").json()["date"] == "2026-10-02"
    assert len(notes(client)) == 1  # only Sep 30's; the late one isn't pushed


def test_starting_shortly_after_9_still_notifies(client, clock):
    at(clock, "2026-09-30T09:40")
    tick(client)
    assert len(notes(client)) == 1


def test_notifications_after_an_id_are_listed_for_each_device(client, clock):
    at(clock, "2026-09-30T09:00")
    tick(client)
    at(clock, "2026-10-01T09:00")
    tick(client)
    all_ = notes(client)
    assert [n["title"] for n in client.get("/api/notifications", params={"after": all_[0]["id"]}).json()] == \
        ["Good morning: your Thu Oct 1"]
