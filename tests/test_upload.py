import io
import json

import docx
import pymupdf

SYLLABUS = """CS 239: Large Language Models and Code Intelligence
Instructor: Robin Ding
Lectures Mondays and Wednesdays, 4:00-5:50 p.m.
Select a paper and register using the paper presentation sign-up sheet
by October 5.
Wed Nov 11 No class Midterm report due
"""


def course_reply(courses=None):
    return json.dumps({"courses": courses if courses is not None else [
        {"number": "CS 239", "instructor": "Robin Ding", "title": "Large Language Models and Code Intelligence",
         "quote": "Instructor: Robin Ding", "meetings": []}]})


def items_reply(*items):
    return json.dumps({"items": list(items)})


def item(kind="deadline", title="Paper registration", quote="register using the paper presentation sign-up sheet by October 5",
         when=None, **extra):
    return {"kind": kind, "title": title, "course": "CS 239", "quote": quote,
            "when": when or {"type": "date", "month": 10, "day": 5}, "provisional": False, **extra}


def upload(client, name, data, mime="text/plain"):
    r = client.post("/api/uploads", files={"file": (name, data, mime)})
    assert r.status_code == 202, r.text
    return client.get(f"/api/sources/{r.json()['id']}").json()


def inbox(client):
    return {**client.get("/api/inbox").json(), "questions": client.get("/api/questions").json()}


def test_syllabus_items_become_proposals_with_their_quotes(client, llm):
    llm.replies = [course_reply(), items_reply(item())]
    src = upload(client, "cs239.txt", SYLLABUS.encode())
    assert src["status"] == "done"

    box = inbox(client)
    course, deadline = box["proposals"]
    assert course["ops"][0]["data"] == {"number": "CS 239", "instructor": "Robin Ding",
                                        "title": "Large Language Models and Code Intelligence"}
    assert deadline["ops"][0] == {"op": "create", "kind": "deadlines", "data": {
        "title": "Paper registration", "due": "2026-10-05", "course_id": f"$p{course['id']}.0"}}
    assert deadline["quote"] == "register using the paper presentation sign-up sheet by October 5"
    assert deadline["source"]["title"] == "cs239.txt"


def test_quotes_match_across_line_breaks_and_spacing(client, llm):
    llm.replies = [course_reply(), items_reply(item(quote="sign-up sheet  by October 5."))]
    upload(client, "cs239.txt", SYLLABUS.encode())
    assert len(inbox(client)["proposals"]) == 2


def test_a_quote_shortened_with_an_ellipsis_must_have_every_piece_in_order(client, llm):
    good = item(title="Midterm report", quote="Wed Nov 11 ... Midterm report due", when={"type": "date", "month": 11, "day": 11})
    spliced = item(title="Fake", quote="Midterm report due ... Robin Ding", when={"type": "date", "month": 11, "day": 11})
    llm.replies = [course_reply(), items_reply(good, spliced)]
    src = upload(client, "cs239.txt", SYLLABUS.encode())
    assert [p["summary"] for p in inbox(client)["proposals"]][1:] == ["Midterm report"]
    assert [d["title"] for d in src["dropped"]] == ["Fake"]


def test_a_question_item_without_question_text_still_reaches_the_inbox(client, llm):
    llm.replies = [course_reply(), items_reply(item(kind="question", title="Which paper to present", when={"type": "unknown"}))]
    upload(client, "cs239.txt", SYLLABUS.encode())
    assert [q["text"] for q in inbox(client)["questions"]] == ["Which paper to present"]


TABLE = """Date Topic Reading List Due
Fri Oct 9
No Class
—
Project
Team List
Due
Mon Nov 30
Final project report
"""


def test_a_quote_may_skip_table_cells_but_its_words_must_appear_in_order_nearby(client, llm):
    ok = item(title="Team list", quote="Fri Oct 9 Project Team List Due", when={"type": "date", "month": 10, "day": 9})
    scattered = item(title="Scrambled", quote="Fri Oct 9 Final project report", when={"type": "date", "month": 10, "day": 9})
    llm.replies = [course_reply([]), items_reply(ok, scattered)]
    src = upload(client, "schedule.txt", TABLE.encode())
    assert [p["summary"] for p in inbox(client)["proposals"]] == ["Team list"]
    assert [d["title"] for d in src["dropped"]] == ["Scrambled"]


