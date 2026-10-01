"""Proposals and Questions: every assistant-originated change waits here.

A Proposal is a list of operations ({op: create|update|delete, kind, id?, data?})
applied all-or-nothing. A data value "$N" is the id created by operation N of
the same Proposal; "$pID.N" is the id created by operation N of Proposal ID
(which must be accepted first)."""

import hashlib
import json
import re

from fastapi import APIRouter, HTTPException, Request

from . import plan
from .clock import local
from .db import WRITE

router = APIRouter(prefix="/api")
REF = re.compile(r"^\$(?:p(\d+)\.)?(\d+)$")


def _now(clock) -> str:
    return local(clock.now()).strftime("%Y-%m-%dT%H:%M")


def _proposal(con, id) -> dict:
    r = con.execute("select * from proposals where id = ?", (id,)).fetchone()
    if not r:
        raise HTTPException(404)
    return {**dict(r), "ops": json.loads(r["ops"]), "applied": json.loads(r["applied"] or "null")}


def _check_ops(ops):
    if not isinstance(ops, list) or not ops:
        raise HTTPException(422, "ops must be a non-empty list")
    for o in ops:
        if o.get("op") not in ("create", "update", "delete") or o.get("kind") not in plan.KINDS:
            raise HTTPException(422, f"bad operation {o}")
        if o["op"] != "create" and not isinstance(o.get("id"), int):
            raise HTTPException(422, f"{o['op']} needs an id")


def propose(con, clock, source_id, summary, ops, quote=None, question_id=None) -> dict:
    """Queue a Proposal unless the same one is pending or was rejected."""
    _check_ops(ops)
    fp = hashlib.sha1(json.dumps(ops, sort_keys=True).encode()).hexdigest()
    with WRITE:
        same = con.execute("select id, status from proposals where fingerprint = ? and status in ('pending', 'rejected')",
                           (fp,)).fetchone()
        if same:
            return {"suppressed": True, "existing": dict(same)}
        cur = con.execute(
            "insert into proposals (source_id, question_id, summary, quote, ops, fingerprint, created_at) values (?,?,?,?,?,?,?)",
            (source_id, question_id, summary, quote, json.dumps(ops), fp, _now(clock)))
        return _proposal(con, cur.lastrowid)


def ask(con, clock, source_id, text, quote=None, purpose="other", target=None, options=None) -> dict:
    """Queue a Question unless the same one is already open. purpose, target
    and options say what the answer is for and acts on (see questions.py)."""
    with WRITE:
        same = con.execute("select * from questions where text = ? and status = 'open'", (text,)).fetchone()
        if same:
            return dict(same)
        cur = con.execute("insert into questions (source_id, text, quote, created_at, purpose, target, options) values (?,?,?,?,?,?,?)",
                          (source_id, text, quote, _now(clock), purpose, json.dumps(target or {}),
                           json.dumps(options) if options else None))
        return dict(con.execute("select * from questions where id = ?", (cur.lastrowid,)).fetchone())


def add_target(con, question_id, proposal_id):
    """The answer to this question acts on what this proposal adds (dates it,
    names its instructor), whether or not the question holds it up."""
    with WRITE:
        row = con.execute("select target from questions where id = ?", (question_id,)).fetchone()
        target = json.loads(row["target"]) if row and row["target"] else {}
        if proposal_id not in target.setdefault("proposals", []):
            target["proposals"].append(proposal_id)
        con.execute("update questions set target = ? where id = ?", (json.dumps(target), question_id))


def mark_optional(con, proposal_id):
    """Offered, not assumed: shown unticked and left out of Accept all."""
    with WRITE:
        con.execute("update proposals set optional = 1 where id = ?", (proposal_id,))


def set_options(con, question_id, options):
    with WRITE:
        con.execute("update questions set options = ? where id = ?", (json.dumps(options), question_id))


def withdraw(con, id):
    """Undo a proposal entirely (rewinding the chat message that made it):
    an accepted one's changes are reversed, then the proposal is removed."""
    with WRITE:
        row = con.execute("select status from proposals where id = ?", (id,)).fetchone()
        if not row:
            return
        if row["status"] == "accepted":
            plan.undo(con, id)  # by its history: only rows this proposal itself changed
        con.execute("delete from proposals where id = ?", (id,))


def propose_and_accept(con, clock, source_id, summary, ops, quote=None) -> dict | None:
    """A change the student's own answer settles: proposed and accepted at once,
    so it goes through the gate, shows in the item's history and can be undone."""
    p = propose(con, clock, source_id, summary, ops, quote)
    return accept(con, clock, p["id"]) if "id" in p else None


def _resolve(con, value, created):
    m = REF.match(value) if isinstance(value, str) else None
    if not m:
        return value
    other, index = m.group(1), int(m.group(2))
    if other is None:
        return created[index]
    p = _proposal(con, int(other))
    if p["status"] != "accepted":
        raise HTTPException(409, f"Accept “{p['summary']}” first.")
    return p["applied"][index]


