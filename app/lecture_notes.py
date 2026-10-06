"""Lecture notes (phase 2 of .scratch/lecture-recording/spec.md): written by
the model from a Recording's Transcript, built on the student's Jottings, in
the shape its Lecture kind calls for.

A long lecture is written a part at a time (each part with the Jottings made
during it), then the parts are combined. Every Jotting must come through word
for word: code checks, and adds any the model left out.

A paper session is written from the class first (part notes from the
Transcript alone), then composed with what Papercut knows about each of the
lecture's papers (papers.py), so every paper is covered, also one not
presented. What must be true is settled by code, not the model: whether a
paper was presented (named in the Transcript), the questions asked (their
quotes found in the Transcript, the paper's answer quoted from its text) and
what was announced (announcements.find, quotes checked)."""
import json
import re

from . import ingest, papers, recordings
from .clock import local
from .db import WRITE

PART_SECONDS = 40 * 60  # transcript per writing pass (about 6,000 words): most lectures in one or two
JOT = "✎"                # marks the student's own lines in the notes
NOT_PRESENTED = "*Not presented in class; from the paper.*"
NOT_KNOWN = "*Not presented in class, and not in your library.*"

COMMON = f"""You write study notes for a university student from the transcript of a lecture they attended (times in [m:ss]).
- Keep everything important: what was taught or said, definitions, reasoning, examples, numbers, names of methods and papers. Length doesn't matter; don't summarize away content. Leave out filler, logistics chatter and repetition.
- Write only what the transcript says; don't guess what a misheard word meant or add your interpretation (no "likely…", "probably means…"). A word that seems misheard, or marked [?], is kept as it is, with [?].
- The student's jottings, made during the lecture, are listed with their times. They are the outline: put each one inside the section about what was being said at its time, as its own line, word for word, starting with "{JOT} " (a mark with no text: "{JOT} (marked)"), with the points it refers to indented under it. Don't repeat those points elsewhere. Only the listed jottings start with "{JOT}"; nothing else does.
- Classmates appear only by role ("a student asked", "the presenter answered"); the instructor by name.
- Don't write what was announced (dates, deadlines, readings, office hours): that's added separately.
- Markdown: "## " for sections, "### " for subsections, "- " for points (indent sub-points by two spaces). A table only where it compares things side by side. Math as LaTeX: inline between single dollar signs, e.g. $K_i \\cdot K_j = 0$; a formula on its own line between double dollar signs."""

KIND_RULES = {
    "concept_lecture": """This was a lecture teaching concepts. Organize by concept ("## " + the concept), with its definition, the reasoning or derivation walked through step by step, and the examples given.""",
    "presentation_day": """This was a presentation day: projects or talks were presented. Write "## Feedback on your work" first with every comment or suggestion made on the student's own project or talk (if any, as said), then "## Other presentations" with a line or two on each other one (what it is, notable feedback).""",
    None: """Organize by topic ("## " + the topic).""",
}

PAPER_SESSION = f"""This was a paper session: papers presented and discussed. You get the notes of what was said in class, and the papers for this lecture with what the student's library knows about each: its abstract (the paper's own words) and a machine-written summary; where they differ, the abstract wins. Each paper says whether it was presented in class. Cover every listed paper, also one not presented. When a word in the class notes sounds like a term in a paper's information ("Geta net" for "Gated DeltaNet"), write the paper's term.
What was said in class comes only from the class notes, what a paper says only from its information; never present one as the other. Sections, in this order:
- "## Takeaways": "### " + each paper's title as listed, in the order listed. Under it "**In class**" with the main points made about it in class (from the class notes), then "**From the paper**" with what the paper's information adds that class didn't (usually 2 to 6 points each). A paper not presented in class: only "**From the paper**". One not presented and with nothing known but its title: nothing under its heading.
- "## Comparison": one table with a row for every listed paper and columns that make these papers comparable (for example the problem it targets, the idea, what it saves and what it costs, how it's trained, the main result, the main limitation). Short cells, from the class and the papers; "—" where neither says.
- "## Connections": how these papers relate to each other (builds on, generalizes, is an alternative to, is combined with, is used inside), each "- " ending with where it's stated: "(in class)" or "(paper: " + the short name of the paper that says it + ")". Only links stated in class or in a paper's information, never a general likeness ("both are about efficiency"). Links to other papers of the reading list only when made in class.
- "## Background": what's needed to follow the papers, and other relevant things said: concepts, earlier methods, context, numbers, examples. "### From class", then "### From the papers"; leave out one with nothing.
- "## Summary": one paragraph, medium to long, on the whole lecture as it happened: what was presented and discussed, the conclusions drawn in class, what ties the papers together. Name a paper not presented only as not presented. Clear, accurate and concise; no points.
No other sections: the questions asked in class and what was announced are added separately."""

