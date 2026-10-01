"""Bruin Learn (Canvas) calendar feed → Deadline and Event proposals.

The feed link is a secret (anyone with it can read the calendar): it lives in
the local settings table and is only ever shown masked. Every CHECK_HOURS the
feed is fetched and diffed by event UID against what earlier fetches put in
the plan: new items are proposed, moved ones become updates, removed ones
removal proposals. A Canvas section ("26F-COM SCI-239-LEC-4") is linked to a
Course once: automatically when only one Course has that number, otherwise by
asking. Items the plan already has (from a syllabus) are linked, not added."""

import json
import re
from datetime import date, datetime, timezone

import httpx
from fastapi import APIRouter, HTTPException, Request

from . import inbox, ingest, merge
from .clock import LA, local
from .db import WRITE, settings
from .scheduler import JOBS, Job, notify

router = APIRouter(prefix="/api")
CHECK_HOURS = (6, 9, 12, 15, 18, 21)
SOURCE_TITLE = "Bruin Learn"
DEPT_ALIASES = {"COM SCI": "CS"}  # Canvas uses the registrar's department names


def fetch_url(url: str) -> str:
    r = httpx.get(url, timeout=30, follow_redirects=True)
    r.raise_for_status()
    return r.text


# ---- reading the feed ---------------------------------------------------------

def _unescape(v: str) -> str:
    return v.replace("\\n", "\n").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\").strip()


def _when(name: str, value: str) -> str | None:
    """An iCalendar date/time as a Los Angeles wall-clock string."""
    v = value.strip()
    try:
        if "VALUE=DATE" in name and "T" not in v:
            return date(int(v[:4]), int(v[4:6]), int(v[6:8])).isoformat()
        dt = datetime.strptime(v[:15], "%Y%m%dT%H%M%S")
        if v.endswith("Z"):
            dt = dt.replace(tzinfo=timezone.utc).astimezone(LA)
        return dt.strftime("%Y-%m-%dT%H:%M")  # TZID times are already local (Canvas uses the user's zone)
    except ValueError:
        return None


def parse(text: str) -> list[dict]:
    text = re.sub(r"\r?\n[ \t]", "", text)  # unfold continuation lines
    events = []
    for block in text.split("BEGIN:VEVENT")[1:]:
        e = {}
        for line in block.split("END:VEVENT")[0].splitlines():
            if ":" not in line:
                continue
            name, value = line.split(":", 1)
            key = name.split(";")[0].upper()
            if key in ("DTSTART", "DTEND"):
                e[key] = _when(name, value)
            elif key in ("UID", "SUMMARY", "URL"):
                e[key] = _unescape(value)
        if e.get("UID") and e.get("SUMMARY") and e.get("DTSTART"):
            m = re.search(r"\s*\[([^\]]+)\]\s*$", e["SUMMARY"])
            e["title"] = ingest.capitalize(e["SUMMARY"][:m.start()].strip() if m else e["SUMMARY"])
            e["code"] = m.group(1) if m else None
            events.append(e)
    return events


def section(code: str) -> tuple[str, str] | None:
    """"26F-COM SCI-239-LEC-4" → ("COM SCI 239", "LEC-4")."""
    m = re.match(r"^\d{2}[A-Z]-(.+?)-(\d+[A-Z]*)-([A-Z]+-?\d+)$", code or "")
    return (f"{m.group(1)} {m.group(2)}", m.group(3)) if m else None


def _norm_number(number: str) -> str:
    n = ingest.course_number(number).upper()
    for long, short in DEPT_ALIASES.items():
        n = n.replace(long, short)
    return n.replace(" ", "")


# ---- course for a section -----------------------------------------------------

def _course_for(con, clock, source_id, code, ask=True):
    """(course_id or None, question or None) for a Canvas section code."""
    if not code:
        return None, None
    known = con.execute("select course_id from canvas_sections where code = ?", (code,)).fetchone()
    if known:
        return known["course_id"], None
    sec = section(code)
    if not sec:
        return None, None
    matches = [dict(r) for r in con.execute("select * from courses") if _norm_number(r["number"]) == _norm_number(sec[0])]
    if len(matches) == 1:
        with WRITE:
            con.execute("insert into canvas_sections (code, course_id) values (?, ?)", (code, matches[0]["id"]))
        return matches[0]["id"], None
    if len(matches) > 1 and ask:
        names = " or ".join(f"{c['number']} · {c['instructor'].split()[-1]}" for c in matches)
        q = inbox.ask(con, clock, source_id, f"Which of your courses is {sec[0]} ({sec[1]}) on Bruin Learn: {names}?",
                      meta={"type": "canvas_section", "code": code, "courses": [c["id"] for c in matches]})
        return None, q
    return None, None


