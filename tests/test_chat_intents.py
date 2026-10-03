"""Chat is read as the student talking about their own plan: it can change
and remove what's planned, not only add."""
import json
from datetime import datetime

import pytest

from app.clock import LA


def actions(*acts):
    return json.dumps({"actions": list(acts)})


def say(client, llm, text, *acts):
    llm.replies = ["Okay.", actions(*acts)]
    client.post("/api/chat", json={"text": text})
    return {p["summary"]: p for p in client.get("/api/inbox").json()["proposals"]}


@pytest.fixture
def plan(client, clock):
    clock.set(datetime(2026, 10, 1, 10, 0, tzinfo=LA))  # a Thursday
    c = client.post("/api/courses", json={"number": "CS 259", "instructor": "Miodrag Potkonjak"}).json()
    client.post("/api/deadlines", json={"title": "Proposal one-pager", "due": "2026-10-21"})
    client.post("/api/events", json={"title": "CS 259 class", "course_id": c["id"], "start": "2026-09-28T14:00",
                                     "end": "2026-09-28T15:50", "repeat": "MO,WE", "until": "2026-12-04"})
    client.post("/api/events", json={"title": "Gating test", "start": "2026-10-02"})
    return c


def test_moving_an_item_changes_it_instead_of_adding_one(client, llm, plan):
    got = say(client, llm, "Move the one-pager to Tuesday",
              {"type": "change", "title": "Proposal one-pager", "quote": "Move the one-pager to Tuesday",
               "when": {"type": "weekday", "weekday": "TU"}})
    (p,) = got.values()
    assert p["ops"] == [{"op": "update", "kind": "deadlines", "id": 1, "data": {"due": "2026-10-06"}}]
    assert p["summary"] == "Change “Proposal one-pager”: Tue Oct 6"


def test_a_new_time_for_a_weekly_class_keeps_its_length(client, llm, plan):
    got = say(client, llm, "The CS 259 lecture is actually at 3",
              {"type": "change", "title": "CS 259 class", "course": "CS 259", "quote": "The CS 259 lecture is actually at 3pm",
               "start_time": "15:00"})
    assert got == {}  # "at 3pm" isn't what they wrote: not trusted
    got = say(client, llm, "The CS 259 lecture is actually at 3pm",
              {"type": "change", "title": "CS 259 class", "course": "CS 259", "quote": "The CS 259 lecture is actually at 3pm",
               "start_time": "15:00"})
    (p,) = got.values()
    assert p["ops"][0]["data"] == {"start": "2026-09-28T15:00", "end": "2026-09-28T16:50"}


def test_removing_an_item(client, llm, plan):
    (p,) = say(client, llm, "Delete the gating test",
               {"type": "remove", "title": "Gating test", "quote": "Delete the gating test"}).values()
    assert p["ops"] == [{"op": "delete", "kind": "events", "id": 2}]


def test_a_routine_is_removed_as_one(client, llm, plan):
    say(client, llm, "I'll watch the CS 259 recording before the next class",
        {"type": "task", "title": "Watch CS 259 recording", "course": "CS 259", "quote": "watch the CS 259 recording before the next class",
         "each_class": True})
    (routine,) = client.get("/api/inbox").json()["proposals"]
    client.post(f"/api/proposals/{routine['id']}/accept")
    n = len(client.get("/api/tasks").json())
    assert n > 10
    (p,) = say(client, llm, "Stop the watch recording tasks",
               {"type": "remove", "title": "Watch CS 259 recording (Mon Oct 5)", "quote": "Stop the watch recording tasks"}).values()
    assert len(p["ops"]) == n and p["summary"] == f"Remove “Watch CS 259 recording” ({n} tasks)"


def test_rewinding_a_change_undoes_it(client, llm, plan):
    (p,) = say(client, llm, "Move the one-pager to Tuesday",
               {"type": "change", "title": "Proposal one-pager", "quote": "Move the one-pager to Tuesday",
                "when": {"type": "weekday", "weekday": "TU"}}).values()
    client.post(f"/api/proposals/{p['id']}/accept")
    assert client.get("/api/deadlines/1").json()["due"] == "2026-10-06"
    mine = [m for m in client.get("/api/chat").json()["messages"] if m["role"] == "user"][-1]
    client.post(f"/api/chat/rewind/{mine['id']}")
    assert client.get("/api/deadlines/1").json()["due"] == "2026-10-21"


def test_the_model_sees_the_weekly_classes_so_it_need_not_ask(client, llm, plan):
    say(client, llm, "hi")
    system = llm.requests[-1]["messages"][0]["content"]
    assert "Weekly classes:\n- CS 259 class: MO,WE 14:00-15:50" in system
    assert "Proposal one-pager (2026-10-21)" in system


def test_an_item_can_be_made_another_kind(client, llm, plan):
    (p,) = say(client, llm, "change the gating test to a task",
               {"type": "change", "title": "Gating test", "quote": "change the gating test to a task", "new_kind": "task"}).values()
    assert p["summary"] == "Make “Gating test” a task"
    client.post(f"/api/proposals/{p['id']}/accept")
    assert [t["title"] for t in client.get("/api/tasks").json()] == ["Gating test"]
    assert client.get("/api/tasks").json()[0]["due"] == "2026-10-02"
    assert [e["title"] for e in client.get("/api/events").json()] == ["CS 259 class"]  # the session is gone, the class stays


def test_a_change_that_cant_be_made_is_said_not_silent(client, llm, plan):
    say(client, llm, "move the reading group to Friday",
        {"type": "change", "title": "Reading group", "quote": "move the reading group to Friday", "when": {"type": "weekday", "weekday": "FR"}})
    assert client.get("/api/chat").json()["messages"][-1]["text"] == "I couldn't find “Reading group” in your plan."
