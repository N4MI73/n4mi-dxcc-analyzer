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
from datetime import date
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from . import advisor, clublog, db, dxmon, guide
from .api import router
from .reference import load_reference

log = logging.getLogger("dxcc")
DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
# Page URL -> HTML file.
PAGES = {"/": "entities.html", "/slots": "slots.html", "/matrix": "matrix.html",
         "/advisor": "advisor.html", "/paper": "paper.html", "/import": "import.html",
         "/settings": "settings.html", "/entity": "entity.html"}


def _page_endpoint(file_path):
    """A route for one fixed HTML page. The endpoint takes NO parameters: an
    earlier version used `lambda page=page: ...`, and FastAPI exposed that
    default argument as a `?page=` query parameter, so a caller could choose any
    readable file (security review DXCC-01, 2026-10-21)."""
    def endpoint():
        return FileResponse(file_path)
    return endpoint


def _help_endpoint(html):
    """The Help page, rendered once at start-up. No parameters (see above)."""
    def endpoint():
        return HTMLResponse(html)
    return endpoint


def create_app(db_path=None, reference=None, clublog_fetch=None, dxmon_fetch=None,
               today=None, guide_path=None):
    app = FastAPI(title="N4MI DXCC Analyzer", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.db_error = None
    app.state.reference = reference or load_reference()
    app.state.clublog_fetch = clublog_fetch or clublog.fetch_raw
    app.state.dxmon_fetch = dxmon_fetch or dxmon.fetch_raw
    app.state.today = today or date.today   # injectable for tests
    # The tested ADXO alias list; a row naming a non-current entity stops
    # start-up loudly rather than mis-tagging a DXpedition later.
    app.state.adxo_builtin = dxmon.load_builtin_aliases(app.state.reference)
    # HamAlert's entity spellings (D55): ADIF names plus a tested override list;
    # a bad row or a duplicate name stops start-up for the same reason.
    app.state.hamalert_names = advisor.Names(app.state.reference,
                                             advisor.load_overrides(app.state.reference))
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
        app.add_api_route(path, _page_endpoint(STATIC_DIR / page), include_in_schema=False)
    # The user guide (D58): User_Guide.md rendered once; its screenshots are
    # served from images/. A missing folder only loses the pictures (404),
    # never start-up.
    app.state.guide = guide.render(guide_path or guide.GUIDE_PATH)
    if app.state.guide.error:
        log.warning(app.state.guide.error)
    help_html = guide.page((STATIC_DIR / "help.html").read_text(encoding="utf-8"), app.state.guide)
    app.add_api_route("/help", _help_endpoint(help_html), include_in_schema=False)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    if guide.IMAGES_DIR.is_dir():
        app.mount("/images", StaticFiles(directory=guide.IMAGES_DIR), name="images")
    return app