QUESTIONS = """You list the questions asked during part of a university lecture (a paper session), from its transcript (times in [m:ss]).
List every question someone in the room asked about the content: a student, the instructor, or the presenter asking the room. Not a question a speaker asks and answers within their own presentation ("So why does this matter? Because…"), not logistics ("can everyone see my screen?"), not a speaker checking on the room ("is that clear?", "any questions?", "does that make sense?").
For each:
- "time": where the question starts, as in the transcript ("45:10").
- "asker": "a student", "the presenter", or the instructor by name. Classmates never by name.
- "question": the question in clear words, meaning kept, nothing added.
- "question_quote": the asker's exact words from the transcript, 8 to 40 words.
- "answered": true if it was answered in class; false if it was put off ("I'll come back to that") or left open.
- "answerer": who answered, as for "asker" ("" if not answered).
- "answer": the answer as given in class, clear and complete, only what was said ("" if not answered).
- "answer_quote": exact words of the answer from the transcript, 8 to 40 words ("" if not answered).
- "paper": the listed paper it's about, its title exactly as listed ("" if none or unclear).
If no questions were asked, return none."""

QUESTIONS_SCHEMA = {"type": "object", "properties": {"questions": {"type": "array", "items": {"type": "object", "properties": {
    "time": {"type": "string"}, "asker": {"type": "string"}, "question": {"type": "string"}, "question_quote": {"type": "string"},
    "answered": {"type": "boolean"}, "answerer": {"type": "string"}, "answer": {"type": "string"},
    "answer_quote": {"type": "string"}, "paper": {"type": "string"}},
    "required": ["time", "asker", "question", "question_quote", "answered", "answerer", "answer", "answer_quote", "paper"]}}},
    "required": ["questions"]}

PAPER_ANSWERS = """You add what the papers say to questions asked in a lecture. Each question comes with passages from the papers (paper and section given) and, if there was one, the answer given in class.
For each question: what the passages say that answers it or bears on it, in 1 to 3 clear sentences, from the passages only (nothing from memory). It may agree with the class answer, add to it, or differ: say what the paper says, not whether class was right. If the passages don't answer the question, "answer" is "": never write what they don't say, and don't mention "the passages".
"quote": the exact words from the passage you used, 8 to 40 words. "paper": its short name as given. "section": its section as given."""

PAPER_ANSWERS_SCHEMA = {"type": "object", "properties": {"answers": {"type": "array", "items": {"type": "object", "properties": {
    "n": {"type": "integer"}, "answer": {"type": "string"}, "quote": {"type": "string"},
    "paper": {"type": "string"}, "section": {"type": "string"}}, "required": ["n", "answer", "quote", "paper", "section"]}}},
    "required": ["answers"]}


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


def _lecture_papers(con, rec) -> list[tuple[str, dict | None]]:
    """The lecture's papers from the syllabus, each with its Papercut entry (None if not there)."""
    lk = recordings.lecture_kind(con, rec["course_id"], rec["date"]) if rec["course_id"] else None
    if not (lk and lk["papers"] and lk["kind"] == rec["kind"]):
        return []
    lib = papers.library()
    return [(t, papers.find(t, lib)) for t in lk["papers"]]