def test_a_date_not_written_in_the_quote_is_not_trusted(client, llm):
    # The model says Nov 23; the document's row says Nov 30.
    wrong = item(title="Final project report", quote="Final project report", when={"type": "date", "month": 11, "day": 23})
    llm.replies = [course_reply([]), items_reply(wrong)]
    upload(client, "schedule.txt", TABLE.encode())
    (p,) = inbox(client)["proposals"]
    assert p["ops"][0]["data"]["due"] == "2026-11-30"


def test_an_item_with_no_date_anywhere_is_asked_about(client, llm):
    llm.replies = [course_reply([]), items_reply(item(title="Final report", quote="Final project report", when={"type": "unknown"}))]
    upload(client, "notes.txt", b"Some intro text.\nThe Final project report is six pages.\n")
    box = inbox(client)
    (p,) = box["proposals"]
    assert "due" not in p["ops"][0]["data"]
    assert [q["text"] for q in box["questions"]] == ["When is “Final report” due? The document doesn't say."]
    assert p["blocked_by"] == box["questions"][0]["text"]


def test_an_ellipsis_may_skip_a_table_rows_cells_but_not_whole_rows(client, llm):
    text = ("Wed Oct 21 Distributed Training: Memory Optimization ZeRO: Memory Optimizations Toward Training "
            "Trillion Parameter Models ZeRO-Infinity: Breaking the GPU Memory Wall Proposal one-pager Due\n"
            "Mon Nov 23 Cyber Security: Benchmark CyberGym: Evaluating AI Agents' Real-World Cybersecurity Capabilities "
            "at Scale ExploitGym: Can AI Agents Turn Security Vulnerabilities into Real Attacks? Cyber Security: Training "
            "Training Language Model Agents to Find Vulnerabilities with CTF-Dojo CVE-Factory: Scaling Expert-Level "
            "Agentic Tasks for Code Security Vulnerability Wed Nov 25 Formal Verification: Benchmark Vero Aristotle\n"
            "Mon Nov 30 Final project report\n")
    one_pager = item(title="Proposal one-pager", quote="Wed Oct 21 ... Proposal one-pager Due",
                     when={"type": "date", "month": 10, "day": 21})
    wrong_row = item(title="Final project report", quote="Mon Nov 23 ... Final project report",
                     when={"type": "date", "month": 11, "day": 23})
    llm.replies = [course_reply([]), items_reply(one_pager, wrong_row)]
    src = upload(client, "schedule.txt", text.encode())
    assert [p["summary"] for p in inbox(client)["proposals"]] == ["Proposal one-pager"]
    assert [d["title"] for d in src["dropped"]] == ["Final project report"]


def test_an_undated_task_is_proposed_without_a_question(client, llm):
    llm.replies = [course_reply([]), items_reply(item(kind="task", title="Read papers before lectures",
                                                      quote="Select a paper", when={"type": "unknown"}))]
    upload(client, "cs239.txt", SYLLABUS.encode())
    box = inbox(client)
    assert [p["summary"] for p in box["proposals"]] == ["Read papers before lectures"]
    assert box["questions"] == []


def test_a_course_without_a_named_instructor_is_asked_about(client, llm):
    llm.replies = [course_reply([{"number": "CS 239", "instructor": "", "quote": "CS 239: Large Language Models", "meetings": []}]),
                   items_reply(item())]
    upload(client, "kim.txt", SYLLABUS.encode())
    box = inbox(client)
    course, deadline = box["proposals"]
    assert course["blocked_by"] == "Who teaches CS 239 in “kim.txt”? The document doesn't name the instructor."
    assert deadline["ops"][0]["data"]["course_id"] == f"$p{course['id']}.0"


