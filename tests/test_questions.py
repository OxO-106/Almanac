"""Each question knows what it's for; the answer goes to that handler."""
import json

from app import inbox as inbox_mod


def chat(client):
    return client.get("/api/chat").json()


def source(client):
    return client.post("/api/sources", json={"kind": "document", "title": "ding.pdf", "text": "x"}).json()


def pending(client):
    return {p["summary"]: p for p in client.get("/api/inbox").json()["proposals"]}


def test_an_answer_for_no_item_is_read_like_chat_and_lands_on_the_item(client, llm):
    src = source(client)
    client.post("/api/questions", json={"source_id": src["id"], "text": "When must you submit your one-page proposal report?"})
    assert chat(client)["current"]
    llm.replies = [json.dumps({"actions": [{"type": "deadline", "title": "One-page proposal report", "quote": "October 21st",
                                            "when": {"type": "date", "month": 10, "day": 21}}]})]
    client.post("/api/chat", json={"text": "October 21st"})
    assert pending(client)["One-page proposal report"]["ops"][0]["data"]["due"] == "2026-10-21"
    assert "You asked: When must you submit your one-page proposal report?" in llm.requests[-1]["messages"][-1]["content"]


def test_an_answer_for_no_item_fills_in_the_one_already_planned(client, llm):
    src = source(client)
    client.post("/api/deadlines", json={"title": "Proposal one-pager", "due": "2026-10-21"})
    client.post("/api/questions", json={"source_id": src["id"], "text": "When must you submit your one-page proposal report?"})
    chat(client)
    llm.replies = [json.dumps({"actions": [{"type": "deadline", "title": "Proposal one-pager", "quote": "October 21st",
                                            "when": {"type": "date", "month": 10, "day": 21}}]})]
    client.post("/api/chat", json={"text": "October 21st"})
    assert pending(client) == {}  # already in the plan: no second one
    assert len(client.get("/api/deadlines").json()) == 1


def test_a_slot_choice_shows_buttons_and_keeps_only_the_chosen_slot(client):
    src = source(client)
    con, clock = client.app.state.db, client.app.state.clock
    nov30 = inbox_mod.propose(con, clock, src["id"], "Final project report, Mon Nov 30",
                              [{"op": "create", "kind": "events", "data": {"title": "Final project report", "start": "2026-11-30"}}])
    dec2 = inbox_mod.propose(con, clock, src["id"], "Final project report, Wed Dec 2",
                             [{"op": "create", "kind": "events", "data": {"title": "Final project report", "start": "2026-12-02"}}])
    client.post(f"/api/proposals/{dec2['id']}/accept")  # accepted already: dropping it removes it from the plan
    inbox_mod.ask(con, clock, src["id"], "Which slot did you sign up for: Mon Nov 30 or Wed Dec 2?", None, "choice", None,
                  [{"label": "Mon Nov 30", "adds": [nov30["id"]]}, {"label": "Wed Dec 2", "adds": [dec2["id"]]}])
    assert chat(client)["current"]["options"] == ["Mon Nov 30", "Wed Dec 2"]
    client.post("/api/chat", json={"text": "Mon Nov 30"})
    assert list(pending(client)) == ["Final project report, Mon Nov 30"]
    assert client.get("/api/events").json() == []  # Dec 2 taken out of the plan
    assert chat(client)["messages"][-1]["text"].startswith("Got it: Mon Nov 30.")


def slots(client):
    src = source(client)
    con, clock = client.app.state.db, client.app.state.clock
    nov4 = inbox_mod.propose(con, clock, src["id"], "Mid-term project report, Wed Nov 4",
                             [{"op": "create", "kind": "deadlines", "data": {"title": "Mid-term project report", "due": "2026-11-04"}}])
    nov9 = inbox_mod.propose(con, clock, src["id"], "Mid-term project report, Mon Nov 9",
                             [{"op": "create", "kind": "deadlines", "data": {"title": "Mid-term project report", "due": "2026-11-09"}}])
    q = inbox_mod.ask(con, clock, src["id"], "Which day is your “Mid-term project report”: Wed Nov 4 or Mon Nov 9?", None, "choice", None,
                      [{"label": "Wed Nov 4", "adds": [nov4["id"]]}, {"label": "Mon Nov 9", "adds": [nov9["id"]]}])
    chat(client)
    return q


def test_a_date_none_of_the_options_had_is_taken(client):
    slots(client)
    client.post("/api/chat", json={"text": "It's due on November 11th"})
    (p,) = pending(client).values()
    assert p["ops"][0]["data"]["due"] == "2026-11-11"
    assert chat(client)["messages"][-1]["text"].startswith("Got it: Wed Nov 11.") and chat(client)["current"] is None
    mine = [m for m in chat(client)["messages"] if m["role"] == "user"][-1]
    client.post(f"/api/chat/rewind/{mine['id']}")  # the dates are back as they were
    assert sorted(p["ops"][0]["data"]["due"] for p in pending(client).values()) == ["2026-11-04", "2026-11-09"]


