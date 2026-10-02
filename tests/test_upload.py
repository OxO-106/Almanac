import io
import json

import docx
import pymupdf

SYLLABUS = """CS 239: Large Language Models and Code Intelligence
Instructor: Robin Ding
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


def test_a_label_that_is_not_a_question_is_not_asked(client, llm):
    # e.g. "Gating test eligibility": the questions pass asks properly instead.
    llm.replies = [course_reply(), items_reply(item(kind="question", title="Which paper to present", when={"type": "unknown"}))]
    upload(client, "cs239.txt", SYLLABUS.encode())
    assert inbox(client)["questions"] == []


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


def test_a_task_with_no_date_or_lecture_is_left_out_and_asked_about(client, llm):
    # "Read papers before lectures" is likely an instruction, not something to plan: not
    # suggested, but asked about, since only the student knows
    llm.replies = [course_reply([]), items_reply(item(kind="task", title="Read papers before lectures",
                                                      quote="Select a paper", when={"type": "unknown"}))]
    src = upload(client, "cs239.txt", SYLLABUS.encode())
    box = inbox(client)
    assert box["proposals"] == []
    assert [(q["text"], q["purpose"]) for q in box["questions"]] == [
        ("I couldn't place “Read papers before lectures”: the document doesn't say when. Is it something you need to do? If so, when?", "other")]
    assert [(d["title"], d["reason"]) for d in src["dropped"]] == [("Read papers before lectures", "no date or lecture stated")]


def test_several_left_out_things_are_one_question(client, llm):
    llm.replies = [course_reply([]), items_reply(
        item(kind="task", title="Read papers before lectures", quote="Select a paper", when={"type": "unknown"}),
        item(kind="deadline", title="Peer review", quote="Peer review is due after the final", when={"type": "unknown"}))]
    upload(client, "cs239.txt", SYLLABUS.encode())
    texts = [q["text"] for q in inbox(client)["questions"]]
    assert "I couldn't place 2 things, even on a second look: “Peer review”; “Read papers before lectures”. " \
           "Do you need to do any of them? If so, tell me which and when." in texts


READINGS = """Course Schedule
Lecture 4: Thursday, October 8 — Search over Reasoning States
P4. Tree of Thoughts
Lecture 5: Tuesday, October 13 — Agent-Computer Interfaces
P5. SWE-agent
Reading list
Papers marked [Required] must be read before the corresponding lecture.
P5. SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering. [NeurIPS
2024] [Required — Lecture 5] (John Yang)
"""


def test_a_reading_is_due_the_day_before_its_lecture(client, llm):
    tagged = item(kind="task", title="Read P5. SWE-agent", when={"type": "unknown"},
                  quote="P5. SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering. [NeurIPS 2024] [Required — Lecture 5]")
    in_schedule = item(kind="task", title="Read P4. Tree of Thoughts", quote="P4. Tree of Thoughts", when={"type": "unknown"})
    llm.replies = [course_reply([]), items_reply(tagged, in_schedule)]
    upload(client, "kim.txt", READINGS.encode())
    got = {p["summary"]: p for p in inbox(client)["proposals"]}
    assert got["Read P5. SWE-agent"]["ops"][0]["data"]["due"] == "2026-10-12"  # Lecture 5 is Tue Oct 13
    assert got["Read P5. SWE-agent"]["quote"].startswith("Lecture 5: Tuesday, October 13")
    assert got["Read P4. Tree of Thoughts"]["ops"][0]["data"]["due"] == "2026-10-07"  # under Lecture 4, Thu Oct 8


def test_questions_already_open_for_the_course_are_not_asked_again(client, llm):
    q1 = json.dumps({"questions": [{"question": "Which paper did you register to present?", "quote": "Select a paper and register"}]})
    llm.replies = [course_reply(), items_reply(), q1]
    upload(client, "cs239.txt", SYLLABUS.encode())
    q2 = json.dumps({"questions": [
        {"question": "Which paper will you present?", "quote": "Select a paper and register"},
        {"question": "Have you already signed up for a slot?", "quote": "Select a paper and register"}]})
    merged = json.dumps({"merged": [{"question": "Which paper did you register to present?", "from": [0, 1]}]})
    llm.replies = [course_reply(), items_reply(), q2, merged]
    upload(client, "cs239 schedule.txt", SYLLABUS.encode())
    assert [q["text"] for q in inbox(client)["questions"]] == ["Which paper did you register to present?"]
    listing = llm.requests[-1]["messages"][-1]["content"]
    assert "1. Which paper did you register to present? (already asked)" in listing
    assert "Have you already" not in listing  # yes/no about something done: not asked


def test_a_question_code_must_ask_is_kept_even_if_the_merge_drops_it(client, llm):
    drafts = json.dumps({"questions": [{"question": "Which paper are you presenting?", "quote": "Select a paper and register"}]})
    undated = item(title="Final report", quote="Instructor: Robin Ding", when={"type": "unknown"})
    llm.replies = [course_reply(), items_reply(undated), drafts, json.dumps({"merged": [{"question": "Which paper are you presenting?", "from": [0]}]})]
    upload(client, "cs239.txt", SYLLABUS.encode())
    assert sorted(q["text"] for q in inbox(client)["questions"]) == [
        "When is “Final report” due? The document doesn't say.", "Which paper are you presenting?"]


def test_a_course_without_a_named_instructor_is_asked_about(client, llm):
    llm.replies = [course_reply([{"number": "CS 239", "instructor": "", "quote": "CS 239: Large Language Models", "meetings": []}]),
                   items_reply(item())]
    upload(client, "kim.txt", SYLLABUS.encode())
    box = inbox(client)
    course, deadline = box["proposals"]
    assert course["blocked_by"] == "Who teaches CS 239? The document doesn't name the instructor."
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
    assert inbox(client)["proposals"][0]["ops"][0]["data"]["number"] == "CS 269"
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


def test_duplicate_questions_are_merged_and_unneeded_ones_dropped(client, llm):
    drafts = json.dumps({"questions": [
        {"question": "Which paper did you register to present?", "quote": "Select a paper and register"},
        {"question": "Which paper will you present in class?", "quote": "Select a paper and register"},
        {"question": "Do you like the course?", "quote": "Select a paper and register"},
        {"question": "Gating test eligibility", "quote": "Select a paper and register"}]})
    blocked = item(kind="task", title="Prepare presentation", question="What paper are you presenting?", when={"type": "unknown"})
    merged = json.dumps({"merged": [{"question": "Which paper are you presenting?", "from": [0, 1, 3]}]})
    llm.replies = [course_reply(), items_reply(blocked), drafts, merged]
    upload(client, "cs239.txt", SYLLABUS.encode())
    box = inbox(client)
    assert [q["text"] for q in box["questions"]] == ["Which paper are you presenting?"]
    assert "3. What paper are you presenting?" in llm.requests[-1]["messages"][-1]["content"]  # the item's own draft
    assert "Gating test eligibility" not in llm.requests[-1]["messages"][-1]["content"]  # not a question
    assert next(p for p in box["proposals"] if p["summary"] == "Prepare presentation")["blocked_by"] == "Which paper are you presenting?"


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
    # one rule for duplicates: a session and what's due at it are one thing; the session is kept
    assert [p["summary"] for p in inbox(client)["proposals"]] == ["Phase 1 check-in"]


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


def test_a_failed_upload_can_be_retried_without_choosing_the_file_again(client, llm):
    llm.replies = ["not json"]  # the model fails the first time
    src = upload(client, "cs239.txt", SYLLABUS.encode())
    assert src["status"] == "failed"
    llm.replies = [course_reply(), items_reply(item())]
    r = client.post(f"/api/sources/{src['id']}/retry")
    assert r.status_code == 202
    assert client.get(f"/api/sources/{src['id']}").json()["status"] == "done"
    assert [p["summary"] for p in inbox(client)["proposals"]] == ["Add course CS 239 · Robin Ding", "Paper registration"]


def test_only_failed_uploads_can_be_retried(client, llm):
    llm.replies = [course_reply(), items_reply()]
    src = upload(client, "cs239.txt", SYLLABUS.encode())
    assert client.post(f"/api/sources/{src['id']}/retry").status_code == 409


def test_a_reading_dated_by_its_lecture_row_moves_to_the_day_before_and_merges(client, llm):
    from_row = item(kind="task", title="Read P5. SWE-agent", quote="Lecture 5: Tuesday, October 13 ... P5. SWE-agent",
                    when={"type": "date", "month": 10, "day": 13})
    from_list = item(kind="task", title="Read SWE-agent: Agent-Computer Interfaces", when={"type": "unknown"},
                     quote="P5. SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering. [NeurIPS 2024] [Required — Lecture 5]")
    llm.replies = [course_reply([]), items_reply(from_row, from_list)]
    upload(client, "kim.txt", READINGS.encode())
    assert [(p["summary"], p["ops"][0]["data"]["due"]) for p in inbox(client)["proposals"]] == [("Read P5. SWE-agent", "2026-10-12")]


def test_someone_named_only_in_passing_is_not_taken_for_the_instructor(client, llm):
    doc = "CS 239 Autonomous Software Engineering Agents\nThaddy will give a tutorial on multi-agent frameworks.\n"
    llm.replies = [course_reply([{"number": "CS 239", "instructor": "Thaddy", "title": "Autonomous Software Engineering Agents",
                                  "quote": "Thaddy will give a tutorial", "meetings": []}]), items_reply()]
    upload(client, "kim.txt", doc.encode())
    assert [q["text"] for q in inbox(client)["questions"]] == [
        "Who teaches CS 239: Autonomous Software Engineering Agents? The document doesn't name the instructor."]


def test_a_schedule_row_quoted_as_date_and_deliverable_is_kept(client, llm):
    # The model leaves out the row's topic and papers without marking the gap.
    text = ("Wed Oct 21\nDistributed Training:\nMemory Optimization\nZeRO: Memory Optimizations Toward Training Trillion Parameter Models\n"
            "ZeRO-Infinity: Breaking the GPU Memory Wall for Extreme Scale Deep Learning\nProposal\none-pager\n"
            "Mon Oct 26\nDistributed Training:\nParallelism\n")
    one_pager = item(title="Proposal one-pager", quote="Wed Oct 21 Proposal one-pager", when={"type": "date", "month": 10, "day": 21})
    llm.replies = [course_reply([]), items_reply(one_pager)]
    src = upload(client, "ding.txt", text.encode())
    (p,) = inbox(client)["proposals"]
    assert (p["summary"], p["ops"][0]["data"]["due"], p["quote"]) == ("Proposal one-pager", "2026-10-21", "Wed Oct 21 … Proposal one-pager")
    assert src["dropped"] == []


SECTION = """In your first week, you must read and sign UCLA's Academic Integrity Statement.
Lecture 12: Thursday, November 12 — Prompt Injection Defense & Preliminary Results
Check-in
P12. Defeating Prompt Injections by Design [IEEE SaTML 2026]
Suggested team presentations: AgentDojo — provides the benchmark and threat model
that CaMeL and other defenses are evaluated against; Agent-C (Temporal Constraints) — a
different enforcement approach using SMT-checked temporal policies rather than
architectural isolation, good contrast to CaMeL's privilege separation.
Project check-in follows the paper discussion: encoding policies.md as rules and early
Phase 2 porting work due.
Lecture 13: Tuesday, November 17 — Plan Compliance & Intent Specifications
"""


def test_a_heading_and_a_note_further_down_its_section_make_one_quote(client, llm):
    check_in = item(title="Project check-in", when={"type": "date", "month": 11, "day": 12},
                    quote="Lecture 12: Thursday, November 12 ... Project check-in follows the paper discussion")
    llm.replies = [course_reply([]), items_reply(check_in)]
    upload(client, "kim.txt", SECTION.encode())
    (p,) = inbox(client)["proposals"]
    assert (p["summary"], p["ops"][0]["data"]["due"]) == ("Project check-in", "2026-11-12")


def test_a_section_quote_may_not_cross_into_the_next_lecture(client, llm):
    wrong = item(title="Plan compliance", when={"type": "date", "month": 11, "day": 12},
                 quote="Lecture 12: Thursday, November 12 ... Plan Compliance & Intent Specifications")
    llm.replies = [course_reply([]), items_reply(wrong)]
    src = upload(client, "kim.txt", SECTION.encode())
    assert inbox(client)["proposals"] == [] and [d["title"] for d in src["dropped"]] == ["Plan compliance"]


def test_what_was_left_out_gets_a_second_look(client, llm):
    misquoted = item(title="Project check-in", quote="Nov 12 project check-in: policies as rules", when={"type": "unknown"})
    undated = item(kind="task", title="Read UCLA's Academic Integrity Statement", when={"type": "unknown"},
                   quote="you must read and sign UCLA's Academic Integrity Statement")
    invented = item(title="Final exam", quote="Final exam on December 10", when={"type": "unknown"})
    second = json.dumps({"items": [  # 0, 1: quotes not found; 2: no date
        {"n": 0, "quote": "Lecture 12: Thursday, November 12 ... Project check-in follows the paper discussion",
         "when": {"type": "date", "month": 11, "day": 12}},
        {"n": 1, "quote": "", "when": {"type": "unknown"}},
        {"n": 2, "quote": "In your first week, you must read and sign UCLA's Academic Integrity Statement",
         "when": {"type": "week", "week": 1}}]})
    llm.replies = [course_reply([]), items_reply(misquoted, undated, invented), second]
    src = upload(client, "kim.txt", SECTION.encode())
    got = {p["summary"]: p["ops"][0]["data"] for p in inbox(client)["proposals"]}
    assert got["Project check-in"]["due"] == "2026-11-12"
    assert got["Read UCLA's Academic Integrity Statement"]["due"] == "2026-10-02"  # "first week": by the end of Week 1
    assert [d["title"] for d in src["dropped"]] == ["Final exam"]
    assert any("Items:\n0. Project check-in" in r["messages"][-1]["content"] for r in llm.requests)


def test_weekly_meetings_are_read_from_the_text_when_the_model_reports_none(client, llm):
    doc = ("Miodrag Potkonjak\nCS259 Fall 2026\nSeminal Achievements in Computer Science\nCourse logistics\n"
           "Lecture: MW 2:00pm - 3:50pm\nhttps://ucla.zoom.us/j/4097029656\nOffice hours: per request\n")
    llm.replies = [course_reply([{"number": "CS 259", "instructor": "", "title": "Seminal Achievements in Computer Science",
                                  "quote": "CS259 Fall 2026", "meetings": []}]), items_reply()]
    upload(client, "cs259.txt", doc.encode())
    (cls,) = [p for p in inbox(client)["proposals"] if p["ops"][0]["kind"] == "events"]
    d = cls["ops"][0]["data"]
    assert (d["repeat"], d["start"][11:], d["end"][11:], d["location"]) == ("MO,WE", "14:00", "15:50", "https://ucla.zoom.us/j/4097029656")


def test_a_meetings_type_comes_from_its_heading(client, llm):
    doc = ("CS 239\nInstructor: Robin Ding\nLectures\nMondays and Wednesdays, 4:00-5:50 p.m. @ GEOLOGY 6704\n"
           "Office hours\nThursdays, 4:00-5:00 p.m. @ Engineering VI\n")
    meetings = [{"type": "lecture", "days": "MO,WE", "start": "16:00", "end": "17:50", "location": "GEOLOGY 6704",
                 "quote": "Mondays and Wednesdays, 4:00-5:50 p.m. @ GEOLOGY 6704"},
                {"type": "lecture", "days": "TH", "start": "16:00", "end": "17:00", "location": "Engineering VI",
                 "quote": "Thursdays, 4:00-5:00 p.m. @ Engineering VI"}]
    llm.replies = [course_reply([{"number": "CS 239", "instructor": "Robin Ding", "quote": "Instructor: Robin Ding",
                                  "meetings": meetings}]), items_reply()]
    upload(client, "ding.txt", doc.encode())
    got = {p["summary"]: p for p in inbox(client)["proposals"]}
    assert "CS 239 · Ding class meetings" in got
    assert got["CS 239 office hours (weekly)"]["optional"]  # under "Office hours", whatever the model called it


def test_the_same_presentation_on_two_close_dates_is_a_slot_choice(client, llm):
    doc = "Mon Nov 30 Final project report\nWed Dec 2 Final project report\n"
    llm.replies = [course_reply(), items_reply(
        item(kind="event", title="Final project report", quote="Mon Nov 30 Final project report", when={"type": "date", "month": 11, "day": 30}),
        item(kind="event", title="Final project report", quote="Wed Dec 2 Final project report", when={"type": "date", "month": 12, "day": 2}))]
    upload(client, "ding.txt", doc.encode())
    slots = [p for p in inbox(client)["proposals"] if p["summary"] == "Final project report"]
    assert len(slots) == 2 and all(p["blocked_by"] == "Which day is your “Final project report”: Mon Nov 30 or Wed Dec 2?" for p in slots)


def test_every_spelling_of_computer_science_is_cs():
    from app.plan import course_number
    assert [course_number(x) for x in ["COM SCI 269", "COMSCI269", "Comp Sci 131", "Computer Science 32", "cs  239", "COM SCI M146", "EC ENGR 133A"]] == \
        ["CS 269", "CS 269", "CS 131", "CS 32", "CS 239", "CS M146", "EC ENGR 133A"]
