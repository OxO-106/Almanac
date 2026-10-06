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


def test_a_request_to_write_something_is_answered_with_what_it_needs(client, llm, plan):
    c = client.post("/api/courses", json={"number": "CS 269", "instructor": "Stefano Soatto", "title": "Agentic Learning"}).json()
    client.post("/api/events", json={"title": "CS 269 class", "course_id": c["id"], "start": "2026-09-28T18:00", "repeat": "MO,WE", "until": "2026-12-04"})
    say(client, llm, "write me an email to the CS269 instructor requesting the recording of the last lecture")
    system = next(r for r in llm.requests if r["messages"][0]["content"].startswith("You are Almanac"))["messages"][0]["content"]
    assert "write it in full, ready to send" in system
    assert "CS 269 · Stefano Soatto: Agentic Learning" in system and "CS 269 class: MO,WE 18:00; last met Wed Sep 30" in system
    assert client.get("/api/inbox").json()["proposals"] == []  # a request to write isn't a task


def test_a_reply_doesnt_draw_its_own_buttons_or_lists_above_the_real_ones(client, llm, plan):
    llm.replies = ["I'll suggest it.\n\n**Suggested Actions:**\n- Add “Read ReAct”\n\n[Add “Read ReAct”]\n\nIs that correct?",
                   actions({"type": "task", "title": "Read ReAct", "quote": "read ReAct by Friday", "when": {"type": "weekday", "weekday": "FR"}})]
    client.post("/api/chat", json={"text": "I need to read ReAct by Friday"})
    texts = [m["text"] for m in client.get("/api/chat").json()["messages"]]
    assert texts[-2:] == ["I'll suggest it.", "Here's what I'd add. Check the dates are right:"]


def test_making_an_item_the_kind_it_already_is_says_so(client, llm, plan):
    say(client, llm, "make the proposal one-pager a deadline",
        {"type": "change", "title": "Proposal one-pager", "quote": "make the proposal one-pager a deadline", "new_kind": "deadline"})
    assert client.get("/api/chat").json()["messages"][-1]["text"] == "“Proposal one-pager” is already a deadline."


def test_a_course_can_be_named_from_chat(client, llm, plan):
    kim = client.post("/api/courses", json={"number": "CS 239", "instructor": "Miryung Kim"}).json()
    client.post("/api/events", json={"title": "CS 239 class", "course_id": kim["id"], "start": "2026-09-29T10:00", "repeat": "TU,TH", "until": "2026-12-04"})
    text = "add Agentic Software Engineering to CS239 Kim as the course name"
    (p,) = say(client, llm, text, {"type": "change", "title": "CS 239 · Miryung Kim", "quote": text, "new_title": "Agentic Software Engineering"}).values()
    assert p["summary"] == "Name CS 239 · Kim “Agentic Software Engineering”"
    client.post(f"/api/proposals/{p['id']}/accept")
    assert client.get(f"/api/courses/{kim['id']}").json()["title"] == "Agentic Software Engineering"
    assert [e["title"] for e in client.get("/api/events").json() if e["course_id"] == kim["id"]] == ["CS 239 class"]  # the class isn't renamed
