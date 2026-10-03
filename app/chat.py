"""The conversation with the assistant.

Open Questions are asked here one at a time, most important first (the ones
holding up the most proposals), instead of piling up as a list. A reply to a
question answers it, and fills in what was waiting on it where the answer
states a date. Anything else goes to the model: its reply streams back, then
a second pass turns what the student said into Proposals, with the student's
own words as the quote, checked the same way as a syllabus."""

import asyncio
import json
import queue
import re
import threading
from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from . import goals, inbox, ingest, lecture_notes, merge, questions
from .clock import local
from .db import WRITE
from . import plan
from .plan import current_term
from .scheduler import notify

router = APIRouter(prefix="/api/chat")
HISTORY = 20  # messages of context sent to the model


def _utc(clock) -> str:
    return clock.now().isoformat(timespec="seconds")


# A streamed reply's thread sets `said` so the page shows each message the
# moment it's saved, not only when the slower steps after it (reading the
# message for suggestions, an answer's dates) are done.
_stream = threading.local()


def _say(con, clock, role, text, question_id=None, quote=None, proposals=None) -> int:
    """proposals: ids of suggestions this message presents (shown as a card)."""
    with WRITE:
        mid = con.execute("insert into chat_messages (role, text, question_id, quote, created_at, proposals) values (?,?,?,?,?,?)",
                          (role, text, question_id, quote, local(clock.now()).strftime("%Y-%m-%dT%H:%M"),
                           json.dumps(proposals) if proposals else None)).lastrowid
    if said := getattr(_stream, "said", None):
        said(role)
    return mid


def _record(con, message_id, key, value):
    """Note something a user message changed, so rewinding it can undo it."""
    if message_id is None:
        return
    with WRITE:
        row = con.execute("select effects from chat_messages where id = ?", (message_id,)).fetchone()
        effects = json.loads(row["effects"]) if row and row["effects"] else {}
        effects.setdefault(key, []).append(value)
        con.execute("update chat_messages set effects = ? where id = ?", (json.dumps(effects), message_id))


def _eligible(con, clock) -> list[dict]:
    """Open questions not snoozed, most blocking first."""
    return [dict(r) for r in con.execute(
        "select q.*, s.title as source_title, s.about as source_about, s.kind as source_kind, (select count(*) from proposals p where p.question_id = q.id "
        "and p.status = 'pending') as blocking from questions q left join sources s on s.id = q.source_id "
        "where q.status = 'open' and (q.snoozed_until is null or q.snoozed_until <= ?) order by blocking desc, q.id",
        (_utc(clock),))]


def _current(con, clock):
    """The question the assistant last asked, if it's still waiting for a reply."""
    last = con.execute("select m.*, q.status, q.snoozed_until from chat_messages m join questions q on q.id = m.question_id "
                       "order by m.id desc limit 1").fetchone()
    if last and last["status"] == "open" and (not last["snoozed_until"] or last["snoozed_until"] <= _utc(clock)):
        return dict(last)
    return None


def _course_label(con, q) -> str:
    """How a question names its course: code, instructor and name, e.g.
    "CS 239 · Robin Ding: Large Language Models and Code Intelligence", so two
    courses sharing a number aren't mixed up. The instructor is looked up now,
    since it may have been answered after the document was read."""
    about = q.get("source_about") or ""
    if not about:
        return " ".join((q.get("source_title") or "").rsplit(".", 1)[0].replace("_", " ").split())
    labels = []
    for part in about.split("; "):
        head, _, title = part.partition(": ")
        if " · " not in head:
            who = None
            for r in con.execute("select ops, applied, status from proposals where source_id = ? and status != 'rejected'", (q["source_id"],)):
                op = json.loads(r["ops"])[0]
                if op.get("op") != "create" or op.get("kind") != "courses" or op["data"].get("number") != head:
                    continue
                who = op["data"].get("instructor")
                if r["status"] == "accepted" and r["applied"]:
                    row = con.execute("select instructor from courses where id = ?", (json.loads(r["applied"])[0],)).fetchone()
                    who = row["instructor"] if row else who
            head = f"{head} · {who}" if who and who != "Not stated" else f"{head} (instructor not named yet)"
        labels.append(f"{head}: {title}" if title else head)
    return "; ".join(labels)


LEADS = ["Got it.", "Okay.", "Good to know.", "All right.", "Understood."]


def _ask_next(con, clock):
    """Ask the next question. Right after an answer it opens with a short
    acknowledgement (varied, so it doesn't read like a form); after the
    last one, a closing line."""
    if _current(con, clock):
        return
    recent = [dict(r) for r in con.execute("select m.*, s.about from chat_messages m left join questions q on q.id = m.question_id "
                                           "left join sources s on s.id = q.source_id order by m.id desc limit 2")]
    answered = len(recent) == 2 and recent[0]["role"] == "user" and recent[1]["question_id"]
    lead = LEADS[recent[0]["id"] % len(LEADS)] + " " if answered else ""
    queue = _eligible(con, clock)
    if not queue:
        if answered:
            _say(con, clock, "assistant", lead + "That's all I wanted to ask for now.")
        return
    q = queue[0]
    # name the course (with its instructor), not the file; a file name only if the course is unknown
    name = _course_label(con, q)
    about = ""
    if name and q.get("source_kind") != "chat" and name not in q["text"] and not (q.get("source_about") and q["source_about"] in q["text"]):
        if answered and recent[1]["about"] == q.get("source_about"):
            about = f"One more about {name.split(':')[0]}: "  # same course as the last one: its code is enough
        elif answered:
            about = f"Next, about {name}: "
        else:
            about = f"Quick question about {name}: "
    _say(con, clock, "assistant", lead + about + q["text"], q["id"], q["quote"])


