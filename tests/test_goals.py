import json
from datetime import datetime

from app.clock import LA


def at(clock, text):
    clock.set(datetime.fromisoformat(text).replace(tzinfo=LA))


def make(client, kind, **f):
    r = client.post(f"/api/{kind}", json=f)
    assert r.status_code == 201, r.text
    return r.json()


def step(task, hours=1, project=None):
    return json.dumps({"project": project or "", "task": task, "hours": hours})


def test_the_board_shows_goals_projects_progress_and_next_tasks(client):
    g = make(client, "goals", title="Get an ML research position", horizon="year")
    p = make(client, "projects", title="Reach out to professors", goal_id=g["id"])
    make(client, "tasks", title="Email Prof. Chen", project_id=p["id"], do_date="2026-10-02")
    make(client, "tasks", title="Email Prof. Lee", project_id=p["id"], do_date="2026-10-05")
    done = make(client, "tasks", title="Shortlist labs", project_id=p["id"])
    client.patch(f"/api/tasks/{done['id']}", json={"status": "done"})
    loose = make(client, "projects", title="CS 239 presentation")
    board = client.get("/api/board").json()
    (goal,) = board["goals"]
    (proj,) = goal["projects"]
    assert (proj["next"]["title"], proj["open"], proj["done"]) == ("Email Prof. Chen", 2, 1)
    assert [x["title"] for x in board["projects"]] == [loose["title"]]


def test_a_goal_with_nothing_to_do_gets_a_next_step_proposed(client, clock, llm):
    at(clock, "2026-09-30T10:00")
    g = make(client, "goals", title="Get an ML research position", why="PhD applications")
    p = make(client, "projects", title="Reach out to professors", goal_id=g["id"])
    llm.replies = [step("Email Prof. Chen about research", 1)]
    r = client.post("/api/goals/next-steps").json()
    assert r["proposed"] == 1
    (prop,) = client.get("/api/inbox").json()["proposals"]
    assert prop["summary"] == "Next step for “Get an ML research position”: Email Prof. Chen about research"
    data = prop["ops"][0]["data"]
    assert (data["project_id"], data["do_date"], data["estimate_min"]) == (p["id"], "2026-09-30", 60)
    # asking again doesn't pile up suggestions while one is waiting
    assert client.post("/api/goals/next-steps").json()["proposed"] == 0
    assert len(llm.requests) == 1


def test_a_goal_that_is_moving_is_left_alone(client, llm):
    g = make(client, "goals", title="Run a half marathon")
    p = make(client, "projects", title="Training", goal_id=g["id"])
    make(client, "tasks", title="5k run", project_id=p["id"])
    assert client.post("/api/goals/next-steps").json()["proposed"] == 0
    assert llm.requests == []


def test_when_a_goals_projects_are_finished_the_next_project_is_proposed(client, clock, llm):
    at(clock, "2026-09-30T10:00")
    g = make(client, "goals", title="Get an ML research position")
    p = make(client, "projects", title="Shortlist labs", goal_id=g["id"])
    t = make(client, "tasks", title="List 10 labs", project_id=p["id"])
    client.patch(f"/api/tasks/{t['id']}", json={"status": "done"})
    llm.replies = [step("Draft a cold email template", 1.5, project="Reach out to professors")]
    client.post("/api/goals/next-steps")
    (prop,) = client.get("/api/inbox").json()["proposals"]
    assert [(o["kind"], o["data"]["title"]) for o in prop["ops"]] == [("projects", "Reach out to professors"),
                                                                     ("tasks", "Draft a cold email template")]
    assert prop["ops"][0]["data"]["goal_id"] == g["id"] and prop["ops"][1]["data"]["project_id"] == "$0"
    assert "Shortlist labs" in llm.requests[0]["messages"][-1]["content"]  # what's already done informs the next step


def test_discussing_a_project_focuses_the_chat_on_it(client, llm):
    p = make(client, "projects", title="Present P10 in CS 239 · Kim", deadline="2026-11-05")
    make(client, "tasks", title="First read of P10", project_id=p["id"], do_date="2026-10-14")
    llm.replies = ["Let's look at it."]
    client.post("/api/chat", json={"text": "how is this going?", "focus": {"kind": "projects", "id": p["id"]}})
    system = llm.requests[0]["messages"][0]["content"]
    assert "Present P10 in CS 239 · Kim" in system and "First read of P10" in system and "focused on" in system


def test_long_chats_are_summarised_to_stay_within_context(client, llm):
    for i in range(40):
        client.app.state.db.execute("insert into chat_messages (role, text, created_at) values (?, ?, '2026-09-30T10:00')",
                                    ("user" if i % 2 == 0 else "assistant", f"message {i} " + "blah " * 100))
    llm.replies = ["They talked about many things; the first one mentioned a lab visit.", "Sure."]
    client.post("/api/chat", json={"text": "what did we say earlier?"})
    summary_req, reply_req = llm.requests[0], llm.requests[1]
    assert "message 0 " in summary_req["messages"][-1]["content"]
    sent = json.dumps(reply_req["messages"])
    assert "message 0 " not in sent and "lab visit" in sent and "message 39 " in sent
    llm.replies = ["Again."]
    client.post("/api/chat", json={"text": "and now?"})
    assert sum(r["messages"][0]["content"].startswith("Summarize") for r in llm.requests) == 1  # not re-summarised
