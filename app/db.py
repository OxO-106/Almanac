"""SQLite store. Tables are created on open; later tickets add theirs here."""

import json
import re
import sqlite3
import threading
from pathlib import Path

# Plan times are local Los Angeles wall-clock strings ("2026-10-05" or
# "2026-10-05T16:00"), not UTC: a 4pm class must stay 4pm across DST.
SCHEMA = """
create table if not exists settings (key text primary key, value text not null);
create table if not exists courses (
  id integer primary key autoincrement, number text not null, instructor text not null, title text, color text);
create table if not exists goals (
  id integer primary key autoincrement, title text not null, why text, horizon text, status text not null default 'active');
create table if not exists projects (
  id integer primary key autoincrement, title text not null, goal_id integer references goals on delete set null,
  course_id integer references courses on delete set null, deadline text, team integer not null default 0,
  status text not null default 'active', notes text);
create table if not exists tasks (
  id integer primary key autoincrement, title text not null, project_id integer references projects on delete set null,
  course_id integer references courses on delete set null, due text, do_date text, work_kind text, size real,
  estimate_min integer, status text not null default 'open', done_at text, notes text,
  provisional integer not null default 0);
create table if not exists events (
  id integer primary key autoincrement, title text not null, course_id integer references courses on delete set null,
  start text not null, end text, repeat text, until text, location text, provisional integer not null default 0);
create table if not exists deadlines (
  id integer primary key autoincrement, title text not null, course_id integer references courses on delete set null,
  project_id integer references projects on delete set null, due text, provisional integer not null default 0);
create table if not exists terms (
  id integer primary key autoincrement, name text not null, starts text not null, instruction_begins text not null,
  week1 text not null, instruction_ends text not null, finals_start text, ends text not null, holidays text not null default '');
create table if not exists sources (
  id integer primary key autoincrement, kind text not null, title text not null, text text not null default '', created_at text not null);
create table if not exists questions (
  id integer primary key autoincrement, source_id integer references sources on delete set null, text text not null, quote text,
  answer text, status text not null default 'open', created_at text not null, answered_at text);
create table if not exists memories (
  id integer primary key autoincrement, text text not null, topic text);
create table if not exists sessions (id integer primary key autoincrement, task_id integer not null references tasks on delete cascade,
  started_at text not null, ended_at text, minutes integer, asked_at text, confirmed_at text);
create table if not exists overviews (id integer primary key autoincrement, kind text not null, period_start text not null,
  period_end text not null, data text not null, created_at text not null, unique (kind, period_start));
create table if not exists canvas_sections (code text primary key, course_id integer references courses on delete cascade);
create table if not exists canvas_items (uid text primary key, proposal_id integer, entity_kind text, entity_id integer,
  gone integer not null default 0);
create table if not exists push_subscriptions (endpoint text primary key, p256dh text not null, auth text not null,
  contact text not null);
create table if not exists notes (date text primary key, headline text not null, body text not null, written_by text not null);
create table if not exists jobs (name text primary key, last_run text not null);
create table if not exists notifications (id integer primary key autoincrement, kind text not null, title text not null, body text,
  url text, created_at text not null);
create table if not exists briefings (date text primary key, data text not null);
create table if not exists catchup (id integer primary key autoincrement, text text not null, consumed integer not null default 0);
-- A lecture Recording (app/recordings.py). Its audio is a temporary file, never a column;
-- `pending` holds the uncleaned text only between transcription and clean-up (ADR 0001).
create table if not exists recordings (
  id integer primary key autoincrement, source_id integer references sources on delete set null,
  course_id integer references courses on delete set null, date text not null, kind text,
  status text not null, error text, seconds real, pending text, transcript text, jottings text,
  created_at text not null);
create table if not exists chat_summaries (id integer primary key autoincrement, upto integer not null, text text not null, created_at text not null);
create table if not exists chat_messages (
  id integer primary key autoincrement, role text not null, text text not null, question_id integer references questions on delete set null,
  quote text, created_at text not null);
create table if not exists history (
  id integer primary key autoincrement, kind text not null, item_id integer not null, op text not null,
  proposal_id integer, before text, after text, at text not null);
create index if not exists history_item on history (kind, item_id);
create index if not exists history_proposal on history (proposal_id);
create table if not exists proposals (
  id integer primary key autoincrement, source_id integer references sources on delete set null,
  question_id integer references questions on delete set null, summary text not null, quote text,
  ops text not null, fingerprint text not null, status text not null default 'pending',
  applied text, created_at text not null, decided_at text);
"""


