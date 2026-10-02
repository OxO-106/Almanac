"""Lecture kinds, read from the syllabus: the course's usual kind, presentation days, papers per class."""
import json

from app import recordings
from test_dates import DOC, course, props
from test_upload import item, items_reply, upload

DING = ("Instructor: Robin Ding\nThis seminar course will discuss the impactful papers.\nSchedule\nReadings are listed by lecture date.\n"
        "Mon Oct 5\nModel Architecture:\nGQA: Training Generalized\nMulti-Query Transformer\n"
        "Wed Oct 7\nLanguage Modeling\nWed Oct 14\nCourse project proposal\n")


def ding(client, llm):
    llm.replies = [course(number="CS 239", instructor="Robin Ding", quote="Instructor: Robin Ding"), items_reply()]
    llm.readings = [json.dumps({"readings": [{"title": "GQA: Training Generalized Multi-Query Transformer"}]})]
    llm.lectures = [json.dumps({"usual": {"kind": "paper_session", "quote": "This seminar course will discuss the impactful papers."},
                                "presentation_days": [{"when": {"type": "date", "month": 10, "day": 14}, "quote": "Wed Oct 14 Course project proposal"}]})]
    upload(client, "ding.txt", DING.encode())
    client.get("/api/chat")
    client.post("/api/chat", json={"text": "Yes"})  # add the readings
    for p in client.get("/api/inbox").json()["proposals"]:
        client.post(f"/api/proposals/{p['id']}/accept")
    return client.get("/api/courses").json()[0]["id"]


def test_each_class_date_gets_its_kind_and_papers(client, llm):
    c = ding(client, llm)
    con = client.app.state.db
    oct5 = recordings.lecture_kind(con, c, "2026-10-05")
    assert (oct5["kind"], oct5["papers"]) == ("paper_session", ["GQA: Training Generalized Multi-Query Transformer"])
    assert recordings.lecture_kind(con, c, "2026-10-14")["kind"] == "presentation_day"
    assert recordings.lecture_kind(con, c, "2026-10-07") == {  # nothing listed that day: the course's usual kind
        "kind": "paper_session", "papers": [], "quote": "This seminar course will discuss the impactful papers."}


def test_a_presentation_week_covers_its_days_and_a_concept_course_is_usually_lectures(client, llm):
    llm.replies = [course(), items_reply()]
    llm.lectures = [json.dumps({"usual": {"kind": "concept_lecture", "quote": "Week 5: AI Functions practicum (midterm assessment)"},
                                "presentation_days": [{"when": {"type": "week", "week": 9}, "quote": "Week 9 Monday: Project presentations"}]})]
    upload(client, "cs269.txt", DOC.encode())
    (p,) = [p for s, p in props(client).items() if s.startswith("Add course")]
    client.post(f"/api/proposals/{p['id']}/accept")
    c = client.get("/api/courses").json()[0]["id"]
    con = client.app.state.db
    assert recordings.lecture_kind(con, c, "2026-11-25")["kind"] == "presentation_day"  # in Week 9 (Nov 23-27)
    assert recordings.lecture_kind(con, c, "2026-10-12")["kind"] == "concept_lecture"


def test_a_kind_whose_quote_isnt_in_the_syllabus_is_not_kept(client, llm):
    llm.replies = [course(), items_reply()]
    llm.lectures = [json.dumps({"usual": {"kind": "paper_session", "quote": "Students present a paper each week."}, "presentation_days": []})]
    upload(client, "cs269.txt", DOC.encode())
    (p,) = [p for s, p in props(client).items() if s.startswith("Add course")]
    client.post(f"/api/proposals/{p['id']}/accept")
    assert recordings.lecture_kind(client.app.state.db, client.get("/api/courses").json()[0]["id"], "2026-10-12") is None


def test_a_recording_takes_its_lectures_kind(client, llm, transcriber):
    c = ding(client, llm)
    transcriber.segments = [{"start": 0.0, "end": 5.0, "text": "Today's paper is GQA."}]
    r = client.post(f"/api/recordings?course_id={c}&date=2026-10-05", files={"file": ("l.m4a", b"x", "audio/mp4")}).json()
    rec = client.get(f"/api/recordings/{r['id']}").json()
    assert (rec["kind"], rec["kind_name"], rec["papers"]) == ("paper_session", "Paper session", ["GQA: Training Generalized Multi-Query Transformer"])


def test_presentation_days_come_from_the_schedule_not_only_the_model(client, llm):
    doc = ("Instructor: Robin Ding\nSchedule\nReadings are listed by lecture date.\n"
           "Wed Oct 14\nCourse project proposal\n"
           "Wed Oct 21\nZeRO: Memory Optimizations\nToward Training Trillion\nProposal\none-pager\n"
           "Wed Nov 11\nNo class\nMidterm\nreport due\n")
    llm.replies = [course(number="CS 239", instructor="Robin Ding", quote="Instructor: Robin Ding"), items_reply()]
    llm.readings = [json.dumps({"readings": [{"title": "ZeRO: Memory Optimizations Toward Training Trillion"}]})]
    # the model misses Oct 14 and names Oct 21, where a one-pager is only handed in
    llm.lectures = [json.dumps({"presentation_days": [{"when": {"type": "date", "month": 10, "day": 21}, "quote": "Wed Oct 21 ... Proposal one-pager"}]})]
    upload(client, "ding.txt", doc.encode())
    (p,) = [p for s, p in props(client).items() if s.startswith("Add course")]
    client.post(f"/api/proposals/{p['id']}/accept")
    c, con = client.get("/api/courses").json()[0]["id"], client.app.state.db
    assert recordings.lecture_kind(con, c, "2026-10-14")["kind"] == "presentation_day"   # the row names a project, no papers
    assert recordings.lecture_kind(con, c, "2026-10-21")["kind"] == "paper_session"      # papers; the one-pager is handed in
    assert recordings.lecture_kind(con, c, "2026-11-11") is None                         # no class (and no usual kind given)
