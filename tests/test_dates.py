import json

from test_upload import inbox, item, items_reply, upload


def course(meetings=(), number="COM SCI 269", instructor="Stefano Soatto", quote="Instructor: Stefano Soatto"):
    return json.dumps({"courses": [{"number": number, "instructor": instructor, "quote": quote, "meetings": list(meetings)}]})


DOC = """Advanced Topics in AI: Agentic Learning
Instructor: Stefano Soatto
Time and place: MW 6-7:30pm
Lectures Mondays and Wednesdays, 4:00-5:50 p.m.
Week 5: AI Functions practicum (midterm assessment)
Week 9 Monday: Project presentations
Thursday, October 29 — Phase 1 due by the start of class.
The draft requirements are due two days before Phase 1.
Tuesday, November 24 — Thanksgiving Break (No Class)
Syllabus (provisional)
"""


def props(client):
    return {p["summary"]: p for p in inbox(client)["proposals"]}


def data(p):
    return p["ops"][0]["data"]


def test_the_fall_2026_term_is_seeded_and_editable(client):
    (fall,) = [t for t in client.get("/api/terms").json() if t["name"] == "Fall 2026"]
    assert (fall["instruction_begins"], fall["week1"], fall["instruction_ends"]) == ("2026-09-24", "2026-09-28", "2026-12-04")
    assert "2026-11-11 Veterans Day" in fall["holidays"]
    r = client.patch(f"/api/terms/{fall['id']}", json={"holidays": fall["holidays"] + "\n2026-10-30 Campus closed"})
    assert "2026-10-30 Campus closed" in r.json()["holidays"]
    assert client.patch(f"/api/terms/{fall['id']}", json={"holidays": "Nov 11 Veterans Day"}).status_code == 422


def test_week_and_weekday_resolve_against_the_term(client, llm):
    llm.replies = [course(), items_reply(item(kind="event", title="Project presentations", quote="Week 9 Monday: Project presentations",
                                              when={"type": "week", "week": 9, "weekday": "MO"}))]
    upload(client, "cs269.txt", DOC.encode())
    d = data(props(client)["Project presentations"])
    assert (d["start"], d["provisional"]) == ("2026-11-23", True)


def test_a_week_without_a_day_keeps_the_week_and_asks_for_the_day(client, llm):
    llm.replies = [course(), items_reply(item(title="Midterm assessment", quote="Week 5: AI Functions practicum (midterm assessment)",
                                              when={"type": "week", "week": 5}))]
    upload(client, "cs269.txt", DOC.encode())
    p = props(client)["Midterm assessment"]
    assert (data(p)["due"], data(p)["window"], data(p)["provisional"]) == ("2026-10-26", "2026-10-26/2026-10-30", True)
    assert p["blocked_by"] is None
    assert [q["text"] for q in inbox(client)["questions"]] == [
        "Which day in Week 5 (Oct 26 – Oct 30) is “Midterm assessment”? The document only gives the week."]


def test_a_week_not_written_in_the_quote_is_not_trusted(client, llm):
    llm.replies = [course(), items_reply(item(title="Midterm assessment", quote="AI Functions practicum (midterm assessment)",
                                              when={"type": "week", "week": 5}))]
    upload(client, "cs269.txt", b"Instructor: Stefano Soatto\nThere will be an AI Functions practicum (midterm assessment).\n")
    assert "due" not in data(props(client)["Midterm assessment"])


def test_class_meetings_become_a_recurring_event_that_skips_holidays_and_no_class_days(client, llm):
    meeting = {"days": "MO,WE", "start": "16:00", "end": "17:50", "location": "", "quote": "Lectures Mondays and Wednesdays, 4:00-5:50 p.m."}
    no_class = item(kind="no_class", title="Thanksgiving Break", quote="Tuesday, November 24 — Thanksgiving Break (No Class)",
                    when={"type": "date", "month": 11, "day": 24})
    llm.replies = [course([meeting]), items_reply(no_class)]
    upload(client, "cs269.txt", DOC.encode())
    ev = data(props(client)["COM SCI 269 · Soatto class meetings"])
    assert (ev["start"], ev["end"], ev["repeat"], ev["until"]) == ("2026-09-28T16:00", "2026-09-28T17:50", "MO,WE", "2026-12-04")
    assert ev["skip"] == "2026-11-11,2026-11-24"
    assert "Thanksgiving Break" not in props(client)