# Columns added after a table first shipped: (table, column, declaration).
COLUMNS = [
    ("sources", "status", "text not null default 'done'"),
    ("sources", "error", "text"),
    ("sources", "dropped", "text"),
    # Versions of one document: `lineage` is the first version's id;
    # `replaced_by` marks an old version.
    ("sources", "lineage", "integer"),
    ("sources", "replaced_by", "integer"),
    ("sources", "about", "text"),
    ("questions", "meta", "text"),
    ("chat_messages", "proposals", "text"),
    ("notes", "facts", "text"),  # hash of the facts a note was written from  # JSON ids of suggestions a message presents  # JSON for questions whose answer code acts on, e.g. a Canvas section  # the course(s) a document is for, e.g. "COM SCI 269: Advanced Topics in AI"
    ("events", "skip", "text"),  # comma-separated dates a recurring event doesn't happen
    ("questions", "snoozed_until", "text"),
    ("projects", "slips", "integer not null default 0"),  # times a Replan was needed  # UTC; "skip for now" in chat
    # "2026-10-26/2026-10-30": the source gives only this range (e.g. "Week 5");
    # the item's date field then holds the range start.
    ("tasks", "window", "text"),
    ("deadlines", "window", "text"),
    ("events", "window", "text"),
    # Rewind: what accepting a proposal replaced (JSON, one entry per op), and
    # what a chat message changed, so both can be undone.
    ("proposals", "undo", "text"),
    ("chat_messages", "effects", "text"),
    # What a question is for (date, instructor, meeting, choice, section, other),
    # what its answer acts on, and the answers to offer as buttons. See questions.py.
    ("proposals", "optional", "integer not null default 0"),  # offered unticked (office hours)
    ("questions", "purpose", "text"),
    ("questions", "target", "text"),
    ("questions", "options", "text"),
    ("sources", "url", "text"),  # a course website read from its address (pages.py)
]

# UCLA Registrar, Annual Academic Calendar 2026-27. Week 1 is the first Monday
# of instruction (Fall's Thursday start makes Sep 24-25 "week 0").
TERMS = [
    ("Fall 2026", "2026-09-21", "2026-09-24", "2026-09-28", "2026-12-04", "2026-12-05", "2026-12-11",
     "2026-11-11 Veterans Day\n2026-11-26 Thanksgiving\n2026-11-27 Thanksgiving"),
    ("Winter 2027", "2027-01-04", "2027-01-04", "2027-01-04", "2027-03-12", "2027-03-13", "2027-03-19",
     "2027-01-18 Martin Luther King, Jr. Day\n2027-02-15 Presidents' Day"),
    ("Spring 2027", "2027-03-24", "2027-03-29", "2027-03-29", "2027-06-04", "2027-06-05", "2027-06-11",
     "2027-03-26 César Chávez Day\n2027-05-31 Memorial Day"),
]

# One connection is shared by the request thread pool and background jobs, so
# every write (and every multi-statement transaction) holds this lock.
WRITE = threading.RLock()


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("pragma foreign_keys = on")
    con.execute("pragma journal_mode = wal")
    con.executescript(SCHEMA)
    for table, column, decl in COLUMNS:
        if column not in {r["name"] for r in con.execute(f"pragma table_info({table})")}:
            con.execute(f"alter table {table} add column {column} {decl}")
    _stable_ids(con)
    _backfill_history(con)
    _question_purposes(con)
    if not con.execute("select 1 from terms").fetchone():
        con.executemany("insert into terms (name, starts, instruction_begins, week1, instruction_ends, finals_start, ends,"
                        " holidays) values (?,?,?,?,?,?,?,?)", TERMS)
    return con


