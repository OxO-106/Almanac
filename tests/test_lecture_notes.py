"""Lecture notes: built on the Jottings, shaped by the Lecture kind, every Jotting kept."""
import json

from test_lecture_kinds import ding
from test_live_recording import send, start, tone, wait_for
from test_papers import shelve


def lecture(client, transcriber, segments, course=None, kind=None, jots=()):
    transcriber.segments = segments
    rid = start(client, course, **({"kind": kind} if kind else {}))
    send(client, rid, 0, tone(1))
    for at, text in jots:
        client.post(f"/api/recordings/{rid}/jottings", json={"at": at, "text": text})
    client.post(f"/api/recordings/{rid}/stop")
    return wait_for(lambda: client.get(f"/api/recordings/{rid}").json(), lambda r: r["notes_status"] in ("done", "failed"))


def test_notes_are_built_on_the_jottings_and_keep_every_one(client, llm, transcriber):
    llm.notes = ["## Grouped-query attention\n✎ KV cache!! \n- Keys and values are shared across groups of heads.\n\n## Announced\n- Nothing announced."]
    rec = lecture(client, transcriber, [{"start": 0.0, "end": 30.0, "text": "Grouped-query attention shares keys and values across groups."},
                                        {"start": 30.0, "end": 60.0, "text": "That shrinks the KV cache a lot."}],
                  jots=[(31, "KV cache!!"), (45, "ask about MQA vs GQA")])
    assert rec["notes_status"] == "done"
    assert rec["notes"].startswith("## Grouped-query attention\n✎ KV cache!!")
    # the one the model dropped goes above the point about what was said at 0:45
    assert "✎ ask about MQA vs GQA\n- Keys and values are shared across groups of heads." in rec["notes"]
    (req,) = llm.notes_requests
    sent = req["messages"][1]["content"]
    assert "[0:31] KV cache!!" in sent and "[0:30] That shrinks the KV cache a lot." in sent
    assert "## Announced" not in req["messages"][0]["content"]  # written by code, from announcements.find's quotes


def test_a_long_lecture_is_written_in_parts_then_combined(client, llm, transcriber):
    segments = [{"start": m * 60.0, "end": m * 60.0 + 60, "text": f"Minute {m} of the lecture."} for m in range(90)]
    llm.notes = ["part one notes", "part two notes", "part three notes", "## Combined\n✎ remember this"]
    rec = lecture(client, transcriber, segments, jots=[(2700, "remember this"), (5100, "")])
    assert len(llm.notes_requests) == 4  # parts of 40, 40 and 10 minutes, then combining them
    part2 = llm.notes_requests[1]["messages"][1]["content"]
    assert "[45:00] remember this" in part2 and "(marked)" not in part2
    assert "[40:00] Minute 40" in part2 and "[39:00]" not in part2  # part 2 is 40:00-80:00
    assert "[85:00] (marked)" in llm.notes_requests[2]["messages"][1]["content"]
    combine = llm.notes_requests[3]["messages"][1]["content"]
    assert "--- Notes, part 1 ---\npart one notes" in combine and "--- Notes, part 3 ---\npart three notes" in combine
    assert rec["notes"] == "## Combined\n✎ remember this\n\n## More of your jottings\n✎ (marked) (85:00)"  # no point to put the mark on


def paper_session(client, llm, transcriber, said):
    c = ding(client, llm)
    transcriber.segments = [{"start": i * 10.0, "end": i * 10.0 + 10, "text": t} for i, t in enumerate(said)]
    rid = client.post("/api/recordings/start", json={"course_id": c, "date": "2026-10-05"}).json()["id"]
    send(client, rid, 0, tone(1))
    client.post(f"/api/recordings/{rid}/stop")
    return wait_for(lambda: client.get(f"/api/recordings/{rid}").json(), lambda r: r["notes_status"] in ("done", "failed"))


COMPOSED = ("## Takeaways\n### GQA: Training Generalized Multi-Query Transformer\n**In class**\n- Groups share K and V.\n"
            "**From the paper**\n- Uptraining costs 5% of pre-training.\n\n## Comparison\n| Paper | Idea |\n|---|---|\n| GQA | shared K/V |\n\n"
            "## Summary\nThe class covered GQA.\n\n## Announced\n- Assignment 3 is due October 12.\n\n## Questions Asked in Class\n- Why groups?")