def _context(con, rec, segments=(), briefs=True) -> str:
    """The course and date; for a paper session its papers (with what Papercut knows
    and whether the Transcript names them, or for the class notes their titles only)."""
    c = con.execute("select * from courses where id = ?", (rec["course_id"],)).fetchone() if rec["course_id"] else None
    lines = [f"Course: {c['number']} {c['title'] or ''}, taught by {c['instructor']}." if c else "Course: not given.",
             f"Lecture date: {rec['date']}."]
    listed = _lecture_papers(con, rec)
    if listed and not briefs:
        lines.append("Papers for this lecture on the reading list: " + "; ".join(t for t, _ in listed))
    elif listed:
        said = " ".join(s["text"] for s in segments)
        lines.append(f"Papers for this lecture ({len(listed)}), from the syllabus, with what the student's library knows about each:")
        for n, (title, p) in enumerate(listed, 1):
            shown = "Presented in class: " + ("yes (named in the transcript)." if papers.named(title, said) else "no (never named in the transcript).")
            lines.append(f"\n{n}. {title}\n{shown}\n" + (papers.brief(p) if p else "Not in the student's library: only its title is known."))
        lines.append("")
    reading = _reading_list(con, rec["course_id"])
    if reading and rec["kind"] == "paper_session" and briefs:
        lines.append("The course's whole reading list (for connections): " + "; ".join(reading[:80]))
    return "\n".join(lines)


def _reading_list(con, course_id) -> list[str]:
    if course_id is None:
        return []
    return [re.sub(r"^(read|review|skim)\s+", "", r["title"], flags=re.I)
            for r in con.execute("select title from tasks where course_id = ? and lower(title) like 'read %' order by due", (course_id,))]


def _part_notes(llm, context, parts, jots) -> list[str]:
    """Each part's notes, from its transcript and the jottings made during it."""
    drafts = []
    for n, part in enumerate(parts, 1):
        lo, hi = part[0]["start"], part[-1]["end"]
        mine = [j for j in jots if lo <= j["at"] < hi or (n == len(parts) and j["at"] >= lo) or (n == 1 and j["at"] < lo)]
        drafts.append(llm.chat([{"role": "system", "content": COMMON + "\nThis is part " + f"{n} of {len(parts)} of the lecture: write its notes in full; they'll be combined with the others."},
                                {"role": "user", "content": f"{context}\n\nJottings in this part:\n{_jottings(mine)}\n\nTranscript, part {n}:\n{_transcript(part)}"}],
                               temperature=0, max_tokens=4000, timeout=900))
    return drafts


def _combined(drafts) -> str:
    return "\n\n".join(f"--- Notes, part {n} ---\n{d}" for n, d in enumerate(drafts, 1))


def write(llm, con, rec, segments, jots, announced=()) -> str:
    """The notes (markdown) for a Recording. `announced`: what the lecturer
    announced (announcements.find), each with its quote."""
    kind = rec["kind"]
    parts = _parts(segments)
    if kind == "paper_session":
        notes = _paper_session(llm, con, rec, segments, parts, jots)
    else:
        context = _context(con, rec)
        if len(parts) == 1:
            notes = llm.chat([{"role": "system", "content": COMMON + "\n" + KIND_RULES.get(kind, KIND_RULES[None])},
                              {"role": "user", "content": f"{context}\n\nJottings:\n{_jottings(jots)}\n\nTranscript:\n{_transcript(segments)}"}],
                             temperature=0, max_tokens=8000, timeout=900)
        else:
            notes = llm.chat([{"role": "system", "content": COMBINE + "\n" + KIND_RULES.get(kind, KIND_RULES[None])},
                              {"role": "user", "content": context + "\n\n" + _combined(_part_notes(llm, context, parts, jots))}],
                             temperature=0, max_tokens=12000, timeout=1200)
    # the model's guesses about what was meant aren't what was said: "(likely referring to touch interfaces)"
    notes = re.sub(r"\s*\((?:likely|probably|possibly|presumably|perhaps)\b[^)]*\)", "", notes, flags=re.I)
    # what was announced is only what announcements.find quoted from the Transcript
    notes = "\n\n".join(s for s in _sections(notes.strip()) if _heading(s) != "announced")
    if announced:
        notes += "\n\n## Announced\n" + "\n".join(f"- {ingest.capitalize(a['title'].strip())}: “{a['quote'].strip()}”" for a in announced)
    return _keep_jottings(notes.strip(), jots, segments)