def answer_section(con, question, meta, text) -> str | None:
    """The student said which course a section is: remember it and link what waited."""
    said = text.lower()
    hits = [c for c in (dict(r) for r in con.execute(
        f"select * from courses where id in ({','.join('?' * len(meta['courses']))})", meta["courses"]))
        if c["instructor"].split()[-1].lower() in said or c["instructor"].lower() in said]
    if len(hits) != 1:
        return None
    c = hits[0]
    with WRITE:
        con.execute("insert or replace into canvas_sections (code, course_id) values (?, ?)", (meta["code"], c["id"]))
        for p in con.execute("select id, ops from proposals where question_id = ? and status = 'pending'", (question["id"],)).fetchall():
            ops = json.loads(p["ops"])
            for o in ops:
                if o["op"] == "create":
                    o["data"]["course_id"] = c["id"]
            con.execute("update proposals set ops = ? where id = ?", (json.dumps(ops), p["id"]))
    return f"Linked {section(meta['code'])[0]} ({section(meta['code'])[1]}) to {c['number']} · {c['instructor']}."


# ---- syncing ------------------------------------------------------------------

def _source(con, clock) -> int:
    row = con.execute("select id from sources where kind = 'canvas'").fetchone()
    if row:
        return row["id"]
    with WRITE:
        return con.execute("insert into sources (kind, title, text, status, created_at) values ('canvas', ?, '', 'done', ?)",
                           (SOURCE_TITLE, local(clock.now()).strftime("%Y-%m-%dT%H:%M"))).lastrowid


def _entity(con, item):
    """The plan row a feed item is linked to, if it still exists."""
    kind, eid = item["entity_kind"], item["entity_id"]
    if not eid and item["proposal_id"]:
        p = con.execute("select ops, applied, status from proposals where id = ?", (item["proposal_id"],)).fetchone()
        if p and p["status"] == "accepted":
            kind, eid = json.loads(p["ops"])[0]["kind"], json.loads(p["applied"])[0]
    if not eid:
        return None, None
    row = con.execute(f"select * from {kind} where id = ?", (eid,)).fetchone()
    return kind, (dict(row) if row else None)