def test_a_paper_session_is_written_from_class_then_with_the_papers(client, llm, transcriber, papercut):
    shelve(papercut, "ba9094fe73db9bf5", "GQA: Training Generalized Multi-Query Transformer Models from Multi-Head Checkpoints", "CS 239 Ding")
    llm.notes = ["## GQA\n- Groups share K and V.", COMPOSED]
    rec = paper_session(client, llm, transcriber, ["Today's paper is GQA.", "Groups of heads share keys and values."])
    part, composed = llm.notes_requests
    assert "Papers for this lecture on the reading list: GQA: Training" in part["messages"][1]["content"]
    assert "Abstract" not in part["messages"][1]["content"]  # what was said in class comes from the transcript alone
    system, user = (m["content"] for m in composed["messages"])
    assert "paper session" in system and "also one not presented" in system
    assert all(h in system for h in ("## Takeaways", "## Comparison", "## Connections", "## Background", "## Summary"))
    assert "1. GQA: Training Generalized Multi-Query Transformer\nPresented in class: yes" in user
    assert "Abstract (the paper's words): We introduce grouped-query attention." in user and "TL;DR: Share K/V heads per group." in user
    assert "The class notes:\n\n--- Notes, part 1 ---\n## GQA\n- Groups share K and V." in user
    assert "Course: CS 239" in user and "Robin Ding" in user
    # nothing was announced: the model's own Announced section is dropped, as are sections not asked for
    assert rec["notes"] == COMPOSED.split("\n\n## Announced")[0]


def test_a_paper_not_in_the_library_is_known_by_its_title_only(client, llm, transcriber):
    paper_session(client, llm, transcriber, ["Today's paper is GQA."])
    user = llm.notes_requests[-1]["messages"][1]["content"]
    assert ("1. GQA: Training Generalized Multi-Query Transformer\nPresented in class: yes (named in the transcript).\n"
            "Not in the student's library: only its title is known.") in user


def test_questions_are_checked_against_the_transcript_then_answered_from_the_paper(client, llm, transcriber, papercut):
    shelve(papercut, "ba9094fe73db9bf5", "GQA: Training Generalized Multi-Query Transformer Models from Multi-Head Checkpoints", "CS 239 Ding")
    llm.notes = ["## GQA\n- Groups.", COMPOSED.split("\n\n## Announced")[0]]

    def q(**k):
        return {"time": "0:10", "asker": "a student", "question": "", "question_quote": "", "answered": False,
                "answerer": "", "answer": "", "answer_quote": "", "paper": "", **k}
    llm.questions = [json.dumps({"questions": [
        q(time="0:20", question="Can Top-K be trained?", question_quote="how can you train all the Top-K models"),
        q(question="Why not map all queries to one set of keys?", question_quote="why not just have all queries mapped to one key",
          answered=True, answerer="the presenter", answer="Grouped-query attention keeps the computation graph simple.",
          answer_quote="it keeps the computational graph simple", paper="GQA: Training Generalized Multi-Query Transformer"),
        q(time="0:30", question="What happens with GQA and NSA together?", question_quote="what happens if we use GQA with NSA"),  # never asked
        q(time="0:30", question="Is it fast?", question_quote="is it fast though really", answered=True, answer="Yes, ten times.",
          answer_quote="ten times faster than anything"),  # the answer isn't in the transcript
    ]})]
    llm.paper_answers = [json.dumps({"answers": [
        {"n": 1, "answer": "The paper introduces grouped-query attention as a middle ground.", "quote": "We introduce grouped-query attention",
         "paper": "GQA", "section": "Abstract"},
        {"n": 3, "answer": "The passages do not explain whether it is fast.", "quote": "We introduce grouped-query attention",
         "paper": "GQA", "section": "Abstract"},  # says what the paper doesn't say: not an answer
        {"n": 2, "answer": "Top-K is made differentiable.", "quote": "top-k is made differentiable by design", "paper": "GQA", "section": ""},  # not in its passages
    ]})]
    rec = paper_session(client, llm, transcriber, [
        "Today's paper is GQA.", "Why not just have all queries mapped to one key? Well, it keeps the computational graph simple.",
        "And how can you train all the Top-K models? I'll be back to that.", "Is it fast though really?"])
    assert rec["notes"].split("## Questions\n")[1].split("\n\n## Summary")[0] == (
        "- **Q** (a student, 0:10): Why not map all queries to one set of keys?\n"
        "  - **A** (the presenter): Grouped-query attention keeps the computation graph simple.\n"
        "  - **From the paper** (GQA, Abstract): The paper introduces grouped-query attention as a middle ground.\n"
        "- **Q** (a student, 0:20): Can Top-K be trained?\n"
        "  - Not answered in class.\n"
        "- **Q** (a student, 0:30): Is it fast?\n"
        "  - The answer couldn't be matched to the transcript.")
    asked = llm.paper_answer_requests[0]["messages"][1]["content"]
    assert "Question 1: Why not map all queries to one set of keys?\nAnswer in class: Grouped-query attention keeps the computation graph simple." in asked
    assert "- [GQA, Abstract] We introduce grouped-query attention." in asked


