"""Every change to the plan goes through plan.insert / change / remove, which
record history; ids are never reused."""
import json
import re
import sqlite3
from pathlib import Path

from app import db

APP = Path(__file__).resolve().parent.parent / "app"
PLAN_TABLES = r"(tasks|events|deadlines|projects|courses|goals|memories|terms)\b"
WRITES = re.compile(rf"(insert(\s+or\s+\w+)?\s+into|update|delete\s+from)\s+(\{{|{PLAN_TABLES})", re.I)
ALLOWED = {"plan.py", "db.py", "dev.py"}  # the gate, migrations, and the development Clear button


def test_nothing_writes_to_the_plan_outside_the_gate():
    offenders = [f"{p.name}:{n}" for p in APP.glob("*.py") if p.name not in ALLOWED
                 for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
                 if WRITES.search(line) and "proposals" not in line and "questions" not in line and "sources" not in line]
    assert offenders == []


def test_ids_are_never_reused(client):
    a = client.post("/api/tasks", json={"title": "A"}).json()
    client.delete(f"/api/tasks/{a['id']}")
    b = client.post("/api/tasks", json={"title": "B"}).json()
    assert b["id"] != a["id"]


def test_an_item_knows_the_proposal_and_quote_it_came_from(client):
    src = client.post("/api/sources", json={"kind": "document", "title": "cs239.pdf", "text": "x"}).json()
    p = client.post("/api/proposals", json={"source_id": src["id"], "summary": "Paper registration", "quote": "register by October 5",
                                             "ops": [{"op": "create", "kind": "deadlines", "data": {"title": "Paper registration", "due": "2026-10-05"}}]}).json()
    (dl_id,) = client.post(f"/api/proposals/{p['id']}/accept").json()["applied"]
    o = client.get(f"/api/deadlines/{dl_id}").json()["origin"]
    assert (o["id"], o["source"], o["quote"]) == (p["id"], "cs239.pdf", "register by October 5")
    mine = client.post("/api/tasks", json={"title": "By hand"}).json()
    assert client.get(f"/api/tasks/{mine['id']}").json()["origin"] is None


def test_undoing_a_proposal_reverses_exactly_its_changes(client):
    keep = client.post("/api/tasks", json={"title": "Keep", "due": "2026-10-05"}).json()
    p = client.post("/api/proposals", json={"summary": "Move and add", "ops": [
        {"op": "update", "kind": "tasks", "id": keep["id"], "data": {"due": "2026-10-09"}},
        {"op": "create", "kind": "tasks", "data": {"title": "New"}}]}).json()
    client.post(f"/api/proposals/{p['id']}/accept")
    from app import inbox
    inbox.withdraw(client.app.state.db, p["id"])
    assert [(t["title"], t["due"]) for t in client.get("/api/tasks").json()] == [("Keep", "2026-10-05")]


def test_an_old_database_is_migrated_keeping_ids_and_never_reusing_one(tmp_path):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript(db.SCHEMA.replace(" autoincrement", "").split("create table if not exists history")[0]
                      + "create table if not exists proposals (id integer primary key, source_id integer, question_id integer, "
                        "summary text not null, quote text, ops text not null, fingerprint text not null, status text not null default "
                        "'pending', applied text, created_at text not null, decided_at text);")
    old.execute("insert into deadlines (id, title, due) values (6, 'Kept', '2026-10-05')")
    old.execute("insert into proposals (id, summary, ops, fingerprint, status, applied, created_at) values "
                "(1, 'x', ?, 'f', 'accepted', '[7]', '2026-10-01')", (json.dumps([{"op": "create", "kind": "deadlines", "data": {"title": "Gone"}}]),))
    old.commit()
    old.close()
    con = db.connect(path)
    assert con.execute("select title from deadlines where id = 6").fetchone()[0] == "Kept"
    con.execute("insert into deadlines (title) values ('New')")
    assert con.execute("select id from deadlines where title = 'New'").fetchone()[0] == 8  # 7 was used by proposal 1
