"""Lecture notes (phase 2 of .scratch/lecture-recording/spec.md): written by
the model from a Recording's Transcript, built on the student's Jottings, in
the shape its Lecture kind calls for.

A long lecture is written a part at a time (each part with the Jottings made
during it), then the parts are combined. Every Jotting must come through word
for word: code checks, and adds any the model left out. The model's own
connections are labelled "Almanac:"; everything else is what was said."""
import json
import re

from . import recordings
from .clock import local
from .db import WRITE

PART_SECONDS = 40 * 60  # transcript per writing pass (about 6,000 words): most lectures in one or two
JOT = "✎"                # marks the student's own lines in the notes

COMMON = f"""You write study notes for a university student from the transcript of a lecture they attended (times in [m:ss]).
- Keep everything important: what was taught or said, definitions, reasoning, examples, numbers, names of methods and papers. Length doesn't matter; don't summarize away content. Leave out filler, logistics chatter and repetition.
- Write only what the transcript says; don't guess what a misheard word meant or add your interpretation (no "likely…", "probably means…"). A word that seems misheard, or marked [?], is kept as it is, with [?].
- The student's jottings, made during the lecture, are listed with their times. They are the outline: put each one inside the section about what was being said at its time, as its own line, word for word, starting with "{JOT} " (a mark with no text: "{JOT} (marked)"), with the points it refers to indented under it. Don't repeat those points elsewhere. Only the listed jottings start with "{JOT}"; nothing else does.
- Classmates appear only by role ("a student asked", "the presenter answered"); the instructor by name.
- Markdown: "## " for sections, "### " for subsections, "- " for points (indent sub-points by two spaces). No tables."""

KIND_RULES = {
    "paper_session": """This was a paper session: papers presented and discussed. Organize by paper ("## " + the paper's title as on the reading list, if it's one of them), each with:
- "### Main points": the problem, the method, the results, the limits, as presented.
- "### Discussion": each question and its answer: "- Q (a student): …" then "  - A (the presenter): …".
- "### Connections": links to other papers made in the room; then links you notice to papers on the reading list, each starting "Almanac: " (only when clearly related; say why).""",
    "concept_lecture": """This was a lecture teaching concepts. Organize by concept ("## " + the concept), with its definition, the reasoning or derivation walked through step by step, and the examples given.""",
    "presentation_day": """This was a presentation day: projects or talks were presented. Write "## Feedback on your work" first with every comment or suggestion made on the student's own project or talk (if any, as said), then "## Other presentations" with a line or two on each other one (what it is, notable feedback).""",
    None: """Organize by topic ("## " + the topic).""",
}

ANNOUNCED = """End with "## Announced": everything the lecturer said will happen or is expected of the students: dates, deadlines, readings, exams, assignments, office hours, what will be covered when ("in week two I will present…"), schedule changes. One "- " each, with when, as said; "- Nothing announced." only if there is truly none."""


def _stamp(s: float) -> str:
    return f"{int(s // 60)}:{int(s % 60):02d}"


def _transcript(segments) -> str:
    return "\n".join(f"[{_stamp(s['start'])}] {s['text']}" for s in segments)


def _jottings(jots) -> str:
    return "\n".join(f"[{_stamp(j['at'])}] {j['text'] or '(marked)'}" for j in jots) or "(none)"


def _parts(segments, seconds=PART_SECONDS):
    parts, cur = [], []
    for s in segments:
        if cur and s["start"] - cur[0]["start"] >= seconds:
            parts.append(cur)
            cur = []
        cur.append(s)
    return parts + [cur] if cur else parts


def _context(con, rec) -> str:
    c = con.execute("select * from courses where id = ?", (rec["course_id"],)).fetchone() if rec["course_id"] else None
    lk = recordings.lecture_kind(con, rec["course_id"], rec["date"]) if rec["course_id"] else None
    lines = [f"Course: {c['number']} {c['title'] or ''}, taught by {c['instructor']}." if c else "Course: not given.",
             f"Lecture date: {rec['date']}."]
    if lk and lk["papers"] and lk["kind"] == rec["kind"]:
        lines.append("Papers for this lecture on the reading list: " + "; ".join(lk["papers"]))
    reading = _reading_list(con, rec["course_id"])
    if reading and rec["kind"] == "paper_session":
        lines.append("The course's whole reading list (for connections): " + "; ".join(reading[:80]))
    return "\n".join(lines)


