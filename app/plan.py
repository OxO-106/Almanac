"""Goals, Projects, Tasks, Events, Deadlines and Courses: CRUD and Today."""

import json
from datetime import date, datetime, timedelta

from fastapi import APIRouter, HTTPException, Request, Response

from . import db
from .clock import local
from .db import WRITE

DAYS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]


def _date(v):
    date.fromisoformat(v)
    return v


def _date_or_time(v):
    (datetime if "T" in v else date).fromisoformat(v)
    return v[:16]


def _one_of(*values):
    def check(v):
        if v not in values:
            raise ValueError
        return v
    return check


def _days(v):
    if not all(d in DAYS for d in v.split(",")):
        raise ValueError
    return v


def _dates(v):
    """Comma-separated dates."""
    return ",".join(_date(d.strip()) for d in v.split(",") if d.strip()) or None


def _window(v):
    a, b = v.split("/")
    return f"{_date(a)}/{_date(b)}"


def _holidays(v):
    """One "YYYY-MM-DD name" per line."""
    lines = [l.strip() for l in v.splitlines() if l.strip()]
    for l in lines:
        _date(l[:10])
    return "\n".join(lines)


# kind -> {field: validator}; `required` fields must be present on create.
KINDS = {
    "courses": ({"number": str, "instructor": str, "title": str, "color": str}, {"number", "instructor"}),
    "goals": ({"title": str, "why": str, "horizon": str, "status": str}, {"title"}),
    "projects": ({"title": str, "goal_id": int, "course_id": int, "deadline": _date_or_time, "team": bool,
                  "status": str, "notes": str}, {"title"}),
    "tasks": ({"title": str, "project_id": int, "course_id": int, "due": _date_or_time, "do_date": _date,
               "work_kind": str, "size": float, "estimate_min": int, "status": _one_of("open", "done"), "notes": str,
               "provisional": bool, "window": _window}, {"title"}),
    "events": ({"title": str, "course_id": int, "start": _date_or_time, "end": _date_or_time, "repeat": _days,
                "until": _date, "skip": _dates, "location": str, "provisional": bool, "window": _window}, {"title", "start"}),
    "deadlines": ({"title": str, "course_id": int, "project_id": int, "due": _date_or_time,
                   "provisional": bool, "window": _window}, {"title"}),
    "memories": ({"text": str, "topic": str}, {"text"}),
    "terms": ({"name": str, "starts": _date, "instruction_begins": _date, "week1": _date, "instruction_ends": _date,
               "finals_start": _date, "ends": _date, "holidays": _holidays},
              {"name", "starts", "instruction_begins", "week1", "instruction_ends", "ends"}),
}


def current_term(con, day: date) -> dict | None:
    """The term containing `day`, else the next one to start."""
    rows = [dict(r) for r in con.execute("select * from terms order by starts")]
    return next((t for t in rows if t["starts"] <= day.isoformat() <= t["ends"]), None) or \
        next((t for t in rows if t["starts"] > day.isoformat()), None)

router = APIRouter(prefix="/api")


def _clean(kind, body: dict, creating: bool) -> dict:
    fields, required = KINDS[kind]
    unknown = set(body) - set(fields)
    missing = required - {k for k, v in body.items() if v not in (None, "")} if creating else set()
    if unknown or missing:
        raise HTTPException(422, f"unknown fields {sorted(unknown)}" if unknown else f"missing {sorted(missing)}")
    out = {}
    for k, v in body.items():
        try:
            out[k] = None if v is None else fields[k](v)
        except (ValueError, TypeError):
            raise HTTPException(422, f"invalid {k}: {v!r}")
    return out


def _kind(kind):
    if kind not in KINDS:
        raise HTTPException(404)
    return kind


def _row(con, kind, id):
    r = con.execute(f"select * from {kind} where id = ?", (id,)).fetchone()
    if not r:
        raise HTTPException(404)
    return dict(r)


def _now(request) -> str:
    return local(request.app.state.clock.now()).strftime("%Y-%m-%dT%H:%M")


@router.get("/today")
def today(request: Request):
    con = request.app.state.db
    day = _now(request)[:10]
    q = lambda sql, *a: [dict(r) for r in con.execute(sql, a)]
    return {
        "date": day,
        "tasks": q("select * from tasks where status = 'open' and do_date = ? order by id", day),
        "overdue": q("select * from tasks where status = 'open' and do_date < ? order by do_date, id", day),
        "done": q("select * from tasks where status = 'done' and substr(done_at, 1, 10) = ? order by done_at", day),
        "events": occurrences(q("select * from events"), day, day),
        "deadlines": q("select * from deadlines where substr(due, 1, 10) = ? order by due", day),
    }


CAPACITY = {"weekday": 6, "weekend": 10}  # soft hours of planned work per day


def capacity(con) -> dict:
    return {**CAPACITY, **db.settings(con).get("capacity", {})}


@router.get("/capacity")
def get_capacity(request: Request):
    return capacity(request.app.state.db)


