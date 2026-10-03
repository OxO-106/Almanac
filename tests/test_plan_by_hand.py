from datetime import datetime

from app.clock import LA


def at(client_clock, text):
    client_clock.set(datetime.fromisoformat(text).replace(tzinfo=LA))


def make(client, kind, **fields):
    r = client.post(f"/api/{kind}", json=fields)
    assert r.status_code == 201, r.text
    return r.json()


def test_goal_project_task_are_linked(client):
    goal = make(client, "goals", title="Get an ML research position", horizon="year", why="PhD applications")
    project = make(client, "projects", title="Reach out to professors", goal_id=goal["id"])
    task = make(client, "tasks", title="Email Prof. X", project_id=project["id"], do_date="2026-10-02")

    tasks = client.get("/api/tasks", params={"project_id": project["id"]}).json()
    assert [t["id"] for t in tasks] == [task["id"]]
    assert client.get(f"/api/projects/{project['id']}").json()["goal_id"] == goal["id"]


def test_task_keeps_due_date_do_date_work_kind_and_size(client):
    task = make(client, "tasks", title="First read of P10", due="2026-10-20", do_date="2026-10-13",
                work_kind="paper", size=14)
    got = client.get(f"/api/tasks/{task['id']}").json()
    assert (got["due"], got["do_date"], got["work_kind"], got["size"], got["status"]) == \
        ("2026-10-20", "2026-10-13", "paper", 14, "open")


def test_bad_dates_are_rejected(client):
    assert client.post("/api/tasks", json={"title": "x", "do_date": "next friday"}).status_code == 422


def test_course_needs_number_and_instructor(client):
    assert client.post("/api/courses", json={"number": "CS 239"}).status_code == 422
    ding = make(client, "courses", number="CS 239", instructor="Robin Ding")
    kim = make(client, "courses", number="CS 239", instructor="Miryung Kim")
    assert ding["id"] != kim["id"]


def test_edit_and_delete(client):
    task = make(client, "tasks", title="Draft outline")
    r = client.patch(f"/api/tasks/{task['id']}", json={"title": "Draft talk outline", "do_date": "2026-10-20"})
    assert r.json()["title"] == "Draft talk outline"
    assert client.delete(f"/api/tasks/{task['id']}").status_code == 204
    assert client.get(f"/api/tasks/{task['id']}").status_code == 404


def test_deleting_a_project_keeps_its_tasks(client):
    project = make(client, "projects", title="P10 presentation")
    task = make(client, "tasks", title="Read P10", project_id=project["id"])
    client.delete(f"/api/projects/{project['id']}")
    assert client.get(f"/api/tasks/{task['id']}").json()["project_id"] is None


def test_today_lists_do_dates_events_and_deadlines(client, clock):
    at(clock, "2026-10-05T09:00")  # a Monday
    course = make(client, "courses", number="CS 239", instructor="Robin Ding")
    make(client, "tasks", title="Register paper", do_date="2026-10-05")
    make(client, "tasks", title="Tomorrow's thing", do_date="2026-10-06")
    make(client, "events", title="CS 239 lecture", course_id=course["id"], start="2026-09-28T16:00",
         end="2026-09-28T17:50", repeat="MO,WE", until="2026-12-04")
    make(client, "deadlines", title="Paper registration", course_id=course["id"], due="2026-10-05")

    today = client.get("/api/today").json()
    assert today["date"] == "2026-10-05"
    assert [t["title"] for t in today["tasks"]] == ["Register paper"]
    assert [(e["title"], e["start"]) for e in today["events"]] == [("CS 239 lecture", "2026-10-05T16:00")]
    assert [d["title"] for d in today["deadlines"]] == ["Paper registration"]


def test_recurring_class_keeps_wall_clock_time_across_daylight_saving(client, clock):
    at(clock, "2026-11-02T09:00")  # the Monday after DST ends
    make(client, "events", title="Lecture", start="2026-09-28T16:00", end="2026-09-28T17:50", repeat="MO,WE")
    assert client.get("/api/today").json()["events"][0]["start"] == "2026-11-02T16:00"


def test_recurring_event_stops_after_until(client, clock):
    at(clock, "2026-12-07T09:00")
    make(client, "events", title="Lecture", start="2026-09-28T16:00", end="2026-09-28T17:50",
         repeat="MO,WE", until="2026-12-04")
    assert client.get("/api/today").json()["events"] == []


def test_ticking_a_task_done_removes_it_from_today(client, clock):
    at(clock, "2026-10-05T09:00")
    task = make(client, "tasks", title="Register paper", do_date="2026-10-05")
    at(clock, "2026-10-05T14:30")
    done = client.patch(f"/api/tasks/{task['id']}", json={"status": "done"}).json()
    assert done["done_at"] == "2026-10-05T14:30"
    today = client.get("/api/today").json()
    assert today["tasks"] == []
    assert [t["title"] for t in today["done"]] == ["Register paper"]


def test_open_tasks_from_earlier_days_show_as_overdue(client, clock):
    at(clock, "2026-10-07T09:00")
    make(client, "tasks", title="Missed read", do_date="2026-10-05")
    assert [t["title"] for t in client.get("/api/today").json()["overdue"]] == ["Missed read"]


def test_a_task_past_its_due_date_is_overdue_too(client, clock):
    at(clock, "2026-10-02T21:00")
    make(client, "tasks", title="Read P1. SWE-bench", due="2026-09-28")  # no day planned: its due date has passed
    make(client, "tasks", title="Read P3. Reflexion", due="2026-10-05")  # not yet
    make(client, "tasks", title="Read P2. ReAct", due="2026-09-30", do_date="2026-10-02")  # behind, but planned for today
    t = client.get("/api/today").json()
    assert [x["title"] for x in t["overdue"]] == ["Read P1. SWE-bench"]
    assert [x["title"] for x in t["tasks"]] == ["Read P2. ReAct"]


def test_a_deadline_can_be_done_early_and_undone(client, clock):
    at(clock, "2026-10-03T09:00")
    d = make(client, "deadlines", title="Paper Presentation Registration", due="2026-10-05")
    client.patch(f"/api/deadlines/{d['id']}", json={"done_at": "2026-10-03T09:05"})
    assert client.get(f"/api/deadlines/{d['id']}").json()["done_at"] == "2026-10-03T09:05"
    from app import note
    assert note.facts(client.app.state.db, clock.now().astimezone())["due"] == []  # not "due Monday" in the note any more
    client.patch(f"/api/deadlines/{d['id']}", json={"done_at": None})
    assert client.get(f"/api/deadlines/{d['id']}").json()["done_at"] is None
    con = client.app.state.db  # both changes are in the item's history (plan.change), like any edit
    assert [r["op"] for r in con.execute("select op from history where kind = 'deadlines' and item_id = ? order by id", (d["id"],))][-2:] == ["update", "update"]
