"""Documents → Proposals and Questions.

The model only reads and quotes: it reports what the document states, with a
verbatim quote and dates as written. Code checks every quote against the
text, turns dates into calendar dates, and queues Proposals for review."""

import io
import json
from pathlib import Path
import re
import unicodedata
import zipfile
from datetime import date, timedelta

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, UploadFile

from . import inbox, merge, plan
from .clock import local
from .plan import current_term
from .db import WRITE
from .scheduler import notify

router = APIRouter(prefix="/api")

# ---- text extraction ----------------------------------------------------------


def _drop_running_lines(pages: list[str]) -> str:
    """Join pages, removing running headers and footers (a web page printed to
    PDF repeats its title, URL, print time and "3/14" on every page); they
    otherwise split sentences at page breaks and look like dates."""
    shape = lambda line: re.sub(r"\d+", "#", line.strip().lower())
    counts = {}
    for p in pages:
        for s in {shape(l) for l in p.splitlines() if l.strip()}:
            counts[s] = counts.get(s, 0) + 1
    running = {s for s, n in counts.items() if len(pages) >= 3 and n > len(pages) / 2}
    return "\n".join(l for p in pages for l in p.splitlines() if shape(l) not in running)


def _pymupdf(data):
    import pymupdf
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        return _drop_running_lines([page.get_text() for page in doc])


def _pypdf(data):
    from pypdf import PdfReader
    return _drop_running_lines([page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages])


def _python_docx(data):
    import docx
    d = docx.Document(io.BytesIO(data))
    rows = ["\t".join(c.text for c in r.cells) for t in d.tables for r in t.rows]
    return "\n".join([p.text for p in d.paragraphs] + rows)


def _docx_xml(data):
    xml = zipfile.ZipFile(io.BytesIO(data)).read("word/document.xml").decode("utf-8")
    return re.sub(r"<[^>]+>", "", re.sub(r"</w:p>", "\n", xml))


def _plain(data):
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError as e:
            err = e
    raise err


EXTRACTORS = {
    ".pdf": [("PyMuPDF", _pymupdf), ("pypdf", _pypdf)],
    ".docx": [("python-docx", _python_docx), ("raw XML", _docx_xml)],
    ".txt": [("text", _plain)], ".md": [("text", _plain)],
}


def extract(filename: str, data: bytes) -> str:
    """Text of the document. Tries each parser in turn; if all fail, the error
    lists what each one actually said (never a guessed cause)."""
    ext = filename[filename.rfind("."):].lower() if "." in filename else ""
    if ext not in EXTRACTORS:
        raise ValueError(f"Can't read {ext or 'this'} files yet. Upload a PDF, DOCX or TXT.")
    errors = []
    for name, fn in EXTRACTORS[ext]:
        try:
            text = fn(data)
        except Exception as e:
            errors.append(f"{name}: {type(e).__name__}: {e}")
            continue
        if text.strip():
            return text
        errors.append(f"{name}: no text found (the file may be a scanned image)")
    raise ValueError("Couldn't read the file. " + " | ".join(errors))


# ---- model passes -------------------------------------------------------------

RULES = """You read a university course document for a student and report what it states. Rules:
- Report only what the document states explicitly. Never guess, infer or fill in a date, time, room, team or assignment.
- "quote": copy one short passage (under 200 characters) exactly as it appears in the document, word for word, that states the item. Do not paraphrase or fix typos.
- Dates: report them as written. A calendar date → {"type":"date","month":M,"day":D} (add "year" only if written). With a time → {"type":"datetime",...,"time":"HH:MM"} in 24-hour time. "Week N" (optionally a weekday) → {"type":"week","week":N,"weekday":"MO".."SU"}. A date stated relative to another item ("two days before the final") → {"type":"relative","relative_to":"<that item>","offset_days":-2}. Not stated → {"type":"unknown"}.
- Set "provisional": true when the document calls the schedule provisional, tentative or subject to change."""

COURSE_PROMPT = RULES + """
Task: list the course(s) this document is for: course number as department and number only (e.g. "CS 239", "COM SCI 269"; not a term or section code), instructor's full name, title, and the regular class meetings (days as MO,TU,WE,TH,FR,SA,SU; start and end as HH:MM 24-hour; location). If the instructor or a meeting time is not written, leave it empty; do not guess. Quote the line that names the course."""

ITEMS_PROMPT = RULES + """
Task: list everything in this part of the document the student must attend, submit or do:
- "deadline": something due or submitted by a moment (registration, report, sign-up).
- "event": a scheduled session the student attends that is not a regular lecture (exam, tutorial, presentation day, check-in, guest lecture).
- "task": a specific piece of work to do before a moment. List each assigned reading on its own, titled "Read <paper or chapter>", and quote the line that ties it to its lecture or date (e.g. "[Required — Lecture 5]"). Not general expectations that apply every week or to whoever presents ("read the papers before class", "participate in discussion", "bring an annotated copy").
- "project": a multi-part deliverable spanning weeks (a course project, a presentation to prepare).
- "question": a fact only the student can supply that decides WHEN something happens or WHETHER a task exists for them (which paper they present and so on which date, their team, their presentation slot, a choice between options such as an exam or a project). Not questions about the content of their work. Write the question to ask them, addressed to "you", as a full sentence ending in "?", in "question".
Also set "question" on any other item whose date depends on the student's choice or assignment.
The quote must contain the date you report. When the date is in a heading or table row above the item, quote from the date to the item and mark the skipped middle with "...", e.g. "Lecture 2: Thursday, October 1 ... P2. ReAct".
- "no_class": a specific date the document says there is no class (holiday, break).
Do not list regular lectures, grading percentages, or policies."""