@router.put("/capacity")
async def put_capacity(request: Request):
    body = await request.json()
    try:
        cap = {k: float(body[k]) for k in CAPACITY}
    except (KeyError, TypeError, ValueError):
        raise HTTPException(422, "weekday and weekend hours are required")
    if not all(0 <= v <= 16 for v in cap.values()):
        raise HTTPException(422, "hours must be between 0 and 16")
    cap = {k: int(v) if v == int(v) else v for k, v in cap.items()}
    with WRITE:
        request.app.state.db.execute("insert into settings (key, value) values ('capacity', ?) "
                                     "on conflict(key) do update set value = excluded.value", (json.dumps(cap),))
    return cap


@router.get("/calendar")
def calendar(start: str, end: str, request: Request):
    con = request.app.state.db
    _date(start), _date(end)
    q = lambda sql: [dict(r) for r in con.execute(sql, (start, end))]
    return {
        "tasks": q("select * from tasks where do_date between ? and ? order by do_date, id"),
        "unscheduled": q("select * from tasks where do_date is null and substr(due, 1, 10) between ? and ? order by due"),
        "events": occurrences([dict(r) for r in con.execute("select * from events")], start, end),
        "deadlines": q("select * from deadlines where substr(due, 1, 10) between ? and ? order by due"),
    }


# Distinct, readable on light and dark backgrounds; assigned in order so two
# Courses (even with the same number) never share one until the list runs out.
COLORS = ["#3b82f6", "#e8590c", "#2f9e44", "#ae3ec9", "#d6336c", "#0c8599", "#e67700", "#5c7cfa"]


def _next_color(con):
    used = [r[0] for r in con.execute("select color from courses")]
    return min(COLORS, key=lambda c: (used.count(c), COLORS.index(c)))


def occurrences(events: list[dict], first: str, last: str) -> list[dict]:
    """Every occurrence of the events between two dates (inclusive), sorted by start."""
    lo, hi = date.fromisoformat(first), date.fromisoformat(last)
    out = []
    for e in events:
        start = e["start"]
        d0 = date.fromisoformat(start[:10])
        if not e["repeat"]:
            if lo <= d0 <= hi:
                out.append(e)
            continue
        days = {DAYS.index(d) for d in e["repeat"].split(",")}
        skip = set((e.get("skip") or "").split(","))
        end = min(hi, date.fromisoformat(e["until"])) if e["until"] else hi
        d = max(lo, d0)
        while d <= end:
            if d.weekday() in days and d.isoformat() not in skip:
                shift = lambda t: t and d.isoformat() + t[10:]
                out.append({**e, "start": shift(start), "end": shift(e["end"])})
            d += timedelta(days=1)
    return sorted(out, key=lambda e: e["start"])


@router.get("/{kind}")
def list_(kind: str, request: Request):
    _kind(kind)
    fields = KINDS[kind][0]
    filters = {k: v for k, v in request.query_params.items() if k in fields}
    where = " and ".join(f"{k} = ?" for k in filters) or "1"
    rows = request.app.state.db.execute(f"select * from {kind} where {where} order by id", tuple(filters.values()))
    return [dict(r) for r in rows]


# insert/change/remove are shared by the HTTP routes and accepted Proposals.

def insert(con, kind: str, body: dict) -> dict:
    data = _clean(_kind(kind), body, creating=True)
    with WRITE:
        if kind == "courses" and not data.get("color"):
            data["color"] = _next_color(con)
        cur = con.execute(f"insert into {kind} ({', '.join(data)}) values ({', '.join('?' * len(data))})",
                          tuple(data.values()))
        return _row(con, kind, cur.lastrowid)


def change(con, kind: str, id: int, body: dict, now: str) -> dict:
    data = _clean(_kind(kind), body, creating=False)
    with WRITE:
        _row(con, kind, id)
        if kind == "tasks" and "status" in data:
            data["done_at"] = now if data["status"] == "done" else None
        if data:
            con.execute(f"update {kind} set {', '.join(f'{k} = ?' for k in data)} where id = ?", (*data.values(), id))
        return _row(con, kind, id)


def remove(con, kind: str, id: int):
    with WRITE:
        _row(con, _kind(kind), id)
        con.execute(f"delete from {kind} where id = ?", (id,))


@router.post("/{kind}", status_code=201)
async def create(kind: str, request: Request):
    return insert(request.app.state.db, kind, await request.json())


@router.get("/{kind}/{id}")
def get(kind: str, id: int, request: Request):
    row = _row(request.app.state.db, _kind(kind), id)
    if kind == "tasks":
        from .timers import spent  # timers builds on plan
        row["spent_min"] = spent(request.app.state.db, id)
    return row


@router.patch("/{kind}/{id}")
async def update(kind: str, id: int, request: Request):
    s = request.app.state
    body = await request.json()
    row = change(s.db, kind, id, body, _now(request))
    if kind == "tasks" and body.get("status") == "done":
        from .timers import after_done
        after_done(s.db, s.clock, row)
    return row


@router.delete("/{kind}/{id}", status_code=204)
def delete(kind: str, id: int, request: Request):
    remove(request.app.state.db, kind, id)
    return Response(status_code=204)