def _paper_session(llm, con, rec, segments, parts, jots) -> str:
    """Class notes from the Transcript alone; then composed with the papers into
    Takeaways, Comparison, Connections, Background and Summary; the Questions,
    checked against the Transcript and answered from the papers' text, go before
    the Summary."""
    drafts = _part_notes(llm, _context(con, rec, briefs=False), parts, jots)
    listed = _lecture_papers(con, rec)
    notes = llm.chat([{"role": "system", "content": COMBINE + "\n" + PAPER_SESSION},
                      {"role": "user", "content": _context(con, rec, segments) + "\n\nThe class notes:\n\n" + _combined(drafts)}],
                     temperature=0, max_tokens=12000, timeout=1200)
    said = " ".join(s["text"] for s in segments)
    notes = _mark_not_presented(notes, [(t, p) for t, p in listed if not papers.named(t, said)])
    notes = _drop_unsaid_numbers(notes, said)
    qs = _questions(llm, parts, listed)
    qs = _paper_answers(llm, qs, listed)
    # only the sections asked for: the model adds its own ("Questions Asked in Class", "Announcements")
    secs = [s for s in _sections(notes.strip()) if _heading(s) in PAPER_SECTIONS or s.startswith("## More of your jottings")]
    at = next((i for i, s in enumerate(secs) if _heading(s) == "summary"), len(secs))
    if qs:
        secs.insert(at, _render_questions(qs))
    return "\n\n".join(secs)


PAPER_SECTIONS = {"takeaways", "comparison", "connections", "background", "summary"}
# a paper "answer" that only says what the passages don't contain isn't one
NO_ANSWER = re.compile(r"\bpassages?\b|\b(do|does|did) not (explain|describe|mention|discuss|define|specify|state|address|say)", re.I)
_UNITS = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
_UNIT_WORDS = (("%", r"percent|per cent|%"), ("gb", r"gigabytes?|gigs?|gb"), ("mb", r"megabytes?|megs?|mb"), ("x", r"times|×|x"))


def _as_digits(text: str) -> str:
    """Numbers in words as digits and units in one form, to compare what was
    said with what a note says: "sixty-four", "five percent", "5GB" → "64", "5 %", "5 gb"."""
    t = text.lower().replace(",", "")
    tens, units = "|".join(_TENS), "|".join(_UNITS)
    t = re.sub(rf"\b({tens})[- ]({'|'.join(_UNITS[1:10])})\b", lambda m: str(_TENS[m[1]] + _UNITS.index(m[2])), t)
    t = re.sub(rf"\b({tens})\b", lambda m: str(_TENS[m[1]]), t)
    t = re.sub(rf"\b({units})\b", lambda m: str(_UNITS.index(m[1])), t)
    for unit, forms in _UNIT_WORDS:
        t = re.sub(rf"(?<=\d)\s*(?:{forms})(?![a-z])", f" {unit}", t)
    return t


_AMOUNT = re.compile(r"(?<![a-z_\d.\\])(\d+(?:\.\d+)?)(?: (%|gb|mb|x)(?![a-z]))?")


def _amounts(text: str) -> set[tuple[str, str]]:
    """(number, unit) pairs: "~5GB" → ("5", "gb"); a bare number has unit ""."""
    return set(_AMOUNT.findall(_as_digits(re.sub(r"\$[^$]*\$", "", text))))


def _drop_unsaid_numbers(notes: str, said: str) -> str:
    """A point given as said in class ("**In class**", "### From class") with an
    amount the transcript never says was not said in class ("~5 GB" when the
    lecture said "hundreds of megabytes"): it's left out. Math ($…$) isn't checked."""
    have, out, inside = _amounts(said), [], False
    have |= {(n, "") for n, _ in have}
    for line in notes.splitlines():
        s = line.strip()
        if line.startswith("#"):
            inside = line.startswith("### ") and _hnorm(line[4:]) == "from class"
        elif s == "**In class**":
            inside = True
        elif s.startswith("**From the paper**"):
            inside = False
        elif inside and re.match(r"[-*] ", s) and _amounts(s) - have:
            continue
        out.append(line)
    return "\n".join(out)