def test_a_paper_never_named_in_class_is_marked_not_presented():
    from app.lecture_notes import _mark_not_presented
    notes = ("## Takeaways\n### GQA: Training\n**In class**\n- Shared K/V.\n### Kimi Linear: An Expressive, Efficient Attention Architecture\n"
             "**In class**\n- Was covered, says the model.\n**From the paper**\n- KDA extends Gated DeltaNet.\n"
             "### Native Sparse Attention\n**From the paper**\n- Three branches.\n\n## Summary\nThe class covered GQA.")
    out = _mark_not_presented(notes, [("Kimi Linear: An Expressive, Efficient Attention Architecture", {"title": "Kimi Linear"}),
                                      ("Native Sparse Attention", None)])
    assert out == ("## Takeaways\n### GQA: Training\n**In class**\n- Shared K/V.\n### Kimi Linear: An Expressive, Efficient Attention Architecture\n"
                   "*Not presented in class; from the paper.*\n**From the paper**\n- KDA extends Gated DeltaNet.\n"
                   "### Native Sparse Attention\n*Not presented in class, and not in your library.*\n\n## Summary\nThe class covered GQA.")


def test_announced_is_only_what_the_transcript_says(client, llm, transcriber):
    llm.notes = ["## Topic\n- A point.\n\n## Announced\n- Office hours moved to Thursday."]
    llm.announced = [json.dumps({"items": [
        {"kind": "task", "title": "read the Mamba paper", "quote": "read the Mamba paper for next Monday",
         "when": {"type": "weekday", "weekday": "MO", "next_week": True}, "clear": True},
        {"kind": "deadline", "title": "Assignment 3 due", "quote": "assignment three is due October 12th",
         "when": {"type": "date", "month": 10, "day": 12}, "clear": True}]})]
    rec = lecture(client, transcriber, [{"start": 0.0, "end": 9.0, "text": "A point. Please read the Mamba paper for next Monday."}])
    assert rec["notes"] == "## Topic\n- A point.\n\n## Announced\n- Read the Mamba paper: “read the Mamba paper for next Monday”"
    assert len(llm.announce_requests) == 1  # asked once, for the notes and the plan


def test_a_paper_is_named_by_its_short_name_first_words_or_initials():
    from app import papers
    said = "Today GQA, then native sparse attention, and the gated delta rule."
    assert papers.named("GQA: Training Generalized", said)
    assert papers.named("Gated Delta Networks: Improving Mamba2", said)  # its first two words
    assert papers.named("Native Sparse Attention: Hardware-Aligned", "we read NSA")  # its initials
    assert not papers.named("Kimi Linear: An Expressive, Efficient Attention Architecture", said)


def test_notes_that_fail_can_be_written_again(client, llm, transcriber):
    def fail(*a, **k):
        raise TimeoutError("the model didn't answer in time")
    real = llm.chat
    llm.chat = lambda messages, schema=None, **kw: fail() if messages[0]["content"].startswith("You write study notes") else real(messages, schema, **kw)
    rec = lecture(client, transcriber, [{"start": 0.0, "end": 5.0, "text": "Hello."}])
    assert rec["notes_status"] == "failed" and "didn't answer" in rec["notes_error"] and rec["transcript"]
    llm.chat = real
    llm.notes = ["## Hello\n- A greeting."]
    client.post(f"/api/recordings/{rec['id']}/notes/retry")
    assert client.get(f"/api/recordings/{rec['id']}").json()["notes"] == "## Hello\n- A greeting."


def test_only_the_students_jottings_are_marked_as_theirs():
    from app.lecture_notes import _keep_jottings
    notes = "## Logistics\n✎ office hours per request\n  - By request.\n✎ [12:43] Mokir got the Nobel Prize for replacing a technology\n✎ (marked)\n  - The Turing Award."
    out = _keep_jottings(notes, [{"at": 115, "text": "office hours per request"}, {"at": 170, "text": ""}])
    assert out == "## Logistics\n✎ office hours per request\n  - By request.\n- [12:43] Mokir got the Nobel Prize for replacing a technology\n✎ (marked)\n  - The Turing Award."


