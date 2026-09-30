"""The Goals board, and keeping every active Goal moving: a Goal with no open
task anywhere gets one concrete next step proposed (with a new Project when
its Projects are all finished)."""

import json
from datetime import timedelta

from fastapi import APIRouter, HTTPException, Request

from . import inbox, plan
from .clock import local
from .ingest import capitalize
from .planner import day_loads

router = APIRouter(prefix="/api")

NEXT_PROMPT = """You help a student keep a long-term goal moving. Suggest ONE concrete next step they can do in a single sitting (under 3 hours), as a short imperative task title, with realistic hours. If the goal's projects are all finished (or it has none), also name the next project the step belongs to; otherwise leave "project" empty. Build on what's already done; don't repeat it."""

NEXT_SCHEMA = {"type": "object", "properties": {"project": {"type": "string"}, "task": {"type": "string"},
                                                "hours": {"type": "number"}}, "required": ["task", "hours"]}


def _projects(con, goal_id=None):
    where = "p.goal_id = ?" if goal_id is not None else "p.goal_id is null"
    rows = [dict(r) for r in con.execute(
        f"select p.*, (select count(*) from tasks t where t.project_id = p.id and t.status = 'open') as open, "
        f"(select count(*) from tasks t where t.project_id = p.id and t.status = 'done') as done "
        f"from projects p where {where} and p.status = 'active' order by coalesce(p.deadline, '9999'), p.id",
        (goal_id,) if goal_id is not None else ())]
    for p in rows:
        n = con.execute("select * from tasks where project_id = ? and status = 'open' "
                        "order by coalesce(do_date, substr(due, 1, 10), '9999'), id limit 1", (p["id"],)).fetchone()
        p["next"] = dict(n) if n else None
    return rows


@router.get("/board")
def board(request: Request):
    con = request.app.state.db
    goals = [dict(g) for g in con.execute("select * from goals where status = 'active' order by id")]
    for g in goals:
        g["projects"] = _projects(con, g["id"])
    return {"goals": goals, "projects": _projects(con)}


def _waiting_on(con, goal, projects) -> bool:
    """A suggestion for this goal is already waiting in the Inbox."""
    marks = [f'"goal_id": {goal["id"]}'] + [f'"project_id": {p["id"]}' for p in projects]
    return any(any(m in r["ops"] for m in marks) for r in con.execute("select ops from proposals where status = 'pending'"))


def next_steps(con, llm, clock) -> int:
    today = local(clock.now()).date()
    cap = plan.capacity(con)
    memories = "\n".join(f"- {r['text']}" for r in con.execute("select text from memories")) or "- nothing yet"
    n = 0
    for g in [dict(r) for r in con.execute("select * from goals where status = 'active' order by id")]:
        projects = _projects(con, g["id"])
        if any(p["open"] for p in projects) or _waiting_on(con, g, projects):
            continue
        unfinished = [p for p in projects if not p["done"]]
        history = "\n".join(
            f"- Project “{p['title']}”: " + (", ".join(r["title"] for r in con.execute(
                "select title from tasks where project_id = ? and status = 'done' order by done_at", (p["id"],))) or "nothing done yet")
            for p in projects) or "- no projects yet"
        user = (f"Goal: {g['title']}\nWhy: {g['why'] or 'not stated'}\nHorizon: {g['horizon'] or 'not stated'}\n\n"
                f"Projects and what's done:\n{history}\n\nWhat you know about the student:\n{memories}")
        try:
            got = json.loads(llm.chat([{"role": "system", "content": NEXT_PROMPT}, {"role": "user", "content": user}],
                                      schema=NEXT_SCHEMA, timeout=600))
        except Exception:
            continue
        task = capitalize((got.get("task") or "").strip())
        if not task:
            continue
        hours = min(max(float(got.get("hours") or 1), 0.25), 3)
        # the first day this week with room for it
        loads = day_loads(con, today, today + timedelta(days=6))
        day = next((d for d in (today + timedelta(days=i) for i in range(7))
                    if (cap["weekend"] if d.weekday() >= 5 else cap["weekday"]) - loads.get(d.isoformat(), 0) >= hours), today)
        data = {"title": task, "do_date": day.isoformat(), "estimate_min": round(hours * 60)}
        if unfinished:
            ops = [{"op": "create", "kind": "tasks", "data": {**data, "project_id": unfinished[-1]["id"]}}]
        else:
            name = capitalize((got.get("project") or "").strip()) or f"Next step toward {g['title']}"
            ops = [{"op": "create", "kind": "projects", "data": {"title": name, "goal_id": g["id"]}},
                   {"op": "create", "kind": "tasks", "data": {**data, "project_id": "$0"}}]
        p = inbox.propose(con, clock, None, f"Next step for “{g['title']}”: {task}", ops)
        n += "id" in p
    return n


@router.post("/goals/next-steps")
def post_next_steps(request: Request):
    s = request.app.state
    return {"proposed": next_steps(s.db, s.llm, s.clock)}


def focus_text(con, focus: dict | None) -> str:
    """What chat sees about the Project or Goal a "discuss" button focused on."""
    if not focus or focus.get("kind") not in ("projects", "goals"):
        return ""
    try:
        row = plan._row(con, focus["kind"], int(focus["id"]))
    except (HTTPException, TypeError, ValueError):
        return ""
    if focus["kind"] == "goals":
        projects = _projects(con, row["id"])
        body = "\n".join(f"- Project “{p['title']}” ({p['open']} open, {p['done']} done)" for p in projects) or "- no projects yet"
        return f"\n\nThe student is focused on this goal: {row['title']} (why: {row['why'] or 'not stated'}).\n{body}"
    tasks = con.execute("select title, status, do_date, due from tasks where project_id = ? order by coalesce(do_date, due, '9999')",
                        (row["id"],)).fetchall()
    body = "\n".join(f"- [{'x' if t['status'] == 'done' else ' '}] {t['title']}"
                     + (f" (do {t['do_date']})" if t["do_date"] else "") for t in tasks) or "- no tasks yet"
    return (f"\n\nThe student is focused on this project: {row['title']}"
            + (f", due {row['deadline']}" if row["deadline"] else "") + (f". Notes: {row['notes']}" if row["notes"] else "")
            + f"\nIts tasks:\n{body}")
