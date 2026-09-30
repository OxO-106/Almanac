def test_memories_can_be_added_edited_and_deleted(client):
    m = client.post("/api/memories", json={"text": "I read papers slowly, about 3 pages an hour", "topic": "work habits"}).json()
    client.patch(f"/api/memories/{m['id']}", json={"text": "I read papers at about 4 pages an hour"})
    assert [x["text"] for x in client.get("/api/memories").json()] == ["I read papers at about 4 pages an hour"]
    client.delete(f"/api/memories/{m['id']}")
    assert client.get("/api/memories").json() == []


def test_a_memory_proposal_is_remembered_only_when_accepted(client):
    p = client.post("/api/proposals", json={"summary": "Remember: prefers working at night", "quote": "I'm useless before 10am",
                                            "ops": [{"op": "create", "kind": "memories", "data": {"text": "Works best after 10am"}}]}).json()
    assert client.get("/api/memories").json() == []
    client.post(f"/api/proposals/{p['id']}/accept")
    assert [m["text"] for m in client.get("/api/memories").json()] == ["Works best after 10am"]


def test_capacity_defaults_to_six_and_ten_hours_and_can_change(client):
    assert client.get("/api/capacity").json() == {"weekday": 6, "weekend": 10}
    assert client.put("/api/capacity", json={"weekday": 5, "weekend": 8}).json() == {"weekday": 5, "weekend": 8}
    assert client.get("/api/capacity").json() == {"weekday": 5, "weekend": 8}
    assert client.put("/api/capacity", json={"weekday": 30, "weekend": 8}).status_code == 422
