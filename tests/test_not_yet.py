from datetime import datetime

import pytest

from app import chat
from app.clock import LA


def asked(client):
    return client.get("/api/chat").json()["current"]


def answer(client, text):
    client.post("/api/chat", json={"text": text})
    return client.get("/api/chat").json()["messages"][-1]["text"]


@pytest.fixture
def question(client, clock):
    clock.set(datetime(2026, 10, 1, 10, 0, tzinfo=LA))
    client.post("/api/questions", json={"text": "Which topic will you present?"})
    assert asked(client)


def test_not_yet_asks_again_in_a_week(client, clock, question):
    assert answer(client, "Haven't decide yet") == "No problem. I'll ask again on Thu, Oct 8."
    assert asked(client) is None
    clock.set(datetime(2026, 10, 8, 10, 0, tzinfo=LA))
    assert asked(client)["text"].endswith("Which topic will you present?")


def test_a_question_holding_something_up_comes_back_sooner(client, clock):
    clock.set(datetime(2026, 10, 1, 10, 0, tzinfo=LA))
    client.post("/api/questions", json={"text": "When is the project due?"})
    assert asked(client)
    assert answer(client, "I don't know") == "No problem. I'll ask again on Sun, Oct 4."


def test_when_to_ask_again_can_be_said(client, question):
    assert answer(client, "not sure yet, ask me in 2 days") == "No problem. I'll ask again on Sat, Oct 3."


def test_a_real_answer_is_still_an_answer(client, question):
    assert answer(client, "Not yet sure between ReAct and Reflexion, probably ReAct because I already read it twice") == "Thanks, noted."


@pytest.mark.parametrize("text", ["not yet", "Don't know", "idk", "No idea", "still deciding", "I haven't chosen", "dunno, next week"])
def test_ways_of_saying_not_yet(text):
    assert chat._later(text, False) == 7


def test_answers_that_are_not_not_yet():
    assert chat._later("ReAct", False) is None
    assert chat._later("Notably the second one", False) is None
