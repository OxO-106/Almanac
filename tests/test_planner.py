import json
from datetime import datetime

from app.clock import LA


def at(clock, text):
    clock.set(datetime.fromisoformat(text).replace(tzinfo=LA))


def steps(*s):
    return json.dumps({"milestones": [{"title": t, "work_kind": k, "size": z, "unit": u, "hours": h} for t, k, z, u, h in s]})


PRESENTATION = steps(("First read of the paper", "paper", 14, "pages", 3), ("Second read and notes", "paper", 14, "pages", 3),
                     ("Outline the talk", "other", 1, "task", 2), ("Make the slides", "slides", 20, "slides", 4),
                     ("Rehearse", "other", 1, "task", 2))


def project(client, **kw):
    return client.post("/api/projects", json={"title": "Present P10 in CS 239 · Kim", "deadline": "2026-11-05T14:00", **kw}).json()


def plan(client, p, **kw):
    r = client.post(f"/api/projects/{p['id']}/plan", json=kw)
    assert r.status_code == 200, r.text
    return r.json()


def placed(result):
    return [(o["data"]["title"], o["data"]["do_date"]) for o in result["proposal"]["ops"]]


def test_the_nov_5_presentation_is_planned_backward_with_slack(client, clock, llm):
    at(clock, "2026-09-30T10:00")
    llm.replies = [PRESENTATION]
    p = project(client)
    r = plan(client, p)
    assert placed(r) == [("First read of the paper", "2026-10-14"), ("Second read and notes", "2026-10-18"),
                         ("Outline the talk", "2026-10-22"), ("Make the slides (1/2)", "2026-10-26"),
                         ("Make the slides (2/2)", "2026-10-30"), ("Rehearse", "2026-11-03")]  # 2 days before Nov 5
    op = r["proposal"]["ops"][0]
    assert op["kind"] == "tasks" and op["data"]["project_id"] == p["id"] and op["data"]["due"] == "2026-11-05T14:00"
    assert (op["data"]["work_kind"], op["data"]["size"], op["data"]["estimate_min"]) == ("paper", 14, 180)
    assert r["warnings"] == []
    assert r["proposal"]["summary"] == "Plan for “Present P10 in CS 239 · Kim”: 6 steps, Wed Oct 14 – Tue Nov 3"


def test_the_model_never_picks_dates(client, clock, llm):
    at(clock, "2026-09-30T10:00")
    llm.replies = [PRESENTATION]
    plan(client, project(client))
    assert "date" not in json.dumps(llm.requests[0]["schema"])


def test_full_days_push_work_earlier(client, clock, llm):
    at(clock, "2026-09-30T10:00")
    for day in ("2026-11-03", "2026-10-30"):
        client.post("/api/tasks", json={"title": "Other course work", "do_date": day, "estimate_min": 330})
    llm.replies = [PRESENTATION]
    days = [d for _, d in placed(plan(client, project(client)))]
    assert days[-1] == "2026-11-02" and "2026-10-30" not in days
    assert days == sorted(days) and len(set(days)) == len(days)


def test_class_time_counts_toward_a_days_load(client, clock, llm):
    at(clock, "2026-09-30T10:00")
    client.put("/api/capacity", json={"weekday": 4, "weekend": 10})
    client.post("/api/events", json={"title": "CS 239 class", "start": "2026-09-28T16:00", "end": "2026-09-28T18:00", "repeat": "MO,TU"})
    llm.replies = [steps(("Rehearse", "other", 1, "task", 3))]
    # Nov 3 is a Tuesday: 2h of class leaves 2h, not enough for 3h -> Nov 2 is Monday (class) -> Nov 1 Sunday
    assert placed(plan(client, project(client))) == [("Rehearse", "2026-11-01")]


def test_a_plan_that_cannot_fit_is_still_proposed_with_warnings(client, clock, llm):
    at(clock, "2026-11-01T10:00")
    client.put("/api/capacity", json={"weekday": 2, "weekend": 2})
    llm.replies = [PRESENTATION]
    r = plan(client, project(client))
    assert len(r["proposal"]["ops"]) == 6
    assert r["warnings"] and all("over" in w for w in r["warnings"])
    assert all("2026-11-01" <= d <= "2026-11-03" for _, d in placed(r))  # never in the past, never past the slack
    assert "over capacity" in r["proposal"]["summary"]


def test_team_projects_leave_time_to_merge_and_plan_only_your_part(client, clock, llm):
    at(clock, "2026-09-30T10:00")
    llm.replies = [steps(("Write my section", "writing", 2, "pages", 3))]
    p = project(client, title="CS 239 · Ding midterm report", deadline="2026-11-11", team=True, notes="My part: evaluation section")
    assert placed(plan(client, p)) == [("Write my section", "2026-11-07")]  # 2 days slack + 2 days to merge
    prompt = llm.requests[0]["messages"][-1]["content"]
    assert "only the student's own part" in prompt and "My part: evaluation section" in prompt


def test_slack_can_be_overridden(client, clock, llm):
    at(clock, "2026-09-30T10:00")
    llm.replies = [steps(("Rehearse", "other", 1, "task", 2))]
    assert placed(plan(client, project(client), slack_days=0)) == [("Rehearse", "2026-11-05")]


def test_a_project_without_a_deadline_cannot_be_planned(client, llm):
    p = client.post("/api/projects", json={"title": "Research outreach"}).json()
    r = client.post(f"/api/projects/{p['id']}/plan", json={})
    assert r.status_code == 422 and "deadline" in r.json()["detail"]


def test_what_the_assistant_knows_about_you_informs_estimates(client, clock, llm):
    at(clock, "2026-09-30T10:00")
    client.post("/api/memories", json={"text": "Reads papers at about 4 pages an hour"})
    llm.replies = [PRESENTATION]
    plan(client, project(client))
    assert "Reads papers at about 4 pages an hour" in llm.requests[0]["messages"][-1]["content"]