def test_a_meeting_without_a_stated_time_is_asked_about(client, llm):
    meeting = {"days": "TU,TH", "start": "08:00", "end": "", "location": "", "quote": "Lectures Mondays and Wednesdays"}
    llm.replies = [course([meeting]), items_reply()]
    upload(client, "cs269.txt", DOC.encode())
    assert not any("class meetings" in s for s in props(client))
    assert [q["text"] for q in inbox(client)["questions"]] == [
        "What time does COM SCI 269 · Soatto meet on TU/TH? The document doesn't say."]


def test_relative_dates_resolve_from_another_item_in_the_document(client, llm):
    phase1 = item(title="Phase 1", quote="Thursday, October 29 — Phase 1 due", when={"type": "date", "month": 10, "day": 29})
    draft = item(title="Draft requirements", quote="The draft requirements are due two days before Phase 1",
                 when={"type": "relative", "relative_to": "Phase 1", "offset_days": -2})
    llm.replies = [course(), items_reply(phase1, draft)]
    upload(client, "kim.txt", DOC.encode())
    assert data(props(client)["Draft requirements"])["due"] == "2026-10-27"


def test_a_relative_offset_not_written_in_the_quote_is_not_trusted(client, llm):
    phase1 = item(title="Phase 1", quote="Thursday, October 29 — Phase 1 due", when={"type": "date", "month": 10, "day": 29})
    draft = item(title="Draft requirements", quote="The draft requirements are due",
                 when={"type": "relative", "relative_to": "Phase 1", "offset_days": -1})
    llm.replies = [course(), items_reply(phase1, draft)]
    upload(client, "kim.txt", DOC.encode())
    assert "due" not in data(props(client)["Draft requirements"])


SCHEDULE = """Date Topic Reading List Due
Fri Oct 9
No Class
—
Project
Team List
Due
Mon Oct 12
Model Architecture: Low-rank Adapter LoRA
"""


def test_an_undated_item_takes_the_nearest_date_heading_above_it(client, llm):
    text = "Wed Oct 7 Language Modeling\n" + SCHEDULE
    team = item(title="Project team list", quote="Project Team List Due", when={"type": "unknown"})
    llm.replies = [course(), items_reply(team)]
    upload(client, "cs239.txt", text.encode())
    p = props(client)["Project team list"]
    assert data(p)["due"] == "2026-10-09"  # not Oct 7 (further up) nor Oct 12 (below)
    assert p["quote"] == "Fri Oct 9 … Project Team List Due"
    assert inbox(client)["questions"] == []


def test_a_print_timestamp_is_not_a_date_heading(client, llm):
    text = "9/30/26, 9:57 AM CS 239 Fall 2026 Course Schedule\nSeptember 30, 2026, 9:57 AM\nTutorial: Multi-Agent Frameworks\n"
    tut = item(kind="event", title="Tutorial", quote="Tutorial: Multi-Agent Frameworks", when={"type": "unknown"})
    llm.replies = [course(), items_reply(tut)]
    upload(client, "kim.txt", text.encode())
    assert "start" not in data(props(client)["Tutorial"])


def test_a_date_heading_too_far_above_is_not_used(client, llm):
    text = "Fri Oct 9\n" + "filler line\n" * 20 + "Project Team List Due\n"
    llm.replies = [course(), items_reply(item(title="Project team list", quote="Project Team List Due", when={"type": "unknown"}))]
    upload(client, "cs239.txt", text.encode())
    assert "due" not in data(props(client)["Project team list"])


def test_a_week_heading_counts(client, llm):
    text = "Week 5: A language and framework for controlling LLMs\n(introduction)\nAI Functions practicum (midterm assessment)\n"
    llm.replies = [course(), items_reply(item(title="Midterm assessment", quote="AI Functions practicum (midterm assessment)",
                                              when={"type": "unknown"}))]
    upload(client, "cs269.txt", text.encode())
    assert data(props(client)["Midterm assessment"])["window"] == "2026-10-26/2026-10-30"


def test_skipped_dates_are_left_out_of_the_calendar(client):
    client.post("/api/events", json={"title": "Lecture", "start": "2026-09-28T16:00", "repeat": "MO,WE", "skip": "2026-11-11"})
    starts = [e["start"] for e in client.get("/api/calendar", params={"start": "2026-11-09", "end": "2026-11-13"}).json()["events"]]
    assert starts == ["2026-11-09T16:00"]


