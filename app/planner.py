"""Backward planning: a Project with a deadline → dated Milestones, proposed.

The model only breaks the project into steps with hour estimates. Code places
them: the last one `slack` days before the deadline (plus `merge` more for
team projects), earlier ones spread at most MAX_GAP days apart, each on a day
with room left under the student's Capacity after existing tasks and class
time. A plan that can't fit is still proposed, with the overloaded days named."""

import json
import math
import re
from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, Request

from . import inbox, plan
from .clock import local
from .ingest import capitalize

router = APIRouter(prefix="/api")

BLOCK_HOURS = 3  # longer steps become several work blocks, each on its own day
MAX_GAP = 4      # days between blocks when there's plenty of time
SLACK_DAYS = 2   # finish before a hard deadline, not on it
MERGE_DAYS = 2   # team projects: time to combine everyone's parts

PROMPT = """You help a student plan a project that has a deadline. Break it into the concrete steps they will do, in order (e.g. for presenting a paper: first read, second read with notes, outline, slides, rehearse). For each step give a work kind (paper, slides, writing, coding, reading, other), its size and unit (pages, slides, words, task), and a realistic number of hours for this student, using what you know about them. 3 to 8 steps. Do not give dates."""

SCHEMA = {"type": "object", "properties": {"milestones": {"type": "array", "items": {"type": "object", "properties": {
    "title": {"type": "string"}, "work_kind": {"type": "string"}, "size": {"type": "number"}, "unit": {"type": "string"},
    "hours": {"type": "number"}}, "required": ["title", "hours"]}}}, "required": ["milestones"]}


def _hours(start, end) -> float:
    if not (start and end and len(start) > 10 and len(end) > 10):
        return 0
    s = int(start[11:13]) * 60 + int(start[14:16])
    e = int(end[11:13]) * 60 + int(end[14:16])
    return max(0, e - s) / 60


def day_loads(con, first: date, last: date) -> dict:
    """Hours already committed per day: open tasks' estimates plus class time."""
    load = {}
    for r in con.execute("select do_date, coalesce(estimate_min, 0) as m from tasks where status = 'open' and do_date between ? and ?",
                         (first.isoformat(), last.isoformat())):
        load[r["do_date"]] = load.get(r["do_date"], 0) + r["m"] / 60
    events = [dict(r) for r in con.execute("select * from events")]
    for e in plan.occurrences(events, first.isoformat(), last.isoformat()):
        load[e["start"][:10]] = load.get(e["start"][:10], 0) + _hours(e["start"], e["end"])
    return load


def place(blocks: list[float], today: date, last: date, load: dict, cap: dict):
    """Days for each block (in order) and warnings. Pure: no database."""
    load = dict(load)
    earliest = today
    last = max(last, earliest)
    n = len(blocks)
    window = (last - earliest).days + 1
    gap = min(MAX_GAP, window / n)
    capacity = lambda d: cap["weekend"] if d.weekday() >= 5 else cap["weekday"]
    free = lambda d: capacity(d) - load.get(d.isoformat(), 0)
    days, warnings = [None] * n, []
    for k in range(n - 1, -1, -1):
        upper = last - timedelta(days=round((n - 1 - k) * gap))
        if k < n - 1:  # before the next block: a different day when there's room for one
            upper = min(upper, days[k + 1] - timedelta(days=1) if gap >= 1 else days[k + 1])
        upper = max(upper, earliest)
        d = upper
        while d >= earliest and free(d) < blocks[k]:
            d -= timedelta(days=1)
        if d < earliest:  # nowhere with room: the least loaded day allowed
            span = [upper - timedelta(days=i) for i in range((upper - earliest).days + 1)]
            d = max(span, key=free)
        days[k] = d
        load[d.isoformat()] = load.get(d.isoformat(), 0) + blocks[k]
    for d in sorted(set(days)):
        if load[d.isoformat()] > capacity(d) + 1e-9:
            warnings.append(f"{d:%a %b} {d.day} would be over capacity ({load[d.isoformat()]:g}h of {capacity(d):g}h)")
    return days, warnings