def _mark_not_presented(notes: str, absent) -> str:
    """Under the Takeaways heading of each paper class never named: the line
    saying so; its "In class" part is dropped (nothing of it is from class),
    and for one not in the library, everything under it."""
    out, drop = [], None  # None, "all", "paper" (under such a paper), "class" (inside its In class part)
    for line in notes.splitlines():
        s = line.strip()
        if line.startswith("#"):
            gone = [p for t, p in absent if line.startswith("### ") and papers.find(t, [{"title": line[4:]}])]
            out.append(line)
            drop = None
            if gone:
                out.append(NOT_PRESENTED if gone[0] else NOT_KNOWN)
                drop = "paper" if gone[0] else "all"
            continue
        if s in (NOT_PRESENTED, NOT_KNOWN):
            continue
        if drop == "paper" and s == "**In class**":
            drop = "class"
        elif drop == "class" and s.startswith("**From the paper**"):
            drop = "paper"
        if drop not in ("all", "class") or not s:
            out.append(line)
    return "\n".join(out)


def _minutes(t: str) -> float:
    m = re.match(r"\[?(\d+):(\d\d)", t or "")
    return int(m[1]) * 60 + int(m[2]) if m else 0.0


def _questions(llm, parts, listed) -> list[dict]:
    """The questions asked in class, a part at a time; one whose words aren't in
    the Transcript is dropped, an answer whose words aren't is not shown as one."""
    titles = "; ".join(t for t, _ in listed) or "(none listed)"
    out = []
    for part in parts:
        text = " ".join(s["text"] for s in part)
        try:
            got = json.loads(llm.chat([{"role": "system", "content": QUESTIONS},
                                       {"role": "user", "content": f"Papers for this lecture: {titles}\n\nTranscript:\n{_transcript(part)}"}],
                                      schema=QUESTIONS_SCHEMA, temperature=0, max_tokens=6000, timeout=900))["questions"]
        except Exception as e:
            print(f"questions: {type(e).__name__}: {e}")
            continue
        for q in got:
            if not (q.get("question") or "").strip() or not ingest.quoted(q.get("question_quote"), text):
                continue
            if q.get("answered") and not ((q.get("answer") or "").strip() and ingest.quoted(q.get("answer_quote"), text)):
                q = {**q, "answered": False, "unchecked": True}
            out.append(q)
    return sorted(out, key=lambda q: _minutes(q.get("time")))


def _paper_answers(llm, qs, listed) -> list[dict]:
    """Each question with what the papers' text says about it, quoted."""
    found = [p for _, p in listed if p]
    if not qs or not found:
        return qs
    blocks, shown = [], {}
    for n, q in enumerate(qs, 1):
        mine = [p for t, p in listed if p and q.get("paper") and papers.find(q["paper"], [{"title": t}])] or found
        query = q["question"] + " " + (q.get("answer") or "")
        hits = sorted(((score, p, x) for p in mine for score, x in papers.passages(p, query)), key=lambda h: -h[0])[:4]
        shown[n] = " ".join(x["text"] for _, _, x in hits)
        blocks.append(f"Question {n}: {q['question']}\nAnswer in class: {q.get('answer') or '(none)'}\nPassages:\n"
                      + ("\n".join(f"- [{papers.short(p)}, {x['section'] or 'no section'}] {x['text']}" for _, p, x in hits) or "(none)"))
    try:
        got = json.loads(llm.chat([{"role": "system", "content": PAPER_ANSWERS}, {"role": "user", "content": "\n\n".join(blocks)}],
                                  schema=PAPER_ANSWERS_SCHEMA, temperature=0, max_tokens=4000, timeout=900))["answers"]
    except Exception as e:
        print(f"paper answers: {type(e).__name__}: {e}")
        return qs
    qs = [dict(q) for q in qs]
    for a in got:
        n = a.get("n")
        if isinstance(n, int) and 1 <= n <= len(qs) and (a.get("answer") or "").strip() and ingest.quoted(a.get("quote"), shown.get(n, "")) \
                and not NO_ANSWER.search(a["answer"]):
            qs[n - 1]["paper_answer"] = {"text": a["answer"].strip(), "paper": (a.get("paper") or "").strip(), "section": (a.get("section") or "").strip()}
    return qs