def accept(con, clock, id, ops=None) -> dict:
    p = _proposal(con, id)
    if p["status"] != "pending":
        raise HTTPException(409, f"This proposal was already {p['status']}.")
    if p["question_id"]:
        q = con.execute("select * from questions where id = ?", (p["question_id"],)).fetchone()
        if q and q["status"] != "answered":
            raise HTTPException(409, f"Answer the question first: {q['text']}")
    if ops is not None:
        _check_ops(ops)
    ops = ops if ops is not None else p["ops"]
    now, created = _now(clock), []
    with WRITE:
        return _apply(con, id, ops, now, created)


def _apply(con, id, ops, now, created):
    con.execute("begin")
    try:
        for o in ops:  # through the gate, which records each change against this proposal
            data = {k: _resolve(con, v, created) for k, v in (o.get("data") or {}).items()}
            if o["op"] == "create":
                created.append(plan.insert(con, o["kind"], data, id, now)["id"])
            elif o["op"] == "update":
                created.append(plan.change(con, o["kind"], o["id"], data, now, id)["id"])
            else:
                plan.remove(con, o["kind"], o["id"], id, now)
                created.append(o["id"])
        con.execute("update proposals set status = 'accepted', ops = ?, applied = ?, decided_at = ? where id = ?",
                    (json.dumps(ops), json.dumps(created), now, id))
        con.execute("commit")
    except HTTPException as e:
        con.execute("rollback")
        detail = e.detail if e.status_code != 404 else "Something this proposal changes no longer exists."
        raise HTTPException(409, detail)
    except Exception:
        con.execute("rollback")
        raise
    return _proposal(con, id)


# ---- HTTP --------------------------------------------------------------------

@router.get("/inbox")
def inbox(request: Request):
    con = request.app.state.db
    sources = {r["id"]: {"id": r["id"], "title": r["title"], "kind": r["kind"]} for r in con.execute("select * from sources")}
    questions = [dict(r) for r in con.execute("select * from questions where status = 'open' order by id")]
    open_q = {q["id"]: q for q in questions}
    proposals = []
    for r in con.execute("select id from proposals where status = 'pending' order by id"):
        p = _proposal(con, r["id"])
        p["source"] = sources.get(p["source_id"])
        p["blocked_by"] = open_q.get(p["question_id"], {}).get("text")
        proposals.append(p)
    return {"proposals": proposals, "count": len(proposals)}  # questions are asked in chat


@router.get("/questions")
def open_questions(request: Request):
    return [dict(r) for r in request.app.state.db.execute("select * from questions where status = 'open' order by id")]


@router.post("/sources")
async def add_source(request: Request):
    b = await request.json()
    con = request.app.state.db
    cur = con.execute("insert into sources (kind, title, text, created_at) values (?,?,?,?)",
                      (b.get("kind", "manual"), b["title"], b.get("text", ""), _now(request.app.state.clock)))
    return dict(con.execute("select * from sources where id = ?", (cur.lastrowid,)).fetchone())


@router.post("/sources/{id}/accept-all")
def accept_all(id: int, request: Request):
    s = request.app.state
    accepted, skipped = 0, []
    for r in s.db.execute("select id, summary from proposals where source_id = ? and status = 'pending' and not optional order by id", (id,)).fetchall():
        try:
            accept(s.db, s.clock, r["id"])
            accepted += 1
        except HTTPException as e:
            skipped.append({"id": r["id"], "summary": r["summary"], "reason": e.detail})
    return {"accepted": accepted, "skipped": skipped}


@router.post("/proposals")
async def create_proposal(request: Request):
    b = await request.json()
    s = request.app.state
    return propose(s.db, s.clock, b.get("source_id"), b["summary"], b["ops"], b.get("quote"), b.get("question_id"))


@router.post("/proposals/{id}/accept")
async def accept_route(id: int, request: Request):
    body = await request.json() if await request.body() else {}
    return accept(request.app.state.db, request.app.state.clock, id, body.get("ops"))


@router.post("/proposals/{id}/reject")
def reject(id: int, request: Request):
    s = request.app.state
    if _proposal(s.db, id)["status"] != "pending":
        raise HTTPException(409, "Only pending proposals can be rejected.")
    s.db.execute("update proposals set status = 'rejected', decided_at = ? where id = ?", (_now(s.clock), id))
    return _proposal(s.db, id)


@router.post("/questions")
async def create_question(request: Request):
    b = await request.json()
    return ask(request.app.state.db, request.app.state.clock, b.get("source_id"), b["text"], b.get("quote"))


@router.get("/questions/{id}")
def get_question(id: int, request: Request):
    r = request.app.state.db.execute("select * from questions where id = ?", (id,)).fetchone()
    if not r:
        raise HTTPException(404)
    return dict(r)


@router.post("/questions/{id}/answer")
async def answer(id: int, request: Request):
    b = await request.json()
    s = request.app.state
    if not (b.get("answer") or "").strip():
        raise HTTPException(422, "answer is empty")
    get_question(id, request)
    s.db.execute("update questions set answer = ?, status = 'answered', answered_at = ? where id = ?",
                 (b["answer"].strip(), _now(s.clock), id))
    return get_question(id, request)