def state(con, clock) -> dict:
    _ask_next(con, clock)
    cur = _current(con, clock)
    messages = []
    for r in con.execute("select id, role, text, question_id, quote, created_at, proposals from chat_messages order by id"):
        m = dict(r)
        ids = json.loads(m.pop("proposals") or "[]")
        m["proposals"] = [{k: p[k] for k in ("id", "summary", "status", "ops", "quote", "optional")}
                          for p in (inbox._proposal(con, i) for i in ids if _exists(con, i))]
        messages.append(m)
    waiting = len(_eligible(con, clock)) - (1 if cur else 0)
    return {"messages": messages, "waiting": waiting,
            "current": cur and {"id": cur["id"], "question_id": cur["question_id"], "text": cur["text"],
                                "options": _options(con, cur["question_id"])}}


def _exists(con, proposal_id) -> bool:
    return con.execute("select 1 from proposals where id = ?", (proposal_id,)).fetchone() is not None


def _options(con, question_id) -> list[str]:
    """Answers to offer as buttons, when the question has a fixed set."""
    return questions.option_labels(con, question_id)


# ---- answering a question -----------------------------------------------------

DATE_FIELD = {"deadlines": "due", "tasks": "due", "events": "start", "projects": "deadline"}


# "Not yet" in its many forms: at the start of a short answer ("haven't sign
# up yet", "I have not chosen", "not assigned", "don't know", "TBD"), or
# "yet" / "later" anywhere in one ("no team yet", "will decide later").
UNDECIDED = re.compile(
    r"\s*(i\s+)?((have|has|did|do)\s*n[o']?t\b|(have|has|did|do)\s+not\b|not\s+(yet|sure|decided|assigned|registered|signed|chosen|picked|known|certain)\b"
    r"|no\s+(idea|clue)\b|undecided|unsure|still\s+(deciding|thinking|figuring)|tbd\b|idk\b|dunno\b)", re.I)
UNDECIDED_ANYWHERE = re.compile(r"\b(yet|later|tbd|undecided)\b", re.I)
NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "a": 1, "an": 1, "a couple of": 2, "a few": 3}


def _later(text, urgent) -> int | None:
    """Days to wait before asking again, if the answer is "not yet" / "don't
    know": when they said ("tomorrow", "in 2 days", "next week"), else 3 days
    if something is waiting on it, else a week."""
    t = " ".join(text.lower().split())
    if len(t.split()) > 12 or not (UNDECIDED.match(t) or UNDECIDED_ANYWHERE.search(t)):
        return None
    if "tomorrow" in t:
        return 1
    if m := re.search(r"\b(\d+|one|two|three|four|five|six|seven|an?|a couple of|a few)\s+(day|week)s?\b", t):
        n = int(m.group(1)) if m.group(1).isdigit() else NUMBERS[m.group(1)]
        return min(n * (7 if m.group(2) == "week" else 1), 60)
    if "next week" in t:
        return 7
    return 3 if urgent else 7


def _urgent(con, question) -> bool:
    """Something waits on the answer: a suggestion it holds up, or a date for the plan."""
    blocking = con.execute("select count(*) from proposals where question_id = ? and status = 'pending'", (question["id"],)).fetchone()[0]
    return bool(blocking or re.search(r"\b(when|dates?|day|time|slot)\b", question["text"], re.I))


def _snooze(con, clock, question_id, days):
    """Ask again in `days` (3 if something waits on it, else a week, unless the student said)."""
    again = clock.now() + timedelta(days=days)
    with WRITE:
        con.execute("update questions set snoozed_until = ? where id = ?", (again.isoformat(timespec="seconds"), question_id))
    on = local(again).date()
    _say(con, clock, "assistant", "No problem. I'll ask again " + ("tomorrow." if days == 1 else f"on {on:%a, %b} {on.day}."))


def _answer(con, llm, clock, question, text, message_id=None):
    """A reply to the open question: "not yet" asks again later; anything else
    goes to the handler for what the question is for (questions.py). False:
    it wasn't an answer (none of a choice's options), so it's read as chat."""
    q0 = con.execute("select status, answer, answered_at, snoozed_until from questions where id = ?", (question["id"],)).fetchone()
    _record(con, message_id, "questions_before", [question["id"], dict(q0) if q0 else None])
    if (days := _later(text, _urgent(con, question))) is not None:
        _snooze(con, clock, question["id"], days)
        return None

    def read(said):  # an answer that's for no particular item, read like a chat message
        made = _actions(con, llm, clock, said, None, message_id, answering=True)
        if made:
            _say(con, clock, "assistant", "Here's what I'd add. Check the dates are right:", proposals=made)

    return questions.answer(con, llm, clock, question["id"], text, questions.Reply(
        say=lambda t, qid=None: _say(con, clock, "assistant", t, qid),
        record=lambda key, value: _record(con, message_id, key, value),
        read=read))


# ---- free conversation --------------------------------------------------------