def _reading_list(con, course_id) -> list[str]:
    if course_id is None:
        return []
    return [re.sub(r"^(read|review|skim)\s+", "", r["title"], flags=re.I)
            for r in con.execute("select title from tasks where course_id = ? and lower(title) like 'read %' order by due", (course_id,))]


def write(llm, con, rec, segments, jots) -> str:
    """The notes (markdown) for a Recording."""
    kind = rec["kind"]
    system = COMMON + "\n" + KIND_RULES.get(kind, KIND_RULES[None]) + "\n" + ANNOUNCED
    context = _context(con, rec)
    parts = _parts(segments)
    if len(parts) == 1:
        notes = llm.chat([{"role": "system", "content": system},
                          {"role": "user", "content": f"{context}\n\nJottings:\n{_jottings(jots)}\n\nTranscript:\n{_transcript(segments)}"}],
                         temperature=0, max_tokens=8000, timeout=900)
    else:
        drafts = []
        for n, part in enumerate(parts, 1):
            lo, hi = part[0]["start"], part[-1]["end"]
            mine = [j for j in jots if lo <= j["at"] < hi or (n == len(parts) and j["at"] >= lo) or (n == 1 and j["at"] < lo)]
            drafts.append(llm.chat([{"role": "system", "content": COMMON + "\nThis is part " + f"{n} of {len(parts)} of the lecture: write its notes in full; they'll be combined with the others."},
                                    {"role": "user", "content": f"{context}\n\nJottings in this part:\n{_jottings(mine)}\n\nTranscript, part {n}:\n{_transcript(part)}"}],
                                   temperature=0, max_tokens=4000, timeout=900))
        notes = llm.chat([{"role": "system", "content": COMBINE + "\n" + KIND_RULES.get(kind, KIND_RULES[None]) + "\n" + ANNOUNCED},
                          {"role": "user", "content": context + "\n\n" + "\n\n".join(f"--- Notes, part {n} ---\n{d}" for n, d in enumerate(drafts, 1))}],
                         temperature=0, max_tokens=12000, timeout=1200)
    # the model's guesses about what was meant aren't what was said: "(likely referring to touch interfaces)"
    notes = re.sub(r"\s*\((?:likely|probably|possibly|presumably|perhaps)\b[^)]*\)", "", notes, flags=re.I)
    return _keep_jottings(notes.strip(), jots, segments)


COMBINE = f"""You combine the notes of a lecture, written a part at a time, into the student's notes for the whole lecture.
- Keep every point and every detail; only merge what repeats and reorganize into the structure below. Don't add anything new.
- Lines starting "{JOT} " are the student's own: keep each exactly as it is, inside the section about its topic, with its points indented under it; don't repeat those points elsewhere. Don't start any other line with "{JOT}".
- Markdown: "## " for sections, "### " for subsections, "- " for points (indent sub-points by two spaces). No tables."""


WINDOW = (30, 15)  # a jotting refers to what was said from 30 s before it to 15 s after
_STOP = set("the a an and or of to in on for is are was were be it this that with as at by from you we they i he she "
            "so but if not have has had will would can could about what which who there their them our your".split())


def _keywords(t: str) -> set:
    return {w for w in re.findall(r"[a-z0-9]+", t.lower()) if len(w) > 2 and w not in _STOP}


def _keep_jottings(notes: str, jots, segments=()) -> str:
    """Only the student's jottings are marked as theirs, and all are there,
    word for word. A line the model marked {JOT} that isn't one becomes an
    ordinary point. A jotting the model left out (or a Mark) is put just above
    the note point that best matches what was being said at its moment; one
    nothing matches is added at the end."""
    norm = lambda t: re.sub(r"\s+", " ", re.sub(r"\[\d+:\d\d\]", "", t)).strip(" .-").lower()
    real = {norm(j["text"]) for j in jots if j["text"]}
    marks = any(not j["text"] for j in jots)
    lines, placed_marks = [], 0
    for line in notes.splitlines():
        m = re.match(rf"(\s*)(?:[-*] )?{JOT}\s*(.*)", line)
        if m:
            said = norm(m.group(2))
            ours = said in real or any(r and r in said and len(said) <= len(r) + 12 for r in real) or (marks and said.startswith("(marked)"))
            if not ours:
                line = f"{m.group(1)}- {m.group(2).strip()}"
            elif said.startswith("(marked)"):
                placed_marks += 1
        lines.append(line)
    have = norm("\n".join(lines))
    todo = [j for j in jots if (j["text"] and norm(j["text"]) not in have)]
    todo += [j for j in jots if not j["text"]][placed_marks:]
    left = []
    for jot in sorted(todo, key=lambda j: j["at"], reverse=True):  # from the end, so earlier insertions don't shift later ones
        said = " ".join(s["text"] for s in segments if s["start"] <= jot["at"] + WINDOW[1] and s["end"] >= jot["at"] - WINDOW[0])
        want = _keywords(said)
        best, score, section = None, 0, ""
        for n, line in enumerate(lines):
            if line.startswith("## "):
                section = line.lower()
            if "announced" in section or not re.match(r"\s*[-*] ", line):
                continue
            hit = len(want & _keywords(line))
            if hit > score:
                best, score = n, hit
        if best is None:
            left.append(jot)
            continue
        indent = re.match(r"\s*", lines[best]).group(0)
        lines.insert(best, f"{indent}{JOT} {jot['text'] or '(marked)'}")
    notes = "\n".join(lines)
    if left:
        notes += "\n\n## More of your jottings\n" + "\n".join(f"{JOT} {j['text'] or '(marked)'} ({_stamp(j['at'])})" for j in sorted(left, key=lambda j: j["at"]))
    return notes