def test_a_time_not_written_in_the_quote_is_dropped_but_the_date_kept(client, llm):
    text = "Thursday, October 29 — Phase 1 is due by the start of class.\nLectures Mondays and Wednesdays, 4:00-5:50 p.m.\nOct 5 at 4 PM: sign-up"
    invented = item(title="Phase 1", quote="Thursday, October 29 — Phase 1 is due by the start of class",
                    when={"type": "datetime", "month": 10, "day": 29, "time": "08:00"})
    stated = item(title="Sign-up", quote="Oct 5 at 4 PM: sign-up", when={"type": "datetime", "month": 10, "day": 5, "time": "16:00"})
    llm.replies = [course_reply([]), items_reply(invented, stated)]
    upload(client, "kim.txt", text.encode())
    dues = [p["ops"][0]["data"]["due"] for p in inbox(client)["proposals"]]
    assert dues == ["2026-10-29", "2026-10-05T16:00"]


def test_a_course_title_given_as_the_number_falls_back_to_the_file_name(client, llm):
    llm.replies = [course_reply([{"number": "Advanced Topics in AI: Agentic Learning", "instructor": "Robin Ding",
                                  "quote": "Instructor: Robin Ding", "meetings": []}]), items_reply()]
    upload(client, "26F-COM SCI-269-SEM-3 Seminar_ Current Topics.pdf".replace(".pdf", ".txt"), SYLLABUS.encode())
    assert inbox(client)["proposals"][0]["ops"][0]["data"]["number"] == "COM SCI 269"
    assert "File name: 26F-COM SCI-269-SEM-3" in llm.requests[0]["messages"][-1]["content"]


def test_titles_start_with_a_capital(client, llm):
    llm.replies = [course_reply(), items_reply(item(title="paper registration"), item(title="iOS demo"))]
    upload(client, "cs239.txt", SYLLABUS.encode())
    assert [p["summary"] for p in inbox(client)["proposals"]][1:] == ["Paper registration", "iOS demo"]
    assert inbox(client)["proposals"][1]["ops"][0]["data"]["title"] == "Paper registration"


def test_a_separate_pass_asks_what_only_the_student_can_answer(client, llm):
    q = json.dumps({"questions": [
        {"question": "Which paper did you register to present?", "quote": "Select a paper and register"},
        {"question": "Invented?", "quote": "This sentence is not in the document"}]})
    llm.replies = [course_reply(), items_reply(), q]
    upload(client, "cs239.txt", SYLLABUS.encode())
    assert [x["text"] for x in inbox(client)["questions"]] == ["Which paper did you register to present?"]


def test_regular_lectures_are_not_proposed_as_events(client, llm):
    lecture = item(kind="event", title="Lecture 10: Thursday, November 5 — Industrial-Scale Repair", quote="Wed Nov 11 No class")
    llm.replies = [course_reply(), items_reply(lecture, item())]
    upload(client, "cs239.txt", SYLLABUS.encode())
    assert [p["summary"] for p in inbox(client)["proposals"]][1:] == ["Paper registration"]


def test_course_numbers_are_normalised(client, llm):
    llm.replies = [course_reply([{"number": "CS239", "instructor": "Robin Ding", "quote": "Instructor: Robin Ding", "meetings": []}]),
                   items_reply()]
    upload(client, "cs239.txt", SYLLABUS.encode())
    assert inbox(client)["proposals"][0]["ops"][0]["data"]["number"] == "CS 239"


def test_a_second_document_for_the_same_course_links_to_its_pending_course(client, llm):
    llm.replies = [course_reply(), items_reply()]
    upload(client, "cs239 syllabus.txt", SYLLABUS.encode())
    course = inbox(client)["proposals"][0]
    llm.replies = [course_reply(), items_reply(item())]
    upload(client, "cs239 schedule.txt", SYLLABUS.encode())
    deadline = inbox(client)["proposals"][-1]
    assert deadline["ops"][0]["data"]["course_id"] == f"$p{course['id']}.0"


def test_a_failed_upload_withdraws_what_it_had_proposed(client, llm):
    llm.replies = [course_reply()]  # the items pass then fails: no reply left
    src = upload(client, "cs239.txt", SYLLABUS.encode())
    assert src["status"] == "failed"
    assert inbox(client)["count"] == 0


def test_items_whose_quote_is_not_in_the_document_are_dropped_and_reported(client, llm):
    invented = item(title="Final exam", quote="Final exam on December 10", when={"type": "date", "month": 12, "day": 10})
    llm.replies = [course_reply(), items_reply(item(), invented)]
    src = upload(client, "cs239.txt", SYLLABUS.encode())

    assert [p["summary"] for p in inbox(client)["proposals"]][1:] == ["Paper registration"]
    assert src["dropped"] == [{"title": "Final exam", "quote": "Final exam on December 10",
                               "reason": "quote not found in the document"}]