ACTIONS_PROMPT = """You turn what a student just told their personal assistant into suggestions for their plan. Only what the student's latest message says; nothing from earlier messages, nothing invented. Types:
- "task": something they need to do. "event": something at a set time they attend. "deadline": something due by a moment.
- "goal": a long-term outcome they want (set "why" and "horizon": quarter, year or multi-year if they said). "project": a bounded piece of work toward a goal.
- "memory": a lasting fact about the student worth remembering (habits, preferences, constraints, people); "title" is the fact, "topic" a short label.
- "progress": they finished (or undid) one of their open tasks listed below; "title" is that task's title, "done": true.
- "question": something the assistant must ask to plan it properly (e.g. a due date they didn't give); "title" is the question.
- "change": something already in their plan (listed below) changes: moved to another date ("when"), a new time ("start_time", 24-hour "HH:MM"), place or link ("location"), or name ("new_title"). "title" is the item as listed.
- "remove": they want an item in their plan gone (or a routine stopped); "title" is the item as listed.
Use "change" or "remove", not a new item, when they talk about something already planned. Statements count, not only requests: "the CS 259 lecture is at 3pm now" is a change (start_time "15:00"); "the gating test moved to Monday" is a change (when); "I dropped the reading group" is a remove.
"quote": the student's exact words (copied from their message) that state it. Dates, as said: a calendar date → {"type":"date","month":M,"day":D}; "Friday" → {"type":"weekday","weekday":"FR"}; "next Friday" → add "next_week": true; "tomorrow", "in 3 days", "in two weeks" → {"type":"in_days","days":N}; anything else (e.g. "before Thanksgiving") → {"type":"unknown"}.
Also, when the student said which course or project it belongs to: "course" as they named it (e.g. "Ding's CS 239"), "project" likewise.
A class or meeting that repeats every week ("MW 2pm - 3:50pm"): one "event" with "days" (e.g. "MO,WE"), "start_time" and "end_time" (24-hour "HH:MM"), as said; no "when".
Something to do after every class of a course ("watch the recording before the next class"): one "task" with "each_class": true; no "when". Don't ask for dates the schedule already gives.
- "notes": they ask to change the notes of one of their lectures (listed below): "make Monday's CS 259 notes shorter", "add the derivation to my 269 notes". "title" is the change they ask for, in their words; "course" the course as they named it.
Several dates in one message: one action per date, each quoting its own date ("Oct 8th"); no question asking for times when the item is a class session (its time is the class's).
When the message answers a question you asked (shown first, in brackets), its dates are for what the question asks about: new items, never a "change" to a class. "Oct 8th, Oct 22nd" to "Which lectures will you write summaries for?" → a "task" per date: "Write a summary of the CS 201 lecture", when that date, course "CS 201".
If the message is just conversation, return no actions."""

ACTIONS_SCHEMA = {"type": "object", "properties": {"actions": {"type": "array", "items": {"type": "object", "properties": {
    "type": {"type": "string", "enum": ["task", "event", "deadline", "goal", "project", "memory", "progress", "question",
                                        "change", "remove", "notes"]},
    "title": {"type": "string"}, "quote": {"type": "string"}, "when": ingest.WHEN, "done": {"type": "boolean"},
    "why": {"type": "string"}, "horizon": {"type": "string"}, "topic": {"type": "string"},
    "course": {"type": "string"}, "project": {"type": "string"},
    "days": {"type": "string"}, "start_time": {"type": "string"}, "end_time": {"type": "string"}, "each_class": {"type": "boolean"},
    "location": {"type": "string"}, "new_title": {"type": "string"}},
    "required": ["type", "title", "quote"]}}}, "required": ["actions"]}


def _context(con, clock) -> str:
    now = local(clock.now())
    q = lambda sql, *a: [dict(r) for r in con.execute(sql, a)]
    upcoming = q("select title, due as at from deadlines where substr(due, 1, 10) between ? and ? "
                 "union all select title, do_date from tasks where status = 'open' and do_date between ? and ? order by at limit 15",
                 now.date().isoformat(), (now.date() + timedelta(days=14)).isoformat(),
                 now.date().isoformat(), (now.date() + timedelta(days=14)).isoformat())
    open_tasks = q("select title from tasks where status = 'open' order by coalesce(do_date, due, '9999'), id limit 40")
    weekly = [{"title": c["title"], "repeat": ",".join(c["days"]), "start": f"2000-01-01T{c['start']}", "end": c["end"] and f"2000-01-01T{c['end']}",
               "location": (c.get("event") or c["proposal"]["ops"][0]["data"]).get("location")} for c in questions._classes(con)]
    dated = q("select title, start as at from events where repeat is null and substr(start, 1, 10) >= ? "
              "union all select title, due from deadlines where substr(due, 1, 10) >= ? order by at limit 30",
              now.date().isoformat(), now.date().isoformat())
    goals = q("select title from goals where status = 'active'")
    memories = q("select text from memories order by id limit 40")
    lectures = q("select r.date, c.number, c.instructor from recordings r left join courses c on c.id = r.course_id "
                 "where r.notes is not null order by r.date desc, r.id desc limit 10")
    lines = lambda rows, f: "\n".join(f"- {f(r)}" for r in rows) or "- none"
    return (f"Today is {now:%A, %B %d, %Y}, {now:%H:%M} in Los Angeles.\n\n"
            f"Coming up in the next two weeks:\n{lines(upcoming, lambda r: f'{r['at']}: {r['title']}')}\n\n"
            f"Open tasks:\n{lines(open_tasks, lambda r: r['title'])}\n\n"
            f"Weekly classes:\n{lines(weekly, lambda r: f'{r['title']}: {r['repeat']} {r['start'][11:16]}' + (f'-{r['end'][11:16]}' if r['end'] else '') + (f' ({r['location']})' if r['location'] else ''))}\n\n"
            f"Planned sessions and deadlines:\n{lines(dated, lambda r: f'{r['title']} ({r['at']})')}\n\n"
            f"Goals:\n{lines(goals, lambda r: r['title'])}\n\n"
            f"What you know about the student:\n{lines(memories, lambda r: r['text'])}\n\n"
            f"Lectures with notes (you can change them when asked):\n{lines(lectures, _lecture_line)}")


KEEP = 10             # recent messages always sent verbatim
SUMMARY_BUDGET = 8000  # characters of older messages before they're folded into the summary
SUMMARY_PROMPT = ("Summarize the earlier conversation between a student and their personal assistant for the assistant's "
                  "own memory: plans, commitments, dates, feelings and decisions they mentioned, and anything left open. "
                  "Keep facts exactly as stated; don't add any. Under 250 words.")


