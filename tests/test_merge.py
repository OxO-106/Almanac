import json

from test_canvas import Feed, connect, ics, TEAM
from test_upload import SYLLABUS, course_reply, item, items_reply, upload


def proposals(client):
    return client.get("/api/inbox").json()["proposals"]


TEAM_ITEM = item(title="Project Team List", quote="register using the paper presentation sign-up sheet by October 5",
                 when={"type": "date", "month": 10, "day": 5})  # (the test syllabus only has Oct 5 to quote)


def test_a_syllabus_fills_in_the_course_of_an_item_you_already_have(client, llm):
    d = client.post("/api/deadlines", json={"title": "Course Project Team List", "due": "2026-10-05"}).json()
    ding = client.post("/api/courses", json={"number": "CS 239", "instructor": "Robin Ding"}).json()
    llm.replies = [course_reply(), items_reply(TEAM_ITEM)]
    upload(client, "cs239.txt", SYLLABUS.encode())
    (p,) = proposals(client)
    assert p["ops"] == [{"op": "update", "kind": "deadlines", "id": d["id"], "data": {"course_id": ding["id"]}}]
    assert p["summary"] == "Add details to “Course Project Team List”: course"


def test_nothing_is_proposed_when_the_item_already_has_everything(client, llm):
    ding = client.post("/api/courses", json={"number": "CS 239", "instructor": "Robin Ding"}).json()
    client.post("/api/deadlines", json={"title": "Paper registration", "due": "2026-10-05", "course_id": ding["id"]})
    llm.replies = [course_reply(), items_reply(item())]
    upload(client, "cs239.txt", SYLLABUS.encode())
    assert proposals(client) == []


def test_a_waiting_proposal_absorbs_the_details_instead_of_a_duplicate(client, llm):
    feed = Feed()
    feed.text = ics({**TEAM, "DTSTART;VALUE=DATE;VALUE=DATE": "20261005"})
    connect(client, feed)  # Bruin Learn's item is waiting in the Inbox, no course yet
    ding = client.post("/api/courses", json={"number": "CS 239", "instructor": "Robin Ding"}).json()
    llm.replies = [course_reply(), items_reply(TEAM_ITEM)]
    upload(client, "cs239.txt", SYLLABUS.encode())
    (p,) = proposals(client)
    assert p["source"]["title"] == "Bruin Learn" and p["ops"][0]["data"]["course_id"] == ding["id"]


def test_an_accepted_canvas_item_gets_its_course_once_known(client):
    connect(client, Feed())
    client.post(f"/api/proposals/{proposals(client)[0]['id']}/accept")
    ding = client.post("/api/courses", json={"number": "CS 239", "instructor": "Robin Ding"}).json()
    client.post("/api/canvas/fetch")
    (p,) = proposals(client)
    d = client.get("/api/deadlines").json()[0]
    assert p["ops"] == [{"op": "update", "kind": "deadlines", "id": d["id"], "data": {"course_id": ding["id"]}}]
    assert p["summary"] == "Add details to “Course Project Team List”: course"


def test_the_matching_project_in_the_course_is_linked_too(client):
    ding = client.post("/api/courses", json={"number": "CS 239", "instructor": "Robin Ding"}).json()
    proj = client.post("/api/projects", json={"title": "Course project", "course_id": ding["id"]}).json()
    client.post("/api/projects", json={"title": "Paper presentation", "course_id": ding["id"]})
    connect(client, Feed())
    (p,) = proposals(client)
    assert p["ops"][0]["data"] == {"title": "Course Project Team List", "due": "2026-10-09",
                                   "course_id": ding["id"], "project_id": proj["id"]}


def test_chat_can_add_the_course_to_an_existing_item(client, llm):
    d = client.post("/api/deadlines", json={"title": "Course Project Team List", "due": "2026-10-09"}).json()
    client.post("/api/courses", json={"number": "CS 239", "instructor": "Miryung Kim"})
    ding = client.post("/api/courses", json={"number": "CS 239", "instructor": "Robin Ding"}).json()
    llm.replies = ["Got it.", json.dumps({"actions": [{
        "type": "deadline", "title": "Course Project Team List", "quote": "the team list due Oct 9 is for Ding's CS 239",
        "when": {"type": "date", "month": 10, "day": 9}, "course": "Ding's CS 239"}]})]
    client.post("/api/chat", json={"text": "the team list due Oct 9 is for Ding's CS 239"})
    (p,) = proposals(client)
    assert p["ops"] == [{"op": "update", "kind": "deadlines", "id": d["id"], "data": {"course_id": ding["id"]}}]


def test_chat_without_a_date_still_finds_the_one_matching_item(client, llm):
    d = client.post("/api/deadlines", json={"title": "Course Project Team List", "due": "2026-10-09"}).json()
    ding = client.post("/api/courses", json={"number": "CS 239", "instructor": "Robin Ding"}).json()
    llm.replies = ["Got it.", json.dumps({"actions": [{
        "type": "deadline", "title": "Course Project Team List", "quote": "the team list deadline is for Ding's CS 239",
        "when": {"type": "unknown"}, "course": "Ding's CS 239"}]})]
    client.post("/api/chat", json={"text": "the team list deadline is for Ding's CS 239"})
    (p,) = proposals(client)
    assert p["ops"] == [{"op": "update", "kind": "deadlines", "id": d["id"], "data": {"course_id": ding["id"]}}]
