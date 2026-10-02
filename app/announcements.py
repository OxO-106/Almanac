"""What the lecturer announces reaches the plan (ticket 11 of
.scratch/lecture-recording): a deadline set or moved, a reading assigned, an
exam or session scheduled, a class cancelled.

The model lists them with quotes; a quote must be in the Transcript. Dates
are read relative to the lecture's day, by code where the words allow
("next Thursday", "the 13th", "October 21"). Something already planned with
another date gets an update Proposal (the lecture is newer than the syllabus);
something new a Proposal; anything plan-relevant that isn't clear becomes a
question in chat, quoting the lecturer, never a guess."""
import json
import re
from datetime import date, timedelta

from . import ingest, inbox, merge, plan
from .plan import current_term

PROMPT = """You read the transcript of a university lecture for a student and list what the lecturer announced that changes the student's plan:
- "deadline": something due or to submit, set or moved ("the report is now due the 13th").
- "task": a reading or other work assigned for a later class ("read the Mamba paper for next Monday").
- "event": an exam, extra session, presentation or office hours scheduled at a time.
- "no_class": a class that won't happen ("no class next Wednesday").
Not the lecture's content, not what happens during this lecture, not general advice.
For each: "title" (short, like a calendar entry, e.g. "Midterm report due"), "quote" (the lecturer's exact words from the transcript, under 200 characters, including the date words), "when" as said, and "clear": false if the date is uncertain ("the fourteenth or so", "maybe Friday", two possible dates) or not given.
Dates: a calendar date → {"type":"date","month":M,"day":D} (month 0 if only the day was said, e.g. "the 13th"); a weekday → {"type":"weekday","weekday":"MO".."SU"} (add "next_week": true for "next Monday"); "tomorrow", "in two weeks" → {"type":"in_days","days":N}; "week 5" → {"type":"week","week":5}; anything else → {"type":"unknown"}.
If nothing was announced, return no items."""

SCHEMA = {"type": "object", "properties": {"items": {"type": "array", "items": {"type": "object", "properties": {
    "kind": {"type": "string", "enum": ["deadline", "task", "event", "no_class"]},
    "title": {"type": "string"}, "quote": {"type": "string"}, "when": ingest.WHEN, "clear": {"type": "boolean"}},
    "required": ["kind", "title", "quote", "when", "clear"]}}}, "required": ["items"]}

TABLE = {"deadline": "deadlines", "task": "tasks", "event": "events"}
FIELD = {"deadlines": "due", "tasks": "due", "events": "start"}
CHUNK_SECONDS = 40 * 60


def _day_only(quote: str, when: dict, lecture: date) -> date | None:
    """"the 13th" said in a lecture on Nov 2 → Nov 13 (the next 13th from the lecture)."""
    d = when.get("day")
    if when.get("type") != "date" or not isinstance(d, int) or (when.get("month") or 0) != 0:
        return None
    if not re.search(rf"\b{d}(st|nd|rd|th)?\b", ingest._norm(quote)):
        return None
    for months in range(0, 3):
        y, m = lecture.year + (lecture.month - 1 + months) // 12, (lecture.month - 1 + months) % 12 + 1
        try:
            day = date(y, m, d)
        except ValueError:
            continue
        if day >= lecture:
            return day
    return None


def _when(con, it, lecture: date) -> str | None:
    """The date (or date and time) an announcement gives, from the lecture's day, or None."""
    quote = it["quote"]
    if (said := ingest.said_when(quote)) is not None:
        it = {**it, "when": said}
    elif it["when"].get("type") == "date" and not ingest.date_in_quote(it["when"], quote):
        it = {**it, "when": {**it["when"], "month": 0}}  # "the 13th": the model's month wasn't said; the next 13th it is
    if (day := _day_only(quote, it["when"], lecture)) is not None:
        value = day.isoformat()
    else:
        w = ingest.resolve({"title": it["title"], "quote": quote, "when": it["when"]}, lecture, current_term(con, lecture), {})
        value = w.value if w.value and not w.window else None
    if value and (t := ingest.said_time(quote)) and len(value) == 10:
        value += f"T{t}"
    return value


def _class_days(con, course_id, first: str, last: str) -> set[str]:
    events = [dict(r) for r in con.execute("select * from events where course_id = ? and repeat is not null", (course_id,))]
    return {e["start"][:10] for e in plan.occurrences(events, first, last)}