def _summary(con, llm, clock):
    """(summary text, id of the last message it covers). Folds older messages
    into the summary once they pass SUMMARY_BUDGET, so long chats stay
    within the model's context."""
    last = con.execute("select text, upto from chat_summaries order by id desc limit 1").fetchone()
    text, upto = (last["text"], last["upto"]) if last else ("", 0)
    rows = con.execute("select id, role, text from chat_messages where id > ? order by id", (upto,)).fetchall()
    older = rows[:-(KEEP + 1)]  # the newest row is the message being answered
    if sum(len(r["text"]) for r in older) > SUMMARY_BUDGET:
        transcript = "\n".join(f"{r['role']}: {r['text']}" for r in older)
        try:
            new = llm.chat([{"role": "system", "content": SUMMARY_PROMPT},
                            {"role": "user", "content": (f"Summary so far:\n{text}\n\n" if text else "") + transcript}],
                           temperature=0, timeout=600).strip()
        except Exception:
            return text, upto  # try again next message; recent history still goes out
        text, upto = new, older[-1]["id"]
        with WRITE:
            con.execute("insert into chat_summaries (upto, text, created_at) values (?, ?, ?)",
                        (upto, text, _utc(clock)))
    return text, upto


def _messages(con, llm, clock, text, focus=None):
    summary, upto = _summary(con, llm, clock)
    history = [{"role": r["role"], "content": r["text"]} for r in con.execute(
        "select role, text from chat_messages where id > ? order by id desc limit ?", (upto, HISTORY + 1))][::-1][:-1]
    system = ("You are Almanac, a personal assistant for a university student. Be brief and warm. Never invent facts "
              "about their courses or dates; if you don't know, ask. When they mention things to do, plans or goals, say "
              "you'll suggest adding them, for them to confirm; don't claim anything is already scheduled. When they "
              "ask to change the notes of a lecture, say in a few words that you're making the change now (don't say it's done: the result comes in your next message). No emoji.\n\n"
              + _context(con, clock) + goals.focus_text(con, focus)
              + (f"\n\nEarlier in this conversation (summary):\n{summary}" if summary else ""))
    return [{"role": "system", "content": system}, *history, {"role": "user", "content": text}]


def _chat_source(con, clock, text) -> int:
    """One chat Source per day; its text grows with the day's messages."""
    today = local(clock.now())
    title = f"Chat, {today:%b} {today.day}"
    with WRITE:
        row = con.execute("select id from sources where kind = 'chat' and title = ?", (title,)).fetchone()
        if row:
            con.execute("update sources set text = text || char(10) || ? where id = ?", (text, row["id"]))
            return row["id"]
        return con.execute("insert into sources (kind, title, text, status, created_at) values ('chat', ?, ?, 'done', ?)",
                           (title, text, today.strftime("%Y-%m-%dT%H:%M"))).lastrowid


def _match_item(con, title, course=None):
    """(kind, row) of the plan item the student means: most title words in
    common (at least half), the named course breaking ties."""
    title = re.sub(r"^\s*\d{4}-\d{2}-\d{2}(T\d\d:\d\d)?\s*:\s*|\s*\(\d{4}-\d{2}-\d{2}[^)]*\)\s*$", "", title)  # as listed to the model
    want = set(ingest._words(title)) - ingest.STOP
    best, score = None, 0.0
    for kind in ("events", "deadlines", "tasks"):
        for r in con.execute(f"select * from {kind}" + (" where status = 'open'" if kind == "tasks" else "")):
            have = set(ingest._words(r["title"])) - ingest.STOP
            s = len(want & have) / max(1, len(want)) + (0.25 if course is not None and r["course_id"] == course else 0)
            if s > score:
                best, score = (kind, dict(r)), s
    return best if score >= 0.5 else None


def _series(con, kind, row) -> list[int]:
    """The routine an item belongs to: the items its proposal created with the
    same name ("Watch CS269 recording (Mon Oct 5)", "(Wed Oct 7)", …)."""
    o = plan.origin(con, kind, row["id"])
    if not o:
        return [row["id"]]
    stem = row["title"].split(" (")[0]
    ids = [r["item_id"] for r in con.execute("select item_id from history where proposal_id = ? and kind = ? and op = 'create'",
                                             (o["id"], kind))]
    return [i for i in ids if (r := con.execute(f"select title from {kind} where id = ?", (i,)).fetchone())
            and r["title"].split(" (")[0] == stem] or [row["id"]]


def _change_or_remove(con, clock, source, a, title, text, today, term):
    """"Move the one-pager to Tuesday", "the CS 259 lecture is at 3 now", "delete
    the gating test": a proposal changing or removing what's already planned.
    New dates, times and places must be in the student's words."""
    hit = _match_item(con, title, _match_course(con, a.get("course"), text))
    if not hit:
        return None
    kind, row = hit
    quote = a["quote"]
    if a["type"] == "remove":
        ids = _series(con, kind, row)
        name = row["title"].split(" (")[0] if len(ids) > 1 else row["title"]
        p = inbox.propose(con, clock, source, f"Remove “{name}”" + (f" ({len(ids)} {kind})" if len(ids) > 1 else ""),
                          [{"op": "delete", "kind": kind, "id": i} for i in ids], quote)
        return p if "id" in p else None
    field = DATE_FIELD[kind]
    data, said = {}, []
    when = ingest.said_when(quote) or a.get("when")  # the date words as code reads them win
    w = ingest.resolve({"title": row["title"], "quote": quote, "when": when}, today, term, {}) if when else None
    old = row.get(field) or ""
    if w and w.value:
        day = w.value[:10]
        data[field] = day + (old[10:] if len(old) > 10 and len(w.value) == 10 else w.value[10:])
        if kind == "events" and row.get("end") and len(old) > 10:
            data["end"] = day + row["end"][10:]
        said.append(_fmt_day(data[field]))
    if (t := a.get("start_time")) and ingest.time_in_quote(t, quote) and kind in ("events", "deadlines", "tasks") and old:
        start = (data.get(field) or old)[:10] + "T" + t[:5]
        if kind == "events" and row.get("end") and len(old) > 10:  # keep the length
            from datetime import datetime as dt
            length = dt.fromisoformat(row["end"]) - dt.fromisoformat(old)
            data["end"] = (dt.fromisoformat(start) + length).isoformat(timespec="minutes")
        data[field] = start
        said.append(f"at {questions._fmt_time(t[:5])}")
    if (loc := (a.get("location") or "").strip()) and kind == "events" and _place_ok(loc, text):
        data["location"] = loc
        said.append(f"at {loc}")
    if (new := (a.get("new_title") or "").strip()) and set(ingest._words(new)) <= set(ingest._words(text)):
        data["title"] = ingest.capitalize(new)
        said.append(f"renamed “{data['title']}”")
    if not data:
        return None
    if "provisional" in row and row["provisional"] and field in data:
        data["provisional"] = False
    if row.get("window") and field in data:
        data["window"] = None
    p = inbox.propose(con, clock, source, f"Change “{row['title']}”: {', '.join(said)}",
                      [{"op": "update", "kind": kind, "id": row["id"], "data": data}], quote)
    return p if "id" in p else None


