"""The database is read and written from many threads at once (requests, a chat
reply, background jobs): each gets its own connection, so reads don't mix."""
import threading

from app import db


def test_reads_on_many_threads_while_one_writes(tmp_path):
    con = db.connect(tmp_path / "a.db")
    con.execute("insert into sources (kind, title, text, created_at) values ('chat', 't', 'x', '2026-10-01')")
    errors, stop = [], threading.Event()

    def read():
        try:
            while not stop.is_set():
                for r in con.execute("select id from sources").fetchall():
                    row = con.execute("select * from sources where id = ?", (r["id"],)).fetchone()
                    assert row is None or row["text"] is not None
        except Exception as e:
            errors.append(e)

    readers = [threading.Thread(target=read) for _ in range(6)]
    for t in readers:
        t.start()
    for i in range(300):
        with db.WRITE:
            con.execute("insert into sources (kind, title, text, created_at) values ('chat', ?, 'x', '2026-10-01')", (str(i),))
    stop.set()
    for t in readers:
        t.join()
    assert errors == []
