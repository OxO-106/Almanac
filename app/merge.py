"""Fill in, don't duplicate.

When a syllabus, Bruin Learn or chat brings an item the plan already has
(same day, overlapping title, no conflicting course), what's new about it is
proposed as an update: its course, project, exact time, week or location.
If the match is still a pending proposal, the details merge into it."""

import json

from . import ingest

DATE_FIELD = {"deadlines": "due", "events": "start", "tasks": "due", "projects": "deadline"}
FILLABLE = {"course_id": "course", "project_id": "project", "window": "week", "location": "location", "end": "end time"}


def _words(title):
    return set(ingest._words(title)) - ingest.STOP


def _same(a_title, b_title) -> bool:
    a, b = _words(a_title), _words(b_title)
    return bool(a and b) and len(a & b) / min(len(a), len(b)) >= 0.5


def _compatible(a, b) -> bool:
    """Courses don't conflict (a pending course reference can't be compared)."""
    return not (isinstance(a, int) and isinstance(b, int) and a != b)


def find(con, kind, data):
    """(table, row) of a plan item that is this one, or (None, None)."""
    # same kind only: a deadline and a session on its day are different things
    table = kind if kind in ("deadlines", "events", "tasks") else None
    if not table:
        return None, None
    f = DATE_FIELD[table]
    day = (data.get(f) or "")[:10]
    rows = con.execute(f"select * from {table} where substr({f}, 1, 10) = ?", (day,)) if day else \
        con.execute(f"select * from {table}")  # no date given ("the team list is for Ding's course")
    hits = [dict(r) for r in rows if _same(r["title"], data["title"]) and _compatible(r["course_id"], data.get("course_id"))]
    # with a date, the first match; without one, only an unambiguous match
    return (table, hits[0]) if hits and (day or len(hits) == 1) else (None, None)


def find_pending(con, kind, data):
    """A pending proposal creating this same item, or None."""
    day = (data.get(DATE_FIELD.get(kind, "due")) or "")[:10]
    if not day:
        return None
    for r in con.execute("select id, ops from proposals where status = 'pending' order by id"):
        ops = json.loads(r["ops"])
        o = ops[0]
        if len(ops) != 1 or o["op"] != "create" or o["kind"] != kind:
            continue
        if (o["data"].get(DATE_FIELD[o["kind"]]) or "")[:10] == day and _same(o["data"].get("title", ""), data["title"]) \
                and _compatible(o["data"].get("course_id"), data.get("course_id")):
            return {"id": r["id"], "ops": ops}
    return None


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
