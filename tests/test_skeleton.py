def test_health_reports_ready_model(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["ai"] == {"model": "fake", "ready": True, "message": ""}


def test_health_explains_when_ollama_is_down(client, llm):
    llm.ready = False
    assert client.get("/api/health").json()["ai"]["message"] == "Ollama is not running."


def test_health_reports_local_time(client, clock):
    # 17:00 UTC on Sep 30 is 10:00 in Los Angeles (PDT).
    assert client.get("/api/health").json()["now"] == "2026-09-30T10:00:00-07:00"


def test_today_page_is_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Almanac" in r.text