def _place_ok(loc, text) -> bool:
    """A place the student wrote: in their words as written, and shaped like a
    place (a capital, a number or a link), so "now" or "online later" isn't one."""
    return loc in text and (loc[:1].isupper() or any(ch.isdigit() for ch in loc) or "http" in loc)


def _fmt_day(value):
    d = date.fromisoformat(value[:10])
    return f"{d:%a %b} {d.day}" + (f", {questions._fmt_time(value[11:16])}" if len(value) > 10 else "")


def _match_task(con, title):
    """The open task a progress report is about (most title words in common)."""
    want = set(ingest._words(title)) - ingest.STOP
    best, score = None, 0.0
    for r in con.execute("select id, title from tasks where status = 'open'"):
        have = set(ingest._words(r["title"])) - ingest.STOP
        s = len(want & have) / max(1, len(want))
        if s > score:
            best, score = r, s
    return best if score >= 0.5 else None


def _match_course(con, named, text):
    """The course the student named ("Ding's CS 239"), checked against their own
    words: the instructor's surname first (two CS 239s), else the number."""
    if not named:
        return None
    said = (named + " " + text).lower()
    courses = [dict(r) for r in con.execute("select * from courses")]
    for r in con.execute("select id, ops from proposals where status = 'pending'").fetchall():  # a course still waiting
        ops = json.loads(r["ops"])
        if len(ops) == 1 and ops[0]["op"] == "create" and ops[0]["kind"] == "courses":
            courses.append({**ops[0]["data"], "instructor": ops[0]["data"].get("instructor") or "Not stated", "id": f"$p{r['id']}.0"})
    # whole words: "recording" doesn't name Ding
    by_name = [c for c in courses if c["instructor"] != "Not stated"
               and re.search(rf"\b{re.escape(c['instructor'].split()[-1].lower())}\b", said)]
    if len(by_name) == 1:
        return by_name[0]["id"]
    # by number, as written or by its digits ("CS269" is CS 269), if only one course has it
    def digits(number):
        m = re.search(r"\d+[a-z]?", number.lower())
        return m.group() if m else None
    by_number = [c for c in courses if (n := digits(c["number"])) and re.search(rf"(?<!\d){n}(?![\da-z])", said)]
    return by_number[0]["id"] if len(by_number) == 1 else None


def _days_said(days: list[str], quote: str) -> bool:
    """Each weekday is in the student's words: by name ("Mondays", "Wed") or
    in a letter run ("MW", "TTh", "MWF")."""
    words = ingest._words(quote)
    runs = [w for w in words if re.fullmatch(r"(m|tu|t|w|th|r|f|sa|su)+", w) and len(w) >= 2]
    letter = {"MO": "m", "TU": "t", "WE": "w", "TH": ("th", "r"), "FR": "f", "SA": "sa", "SU": "su"}
    for d in days:
        name = ingest.DAY_NAMES[plan.DAYS.index(d)]
        if any(w.startswith(name[:3]) for w in words):
            continue
        marks = letter[d] if isinstance(letter[d], tuple) else (letter[d],)
        if not any(m in r for r in runs for m in marks):
            return False
    return True


def _each_class(con, title, course, meeting, today, term):
    """One task per class from today on, each due when the next class starts
    ("watch the recording before the next class")."""
    events = [{"end": None, "until": None, "skip": None, **meeting}] if meeting else [dict(r) for r in con.execute(
        "select * from events where course_id = ? and repeat is not null", (course,))] if course is not None else []
    if not events or not term:
        return []
    occ = plan.occurrences(events, (today - timedelta(days=7)).isoformat(), term["instruction_ends"])
    out = []
    for this, nxt in zip(occ, occ[1:]):
        if nxt["start"][:10] < today.isoformat():
            continue  # both already past; the latest class whose next one is ahead still counts
        d = date.fromisoformat(this["start"][:10])
        data = {"title": f"{title} ({d:%a %b} {d.day})", "due": nxt["start"], "do_date": max(this["start"][:10], today.isoformat())}
        if course is not None:
            data["course_id"] = course
        out.append({"op": "create", "kind": "tasks", "data": data})
    return out


def _match_project(con, named, course_id, text):
    if not named:
        return None
    hits = [r["id"] for r in con.execute("select id, title, course_id from projects where status = 'active'")
            if merge._same(r["title"], named) and (course_id is None or r["course_id"] in (None, course_id))]
    return hits[0] if len(hits) == 1 else None


def _lecture_line(r) -> str:
    return (f"{r['number']} · {r['instructor'].split()[-1]}" if r["number"] else "Lecture") + f", {(d := date.fromisoformat(r['date'])):%a %b} {d.day}"


WEEKDAY = re.compile(r"\b(mon|tues|wednes|thurs|fri|satur|sun)day\b", re.I)


