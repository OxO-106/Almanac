import json

from test_upload import SYLLABUS, course_reply, item, items_reply, upload


def notes(client, kind):
    return [n for n in client.get("/api/notifications", params={"after": 0}).json() if n["kind"] == kind]


def test_a_read_document_says_its_suggestions_are_ready(client, llm):
    llm.replies = [course_reply(), items_reply(item())]
    upload(client, "cs239.txt", SYLLABUS.encode())
    (n,) = notes(client, "upload")
    assert n["title"] == "Suggestions ready"
    assert n["body"].endswith(": 2 suggestions.")
    assert n["url"] == "#inbox"


def test_a_document_that_could_not_be_read_says_so(client, llm):
    llm.replies = ["not json"]
    upload(client, "cs239.txt", SYLLABUS.encode())
    (n,) = notes(client, "upload")
    assert n["title"] == "Couldn't read cs239.txt"


def test_a_reply_you_watched_arrive_is_not_notified(client, llm):
    llm.replies = ["Sure.", json.dumps({"actions": []})]
    with client.stream("POST", "/api/chat/stream", json={"text": "hello"}) as r:
        list(r.iter_lines())
    assert notes(client, "chat") == []


def test_clearing_the_chat_keeps_open_questions(client, llm):
    llm.replies = ["Sure.", json.dumps({"actions": []})]
    client.post("/api/chat", json={"text": "hello"})
    client.post("/api/questions", json={"text": "Which paper did you pick?"})
    assert len(client.get("/api/chat").json()["messages"]) == 3
    after = client.post("/api/chat/clear").json()
    assert [m["text"] for m in after["messages"]] == ["Which paper did you pick?"]
