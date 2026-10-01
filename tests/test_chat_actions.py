import json

from test_chat import chat, say


def actions(*acts):
    return json.dumps({"actions": list(acts)})


def act(type="task", title="Email Prof. Smith about research", quote="email Prof. Smith about research by Friday", when=None, **extra):
    return {"type": type, "title": title, "quote": quote, "when": when or {"type": "unknown"}, **extra}


def proposals(client):
    return client.get("/api/inbox").json()["proposals"]


def test_a_brain_dump_becomes_proposals(client, llm):
    llm.replies = ["On it — I've suggested a task.",
                   actions(act(when={"type": "weekday", "weekday": "FR"}),
                           act(type="deadline", title="Job applications", quote="job apps before Thanksgiving",
                               when={"type": "unknown"}))]
    say(client, "I need to email Prof. Smith about research by Friday, also job apps before Thanksgiving")
    ps = proposals(client)
    assert [(p["summary"], p["ops"][0]["kind"]) for p in ps] == [("Email Prof. Smith about research", "tasks"),
                                                              ("Job applications", "deadlines")]
    assert ps[0]["ops"][0]["data"]["due"] == "2026-10-02"  # the coming Friday (today is Wed Sep 30)
    assert "due" not in ps[1]["ops"][0]["data"]  # "Thanksgiving" isn't a date the code will guess
    assert ps[0]["quote"] == "email Prof. Smith about research by Friday"
    assert ps[0]["source"]["kind"] == "chat"


def test_everyday_dates_resolve_only_when_said(client, llm):
    llm.replies = ["ok", actions(
        act(title="Call mom", quote="call mom tomorrow", when={"type": "in_days", "days": 1}),
        act(title="Draft outline", quote="draft the outline in two weeks", when={"type": "in_days", "days": 14}),
        act(title="Gym", quote="go to the gym", when={"type": "weekday", "weekday": "MO"}),
        act(title="Read P10", quote="read P10 next Tuesday", when={"type": "weekday", "weekday": "TU", "next_week": True}))]
    say(client, "call mom tomorrow, draft the outline in two weeks, go to the gym, read P10 next Tuesday")
    due = {p["summary"]: p["ops"][0]["data"].get("due") for p in proposals(client)}
    assert due == {"Call mom": "2026-10-01", "Draft outline": "2026-10-14", "Gym": None, "Read P10": "2026-10-06"}


def test_actions_whose_quote_is_not_in_the_message_are_dropped(client, llm):
    llm.replies = ["ok", actions(act(quote="something the user never said"))]
    say(client, "I need to email Prof. Smith about research by Friday")
    assert proposals(client) == []


def test_things_to_remember_become_memory_proposals(client, llm):
    llm.replies = ["Noted!", actions(act(type="memory", title="Reads papers at about 4 pages an hour",
                                         quote="I read about 4 pages an hour", topic="work habits"))]
    say(client, "honestly I read about 4 pages an hour")
    (p,) = proposals(client)
    assert p["ops"] == [{"op": "create", "kind": "memories",
                         "data": {"text": "Reads papers at about 4 pages an hour", "topic": "work habits"}}]


def test_goals_become_goal_proposals(client, llm):
    llm.replies = ["Great goal.", actions(act(type="goal", title="Get an ML research position", quote="get into a research lab",
                                              why="PhD applications", horizon="year"))]
    say(client, "I want to get into a research lab this year for PhD applications")
    (p,) = proposals(client)
    assert p["ops"][0] == {"op": "create", "kind": "goals",
                           "data": {"title": "Get an ML research position", "why": "PhD applications", "horizon": "year"}}


def test_progress_on_an_open_task_becomes_an_update(client, llm):
    task = client.post("/api/tasks", json={"title": "Read P10: Agentic Program Repair"}).json()
    llm.replies = ["Nice work!", actions(act(type="progress", title="Read P10", quote="finished reading P10", done=True))]
    say(client, "finished reading P10 today")
    (p,) = proposals(client)
    assert p["ops"] == [{"op": "update", "kind": "tasks", "id": task["id"], "data": {"status": "done"}}]
    assert "Read P10: Agentic Program Repair" in llm.requests[-1]["messages"][0]["content"]  # open tasks are shown to the model