def test_the_models_guesses_about_meaning_are_taken_out(client, llm, transcriber):
    llm.notes = ['## Patents\n- Apple\'s patent for "penny-free climbs" (likely referring to touch interfaces) is an example.']
    rec = lecture(client, transcriber, [{"start": 0.0, "end": 9.0, "text": "Apple patent for penny-free climbs."}])
    assert rec["notes"] == '## Patents\n- Apple\'s patent for "penny-free climbs" is an example.'


def test_the_models_own_instructions_copied_into_the_notes_are_taken_out(client, llm, transcriber):
    # CS 259, 2026-10-06: the combined notes ended with the combine prompt's rules
    segments = [{"start": m * 60.0, "end": m * 60.0 + 60, "text": f"Minute {m} of the lecture."} for m in range(50)]
    llm.notes = ["part one", "part two", "## Upcoming lecture topics\n- Next Monday: Nobel Prizes.\n\n"
                 "- Keep every point and every detail; only merge what repeats and reorganize into the structure below. "
                 "Don't add anything that isn't in the part notes or in the papers' information given.\n"
                 '  - Markdown: "## " for sections, "### " for subsections, "- " for points (indent sub-points by two spaces). '
                 "A table only where it compares things side by side. Math as LaTeX: inline between single dollar signs, "
                 "e.g. $K_i \\cdot K_j = 0$; a formula on its own line between double dollar signs.\n"
                 '  - This was a lecture teaching concepts. Organize by concept ("## " + the concept), with its definition, '
                 "the reasoning or derivation walked through step by step, and the examples given.\n\n"
                 "- Students should keep every point of their reports short."]
    rec = lecture(client, transcriber, segments, kind="concept_lecture")
    assert rec["notes"] == "## Upcoming lecture topics\n- Next Monday: Nobel Prizes.\n\n- Students should keep every point of their reports short."


def test_a_replay_ticks_off_the_task_for_that_lecture(client, llm, transcriber):
    cid = client.post("/api/courses", json={"number": "CS 269", "instructor": "Stefano Soatto"}).json()["id"]
    t1 = client.post("/api/tasks", json={"title": "Watch the CS 269 recording", "due": "2026-10-06", "course_id": cid}).json()
    t2 = client.post("/api/tasks", json={"title": "Watch the CS 269 recording", "due": "2026-10-08", "course_id": cid}).json()
    other = client.post("/api/tasks", json={"title": "Read the GQA paper", "due": "2026-10-06", "course_id": cid}).json()
    transcriber.segments = [{"start": 0.0, "end": 5.0, "text": "Welcome back."}]
    rid = client.post("/api/recordings/start", json={"course_id": cid, "date": "2026-10-05"}).json()["id"]
    send(client, rid, 0, tone(1))
    client.post(f"/api/recordings/{rid}/stop")
    wait_for(lambda: client.get(f"/api/recordings/{rid}").json(), lambda r: r["notes_status"] == "done")
    status = {t["id"]: t["status"] for t in client.get("/api/tasks").json()}
    assert (status[t1["id"]], status[t2["id"]], status[other["id"]]) == ("done", "open", "open")  # the Oct 5 lecture's task only
    assert any(n["title"] == "Ticked off “Watch the CS 269 recording”" for n in client.get("/api/notifications").json())
    # through the gate, in the task's history: undoing it reopens the task
    from app import inbox
    con = client.app.state.db
    (pid,) = [r["id"] for r in con.execute("select id from proposals where summary like 'Mark “Watch%' and status = 'accepted'")]
    inbox.withdraw(con, pid)
    assert client.get(f"/api/tasks/{t1['id']}").json()["status"] == "open"


def test_a_point_from_class_with_an_amount_class_never_said_is_left_out():
    from app.lecture_notes import _drop_unsaid_numbers
    said = "At sixty-four K the cache is about 5GB. Decoding takes most of the time. We got five percent."
    notes = ("### GQA\n**In class**\n- The cache is ~5 GB at 64k.\n- Loading it takes 70-80% of decoding time.\n- Uptraining costs 5% of compute.\n"
             "**From the paper**\n- Loading it takes 70-80% of decoding time.\n## Background\n### From class\n- Attention is $O(N^2)$; a 10x cache.\n")
    assert _drop_unsaid_numbers(notes, said) == (
        "### GQA\n**In class**\n- The cache is ~5 GB at 64k.\n- Uptraining costs 5% of compute.\n"
        "**From the paper**\n- Loading it takes 70-80% of decoding time.\n## Background\n### From class")
