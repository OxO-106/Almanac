"""Weekly, monthly and quarterly Overviews, kept in the Archive.

Weekly on Sunday at 8pm, monthly on the last day at 8:30pm, quarterly on the
last day of a term at 9pm; never merged. Everything counted is computed here;
the model only writes a one-sentence assessment from those numbers."""

import json
from calendar import monthrange
from datetime import date, datetime, timedelta

from fastapi import APIRouter, HTTPException, Request

from . import plan
from .clock import local
from .db import WRITE
from .scheduler import JOBS, WATCHERS, Job, notify

router = APIRouter(prefix="/api")

ASSESS_PROMPT = ("Write ONE honest, kind sentence (under 25 words) assessing the student's {period} from these numbers. "
                 "Mention what went well and what slipped, if anything. Use only the facts given.")


def _fmt(d: date) -> str:
    return f"{d:%b} {d.day}"


def build(con, llm, kind: str, start: date, end: date, now: datetime) -> dict:
    s, e = start.isoformat(), end.isoformat()
    q = lambda sql, *a: [dict(r) for r in con.execute(sql, a)]
    goal_of = "coalesce((select g.title from projects p join goals g on g.id = p.goal_id where p.id = t.project_id), " \
              "(select p.title from projects p where p.id = t.project_id), 'Other')"
    hours = q(f"select {goal_of} as name, round(sum(x.minutes) / 60.0, 1) as hours from sessions x join tasks t on t.id = x.task_id "
              f"where x.ended_at is not null and substr(x.started_at, 1, 10) between ? and ? group by name having hours > 0 order by hours desc", s, e)
    completed = q(f"select t.id, t.title, {goal_of} as goal from tasks t where t.status = 'done' "
                  f"and substr(t.done_at, 1, 10) between ? and ? order by t.done_at", s, e)
    # slipped: its day has passed and it wasn't done by then
    slipped = q("select id, title, do_date from tasks where do_date between ? and ? and do_date < ? and "
                "(status = 'open' or substr(done_at, 1, 10) > do_date) order by do_date", s, e, now.date().isoformat())
    moved = {r["goal"] for r in completed} | {h["name"] for h in hours}
    goals = q("select id, title from goals where status = 'active' order by id")
    data = {"kind": kind, "period_start": s, "period_end": e, "hours": hours,
            "completed": [{"title": r["title"], "goal": r["goal"]} for r in completed],
            "slipped": [{"title": r["title"], "do_date": r["do_date"]} for r in slipped],
            "stalled_goals": [g["title"] for g in goals if g["title"] not in moved]}
    if kind == "weekly":
        ns, ne = (end + timedelta(days=1)).isoformat(), (end + timedelta(days=7)).isoformat()
        data["next"] = q("select title, do_date as at from tasks where status = 'open' and do_date between ? and ? "
                         "union all select title, due from deadlines where substr(due, 1, 10) between ? and ? order by at",
                         ns, ne, ns, ne)
    if kind == "monthly":
        data["goals"] = [{"goal": g["title"], **dict(con.execute(
            "select coalesce(sum(t.status = 'done'), 0) as done, count(t.id) as total from projects p "
            "left join tasks t on t.project_id = p.id where p.goal_id = ?", (g["id"],)).fetchone())} for g in goals]
    if kind == "quarterly":
        by = {}
        for r in completed:
            by.setdefault(r["goal"], []).append(r["title"])
        data["record"] = [{"goal": g, "done": titles} for g, titles in by.items()]

    period = {"weekly": "week", "monthly": "month", "quarterly": "quarter"}[kind]
    facts = (f"Hours: {', '.join(f'{h['name']} {h['hours']:g}h' for h in hours) or 'none timed'}. "
             f"Done ({len(completed)}): {', '.join(r['title'] for r in completed) or 'nothing'}. "
             f"Slipped ({len(slipped)}): {', '.join(r['title'] for r in slipped) or 'nothing'}. "
             f"Goals with no movement: {', '.join(data['stalled_goals']) or 'none'}.")
    try:
        data["assessment"] = llm.chat([{"role": "system", "content": ASSESS_PROMPT.format(period=period)},
                                       {"role": "user", "content": facts}], temperature=0.3, timeout=600).strip()
    except Exception:
        data["assessment"] = f"{len(completed)} done, {len(slipped)} slipped."
    with WRITE:
        cur = con.execute("insert into overviews (kind, period_start, period_end, data, created_at) values (?,?,?,?,?) "
                          "on conflict(kind, period_start) do update set data = excluded.data, period_end = excluded.period_end "
                          "returning id", (kind, s, e, json.dumps(data), now.isoformat(timespec="minutes")))
        data["id"] = cur.fetchone()[0]
    return data


TITLES = {"weekly": "Your week in review", "monthly": "Your month in review", "quarterly": "Your quarter in review"}


def _job(kind):
    def run(state, scheduled, late, missed):
        day = scheduled.date()
        if kind == "weekly":
            start, end = day - timedelta(days=6), day
        elif kind == "monthly":
            start, end = day.replace(day=1), day
        else:
            term = next((dict(t) for t in state.db.execute("select * from terms where ends = ?", (day.isoformat(),))), None)
            if not term:
                return
            start, end = date.fromisoformat(term["starts"]), day
        o = build(state.db, state.llm, kind, start, end, local(state.clock.now()).replace(tzinfo=None))
        span = f"{_fmt(start)} – {_fmt(end)}"
        if late:
            with WRITE:
                state.db.execute("insert into catchup (text) values (?)", (f"Your {kind} overview for {span} is in the Archive.",))
        else:
            notify(state.db, state.clock, "overview", f"{TITLES[kind]} ({span})", o["assessment"], f"#archive/{o['id']}")
    return run


_TERM_ENDS: set[str] = set()


def _weekly(d):
    return [datetime(d.year, d.month, d.day, 20)] if d.weekday() == 6 else []


def _monthly(d):
    return [datetime(d.year, d.month, d.day, 20, 30)] if d.day == monthrange(d.year, d.month)[1] else []


def _quarterly(d):
    return [datetime(d.year, d.month, d.day, 21)] if d.isoformat() in _TERM_ENDS else []


def refresh_term_ends(con):
    """The quarterly job's days come from the (editable) term calendar."""
    _TERM_ENDS.clear()
    _TERM_ENDS.update(r["ends"] for r in con.execute("select ends from terms"))


WATCHERS.append(lambda state: refresh_term_ends(state.db))
JOBS.append(Job("weekly", _weekly, _job("weekly")))
JOBS.append(Job("monthly", _monthly, _job("monthly")))
JOBS.append(Job("quarterly", _quarterly, _job("quarterly")))


@router.get("/overviews")
def list_overviews(request: Request):
    return [dict(r) for r in request.app.state.db.execute(
        "select id, kind, period_start, period_end, created_at from overviews order by period_end desc, kind")]


@router.get("/overviews/{id}")
def get_overview(id: int, request: Request):
    r = request.app.state.db.execute("select * from overviews where id = ?", (id,)).fetchone()
    if not r:
        raise HTTPException(404)
    return {**json.loads(r["data"]), "id": r["id"]}
