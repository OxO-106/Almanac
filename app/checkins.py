"""Evening check-ins and the nightly Replan.

8pm, every day: ask what's new today, and about today's still-open tasks (notification + a chat message; the
reply goes through chat's suggestions pass, so "finished the reading" becomes
a proposal to tick it off). 11pm: ask once more about what's still open.
10:30pm: any Project with a step whose do date has passed gets a Replan
Proposal re-placing its open steps from tomorrow; a second slip starts a
conversation. Loose missed tasks are proposed onto the next day with room."""

import json
from datetime import date, timedelta

from . import inbox, plan, planner
from .db import WRITE
from .scheduler import JOBS, Job, _now, daily, notify

SLIPS_FOR_A_CHAT = 2
WHATS_NEW = "Anything new today? New deadlines, plans, something mentioned in class: tell me and I'll suggest adding it."


def _open_today(con, day: date):
    return [dict(r) for r in con.execute("select * from tasks where status = 'open' and do_date = ? order by id", (day.isoformat(),))]


def _say(con, clock, text):
    from .chat import _say as say  # chat imports goals which imports planner: import late to avoid a cycle
    say(con, clock, "assistant", text)


def _checkin(final: bool):
    def run(state, scheduled, late, missed):
        con, clock = state.db, state.clock
        day = scheduled.date()
        titles = ", ".join(t["title"] for t in _open_today(con, day))
        if not titles:
            # The 8pm check-in happens every day: what's new is worth asking even with nothing open.
            if not final and not late:
                notify(con, clock, "checkin", "Anything new today?", "New deadlines, plans, something mentioned in class?", "#chat")
                _say(con, clock, f"It's 8pm. {WHATS_NEW}")
            return
        if late:  # the PC was off: tell the next briefing instead of pinging now (once for both check-ins)
            text = f"{day:%b} {day.day}: {titles} {'was' if ',' not in titles else 'were'} still open at the evening check-in."
            with WRITE:
                if not con.execute("select 1 from catchup where text = ? and consumed = 0", (text,)).fetchone():
                    con.execute("insert into catchup (text) values (?)", (text,))
            return
        if final:
            notify(con, clock, "checkin", "Last check for today", f"Still open: {titles}. Done, or should I move it?", "#chat")
            _say(con, clock, f"Last check for today: {titles} {'is' if ',' not in titles else 'are'} still open. "
                             "Done, or should I move it to another day?")
        else:
            notify(con, clock, "checkin", "How did today go?", f"Still open: {titles}. Anything new today?", "#chat")
            _say(con, clock, f"It's 8pm. How did today go? Still open from today's plan: {titles}. "
                             f"Tell me what you finished, or tick it off on Today. And {WHATS_NEW[0].lower()}{WHATS_NEW[1:]}")
    return run


def _pending_for(con, kind, id) -> bool:
    mark = f'"kind": "{kind}", "id": {id}'
    return any(mark in r["ops"] for r in con.execute("select ops from proposals where status = 'pending'"))


def _replan(state, scheduled, late, missed):
    con, clock = state.db, state.clock
    today = _now(state).date()
    tomorrow = today + timedelta(days=1)
    cap = plan.capacity(con)
    slipped = [dict(r) for r in con.execute(
        "select * from tasks where status = 'open' and do_date < ? order by do_date, id", (today.isoformat(),))]

    for pid in sorted({t["project_id"] for t in slipped if t["project_id"]}):
        p = plan._row(con, "projects", pid)
        steps = [dict(r) for r in con.execute("select * from tasks where project_id = ? and status = 'open' "
                                              "order by coalesce(do_date, '9999'), id", (pid,))]
        if any(_pending_for(con, "tasks", t["id"]) for t in steps):
            continue
        deadline = date.fromisoformat(p["deadline"][:10]) if p["deadline"] else None
        last = (deadline - timedelta(days=planner.SLACK_DAYS + (planner.MERGE_DAYS if p["team"] else 0))
                if deadline else max(date.fromisoformat(t["do_date"]) for t in steps if t["do_date"]))
        last = max(last, tomorrow)
        load = planner.day_loads(con, tomorrow, last)
        for t in steps:  # these steps are what's being placed: take them out of the load
            if t["do_date"] and t["do_date"] in load:
                load[t["do_date"]] -= (t["estimate_min"] or 60) / 60
        days, warnings = planner.place([(t["estimate_min"] or 60) / 60 for t in steps], tomorrow, last, load, cap)
        ops = [{"op": "update", "kind": "tasks", "id": t["id"], "data": {"do_date": d.isoformat()}}
               for t, d in zip(steps, days) if t["do_date"] != d.isoformat()]
        if not ops:
            continue
        missed_titles = ", ".join(t["title"] for t in slipped if t["project_id"] == pid)
        summary = f"Replan “{p['title']}”: {missed_titles} missed; {len(ops)} step{'s' if len(ops) > 1 else ''} moved"
        inbox.propose(con, clock, None, summary + ("; some days over capacity" if warnings else ""), ops,
                      "; ".join(warnings) or None)
        with WRITE:
            slips = con.execute("update projects set slips = coalesce(slips, 0) + 1 where id = ? returning slips", (pid,)).fetchone()[0]
        if slips == SLIPS_FOR_A_CHAT:
            _say(con, clock, f"“{p['title']}” has slipped twice now. What's getting in the way? We could make the "
                             "steps smaller, move the deadline if that's possible, or drop something else this week.")

    loose = [t for t in slipped if not t["project_id"] and not _pending_for(con, "tasks", t["id"])]
    if loose:
        load = planner.day_loads(con, tomorrow, tomorrow + timedelta(days=13))
        ops = []
        for t in loose:
            hours = (t["estimate_min"] or 60) / 60
            limit = date.fromisoformat(t["due"][:10]) if t["due"] and t["due"][:10] > tomorrow.isoformat() else tomorrow + timedelta(days=13)
            day = next((tomorrow + timedelta(days=i) for i in range((limit - tomorrow).days + 1)
                        if (cap["weekend"] if (tomorrow + timedelta(days=i)).weekday() >= 5 else cap["weekday"])
                        - load.get((tomorrow + timedelta(days=i)).isoformat(), 0) >= hours), tomorrow)
            load[day.isoformat()] = load.get(day.isoformat(), 0) + hours
            ops.append({"op": "update", "kind": "tasks", "id": t["id"], "data": {"do_date": day.isoformat()}})
        inbox.propose(con, clock, None, f"Move {len(ops)} missed task{'s' if len(ops) > 1 else ''} to the next day with room", ops)


JOBS.append(Job("checkin", daily(20), _checkin(final=False)))
JOBS.append(Job("replan", daily(22, 30), _replan))
JOBS.append(Job("checkin-final", daily(23), _checkin(final=True)))
