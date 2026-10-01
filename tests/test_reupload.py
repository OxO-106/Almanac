import json

from test_upload import SYLLABUS, course_reply, inbox, item, items_reply, upload

REG = item(title="Paper registration")
MIDTERM = item(title="Midterm report", quote="Wed Nov 11 No class Midterm report due", when={"type": "date", "month": 11, "day": 11})


def accept_all(client):
    for src in client.get("/api/sources").json():
        client.post(f"/api/sources/{src['id']}/accept-all")


def summaries(client):
    return [p["summary"] for p in inbox(client)["proposals"]]


def test_a_known_course_number_with_a_different_instructor_is_asked_about(client, llm):
    client.post("/api/courses", json={"number": "CS 239", "instructor": "Robin Ding"})
    llm.replies = [course_reply([{"number": "CS 239", "instructor": "Miryung Kim", "quote": "Instructor: Miryung Kim", "meetings": []}]),
                   items_reply()]
    upload(client, "kim.txt", SYLLABUS.replace("Robin Ding", "Miryung Kim").encode())
    (course,) = inbox(client)["proposals"]
    assert course["blocked_by"] == ("You already have CS 239 · Robin Ding. Is CS 239 · Miryung Kim a different course? "
                                    "If it's the same one, reject this and correct the instructor instead.")


def test_reuploading_an_unchanged_syllabus_proposes_nothing(client, llm):
    llm.replies = [course_reply(), items_reply(REG, MIDTERM)]
    upload(client, "cs239.txt", SYLLABUS.encode())
    accept_all(client)
    llm.replies = [course_reply(), items_reply(REG, MIDTERM)]
    upload(client, "cs239 (1).txt", SYLLABUS.encode())
    assert inbox(client)["count"] == 0


def test_a_changed_date_becomes_an_update_of_just_that_field(client, llm):
    llm.replies = [course_reply(), items_reply(REG, MIDTERM)]
    upload(client, "cs239.txt", SYLLABUS.encode())
    accept_all(client)
    moved = SYLLABUS.replace("by October 5", "by October 7")
    llm.replies = [course_reply(), items_reply(item(title="Paper registration", quote="sign-up sheet by October 7",
                                                    when={"type": "date", "month": 10, "day": 7}), MIDTERM)]
    upload(client, "cs239.txt", moved.encode())
    (p,) = inbox(client)["proposals"]
    reg = next(d for d in client.get("/api/deadlines").json() if d["title"] == "Paper registration")
    assert p["ops"] == [{"op": "update", "kind": "deadlines", "id": reg["id"], "data": {"due": "2026-10-07"}}]
    assert p["summary"] == "Update “Paper registration”: due 2026-10-05 → 2026-10-07"


def test_items_missing_from_the_new_version_are_proposed_for_removal(client, llm):
    llm.replies = [course_reply(), items_reply(REG, MIDTERM)]
    upload(client, "cs239.txt", SYLLABUS.encode())
    accept_all(client)
    llm.replies = [course_reply(), items_reply(REG)]
    upload(client, "cs239.txt", SYLLABUS.encode())
    (p,) = inbox(client)["proposals"]
    assert p["summary"] == "Remove “Midterm report”? It's not in the new version of cs239.txt."
    assert p["ops"][0]["op"] == "delete"


def test_new_items_in_the_new_version_are_proposed(client, llm):
    llm.replies = [course_reply(), items_reply(REG)]
    upload(client, "cs239.txt", SYLLABUS.encode())
    accept_all(client)
    llm.replies = [course_reply(), items_reply(REG, MIDTERM)]
    upload(client, "cs239.txt", SYLLABUS.encode())
    assert summaries(client) == ["Midterm report"]


def test_a_new_version_withdraws_the_old_versions_pending_proposals(client, llm):
    llm.replies = [course_reply(), items_reply(REG)]
    upload(client, "cs239.txt", SYLLABUS.encode())
    llm.replies = [course_reply(), items_reply(REG, MIDTERM)]
    upload(client, "cs239.txt", SYLLABUS.encode())
    assert summaries(client) == ["Add course CS 239 · Robin Ding", "Paper registration", "Midterm report"]
    assert len(client.get("/api/sources").json()) == 1  # the old version is replaced in the list


def test_a_new_version_can_be_named_explicitly(client, llm):
    llm.replies = [course_reply(), items_reply(REG)]
    first = upload(client, "cs239.txt", SYLLABUS.encode())
    accept_all(client)
    llm.replies = [course_reply(), items_reply(REG)]
    r = client.post(f"/api/uploads?replaces={first['id']}", files={"file": ("CS239 schedule v2.txt", SYLLABUS.encode(), "text/plain")})
    assert r.status_code == 202
    assert inbox(client)["count"] == 0
