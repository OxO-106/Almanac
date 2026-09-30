"""Timed work Sessions and the estimates learned from them.

One timer runs at a time. After CHECK_AFTER the student is asked whether
they're still working; with no answer within ANSWER_WITHIN the session is
capped at CHECK_AFTER. Once MIN_TASKS finished tasks of a Work kind have been
timed, that kind's median minutes per unit replaces the model's guesses."""

import statistics
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Request

from . import inbox, plan
from .clock import local
from .db import WRITE, settings
from .scheduler import WATCHERS, notify

router = APIRouter(prefix="/api")
CHECK_AFTER = timedelta(hours=2)
ANSWER_WITHIN = timedelta(minutes=15)
MIN_TASKS = 3
UNITS = {"paper": ("page", "Reading a paper"), "reading": ("page", "Reading"), "slides": ("slide", "Making slides"),
         "writing": ("page", "Writing")}


def _utc(clock) -> datetime:
    return clock.now().replace(microsecond=0)


def _running(con):
    r = con.execute("select * from sessions where ended_at is null").fetchone()
    return dict(r) if r else None


def _end(con, s, end: datetime):
    minutes = max(0, round((end - datetime.fromisoformat(s["started_at"])).total_seconds() / 60))
    with WRITE:
        con.execute("update sessions set ended_at = ?, minutes = ? where id = ?", (end.isoformat(), minutes, s["id"]))
    return minutes


def spent(con, task_id) -> int:
    return con.execute("select coalesce(sum(minutes), 0) from sessions where task_id = ? and ended_at is not null",
                       (task_id,)).fetchone()[0]


def rates(con) -> dict:
    """Work kind → finished timed tasks and median minutes per unit (once there are MIN_TASKS)."""
    out = {}
    for kind, (unit, _) in UNITS.items():
        per = [r["m"] / r["size"] for r in con.execute(
            "select t.size, (select sum(minutes) from sessions s where s.task_id = t.id and s.ended_at is not null) as m "
            "from tasks t where t.status = 'done' and t.work_kind = ? and t.size > 0", (kind,)) if r["m"]]
        med = statistics.median(per) if len(per) >= MIN_TASKS else None
        out[kind] = {"unit": unit, "tasks": len(per), "minutes_per_unit": (round(med, 1) if med % 1 else int(med)) if med else None}
    return out


def after_done(con, clock, task):
    """A task was finished: if that completes a kind's MIN_TASKS-th timed task
    (or the 10th), propose remembering the pace."""
    unit, label = UNITS.get(task.get("work_kind"), (None, None))
    if not unit:
        return
    r = rates(con)[task["work_kind"]]
    if r["minutes_per_unit"] is None or r["tasks"] not in (MIN_TASKS, 10):
        return
    mpu = r["minutes_per_unit"]
    inbox.propose(con, clock, None, f"Remember your pace: {label.lower()}",
                  [{"op": "create", "kind": "memories", "data": {
                      "text": f"{label} takes you about {mpu:g} minutes a {unit} (from {r['tasks']} timed tasks).",
                      "topic": "pace"}}])


def watch(state):
    """Every tick: ask about a long-running timer; cap it if nobody answers."""
    con, clock = state.db, state.clock
    s = _running(con)
    if not s:
        return
    now = _utc(clock)
    since = datetime.fromisoformat(s["confirmed_at"] or s["started_at"])
    if s["asked_at"]:
        if now - datetime.fromisoformat(s["asked_at"]) >= ANSWER_WITHIN:
            _end(con, s, since + CHECK_AFTER)  # count only up to when we asked
    elif now - since >= CHECK_AFTER:
        title = con.execute("select title from tasks where id = ?", (s["task_id"],)).fetchone()["title"]
        with WRITE:
            con.execute("update sessions set asked_at = ? where id = ?", (now.isoformat(), s["id"]))
        notify(con, clock, "timer", f"Still working on “{title}”?",
               "The timer has run for 2 hours. Keep going, or I'll stop it in 15 minutes.", "#today")


# ---- HTTP ---------------------------------------------------------------------

@router.post("/tasks/{id}/timer/start")
def start(id: int, request: Request):
    s = request.app.state
    plan._row(s.db, "tasks", id)
    now = _utc(s.clock)
    if running := _running(s.db):
        _end(s.db, running, now)
    with WRITE:
        s.db.execute("insert into sessions (task_id, started_at) values (?, ?)", (id, now.isoformat()))
    return get_timer(request)


@router.post("/timer/stop")
def stop(request: Request):
    s = request.app.state
    running = _running(s.db)
    if not running:
        raise HTTPException(409, "No timer is running.")
    minutes = _end(s.db, running, _utc(s.clock))
    return {"task_id": running["task_id"], "minutes": minutes, "spent_min": spent(s.db, running["task_id"])}


@router.post("/timer/keep")
def keep(request: Request):
    s = request.app.state
    running = _running(s.db)
    if running:
        with WRITE:
            s.db.execute("update sessions set confirmed_at = ?, asked_at = null where id = ?",
                         (_utc(s.clock).isoformat(), running["id"]))
    return get_timer(request)


@router.get("/timer")
def get_timer(request: Request):
    s = request.app.state
    running = _running(s.db)
    if not running:
        return None
    task = plan._row(s.db, "tasks", running["task_id"])
    elapsed = round((_utc(s.clock) - datetime.fromisoformat(running["started_at"])).total_seconds() / 60)
    return {"task": task, "started_at": running["started_at"], "elapsed_min": elapsed, "asking": bool(running["asked_at"])}


@router.get("/estimates")
def get_estimates(request: Request):
    return rates(request.app.state.db)


WATCHERS.append(watch)