def test_the_assistant_can_ask_back(client, llm):
    llm.replies = ["When is it due?", actions(act(type="question", title="When is your job application due?",
                                                  quote="I have a job application"))]
    say(client, "I have a job application")
    cur = chat(client)["current"]
    assert cur["text"] == "When is it due?"  # the reply that asked it; not asked a second time
    assert client.get(f"/api/questions/{cur['question_id']}").json()["text"] == "When is your job application due?"
    say(client, "Friday")
    assert client.get(f"/api/questions/{cur['question_id']}").json()["answer"] == "Friday"


def test_answering_a_date_question_fills_in_the_waiting_item(client, llm):
    src = client.post("/api/sources", json={"kind": "document", "title": "cs239.pdf", "text": "x"}).json()
    q = client.post("/api/questions", json={"source_id": src["id"], "text": "When is “Project team list” due? The document doesn't say."}).json()
    client.post("/api/proposals", json={"source_id": src["id"], "summary": "Project team list", "question_id": q["id"],
                                        "ops": [{"op": "create", "kind": "deadlines", "data": {"title": "Project team list"}}]})
    chat(client)
    llm.replies = [json.dumps({"items": [{"n": 0, "when": {"type": "date", "month": 10, "day": 9}}]})]
    c = say(client, "It's due Oct 9")
    (p,) = proposals(client)
    assert p["ops"][0]["data"]["due"] == "2026-10-09"
    assert "Project team list: Fri Oct 9" in [m["text"] for m in c["messages"]][-1]


def test_an_answer_without_a_date_leaves_the_item_undated(client, llm):
    src = client.post("/api/sources", json={"kind": "document", "title": "cs239.pdf", "text": "x"}).json()
    q = client.post("/api/questions", json={"source_id": src["id"], "text": "When is “Final report” due?"}).json()
    client.post("/api/proposals", json={"source_id": src["id"], "summary": "Final report", "question_id": q["id"],
                                        "ops": [{"op": "create", "kind": "deadlines", "data": {"title": "Final report"}}]})
    chat(client)
    llm.replies = [json.dumps({"items": [{"n": 0, "when": {"type": "date", "month": 12, "day": 4}}]})]
    say(client, "not sure, I'll check Piazza")
    assert "due" not in proposals(client)[0]["ops"][0]["data"]


def test_streamed_replies_arrive_in_pieces_then_the_actions(client, llm):
    llm.replies = ["Sounds good! I added a task.", actions(act(when={"type": "weekday", "weekday": "FR"}))]
    with client.stream("POST", "/api/chat/stream", json={"text": "I need to email Prof. Smith about research by Friday"}) as r:
        events = [json.loads(line[6:]) for line in r.iter_lines() if line.startswith("data: ")]
    tokens = "".join(e["text"] for e in events if e["type"] == "token")
    assert tokens == "Sounds good! I added a task."
    assert events[-1]["type"] == "done"
    assert events[-1]["proposed"] == 1


def test_a_failed_suggestions_pass_is_reported_not_hidden(client, llm):
    llm.replies = ["Sure!", "not json"]
    r = client.post("/api/chat", json={"text": "I need to email Prof. Smith about research by Friday"}).json()
    assert r["proposed"] is None
    assert proposals(client) == []


def test_questions_name_the_course_not_the_file(client, llm):
    from test_upload import SYLLABUS, course_reply, item, items_reply, upload
    llm.replies = [course_reply([{"number": "COM SCI 269", "instructor": "", "title": "Advanced Topics in AI: Agentic Learning",
                                  "quote": "Instructor: Robin Ding", "meetings": []}]), items_reply()]
    upload(client, "26F-COM SCI-269-SEM-3 Seminar_ Current Topics.txt", SYLLABUS.encode())
    text = chat(client)["current"]["text"]
    assert text == "Who teaches COM SCI 269: Advanced Topics in AI: Agentic Learning? The document doesn't name the instructor."
    client.post("/api/chat/skip")
    client.post("/api/questions", json={"source_id": 1, "text": "Which option will you take?"})
    assert chat(client)["current"]["text"] == ("Quick question about COM SCI 269: Advanced Topics in AI: Agentic Learning: "
                                               "Which option will you take?")


