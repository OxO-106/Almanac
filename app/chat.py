"""The conversation with the assistant.

Open Questions are asked here one at a time, most important first (the ones
holding up the most proposals), instead of piling up as a list. A reply to a
question answers it; otherwise the message goes to the model."""

from datetime import timedelta

from fastapi import APIRouter, HTTPException, Request

from .clock import local
from .db import WRITE

router = APIRouter(prefix="/api/chat")
HISTORY = 20  # messages of context sent to the model


def _utc(clock) -> str:
    return clock.now().isoformat(timespec="seconds")


def _say(con, clock, role, text, question_id=None, quote=None):
    with WRITE:
        con.execute("insert into chat_messages (role, text, question_id, quote, created_at) values (?,?,?,?,?)",
                    (role, text, question_id, quote, local(clock.now()).strftime("%Y-%m-%dT%H:%M")))


def _eligible(con, clock) -> list[dict]:
    """Open questions not snoozed, most blocking first."""
    return [dict(r) for r in con.execute(
        "select q.*, s.title as source_title, (select count(*) from proposals p where p.question_id = q.id "
        "and p.status = 'pending') as blocking from questions q left join sources s on s.id = q.source_id "
        "where q.status = 'open' and (q.snoozed_until is null or q.snoozed_until <= ?) order by blocking desc, q.id",
        (_utc(clock),))]


def _current(con, clock):
    """The question the assistant last asked, if it's still waiting for a reply."""
    last = con.execute("select m.*, q.status, q.snoozed_until from chat_messages m join questions q on q.id = m.question_id "
                       "order by m.id desc limit 1").fetchone()
    if last and last["status"] == "open" and (not last["snoozed_until"] or last["snoozed_until"] <= _utc(clock)):
        return dict(last)
    return None


def _ask_next(con, clock):
    if _current(con, clock):
        return
    queue = _eligible(con, clock)
    if queue:
        q = queue[0]
        name = (q.get("source_title") or "").rsplit(".", 1)[0].replace("_", " ").strip()
        name = " ".join(name.split())
        name = name if len(name) <= 40 else name[:38].rstrip() + "…"
        about = f"Quick question about “{name}”: " if name else ""
        _say(con, clock, "assistant", about + q["text"], q["id"], q["quote"])


def state(con, clock) -> dict:
    _ask_next(con, clock)
    cur = _current(con, clock)
    messages = [dict(r) for r in con.execute("select id, role, text, question_id, quote, created_at from chat_messages order by id")]
    waiting = len(_eligible(con, clock)) - (1 if cur else 0)
    return {"messages": messages, "current": cur and {"id": cur["id"], "question_id": cur["question_id"], "text": cur["text"]},
            "waiting": waiting}


def _answer(con, clock, question_id, text):
    with WRITE:
        con.execute("update questions set answer = ?, status = 'answered', answered_at = ? where id = ?",
                    (text, local(clock.now()).strftime("%Y-%m-%dT%H:%M"), question_id))
    n = con.execute("select count(*) from proposals where question_id = ? and status = 'pending'", (question_id,)).fetchone()[0]
    ack = "Thanks, noted." if not n else \
        f"Thanks. {n} item{'s that were' if n > 1 else ' that was'} waiting on this {'are' if n > 1 else 'is'} ready in your Inbox."
    _say(con, clock, "assistant", ack)


def _system(con, clock) -> str:
    now = local(clock.now())
    upcoming = [dict(r) for r in con.execute(
        "select title, due as at from deadlines where substr(due, 1, 10) between ? and ? "
        "union all select title, do_date from tasks where status = 'open' and do_date between ? and ? order by at limit 15",
        (now.date().isoformat(), (now.date() + timedelta(days=14)).isoformat()) * 2)]
    plan = "\n".join(f"- {u['at']}: {u['title']}" for u in upcoming) or "- nothing yet"
    return (f"You are Almanac, a personal assistant for a university student. Today is {now:%A, %B %d, %Y}, "
            f"{now:%H:%M} in Los Angeles. Be brief and warm. Never invent facts about their courses or dates; "
            f"if you don't know, ask.\n\nComing up in the next two weeks:\n{plan}")


# ---- HTTP --------------------------------------------------------------------

@router.get("")
def get_chat(request: Request):
    return state(request.app.state.db, request.app.state.clock)


@router.post("")
async def post(request: Request):
    s = request.app.state
    text = ((await request.json()).get("text") or "").strip()
    if not text:
        raise HTTPException(422, "empty message")
    cur = _current(s.db, s.clock)
    history = [{"role": r["role"], "content": r["text"]} for r in
               s.db.execute("select role, text from chat_messages order by id desc limit ?", (HISTORY,))][::-1]
    _say(s.db, s.clock, "user", text)
    if cur:
        _answer(s.db, s.clock, cur["question_id"], text)
    else:
        reply = s.llm.chat([{"role": "system", "content": _system(s.db, s.clock)}, *history,
                            {"role": "user", "content": text}], temperature=0.4, timeout=300)
        _say(s.db, s.clock, "assistant", reply.strip())
    return state(s.db, s.clock)


@router.post("/skip")
def skip(request: Request):
    s = request.app.state
    cur = _current(s.db, s.clock)
    if cur:
        with WRITE:
            s.db.execute("update questions set snoozed_until = ? where id = ?",
                         ((s.clock.now() + timedelta(days=1)).isoformat(timespec="seconds"), cur["question_id"]))
        _say(s.db, s.clock, "assistant", "No problem, I'll ask again tomorrow.")
    return state(s.db, s.clock)


@router.post("/dismiss")
def dismiss(request: Request):
    """Not relevant: drop the question and reject what was waiting on it."""
    s = request.app.state
    cur = _current(s.db, s.clock)
    if cur:
        with WRITE:
            s.db.execute("update questions set status = 'dismissed' where id = ?", (cur["question_id"],))
            n = s.db.execute("update proposals set status = 'rejected', decided_at = ? where question_id = ? and status = 'pending'",
                             (local(s.clock.now()).strftime("%Y-%m-%dT%H:%M"), cur["question_id"])).rowcount
        _say(s.db, s.clock, "assistant", "Got it, I'll drop that" + (f" and the {n} item{'s' if n > 1 else ''} that depended on it." if n else "."))
    return state(s.db, s.clock)


@router.get("/badge")
def badge(request: Request):
    return {"questions": len(_eligible(request.app.state.db, request.app.state.clock))}
