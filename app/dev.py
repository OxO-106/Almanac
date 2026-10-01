"""Development only: clear everything to re-test reading documents from
scratch. Delete this file (and its router in main.py and the Settings card)
once the app settles."""

import shutil
import sqlite3
from datetime import datetime

from fastapi import APIRouter, Request

from .db import WRITE

router = APIRouter(prefix="/api/dev")

# Kept: push keys and devices (notifications keep working), the term calendar
# (seeded; week numbers and class times need it), scheduler state.
KEEP = {"settings", "push_subscriptions", "jobs", "terms", "notifications"}


@router.post("/clear-all")
def clear_all(request: Request):
    s = request.app.state
    con = s.db
    folder = s.db_path.parent
    backup = folder / "backups" / f"before-clear-{datetime.now():%Y%m%d-%H%M%S}.db"
    backup.parent.mkdir(exist_ok=True)
    with WRITE:
        out = sqlite3.connect(backup)
        con.backup(out)
        out.close()
        con.execute("pragma foreign_keys = off")
        tables = [r[0] for r in con.execute("select name from sqlite_master where type = 'table' and name not like 'sqlite_%'")]
        for t in tables:
            if t not in KEEP:
                con.execute(f"delete from {t}")
        # the newest notification stays, so ids keep counting up and devices
        # that remember the last one they showed don't miss new ones
        con.execute("delete from notifications where id < (select max(id) from notifications)")
        con.execute("delete from settings where key = 'canvas'")
        con.execute("pragma foreign_keys = on")
    shutil.rmtree(folder / "uploads", ignore_errors=True)
    return {"backup": backup.name}