def _match_lecture(con, clock, named, text):
    """(recording, None) for the lecture whose notes the student means, or (None, why not):
    the named course's, on the day they said (a weekday: the latest such day), else its latest."""
    rows = [dict(r) for r in con.execute("select r.*, c.number, c.instructor from recordings r left join courses c on c.id = r.course_id "
                                         "where r.notes is not null order by r.date desc, r.id desc")]
    if (course := _match_course(con, named, text)) is not None:
        rows = [r for r in rows if r["course_id"] == course]
    elif named and (n := re.search(r"\d+[a-z]?", named.lower())):  # "CS 239" when there are two: either one's
        rows = [r for r in rows if r["number"] and n.group() in r["number"].lower()]
    today = local(clock.now()).date()
    day = None
    if re.search(r"\btoday'?s?\b", text, re.I):
        day = today
    elif re.search(r"\byesterday'?s?\b", text, re.I):
        day = today - timedelta(days=1)
    elif m := WEEKDAY.search(text):
        want = ["mon", "tues", "wednes", "thurs", "fri", "satur", "sun"].index(m.group(1).lower())
        day = today - timedelta(days=(today.weekday() - want) % 7)
    elif (w := ingest.said_when(text)) and w.get("type") == "date" and w.get("month"):
        try:
            day = date(today.year, w["month"], w["day"])
        except ValueError:
            day = None
        day = day.replace(year=day.year - 1) if day and day > today else day
    if day:
        rows = [r for r in rows if r["date"] == day.isoformat()]
        if not rows:
            return None, f"I don't have notes for {'that course on ' if named else 'a lecture on '}{day:%a %b} {day.day}."
    return (rows[0], None) if rows else (None, "I couldn't tell which lecture's notes you mean.")


def _change_notes(con, llm, clock, a, text, message_id):
    """A "notes" action: the change is made now (Undo: "undo that" or Rewind)."""
    rec, why = _match_lecture(con, clock, a.get("course"), text)
    if not rec:
        _say(con, clock, "assistant", why)
        return
    label = _lecture_line(rec)
    if rec["notes_status"] in lecture_notes.BUSY:
        _say(con, clock, "assistant", f"The {label} notes are being written or changed right now. Ask me again in a minute.")
        return
    try:
        done = lecture_notes.change(con, llm, clock, rec["id"], a["title"])
    except Exception as e:
        _say(con, clock, "assistant", f"I couldn't change the {label} notes: " + (str(e) if isinstance(e, ValueError) else f"{type(e).__name__}: {e}"))
        return
    _record(con, message_id, "notes", [rec["id"], done["version"]])
    _say(con, clock, "assistant", f"{done['summary']} [Open the {label} notes](#lecture/{rec['id']}). Say “undo that” to put them back.")


UNDO = re.compile(r"^\s*(please\s+)?(undo|revert|put (it|them) back|change (it|them) back)\b.{0,30}$", re.I)


def _undo_notes(con, clock, text) -> bool:
    """ "Undo that" right after a notes change: the notes as they were."""
    if not UNDO.match(text):
        return False
    last = con.execute("select * from chat_messages where role = 'user' order by id desc limit 1").fetchone()
    changed = json.loads(last["effects"]).get("notes") if last and last["effects"] else None
    if not changed:
        return False
    mid = _say(con, clock, "user", text)
    for rid, vid in reversed(changed):
        lecture_notes.restore(con, rid, vid)
    with WRITE:  # done: undoing again does nothing, and Rewind of the earlier message has nothing left to restore
        e = json.loads(last["effects"])
        e.pop("notes")
        con.execute("update chat_messages set effects = ? where id = ?", (json.dumps(e), last["id"]))
    rec = con.execute("select r.date, c.number, c.instructor from recordings r left join courses c on c.id = r.course_id where r.id = ?",
                      (changed[-1][0],)).fetchone()
    _say(con, clock, "assistant", f"Done: the {_lecture_line(rec)} notes are back as they were. [Open them](#lecture/{changed[-1][0]}).")
    return mid is not None