WHEN = {"type": "object", "properties": {
    "type": {"type": "string", "enum": ["date", "datetime", "week", "relative", "weekday", "in_days", "unknown"]},
    "next_week": {"type": "boolean"}, "days": {"type": "integer"},
    "year": {"type": "integer"}, "month": {"type": "integer"}, "day": {"type": "integer"}, "time": {"type": "string"},
    "week": {"type": "integer"}, "weekday": {"type": "string"},
    "relative_to": {"type": "string"}, "offset_days": {"type": "integer"}}, "required": ["type"]}

COURSE_SCHEMA = {"type": "object", "properties": {"courses": {"type": "array", "items": {"type": "object", "properties": {
    "number": {"type": "string"}, "instructor": {"type": "string"}, "title": {"type": "string"}, "quote": {"type": "string"},
    "meetings": {"type": "array", "items": {"type": "object", "properties": {
        "days": {"type": "string"}, "start": {"type": "string"}, "end": {"type": "string"}, "location": {"type": "string"},
        "quote": {"type": "string"}}, "required": ["days", "quote"]}}},
    "required": ["number", "instructor", "quote"]}}}, "required": ["courses"]}

ITEMS_SCHEMA = {"type": "object", "properties": {"items": {"type": "array", "items": {"type": "object", "properties": {
    "kind": {"type": "string", "enum": ["deadline", "event", "task", "project", "question", "no_class"]},
    "title": {"type": "string"}, "course": {"type": "string"}, "quote": {"type": "string"},
    "when": WHEN, "provisional": {"type": "boolean"}, "question": {"type": "string"}},
    "required": ["kind", "title", "quote", "when"]}}}, "required": ["items"]}

QUESTIONS_PROMPT = RULES + """
Task: a careful personal assistant is turning this course document into the student's plan. List the questions it must ask the student before the plan is complete: facts only the student knows that decide WHEN something happens for them or WHETHER a task applies to them. For example: which paper or topic they were assigned or chose (and so which date they present), which team they are on and their part, which presentation or demo slot they signed up for, which option they take when the document offers a choice (exam or project), and a due date or time the document leaves out for something they must hand in or attend.
Do not ask about course content, grading, or policies. Address the student as "you", one full sentence ending in "?" per question, each with a quote from the document that makes the question necessary. At most 6 questions, most important first."""

QUESTIONS_SCHEMA = {"type": "object", "properties": {"questions": {"type": "array", "items": {"type": "object", "properties": {
    "question": {"type": "string"}, "quote": {"type": "string"}}, "required": ["question", "quote"]}}}, "required": ["questions"]}
QUESTIONS_CHARS = 60000


MERGE_PROMPT = """You help a personal assistant decide what to ask a student about one course document. Below are draft questions, numbered. Many ask the same thing in different words.
- Merge drafts that ask the same thing into one question, worded clearly, addressed to "you", ending in "?".
- Drop drafts that aren't needed to know WHEN something happens for the student or WHETHER a task applies to them (course content, grading, whether they already did something, reminders).
- Never drop a draft asking when something is due or which day it happens; merge it only with drafts about the same thing.
- Questions marked "already asked" are waiting for the student's answer from another document of the same course. If a draft asks the same thing, put it in that question's group and keep that question's wording; never ask it twice.
- Keep at most 8 questions, most important first.
Return each kept question with "from": the numbers of every draft (and already-asked question) it covers."""

MERGE_SCHEMA = {"type": "object", "properties": {"merged": {"type": "array", "items": {"type": "object", "properties": {
    "question": {"type": "string"}, "from": {"type": "array", "items": {"type": "integer"}}},
    "required": ["question", "from"]}}}, "required": ["merged"]}


def _consolidate(llm, context, drafts, required=(), existing=()):
    """Draft index → (question, quote) to ask, an existing open question (a
    dict) that already asks it, or None if merged away/dropped. `required`:
    drafts that may be merged but never dropped (when is it due, which day).
    `existing`: questions already open for this course from other documents.
    If the model call fails, exact duplicates are merged and the rest kept."""
    same = {q["text"].lower(): q for q in existing}
    exact = {}
    final = [same.get(q.lower()) or exact.setdefault(q.lower(), (q, quote)) for q, quote in drafts]
    if len(drafts) + len(existing) < 2:
        return final
    n = len(drafts)
    listing = "\n".join([f"{i}. {q}" for i, (q, _) in enumerate(drafts)] +
                        [f"{n + j}. {q['text']} (already asked)" for j, q in enumerate(existing)])
    try:
        merged = json.loads(llm.chat([{"role": "system", "content": MERGE_PROMPT},
                                      {"role": "user", "content": f"{context}\n\nDrafts:\n{listing}"}],
                                     schema=MERGE_SCHEMA, timeout=900))["merged"]
    except Exception:
        return final
    out = [None] * n
    for m in merged[:8]:
        ids = [i for i in m.get("from") or [] if isinstance(i, int) and 0 <= i < n + len(existing)]
        members = [i for i in ids if i < n]
        old = next((existing[i - n] for i in ids if i >= n), None)
        q = capitalize((m.get("question") or "").strip())
        if members and (old or q.endswith("?")):
            for i in members:
                out[i] = out[i] or old or (q, drafts[members[0]][1])
    for i in required:  # dropped by the model, but the answer is needed
        out[i] = out[i] or final[i]
    return out


ROLE = re.compile(r"\b(instructors?|professor|prof|lecturer|taught|teacher|faculty)\b")


def named_as_instructor(name: str, text: str) -> bool:
    """The document names this person as the instructor: a role word within a
    line or so of their surname ("Instructor: Stefano Soatto", "Robin Ding /
    Instructor"), not just anywhere ("Thaddy will give a tutorial")."""
    t = _norm_keep_len(text)
    surname = name.split()[-1].lower()
    return any(ROLE.search(t[max(0, m.start() - 60):m.end() + 60])
               for m in re.finditer(rf"\b{re.escape(surname)}\b", t))


def capitalize(s: str) -> str:
    """"gating test" → "Gating test"; "iOS demo" stays."""
    return s[:1].upper() + s[1:] if s[:1].islower() and not s[1:2].isupper() else s


