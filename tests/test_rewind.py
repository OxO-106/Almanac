import json
from datetime import datetime

from app.clock import LA


def chat(client):
    return client.get("/api/chat").json()


def actions(*acts):
    return json.dumps({"actions": list(acts)})


def test_rewinding_a_message_removes_it_its_reply_and_what_it_added(client, llm, clock):
    clock.set(datetime(2026, 10, 1, 10, 0, tzinfo=LA))
    llm.replies = ["Sure.", actions({"type": "task", "title": "Email Prof. Chen", "quote": "email Prof. Chen tomorrow",
                                     "when": {"type": "in_days", "days": 1}})]
    client.post("/api/chat", json={"text": "I need to email Prof. Chen tomorrow"})
    (p,) = client.get("/api/inbox").json()["proposals"]
    client.post(f"/api/proposals/{p['id']}/accept")
    assert [t["title"] for t in client.get("/api/tasks").json()] == ["Email Prof. Chen"]
    mine = next(m for m in chat(client)["messages"] if m["role"] == "user")
    r = client.post(f"/api/chat/rewind/{mine['id']}").json()
    assert r["text"] == "I need to email Prof. Chen tomorrow"  # back in the reply box to edit
    assert r["messages"] == []
    assert client.get("/api/tasks").json() == []  # the accepted task is gone too
    assert client.get("/api/inbox").json()["proposals"] == []


def test_rewinding_an_answer_reopens_the_question_and_undoes_the_date(client, llm, clock):
    clock.set(datetime(2026, 10, 1, 10, 0, tzinfo=LA))
    src = client.post("/api/sources", json={"kind": "document", "title": "x.pdf", "text": "x"}).json()
    q = client.post("/api/questions", json={"source_id": src["id"], "text": "When is the report due?"}).json()
    p = client.post("/api/proposals", json={"source_id": src["id"], "summary": "Report", "question_id": q["id"],
                                             "ops": [{"op": "create", "kind": "deadlines", "data": {"title": "Report"}}]}).json()
    client.post("/api/questions", json={"source_id": src["id"], "text": "Which team are you on?"})
    chat(client)
    llm.replies = [json.dumps({"items": [{"n": 0, "when": {"type": "date", "month": 10, "day": 21}}]})]
    client.post("/api/chat", json={"text": "October 21"})
    assert client.get(f"/api/questions/{q['id']}").json()["status"] == "answered"
    assert chat(client)["current"]["text"].endswith("Which team are you on?")
    answer = [m for m in chat(client)["messages"] if m["role"] == "user"][-1]
    client.post(f"/api/chat/rewind/{answer['id']}")
    back = client.get(f"/api/questions/{q['id']}").json()
    assert (back["status"], back["answer"]) == ("open", None)
    (again,) = [x for x in client.get("/api/inbox").json()["proposals"] if x["id"] == p["id"]]
    assert "due" not in again["ops"][0]["data"]
    assert chat(client)["current"]["text"].endswith("When is the report due?")  # asked again


def test_only_your_own_messages_can_be_rewound(client):
    src = client.post("/api/sources", json={"kind": "document", "title": "x.pdf", "text": "x"}).json()
    client.post("/api/questions", json={"source_id": src["id"], "text": "Which paper?"})
    asked = chat(client)["messages"][0]
    assert client.post(f"/api/chat/rewind/{asked['id']}").status_code == 404
