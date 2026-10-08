"""
App setup. Run locally with:

    uvicorn app.main:create_app --factory --port 8086

(--factory: the app is built at start-up, so importing this module in tests
never touches the real database.)

The database lives in DATA_DIR (default: the repo's data/ folder, which
.gitignore excludes). In Docker, DATA_DIR is the mounted NAS folder.
"""

import logging
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import clublog, db
from .api import router
from .reference import load_reference

log = logging.getLogger("dxcc")
DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
# Page URL -> HTML file.
PAGES = {"/": "entities.html", "/slots": "slots.html", "/matrix": "matrix.html",
         "/paper": "paper.html", "/import": "import.html", "/settings": "settings.html"}


def create_app(db_path=None, reference=None, clublog_fetch=None):
    app = FastAPI(title="N4MI DXCC Analyzer", docs_url=None, redoc_url=None)
    app.state.db_error = None
    app.state.reference = reference or load_reference()
    app.state.clublog_fetch = clublog_fetch or clublog.fetch_raw
    if db_path is None:
        env_dir = os.environ.get("DATA_DIR")
        data_dir = Path(env_dir or DEFAULT_DATA_DIR)
        if env_dir and not data_dir.is_dir():
            # In Docker the data folder is a mounted NAS folder. If it's missing,
            # the mount is wrong: say so instead of quietly starting with an
            # empty database inside the container.
            app.state.db_error = (f"Data folder {data_dir} not found. Check the volume "
                                  "mount in the stack's compose file.")
        else:
            data_dir.mkdir(parents=True, exist_ok=True)
        db_path = data_dir / "dxcc.db"
    app.state.db_path = str(db_path)
    if not app.state.db_error:
        # A damaged or unreadable database must not stop the app: /healthz stays
        # up, and /api/status and every page report the problem (spec 12).
        try:
            conn = db.connect(app.state.db_path)
            try:
                db.init(conn)
                unknown = db.stored_dxccs(conn) - set(app.state.reference.by_dxcc)
                if unknown:   # say so, never drop silently
                    log.warning("Stored data has DXCC numbers missing from the reference "
                                "table: %s", sorted(unknown))
            finally:
                conn.close()
        except Exception as exc:
            app.state.db_error = f"Database problem ({app.state.db_path}): {exc}"
    if app.state.db_error:
        log.error(app.state.db_error)
    app.include_router(router)
    for path, page in PAGES.items():
        app.add_api_route(path, lambda page=page: FileResponse(STATIC_DIR / page),
                          include_in_schema=False)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app

