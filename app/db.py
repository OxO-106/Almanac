"""SQLite store. Tables are created on open; later tickets add theirs here."""

import json
import sqlite3
import threading
from pathlib import Path

# Plan times are local Los Angeles wall-clock strings ("2026-10-05" or
# "2026-10-05T16:00"), not UTC: a 4pm class must stay 4pm across DST.
SCHEMA = """
create table if not exists settings (key text primary key, value text not null);
create table if not exists courses (
  id integer primary key, number text not null, instructor text not null, title text, color text);
create table if not exists goals (
  id integer primary key, title text not null, why text, horizon text, status text not null default 'active');
create table if not exists projects (
  id integer primary key, title text not null, goal_id integer references goals on delete set null,
  course_id integer references courses on delete set null, deadline text, team integer not null default 0,
  status text not null default 'active', notes text);
create table if not exists tasks (
  id integer primary key, title text not null, project_id integer references projects on delete set null,
  course_id integer references courses on delete set null, due text, do_date text, work_kind text, size real,
  estimate_min integer, status text not null default 'open', done_at text, notes text,
  provisional integer not null default 0);
create table if not exists events (
  id integer primary key, title text not null, course_id integer references courses on delete set null,
  start text not null, end text, repeat text, until text, location text, provisional integer not null default 0);
create table if not exists deadlines (
  id integer primary key, title text not null, course_id integer references courses on delete set null,
  project_id integer references projects on delete set null, due text, provisional integer not null default 0);
create table if not exists terms (
  id integer primary key, name text not null, starts text not null, instruction_begins text not null,
  week1 text not null, instruction_ends text not null, finals_start text, ends text not null, holidays text not null default '');
create table if not exists sources (
  id integer primary key, kind text not null, title text not null, text text not null default '', created_at text not null);
create table if not exists questions (
  id integer primary key, source_id integer references sources on delete set null, text text not null, quote text,
  answer text, status text not null default 'open', created_at text not null, answered_at text);
create table if not exists memories (
  id integer primary key, text text not null, topic text);
create table if not exists sessions (id integer primary key, task_id integer not null references tasks on delete cascade,
  started_at text not null, ended_at text, minutes integer, asked_at text, confirmed_at text);
create table if not exists overviews (id integer primary key, kind text not null, period_start text not null,
  period_end text not null, data text not null, created_at text not null, unique (kind, period_start));
create table if not exists jobs (name text primary key, last_run text not null);
create table if not exists notifications (id integer primary key, kind text not null, title text not null, body text,
  url text, created_at text not null);
create table if not exists briefings (date text primary key, data text not null);
create table if not exists catchup (id integer primary key, text text not null, consumed integer not null default 0);
create table if not exists chat_summaries (id integer primary key, upto integer not null, text text not null, created_at text not null);
create table if not exists chat_messages (
  id integer primary key, role text not null, text text not null, question_id integer references questions on delete set null,
  quote text, created_at text not null);
create table if not exists proposals (
  id integer primary key, source_id integer references sources on delete set null,
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
    ("events", "skip", "text"),  # comma-separated dates a recurring event doesn't happen
    ("questions", "snoozed_until", "text"),
    ("projects", "slips", "integer not null default 0"),  # times a Replan was needed  # UTC; "skip for now" in chat
    # "2026-10-26/2026-10-30": the source gives only this range (e.g. "Week 5");
    # the item's date field then holds the range start.
    ("tasks", "window", "text"),
    ("deadlines", "window", "text"),
    ("events", "window", "text"),
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
    if not con.execute("select 1 from terms").fetchone():
        con.executemany("insert into terms (name, starts, instruction_begins, week1, instruction_ends, finals_start, ends,"
                        " holidays) values (?,?,?,?,?,?,?,?)", TERMS)
    return con


def settings(con: sqlite3.Connection) -> dict:
    return {r["key"]: json.loads(r["value"]) for r in con.execute("select key, value from settings")}