def after_transcript(con, llm, clock, rec_id):
    """The steps after a Transcript is ready: the notes. (Ticket 11 adds the plan,
    12 the replay task.) A failure leaves the Transcript, says why, and can be retried."""
    rec = con.execute("select * from recordings where id = ?", (rec_id,)).fetchone()
    segments = json.loads(rec["transcript"] or "[]")
    if not segments:
        return
    with WRITE:
        con.execute("update recordings set notes_status = 'writing', notes_error = null where id = ?", (rec_id,))
    try:
        notes = write(llm, con, rec, segments, json.loads(rec["jottings"] or "[]"))
        with WRITE:
            con.execute("update recordings set notes = ?, notes_status = 'done', notes_at = ? where id = ?",
                        (notes, local(clock.now()).strftime("%Y-%m-%dT%H:%M"), rec_id))
        recordings.notify(con, clock, "recording", "Lecture notes ready", f"{recordings._label(con, rec)}: your notes are written.",
                          f"#lecture/{rec_id}")
    except Exception as e:
        with WRITE:
            con.execute("update recordings set notes_status = 'failed', notes_error = ? where id = ?",
                        (f"{type(e).__name__}: {e}", rec_id))
    try:  # a replay ticks off its "watch the recording" task (ticket 12)
        tick_replay_task(con, clock, rec)
    except Exception as e:
        print(f"replay task: {type(e).__name__}: {e}")
    try:  # what the lecturer announced → Proposals and questions (ticket 11)
        from . import announcements
        if (n := announcements.to_plan(con, llm, clock, rec, segments)):
            recordings.notify(con, clock, "recording", "From the lecture, for your plan",
                              f"{recordings._label(con, rec)}: {n} thing{'s' if n != 1 else ''} the lecturer announced. Check them in Suggestions.",
                              "#inbox")
    except Exception as e:
        print(f"announcements: {type(e).__name__}: {e}")


WATCH = re.compile(r"\b(watch|re-?watch|recording|replay)\b", re.I)


def tick_replay_task(con, clock, rec):
    """Watching the lecture is done: its "watch the recording" task (the earliest
    open one due on or after the lecture's day, else the most overdue) is marked
    done as the student's own doing, so it shows in the task's history and can
    be undone."""
    if rec["course_id"] is None:
        return None
    tasks = [dict(r) for r in con.execute("select * from tasks where course_id = ? and status = 'open'", (rec["course_id"],))
             if WATCH.search(r["title"])]
    if not tasks:
        return None
    due = lambda t: (t["due"] or t["do_date"] or "9999")[:10]
    ahead = sorted((t for t in tasks if due(t) >= rec["date"]), key=due)
    task = ahead[0] if ahead else sorted(tasks, key=due)[0]
    from . import inbox
    p = inbox.propose_and_accept(con, clock, rec["source_id"], f"Mark “{task['title']}” done (you recorded the {rec['date']} lecture)",
                                 [{"op": "update", "kind": "tasks", "id": task["id"], "data": {"status": "done"}}])
    if p:
        recordings.notify(con, clock, "recording", f"Ticked off “{task['title']}”",
                          f"You recorded the {rec['date']} lecture. If you haven't watched it yet, open the task and mark it not done.", f"#lecture/{rec['id']}")
    return task
