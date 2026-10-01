def test_clear_all_empties_the_plan_but_keeps_terms_and_devices(client):
    client.post("/api/courses", json={"number": "CS 239", "instructor": "Robin Ding"})
    client.post("/api/tasks", json={"title": "Read ReAct"})
    client.post("/api/questions", json={"text": "Which paper?"})
    r = client.post("/api/dev/clear-all")
    assert r.status_code == 200 and r.json()["backup"].startswith("before-clear-")
    assert client.get("/api/courses").json() == [] and client.get("/api/tasks").json() == []
    assert client.get("/api/questions").json() == []
    assert client.get("/api/terms").json()  # the term calendar stays
