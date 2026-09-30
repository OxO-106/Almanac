from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


class FakeClock:
    """Test time. Starts Wed Sep 30 2026, 10:00 in Los Angeles."""

    def __init__(self, now=datetime(2026, 9, 30, 17, 0, tzinfo=timezone.utc)):
        self._now = now

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt.astimezone(timezone.utc)

    def advance(self, **kw):
        self._now += timedelta(**kw)


class FakeLLM:
    """Scripted model: tests queue replies; every request is recorded."""

    def __init__(self):
        self.ready = True
        self.replies = []
        self.requests = []

    def status(self):
        if not self.ready:
            return {"model": "fake", "ready": False, "message": "Ollama is not running."}
        return {"model": "fake", "ready": True, "message": ""}

    def chat(self, messages, schema=None, **kw):
        self.requests.append({"messages": messages, "schema": schema})
        if not self.replies and schema and "questions" in schema.get("properties", {}):
            return '{"questions": []}'  # the questions pass, when a test doesn't script it
        return self.replies.pop(0)


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def llm():
    return FakeLLM()


@pytest.fixture
def client(tmp_path, clock, llm):
    app = create_app(db_path=tmp_path / "almanac.db", llm=llm, clock=clock)
    with TestClient(app) as c:
        yield c