def _existing(con, table, course_id, title):
    """A plan item this announcement is about: same course, a title sharing its words, any date."""
    for t in {"deadlines": ("deadlines", "events"), "events": ("events", "deadlines"), "tasks": ("tasks",)}[table]:
        for r in con.execute(f"select * from {t} where course_id is ?" + (" and repeat is null" if t == "events" else ""), (course_id,)):
            if merge._same(r["title"], title):
                return t, dict(r)
    return None, None


def _ask(con, clock, rec, it, who):
    q = f"{who} said in the {rec['date']} lecture: “{it['quote']}” When is “{it['title']}”?"
    return inbox.ask(con, clock, rec["source_id"], q, it["quote"], "other")


def find(llm, segments, rec_date: str) -> list[dict]:
    """The model's list of announcements, a chunk of the lecture at a time, quotes checked."""
    text = "\n".join(s["text"] for s in segments)
    out, part, start = [], [], None
    chunks = []
    for s in segments:
        if part and s["start"] - start >= CHUNK_SECONDS:
            chunks.append(part)
            part = []
        if not part:
            start = s["start"]
        part.append(s)
    chunks += [part] if part else []
    for c in chunks:
        try:
            got = json.loads(llm.chat([{"role": "system", "content": PROMPT},
                                       {"role": "user", "content": f"The lecture was on {rec_date}.\n\nTranscript:\n" + "\n".join(s["text"] for s in c)}],
                                      schema=SCHEMA, timeout=600))["items"]
        except Exception:
            continue
        out += [it for it in got if (it.get("title") or "").strip() and ingest.quoted(it.get("quote"), text)]
    return out


def to_plan(con, llm, clock, rec, segments) -> int:
    """Proposals and questions for what the lecture announced. Returns how many."""
    lecture = date.fromisoformat(rec["date"])
    c = con.execute("select * from courses where id = ?", (rec["course_id"],)).fetchone() if rec["course_id"] else None
    who = f"Prof. {c['instructor'].split()[-1]}" if c else "The lecturer"
    made = 0
    for it in find(llm, segments, rec["date"]):
        title, quote = ingest.capitalize(it["title"].strip()), it["quote"]
        value = _when(con, it, lecture) if it.get("clear", True) else None
        if not value or value[:10] < lecture.isoformat():
            _ask(con, clock, rec, {**it, "title": title}, who)
            made += 1
            continue
        if it["kind"] == "no_class":
            for e in con.execute("select * from events where course_id = ? and repeat is not null", (rec["course_id"],)).fetchall():
                if value[:10] in _class_days(con, rec["course_id"], value[:10], value[:10]) and \
                        plan.DAYS[date.fromisoformat(value[:10]).weekday()] in e["repeat"].split(","):
                    skip = ",".join(sorted(set(filter(None, (e["skip"] or "").split(","))) | {value[:10]}))
                    p = inbox.propose(con, clock, rec["source_id"], f"No “{e['title']}” on {value[:10]} (said in the {rec['date']} lecture)",
                                      [{"op": "update", "kind": "events", "id": e["id"], "data": {"skip": skip}}], quote)
                    made += "id" in p
            continue
        table = TABLE[it["kind"]]
        if table == "tasks" and re.match(r"(read|review|skim|watch|prepare)\b", title, re.I) and len(value) == 10 \
                and value in _class_days(con, rec["course_id"], value, value):
            value = (date.fromisoformat(value) - timedelta(days=1)).isoformat()  # for that class: done the day before
        if table == "events" and len(value) == 10:
            table = "deadlines"  # an event without a time: a dated marker until its time is known
        found_table, row = _existing(con, table, rec["course_id"], title)
        if row:
            field = FIELD[found_table]
            old = (row.get(field) or "")
            if old[:10] == value[:10]:
                continue  # already planned for that day
            new = value if len(value) > 10 or len(old) <= 10 else value + old[10:]
            p = inbox.propose(con, clock, rec["source_id"], f"Update “{row['title']}”: {old[:10] or 'no date'} → {new[:10]} (said in the {rec['date']} lecture)",
                              [{"op": "update", "kind": found_table, "id": row["id"], "data": {field: new}}], quote)
            made += "id" in p
            continue
        data = {"title": title, FIELD[table]: value, **({"course_id": rec["course_id"]} if rec["course_id"] is not None else {})}
        if merge.propose_or_fill(con, clock, rec["source_id"], table, data, quote):
            made += 1
    return made
