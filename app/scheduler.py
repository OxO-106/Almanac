"""Scheduled jobs, notifications and the morning Briefing.

Each job runs at fixed local times. A tick (every 30 s in the app; on demand
in tests) runs each job whose latest scheduled time since its last run has
passed, once, however many were missed while the PC was off. A run more than
GRACE late sends no notification (no burst of stale alerts on start-up); jobs
that care can record what was missed for the next Briefing."""

import json
import threading
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable

from fastapi import APIRouter, Request

from . import plan
from .clock import local
from .db import WRITE

router = APIRouter(prefix="/api")
GRACE = timedelta(minutes=90)
TICK_SECONDS = 30


@dataclass
class Job:
    name: str
    times: Callable[[date], list[datetime]]  # local wall-clock times the job runs on a day
    run: Callable  # run(app_state, scheduled, late, missed): the latest due time, whether it's past GRACE, earlier missed times


JOBS: list[Job] = []
WATCHERS: list[Callable] = []  # run on every tick: watcher(app_state)


def daily(hh: int, mm: int = 0):
    return lambda d: [datetime(d.year, d.month, d.day, hh, mm)]


def _now(state) -> datetime:
    return local(state.clock.now()).replace(tzinfo=None, second=0, microsecond=0)


def notify(con, clock, kind, title, body, url="#today"):
    with WRITE:
        con.execute("insert into notifications (kind, title, body, url, created_at) values (?,?,?,?,?)",
                    (kind, title, body, url, local(clock.now()).strftime("%Y-%m-%dT%H:%M")))


def tick(state) -> list[str]:
    for watch in WATCHERS:
        watch(state)
    con, now, ran, pending = state.db, _now(state), [], []
    for job in JOBS:
        row = con.execute("select last_run from jobs where name = ?", (job.name,)).fetchone()
        if not row:  # first tick ever: count from today's midnight, so today's runs still happen
            with WRITE:
                con.execute("insert into jobs (name, last_run) values (?, ?)",
                            (job.name, datetime(now.year, now.month, now.day).isoformat(timespec="minutes")))
            row = con.execute("select last_run from jobs where name = ?", (job.name,)).fetchone()
        last = datetime.fromisoformat(row["last_run"])
        due, d = [], last.date()
        while d <= now.date():
            due += [t for t in job.times(d) if last < t <= now]
            d += timedelta(days=1)
        if due:
            pending.append((due[-1], job, due))
    # in the order they were due: last night's missed check-in before this morning's briefing
    for _, job, due in sorted(pending, key=lambda p: p[0]):
        with WRITE:
            con.execute("insert into jobs (name, last_run) values (?, ?) on conflict(name) do update set last_run = excluded.last_run",
                        (job.name, now.isoformat(timespec="minutes")))
        job.run(state, due[-1], now - due[-1] > GRACE, due[:-1])
        ran.append(job.name)
    return ran


# ---- the Briefing -------------------------------------------------------------

def build_briefing(con, day: date) -> dict:
    q = lambda sql, *a: [dict(r) for r in con.execute(sql, a)]
    iso = day.isoformat()
    soon = (day + timedelta(days=3)).isoformat()
    catchup = q("select id, text from catchup where consumed = 0 order by id")
    b = {
        "date": iso,
        "today": q("select * from tasks where status = 'open' and do_date = ? order by id", iso),
        "carried_over": q("select * from tasks where status = 'open' and do_date < ? order by do_date", iso),
        "events": plan.occurrences(q("select * from events"), iso, iso),
        "coming_up": q("select * from deadlines where substr(due, 1, 10) between ? and ? order by due", iso, soon)
        + q("select * from tasks where status = 'open' and do_date is null and substr(due, 1, 10) between ? and ? order by due", iso, soon),
        "questions": con.execute("select count(*) from questions where status = 'open'").fetchone()[0],
        "catchup": [c["text"] for c in catchup],
    }
    with WRITE:
        con.execute("insert into briefings (date, data) values (?, ?) on conflict(date) do update set data = excluded.data",
                    (iso, json.dumps(b)))
        con.executemany("update catchup set consumed = 1 where id = ?", [(c["id"],) for c in catchup])
    return b


def _plural(n, word, plural=None):
    return f"{n} {word if n == 1 else plural or word + 's'}"


def briefing_line(b) -> str:
    parts = [f"{len(b['today'])} to do"]
    if b["carried_over"]:
        parts.append(f"{len(b['carried_over'])} carried over")
    parts.append(_plural(len(b["events"]), "event"))
    if b["coming_up"]:
        parts.append(f"{_plural(len(b['coming_up']), 'deadline')} in the next 3 days")
    if b["questions"]:
        parts.append(f"{_plural(b['questions'], 'question')} waiting in Chat")
    return ", ".join(parts) + "."


def _briefing_job(state, scheduled, late, missed):
    day = _now(state).date()  # a late run briefs today, not the day it was due
    b = build_briefing(state.db, day)
    if not late:
        notify(state.db, state.clock, "briefing", f"Good morning: your {day:%a %b} {day.day}", briefing_line(b))


JOBS.append(Job("briefing", daily(9), _briefing_job))


# ---- running it ---------------------------------------------------------------

def start(app_state) -> threading.Event:
    """Tick in a background thread until the returned event is set."""
    stop = threading.Event()

    def loop():
        while not stop.is_set():
            try:
                tick(app_state)
            except Exception as e:  # a failing job must not stop the others tomorrow
                print(f"scheduler: {type(e).__name__}: {e}")
            stop.wait(TICK_SECONDS)

    threading.Thread(target=loop, name="almanac-scheduler", daemon=True).start()
    return stop


@router.post("/scheduler/tick")
def post_tick(request: Request):
    return {"ran": tick(request.app.state)}


@router.get("/briefing")
def get_briefing(request: Request):
    s = request.app.state
    r = s.db.execute("select data from briefings where date = ?", (_now(s).date().isoformat(),)).fetchone()
    return json.loads(r["data"]) if r else None


@router.get("/notifications")
def get_notifications(request: Request, after: int = 0):
    return [dict(r) for r in request.app.state.db.execute(
        "select * from notifications where id > ? order by id limit 50", (after,))]
