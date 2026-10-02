"""Living notes (phase 3): the student's own edits, change requests from the
lecture page and from Chat, each applied at once with Undo."""
import json

from test_live_recording import send, tone, wait_for

NOTES = ("## Grouped-query attention\n✎ KV cache!!\n- Keys and values are shared across groups of heads.\n- It shrinks the KV cache.\n\n"
         "## Mamba\n- A state-space model with selective scan.\n\n## Announced\n- Read the Mamba paper for Monday.")


def lecture(client, llm, transcriber, course=None, day="2026-09-28", notes=NOTES):
    llm.notes = [notes]
    transcriber.segments = [{"start": 0.0, "end": 30.0, "text": "Grouped-query attention shares keys and values across groups."},
                            {"start": 30.0, "end": 60.0, "text": "That shrinks the KV cache a lot. GQA interpolates between MHA and MQA."}]
    rid = client.post("/api/recordings/start", json={"course_id": course, "date": day}).json()["id"]
    send(client, rid, 0, tone(1))
    client.post(f"/api/recordings/{rid}/jottings", json={"at": 31, "text": "KV cache!!"})
    client.post(f"/api/recordings/{rid}/stop")
    wait_for(lambda: client.get(f"/api/recordings/{rid}").json(), lambda r: r["notes_status"] == "done")
    return rid


def get(client, rid):
    return client.get(f"/api/recordings/{rid}").json()


def changed(summary, *sections):
    return json.dumps({"summary": summary, "sections": [{"replaces": r, "markdown": m} for r, m in sections]})


def ask(client, rid, request):
    assert client.post(f"/api/recordings/{rid}/notes/change", json={"request": request}).status_code == 202
    return wait_for(lambda: get(client, rid), lambda r: r["notes_status"] == "done")


def test_your_edits_can_be_undone_in_order(client, llm, transcriber):
    rid = lecture(client, llm, transcriber)
    assert get(client, rid)["undo"] is None
    client.put(f"/api/recordings/{rid}/notes", json={"notes": NOTES + "\n- Ask about MQA."})
    client.put(f"/api/recordings/{rid}/notes", json={"notes": "## Mine\n- Rewritten."})
    r = get(client, rid)
    assert r["notes"] == "## Mine\n- Rewritten." and r["undo"] == "your edit"
    assert client.post(f"/api/recordings/{rid}/notes/undo").json()["notes"] == NOTES + "\n- Ask about MQA."
    assert client.post(f"/api/recordings/{rid}/notes/undo").json()["notes"] == NOTES
    assert client.post(f"/api/recordings/{rid}/notes/undo").status_code == 409


def test_a_change_touches_only_the_sections_it_returns(client, llm, transcriber):
    rid = lecture(client, llm, transcriber)
    llm.changes = [changed("Turned the Mamba section into two bullets.",
                           ("Mamba", "## Mamba\n- State-space model.\n- Selective scan."))]
    r = ask(client, rid, "make the Mamba section two bullets")
    assert r["notes"] == NOTES.replace("- A state-space model with selective scan.", "- State-space model.\n- Selective scan.")
    assert r["undo"] == "“make the Mamba section two bullets”"
    assert any(n["title"] == "Notes changed" and "two bullets" in n["body"] for n in client.get("/api/notifications").json())
    (req,) = llm.change_requests
    user = req["messages"][1]["content"]
    assert "The notes:\n" + NOTES in user and "[0:30] That shrinks the KV cache" in user and user.endswith("The student asks: make the Mamba section two bullets")
    assert client.post(f"/api/recordings/{rid}/notes/undo").json()["notes"] == NOTES


def test_new_sections_go_before_announced_and_removed_ones_go(client, llm, transcriber):
    rid = lecture(client, llm, transcriber)
    llm.changes = [changed("Added the MQA comparison; removed Mamba.", ("", "## MHA, MQA and GQA\n- GQA interpolates between them."), ("Mamba", ""))]
    notes = ask(client, rid, "add how GQA compares to MHA and MQA, and drop the Mamba part")["notes"]
    assert [l for l in notes.splitlines() if l.startswith("## ")] == ["## Grouped-query attention", "## MHA, MQA and GQA", "## Announced"]
    llm.changes = [json.dumps({"summary": "Added a summary at the top.", "sections": [
        {"replaces": "", "markdown": "## In short\n- GQA shares keys and values.", "before": "Grouped-query attention"}]})]
    notes = ask(client, rid, "a one-line summary at the top")["notes"]
    assert notes.startswith("## In short\n- GQA shares keys and values.\n\n## Grouped-query attention\n")


def test_your_jottings_survive_a_change_and_the_model_cant_make_new_ones(client, llm, transcriber):
    rid = lecture(client, llm, transcriber)
    llm.changes = [changed("Shortened it.", ("Grouped-query attention",
                                             "## Grouped-query attention\n✎ GQA is a middle ground\n- Heads share keys and values.\n- Smaller KV cache."))]
    notes = ask(client, rid, "shorter")["notes"]
    # back above the first of the points it was above before
    assert notes.startswith("## Grouped-query attention\n- GQA is a middle ground\n✎ KV cache!!\n- Heads share keys and values.")
    # asked about them, they can go
    llm.changes = [changed("Removed your jotting.", ("Grouped-query attention", "## Grouped-query attention\n- Smaller KV cache."))]
    assert "✎" not in ask(client, rid, "remove my jotting")["notes"]


