from datetime import datetime

from app.clock import LA


def at(clock, text):
    clock.set(datetime.fromisoformat(text).replace(tzinfo=LA))


def tick(client):
    return client.post("/api/scheduler/tick").json()["ran"]


def notes(client, kind=None):
    return [n for n in client.get("/api/notifications", params={"after": 0}).json() if kind in (None, n["kind"])]


def assistant(client):
    return [m["text"] for m in client.get("/api/chat").json()["messages"] if m["role"] == "assistant"]


def task(client, **f):
    return client.post("/api/tasks", json=f).json()


def proposals(client):
    return client.get("/api/inbox").json()["proposals"]


def test_8pm_checks_in_on_todays_open_tasks(client, clock):
    at(clock, "2026-10-05T19:00")
    task(client, title="Register paper", do_date="2026-10-05")
    done = task(client, title="Email Prof. Chen", do_date="2026-10-05")
    client.patch(f"/api/tasks/{done['id']}", json={"status": "done"})
    task(client, title="Tomorrow's thing", do_date="2026-10-06")
    tick(client)  # the 9am briefing, late: no notification
    at(clock, "2026-10-05T20:00")
    assert "checkin" in tick(client)
    (n,) = notes(client, "checkin")
    assert n["title"] == "How did today go?" and n["body"] == "Still open: Register paper. Anything new today?"
    assert assistant(client)[-1] == ("It's 8pm. How did today go? Still open from today's plan: Register paper. "
                                     "Tell me what you finished, or tick it off on Today. And anything new today? New deadlines, "
                                     "plans, something mentioned in class: tell me and I'll suggest adding it.")


def test_11pm_asks_again_only_about_what_is_still_open(client, clock):
    at(clock, "2026-10-05T19:59")
    a = task(client, title="Register paper", do_date="2026-10-05")
    task(client, title="Read P10", do_date="2026-10-05")
    tick(client)
    at(clock, "2026-10-05T20:00")
    tick(client)
    client.patch(f"/api/tasks/{a['id']}", json={"status": "done"})
    at(clock, "2026-10-05T23:00")
    tick(client)
    last = notes(client, "checkin")[-1]
    assert last["title"] == "Last check for today" and last["body"] == "Still open: Read P10. Done, or should I move it?"


def test_with_nothing_open_8pm_still_asks_whats_new(client, clock):
    at(clock, "2026-10-05T19:59")
    tick(client)
    at(clock, "2026-10-05T20:00")
    tick(client)
    (n,) = notes(client, "checkin")
    assert n["title"] == "Anything new today?" and n["body"] == "New deadlines, plans, something mentioned in class?"
    assert assistant(client)[-1] == ("It's 8pm. Anything new today? New deadlines, plans, something mentioned in class: "
                                     "tell me and I'll suggest adding it.")
    at(clock, "2026-10-05T23:00")
    tick(client)
    assert len(notes(client, "checkin")) == 1  # 11pm only asks about open tasks


def test_check_ins_missed_while_off_appear_in_the_next_briefing(client, clock):
    at(clock, "2026-10-05T19:00")
    task(client, title="Read P10", do_date="2026-10-05")
    tick(client)
    at(clock, "2026-10-06T09:05")  # off from 7pm to the next morning
    tick(client)
    assert notes(client, "checkin") == []
    b = client.get("/api/briefing").json()
    assert b["catchup"] == ["Oct 5: Read P10 was still open at the evening check-in."]


def test_a_missed_step_gets_a_replan_that_respects_order_and_slack(client, clock):
    at(clock, "2026-10-12T20:00")
    p = client.post("/api/projects", json={"title": "Present P10", "deadline": "2026-11-05T14:00"}).json()
    a = task(client, title="First read", project_id=p["id"], do_date="2026-10-10", estimate_min=180)
    b = task(client, title="Outline", project_id=p["id"], do_date="2026-10-20", estimate_min=120)
    tick(client)
    at(clock, "2026-10-12T22:30")
    assert "replan" in tick(client)
    (prop,) = [x for x in proposals(client) if x["summary"].startswith("Replan")]
    moved = {o["id"]: o["data"]["do_date"] for o in prop["ops"]}
    assert "2026-10-13" <= moved[a["id"]] < moved.get(b["id"], "2026-10-20") <= "2026-11-03"
    assert prop["summary"].startswith("Replan “Present P10”: First read missed")
    # not proposed again while it waits
    at(clock, "2026-10-13T22:30")
    tick(client)
    assert len([x for x in proposals(client) if x["summary"].startswith("Replan")]) == 1


def test_a_second_slip_starts_a_conversation(client, clock):
    at(clock, "2026-10-12T20:00")
    p = client.post("/api/projects", json={"title": "Present P10", "deadline": "2026-11-05T14:00"}).json()
    a = task(client, title="First read", project_id=p["id"], do_date="2026-10-10", estimate_min=60)
    at(clock, "2026-10-12T22:30")
    tick(client)
    (prop,) = proposals(client)
    client.post(f"/api/proposals/{prop['id']}/accept")
    new_day = client.get(f"/api/tasks/{a['id']}").json()["do_date"]
    at(clock, f"{new_day}T23:59")
    tick(client)
    nxt = datetime.fromisoformat(new_day).replace(day=int(new_day[8:]) + 1).date().isoformat()
    at(clock, f"{nxt}T22:30")
    tick(client)
    assert "“Present P10” has slipped twice now." in assistant(client)[-1]


def test_a_missed_loose_task_is_moved_to_the_next_day_with_room(client, clock):
    at(clock, "2026-10-12T20:00")
    t = task(client, title="Buy a poster tube", do_date="2026-10-10", estimate_min=30)
    at(clock, "2026-10-12T22:30")
    tick(client)
    (prop,) = proposals(client)
    assert prop["ops"] == [{"op": "update", "kind": "tasks", "id": t["id"], "data": {"do_date": "2026-10-13"}}]
    assert prop["summary"] == "Move 1 missed task to the next day with room"