def _render_questions(qs) -> str:
    lines = ["## Questions"]
    for q in qs:
        lines.append(f"- **Q** ({q.get('asker') or 'a student'}, {q.get('time') or '?'}): {q['question'].strip()}")
        if q.get("answered"):
            lines.append(f"  - **A** ({q.get('answerer') or 'the presenter'}): {q['answer'].strip()}")
        else:
            lines.append("  - The answer couldn't be matched to the transcript." if q.get("unchecked") else "  - Not answered in class.")
        if pa := q.get("paper_answer"):
            where = ", ".join(x for x in (pa["paper"], pa["section"]) if x)
            lines.append(f"  - **From the paper**{f' ({where})' if where else ''}: {pa['text']}")
    return "\n".join(lines)


COMBINE = f"""You combine the notes of a lecture, written a part at a time, into the student's notes for the whole lecture.
- Keep every point and every detail; only merge what repeats and reorganize into the structure below. Don't add anything that isn't in the part notes or in the papers' information given.
- Lines starting "{JOT} " are the student's own: keep each exactly as it is, inside the section about its topic, with its points indented under it; don't repeat those points elsewhere. Don't start any other line with "{JOT}".
- Markdown: "## " for sections, "### " for subsections, "- " for points (indent sub-points by two spaces). A table only where it compares things side by side. Math as LaTeX: inline between single dollar signs, e.g. $K_i \\cdot K_j = 0$; a formula on its own line between double dollar signs."""


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
    from . import announcements
    try:  # asked once: the notes' Announced section and the plan's Proposals come from the same quotes
        announced = announcements.find(llm, segments, rec["date"])
    except Exception as e:
        print(f"announcements: {type(e).__name__}: {e}")
        announced = None
    try:
        notes = write(llm, con, rec, segments, json.loads(rec["jottings"] or "[]"), announced or [])
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
        if (n := announcements.to_plan(con, llm, clock, rec, segments, announced)):
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


# ---- living notes (phase 3): the student's edits, change requests, Undo ----------
# Every change keeps the notes before it in note_versions; Undo puts the newest
# back (and again for the one before). A change request returns only the
# sections it changes, so the rest stay exactly as they were.

BUSY = ("writing", "changing")


def set_notes(con, clock, rec_id, notes, why) -> int:
    """New notes, the old ones kept first. Returns the kept version's id."""
    with WRITE:
        old = con.execute("select notes from recordings where id = ?", (rec_id,)).fetchone()["notes"]
        vid = con.execute("insert into note_versions (recording_id, notes, why, made_at) values (?, ?, ?, ?)",
                          (rec_id, old or "", why, local(clock.now()).strftime("%Y-%m-%dT%H:%M"))).lastrowid
        con.execute("update recordings set notes = ?, notes_error = null where id = ?", (notes, rec_id))
    return vid


def last_change(con, rec_id):
    return con.execute("select * from note_versions where recording_id = ? order by id desc limit 1", (rec_id,)).fetchone()


def restore(con, rec_id, version_id=None) -> str | None:
    """Put back the notes kept before a change (the newest, or a given one and
    every change after it). Returns what was undone, or None."""
    v = con.execute("select * from note_versions where id = ? and recording_id = ?", (version_id, rec_id)).fetchone() \
        if version_id is not None else last_change(con, rec_id)
    if not v:
        return None
    with WRITE:
        con.execute("update recordings set notes = ?, notes_error = null where id = ?", (v["notes"] or None, rec_id))
        con.execute("delete from note_versions where recording_id = ? and id >= ?", (rec_id, v["id"]))
    return v["why"]


CHANGE_PROMPT = f"""You change a university student's lecture notes the way they ask. The notes are theirs; change only what the request is about and keep everything else as it is.
- Return only the sections you change, each whole: "replaces" is the heading of the section it replaces, exactly as in the notes without "## " ("" for a new section); "markdown" is the new section, starting with its "## " heading. "before" places a new section: the heading of the section it goes before, e.g. the first section's heading for the top ("" for the end, before "Announced"; "" for a replaced one). To remove a section, return it with "markdown": "". A request about everything ("shorter", "fix the formatting") returns every section.
- Use the transcript for anything to add ("add the derivation", "what did the student ask about X"): only what it says, no guesses about what was meant. If the lecture didn't cover (part of) what they ask for, add nothing for that part and don't name it in headings or points; say so only in the summary ("He didn't talk about grading."), never in the notes.
- Lines starting "{JOT} " are the student's own: keep them word for word with their points under them, unless the request is about them. Don't start other lines with "{JOT}".
- Markdown: "## " sections, "### " subsections, "- " points (sub-points indented by two spaces). A table only where it compares things side by side. Math as LaTeX: inline between single dollar signs, e.g. $K_i \\cdot K_j = 0$; a formula on its own line between double dollar signs.
- "summary": one short sentence to the student on what you changed ("Turned the GQA section into bullets.")."""

