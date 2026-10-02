from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import canvas, chat, checkins, db, dev, goals, inbox, ingest, note, overviews, plan, planner, push, recordings, scheduler, timers  # noqa: F401 (checkins registers jobs)
from .clock import SystemClock, local
from .config import DB_PATH, WEB_DIR
from .llm import DEFAULT_READER, Ollama
from .transcriber import Parakeet


def create_app(db_path: Path = DB_PATH, llm=None, clock=None, transcriber=None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app):
        # Real time only: tests move a fake clock and tick by hand.
        stop = scheduler.start(app.state) if isinstance(app.state.clock, SystemClock) else None
        yield
        if stop:
            stop.set()

    app = FastAPI(title="Almanac", lifespan=lifespan)
    con = db.connect(db_path)
    app.state.db = con
    app.state.db_path = Path(db_path)
    app.state.llm = llm or Ollama(lambda: db.settings(con))
    app.state.reader = llm or Ollama(lambda: db.settings(con), "reader_model", DEFAULT_READER)
    app.state.clock = clock or SystemClock()
    app.state.fetch = canvas.fetch_url  # tests swap in a fake feed
    app.state.transcriber = transcriber or Parakeet()  # speech to text for Recordings; tests use a fake
    app.state.live = {}  # running Recordings (recordings.Live)
    recordings.recover(con, app.state.db_path.parent / "recording-audio")

    @app.get("/api/version")
    def version(request: Request):
        """Changes whenever the plan, suggestions, questions, chat, documents or
        notifications do, so open pages know to redraw (a cheap poll)."""
        con = request.app.state.db
        parts = con.execute(
            "select (select coalesce(max(id), 0) from history), (select coalesce(max(id), 0) from proposals), "
            "(select count(*) from proposals where status = 'pending'), (select coalesce(max(id), 0) from questions), "
            "(select count(*) from questions where status = 'open'), (select coalesce(max(id), 0) from chat_messages), "
            "(select count(*) from chat_messages), (select coalesce(max(id), 0) from notifications), "
            "(select count(*) from sources where status = 'processing'), (select coalesce(max(id), 0) from sources)").fetchone()
        return {"v": "-".join(str(x) for x in parts)}

    @app.get("/api/health")
    def health(request: Request):
        s = request.app.state
        return {"ai": s.llm.status(), "now": local(s.clock.now()).isoformat()}

    @app.middleware("http")
    async def revalidate(request: Request, call_next):
        # Always revalidate the UI so a new version reaches every device at once.
        response = await call_next(request)
        if not request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    app.include_router(inbox.router)  # before plan's catch-all /api/{kind}
    app.include_router(ingest.router)
    app.include_router(chat.router)
    app.include_router(recordings.router)
    app.include_router(planner.router)
    app.include_router(goals.router)
    app.include_router(scheduler.router)
    app.include_router(timers.router)
    app.include_router(overviews.router)
    app.include_router(canvas.router)
    app.include_router(push.router)
    app.include_router(note.router)
    app.include_router(dev.router)  # development only
    app.include_router(plan.router)

    @app.get("/")
    def index():
        return FileResponse(WEB_DIR / "index.html")

    @app.get("/favicon.ico")
    def favicon():
        return FileResponse(WEB_DIR / "icons" / "almanac.ico", media_type="image/x-icon")

    @app.get("/sw.js")
    def service_worker():
        # at the root so its scope covers the whole app
        return FileResponse(WEB_DIR / "sw.js", media_type="text/javascript")

    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
    return app
