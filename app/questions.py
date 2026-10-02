"""Questions: what to ask, what each question is for, and what its answer does.

Every question is stored with a purpose, and most with a target:

  date        target {"proposals": [...]}  the answer dates those items, or makes
              a weekly event ("MW 2:00pm - 3:50pm"); a link in it is the place
  instructor  target {"proposals": [...]}  the answer is the new course's instructor
  meeting     target {"course", "short", "days", "quote"}  the answer is the class time
  choice      options [{"label", "adds": [proposal ids]}]  the answer picks one;
              what only the other options add is dropped
  section     target {"code", "courses"}, options [labels]  links a Bruin Learn section
  other       target {"proposals": [...]} (optional)  read like a chat message, so
              "October 21st" to "When must you submit the one-pager?" still lands

A question can also hold suggestions up (proposals.question_id): those can't
be accepted until it's answered. The wording is in asks.py."""

import json
import re
from datetime import date, timedelta

from . import canvas, inbox, ingest, merge
from .clock import local
from .db import WRITE
from .plan import current_term

DATE_FIELD = {"deadlines": "due", "tasks": "due", "events": "start", "projects": "deadline"}

def _load(con, qid) -> dict:
    q = dict(con.execute("select * from questions where id = ?", (qid,)).fetchone())
    q["target"] = json.loads(q["target"]) if q.get("target") else {}
    q["options"] = json.loads(q["options"]) if q.get("options") else []
    return q


def option_labels(con, qid) -> list[str]:
    return [o["label"] if isinstance(o, dict) else o for o in _load(con, qid)["options"]]


# ---- answering ------------------------------------------------------------------


class Reply:
    """What answering needs from the conversation: speaking, recording effects
    (for Rewind), and reading a message for suggestions."""
    def __init__(self, say, record, read):
        self.say, self.record, self.read = say, record, read


def answer(con, llm, clock, question_id, text, reply: Reply):
    """Answer a question (not "not yet": that's handled before). Marks it
    answered, then acts on the answer according to what it was for."""
    q = _load(con, question_id)
    purpose = q.get("purpose") or "other"
    if purpose == "section":
        linked = canvas.answer_section(con, q, q["target"], text)
        if not linked:
            reply.say("I couldn't tell which one you meant. Could you name the instructor?", question_id)
            return
        _mark(con, clock, question_id, text)
        n = _held(con, question_id)
        reply.say(linked + (f" {n} suggestion{'s are' if n > 1 else ' is'} ready in Suggestions." if n else ""))
        return
    if purpose == "choice":
        picked = _pick(q["options"], text)
        if picked is None:
            reply.say("Which one? " + " / ".join(o["label"] for o in q["options"]), question_id)
            return
        _mark(con, clock, question_id, text)
        _choose(con, clock, q, picked, reply)
        return
    _mark(con, clock, question_id, text)
    held = [inbox._proposal(con, r["id"]) for r in con.execute(
        "select id from proposals where question_id = ? and status = 'pending' order by id", (question_id,))]
    targets = held + [inbox._proposal(con, pid) for pid in q["target"].get("proposals", [])
                      if pid not in {p["id"] for p in held} and _exists(con, pid)]
    for p in targets:
        if p["status"] == "pending":  # an accepted one is changed through the gate instead
            reply.record("proposals_before", [p["id"], json.dumps(p["ops"]), p["summary"]])
    filled = []
    if purpose == "instructor":
        filled += _instructor(con, clock, targets, text, reply)
    elif purpose == "meeting":
        filled += _meeting(con, clock, q, text, reply)
    else:  # date, other
        filled += _dates(con, llm, clock, q, targets, text, reply)
        if purpose == "other" and not filled:
            about = con.execute("select about from sources where id = ?", (q["source_id"],)).fetchone() if q.get("source_id") else None
            course = f" about {about['about'].split(':')[0]}" if about and about["about"] else ""
            reply.read(f"(You asked{course}: {q['text']})\n{text}")  # e.g. "October 21st": find or add the one-pager
    n = len(held)
    if n or filled:
        reply.say((f"Updated {'; '.join(filled)}." if filled else "") + (" " if filled and n else "") +
                  (f"{n} suggestion{'s' if n > 1 else ''} that {'were' if n > 1 else 'was'} waiting on this "
                   f"{'are' if n > 1 else 'is'} ready in Suggestions." if n else ""))


def _exists(con, pid) -> bool:
    return con.execute("select 1 from proposals where id = ?", (pid,)).fetchone() is not None


def _mark(con, clock, qid, text):
    with WRITE:
        con.execute("update questions set answer = ?, status = 'answered', answered_at = ? where id = ?",
                    (text, local(clock.now()).strftime("%Y-%m-%dT%H:%M"), qid))


def _held(con, qid) -> int:
    return con.execute("select count(*) from proposals where question_id = ? and status = 'pending'", (qid,)).fetchone()[0]


