from datetime import datetime

from app.clock import LA

URL = "https://bruinlearn.ucla.edu/feeds/calendars/user_SECRETTOKEN123.ics"


def ics(*events):
    body = "".join(
        "BEGIN:VEVENT\r\n" + "".join(f"{k}:{v}\r\n" for k, v in e.items()) + "END:VEVENT\r\n" for e in events)
    return "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n" + body + "END:VCALENDAR\r\n"


TEAM = {"UID": "event-assignment-2053849", "DTSTART;VALUE=DATE;VALUE=DATE": "20261009",
        "SUMMARY": "Course Project Team List [26F-COM SCI-239-LEC-4]", "URL;VALUE=URI": "https://bruinlearn.ucla.edu/x"}
HW = {"UID": "event-assignment-777", "DTSTART": "20261010T065900Z", "DTEND": "20261010T065900Z",
      "SUMMARY": "Reading response 1 [26F-COM SCI-269-SEM-3]"}


class Feed:
    def __init__(self):
        self.text, self.status = ics(TEAM), 200

    def __call__(self, url):
        if self.status != 200:
            raise RuntimeError(f"HTTP {self.status}")
        return self.text


def connect(client, feed):
    client.app.state.fetch = feed
    r = client.put("/api/canvas", json={"url": URL})
    assert r.status_code == 200, r.text
    return client.post("/api/canvas/fetch").json()


def proposals(client):
    return client.get("/api/inbox").json()["proposals"]


def at(clock, text):
    clock.set(datetime.fromisoformat(text).replace(tzinfo=LA))


def test_assignments_become_deadline_proposals(client):
    feed = Feed()
    feed.text = ics(TEAM, HW)
    r = connect(client, feed)
    assert r["new"] == 2
    team, hw = proposals(client)
    assert team["ops"][0] == {"op": "create", "kind": "deadlines", "data": {"title": "Course Project Team List", "due": "2026-10-09"}}
    assert hw["ops"][0]["data"]["due"] == "2026-10-09T23:59"  # 06:59 UTC is 11:59pm in Los Angeles
    assert team["quote"] == "Course Project Team List [26F-COM SCI-239-LEC-4]"
    assert team["source"]["title"] == "Bruin Learn"


def test_the_link_is_kept_private(client):
    connect(client, Feed())
    shown = client.get("/api/canvas").json()
    assert "SECRETTOKEN" not in str(shown) and shown["connected"] is True and shown["status"] == "ok"


def test_a_section_with_one_matching_course_is_linked_to_it(client):
    ding = client.post("/api/courses", json={"number": "CS 239", "instructor": "Robin Ding"}).json()
    connect(client, Feed())
    assert proposals(client)[0]["ops"][0]["data"]["course_id"] == ding["id"]


def test_a_section_matching_two_courses_is_asked_about_once(client, llm):
    client.post("/api/courses", json={"number": "CS 239", "instructor": "Robin Ding"})
    kim = client.post("/api/courses", json={"number": "CS 239", "instructor": "Miryung Kim"}).json()
    connect(client, Feed())
    q = client.get("/api/chat").json()["current"]
    assert "Which of your courses is COM SCI 239 (LEC-4) on Bruin Learn: CS 239 · Ding or CS 239 · Kim?" in q["text"]
    assert proposals(client)[0]["blocked_by"]
    client.post("/api/chat", json={"text": "It's Kim's"})
    (p,) = proposals(client)
    assert p["ops"][0]["data"]["course_id"] == kim["id"] and not p["blocked_by"]
    # remembered: a new assignment for that section links straight away
    feed = client.app.state.fetch
    feed.text = ics(TEAM, {**TEAM, "UID": "event-assignment-9", "SUMMARY": "Phase 1 [26F-COM SCI-239-LEC-4]"})
    client.post("/api/canvas/fetch")
    assert proposals(client)[-1]["ops"][0]["data"]["course_id"] == kim["id"]


def test_a_waiting_item_gets_its_course_once_the_course_exists(client):
    connect(client, Feed())  # no courses yet: the syllabi come later
    ding = client.post("/api/courses", json={"number": "CS 239", "instructor": "Robin Ding"}).json()
    client.post("/api/canvas/fetch")
    assert proposals(client)[0]["ops"][0]["data"]["course_id"] == ding["id"]


def test_a_waiting_item_waits_on_the_question_when_its_course_is_ambiguous(client):
    connect(client, Feed())
    client.post("/api/courses", json={"number": "CS 239", "instructor": "Robin Ding"})
    client.post("/api/courses", json={"number": "CS 239", "instructor": "Miryung Kim"})
    client.post("/api/canvas/fetch")
    assert proposals(client)[0]["blocked_by"].startswith("Which of your courses is COM SCI 239 (LEC-4)")


def test_fetching_again_changes_nothing_unless_canvas_did(client):
    feed = Feed()
    connect(client, feed)
    client.post(f"/api/proposals/{proposals(client)[0]['id']}/accept")
    assert client.post("/api/canvas/fetch").json() == {"new": 0, "changed": 0, "removed": 0}
    feed.text = ics({**TEAM, "DTSTART;VALUE=DATE;VALUE=DATE": "20261012"})
    assert client.post("/api/canvas/fetch").json()["changed"] == 1
    (p,) = proposals(client)
    deadline = client.get("/api/deadlines").json()[0]
    assert p["ops"] == [{"op": "update", "kind": "deadlines", "id": deadline["id"], "data": {"due": "2026-10-12"}}]
    assert p["summary"] == "Bruin Learn moved “Course Project Team List”: Oct 9 → Oct 12"


def test_a_removed_assignment_is_proposed_for_removal(client):
    feed = Feed()
    connect(client, feed)
    client.post(f"/api/proposals/{proposals(client)[0]['id']}/accept")
    feed.text = ics()
    assert client.post("/api/canvas/fetch").json()["removed"] == 1
    (p,) = proposals(client)
    assert p["summary"] == "“Course Project Team List” was removed from Bruin Learn. Remove it?" and p["ops"][0]["op"] == "delete"


def test_an_assignment_the_syllabus_already_added_is_linked_not_duplicated(client):
    ding = client.post("/api/courses", json={"number": "CS 239", "instructor": "Robin Ding"}).json()
    client.post("/api/deadlines", json={"title": "Project Team List", "due": "2026-10-09", "course_id": ding["id"]})
    assert connect(client, Feed())["new"] == 0
    assert proposals(client) == []


def test_a_broken_link_is_reported_once(client):
    feed = Feed()
    connect(client, feed)
    feed.status = 404
    client.post("/api/canvas/fetch")
    client.post("/api/canvas/fetch")
    assert client.get("/api/canvas").json()["status"] == "error"
    notes = [n for n in client.get("/api/notifications").json() if n["kind"] == "canvas"]
    assert [n["title"] for n in notes] == ["Your Bruin Learn feed stopped working"]


def test_the_feed_is_checked_every_three_hours(client, clock):
    at(clock, "2026-10-01T08:00")
    feed = Feed()
    connect(client, feed)
    client.post("/api/scheduler/tick")
    feed.text = ics(TEAM, HW)
    at(clock, "2026-10-01T09:00")
    assert "canvas" in client.post("/api/scheduler/tick").json()["ran"]
    assert len(proposals(client)) == 2
