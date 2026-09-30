from datetime import datetime

from app.clock import LA


def at(clock, text):
    clock.set(datetime.fromisoformat(text).replace(tzinfo=LA))


def tick(client):
    return client.post("/api/scheduler/tick").json()["ran"]


def make(client, kind, **f):
    return client.post(f"/api/{kind}", json=f).json()


def week_of_work(client, clock):
    g = make(client, "goals", title="Get an ML research position")
    make(client, "goals", title="Run a half marathon")
    p = make(client, "projects", title="Reach out to professors", goal_id=g["id"])
    a = make(client, "tasks", title="Email Prof. Chen", project_id=p["id"], do_date="2026-09-30")
    make(client, "tasks", title="Email Prof. Lee", project_id=p["id"], do_date="2026-10-01")  # never done: slipped
    make(client, "tasks", title="Next week thing", do_date="2026-10-06")
    make(client, "deadlines", title="Team list", due="2026-10-09")
    at(clock, "2026-09-30T10:00")
    client.post(f"/api/tasks/{a['id']}/timer/start")
    at(clock, "2026-09-30T11:30")
    client.post("/api/timer/stop")
    client.patch(f"/api/tasks/{a['id']}", json={"status": "done"})


def test_the_weekly_overview_arrives_sunday_at_8pm(client, clock, llm):
    week_of_work(client, clock)
    at(clock, "2026-10-04T19:59")
    tick(client)
    llm.replies = ["A focused start: one professor emailed, one still waiting."]
    at(clock, "2026-10-04T20:00")
    assert "weekly" in tick(client)
    (o,) = client.get("/api/overviews").json()
    assert (o["kind"], o["period_start"], o["period_end"]) == ("weekly", "2026-09-28", "2026-10-04")
    d = client.get(f"/api/overviews/{o['id']}").json()
    assert d["hours"] == [{"name": "Get an ML research position", "hours": 1.5}]
    assert [t["title"] for t in d["completed"]] == ["Email Prof. Chen"]
    assert [t["title"] for t in d["slipped"]] == ["Email Prof. Lee"]
    assert [x["title"] for x in d["next"]] == ["Next week thing", "Team list"]
    assert d["stalled_goals"] == ["Run a half marathon"]
    assert d["assessment"] == "A focused start: one professor emailed, one still waiting."
    assert "1.5h" in llm.requests[-1]["messages"][-1]["content"]  # the model sees the numbers, not raw data to invent from
    (n,) = [n for n in client.get("/api/notifications").json() if n["kind"] == "overview"]
    assert n["title"] == "Your week in review (Sep 28 – Oct 4)" and n["url"] == f"#archive/{o['id']}"


def test_a_sunday_month_end_gets_two_separate_overviews(client, clock, llm):
    at(clock, "2027-01-31T19:00")  # a Sunday and the last day of January
    tick(client)
    llm.replies = ["Quiet week.", "Quiet month."]
    at(clock, "2027-01-31T20:30")
    tick(client)
    kinds = sorted((o["kind"], o["period_start"]) for o in client.get("/api/overviews").json())
    assert kinds == [("monthly", "2027-01-01"), ("weekly", "2027-01-25")]


def test_the_monthly_overview_shows_progress_per_goal(client, clock, llm):
    week_of_work(client, clock)
    at(clock, "2026-10-31T20:00")
    tick(client)
    llm.replies = ["October moved one goal forward."]
    at(clock, "2026-10-31T20:30")
    tick(client)
    (o,) = [o for o in client.get("/api/overviews").json() if o["kind"] == "monthly"]
    d = client.get(f"/api/overviews/{o['id']}").json()
    assert {g["goal"]: (g["done"], g["total"]) for g in d["goals"]} == {"Get an ML research position": (1, 2),
                                                                     "Run a half marathon": (0, 0)}


def test_the_quarterly_overview_records_what_was_done_by_goal(client, clock, llm):
    week_of_work(client, clock)
    at(clock, "2026-12-11T20:00")
    tick(client)
    llm.replies = ["A solid quarter."]
    at(clock, "2026-12-11T21:00")
    tick(client)
    (o,) = [o for o in client.get("/api/overviews").json() if o["kind"] == "quarterly"]
    assert (o["period_start"], o["period_end"]) == ("2026-09-21", "2026-12-11")
    d = client.get(f"/api/overviews/{o['id']}").json()
    assert d["record"] == [{"goal": "Get an ML research position", "done": ["Email Prof. Chen"]}]


def test_a_missed_overview_is_still_built_and_mentioned_in_the_briefing(client, clock, llm):
    at(clock, "2026-10-04T19:00")
    tick(client)
    llm.replies = ["Quiet week."]
    at(clock, "2026-10-05T09:10")  # PC off Sunday evening
    tick(client)
    assert [o["kind"] for o in client.get("/api/overviews").json()] == ["weekly"]
    assert not [n for n in client.get("/api/notifications").json() if n["kind"] == "overview"]
    assert "Your weekly overview for Sep 28 – Oct 4 is in the Archive." in client.get("/api/briefing").json()["catchup"]


def test_if_the_model_fails_the_numbers_still_speak(client, clock, llm):
    at(clock, "2026-10-04T19:00")
    tick(client)
    llm.replies = []  # the assessment call fails
    at(clock, "2026-10-04T20:00")
    tick(client)
    (o,) = client.get("/api/overviews").json()
    assert client.get(f"/api/overviews/{o['id']}").json()["assessment"] == "0 done, 0 slipped."


def test_nothing_counts_as_slipped_before_its_day_is_over(client, clock, llm):
    at(clock, "2026-09-30T10:00")
    client.post("/api/tasks", json={"title": "Friday thing", "do_date": "2026-10-02"})
    client.post("/api/tasks", json={"title": "Today thing", "do_date": "2026-09-30"})
    from datetime import date
    from app import overviews
    o = overviews.build(client.app.state.db, llm, "weekly", date(2026, 9, 28), date(2026, 10, 4), datetime(2026, 9, 30, 20))
    assert o["slipped"] == [] and o["hours"] == []
