def source(client, title="CS 239 syllabus", text="Paper registration due Oct 5."):
    return client.post("/api/sources", json={"kind": "document", "title": title, "text": text}).json()


def propose(client, src, ops, quote="Paper registration due Oct 5.", **extra):
    r = client.post("/api/proposals", json={"source_id": src["id"], "summary": "x", "quote": quote, "ops": ops, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def create(kind, **data):
    return {"op": "create", "kind": kind, "data": data}


def inbox(client):
    return {**client.get("/api/inbox").json(), "questions": client.get("/api/questions").json()}


def test_accepting_a_proposal_applies_it_and_clears_it_from_the_inbox(client):
    src = source(client)
    p = propose(client, src, [create("deadlines", title="Paper registration", due="2026-10-05")])
    assert inbox(client)["count"] == 1
    assert inbox(client)["proposals"][0]["quote"] == "Paper registration due Oct 5."
    assert inbox(client)["proposals"][0]["source"]["title"] == "CS 239 syllabus"

    assert client.post(f"/api/proposals/{p['id']}/accept").status_code == 200
    assert [d["title"] for d in client.get("/api/deadlines").json()] == ["Paper registration"]
    assert inbox(client)["count"] == 0


def test_editing_before_accepting(client):
    p = propose(client, source(client), [create("tasks", title="Read paper", do_date="2026-10-12")])
    edited = [create("tasks", title="Read P10 closely", do_date="2026-10-13")]
    client.post(f"/api/proposals/{p['id']}/accept", json={"ops": edited})
    assert [(t["title"], t["do_date"]) for t in client.get("/api/tasks").json()] == [("Read P10 closely", "2026-10-13")]


def test_rejected_proposals_are_not_proposed_again(client):
    src = source(client)
    ops = [create("tasks", title="Buy textbook")]
    p = propose(client, src, ops)
    client.post(f"/api/proposals/{p['id']}/reject")
    assert inbox(client)["count"] == 0
    assert propose(client, src, ops)["suppressed"] is True


def test_an_identical_pending_proposal_is_not_duplicated(client):
    src = source(client)
    ops = [create("tasks", title="Buy textbook")]
    propose(client, src, ops)
    assert propose(client, src, ops)["suppressed"] is True
    assert inbox(client)["count"] == 1


def test_operations_in_one_proposal_can_reference_each_other(client):
    p = propose(client, source(client), [
        create("projects", title="P10 presentation", deadline="2026-11-05"),
        create("tasks", title="First read", project_id="$0", do_date="2026-10-13"),
    ])
    client.post(f"/api/proposals/{p['id']}/accept")
    project = client.get("/api/projects").json()[0]
    assert client.get("/api/tasks").json()[0]["project_id"] == project["id"]


def test_a_proposal_applies_all_or_nothing(client):
    p = propose(client, source(client), [
        create("tasks", title="Fine"),
        {"op": "update", "kind": "tasks", "id": 999, "data": {"title": "missing"}},
    ])
    assert client.post(f"/api/proposals/{p['id']}/accept").status_code == 409
    assert client.get("/api/tasks").json() == []
    assert inbox(client)["count"] == 1


def test_update_and_delete_operations(client):
    task = client.post("/api/tasks", json={"title": "Outline", "do_date": "2026-10-20"}).json()
    other = client.post("/api/tasks", json={"title": "Obsolete"}).json()
    p = propose(client, source(client), [
        {"op": "update", "kind": "tasks", "id": task["id"], "data": {"do_date": "2026-10-22"}},
        {"op": "delete", "kind": "tasks", "id": other["id"]},
    ])
    client.post(f"/api/proposals/{p['id']}/accept")
    assert [(t["title"], t["do_date"]) for t in client.get("/api/tasks").json()] == [("Outline", "2026-10-22")]


def test_accept_all_from_a_source_applies_in_order_with_cross_references(client):
    src = source(client)
    course = propose(client, src, [create("courses", number="CS 239", instructor="Robin Ding")])
    propose(client, src, [create("events", title="Lecture", start="2026-09-28T16:00", repeat="MO,WE",
                                 course_id=f"$p{course['id']}.0")])
    client.post(f"/api/sources/{src['id']}/accept-all")
    course_id = client.get("/api/courses").json()[0]["id"]
    assert client.get("/api/events").json()[0]["course_id"] == course_id
    assert inbox(client)["count"] == 0


def test_referencing_an_unaccepted_proposal_explains_what_to_accept_first(client):
    src = source(client)
    course = propose(client, src, [create("courses", number="CS 239", instructor="Miryung Kim")])
    course_row = inbox(client)["proposals"][0]
    event = propose(client, src, [create("events", title="Lecture", start="2026-09-29T14:00",
                                         course_id=f"$p{course['id']}.0")])
    r = client.post(f"/api/proposals/{event['id']}/accept")
    assert r.status_code == 409
    assert course_row["summary"] in r.json()["detail"]


def test_questions_block_their_proposals_until_answered(client):
    src = source(client, text="Each student presents one paper.")
    q = client.post("/api/questions", json={"source_id": src["id"], "text": "Which paper are you presenting in CS 239 · Kim?",
                                            "quote": "Each student presents one paper."}).json()
    p = propose(client, src, [create("tasks", title="Prepare presentation")], quote="Each student presents one paper.",
                question_id=q["id"])
    assert inbox(client)["count"] == 1  # questions are asked in chat, not counted here
    assert client.post(f"/api/proposals/{p['id']}/accept").status_code == 409

    client.post(f"/api/questions/{q['id']}/answer", json={"answer": "P10, on Nov 5"})
    box = inbox(client)
    assert box["questions"] == []
    assert client.get(f"/api/questions/{q['id']}").json()["answer"] == "P10, on Nov 5"
    assert client.post(f"/api/proposals/{p['id']}/accept").status_code == 200