def _actions(con, llm, clock, text, reply_id, message_id=None, answering=False) -> list[int] | None:
    """Suggestions from the student's message. Returns the proposals made,
    or None if the model call failed (e.g. Ollama busy with another app)."""
    try:
        acts = json.loads(llm.chat([{"role": "system", "content": ACTIONS_PROMPT + "\n\n" + _context(con, clock)},
                                    {"role": "user", "content": text}], schema=ACTIONS_SCHEMA, timeout=300))["actions"]
    except Exception:
        return None
    today = local(clock.now()).date()
    term = current_term(con, today)
    source = None
    made = []
    seen = set()
    meetings = {}  # course → the weekly class event proposed in this message
    acts.sort(key=lambda a: not (a.get("type") == "event" and a.get("days")))  # classes first: "after each class" needs them
    for a in acts:
        title = ingest.capitalize((a.get("title") or "").strip())
        # the same thing listed twice (models sometimes give it as both a task and a deadline);
        # the same title on different days is several things ("a summary of Oct 8th's lecture, of Oct 22nd's")
        key = (title.lower(), json.dumps(ingest.said_when(a.get("quote") or "") or a.get("when"), sort_keys=True))
        if not title or key in seen or not ingest.quoted(a.get("quote"), text):
            continue
        seen.add(key)
        source = source or _chat_source(con, clock, text)
        kind = a.get("type")
        if kind == "question" and answering:
            continue  # they just answered one: don't ask it back in other words
        if kind == "question":
            q = inbox.ask(con, clock, source, title, a["quote"])
            _record(con, message_id, "asked", q["id"])
            with WRITE:  # the reply just asked it: the student's next message answers it
                con.execute("update chat_messages set question_id = ? where id = ?", (q["id"], reply_id))
            continue
        if kind == "notes":
            _change_notes(con, llm, clock, a, text, message_id)
            continue
        if kind in ("change", "remove"):
            if (p := _change_or_remove(con, clock, source, a, title, text, today, term)):
                made.append(p["id"])
            continue
        if kind == "progress":
            task = _match_task(con, title)
            if not task:
                continue
            op = {"op": "update", "kind": "tasks", "id": task["id"], "data": {"status": "done" if a.get("done", True) else "open"}}
            summary = f"Mark “{task['title']}” {'done' if a.get('done', True) else 'not done'}"
        elif kind == "memory":
            op = {"op": "create", "kind": "memories", "data": {"text": title, **({"topic": a["topic"]} if a.get("topic") else {})}}
            summary = f"Remember: {title}"
        elif kind == "goal":
            op = {"op": "create", "kind": "goals",
                  "data": {"title": title, **{k: a[k] for k in ("why", "horizon") if a.get(k)}}}
            summary = title
        else:
            if not a.get("days"):  # a one-off: presenting, a report… is a deadline; a weekly class stays an event
                kind = ingest.deadline_or_event(kind, title)
            table = {"task": "tasks", "event": "events", "deadline": "deadlines", "project": "projects"}.get(kind)
            if not table:
                continue
            course = _match_course(con, a.get("course"), text)
            if table == "events" and a.get("days") and (hit := _match_item(con, title, course)) and hit[1].get("repeat"):
                # a class they already have, said again with a new time or place: a change, not a second class
                if (p := _change_or_remove(con, clock, source, {**a, "type": "change"}, hit[1]["title"], text, today, term)):
                    made.append(p["id"])
                continue
            if table == "events" and a.get("days"):
                # a weekly class: one repeating event over the term, like a syllabus's class times
                days = [d for d in a["days"].upper().replace(" ", "").split(",") if d in plan.DAYS]
                if days and _days_said(days, a["quote"]) and term:
                    c = con.execute("select number, instructor from courses where id = ?", (course,)).fetchone() if course is not None else None
                    short = f"{c['number']} · {c['instructor'].split()[-1]}" if c else title
                    m = {"days": ",".join(days), "start": a.get("start_time"), "end": a.get("end_time"), "quote": a["quote"]}
                    # one of their courses: "CS 269 class"; otherwise the name they used
                    p = ingest._propose_meetings(con, clock, source, course, short, m, term, [], {}, set(), None if c else title)
                    if p:
                        made.append(p["id"])
                        meetings[course] = p["ops"][0]["data"]
                    continue
            if table == "tasks" and a.get("each_class"):
                ops = _each_class(con, title, course, meetings.get(course), today, term)
                if ops:
                    p = inbox.propose(con, clock, source, f"{title} after each class, before the next", ops, a["quote"])
                    if "id" in p:
                        made.append(p["id"])
                    continue
            # the date as the student said it, read by code; the whole message if the
            # model quoted only part of it ("Email Prof. Kim" from "... by Friday")
            quote = a["quote"] if ingest.said_when(a["quote"]) or len(acts) > 1 else text
            when = ingest.said_when(quote) or a.get("when")
            w = ingest.resolve({"title": title, "quote": quote, "when": when}, today, term, {})
            data = {"title": title}
            if w.value:
                at = ingest.said_time(quote) or (a.get("start_time") if ingest.time_in_quote(a.get("start_time"), quote) else None)
                data[DATE_FIELD[table]] = w.value[:10] + (f"T{at}" if at and len(w.value) == 10 else w.value[10:])
            if table == "events" and len(data.get("start") or "") == 10 and course is not None:
                day = plan.DAYS[date.fromisoformat(data["start"]).weekday()]
                if (cls := next((c for c in questions._classes(con, course) if day in c["days"]), None)):
                    data["start"] += f"T{cls['start']}"
                    if cls["end"]:
                        data["end"] = data["start"][:11] + cls["end"]
            if table == "events" and "start" not in data:
                table = "tasks"  # an event without a time is something to do on no set date
            if course is not None:
                data["course_id"] = course
            if (project := _match_project(con, a.get("project"), data.get("course_id"), text)) is not None:
                data["project_id"] = project
            # already in the plan? then this adds details to it instead of a duplicate
            if p := merge.propose_or_fill(con, clock, source, table, data, a["quote"]):
                made.append(p["id"])
            continue
        p = inbox.propose(con, clock, source, summary, [op], a["quote"])
        if "id" in p:
            made.append(p["id"])
    for pid in made:
        _record(con, message_id, "made", pid)
    return made


def _reply(con, llm, clock, text, focus=None):
    """Handle one message; yields ("token", text) pieces then ("done", proposed)."""
    if _undo_notes(con, clock, text):
        yield "done", 0
        return
    cur = _current(con, clock)
    mid = _say(con, clock, "user", text)
    if cur:
        if _answer(con, llm, clock, {"id": cur["question_id"], "text": cur["text"]}, text, mid) is not False:
            yield "done", 0
            return
        # not an answer to it (none of its options): an ordinary message; the question stays open
    messages = _messages(con, llm, clock, text, focus)
    parts = []
    for piece in llm.stream(messages, temperature=0.4):
        parts.append(piece)
        yield "token", piece
    reply_id = _say(con, clock, "assistant", "".join(parts).strip())
    made = _actions(con, llm, clock, text, reply_id, mid)
    if made:  # the suggestions, right in the conversation
        _say(con, clock, "assistant", "Here's what I'd add. Check the dates are right:", proposals=made)
    if cur and (q := con.execute("select * from questions where id = ? and status = 'open'", (cur["question_id"],)).fetchone()):
        _say(con, clock, "assistant", "Back to my question: " + q["text"], q["id"], q["quote"])  # its buttons, below the reply
    yield "done", None if made is None else len(made)


# ---- HTTP --------------------------------------------------------------------

def _text(body):
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(422, "empty message")
    return text


@router.get("")
def get_chat(request: Request):
    return state(request.app.state.db, request.app.state.clock)


@router.post("")
async def post(request: Request):
    """Whole reply at once (the UI streams from /stream)."""
    s = request.app.state
    body = await request.json()
    text = _text(body)
    proposed = 0
    for kind, value in _reply(s.db, _Whole(s.llm), s.clock, text, body.get("focus")):
        proposed = value if kind == "done" else proposed
    return {**state(s.db, s.clock), "proposed": proposed}


class _Whole:
    """Adapts a model so stream() returns the reply in one piece via chat()."""
    def __init__(self, llm):
        self._llm = llm

    def stream(self, messages, **kw):
        yield self._llm.chat(messages, temperature=kw.get("temperature", 0.4), timeout=300)

    def __getattr__(self, name):
        return getattr(self._llm, name)