CHUNK = 8000  # characters per items pass; the whole doc would overflow the answer budget


def _ask_model(llm, prompt, schema, context, text):
    raw = llm.chat([{"role": "system", "content": prompt},
                    {"role": "user", "content": f"{context}\n\nDocument:\n\"\"\"\n{text}\n\"\"\""}],
                   schema=schema, timeout=900, max_tokens=6000)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        raise ValueError(f"The model returned something that isn't valid JSON: {raw[:200]!r}")


def _items(llm, context, part):
    """The items in one part. A part with a long list (a reading list) can
    overrun the answer: then read it as two halves."""
    try:
        return _ask_model(llm, ITEMS_PROMPT, ITEMS_SCHEMA, context, part)["items"]
    except ValueError:
        halves = chunks(part, len(part) // 2 + 1)
        if len(part) < 2000 or len(halves) < 2:
            raise
        return [it for h in halves for it in _items(llm, context, h)]


def chunks(text, size=CHUNK):
    out, cur = [], ""
    for para in re.split(r"(?<=\n)", text):
        if cur and len(cur) + len(para) > size:
            out.append(cur)
            cur = ""
        cur += para
    return out + [cur] if cur.strip() else out


# ---- checking and resolving ---------------------------------------------------

def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    s = s.translate(str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"',
                                   "–": "-", "—": "-", " ": " "}))
    return re.sub(r"\s+", " ", s).strip().lower()


_words = lambda s: re.findall(r"\w+", _norm(s))


def _match_at(q, t, start):
    """End index if words q match t from `start`, allowing a few skipped words
    (models drop table cells), else -1. The span may be at most
    len + max(4, len/2) words, so words gathered from different places fail."""
    if start >= len(t) or t[start] != q[0]:
        return -1
    limit, pos = start + len(q) + max(4, len(q) // 2), start
    for w in q[1:]:
        try:
            pos = t.index(w, pos + 1, limit)
        except ValueError:
            return -1
    return pos + 1


ELLIPSIS_GAP = 30  # words a "..." may skip: a table row's cells, not the next row


def quoted(quote: str, text: str) -> bool:
    """The quote's words appear in the document in order and close together.
    Pieces joined by "..." may be up to ELLIPSIS_GAP words apart."""
    t = _words(text)
    parts = [p for p in (_words(x) for x in re.split(r"\.\.\.|…", quote or "")) if p]
    if not parts or sum(map(len, parts)) < 2:
        return False

    def rest(pieces, frm):
        if not pieces:
            return True
        return any((end := _match_at(pieces[0], t, s)) >= 0 and rest(pieces[1:], end)
                   for s in range(frm, min(frm + ELLIPSIS_GAP + 1, len(t))))

    return any((end := _match_at(parts[0], t, s)) >= 0 and rest(parts[1:], end) for s in range(len(t)))


def locate(quote: str, text: str):
    """(start, end) character offsets of the quote in the text, else None."""
    spans = [(m.group(), m.start(), m.end()) for m in re.finditer(r"\w+", _norm_keep_len(text))]
    t = [w for w, _, _ in spans]
    parts = [p for p in (_words(x) for x in re.split(r"\.\.\.|…", quote or "")) if p]
    if not parts:
        return None
    for s in range(len(t)):
        end = _match_at(parts[0], t, s)
        for p in parts[1:]:
            if end < 0:
                break
            end = next((e for s2 in range(end, min(end + ELLIPSIS_GAP + 1, len(t))) if (e := _match_at(p, t, s2)) >= 0), -1)
        if end >= 0:
            return spans[s][1], spans[end - 1][2]
    return None


def _norm_keep_len(s: str) -> str:
    """Lower-case with typographic marks unified, same length as the input,
    so word offsets point into the original text."""
    return s.translate(str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"',
                                      "–": "-", "—": "-", " ": " "})).lower()


MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december"]


def date_in_quote(when: dict, quote: str) -> bool:
    """An explicit date counts only if the quote itself states it."""
    w, q = _words(quote), _norm(quote)
    m, d = when.get("month"), when.get("day")
    if not (m and d and 1 <= m <= 12):
        return False
    month_named = any(x in w for x in (MONTHS[m - 1], MONTHS[m - 1][:3], MONTHS[m - 1][:4]))
    numeric = re.search(rf"\b0?{m}[/.-]0?{d}\b", q) is not None
    ordinal = {f"{d}st", f"{d}nd", f"{d}rd", f"{d}th"} & set(w)  # "December 3rd"
    return numeric or (month_named and (str(d) in w or bool(ordinal)))


def time_in_quote(time: str, quote: str) -> bool:
    """"16:00" is stated by "4:00 p.m.", "4pm", "4 PM" or "16:00" in the quote."""
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", (time or "")[:5])
    if not m:
        return False
    h, mm, q = int(m.group(1)), m.group(2), _norm(quote).replace(".", "")
    h12, ampm = (h % 12 or 12), ("pm" if h >= 12 else "am")
    minutes = rf"(:{mm})?" if mm == "00" else rf":{mm}"
    return bool(re.search(rf"\b{h}:{mm}\b", q) or re.search(rf"\b{h12}{minutes}\s*{ampm}\b", q)
                # the start of a range whose am/pm is written once: "4:00-5:50 p.m."
                or re.search(rf"\b{h12}{minutes}\s*-\s*\d{{1,2}}(:\d{{2}})?\s*{ampm}\b", q)
                or (h == 12 and mm == "00" and "noon" in q))


DAY_NAMES = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
NUMBER_WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
                "eleven", "twelve", "thirteen", "fourteen"]


def _explicit(when, today):
    try:
        year = when.get("year") or today.year
        d = date(year, when["month"], when["day"])
        if not when.get("year") and d < today - timedelta(days=60):
            d = date(year + 1, when["month"], when["day"])
    except (ValueError, KeyError, TypeError):
        return None
    return d