def _source(con, q):
    return q.get("source_id")


def _save_ops(con, p):
    with WRITE:
        con.execute("update proposals set ops = ?, summary = ? where id = ?", (json.dumps(p["ops"]), p["summary"], p["id"]))


def _fmt(value: str) -> str:
    d = date.fromisoformat(value[:10])
    return f"{d:%a %b} {d.day}" + (f", {value[11:16]}" if len(value) > 10 else "")


def _fmt_time(hhmm: str) -> str:
    h, m = int(hhmm[:2]), hhmm[3:5]
    return f"{h % 12 or 12}:{m} {'PM' if h >= 12 else 'AM'}"


def _weekly_label(wk) -> str:
    days = "/".join(d[0] + d[1].lower() for d in wk[0])
    return f"every {days}, {_fmt_time(wk[1])}" + (f"–{_fmt_time(wk[2])}" if wk[2] else "")


# ---- instructor -------------------------------------------------------------------

def _instructor(con, clock, targets, text, reply) -> list[str]:
    name = " ".join(text.strip().rstrip(".").split())
    if not (0 < len(name.split()) <= 5 and len(name) <= 60):
        return []
    out = []
    for p in targets:
        o = p["ops"][0]
        if o["op"] != "create" or o["kind"] != "courses":
            continue
        if p["status"] == "pending":
            o["data"]["instructor"] = name
            p["summary"] = f"Add course {o['data']['number']} · {name}"
            _save_ops(con, p)
        elif p["status"] == "accepted" and p.get("applied"):
            done = inbox.propose_and_accept(con, clock, p["source_id"], f"Instructor of {o['data']['number']}: {name}",
                                            [{"op": "update", "kind": "courses", "id": p["applied"][0], "data": {"instructor": name}}], text)
            if done:
                reply.record("made", done["id"])
        out.append(f"{o['data']['number']} · {name}")
    return out


# ---- meeting time --------------------------------------------------------------------

def _meeting(con, clock, q, text, reply) -> list[str]:
    t = q["target"]
    today = local(clock.now()).date()
    term = current_term(con, today)
    letters = "".join({"MO": "M", "TU": "Tu", "WE": "W", "TH": "Th", "FR": "F", "SA": "Sa", "SU": "Su"}[d] for d in t.get("days", []))
    wk = ingest.weekly(text) or ingest.weekly(f"{letters} {text}")
    if not (wk and term):
        return []
    link = re.search(r"https?://\S+", text)
    data = ingest.meeting_data(term, wk[0], wk[1], wk[2], t.get("title") or f"{t.get('short', '').split(' · ')[0]} class",
                               t.get("course"), link.group().rstrip(".,)") if link else None)
    p = merge.propose_or_fill(con, clock, _source(con, q), "events", data, text, None, f"{t.get('short', data['title'])} class meetings")
    if p:
        reply.record("made", p["id"])
    return [f"{data['title']}: {_weekly_label(wk)}"]


# ---- choice ----------------------------------------------------------------------------

def _pick(options, text):
    """The option the answer names: its exact label, or all of its words."""
    said = set(ingest._words(text))
    exact = [o for o in options if " ".join(ingest._words(o["label"])) == " ".join(ingest._words(text))]
    if exact:
        return exact[0]
    hits = [o for o in options if (w := set(ingest._words(o["label"])) - ingest.STOP) and w <= said]
    return hits[0] if len(hits) == 1 else None


def _choose(con, clock, q, picked, reply):
    """Keep the chosen option; drop what only the others would add."""
    dropped, keep = [], set(picked.get("adds", []))
    for o in q["options"]:
        if o is picked:
            continue
        for pid in (x for x in o.get("adds", []) if x not in keep):
            if not _exists(con, pid):
                continue
            p = inbox._proposal(con, pid)
            if p["status"] == "pending":
                with WRITE:
                    con.execute("update proposals set status = 'rejected', decided_at = ? where id = ?",
                                (local(clock.now()).strftime("%Y-%m-%dT%H:%M"), pid))
                reply.record("rejected", pid)
                dropped.append(p["summary"])
            elif p["status"] == "accepted" and p.get("applied"):
                ops = [{"op": "delete", "kind": op["kind"], "id": ref} for op, ref in zip(p["ops"], p["applied"])
                       if op["op"] == "create" and con.execute(f"select 1 from {op['kind']} where id = ?", (ref,)).fetchone()]
                if ops and (done := inbox.propose_and_accept(con, clock, p["source_id"], f"Remove {p['summary']}", ops)):
                    reply.record("made", done["id"])
                    dropped.append(p["summary"])
    reply.say(f"Got it: {picked['label']}." + (f" I've left out {', '.join(dropped)}." if dropped else ""))


# ---- dates -------------------------------------------------------------------------------