@router.post("/stream")
async def post_stream(request: Request):
    s = request.app.state
    body = await request.json()
    text = _text(body)

    # The reply runs on its own thread, so it finishes even if the page is
    # closed mid-reply; then a notification says it's there.
    out, listening, settled = queue.Queue(), threading.Event(), threading.Event()
    listening.set()

    def run():
        parts = []
        _stream.said = lambda role: out.put(("said", role))
        try:
            for kind, value in _reply(s.db, s.llm, s.clock, text, body.get("focus")):
                if kind == "token":
                    parts.append(value)
                out.put((kind, value))
        except Exception as e:
            out.put(("error", f"{type(e).__name__}: {e}"))
        finally:
            out.put(None)
        settled.wait(10)  # until the page has had the last piece, or is known gone
        if parts and not listening.is_set():
            said = " ".join("".join(parts).split())
            notify(s.db, s.clock, "chat", "Almanac replied", said[:140] + ("…" if len(said) > 140 else ""), "#chat")

    async def events():
        threading.Thread(target=run, daemon=True).start()
        # The server drops writes to a closed page silently, so ask each time.
        try:
            while (item := await asyncio.to_thread(out.get)) is not None:
                if await request.is_disconnected():
                    listening.clear()
                    break
                kind, value = item
                yield "data: " + json.dumps({"type": kind, "text": value} if kind in ("token", "error", "said") else
                                            {"type": kind, "proposed": value}) + "\n\n"
            else:
                if await request.is_disconnected():
                    listening.clear()
        except BaseException:
            listening.clear()
            raise
        finally:
            settled.set()

    return StreamingResponse(events(), media_type="text/event-stream")


def rewind(con, message_id) -> str | None:
    """Undo a user message and everything after it, newest first: remove the
    suggestions they made (reversing any already accepted), reopen questions
    they answered or postponed, restore dates they filled in, then delete the
    messages. Returns the message's text (to edit and resend), or None."""
    first = con.execute("select * from chat_messages where id = ? and role = 'user'", (message_id,)).fetchone()
    if not first:
        return None
    with WRITE:
        for m in con.execute("select * from chat_messages where id >= ? order by id desc", (message_id,)).fetchall():
            e = json.loads(m["effects"]) if m["effects"] else {}
            for rid, vid in reversed(e.get("notes", [])):
                lecture_notes.restore(con, rid, vid)
            for pid in reversed(e.get("made", [])):
                inbox.withdraw(con, pid)
            for pid in e.get("rejected", []):
                con.execute("update proposals set status = 'pending', decided_at = null where id = ?", (pid,))
            for qid in e.get("asked", []):
                con.execute("delete from questions where id = ?", (qid,))
            for pid, ops, summary in reversed(e.get("proposals_before", [])):
                con.execute("update proposals set ops = ?, summary = ? where id = ?", (ops, summary, pid))
            for qid, before in reversed(e.get("questions_before", [])):
                if before:
                    con.execute("update questions set status = ?, answer = ?, answered_at = ?, snoozed_until = ? where id = ?",
                                (before["status"], before["answer"], before["answered_at"], before["snoozed_until"], qid))
        con.execute("delete from chat_messages where id >= ?", (message_id,))
        con.execute("delete from chat_summaries where upto >= ?", (message_id,))
    return first["text"]


@router.post("/rewind/{message_id}")
def rewind_route(message_id: int, request: Request):
    s = request.app.state
    text = rewind(s.db, message_id)
    if text is None:
        raise HTTPException(404, "Only your own messages can be rewound.")
    return {**state(s.db, s.clock), "text": text}


@router.post("/clear")
def clear(request: Request):
    """Start the conversation afresh. Open questions stay open: the next one is asked again."""
    s = request.app.state
    with WRITE:
        s.db.execute("delete from chat_messages")
        s.db.execute("delete from chat_summaries")
    return state(s.db, s.clock)


@router.post("/skip")
def skip(request: Request):
    s = request.app.state
    cur = _current(s.db, s.clock)
    if cur:
        q = {"id": cur["question_id"], "text": s.db.execute("select text from questions where id = ?", (cur["question_id"],)).fetchone()["text"]}
        _button(s.db, s.clock, cur["question_id"], "Ask me again later")
        _snooze(s.db, s.clock, q["id"], 3 if _urgent(s.db, q) else 7)
    return state(s.db, s.clock)


def _button(con, clock, question_id, said) -> int:
    """A button pressed on a question is the student's turn in the conversation,
    said as a message of theirs, which Rewind can undo like any other."""
    mid = _say(con, clock, "user", said)
    q0 = con.execute("select status, answer, answered_at, snoozed_until from questions where id = ?", (question_id,)).fetchone()
    _record(con, mid, "questions_before", [question_id, dict(q0) if q0 else None])
    return mid


@router.post("/dismiss")
def dismiss(request: Request):
    """Not relevant: drop the question and reject what was waiting on it."""
    s = request.app.state
    cur = _current(s.db, s.clock)
    if cur:
        mid = _button(s.db, s.clock, cur["question_id"], "Not relevant to me")
        for r in s.db.execute("select id from proposals where question_id = ? and status = 'pending'", (cur["question_id"],)).fetchall():
            _record(s.db, mid, "rejected", r["id"])
        with WRITE:
            s.db.execute("update questions set status = 'dismissed' where id = ?", (cur["question_id"],))
            n = s.db.execute("update proposals set status = 'rejected', decided_at = ? where question_id = ? and status = 'pending'",
                             (local(s.clock.now()).strftime("%Y-%m-%dT%H:%M"), cur["question_id"])).rowcount
        _say(s.db, s.clock, "assistant", "Got it, I'll drop that" + (f" and the {n} item{'s' if n > 1 else ''} that depended on it." if n else "."))
    return state(s.db, s.clock)


@router.get("/badge")
def badge(request: Request):
    return {"questions": len(_eligible(request.app.state.db, request.app.state.clock))}
