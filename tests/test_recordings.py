"""Recordings: upload, the final pass (transcribe, delete the audio, clean up), the Transcript."""
import json

from app import recordings
from test_upload import course_reply, items_reply, upload

SYLLABUS = """Instructor: Miodrag Potkonjak
CS259 Fall 2026
Seminal Achievements in Computer Science
We will read GQA and Kimi Linear, then ZeRO-Infinity and Mamba2.
The Turing Award is the most prestigious award. The award is given each March.
"""


def a_course(client, llm):
    llm.replies = [course_reply([{"number": "CS 259", "instructor": "Miodrag Potkonjak", "title": "Seminal Achievements in Computer Science",
                                  "quote": "Instructor: Miodrag Potkonjak", "meetings": []}]), items_reply()]
    upload(client, "cs259.txt", SYLLABUS.encode())
    (p,) = [p for p in client.get("/api/inbox").json()["proposals"] if p["summary"].startswith("Add course")]
    client.post(f"/api/proposals/{p['id']}/accept")
    return client.get("/api/courses").json()[0]["id"]


def record(client, course_id, name="lecture.m4a", data=b"audio"):
    r = client.post(f"/api/recordings?course_id={course_id}&date=2026-10-02", files={"file": (name, data, "audio/mp4")})
    assert r.status_code == 202, r.text
    return client.get(f"/api/recordings/{r.json()['id']}").json()


def test_a_recording_becomes_a_clean_transcript_and_the_audio_is_gone(client, llm, transcriber, tmp_path):
    course = a_course(client, llm)
    transcriber.seconds = 41.0
    transcriber.segments = [{"start": 0.0, "end": 20.5, "text": "Uh so uh welcome to the the class. My name is Miodrak Potkonyak."},
                            {"start": 20.5, "end": 41.0, "text": "Today we we read uh G Q A and Kimmy linear."}]
    llm.replies = [json.dumps({"segments": [
        {"n": 0, "text": "So, welcome to the class. My name is Miodrag Potkonjak."},
        {"n": 1, "text": "Today we read GQA and Kimi Linear."}]})]
    rec = record(client, course)
    assert rec["status"] == "done" and rec["seconds"] == 41.0
    assert rec["transcript"] == [{"start": 0.0, "end": 20.5, "text": "So, welcome to the class. My name is Miodrag Potkonjak."},
                                 {"start": 20.5, "end": 41.0, "text": "Today we read GQA and Kimi Linear."}]
    assert rec["label"] == "CS 259 · Potkonjak, 2026-10-02"
    assert not list((tmp_path / "recording-audio").iterdir())  # ADR 0001
    system = llm.requests[-1]["messages"][0]["content"]
    for term in ("Miodrag Potkonjak", "GQA", "Kimi", "ZeRO-Infinity", "Mamba2"):  # the course's vocabulary goes to the clean-up
        assert term in system
    titles = [(n["title"], n["url"]) for n in client.get("/api/notifications").json()]
    assert ("Transcript ready", f"#lecture/{rec['id']}") in titles and ("Lecture notes ready", f"#lecture/{rec['id']}") in titles


def test_the_vocabulary_is_the_courses_names_and_terms_not_common_words(client, llm):
    course = a_course(client, llm)
    client.post("/api/tasks", json={"title": "Read Switch Transformers: Scaling to Trillion Parameter Models", "course_id": course})
    vocab = recordings.vocabulary(client.app.state.db, course)
    assert {"CS 259", "Miodrag Potkonjak", "Switch Transformers: Scaling to Trillion Parameter Models", "Turing", "Kimi", "GQA"} <= set(vocab)
    assert "Award" not in vocab and "The" not in vocab  # "award" is also written in lower case: not a name


def test_a_segment_the_model_cut_short_stays_as_transcribed(client, llm, transcriber):
    course = a_course(client, llm)
    said = "The key idea is that attention heads can share keys and values across groups which saves memory."
    transcriber.segments = [{"start": 0.0, "end": 9.0, "text": said}]
    llm.replies = [json.dumps({"segments": [{"n": 0, "text": "Heads share keys."}]})]  # a summary, not a clean-up
    assert record(client, course)["transcript"][0]["text"] == said


