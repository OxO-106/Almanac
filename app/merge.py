"""Fill in, don't duplicate.

When a syllabus, Bruin Learn or chat brings an item the plan already has
(same day, overlapping title, no conflicting course), what's new about it is
proposed as an update: its course, project, exact time, week or location.
If the match is still a pending proposal, the details merge into it."""

import json
import re

from . import ingest

DATE_FIELD = {"deadlines": "due", "events": "start", "tasks": "due", "projects": "deadline"}
FILLABLE = {"course_id": "course", "project_id": "project", "window": "week", "location": "location", "end": "end time"}


def _words(title):
    return set(ingest._words(title)) - ingest.STOP


READING = re.compile(r"\s*(read|review|skim)\b", re.I)
READING_WORDS = {"read", "review", "skim", "paper", "chapter"}


def _same(a_title, b_title) -> bool:
    a, b = _words(a_title), _words(b_title)
    need = 0.5
    if READING.match(a_title) and READING.match(b_title):
        # two papers for one class share words ("Language Models"): the shorter
        # title must be nearly all in the longer ("Read the ReAct paper")
        # ("Read P5. SWE-agent": the list's number isn't in the other title)
        a, b = ({w for w in x - READING_WORDS if not re.fullmatch(r"p\d+", w)} for x in (a, b))
        need = 0.8
    return bool(a and b) and len(a & b) / min(len(a), len(b)) >= need


def _compatible(a, b) -> bool:
    """Courses don't conflict (a pending course reference can't be compared)."""
    return not (isinstance(a, int) and isinstance(b, int) and a != b)


# ---- the one duplicate rule -------------------------------------------------------
# Used by every reader (syllabus, chat, Bruin Learn) and by the duplicate check:
# the same course, a matching date or week, titles sharing half their words,
# and the same kind, except that a session and its deadline on the same day are
# one thing when either says it's due ("Mid-Project Check-in: Phase 1 Due" and
# "Submit Phase 1 deliverables").

DUEISH = re.compile(r"\b(due|submit\w*|deliverables?|hand[- ]in)\b", re.I)


def _days(kind, data) -> tuple[str, str] | None:
    """(first, last) day an item is on: its date, or its week."""
    if data.get("window"):
        a, b = data["window"].split("/")
        return a, b
    d = (data.get(DATE_FIELD.get(kind, "due")) or "")[:10]
    return (d, d) if d else None


def same(kind_a, a, kind_b, b) -> bool:
    """Are these two items (plan rows, proposal data, or items being read) one thing?"""
    if not (_compatible(a.get("course_id"), b.get("course_id")) and _same(a.get("title", ""), b.get("title", ""))):
        return False
    da, db_ = _days(kind_a, a), _days(kind_b, b)
    if not (da and db_ and da[0] <= db_[1] and db_[0] <= da[1]):
        return False
    if a.get("repeat") or b.get("repeat"):
        return False  # a weekly class isn't a one-off on one of its days
    if kind_a == kind_b:
        return True
    return {kind_a, kind_b} == {"events", "deadlines"} and bool(DUEISH.search(a.get("title", "") + " " + b.get("title", "")))


def _kinds(kind):
    return ("events", "deadlines") if kind in ("events", "deadlines") else (kind,)


def find(con, kind, data):
    """(table, row) of a plan item that is this one, or (None, None)."""
    if kind not in ("deadlines", "events", "tasks"):
        return None, None
    if not _days(kind, data):  # no date given ("the team list is for Ding's course"): only an unambiguous match
        hits = [(kind, dict(r)) for r in con.execute(f"select * from {kind}")
                if _same(r["title"], data["title"]) and _compatible(r["course_id"], data.get("course_id"))]
        return hits[0] if len(hits) == 1 else (None, None)
    for table in _kinds(kind):
        for r in con.execute(f"select * from {table}"):
            if same(table, dict(r), kind, data):
                return table, dict(r)
    return None, None


def find_pending(con, kind, data):
    """A pending proposal creating this same item, or None."""
    if not _days(kind, data):
        return None
    for r in con.execute("select id, ops from proposals where status = 'pending' order by id"):
        ops = json.loads(r["ops"])
        o = ops[0]
        if len(ops) != 1 or o["op"] != "create" or o["kind"] not in _kinds(kind):
            continue
        if same(o["kind"], o["data"], kind, data):
            return {"id": r["id"], "ops": ops}
    return None