def _stable_ids(con):
    """Rebuild tables made before ids were stable (plain `integer primary key`
    hands a deleted id out again), keeping every id. The counter starts past
    any id a proposal ever created, so an id that was used is never reused."""
    old = con.execute("select name, sql from sqlite_master where type = 'table' and sql like '%id integer primary key%' "
                      "and sql not like '%autoincrement%'").fetchall()
    if not old:
        return
    con.execute("pragma foreign_keys = off")
    con.execute("pragma legacy_alter_table = on")
    con.execute("begin")
    try:
        for name, sql in old:
            new = re.sub(r"id integer primary key(?! autoincrement)", "id integer primary key autoincrement", sql, count=1)
            new = re.sub(r"^CREATE TABLE\s+\"?\w+\"?", f"CREATE TABLE _{name}_new", new, count=1, flags=re.I)
            con.execute(new)
            con.execute(f"insert into _{name}_new select * from {name}")
            con.execute(f"drop table {name}")
            con.execute(f"alter table _{name}_new rename to {name}")
        used = {}
        for ops, applied in con.execute("select ops, applied from proposals where applied is not null"):
            for o, ref in zip(json.loads(ops), json.loads(applied)):
                if isinstance(ref, int):
                    used[o["kind"]] = max(used.get(o["kind"], 0), ref)
        for kind, top in used.items():
            con.execute("update sqlite_sequence set seq = max(seq, ?) where name = ?", (top, kind))
            con.execute("insert into sqlite_sequence (name, seq) select ?, ? where not exists "
                        "(select 1 from sqlite_sequence where name = ?)", (kind, top, kind))
        con.execute("commit")
    except Exception:
        con.execute("rollback")
        raise
    finally:
        con.execute("pragma legacy_alter_table = off")
        con.execute("pragma foreign_keys = on")
    con.executescript(SCHEMA)  # indexes on the rebuilt tables


def _backfill_history(con):
    """Items accepted before history was kept get their origin: the proposal
    that created them (when the row is still there)."""
    if con.execute("select 1 from history limit 1").fetchone():
        return
    rows = con.execute("select id, ops, applied, undo, decided_at from proposals where status = 'accepted' and applied is not null").fetchall()
    with WRITE:
        for pid, ops, applied, undo, at in rows:
            undo = json.loads(undo) if undo else []
            for i, (o, ref) in enumerate(zip(json.loads(ops), json.loads(applied))):
                if o["op"] == "create" and con.execute(f"select 1 from {o['kind']} where id = ?", (ref,)).fetchone():
                    con.execute("insert into history (kind, item_id, op, proposal_id, at) values (?,?,?,?,?)",
                                (o["kind"], ref, "create", pid, at or ""))
                elif o["op"] in ("update", "delete") and i < len(undo) and undo[i]:
                    con.execute("insert into history (kind, item_id, op, proposal_id, before, at) values (?,?,?,?,?,?)",
                                (o["kind"], ref, o["op"], pid, json.dumps(undo[i]), at or ""))


def _question_purposes(con):
    """Questions asked before they knew what they were for: from their old
    links (meta) and their wording."""
    rows = con.execute("select id, text, meta from questions where purpose is null").fetchall()
    with WRITE:
        for qid, text, meta in rows:
            meta = json.loads(meta) if meta else {}
            held = [r[0] for r in con.execute("select id from proposals where question_id = ?", (qid,))]
            purpose, target, options = "other", {"proposals": held + meta.get("fills", [])}, None
            if meta.get("type") == "canvas_section":
                purpose, target = "section", {"code": meta["code"], "courses": meta["courses"]}
                options = [f"{r[0]} · {r[1]}" for r in con.execute(
                    f"select number, instructor from courses where id in ({','.join('?' * len(meta['courses']))})", meta["courses"])]
            elif text.startswith("Who teaches"):
                purpose = "instructor"
            elif text.startswith(("When is “", "Which day in Week")) or meta.get("fills"):
                purpose = "date"
            con.execute("update questions set purpose = ?, target = ?, options = ? where id = ?",
                        (purpose, json.dumps(target), json.dumps(options) if options else None, qid))


def settings(con: sqlite3.Connection) -> dict:
    return {r["key"]: json.loads(r["value"]) for r in con.execute("select key, value from settings")}