def test_a_failed_transcription_says_why_and_leaves_no_audio(client, llm, transcriber, tmp_path):
    course = a_course(client, llm)
    transcriber.error = "ffmpeg couldn't read the audio: Invalid data found when processing input"
    rec = record(client, course)
    assert rec["status"] == "failed" and "Invalid data" in rec["error"] and rec["retry"] is False
    assert not list((tmp_path / "recording-audio").iterdir())
    assert client.get("/api/notifications").json()[-1]["title"].startswith("Couldn't transcribe")


def test_only_audio_or_video_is_taken_and_the_transcript_can_be_deleted(client, llm, transcriber):
    course = a_course(client, llm)
    r = client.post(f"/api/recordings?course_id={course}", files={"file": ("notes.pdf", b"%PDF", "application/pdf")})
    assert r.status_code == 422
    transcriber.segments = [{"start": 0.0, "end": 5.0, "text": "Hello everyone."}]
    rec = record(client, course)
    assert client.delete(f"/api/recordings/{rec['id']}/transcript").status_code == 204
    again = client.get(f"/api/recordings/{rec['id']}").json()
    assert again["transcript"] is None and again["status"] == "done"  # the Recording itself stays
    assert [r["id"] for r in client.get(f"/api/recordings?course_id={course}").json()] == [rec["id"]]


def test_the_syllabus_counts_even_when_the_instructor_was_answered_in_chat(client, llm):
    # the CS 259 syllabus never says "Instructor:", so its label has no name; the course still came from it
    llm.replies = [course_reply([{"number": "CS 259", "instructor": "Miodrag Potkonjak", "title": "Seminal Achievements in Computer Science",
                                  "quote": "Seminal Achievements in Computer Science", "meetings": []}]), items_reply()]
    upload(client, "cs259.txt", SYLLABUS.replace("Instructor: ", "").encode())
    client.get("/api/chat")
    client.post("/api/chat", json={"text": "Miodrag Potkonjak"})
    (p,) = [p for p in client.get("/api/inbox").json()["proposals"] if p["summary"].startswith("Add course")]
    client.post(f"/api/proposals/{p['id']}/accept")
    course = client.get("/api/courses").json()[0]
    assert course["instructor"] == "Miodrag Potkonjak"
    assert {"GQA", "Kimi", "ZeRO-Infinity"} <= set(recordings.vocabulary(client.app.state.db, course["id"]))


def test_a_course_term_put_where_nothing_like_it_was_heard_is_marked():
    vocab = ["Miodrag Potkonjak", "Kimi Linear", "GQA", "Turing"]
    d = recordings._doubtful_terms
    # a name heard as another name becomes the course's name, unmarked (the student wants it)
    assert d("My name is Miodrag Potkonjak. You can call me Miodrag.", "My name is Miodrak Potkonyak. You can call me Mayu.",
             vocab) == "My name is Miodrag Potkonjak. You can call me Miodrag."
    # an ordinary word turned into a course term is still marked
    assert d("It is related to Kimi Linear.", "it is related to the model", vocab) == "It is related to Kimi [?] Linear [?]."
    assert d("Today we read GQA and Kimi Linear.", "Today we we read uh G Q A and Kimmy linear.", vocab) == "Today we read GQA and Kimi Linear."
    assert d("The Turing Award.", "the during award", vocab) == "The Turing Award."
    assert d("We discussed Kimi Linear.", "we discussed the new model", vocab) == "We discussed Kimi [?] Linear [?]."


def test_heading_words_are_not_taken_for_names(client, llm):
    course = a_course(client, llm)
    vocab = recordings.vocabulary(client.app.state.db, course)
    assert "Turing" in vocab and "Seminal" not in vocab  # "the Turing Award" mid-sentence; "Seminal" only starts a line


def test_words_moved_across_a_segment_boundary_are_kept(client, llm, transcriber):
    course = a_course(client, llm)
    transcriber.segments = [{"start": 0.0, "end": 20.0, "text": "uh so this is the same lecture which we had on Monday or on"},
                            {"start": 20.0, "end": 30.0, "text": "uh graduate study at the uh department"}]
    llm.replies = [json.dumps({"segments": [
        {"n": 0, "text": "So this is the same lecture which we had on Monday, or on graduate study at the department."},
        {"n": 1, "text": ""}]})]  # the sentence finished in segment 0
    rec = record(client, course)
    assert [s["text"] for s in rec["transcript"]] == ["So this is the same lecture which we had on Monday, or on graduate study at the department."]