@router.post("/projects/{id}/plan")
async def plan_project(id: int, request: Request):
    s = request.app.state
    body = await request.json() if await request.body() else {}
    p = plan._row(s.db, "projects", id)
    if not p["deadline"]:
        raise HTTPException(422, "Give the project a deadline first; plans are worked out backward from it.")
    slack = int(body.get("slack_days", SLACK_DAYS))
    merge = int(body.get("merge_days", MERGE_DAYS)) if p["team"] else 0
    today = local(s.clock.now()).date()
    deadline = date.fromisoformat(p["deadline"][:10])
    last = deadline - timedelta(days=slack + merge)

    memories = "\n".join(f"- {r['text']}" for r in s.db.execute("select text from memories")) or "- nothing yet"
    team = (f"\nThis is a team project: plan only the student's own part. What they said about their part: "
            f"{p['notes'] or 'not stated yet'}") if p["team"] else (f"\nNotes: {p['notes']}" if p["notes"] else "")
    user = f"Project: {p['title']}{team}\nDeadline: {deadline:%A, %B} {deadline.day}\n\nWhat you know about the student:\n{memories}"
    try:
        steps = json.loads(s.llm.chat([{"role": "system", "content": PROMPT}, {"role": "user", "content": user}],
                                      schema=SCHEMA, timeout=600))["milestones"]
    except Exception as e:
        raise HTTPException(503, f"The model couldn't break the project into steps ({type(e).__name__}). Try again in a bit.")
    steps = [st for st in steps if (st.get("title") or "").strip() and isinstance(st.get("hours"), (int, float))]
    if not steps:
        raise HTTPException(503, "The model didn't suggest any steps. Try again.")

    # Page counts are facts about the paper: only ones the student stated count.
    # With a known size and the student's own pace, the pace sets the hours.
    from .timers import UNITS, rates  # timers builds on plan
    pace = rates(s.db)
    stated = re.search(r"(\d+)\s*pages?\b", f"{p['title']} {p['notes'] or ''}", re.I)
    for st in steps:
        if st.get("work_kind") in ("paper", "reading"):
            st["size"] = int(stated.group(1)) if stated else None
            if not stated:
                inbox.ask(s.db, s.clock, None, f"How many pages is the paper for “{p['title']}”?")
        mpu = (pace.get(st.get("work_kind")) or {}).get("minutes_per_unit")
        if mpu and isinstance(st.get("size"), (int, float)) and st["size"] > 0 and st.get("work_kind") in UNITS:
            st["hours"] = mpu * st["size"] / 60

    blocks, meta = [], []
    for st in steps:
        hours = min(max(float(st["hours"]), 0.25), 40)
        parts = math.ceil(hours / BLOCK_HOURS)
        for i in range(parts):
            h = min(BLOCK_HOURS, hours - i * BLOCK_HOURS)
            blocks.append(h)
            meta.append((st, f" ({i + 1}/{parts})" if parts > 1 else ""))
    load = day_loads(s.db, today, max(last, today))
    days, warnings = place(blocks, today, last, load, plan.capacity(s.db))

    ops = []
    for (st, part), h, d in zip(meta, blocks, days):
        data = {"title": capitalize(st["title"].strip()) + part, "project_id": id, "due": p["deadline"],
                "do_date": d.isoformat(), "estimate_min": round(h * 60)}
        if p["course_id"]:
            data["course_id"] = p["course_id"]
        if st.get("work_kind"):
            data["work_kind"] = st["work_kind"]
        if isinstance(st.get("size"), (int, float)) and st["size"] > 0:
            data["size"] = st["size"]
        ops.append({"op": "create", "kind": "tasks", "data": data})
    fmt = lambda d: f"{d:%a %b} {d.day}"
    summary = f"Plan for “{p['title']}”: {len(ops)} steps, {fmt(min(days))} – {fmt(max(days))}"
    if warnings:
        summary += "; some days over capacity"
    proposal = inbox.propose(s.db, s.clock, None, summary, ops, "; ".join(warnings) or None)
    if "id" not in proposal:  # the same plan is already waiting
        proposal = inbox._proposal(s.db, proposal["existing"]["id"])
    return {"proposal": proposal, "warnings": warnings}