CHANGE_SCHEMA = {"type": "object", "properties": {
    "summary": {"type": "string"},
    "sections": {"type": "array", "items": {"type": "object", "properties": {
        "replaces": {"type": "string"}, "markdown": {"type": "string"}, "before": {"type": "string"}},
        "required": ["replaces", "before", "markdown"]}}},
    "required": ["summary", "sections"]}

TRANSCRIPT_CHARS = 50_000  # with the notes and the answer, inside the model's window
_LAST = re.compile(r"## (announced|more of your jottings)\b", re.I)
ABOUT_JOTTINGS = re.compile(rf"jott|{JOT}|my (own )?(lines|marks)|what i (wrote|jotted)|\bmark(s|ed)?\b", re.I)
_JOT_LINE = re.compile(rf"(\s*)(?:[-*] )?{JOT}\s*(.*)")
NOT_SAID = re.compile(r"\b(did not|didn't|does not|doesn't|was not|wasn't|were not|weren't|not)\s+(specif|discuss|mention|cover|explain|say|said|state|address|detail|go into|talk)", re.I)


def _sections(notes: str) -> list[str]:
    out, cur = [], []
    for line in notes.splitlines():
        if line.startswith("## ") and cur:
            out.append("\n".join(cur).strip("\n"))
            cur = []
        cur.append(line)
    if cur:
        out.append("\n".join(cur).strip("\n"))
    return [s for s in out if s.strip()]


