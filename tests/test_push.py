import json
from datetime import datetime

import pytest

from app import push
from app.clock import LA

SUB = {"endpoint": "https://web.push.apple.com/QxYz", "keys": {"p256dh": "BPk3", "auth": "c2Vj"}}


class Gone(Exception):
    def __init__(self):
        self.response = type("R", (), {"status_code": 410})()


@pytest.fixture
def sent(monkeypatch):
    calls = []
    monkeypatch.setattr(push, "BACKGROUND", False)
    monkeypatch.setattr(push, "send", lambda sub, payload, key, claims: calls.append((sub, json.loads(payload), claims)))
    return calls


def test_the_public_key_is_generated_once_and_kept(client):
    a = client.get("/api/push/key").json()["key"]
    assert a and client.get("/api/push/key").json()["key"] == a


def test_notifications_are_pushed_to_subscribed_devices(client, clock, sent):
    client.post("/api/push/subscribe", json=SUB, headers={"origin": "https://oxo.tail2efc87.ts.net:8443"})
    clock.set(datetime(2026, 9, 30, 9, 0, tzinfo=LA))
    client.post("/api/scheduler/tick")  # the 9am briefing
    (sub, payload, claims), = sent
    assert sub == SUB
    assert payload["title"] == "Good morning: your Wed Sep 30" and payload["url"] == "#today"
    assert claims == {"sub": "https://oxo.tail2efc87.ts.net"}


def test_a_device_that_unsubscribed_is_forgotten(client, clock, monkeypatch):
    monkeypatch.setattr(push, "BACKGROUND", False)

    def gone(*a):
        raise Gone()
    monkeypatch.setattr(push, "send", gone)
    client.post("/api/push/subscribe", json=SUB)
    clock.set(datetime(2026, 9, 30, 9, 0, tzinfo=LA))
    client.post("/api/scheduler/tick")
    assert client.get("/api/push/devices").json() == {"count": 0}


def test_unsubscribing_stops_pushes(client, clock, sent):
    client.post("/api/push/subscribe", json=SUB)
    assert client.get("/api/push/devices").json() == {"count": 1}
    client.post("/api/push/unsubscribe", json={"endpoint": SUB["endpoint"]})
    clock.set(datetime(2026, 9, 30, 9, 0, tzinfo=LA))
    client.post("/api/scheduler/tick")
    assert sent == []


def test_a_test_push_can_be_sent(client, sent):
    client.post("/api/push/subscribe", json=SUB)
    client.post("/api/push/test")
    assert sent[0][1]["title"] == "Notifications are on"


def test_the_service_worker_is_served_from_the_root(client):
    r = client.get("/sw.js")
    assert r.status_code == 200 and "javascript" in r.headers["content-type"] and "showNotification" in r.text