def test_a_message_thats_none_of_the_options_is_read_as_chat_and_the_question_waits(client, llm):
    q = slots(client)
    llm.replies = ["Sure, I can help with that.", json.dumps({"actions": []})]
    client.post("/api/chat", json={"text": "can you remind me what CS 239 is about?"})
    said = chat(client)
    assert [m["text"] for m in said["messages"][-2:]] == ["Sure, I can help with that.", "Back to my question: " + q["text"]]
    assert said["current"]["question_id"] == q["id"] and said["current"]["options"] == ["Wed Nov 4", "Mon Nov 9"]
    assert len(pending(client)) == 2


def test_rewinding_a_choice_puts_back_what_it_dropped(client):
    src = source(client)
    con, clock = client.app.state.db, client.app.state.clock
    a = inbox_mod.propose(con, clock, src["id"], "Slot A", [{"op": "create", "kind": "events", "data": {"title": "Slot A", "start": "2026-11-30"}}])
    b = inbox_mod.propose(con, clock, src["id"], "Slot B", [{"op": "create", "kind": "events", "data": {"title": "Slot B", "start": "2026-12-02"}}])
    inbox_mod.ask(con, clock, src["id"], "Which slot?", None, "choice", None, [{"label": "Slot A", "adds": [a["id"]]}, {"label": "Slot B", "adds": [b["id"]]}])
    chat(client)
    client.post("/api/chat", json={"text": "Slot A"})
    assert list(pending(client)) == ["Slot A"]
    mine = [m for m in chat(client)["messages"] if m["role"] == "user"][-1]
    client.post(f"/api/chat/rewind/{mine['id']}")
    assert sorted(pending(client)) == ["Slot A", "Slot B"]


def test_an_unclear_choice_is_asked_again():
    from app.questions import _pick
    opts = [{"label": "Mon Nov 30"}, {"label": "Wed Dec 2"}]
    assert _pick(opts, "wed dec 2") is opts[1]
    assert _pick(opts, "the second one") is None


def test_question_wording_lives_in_one_place():
    import re
    from pathlib import Path
    app = Path(__file__).resolve().parent.parent / "app"
    stray = [f"{p.name}:{n}" for p in app.glob("*.py") if p.name not in ("asks.py", "db.py")  # db.py recognises old questions by their words
             for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
             if re.search(r"""f?["'](Who teaches|When is “|Which day in Week|What time does|Which of your courses|How many pages)""", line)]
    assert stray == []


def meeting_question(client, src, days):
    con, clock = client.app.state.db, client.app.state.clock
    return inbox_mod.ask(con, clock, src["id"], f"What time does CS 239 · Kim meet on {'/'.join(days)}?", None, "meeting",
                         {"course": None, "short": "CS 239 · Kim", "days": days, "title": None})


def test_same_as_another_day_adds_that_day_to_the_class(client, llm):
    src = source(client)
    meeting_question(client, src, ["TU"])
    chat(client)
    client.post("/api/chat", json={"text": "10AM to 11:50AM"})  # a written time needs no model
    meeting_question(client, src, ["TH"])
    chat(client)
    llm.replies = [json.dumps({"start": "10:00", "end": "11:50", "unclear": False})]
    said = client.post("/api/chat", json={"text": "same as tuesday"}).json()["messages"]
    (cls,) = [p for s, p in pending(client).items() if "class" in s]
    data = cls["ops"][0]["data"]
    assert (data["repeat"], data["start"][11:], data["end"][11:]) == ("TU,TH", "10:00", "11:50")  # one class, both days
    assert said[-1]["text"].startswith("Updated CS 239 class: every Tu/Th, 10:00 AM–11:50 AM")
    assert "CS 239 class: TU 10:00-11:50" in llm.requests[-1]["messages"][-1]["content"]  # the model saw Tuesday's time


def test_an_answer_with_no_time_is_asked_again_not_closed(client, llm):
    src = source(client)
    q = meeting_question(client, src, ["TH"])
    chat(client)
    llm.replies = [json.dumps({"unclear": True})]
    said = client.post("/api/chat", json={"text": "hmm let me check"}).json()
    assert said["messages"][-1]["text"].startswith("I didn't catch a time there. What time does it meet on Thursdays?")
    assert said["current"]["question_id"] == q["id"]  # still the open question
    assert client.get(f"/api/questions/{q['id']}").json()["status"] == "open"


def test_a_time_the_model_makes_up_is_not_used(client, llm):
    src = source(client)
    meeting_question(client, src, ["TH"])
    chat(client)
    llm.replies = [json.dumps({"start": "09:00", "end": "10:15", "unclear": False})]  # no class at 9, not in the answer
    client.post("/api/chat", json={"text": "same as my other class"})
    assert pending(client) == {}