def test_answering_who_teaches_fills_in_the_instructor(client, llm):
    from test_upload import SYLLABUS, course_reply, items_reply, upload
    llm.replies = [course_reply([{"number": "CS 239", "instructor": "", "quote": "Instructor: Robin Ding", "meetings": []}]), items_reply()]
    upload(client, "kim.txt", SYLLABUS.encode())
    chat(client)
    c = say(client, "Miryung Kim")
    (p,) = proposals(client)
    assert p["ops"][0]["data"]["instructor"] == "Miryung Kim" and p["summary"] == "Add course CS 239 · Miryung Kim"
    assert "CS 239 · Miryung Kim" in [m["text"] for m in c["messages"]][-1]


def test_an_ordinal_date_in_an_answer_counts(client, llm):
    src = client.post("/api/sources", json={"kind": "document", "title": "kim.pdf", "text": "x"}).json()
    q = client.post("/api/questions", json={"source_id": src["id"], "text": "When is “Final Project” due?"}).json()
    client.post("/api/proposals", json={"source_id": src["id"], "summary": "Final Project", "question_id": q["id"],
                                        "ops": [{"op": "create", "kind": "deadlines", "data": {"title": "Final Project"}}]})
    chat(client)
    llm.replies = [json.dumps({"items": [{"n": 0, "when": {"type": "date", "month": 12, "day": 3}}]})]
    c = say(client, "Set it to the last class December 3rd for now")
    assert proposals(client)[0]["ops"][0]["data"]["due"] == "2026-12-03"
    assert "Final Project: Thu Dec 3" in [m["text"] for m in c["messages"]][-1]


def test_suggestions_appear_in_the_conversation_as_a_card(client, llm):
    llm.replies = ["On it.", actions(act(when={"type": "weekday", "weekday": "FR"}))]
    c = say(client, "I need to email Prof. Smith about research by Friday")
    card = c["messages"][-1]
    assert card["text"] == "Here's what I'd add. Check the dates are right:"
    (p,) = card["proposals"]
    assert (p["summary"], p["status"], p["ops"][0]["data"]["due"]) == ("Email Prof. Smith about research", "pending", "2026-10-02")
    client.post(f"/api/proposals/{p['id']}/accept")
    assert chat(client)["messages"][-1]["proposals"][0]["status"] == "accepted"


def test_a_question_with_fixed_answers_offers_them(client):
    from test_canvas import Feed, connect
    client.post("/api/courses", json={"number": "CS 239", "instructor": "Robin Ding"})
    client.post("/api/courses", json={"number": "CS 239", "instructor": "Miryung Kim"})
    connect(client, Feed())
    assert chat(client)["current"]["options"] == ["CS 239 · Robin Ding", "CS 239 · Miryung Kim"]


def test_one_thing_said_once_is_suggested_once(client, llm):
    llm.replies = ["ok", actions(act(), act(type="deadline"))]
    say(client, "I need to email Prof. Smith about research by Friday")
    assert len(proposals(client)) == 1


def test_a_weekday_the_model_turned_into_a_date_counts_when_said(client, llm):
    llm.replies = ["ok", actions(act(when={"type": "date", "month": 10, "day": 2}),
                                 act(title="Call home", quote="call home", when={"type": "date", "month": 10, "day": 2}))]
    say(client, "I need to email Prof. Smith about research by Friday, and call home")
    due = {p["summary"]: p["ops"][0]["data"].get("due") for p in proposals(client)}
    assert due == {"Email Prof. Smith about research": "2026-10-02", "Call home": None}
