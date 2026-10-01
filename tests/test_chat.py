from datetime import timedelta


def source(client, title="kim.pdf"):
    return client.post("/api/sources", json={"kind": "document", "title": title, "text": "x"}).json()


def ask(client, src, text, quote="Each student presents one paper."):
    return client.post("/api/questions", json={"source_id": src["id"], "text": text, "quote": quote}).json()


def propose(client, src, title, question=None):
    return client.post("/api/proposals", json={"source_id": src["id"], "summary": title, "question_id": question and question["id"],
                                               "ops": [{"op": "create", "kind": "tasks", "data": {"title": title}}]}).json()


def chat(client):
    return client.get("/api/chat").json()


def say(client, text):
    r = client.post("/api/chat", json={"text": text})
    assert r.status_code == 200, r.text
    return r.json()


def assistant_texts(c):
    return [m["text"] for m in c["messages"] if m["role"] == "assistant"]


def test_the_inbox_holds_only_proposals(client):
    src = source(client)
    ask(client, src, "Which paper are you presenting?")
    propose(client, src, "Read syllabus")
    box = client.get("/api/inbox").json()
    assert box["count"] == 1 and "questions" not in box


def test_the_assistant_asks_one_question_at_a_time_in_chat(client):
    src = source(client)
    ask(client, src, "Which paper are you presenting?")
    ask(client, src, "Which team are you on?")
    c = chat(client)
    asked = [m for m in c["messages"] if m.get("question_id")]
    assert len(asked) == 1
    assert "Which paper are you presenting?" in asked[0]["text"]
    assert asked[0]["quote"] == "Each student presents one paper."
    assert c["waiting"] == 1  # one more question after this one
    assert len([m for m in chat(client)["messages"] if m.get("question_id")]) == 1  # viewing again doesn't re-ask


def test_questions_that_hold_up_proposals_come_first(client):
    src = source(client)
    ask(client, src, "Minor question?")
    important = ask(client, src, "Who teaches CS 239?")
    propose(client, src, "Add course", important)
    propose(client, src, "Lecture", important)
    assert "Who teaches CS 239?" in assistant_texts(chat(client))[-1]


def test_replying_answers_the_question_and_moves_on(client):
    src = source(client)
    q = ask(client, src, "Which paper are you presenting?")
    blocked = propose(client, src, "Prepare presentation", q)
    ask(client, src, "Which team are you on?")
    chat(client)
    c = say(client, "P10, on Nov 5")
    assert client.get(f"/api/questions/{q['id']}").json()["answer"] == "P10, on Nov 5"
    texts = assistant_texts(c)
    assert texts[-2] == "1 suggestion that was waiting on this is ready in Suggestions."
    assert "Which team are you on?" in texts[-1]
    assert client.post(f"/api/proposals/{blocked['id']}/accept").status_code == 200


def test_skipping_a_question_brings_it_back_tomorrow(client, clock):
    src = source(client)
    ask(client, src, "Which paper are you presenting?")
    chat(client)
    c = client.post("/api/chat/skip").json()
    assert c["current"] is None
    clock.advance(hours=2)
    assert chat(client)["current"] is None
    clock.advance(days=1)
    assert "Which paper are you presenting?" in chat(client)["current"]["text"]


def test_not_relevant_drops_the_question_and_what_waited_on_it(client):
    src = source(client)
    q = ask(client, src, "Do you need accommodations?")
    p = propose(client, src, "Request accommodations", q)
    chat(client)
    client.post("/api/chat/dismiss")
    assert client.get(f"/api/questions/{q['id']}").json()["status"] == "dismissed"
    assert client.get("/api/inbox").json()["count"] == 0
    assert chat(client)["current"] is None


def test_with_no_question_waiting_a_message_goes_to_the_assistant(client, llm):
    llm.replies = ["Sounds like a busy week! Want me to help plan it?"]
    c = say(client, "I have a lot going on this week")
    assert assistant_texts(c)[-1] == "Sounds like a busy week! Want me to help plan it?"
    sent = llm.requests[0]["messages"]  # [1] is the actions pass
    assert sent[-1] == {"role": "user", "content": "I have a lot going on this week"}
    assert "Wednesday, September 30, 2026" in sent[0]["content"]


def test_the_chat_badge_counts_waiting_questions(client):
    src = source(client)
    ask(client, src, "A?")
    ask(client, src, "B?")
    assert client.get("/api/chat/badge").json() == {"questions": 2}


def test_a_plain_answer_is_acknowledged_by_the_next_question_not_a_thanks(client):
    src = source(client)
    ask(client, src, "Which paper are you presenting?")
    ask(client, src, "Which team are you on?")
    chat(client)
    texts = assistant_texts(say(client, "P10"))
    assert not any("Thanks" in t for t in texts)
    assert texts[-1].split(". ", 1)[0] + "." in ("Got it.", "Okay.", "Good to know.", "All right.", "Understood.")
    assert texts[-1].endswith("Which team are you on?")
    texts = assistant_texts(say(client, "Team 3"))
    assert texts[-1].endswith("That's all I wanted to ask for now.")
