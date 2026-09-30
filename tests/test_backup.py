import sqlite3
from datetime import datetime, timedelta

from app.clock import LA


def test_a_nightly_backup_keeps_the_last_14(client, clock, tmp_path):
    client.post("/api/tasks", json={"title": "Keep me safe"})
    day = datetime(2026, 9, 1, 22, 0, tzinfo=LA)
    clock.set(day)
    client.post("/api/scheduler/tick")
    for i in range(20):
        clock.set(day + timedelta(days=i, minutes=45))
        client.post("/api/scheduler/tick")
    backups = sorted((tmp_path / "backups").glob("almanac-*.db"))
    assert len(backups) == 14
    assert backups[-1].name == "almanac-2026-09-20.db"
    rows = sqlite3.connect(backups[-1]).execute("select title from tasks").fetchall()
    assert rows == [("Keep me safe",)]