def test_a_mark_right_above_a_jotting_goes_back_there():
    from app.lecture_notes import restore_jottings
    old = "## Logistics\n- Welcome.\n✎ (marked)\n✎ office hours per request\n- Office hours by request, real ones in week two.\n\n## Announced\n- Office hours in week two."
    new = "## Logistics\n- Welcome.\n✎ office hours per request\n- Office hours by request; real ones in week two.\n\n## Announced\n- Office hours in week two."
    assert restore_jottings(old, new) == "## Logistics\n- Welcome.\n✎ office hours per request\n✎ (marked)\n- Office hours by request; real ones in week two.\n\n## Announced\n- Office hours in week two."


def test_what_the_lecture_didnt_cover_is_said_not_written_into_the_notes(client, llm, transcriber):
    rid = lecture(client, llm, transcriber)
    llm.changes = [changed("Added the presentation format; he didn't talk about grading.",
                           ("Mamba", "## Mamba\n- A state-space model with selective scan.\n- Presentations: one topic each.\n- **Grading**: The lecturer did not specify grading criteria."))]
    notes = ask(client, rid, "add how presentations and grading work")["notes"]
    assert "- Presentations: one topic each." in notes and "Grading" not in notes


def test_a_change_that_fails_leaves_the_notes_and_says_why(client, llm, transcriber):
    rid = lecture(client, llm, transcriber)
    r = ask(client, rid, "add the derivation")  # the model returned nothing to change
    assert r["notes"] == NOTES and r["undo"] is None and "didn't find anything" in r["notes_error"]
    client.put(f"/api/recordings/{rid}/notes", json={"notes": NOTES})
    assert get(client, rid)["notes_error"] is None


def test_notes_being_changed_cant_be_changed_again(client, llm, transcriber):
    rid = lecture(client, llm, transcriber)
    con = client.app.state.db
    con.execute("update recordings set notes_status = 'changing' where id = ?", (rid,))
    assert client.put(f"/api/recordings/{rid}/notes", json={"notes": "x"}).status_code == 409
    assert client.post(f"/api/recordings/{rid}/notes/change", json={"request": "shorter"}).status_code == 409


def test_a_long_transcript_is_cut_to_what_the_request_is_about():
    from app.lecture_notes import TRANSCRIPT_CHARS, _transcript_for
    segments = [{"start": i * 10.0, "end": i * 10.0 + 10, "text": f"Filler sentence number {i} about nothing much at all here."} for i in range(2000)]
    segments[1500]["text"] = "Now the derivation of the softmax gradient."
    out = _transcript_for(segments, "add the softmax gradient derivation")
    assert len(out) < TRANSCRIPT_CHARS * 1.1 and "[250:00] Now the derivation of the softmax gradient." in out and "…" in out


# ---- from Chat ------------------------------------------------------------------

def chat(client, llm, text, *acts, reply="Okay, doing that now."):
    llm.replies = [reply, json.dumps({"actions": list(acts)})]
    return client.post("/api/chat", json={"text": text}).json()["messages"]


def test_chat_changes_the_named_lectures_notes_and_undoes_it(client, llm, transcriber):
    c269 = client.post("/api/courses", json={"number": "CS 269", "instructor": "Stefano Soatto"}).json()["id"]
    c259 = client.post("/api/courses", json={"number": "CS 259", "instructor": "Glenn Reinman"}).json()["id"]
    monday = lecture(client, llm, transcriber, c259, "2026-09-28")
    lecture(client, llm, transcriber, c259, "2026-09-30")
    lecture(client, llm, transcriber, c269, "2026-09-29")
    text = "make Monday's CS 259 notes shorter"
    llm.changes = [changed("Cut the Mamba section to one line.", ("Mamba", "## Mamba\n- Selective state-space model."))]
    said = chat(client, llm, text, {"type": "notes", "title": "shorter", "quote": text, "course": "CS 259"})
    assert said[-1]["text"] == f"Cut the Mamba section to one line. [Open the CS 259 · Reinman, Mon Sep 28 notes](#lecture/{monday}). Say “undo that” to put them back."
    assert "Selective state-space model" in get(client, monday)["notes"]
    assert "Lectures with notes (you can change them when asked):\n- CS 259 · Reinman, Wed Sep 30\n- CS 269 · Soatto, Tue Sep 29" \
        in next(r for r in llm.requests if r["messages"][0]["content"].startswith("You are Almanac"))["messages"][0]["content"]
    said = client.post("/api/chat", json={"text": "undo that"}).json()["messages"]
    assert get(client, monday)["notes"] == NOTES and said[-1]["text"].startswith("Done: the CS 259 · Reinman, Mon Sep 28 notes are back")
    # once undone, another "undo" is just conversation
    llm.replies = ["There's nothing else to undo.", json.dumps({"actions": []})]
    client.post("/api/chat", json={"text": "undo"})
    assert get(client, monday)["notes"] == NOTES


def test_rewinding_the_message_restores_the_notes(client, llm, transcriber):
    rid = lecture(client, llm, transcriber)
    text = "turn my latest notes' Mamba part into a question"
    llm.changes = [changed("Done.", ("Mamba", "## Mamba\n- What is selective scan?"))]
    chat(client, llm, text, {"type": "notes", "title": "turn the Mamba part into a question", "quote": text})
    assert "What is selective scan?" in get(client, rid)["notes"]
    mine = [m for m in client.get("/api/chat").json()["messages"] if m["role"] == "user"][-1]
    client.post(f"/api/chat/rewind/{mine['id']}")
    assert get(client, rid)["notes"] == NOTES and get(client, rid)["undo"] is None


def test_chat_says_when_there_are_no_notes_for_that_day(client, llm, transcriber):
    lecture(client, llm, transcriber, day="2026-09-28")
    text = "add the derivation to Tuesday's notes"
    said = chat(client, llm, text, {"type": "notes", "title": "add the derivation", "quote": text})
    assert said[-1]["text"] == "I don't have notes for a lecture on Tue Sep 29." and not llm.change_requests
