import json
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
        self.rows = []
        self.readings = []
        self.lectures, self.lecture_requests = [], []
        self.notes, self.notes_requests, self.announced, self.announce_requests = [], [], [], []
        self.changes, self.change_requests = [], []
        self.questions, self.question_requests, self.paper_answers, self.paper_answer_requests = [], [], [], []
        self.requests = []

    def status(self):
        if not self.ready:
            return {"model": "fake", "ready": False, "message": "Ollama is not running."}
        return {"model": "fake", "ready": True, "message": ""}

    def chat(self, messages, schema=None, **kw):
        if messages[0]["content"].startswith("You read the transcript of a university lecture"):
            # what a lecture announced: scripted with llm.announced
            self.announce_requests.append({"messages": messages, "schema": schema})
            return self.announced.pop(0) if self.announced else json.dumps({"items": []})
        if messages[0]["content"].startswith("You change a university student's lecture notes"):
            # a change request to a lecture's notes: scripted with llm.changes (the sections changed)
            self.change_requests.append({"messages": messages, "schema": schema})
            return self.changes.pop(0) if self.changes else json.dumps({"summary": "", "sections": []})
        if messages[0]["content"].startswith("You list the questions asked"):
            # a paper session's questions, a part at a time: scripted with llm.questions
            self.question_requests.append({"messages": messages, "schema": schema})
            return self.questions.pop(0) if self.questions else json.dumps({"questions": []})
        if messages[0]["content"].startswith("You add what the papers say"):
            # the papers' answers to those questions: scripted with llm.paper_answers
            self.paper_answer_requests.append({"messages": messages, "schema": schema})
            return self.paper_answers.pop(0) if self.paper_answers else json.dumps({"answers": []})
        if messages[0]["content"].startswith(("You write study notes", "You combine the notes")):
            # lecture notes: scripted with llm.notes, logged apart
            self.notes_requests.append({"messages": messages, "schema": schema})
            return self.notes.pop(0) if self.notes else "## Notes\n- (not scripted)"
        if "how this course's class meetings are run" in messages[0]["content"]:
            # the syllabus reader's last step, Lecture kinds: scripted with llm.lectures, logged apart
            self.lecture_requests.append({"messages": messages, "schema": schema})
            return self.lectures.pop(0) if self.lectures else json.dumps({"presentation_days": []})
        self.requests.append({"messages": messages, "schema": schema})
        if "which the first reading found nothing in" in messages[0]["content"]:
            # the schedule-row coverage pass: tests script it with llm.rows
            return self.rows.pop(0) if self.rows else json.dumps({"items": []})
        if "lists readings (papers, chapters) under class dates" in messages[0]["content"]:
            # the reading-list pass: tests script it with llm.readings
            return self.readings.pop(0) if self.readings else json.dumps({"readings": []})
        if not self.replies and schema:
            # passes a test doesn't script: the questions pass, chat actions
            for key in ("questions", "actions", "segments"):
                if key in schema.get("properties", {}):
                    return json.dumps({key: []})
        return self.replies.pop(0)

    def stream(self, messages, **kw):
        self.requests.append({"messages": messages, "schema": None})
        text = self.replies.pop(0)
        half = len(text) // 2
        yield text[:half]
        yield text[half:]


class FakeTranscriber:
    """Parakeet's stand-in: `segments` is what the next file transcribes to."""
    def __init__(self):
        self.segments, self.seconds, self.files, self.error = [], 0.0, [], None

    def file(self, path):
        self.files.append(path)
        if self.error:
            raise RuntimeError(self.error)
        return [dict(s) for s in self.segments], self.seconds

    caption = staticmethod(lambda pcm16: "")  # what a caption window reads as; tests set it

    def window(self, pcm16):
        return self.caption(pcm16)


@pytest.fixture(autouse=True)
def papercut(tmp_path, monkeypatch):
    """Papercut's library, empty unless a test puts papers in it (never the real one)."""
    from app import papers
    root = tmp_path / "papercut"
    (root / "papers").mkdir(parents=True)
    monkeypatch.setattr(papers, "LIBRARY", root)
    return root


@pytest.fixture
def transcriber():
    return FakeTranscriber()


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def llm():
    return FakeLLM()


@pytest.fixture
def client(tmp_path, clock, llm, transcriber):
    app = create_app(db_path=tmp_path / "almanac.db", llm=llm, clock=clock, transcriber=transcriber)
    with TestClient(app) as c:
        yield c
