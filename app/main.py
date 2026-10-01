from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import canvas, chat, checkins, db, goals, inbox, ingest, overviews, plan, planner, scheduler, timers  # noqa: F401 (checkins registers jobs)
from .clock import SystemClock, local
from .config import DB_PATH, WEB_DIR
from .llm import DEFAULT_READER, Ollama


def create_app(db_path: Path = DB_PATH, llm=None, clock=None) -> FastAPI:
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
    app.include_router(planner.router)
    app.include_router(goals.router)
    app.include_router(scheduler.router)
    app.include_router(timers.router)
    app.include_router(overviews.router)
    app.include_router(canvas.router)
    app.include_router(plan.router)

    @app.get("/")
    def index():
        return FileResponse(WEB_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
    return app