def test_answering_which_day_in_the_week_dates_the_item_even_once_accepted(client, llm):
    llm.replies = [course(), items_reply(item(title="Midterm assessment", quote="Week 5: AI Functions practicum (midterm assessment)",
                                              when={"type": "week", "week": 5}))]
    upload(client, "cs269.txt", DOC.encode())
    for p in inbox(client)["proposals"]:
        client.post(f"/api/proposals/{p['id']}/accept")
    (deadline,) = client.get("/api/deadlines").json()
    assert deadline["window"] == "2026-10-26/2026-10-30"
    assert client.get("/api/chat").json()["current"]["text"].endswith("Which day in Week 5 (Oct 26 – Oct 30) is “Midterm assessment”? "
                                                                      "The document only gives the week.")
    llm.replies = [json.dumps({"items": [{"n": 0, "when": {"type": "weekday", "weekday": "WE"}}]})]
    client.post("/api/chat", json={"text": "It's on Wednesday"})
    (deadline,) = client.get("/api/deadlines").json()
    assert (deadline["due"], deadline["window"], deadline["provisional"]) == ("2026-10-28", None, 0)  # Week 5's Wednesday
    assert "Updated Midterm assessment: Wed Oct 28." in client.get("/api/chat").json()["messages"][-1]["text"]


def test_answering_with_tomorrow_dates_a_waiting_suggestion(client, llm, clock):
    llm.replies = [course(), items_reply(item(title="Midterm assessment", quote="Week 5: AI Functions practicum (midterm assessment)",
                                              when={"type": "week", "week": 5}))]
    upload(client, "cs269.txt", DOC.encode())
    client.get("/api/chat")
    llm.replies = [json.dumps({"items": [{"n": 0, "when": {"type": "in_days", "days": 1}}]})]
    client.post("/api/chat", json={"text": "I plan to finish it by the end of tomorrow"})
    d = data(props(client)["Midterm assessment"])
    assert d["due"] == (clock.now().date() + __import__("datetime").timedelta(days=1)).isoformat()
    assert "window" not in d and "provisional" not in d


CS259 = """CS 259 Seminal Achievements in Computer Science
Lecture: MW 2:00pm - 3:50pm
Short presentations each week.
"""


def test_class_times_are_kept_when_the_instructor_is_not_named(client, llm):
    llm.replies = [json.dumps({"courses": [{"number": "CS 259", "instructor": "", "title": "Seminal Achievements in Computer Science",
                                            "quote": "CS 259 Seminal Achievements in Computer Science",
                                            "meetings": [{"days": "MO,WE", "start": "14:00", "end": "15:50", "quote": "Lecture: MW 2:00pm - 3:50pm"}]}]}),
                   items_reply()]
    upload(client, "cs259.pdf.txt", CS259.encode())
    cls = data(props(client)["CS 259 class meetings"])
    assert (cls["repeat"], cls["start"][11:], cls["end"][11:]) == ("MO,WE", "14:00", "15:50")


def test_a_lecture_item_with_a_weekly_time_becomes_a_weekly_event_not_a_question(client, llm):
    llm.replies = [json.dumps({"courses": [{"number": "CS 259", "instructor": "", "title": "Seminal Achievements in Computer Science",
                                            "quote": "CS 259 Seminal Achievements in Computer Science", "meetings": []}]}),
                   items_reply(item(kind="event", title="Lecture", course="CS 259", quote="Lecture: MW 2:00pm - 3:50pm", when={"type": "unknown"}))]
    upload(client, "cs259.txt", CS259.encode())
    cls = data(props(client)["CS 259 class meetings"])
    assert (cls["repeat"], cls["start"][11:], cls["end"][11:]) == ("MO,WE", "14:00", "15:50")
    assert not any("When is" in q["text"] for q in inbox(client)["questions"])


