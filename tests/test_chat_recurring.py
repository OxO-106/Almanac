import json
from datetime import datetime

from app.clock import LA

MSG = ("CS269 is an online class, MW 2pm - 3:50PM, but I can only watch it later with the recording, "
       "so set due for watch recording before the next class. But also set event for online class time.")


def actions(*acts):
    return json.dumps({"actions": list(acts)})


def test_a_weekly_class_and_a_task_after_each_class(client, llm, clock):
    clock.set(datetime(2026, 10, 1, 15, 0, tzinfo=LA))
    client.post("/api/courses", json={"number": "COM SCI 269", "instructor": "Stefano Soatto"})
    client.post("/api/courses", json={"number": "CS 239", "instructor": "Robin Ding"})
    llm.replies = ["Got it.", actions(
        {"type": "task", "title": "Watch CS269 recording", "quote": "watch recording before the next class", "course": "CS269", "each_class": True},
        {"type": "event", "title": "CS269 online class", "quote": "CS269 is an online class, MW 2pm - 3:50PM", "course": "CS269",
         "days": "MO,WE", "start_time": "14:00", "end_time": "15:50"})]
    client.post("/api/chat", json={"text": MSG})
    props = {p["summary"]: p for p in client.get("/api/inbox").json()["proposals"]}
    cls = props["CS 269 · Soatto class meetings"]["ops"][0]["data"]
    assert (cls["repeat"], cls["start"][11:], cls["end"][11:], cls["course_id"]) == ("MO,WE", "14:00", "15:50", 1)  # not Ding's: "recording"
    (watch,) = [p for s, p in props.items() if s == "Watch CS269 recording after each class, before the next"]
    first, second = watch["ops"][0]["data"], watch["ops"][1]["data"]
    assert (first["title"], first["due"]) == ("Watch CS269 recording (Wed Sep 30)", "2026-10-05T14:00")  # yesterday's, due when the next class starts
    assert (second["title"], second["due"]) == ("Watch CS269 recording (Mon Oct 5)", "2026-10-07T14:00")
    assert all(o["data"]["course_id"] == 1 for o in watch["ops"])


def test_days_must_be_in_the_students_words():
    from app.chat import _days_said
    assert _days_said(["MO", "WE"], "MW 2pm - 3:50PM")
    assert _days_said(["TU", "TH"], "Tuesdays and Thursdays at 4")
    assert _days_said(["TU", "TH"], "TTh 10am")
    assert not _days_said(["MO", "WE"], "online class at 2pm")


def test_a_surname_inside_another_word_does_not_pick_the_course(client):
    from app.chat import _match_course
    client.post("/api/courses", json={"number": "COM SCI 269", "instructor": "Stefano Soatto"})
    client.post("/api/courses", json={"number": "CS 239", "instructor": "Robin Ding"})
    con = client.app.state.db
    assert _match_course(con, "CS269", "watch the recording") == 1
    assert _match_course(con, "Ding's class", "") == 2


def test_another_courses_class_is_new_not_a_change_to_one_already_planned(client, llm, clock):
    clock.set(datetime(2026, 10, 1, 15, 0, tzinfo=LA))
    c201 = client.post("/api/courses", json={"number": "CS 201", "instructor": "Remy Wang"}).json()
    client.post("/api/courses", json={"number": "CS 269", "instructor": "Stefano Soatto"})
    client.post("/api/events", json={"title": "CS 201 class", "course_id": c201["id"], "start": "2026-09-24T12:00", "repeat": "TU,TH", "until": "2026-12-04"})
    text = "CS 269 meets on Monday and Wednesday, 5PM - 7:50PM"
    llm.replies = ["Noted.", actions({"type": "event", "title": "CS 269 class", "quote": text, "course": "CS 269",
                                      "days": "MO,WE", "start_time": "17:00", "end_time": "19:50"})]
    client.post("/api/chat", json={"text": text})
    (p,) = client.get("/api/inbox").json()["proposals"]
    assert p["ops"][0]["op"] == "create"
    d = p["ops"][0]["data"]
    assert (d["repeat"], d["start"][11:], d["end"][11:]) == ("MO,WE", "17:00", "19:50")
    assert client.get("/api/events").json()[0]["start"] == "2026-09-24T12:00"  # the CS 201 seminar as it was