def duplicates(con) -> list[tuple]:
    """Pairs already in the plan that the rule says are one thing:
    (keep (kind, row), drop (kind, row)). Keeps the one with more detail:
    a session over its deadline, a time over a date, a course over none."""
    rows = [(k, dict(r)) for k in ("events", "deadlines", "tasks") for r in con.execute(f"select * from {k}")]
    detail = lambda kr: (kr[0] == "events", len(kr[1].get(DATE_FIELD[kr[0]]) or "") > 10, kr[1].get("course_id") is not None,
                         not kr[1].get("window"), -kr[1]["id"])
    out, gone = [], set()
    for i, a in enumerate(rows):
        for b in rows[i + 1:]:
            if (a[0], a[1]["id"]) in gone or (b[0], b[1]["id"]) in gone or not same(a[0], a[1], b[0], b[1]):
                continue
            keep, drop = sorted([a, b], key=detail, reverse=True)
            gone.add((drop[0], drop[1]["id"]))
            out.append((keep, drop))
    return out


def offer_duplicates(con, clock) -> int:
    """Suggest removing the second copy of each duplicate already in the plan."""
    from . import inbox
    n = 0
    for (kk, keep), (dk, drop) in duplicates(con):
        p = inbox.propose(con, clock, None, f"Same thing twice: keep “{keep['title']}”, remove “{drop['title']}”",
                          [{"op": "delete", "kind": dk, "id": drop["id"]}])
        n += "id" in p
    return n


def details(table, row, data) -> dict:
    """What `data` adds to `row`: only fields the row lacks (and a time for a date-only date)."""
    out = {f: data[f] for f in FILLABLE if data.get(f) not in (None, "") and not row.get(f) and f in _columns(table)}
    f = DATE_FIELD[table]
    mine = row.get(f) or ""
    theirs = next((data[k] for k in ("due", "start", "deadline") if data.get(k)), "")
    if len(mine) == 10 and len(theirs) > 10 and theirs[:10] == mine:
        out[f] = theirs
    return out


def _columns(table):
    from .plan import KINDS
    return KINDS[table][0]


def summary(row, fill) -> str:
    names = []
    for f in fill:
        n = FILLABLE.get(f, "time")
        if n not in names:
            names.append(n)
    return f"Add details to “{row['title']}”: {', '.join(names)}"


def project_for(con, course_id, title):
    """The course's project this item is part of, when the item names it
    ("Course Project Team List" → "Course project")."""
    if not isinstance(course_id, int):
        return None
    have = set(ingest._words(title)) - ingest.STOP
    hits = [r["id"] for r in con.execute("select id, title from projects where course_id = ?", (course_id,))
            if (w := set(ingest._words(r["title"])) - ingest.STOP) and w <= have]
    return hits[0] if len(hits) == 1 else None


def merge_into_pending(con, pending, data) -> bool:
    """Add what's missing to a waiting proposal. True if anything changed."""
    from .db import WRITE
    o = pending["ops"][0]
    fill = details(o["kind"], o["data"], data)
    if not fill:
        return False
    o["data"].update(fill)
    with WRITE:
        con.execute("update proposals set ops = ? where id = ?", (json.dumps(pending["ops"]), pending["id"]))
    return True


def propose_or_fill(con, clock, source_id, kind, data, quote=None, question_id=None, summary_text=None):
    """Create `data` as a proposal, unless the plan (or the Inbox) already has
    it: then propose (or merge) only the missing details. Returns the new
    proposal, or None if nothing new was proposed."""
    from . import inbox
    if "project_id" not in data and (pid := project_for(con, data.get("course_id"), data["title"])):
        data = {**data, "project_id": pid}
    table, row = find(con, kind, data)
    if row:
        fill = details(table, row, data)
        if not fill:
            return None
        p = inbox.propose(con, clock, source_id, summary(row, fill),
                          [{"op": "update", "kind": table, "id": row["id"], "data": fill}], quote, question_id)
        return p if "id" in p else None
    pending = find_pending(con, kind, data)
    if pending:
        merge_into_pending(con, pending, data)
        return None
    p = inbox.propose(con, clock, source_id, summary_text or data["title"],
                      [{"op": "create", "kind": kind, "data": data}], quote, question_id)
    return p if "id" in p else None
