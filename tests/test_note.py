import json
from datetime import datetime

import pytest

from app import note
from app.clock import LA


@pytest.fixture(autouse=True)
def inline(monkeypatch):
    monkeypatch.setattr(note, "BACKGROUND", False)


def at(clock, text):
    clock.set(datetime.fromisoformat(text).replace(tzinfo=LA))


def test_the_note_is_written_by_the_model_from_the_days_facts(client, clock, llm):
    at(clock, "2026-10-01T08:30")
    client.post("/api/tasks", json={"title": "Read ReAct before class", "do_date": "2026-10-01"})
    client.post("/api/deadlines", json={"title": "Paper registration", "due": "2026-10-05"})
    llm.replies = [json.dumps({"headline": "Morning. Today is mostly reading.",
                               "body": "ReAct is the one to get through first. Paper registration is due Monday."})]
    n = client.get("/api/note").json()
    assert n == {"date": "2026-10-01", "headline": "Morning. Today is mostly reading.",
                 "body": "ReAct is the one to get through first. Paper registration is due Monday.", "written_by": "assistant"}
    facts = llm.requests[0]["messages"][-1]["content"]
    assert "Read ReAct before class" in facts and "Paper registration (Mon, Oct 5)" in facts
    client.get("/api/note")
    assert len(llm.requests) == 1  # once a day


def test_without_the_model_a_plain_note_stands_in(client, clock, llm):
    at(clock, "2026-10-01T14:00")
    client.post("/api/tasks", json={"title": "Read ReAct", "do_date": "2026-10-01"})
    client.post("/api/tasks", json={"title": "Shortlist papers", "do_date": "2026-10-01"})
    client.post("/api/events", json={"title": "CS 239 class", "start": "2026-09-28T16:00", "repeat": "MO,TH"})
    client.post("/api/deadlines", json={"title": "Paper registration", "due": "2026-10-05"})
    llm.replies = ["not json"]
    n = client.get("/api/note").json()
    assert n["written_by"] == "plain"
    assert n["headline"] == "Afternoon. Two things on your list today."
    assert n["body"] == "CS 239 class is at 4:00 PM. Next up: Paper registration, Mon, Oct 5."


def test_a_clear_day_says_so(client, clock, llm):
    at(clock, "2026-10-03T20:00")
    llm.replies = ["not json"]
    n = client.get("/api/note").json()
    assert n["headline"] == "Evening. Nothing on your list today."
    assert n["body"] == "Nothing due in the next two weeks that I know of."


def test_the_note_is_refreshed_when_the_morning_briefing_runs(client, clock, llm):
    at(clock, "2026-10-01T08:00")
    llm.replies = ["not json"]
    client.get("/api/note")  # plain, before 9
    llm.replies = [json.dumps({"headline": "Morning. A quiet one.", "body": "Nothing due soon."})]
    at(clock, "2026-10-01T09:00")
    client.post("/api/scheduler/tick")
    assert client.get("/api/note").json()["written_by"] == "assistant"


def test_the_note_is_rewritten_when_the_day_changes(client, clock, llm):
    at(clock, "2026-10-01T08:30")
    llm.replies = [json.dumps({"headline": "Morning. Nothing on today.", "body": "A clear day."})]
    assert client.get("/api/note").json()["body"] == "A clear day."
    client.post("/api/tasks", json={"title": "Read ReAct before class", "do_date": "2026-10-01"})
    llm.replies = [json.dumps({"headline": "Morning. One thing today.", "body": "Read ReAct before class."})]
    assert client.get("/api/note").json()["body"] == "Read ReAct before class."
    assert "Read ReAct before class" in llm.requests[-1]["messages"][-1]["content"]
    client.get("/api/note")
    assert len(llm.requests) == 2  # unchanged facts: no new note


def test_the_note_mentions_what_is_overdue(client, clock, llm):
    at(clock, "2026-10-02T21:00")
    client.post("/api/tasks", json={"title": "Read P1. SWE-bench", "due": "2026-09-28"})
    client.post("/api/tasks", json={"title": "Read P2. ReAct", "due": "2026-09-30"})
    llm.replies = ["not json"]
    n = client.get("/api/note").json()
    assert n["headline"] == "Evening. Two things to catch up on." and "2 things are overdue, the oldest Read P1. SWE-bench." in n["body"]
    facts = llm.requests[0]["messages"][-1]["content"]
    assert "Overdue (2; mention them" in facts and "Read P1. SWE-bench (due Mon, Sep 28)" in facts
