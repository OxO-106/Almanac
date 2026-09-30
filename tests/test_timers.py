import json
from datetime import datetime

from app.clock import LA


def at(clock, text):
    clock.set(datetime.fromisoformat(text).replace(tzinfo=LA))


def task(client, **f):
    return client.post("/api/tasks", json=f).json()


def start(client, t):
    return client.post(f"/api/tasks/{t['id']}/timer/start").json()


def stop(client):
    return client.post("/api/timer/stop").json()


def test_a_timer_records_how_long_a_task_took(client, clock):
    t = task(client, title="First read of P10", work_kind="paper", size=14)
    at(clock, "2026-10-14T19:00")
    start(client, t)
    at(clock, "2026-10-14T19:50")
    assert client.get("/api/timer").json()["elapsed_min"] == 50
    assert stop(client)["minutes"] == 50
    assert client.get("/api/timer").json() is None
    assert client.get(f"/api/tasks/{t['id']}").json()["spent_min"] == 50


def test_only_one_timer_runs_at_a_time(client, clock):
    a, b = task(client, title="A"), task(client, title="B")
    at(clock, "2026-10-14T19:00")
    start(client, a)
    at(clock, "2026-10-14T19:30")
    start(client, b)
    assert client.get("/api/timer").json()["task"]["title"] == "B"
    assert client.get(f"/api/tasks/{a['id']}").json()["spent_min"] == 30


def test_after_two_hours_it_asks_and_caps_a_forgotten_timer(client, clock):
    t = task(client, title="Make the slides")
    at(clock, "2026-10-14T10:00")
    client.post("/api/scheduler/tick")
    start(client, t)
    at(clock, "2026-10-14T11:59")
    client.post("/api/scheduler/tick")
    assert not [n for n in client.get("/api/notifications").json() if n["kind"] == "timer"]
    at(clock, "2026-10-14T12:00")
    client.post("/api/scheduler/tick")
    (n,) = [n for n in client.get("/api/notifications").json() if n["kind"] == "timer"]
    assert n["title"] == "Still working on “Make the slides”?"
    assert client.get("/api/timer").json()["asking"] is True
    at(clock, "2026-10-14T12:15")
    client.post("/api/scheduler/tick")
    assert client.get("/api/timer").json() is None
    assert client.get(f"/api/tasks/{t['id']}").json()["spent_min"] == 120


def test_keep_going_resets_the_two_hours(client, clock):
    t = task(client, title="Make the slides")
    at(clock, "2026-10-14T10:00")
    start(client, t)
    at(clock, "2026-10-14T12:00")
    client.post("/api/scheduler/tick")
    client.post("/api/timer/keep")
    at(clock, "2026-10-14T12:30")
    client.post("/api/scheduler/tick")
    assert client.get("/api/timer").json()["asking"] is False
    assert client.get("/api/timer").json()["elapsed_min"] == 150


def timed_papers(client, clock, pairs):
    for i, (pages, minutes) in enumerate(pairs):
        t = task(client, title=f"Read paper {i}", work_kind="paper", size=pages)
        at(clock, "2026-10-14T10:00")
        start(client, t)
        at(clock, f"2026-10-14T{10 + minutes // 60:02d}:{minutes % 60:02d}")
        stop(client)
        client.patch(f"/api/tasks/{t['id']}", json={"status": "done"})


def test_estimates_switch_to_your_own_pace_after_three_timed_tasks(client, clock):
    timed_papers(client, clock, [(10, 60), (20, 90)])
    assert client.get("/api/estimates").json()["paper"] == {"unit": "page", "tasks": 2, "minutes_per_unit": None}
    assert client.get("/api/inbox").json()["count"] == 0
    timed_papers(client, clock, [(30, 150)])  # 6, 4.5 and 5 minutes a page
    assert client.get("/api/estimates").json()["paper"] == {"unit": "page", "tasks": 3, "minutes_per_unit": 5}
    (p,) = client.get("/api/inbox").json()["proposals"]
    assert p["ops"][0]["data"] == {"text": "Reading a paper takes you about 5 minutes a page (from 3 timed tasks).",
                                   "topic": "pace"}


def test_the_planner_uses_your_pace_when_the_size_is_known(client, clock, llm):
    timed_papers(client, clock, [(10, 60), (20, 90), (30, 150)])
    at(clock, "2026-09-30T10:00")
    p = client.post("/api/projects", json={"title": "Present P10", "deadline": "2026-11-05", "notes": "The paper is 14 pages"}).json()
    llm.replies = [json.dumps({"milestones": [{"title": "First read", "work_kind": "paper", "size": 14, "unit": "pages", "hours": 2}]})]
    r = client.post(f"/api/projects/{p['id']}/plan", json={}).json()
    assert r["proposal"]["ops"][0]["data"]["estimate_min"] == 70  # 14 pages × 5 min, not the model's 2h


def test_the_planner_asks_for_a_page_count_it_was_not_told(client, clock, llm):
    at(clock, "2026-09-30T10:00")
    p = client.post("/api/projects", json={"title": "Present P10", "deadline": "2026-11-05"}).json()
    llm.replies = [json.dumps({"milestones": [{"title": "First read", "work_kind": "paper", "size": 14, "unit": "pages", "hours": 2}]})]
    r = client.post(f"/api/projects/{p['id']}/plan", json={}).json()
    assert "size" not in r["proposal"]["ops"][0]["data"]  # the model's 14 was a guess
    assert [q["text"] for q in client.get("/api/questions").json()] == ["How many pages is the paper for “Present P10”?"]