def _number_said(n: int, words) -> bool:
    return str(n) in words or (n < len(NUMBER_WORDS) and NUMBER_WORDS[n] in words) or (n == 1 and ("a" in words or "an" in words))


class When:
    """What code could establish about an item's date from its quote."""
    def __init__(self, value=None, window=None, provisional=False, ask=None):
        self.value, self.window, self.provisional, self.ask = value, window, provisional, ask


def resolve(it: dict, today: date, term: dict | None, known: dict) -> When:
    """Turn the model's report of a date into a calendar date, trusting only
    what the quote states. `known`: lower-case title → date of items resolved
    from the same document (for "two days before Phase 1")."""
    when, quote = it.get("when") or {}, it["quote"]
    t, words = when.get("type"), _words(quote)
    if t in ("date", "datetime"):
        d = _explicit(when, today)
        # stated as a date, or as a weekday the model turned into this week's date ("by Friday" → Oct 2)
        said = d and (date_in_quote(when, quote) or (
            0 <= (d - today).days < 7 and (DAY_NAMES[d.weekday()] in words or DAY_NAMES[d.weekday()][:3] in words)))
        if not said:
            return When()
        time = when.get("time") if t == "datetime" and time_in_quote(when.get("time"), quote) else None
        return When(d.isoformat() + (f"T{time[:5]}" if time else ""))
    if t == "week" and term and isinstance(when.get("week"), int):
        n = when["week"]
        if not re.search(rf"\bweek\s*{n}\b", _norm(quote)):
            return When()
        monday = date.fromisoformat(term["week1"]) + timedelta(weeks=n - 1)
        wd = (when.get("weekday") or "").upper()[:2]
        if wd in ("MO", "TU", "WE", "TH", "FR", "SA", "SU"):
            i = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"].index(wd)
            if DAY_NAMES[i] in words or DAY_NAMES[i][:3] in words:
                return When((monday + timedelta(days=i)).isoformat(), provisional=True)
        friday = monday + timedelta(days=4)
        return When(monday.isoformat(), f"{monday}/{friday}", True,
                    f"Which day in Week {n} ({monday:%b} {monday.day} – {friday:%b} {friday.day}) is “{it['title']}”? "
                    "The document only gives the week.")
    if t == "weekday" and (when.get("weekday") or "").upper()[:2] in plan.DAYS:
        # "by Friday" = the coming Friday (today counts); "next Friday" = next week's.
        i = plan.DAYS.index(when["weekday"].upper()[:2])
        if not (DAY_NAMES[i] in words or DAY_NAMES[i][:3] in words):
            return When()
        if when.get("next_week"):
            if "next" not in words:
                return When()
            d = today - timedelta(days=today.weekday()) + timedelta(weeks=1, days=i)
        else:
            d = today + timedelta(days=(i - today.weekday()) % 7)
        return When(d.isoformat())
    if t == "in_days" and isinstance(when.get("days"), int) and 0 <= when["days"] <= 366:
        n = when["days"]
        said = {0: {"today", "tonight"}, 1: {"tomorrow"}}.get(n, set()) & set(words) or \
            (_number_said(n, words) and ("day" in words or "days" in words)) or \
            (n % 7 == 0 and _number_said(n // 7, words) and ("week" in words or "weeks" in words)) or \
            (n == 7 and "week" in words)
        return When((today + timedelta(days=n)).isoformat()) if said else When()
    if t == "relative" and isinstance(when.get("offset_days"), int):
        target = (when.get("relative_to") or "").lower().strip()
        base = known.get(target) or next((v for k, v in known.items() if target and (target in k or k in target)), None)
        off = when["offset_days"]
        stated = off == 0 or str(abs(off)) in words or (abs(off) < len(NUMBER_WORDS) and NUMBER_WORDS[abs(off)] in words) \
            or (abs(off) == 7 and "week" in words)
        if base and stated:
            return When((date.fromisoformat(base[:10]) + timedelta(days=off)).isoformat())
    return When()


# ---- ingest -------------------------------------------------------------------

def ingest(con, llm, clock, source_id: int, filename: str, data: bytes):
    try:
        text = extract(filename, data)
        with WRITE:
            con.execute("update sources set text = ? where id = ?", (text, source_id))
        prior = _supersede(con, source_id)
        _propose_all(con, llm, clock, source_id, text, prior)
        with WRITE:
            con.execute("update sources set status = 'done' where id = ?", (source_id,))
        _tell_done(con, clock, source_id, filename)
    except Exception as e:
        msg = str(e) if isinstance(e, ValueError) else f"The model call failed: {type(e).__name__}: {e}"
        with WRITE:  # withdraw the half-finished result so a retry starts clean
            con.execute("delete from proposals where source_id = ? and status = 'pending'", (source_id,))
            con.execute("delete from questions where source_id = ? and status = 'open'", (source_id,))
            con.execute("update sources set status = 'failed', error = ? where id = ?", (msg, source_id))
        notify(con, clock, "upload", f"Couldn't read {filename}", msg, "#inbox")


def _tell_done(con, clock, source_id, filename):
    """A notification that the suggestions are ready (reading takes minutes)."""
    n = lambda sql: con.execute(sql, (source_id,)).fetchone()[0]
    found = n("select count(*) from proposals where source_id = ? and status = 'pending'")
    asks = n("select count(*) from questions where source_id = ? and status = 'open'")
    about = con.execute("select about from sources where id = ?", (source_id,)).fetchone()[0] or filename
    if not found and not asks:
        return notify(con, clock, "upload", f"Finished reading {about}", "Nothing new to add.", "#inbox")
    parts = [f"{found} suggestion{'s' if found != 1 else ''}"] if found else []
    parts += [f"{asks} question{'s' if asks != 1 else ''} for you in Chat"] if asks else []
    notify(con, clock, "upload", "Suggestions ready" if found else f"Questions about {about}",
           f"{about}: " + " and ".join(parts) + ".", "#inbox" if found else "#chat")


def _supersede(con, source_id) -> dict:
    """If this upload is a new version of a document, withdraw the old
    version's pending proposals and return what earlier versions put in the
    plan: (kind, lower-case title) → current row."""
    lineage = con.execute("select lineage from sources where id = ?", (source_id,)).fetchone()["lineage"]
    if not lineage:
        return {}
    old = [r["id"] for r in con.execute("select id from sources where (id = ? or lineage = ?) and id != ?",
                                        (lineage, lineage, source_id))]
    marks = ",".join("?" * len(old))
    with WRITE:
        con.execute(f"delete from proposals where status = 'pending' and source_id in ({marks})", old)
        con.execute(f"delete from questions where status = 'open' and source_id in ({marks})", old)
        con.execute(f"update sources set replaced_by = ? where id in ({marks}) and replaced_by is null", (source_id, *old))
    prior = {}
    for p in con.execute(f"select ops, applied from proposals where status = 'accepted' and source_id in ({marks})", old):
        for op, id in zip(json.loads(p["ops"]), json.loads(p["applied"])):
            if op["op"] != "create" or op["kind"] in ("courses", "terms"):
                continue
            row = con.execute(f"select * from {op['kind']} where id = ?", (id,)).fetchone()
            if row:
                prior[(op["kind"], row["title"].lower())] = dict(row)
    return prior


def _propose_all(con, llm, clock, source_id, text, prior=None):
    prior = prior or {}
    matched = set()
    today = local(clock.now()).date()
    context = f"Today is {today:%A, %B %d, %Y}."
    dropped = []

    def keep(x, title):
        if quoted(x.get("quote"), text):
            return True
        dropped.append({"title": title, "quote": x.get("quote"), "reason": "quote not found in the document"})
        return False

    # Pass A: which course(s). Reuse a known Course (same number and instructor).
    courses, meetings, labels = {}, [], []
    title = source_title(con, source_id)
    for c in _ask_model(llm, COURSE_PROMPT, COURSE_SCHEMA, f"{context}\nFile name: {title}", text[:CHUNK])["courses"]:
        c["number"] = course_number(c.get("number") or "")
        if not re.search(r"[A-Za-z].*\d", c["number"]):
            # Not a course number (e.g. the course title). Canvas pages often
            # state it only in the file name: "26F-COM SCI-269-SEM-3 …".
            c["number"] = number_in(title) or number_in(text[:2000]) or ""
        if not c["number"]:
            continue
        instructor = (c.get("instructor") or "").strip()
        if instructor and not named_as_instructor(instructor, text):
            instructor = c["instructor"] = ""  # e.g. a TA named for one tutorial: ask instead
        name = f"{c['number']} · {instructor or 'instructor not stated'}"
        if not keep(c, name):
            continue
        # How questions name this document in chat: course code, instructor (two
        # courses can share a number) and name, not the file name.
        who = f"{c['number']} · {instructor}" if instructor else c["number"]
        label = f"{who}: {c['title'].strip()}" if (c.get("title") or "").strip() else who
        labels.append(label)
        with WRITE:
            con.execute("update sources set about = ? where id = ?", ("; ".join(labels), source_id))
        if not instructor:
            # Course identity needs the instructor; ask rather than guess.
            q = inbox.ask(con, clock, source_id, f"Who teaches {label}? The document doesn't name the instructor.", c["quote"])
            data = {"number": c["number"], "instructor": "Not stated", **({"title": c["title"]} if c.get("title") else {})}
            p = inbox.propose(con, clock, source_id, f"Add course {c['number']} (edit in the instructor)",
                              [{"op": "create", "kind": "courses", "data": data}], c["quote"], q["id"])
            p = p.get("existing", p)
            if p.get("status", "pending") == "pending":
                courses[c["number"]] = f"$p{p['id']}.0"
            continue
        known = con.execute("select id from courses where lower(replace(number, ' ', '')) = lower(replace(?, ' ', '')) "
                            "and lower(instructor) = lower(?)", (c["number"], c["instructor"])).fetchone()
        short = f"{c['number']} · {instructor.split()[-1]}"
        if known:
            courses[c["number"]] = known["id"]
        else:
            data = {k: c[k] for k in ("number", "instructor", "title") if c.get(k)}
            same_number = con.execute("select number, instructor from courses where lower(replace(number, ' ', '')) = "
                                      "lower(replace(?, ' ', ''))", (c["number"],)).fetchone()
            q = same_number and inbox.ask(
                con, clock, source_id, f"You already have {same_number['number']} · {same_number['instructor']}. "
                f"Is {name} a different course? If it's the same one, reject this and correct the instructor instead.",
                c["quote"])
            p = inbox.propose(con, clock, source_id, f"Add course {name}",
                              [{"op": "create", "kind": "courses", "data": data}], c["quote"], q["id"] if q else None)
            p = p.get("existing", p)  # already pending from an earlier upload: link to that one
            if p.get("status") == "pending":
                courses[c["number"]] = f"$p{p['id']}.0"
        for m in c.get("meetings") or []:
            if quoted(m.get("quote"), text):
                meetings.append((courses.get(c["number"]), short, m))
    only = next(iter(courses.values())) if len(courses) == 1 else None

    # Pass B: items, a chunk at a time.
    items = []
    for part in chunks(text):
        items += [it for it in _items(llm, context, part) if keep(it, it["title"])]
    # Regular lectures ("Lecture 10: Thursday, November 5 — …") come with the
    # class-meeting Event; models list them anyway.
    items = [it for it in items if not (it["kind"] == "event" and re.match(r"\s*lecture\s*\d+\b", it["title"], re.I))]
    for it in items:
        it["title"] = capitalize(it["title"].strip())
        if re.match(r"no class\b", it["title"], re.I):
            it["kind"] = "no_class"  # a day off, not something to do

    # Resolve absolute dates first so relative ones ("two days before Phase 1") can use them.
    term = current_term(con, today)
    known, resolved = {}, {}
    for rnd in ("absolute", "relative"):
        for i, it in enumerate(items):
            if ((it.get("when") or {}).get("type") == "relative") == (rnd == "relative"):
                resolved[i] = resolve(it, today, term, known)
                if resolved[i].value:
                    known.setdefault(it["title"].lower(), resolved[i].value)
    lectures = lecture_dates(text, today, term)
    lecture_days = {d for d, _ in lectures.values()}
    for i, it in enumerate(items):
        if it["kind"] == "task" and resolved[i].value and resolved[i].value[:10] in lecture_days \
                and re.match(r"(read|review|skim)\b", it["title"], re.I):
            # dated by its lecture's row: read it the day before
            day = date.fromisoformat(resolved[i].value[:10]) - timedelta(days=1)
            resolved[i] = When(day.isoformat())
            continue
        if resolved[i].value or (it.get("when") or {}).get("type") == "relative":
            continue
        if it["kind"] == "task":
            # A reading is due the day before the lecture it's for.
            resolved[i] = _before_lecture(it, lectures) or _before_lecture(it, lectures, _repair(it, text, today, term, known)) or resolved[i]
        elif it["kind"] in ("deadline", "event"):
            # Only schedule entries (deadlines, sessions): general instructions such
            # as "read the papers" sit under headings they don't belong to.
            resolved[i] = _repair(it, text, today, term, known) or resolved[i]

    keep_items, seen = [], []
    for i, it in enumerate(items):
        if _duplicate(it, resolved[i], seen):
            continue
        if it["kind"] == "task" and not resolved[i].value and not it.get("question"):
            # No date and no lecture: a general instruction, not a task to plan.
            dropped.append({"title": it["title"], "quote": it["quote"], "reason": "no date or lecture stated"})
            continue
        if it["kind"] == "task" and resolved[i].value and resolved[i].value[:10] < (today - timedelta(days=1)).isoformat():
            continue  # e.g. the reading for a lecture that has already happened
        keep_items.append(i)

    # Questions: what only the student can tell us, from a pass of its own (so
    # asking doesn't depend on the item pass remembering to), from the items,
    # and the ones code must ask (no date; only a week). All are drafts, merged
    # with each other and with what's already open for this course, then asked.
    drafts, item_draft, week_draft, required = [], {}, {}, []

    def draft(q, quote, check=True):
        q = capitalize((q or "").strip())
        if (q.endswith("?") or not check and "?" in q) and not re.match(r"(have|did) you\b", q, re.I) and (not check or quoted(quote, text)):
            drafts.append((q, quote))
            return len(drafts) - 1

    for q in _ask_model(llm, QUESTIONS_PROMPT, QUESTIONS_SCHEMA, context, text[:QUESTIONS_CHARS])["questions"]:
        if draft(q.get("question"), q.get("quote")) is None and q.get("question") and not quoted(q.get("quote"), text):
            dropped.append({"title": q["question"], "quote": q.get("quote"), "reason": "quote not found in the document"})
    for i in keep_items:
        it, w = items[i], resolved[i]
        kind = KIND.get(it["kind"], (None,))[0]
        d = draft(it.get("question") or (it["title"] if it["kind"] == "question" else ""), it["quote"])
        if d is None and kind in ("deadlines", "events", "projects") and not w.value:
            # A deliverable or session without a stated date must be asked about.
            d = draft(f"When is “{it['title']}”{'' if kind == 'events' else ' due'}? The document doesn't say.", it["quote"], False)
            required.append(d)
        if d is not None:
            item_draft[i] = d
        if w.ask:  # e.g. which day of the week: worth asking, but the item stands without it
            week_draft[i] = draft(w.ask, it["quote"], False)
            required.append(week_draft[i])
    about = con.execute("select about from sources where id = ?", (source_id,)).fetchone()["about"]
    existing = [dict(r) for r in con.execute(
        "select q.* from questions q join sources s on s.id = q.source_id where q.status = 'open' "
        "and s.about = ? and s.id != ?", (about, source_id))] if about else []
    final = _consolidate(llm, context, drafts, required, existing)
    asked = {}

    def ask_draft(d):
        if d is None or final[d] is None:
            return None
        if isinstance(final[d], dict):  # already open from another document
            return final[d]
        q, quote = final[d]
        if q not in asked:
            asked[q] = inbox.ask(con, clock, source_id, q, quote)
        return asked[q]

    for d in range(len(drafts)):
        ask_draft(d)

    no_class = []
    for i in keep_items:
        it = items[i]
        if it["kind"] == "no_class":
            if resolved[i].value and not resolved[i].window:
                no_class.append(resolved[i].value[:10])
            continue
        course = courses.get(course_number(it.get("course") or "")) or only
        _propose_item(con, clock, source_id, it, course, resolved[i], prior, matched, ask_draft(item_draft.get(i)))

    for course, short, m in meetings:
        _propose_meetings(con, clock, source_id, course, short, m, term, no_class, prior, matched)

    # Whatever earlier versions added that this version no longer mentions.
    for (kind, _), row in prior.items():
        if (kind, row["title"].lower()) not in matched:
            inbox.propose(con, clock, source_id, f"Remove “{row['title']}”? It's not in the new version of {title}.",
                          [{"op": "delete", "kind": kind, "id": row["id"]}])

    with WRITE:
        con.execute("update sources set dropped = ? where id = ?", (json.dumps(dropped), source_id))


HEADING_LINES = 15  # how far above an item its date heading may be (one table row)
_MONTH_RE = "|".join(m[:3] + r"\w*" for m in MONTHS)
# A date that starts a line (a table row or heading), optionally after a short
# label such as "Lecture 2:". Dates inside prose sentences don't qualify.
DATE_HEADING = re.compile(
    rf"^[^\w\n]*(?:[A-Za-z]+\s+\d{{1,2}}\s*:\s*)?"
    rf"(?:(?:(?:mon|tue|wed|thu|fri|sat|sun)\w*,?\s+)?(?P<month>{_MONTH_RE})\.?\s+(?P<day>\d{{1,2}})\b(?!\s*,?\s*\d{{4}}\s*,?\s*\d{{1,2}}:)"
    rf"|week\s+(?P<week>\d{{1,2}})\b)", re.I | re.M)


def _repair(it, text, today, term, known):
    """An item whose own quote states no date takes the nearest date heading
    above it (schedules put the date on the row or heading, not beside every
    item). Deterministic on purpose: a model asked to pick a date from the
    passage picked the wrong row's date and a print timestamp. The quote shown
    for review then starts with that heading, so the reason is visible."""
    at = locate(it["quote"], text)
    if not at:
        return None
    above = text[:at[0]].split("\n")
    passage = "\n".join(above[-HEADING_LINES:])
    heading = None
    for m in DATE_HEADING.finditer(passage):
        heading = m
    if not heading:
        return None
    if heading.group("week"):
        when = {"type": "week", "week": int(heading.group("week"))}
    else:
        month = next(i for i, name in enumerate(MONTHS, 1) if heading.group("month").lower()[:3] == name[:3])
        when = {"type": "date", "month": month, "day": int(heading.group("day"))}
    quote = heading.group(0).strip(" \t-•*·")
    w = resolve({"title": it["title"], "quote": quote, "when": when}, today, term, known)
    if not w.value:
        return None
    it["quote"] = f"{quote.strip()} … {it['quote'].strip()}"
    return w


LECTURE_HEADING = re.compile(
    rf"^[^\w\n]*(?:lecture|class|session)\s+(?P<n>\d{{1,2}})\s*[:.\-–—]\s*"
    rf"(?:(?:mon|tue|wed|thu|fri|sat|sun)\w*,?\s+)?(?P<month>{_MONTH_RE})\.?\s+(?P<day>\d{{1,2}})\b", re.I | re.M)
LECTURE_REF = re.compile(r"\b(?:lecture|class|session)\s*[:#\-–—]?\s*(\d{1,2})\b", re.I)


def lecture_dates(text, today, term) -> dict:
    """Lecture number → (date, heading) from schedule lines such as
    "Lecture 5: Tuesday, October 13 — Agent-Computer Interfaces"."""
    out = {}
    for m in LECTURE_HEADING.finditer(text):
        month = next(i for i, name in enumerate(MONTHS, 1) if m.group("month").lower()[:3] == name[:3])
        heading = m.group(0).strip(" \t-•*·")
        w = resolve({"title": "", "quote": heading, "when": {"type": "date", "month": month, "day": int(m.group("day"))}},
                    today, term, {})
        if w.value:
            out.setdefault(int(m.group("n")), (w.value[:10], heading))
    return out


def _before_lecture(it, lectures, under=None) -> When | None:
    """A reading for Lecture N ("[Required — Lecture 5]") is due the day
    before that lecture. `under`: the schedule row the item sits under, for
    a reading listed in the schedule itself (titles starting "Read")."""
    if under:
        if not re.match(r"(read|review|skim)\b", it["title"], re.I):
            return None
        day = date.fromisoformat(under.value[:10])
    else:
        m = LECTURE_REF.search(_norm(it["quote"])) or LECTURE_REF.search(_norm(it["title"]))
        if not m or int(m.group(1)) not in lectures:
            return None
        iso, heading = lectures[int(m.group(1))]
        day = date.fromisoformat(iso)
        it["quote"] = f"{heading} … {it['quote'].strip()}"
    return When((day - timedelta(days=1)).isoformat())


COMPARED = ("due", "start", "end", "deadline", "window", "repeat", "until", "skip", "location", "provisional")


def _emit(con, clock, source_id, kind, data, quote, question_id, prior, matched, summary=None):
    """Propose `data` as a new item, or, if an earlier version of this
    document already put the same item in the plan, only what changed."""
    key = (kind, data["title"].lower())
    old = prior.get(key)
    if not old:  # new to this document: but maybe not to the plan (Bruin Learn, another file, chat)
        return merge.propose_or_fill(con, clock, source_id, kind, data, quote, question_id, summary)
    matched.add(key)
    changed = {f: data[f] for f in COMPARED if f in data and data[f] != old.get(f)
               and not (f == "provisional" and bool(data[f]) == bool(old.get(f)))}
    if changed:
        what = "; ".join(f"{f} {old.get(f) or 'none'} → {v}" for f, v in changed.items())
        inbox.propose(con, clock, source_id, f"Update “{old['title']}”: {what}",
                      [{"op": "update", "kind": kind, "id": old["id"], "data": changed}], quote, question_id)


STOP = {"the", "a", "an", "and", "or", "of", "for", "to", "in", "on", "due", "your", "with"}


def _duplicate(it, when, seen) -> bool:
    """The same kind of item on the same date with overlapping title words is
    one item reported twice (a model lists "Phase 1 due" and "Phase 1
    application, traces and draft requirements" from the same schedule)."""
    words = {w for w in _words(it["title"]) if w not in STOP}
    key = (it["kind"], (when.value or "")[:10])
    for k, other in seen:
        if k == key and key[1] and words and other and len(words & other) / min(len(words), len(other)) >= 0.5:
            return True
    seen.append((key, words))
    return False


def _propose_meetings(con, clock, source_id, course, short, m, term, no_class, prior, matched):
    """Regular class meetings → one weekly Event over the term's instruction
    weeks, skipping holidays on those days and the document's no-class days."""
    days = [d for d in (m.get("days") or "").upper().replace(" ", "").split(",") if d in plan.DAYS]
    start = m.get("start") if time_in_quote(m.get("start"), m["quote"]) else None
    end = m.get("end") if time_in_quote(m.get("end"), m["quote"]) else None
    if not days or not term:
        return
    if not start:
        inbox.ask(con, clock, source_id, f"What time does {short} meet on {'/'.join(days)}? The document doesn't say.", m["quote"])
        return
    first = date.fromisoformat(term["week1"]) - timedelta(days=7)
    while first.isoformat() < term["instruction_begins"] or plan.DAYS[first.weekday()] not in days:
        first += timedelta(days=1)
    holidays = [h[:10] for h in term["holidays"].splitlines()
                if plan.DAYS[date.fromisoformat(h[:10]).weekday()] in days]
    data = {"title": f"{short.split(' · ')[0]} class", "start": f"{first}T{start[:5]}", "repeat": ",".join(days),
            "until": term["instruction_ends"]}
    if end:
        data["end"] = f"{first}T{end[:5]}"
    if m.get("location"):
        data["location"] = m["location"]
    if course is not None:
        data["course_id"] = course
    if skip := sorted(set(holidays + no_class)):
        data["skip"] = ",".join(skip)
    _emit(con, clock, source_id, "events", data, m["quote"], None, prior, matched, f"{short} class meetings")


KIND = {"deadline": ("deadlines", "due"), "event": ("events", "start"), "task": ("tasks", "due"),
        "project": ("projects", "deadline")}


def source_title(con, source_id) -> str:
    return con.execute("select title from sources where id = ?", (source_id,)).fetchone()["title"]


def number_in(s: str) -> str | None:
    """A course number written in text: "COM SCI-269", "CS239", "CS 239" → normalised."""
    m = re.search(r"\b([A-Z]{2,}(?:\s[A-Z]{2,})*)[\s-]?(\d{2,3}[A-Z]?)\b", s)
    return course_number(f"{m.group(1)} {m.group(2)}") if m else None


def course_number(s: str) -> str:
    """"CS239" and "cs  239" → "CS 239"."""
    return re.sub(r"\s+", " ", re.sub(r"([A-Za-z])(\d)", r"\1 \2", s)).strip()


def _propose_item(con, clock, source_id, it, course, when: When, prior, matched, question=None):
    """question: the (merged) question the item waits on, if the model drafted one."""
    kind, field = KIND.get(it["kind"], (None, None))
    if not kind:
        return
    data = {"title": it["title"]}
    if when.value:
        data[field] = when.value
    if when.window and kind != "projects":
        data["window"] = when.window
    if course is not None:
        data["course_id"] = course
    if it.get("provisional") or when.provisional:
        data["provisional"] = True
    if kind == "events" and "start" not in data:
        # An Event needs a time; without one it's a Deadline-like marker until answered.
        kind = "deadlines"
    _emit(con, clock, source_id, kind, data, it["quote"], question["id"] if question else None, prior, matched)


# ---- HTTP ---------------------------------------------------------------------

def _doc_name(filename: str) -> str:
    """"CS239 (1).pdf" and "cs239.pdf" name the same document."""
    stem = filename.rsplit(".", 1)[0]
    return re.sub(r"\s*\(\d+\)$", "", stem).strip().lower()


@router.post("/uploads", status_code=202)
async def upload(file: UploadFile, background: BackgroundTasks, request: Request, replaces: int | None = None):
    """Upload a document; `replaces` (or the same file name) makes it a new
    version of an earlier upload."""
    s = request.app.state
    data = await file.read()
    now = local(s.clock.now()).strftime("%Y-%m-%dT%H:%M")
    if replaces is None:
        prev = next((r for r in s.db.execute("select id, title from sources where kind = 'document' and replaced_by is null "
                                             "and status = 'done' order by id desc") if _doc_name(r["title"]) == _doc_name(file.filename)), None)
    else:
        prev = s.db.execute("select id from sources where id = ?", (replaces,)).fetchone()
        if not prev:
            raise HTTPException(404, "The upload to replace doesn't exist.")
    lineage = None
    if prev:
        lineage = s.db.execute("select coalesce(lineage, id) from sources where id = ?", (prev["id"],)).fetchone()[0]
    with WRITE:
        cur = s.db.execute("insert into sources (kind, title, text, status, created_at, lineage) "
                           "values ('document', ?, '', 'processing', ?, ?)", (file.filename, now, lineage))
    _kept(s, cur.lastrowid, file.filename).write_bytes(data)  # so a failed upload can be retried
    background.add_task(ingest, s.db, s.reader, s.clock, cur.lastrowid, file.filename, data)
    return {"id": cur.lastrowid, "status": "processing"}


def _kept(state, source_id, filename):
    folder = state.db_path.parent / "uploads"
    folder.mkdir(exist_ok=True)
    return folder / f"{source_id}{Path(filename).suffix.lower()}"


@router.post("/sources/{id}/retry", status_code=202)
def retry(id: int, background: BackgroundTasks, request: Request):
    """Read a failed upload again, from the copy kept when it was uploaded."""
    s = request.app.state
    src = _source(s.db, id)
    if src["status"] != "failed":
        raise HTTPException(409, "Only a failed upload can be retried.")
    kept = _kept(s, id, src["title"])
    if not kept.exists():
        raise HTTPException(409, "The file wasn't kept (it was uploaded before retrying existed). Upload it again.")
    with WRITE:
        s.db.execute("update sources set status = 'processing', error = null where id = ?", (id,))
    background.add_task(ingest, s.db, s.reader, s.clock, id, src["title"], kept.read_bytes())
    return {"id": id, "status": "processing"}


def _source(con, id):
    r = con.execute("select id, kind, title, status, error, dropped, created_at, lineage from sources where id = ?", (id,)).fetchone()
    if not r:
        raise HTTPException(404)
    return {**dict(r), "dropped": json.loads(r["dropped"] or "[]")}


@router.get("/sources")
def list_sources(request: Request):
    con = request.app.state.db
    return [_source(con, r["id"]) for r in con.execute(
        "select id from sources where kind = 'document' and replaced_by is null order by id desc")]


@router.get("/sources/{id}")
def get_source(id: int, request: Request):
    return _source(request.app.state.db, id)
