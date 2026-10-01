"""The assistant's note at the top of Today.

Code gathers the day's facts and writes a plain note at once; the model then
rewrites it in a warmer voice, from those facts only, once a day (and again
when the 9am briefing runs). Until it has, or if it can't, the plain note
stands: Today never waits on the model."""

import json
import threading
from datetime import date, timedelta

from fastapi import APIRouter, Request

from . import plan
from .clock import local
from .db import WRITE
from .scheduler import JOBS, Job, daily

router = APIRouter(prefix="/api")
BACKGROUND = True  # tests write the note inline
_busy: set[str] = set()
_lock = threading.Lock()

PROMPT = """You are Almanac, a student's personal assistant, writing the short note at the top of their Today page. From the facts given (and nothing else), write:
- "headline": one short, warm sentence that sums up the day, starting with "Morning.", "Afternoon." or "Evening." as fits the time. Under 10 words.
- "body": one or two plain sentences on what matters most today and anything due soon. Name things as the facts name them. Never add a fact, a time, a number or advice the facts don't support.
No greetings by name, no emoji, no exclamation marks."""
SCHEMA = {"type": "object", "properties": {"headline": {"type": "string"}, "body": {"type": "string"}},
          "required": ["headline", "body"]}
WORDS = ["Nothing", "One thing", "Two things", "Three things", "Four things", "Five things"]


def _fmt_day(iso: str) -> str:
    d = date.fromisoformat(iso[:10])
    return f"{d:%a, %b} {d.day}"


def _fmt_time(iso: str) -> str:
    h, m = int(iso[11:13]), iso[14:16]
    return f"{h % 12 or 12}:{m} {'PM' if h >= 12 else 'AM'}"


def facts(con, now) -> dict:
    day = now.date().isoformat()
    soon = (now.date() + timedelta(days=14)).isoformat()
    q = lambda sql, *a: [dict(r) for r in con.execute(sql, a)]
    return {
        "now": now,
        "today": q("select title from tasks where status = 'open' and do_date = ? order by id", day),
        "overdue": q("select title from tasks where status = 'open' and do_date < ? order by do_date", day),
        "events": plan.occurrences(q("select * from events"), day, day),
        "due": q("select title, due from deadlines where substr(due, 1, 10) between ? and ? order by due", day, soon),
        "questions": con.execute("select count(*) from questions where status = 'open'").fetchone()[0],
    }


def plain(f) -> dict:
    """A note written by code, from the facts alone."""
    hour = f["now"].hour
    hello = "Morning." if hour < 12 else "Afternoon." if hour < 17 else "Evening."
    n = len(f["today"])
    what = WORDS[n] if n < len(WORDS) else f"{n} things"
    headline = f"{hello} {what} on your list today." if n else f"{hello} Nothing on your list today."
    parts = []
    timed = [e for e in f["events"] if len(e["start"]) > 10]
    if timed:
        parts.append(" ".join(f"{e['title']} is at {_fmt_time(e['start'])}." for e in timed[:2]))
    if f["overdue"]:
        parts.append(f"{f['overdue'][0]['title']} is still open from an earlier day.")
    if f["due"]:
        d = f["due"][0]
        parts.append(f"Next up: {d['title']}, {_fmt_day(d['due'])}.")
    else:
        parts.append("Nothing due in the next two weeks that I know of.")
    return {"headline": headline, "body": " ".join(parts)}


def _facts_text(f) -> str:
    lines = [f"It is {f['now']:%A, %B} {f['now'].day}, {f['now']:%H:%M}."]
    lines.append("Planned for today: " + ("; ".join(t["title"] for t in f["today"]) or "nothing"))
    if f["overdue"]:
        lines.append("Still open from earlier days: " + "; ".join(t["title"] for t in f["overdue"]))
    lines.append("Today's schedule: " + ("; ".join(
        e["title"] + (f" at {_fmt_time(e['start'])}" if len(e["start"]) > 10 else "") for e in f["events"]) or "nothing"))
    lines.append("Due in the next two weeks: " + ("; ".join(f"{d['title']} ({_fmt_day(d['due'])})" for d in f["due"]) or "nothing"))
    if f["questions"]:
        lines.append(f"Questions waiting for the student's answer: {f['questions']}")
    return "\n".join(lines)


def _save(con, day, note, by):
    with WRITE:
        con.execute("insert into notes (date, headline, body, written_by) values (?,?,?,?) on conflict(date) do update set "
                    "headline = excluded.headline, body = excluded.body, written_by = excluded.written_by",
                    (day, note["headline"], note["body"], by))


def write(con, llm, clock):
    """Have the model write today's note (single-flight, background by default)."""
    now = local(clock.now()).replace(tzinfo=None)
    day = now.date().isoformat()
    with _lock:
        if day in _busy:
            return
        _busy.add(day)

    def run():
        try:
            f = facts(con, now)
            raw = llm.chat([{"role": "system", "content": PROMPT}, {"role": "user", "content": _facts_text(f)}],
                           schema=SCHEMA, temperature=0.4, timeout=600)
            got = json.loads(raw)
            headline, body = (got.get("headline") or "").strip(), (got.get("body") or "").strip()
            if headline and body:
                _save(con, day, {"headline": headline, "body": body}, "assistant")
        except Exception:
            pass  # the plain note stays
        finally:
            with _lock:
                _busy.discard(day)

    threading.Thread(target=run, daemon=True).start() if BACKGROUND else run()


@router.get("/note")
def get_note(request: Request):
    s = request.app.state
    now = local(s.clock.now()).replace(tzinfo=None)
    day = now.date().isoformat()
    row = s.db.execute("select * from notes where date = ?", (day,)).fetchone()
    if not row:
        _save(s.db, day, plain(facts(s.db, now)), "plain")
        write(s.db, s.llm, s.clock)
        row = s.db.execute("select * from notes where date = ?", (day,)).fetchone()
    return {"date": day, "headline": row["headline"], "body": row["body"], "written_by": row["written_by"]}


def _morning(state, scheduled, late, missed):
    """At 9, rewrite a note opened earlier today (it predates the morning's
    changes); an unopened day gets its note when Today is first opened."""
    day = local(state.clock.now()).date().isoformat()
    if state.db.execute("select 1 from notes where date = ?", (day,)).fetchone():
        write(state.db, state.llm, state.clock)


JOBS.append(Job("note", daily(9), _morning))