ANSWER_PROMPT = """The student answered a question the assistant asked. For each numbered item waiting on the answer, report the date the answer gives for it, as written. A calendar date → {"type":"date","month":M,"day":D} (with "time":"HH:MM" and type "datetime" if a time is given). A weekday → {"type":"weekday","weekday":"MO".."SU"} (add "next_week": true for "next <day>"). "tomorrow", "in 3 days" → {"type":"in_days","days":N}. If the answer gives no date for an item, {"type":"unknown"}."""

ANSWER_SCHEMA = {"type": "object", "properties": {"items": {"type": "array", "items": {"type": "object", "properties": {
    "n": {"type": "integer"}, "when": ingest.WHEN}, "required": ["n", "when"]}}}, "required": ["items"]}


def _dates(con, llm, clock, q, targets, text, reply) -> list[str]:
    """Date the targets from the answer: a weekly time makes one a weekly event;
    otherwise each gets the date the answer gives it."""
    dateable = [(p, p["ops"][0]) for p in targets
                if p["status"] in ("pending", "accepted") and p["ops"][0]["op"] == "create" and p["ops"][0]["kind"] in DATE_FIELD]
    undated = [(p, o) for p, o in dateable if p["status"] == "accepted" or not o["data"].get(DATE_FIELD[o["kind"]]) or o["data"].get("window")]
    if not undated:
        return []
    today = local(clock.now()).date()
    term = current_term(con, today)
    if len(undated) == 1 and (wk := ingest.weekly(text)) and term and undated[0][1]["kind"] in ("events", "deadlines"):
        return _make_weekly(con, clock, q, *undated[0], wk, term, text, reply)
    listing = "\n".join(f"{i}. {o['data']['title']}" for i, (_, o) in enumerate(undated))
    try:
        got = json.loads(llm.chat([{"role": "system", "content": ANSWER_PROMPT},
                                   {"role": "user", "content": f"Today is {today:%A, %B %d, %Y}.\nQuestion: {q['text']}\n"
                                                               f"Answer: {text}\n\nItems:\n{listing}"}],
                                  schema=ANSWER_SCHEMA, timeout=300))["items"]
    except Exception:
        got = []
    out = []
    for g in got:
        if not (isinstance(g.get("n"), int) and 0 <= g["n"] < len(undated)):
            continue
        p, o = undated[g["n"]]
        # the date must be in the student's own words, like any other quote
        w = ingest.resolve({"title": o["data"]["title"], "quote": text, "when": g.get("when")}, today, term, {})
        window = o["data"].get("window") or ""
        if w.value and window and (g.get("when") or {}).get("type") == "weekday" and not g["when"].get("next_week"):
            # "Wednesday" to "which day in Week 5": that week's Wednesday, not this one
            monday = date.fromisoformat(window[:10])
            w = ingest.When((monday + timedelta(days=date.fromisoformat(w.value[:10]).weekday())).isoformat())
        if not w.value:
            continue
        field = DATE_FIELD[o["kind"]]
        if p["status"] == "accepted" and p.get("applied"):
            done = inbox.propose_and_accept(con, clock, p["source_id"], f"Date “{o['data']['title']}”: {_fmt(w.value)}",
                                            [{"op": "update", "kind": o["kind"], "id": p["applied"][0],
                                              "data": {field: w.value, "window": None, "provisional": False}}], text)
            if done:
                reply.record("made", done["id"])
        else:
            o["data"][field] = w.value
            o["data"].pop("window", None)  # the day is known now: no longer just "sometime in Week 9"
            o["data"].pop("provisional", None)
            _save_ops(con, p)
        out.append(f"{o['data']['title']}: {_fmt(w.value)}")
    return out


def _make_weekly(con, clock, q, p, o, wk, term, text, reply) -> list[str]:
    """"When is Lecture?" → "MW 2:00pm - 3:50pm": a weekly event; a link in the answer is where."""
    link = re.search(r"https?://\S+", text)
    data = ingest.meeting_data(term, wk[0], wk[1], wk[2], o["data"]["title"], o["data"].get("course_id"),
                               link.group().rstrip(".,)") if link else None)
    if p["status"] == "pending":
        p["ops"] = [{"op": "create", "kind": "events", "data": data}]
        _save_ops(con, p)
    elif p.get("applied"):
        ops = [{"op": "delete", "kind": o["kind"], "id": p["applied"][0]}, {"op": "create", "kind": "events", "data": data}] \
            if o["kind"] != "events" else [{"op": "update", "kind": "events", "id": p["applied"][0],
                                            "data": {k: data.get(k) for k in ("start", "end", "repeat", "until", "skip", "location", "window")}}]
        if (done := inbox.propose_and_accept(con, clock, p["source_id"], f"Make “{o['data']['title']}” weekly", ops, text)):
            reply.record("made", done["id"])
    return [f"{o['data']['title']}: {_weekly_label(wk)}"]