def sync(con, clock, fetch) -> dict:
    cfg = settings(con).get("canvas") or {}
    if not cfg.get("url"):
        raise HTTPException(409, "Connect your Bruin Learn calendar feed first.")
    now = local(clock.now()).strftime("%Y-%m-%dT%H:%M")
    try:
        events = parse(fetch(cfg["url"]))
    except Exception as e:
        if cfg.get("status") != "error":
            notify(con, clock, "canvas", "Your Bruin Learn feed stopped working",
                   "Paste a new calendar feed link in Settings.", "#settings")
        _save(con, {**cfg, "status": "error", "error": f"{type(e).__name__}: {e}"[:200], "checked": now})
        return {"new": 0, "changed": 0, "removed": 0}
    src = _source(con, clock)
    counts = {"new": 0, "changed": 0, "removed": 0}
    seen = set()
    for e in events:
        seen.add(e["UID"])
        kind = "deadlines" if "assignment" in e["UID"] or not e.get("DTEND") or e["DTEND"] == e["DTSTART"] else "events"
        data = {"title": e["title"]}
        data["due" if kind == "deadlines" else "start"] = e["DTSTART"]
        if kind == "events" and e.get("DTEND"):
            data["end"] = e["DTEND"]
        course, question = _course_for(con, clock, src, e.get("code"))
        if course:
            data["course_id"] = course
        item = con.execute("select * from canvas_items where uid = ?", (e["UID"],)).fetchone()
        quote = e["SUMMARY"]
        if not item:
            # already in the plan (e.g. from the syllabus)? link it, and offer only what's new
            table, existing = merge.find(con, kind, data)
            pending = None if existing else merge.find_pending(con, kind, data)
            pid = None
            if existing:
                merge.propose_or_fill(con, clock, src, kind, data, quote)
            elif pending:
                merge.merge_into_pending(con, pending, data)
                pid = pending["id"]
            else:
                p = merge.propose_or_fill(con, clock, src, kind, data, quote, question["id"] if question else None)
                pid = p and p["id"]
                counts["new"] += bool(p)
            with WRITE:
                con.execute("insert into canvas_items (uid, proposal_id, entity_kind, entity_id, gone) values (?,?,?,?,0)",
                            (e["UID"], pid, table, existing and existing["id"]))
            continue
        ekind, row = _entity(con, dict(item))
        if row and ekind in ("deadlines", "events", "tasks") and not inbox_pending_for(con, ekind, row["id"]):
            # learned since it was accepted (its course, its project): offer to fill them in
            known = dict(data)
            if pid := merge.project_for(con, data.get("course_id") or row.get("course_id"), row["title"]):
                known["project_id"] = pid
            fill = {k: v for k, v in merge.details(ekind, row, known).items() if k in ("course_id", "project_id")}
            if fill:
                inbox.propose(con, clock, src, merge.summary(row, fill),
                              [{"op": "update", "kind": ekind, "id": row["id"], "data": fill}], quote)
        if row:
            field = "due" if ekind == "deadlines" else "start"
            if ekind in ("deadlines", "events") and row.get(field) != data.get(field) \
                    and not inbox_pending_for(con, ekind, row["id"]):
                old, new = row.get(field), data.get(field)
                fmt = lambda v: f"{date.fromisoformat(v[:10]):%b} {int(v[8:10])}" + (f" {v[11:]}" if len(v) > 10 else "")
                inbox.propose(con, clock, src, f"Bruin Learn moved “{row['title']}”: {fmt(old) if old else 'no date'} → {fmt(new)}",
                              [{"op": "update", "kind": ekind, "id": row["id"], "data": {field: new}}], quote)
                counts["changed"] += 1
        elif item["proposal_id"]:  # still waiting in the Inbox: keep it current
            p = con.execute("select ops, status from proposals where id = ?", (item["proposal_id"],)).fetchone()
            if p and p["status"] == "pending":
                ops = json.loads(p["ops"])
                if ops[0]["data"] != {**ops[0]["data"], **data}:
                    ops[0]["data"].update(data)
                    with WRITE:
                        con.execute("update proposals set ops = ? where id = ?", (json.dumps(ops), item["proposal_id"]))
                if question:  # its course became ambiguous since: it waits on the answer too
                    with WRITE:
                        con.execute("update proposals set question_id = ? where id = ?", (question["id"], item["proposal_id"]))
    for item in [dict(r) for r in con.execute("select * from canvas_items where gone = 0")]:
        if item["uid"] in seen:
            continue
        ekind, row = _entity(con, item)
        with WRITE:
            con.execute("update canvas_items set gone = 1 where uid = ?", (item["uid"],))
            if not row and item["proposal_id"]:
                con.execute("delete from proposals where id = ? and status = 'pending'", (item["proposal_id"],))
        if row:
            inbox.propose(con, clock, src, f"“{row['title']}” was removed from Bruin Learn. Remove it?",
                          [{"op": "delete", "kind": ekind, "id": row["id"]}])
            counts["removed"] += 1
    _save(con, {**cfg, "status": "ok", "error": None, "checked": now})
    return counts


def inbox_pending_for(con, kind, id) -> bool:
    mark = f'"kind": "{kind}", "id": {id}'
    return any(mark in r["ops"] for r in con.execute("select ops from proposals where status = 'pending'"))


def _save(con, cfg):
    with WRITE:
        con.execute("insert into settings (key, value) values ('canvas', ?) on conflict(key) do update set value = excluded.value",
                    (json.dumps(cfg),))


def _job(state, scheduled, late, missed):
    if not (settings(state.db).get("canvas") or {}).get("url"):
        return
    counts = sync(state.db, state.clock, state.fetch)
    if counts["new"] and not late:
        notify(state.db, state.clock, "canvas", f"{counts['new']} new from Bruin Learn",
               "Review them in Suggestions.", "#inbox")


JOBS.append(Job("canvas", lambda d: [datetime(d.year, d.month, d.day, h) for h in CHECK_HOURS], _job))


# ---- HTTP ---------------------------------------------------------------------

def _masked(cfg):
    url = cfg.get("url") or ""
    return {"connected": bool(url), "link": (url.split("/feeds/")[0] + "/feeds/…" + url[-8:]) if url else None,
            "status": cfg.get("status"), "error": cfg.get("error"), "checked": cfg.get("checked")}


@router.get("/canvas")
def get_canvas(request: Request):
    return _masked(settings(request.app.state.db).get("canvas") or {})


@router.put("/canvas")
async def put_canvas(request: Request):
    url = ((await request.json()).get("url") or "").strip()
    if not re.match(r"^https://[^\s]+/feeds/calendars/[^\s]+\.ics$", url):
        raise HTTPException(422, "That doesn't look like a Bruin Learn calendar feed link (…/feeds/calendars/….ics).")
    _save(request.app.state.db, {"url": url, "status": None})
    return _masked({"url": url})


@router.delete("/canvas")
def delete_canvas(request: Request):
    _save(request.app.state.db, {})
    return _masked({})


@router.post("/canvas/fetch")
def fetch_now(request: Request):
    s = request.app.state
    return sync(s.db, s.clock, s.fetch)