def test_an_existing_course_is_reused_not_proposed_again(client, llm):
    ding = client.post("/api/courses", json={"number": "CS 239", "instructor": "Robin Ding"}).json()
    llm.replies = [course_reply(), items_reply(item())]
    upload(client, "cs239.txt", SYLLABUS.encode())
    (deadline,) = inbox(client)["proposals"]
    assert deadline["ops"][0]["data"]["course_id"] == ding["id"]


def test_questions_from_the_document_go_to_the_inbox(client, llm):
    q = item(kind="question", title="Which paper will you present?", quote="Select a paper and register",
             question="Which paper did you register to present in CS 239 · Ding?", when={"type": "unknown"})
    llm.replies = [course_reply(), items_reply(q)]
    upload(client, "cs239.txt", SYLLABUS.encode())
    assert [x["text"] for x in inbox(client)["questions"]] == ["Which paper did you register to present in CS 239 · Ding?"]


def test_the_model_sees_the_document_text_from_a_pdf(client, llm):
    pdf = pymupdf.open()
    pdf.new_page().insert_text((72, 72), "Instructor: Robin Ding")
    llm.replies = [course_reply(), items_reply()]
    upload(client, "syllabus.pdf", pdf.tobytes(), "application/pdf")
    assert "Instructor: Robin Ding" in llm.requests[0]["messages"][-1]["content"]


def test_running_headers_and_footers_are_removed_from_pdfs(client, llm):
    pdf = pymupdf.open()
    for n, body in enumerate(["Phase 1 — Prototype: Build a working", "multi-agent application.", "Final notes."], 1):
        page = pdf.new_page()
        page.insert_text((72, 40), "9/30/26, 9:57 AM   CS 239 Fall 2026 Course Schedule")
        page.insert_text((72, 100), body)
        page.insert_text((72, 780), f"https://web.cs.ucla.edu/~miryung/teaching/CS239-Fall2026/main.html {n}/3")
    llm.replies = [course_reply([]), items_reply()]
    upload(client, "kim.pdf", pdf.tobytes(), "application/pdf")
    seen = llm.requests[0]["messages"][-1]["content"]
    assert "Build a working\nmulti-agent application." in seen
    assert "9:57" not in seen and "miryung" not in seen


def test_the_same_item_reported_twice_is_proposed_once(client, llm):
    a = item(title="Phase 1 due", quote="Wed Nov 11 No class Midterm report due", when={"type": "date", "month": 11, "day": 11})
    b = item(title="Phase 1 application and traces", quote="Wed Nov 11 No class Midterm report due",
             when={"type": "date", "month": 11, "day": 11})
    c = item(kind="event", title="Phase 1 check-in", quote="Wed Nov 11 No class Midterm report due",
             when={"type": "date", "month": 11, "day": 11})
    llm.replies = [course_reply([]), items_reply(a, b, c)]
    upload(client, "x.txt", SYLLABUS.encode())
    assert [p["summary"] for p in inbox(client)["proposals"]] == ["Phase 1 due", "Phase 1 check-in"]


def test_the_model_sees_the_document_text_from_a_docx(client, llm):
    d = docx.Document()
    d.add_paragraph("Instructor: Robin Ding")
    buf = io.BytesIO()
    d.save(buf)
    llm.replies = [course_reply(), items_reply()]
    upload(client, "syllabus.docx", buf.getvalue(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    assert "Instructor: Robin Ding" in llm.requests[0]["messages"][-1]["content"]


def test_an_unreadable_file_reports_each_parsers_real_error(client, llm):
    src = upload(client, "broken.pdf", b"this is not a pdf", "application/pdf")
    assert src["status"] == "failed"
    assert "PyMuPDF:" in src["error"] and "pypdf:" in src["error"]
    assert "password" not in src["error"].lower()
    assert llm.requests == []


def test_a_model_failure_is_reported_on_the_upload(client, llm):
    llm.replies = ["not json"]
    src = upload(client, "cs239.txt", SYLLABUS.encode())
    assert src["status"] == "failed"
    assert "model" in src["error"].lower()