def test_answering_when_with_a_weekly_time_and_a_link_makes_a_weekly_event(client, llm):
    src = client.post("/api/sources", json={"kind": "document", "title": "x.pdf", "text": "x"}).json()
    q = client.post("/api/questions", json={"source_id": src["id"], "text": "When is “Lecture”? The document doesn't say."}).json()
    client.post("/api/proposals", json={"source_id": src["id"], "summary": "Lecture", "question_id": q["id"],
                                        "ops": [{"op": "create", "kind": "deadlines", "data": {"title": "Lecture"}}]})
    client.get("/api/chat")
    client.post("/api/chat", json={"text": "Lecture: MW 2:00pm - 3:50pm\nAnd it's online, so add this Zoom Link: https://ucla.zoom.us/j/123"})
    (p,) = inbox(client)["proposals"]
    o = p["ops"][0]
    assert o["kind"] == "events"
    assert (o["data"]["repeat"], o["data"]["start"][11:], o["data"]["end"][11:], o["data"]["location"]) == ("MO,WE", "14:00", "15:50", "https://ucla.zoom.us/j/123")
    assert "Updated Lecture: every Mo/We, 2:00 PM–3:50 PM." in client.get("/api/chat").json()["messages"][-1]["text"]


def test_presentation_slots_become_one_question_with_the_dates_as_buttons(client, llm):
    doc = "Mon Nov 30 Final project report\nWed Dec 2 Final project report\n"
    choice = {"kind": "choice", "title": "Final project report", "course": "CS 239", "quote": "Mon Nov 30 Final project report",
              "when": {"type": "unknown"}, "options": [
                  {"when": {"type": "date", "month": 11, "day": 30}, "quote": "Mon Nov 30 Final project report"},
                  {"when": {"type": "date", "month": 12, "day": 2}, "quote": "Wed Dec 2 Final project report"}]}
    llm.replies = [course(), items_reply(choice)]
    upload(client, "ding.txt", doc.encode())
    box = inbox(client)
    slots = [p for p in box["proposals"] if p["summary"] == "Final project report"]
    assert sorted(data(p)["start"] for p in slots) == ["2026-11-30", "2026-12-02"]
    assert all(p["blocked_by"] == "Which day is your “Final project report”: Mon Nov 30 or Wed Dec 2?" for p in slots)
    assert client.get("/api/chat").json()["current"]["options"] == ["Mon Nov 30", "Wed Dec 2"]
    client.post("/api/chat", json={"text": "Wed Dec 2"})
    (left,) = [p for p in inbox(client)["proposals"] if p["summary"] == "Final project report"]
    assert data(left)["start"] == "2026-12-02" and left["blocked_by"] is None


def test_office_hours_are_offered_unticked_and_a_location_must_be_in_the_document(client, llm):
    doc = "Advanced Topics in AI\nInstructor: Stefano Soatto\nLectures MW 6-7:30pm, Room 1200\nOffice hours: Tue 3-4pm\n"
    llm.replies = [course(meetings=[
        {"type": "lecture", "days": "MO,WE", "start": "18:00", "end": "19:30", "location": "Room 1200", "quote": "Lectures MW 6-7:30pm, Room 1200"},
        {"type": "office_hours", "days": "TU", "start": "15:00", "end": "16:00", "location": "Boelter 3532", "quote": "Office hours: Tue 3-4pm"}]),
        items_reply()]
    upload(client, "cs269.txt", doc.encode())
    got = props(client)
    lecture, office = got["COM SCI 269 · Soatto class meetings"], got["COM SCI 269 office hours (weekly)"]
    assert data(lecture)["location"] == "Room 1200"
    assert "location" not in data(office)  # "Boelter 3532" isn't in the document
    assert office["optional"] and not lecture["optional"]
    src = client.get("/api/sources").json()[0]
    client.post(f"/api/sources/{src['id']}/accept-all")
    assert [p["summary"] for p in inbox(client)["proposals"]] == ["COM SCI 269 office hours (weekly)"]  # left for the student


def test_optional_readings_are_not_tasks(client, llm):
    doc = "Lecture 5: Tuesday, October 13 — Interfaces\nP5. SWE-agent [Required — Lecture 5]\nCodeAct [Optional — team presentations]\n"
    llm.replies = [course(), items_reply(
        item(kind="task", title="Read P5. SWE-agent", quote="P5. SWE-agent [Required — Lecture 5]", when={"type": "unknown"}),
        item(kind="task", title="Read CodeAct", quote="CodeAct [Optional — team presentations]", when={"type": "unknown"}))]
    upload(client, "kim.txt", doc.encode())
    assert [p["summary"] for p in inbox(client)["proposals"] if p["summary"].startswith("Read")] == ["Read P5. SWE-agent"]