def _hnorm(h: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", h.lower()).strip()


def _heading(section: str) -> str:
    first = section.split("\n", 1)[0]
    return _hnorm(first[3:]) if first.startswith("## ") else ""


def apply_sections(notes: str, changed: list[dict]) -> str:
    """The notes with the model's changed sections in place; a new one goes before
    the section it names, else at the end, before "Announced"."""
    secs = _sections(notes)

    def find(heading):
        h = _hnorm(re.sub(r"^#+\s*", "", heading or ""))
        return next((i for i, s in enumerate(secs) if s and h and _heading(s) == h), None)

    new = []
    for c in changed:
        md = (c.get("markdown") or "").strip()
        if (hit := find(c.get("replaces"))) is not None:
            secs[hit] = md
        elif md:
            new.append((c.get("before"), md))
    for before, md in new:
        at = find(before)
        secs.insert(at if at is not None else next((i for i, s in enumerate(secs) if s and _LAST.match(s)), len(secs)), md)
    return "\n\n".join(s for s in secs if s)


def _jot_norm(t: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[(\[]?\d+:\d\d[)\]]?", "", t)).strip(" .-").lower()


def restore_jottings(old: str, new: str) -> str:
    """After a change: a {JOT} line the old notes didn't have isn't the student's
    (it becomes an ordinary point); one of theirs the change dropped goes back
    above the point most like the ones it was above before."""
    old_lines, lines = old.splitlines(), new.splitlines()
    theirs = {_jot_norm(m.group(2)) for l in old_lines if (m := _JOT_LINE.match(l))}
    for n, l in enumerate(lines):
        if (m := _JOT_LINE.match(l)) and _jot_norm(m.group(2)) not in theirs:
            lines[n] = f"{m.group(1)}- {m.group(2).strip()}"
    have = {_jot_norm(m.group(2)) for l in lines if (m := _JOT_LINE.match(l))}
    left = []
    for i in reversed([i for i, l in enumerate(old_lines) if (m := _JOT_LINE.match(l)) and _jot_norm(m.group(2)) not in have]):
        under = []
        for l in old_lines[i + 1:]:
            if l.startswith("#") or len(under) == 3 or (_JOT_LINE.match(l) and under):
                break
            if not _JOT_LINE.match(l):  # a jotting right above another one: what's under that one
                under.append(l)
        text = _JOT_LINE.match(old_lines[i]).group(2).strip()
        want = _keywords(" ".join(under) or text)
        best, score, section = None, 0, ""
        for n, l in enumerate(lines):
            if l.startswith("## "):
                section = l.lower()
            if "announced" in section or not re.match(r"\s*[-*] ", l):
                continue
            if (hit := len(want & _keywords(l))) > score:
                best, score = n, hit
        if best is None:
            left.append(text)
        else:
            lines.insert(best, re.match(r"\s*", lines[best]).group(0) + f"{JOT} {text}")
    out = "\n".join(lines)
    if left:
        out += "\n\n## More of your jottings\n" + "\n".join(f"{JOT} {t}" for t in reversed(left))
    return out


def _transcript_for(segments, request: str) -> str:
    """The Transcript, or for a long one the parts that match the request."""
    full = _transcript(segments)
    if len(full) <= TRANSCRIPT_CHARS:
        return full
    want = _keywords(request)
    keep, size = set(), 0
    for i in sorted(range(len(segments)), key=lambda i: -len(want & _keywords(segments[i]["text"]))):
        for j in range(max(0, i - 6), min(len(segments), i + 7)):
            if j not in keep:
                keep.add(j)
                size += len(segments[j]["text"]) + 8
        if size > TRANSCRIPT_CHARS:
            break
    out, prev = [], None
    for j in sorted(keep):
        if prev is not None and j != prev + 1:
            out.append("…")
        out.append(f"[{_stamp(segments[j]['start'])}] {segments[j]['text']}")
        prev = j
    return "\n".join(out)


def change(con, llm, clock, rec_id, request: str) -> dict:
    """Make the change the student asked for. Returns {"summary", "version"}.
    Raises (ValueError: said to the student) leaving the notes as they were."""
    rec = con.execute("select * from recordings where id = ?", (rec_id,)).fetchone()
    old = rec["notes"] or ""
    if not old:
        raise ValueError("This lecture has no notes yet.")
    segments = json.loads(rec["transcript"] or "[]")
    got = json.loads(llm.chat([{"role": "system", "content": CHANGE_PROMPT},
                               {"role": "user", "content": f"{_context(con, rec)}\n\nThe notes:\n{old}\n\n"
                                + (f"Transcript:\n{_transcript_for(segments, request)}\n\n" if segments else "")
                                + f"The student asks: {request}"}],
                              schema=CHANGE_SCHEMA, temperature=0, max_tokens=10000, timeout=1200))
    new = apply_sections(old, got.get("sections") or [])
    new = re.sub(r"\s*\((?:likely|probably|possibly|presumably|perhaps)\b[^)]*\)", "", new, flags=re.I)
    # what the lecture didn't cover is for the summary, not a point in the notes
    had = set(old.splitlines())
    new = "\n".join(l for l in new.splitlines() if l in had or not NOT_SAID.search(l))
    if not ABOUT_JOTTINGS.search(request):
        new = restore_jottings(old, new)
    if new.strip() == old.strip():
        raise ValueError("I didn't find anything in the notes to change for that.")
    vid = set_notes(con, clock, rec_id, new.strip(), f"“{request.strip()[:80]}”")
    return {"summary": (got.get("summary") or "").strip() or "Changed the notes.", "version": vid}


def change_in_background(con, llm, clock, rec_id, request):
    """The lecture page's change request: notes_status says it's running, notes_error why it failed."""
    try:
        done = change(con, llm, clock, rec_id, request)
    except Exception as e:
        with WRITE:
            con.execute("update recordings set notes_status = 'done', notes_error = ? where id = ?",
                        (f"I couldn't make that change: {e}" if isinstance(e, ValueError) else f"I couldn't make that change ({type(e).__name__}: {e}).", rec_id))
        return
    with WRITE:
        con.execute("update recordings set notes_status = 'done' where id = ?", (rec_id,))
    rec = con.execute("select * from recordings where id = ?", (rec_id,)).fetchone()
    recordings.notify(con, clock, "recording", "Notes changed", f"{recordings._label(con, rec)}: {done['summary']}", f"#lecture/{rec_id}")
