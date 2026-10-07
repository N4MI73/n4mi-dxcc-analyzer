"""
Internal endpoints for the app's own pages (spec section 11).

These may change freely in Phase 1. The stable DXMon contract
(/api/v1/needs/...) is a separate Phase 2 design, documented in the brief
before DXMon depends on it, so a page redesign can never break DXMon.
"""

import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel

from . import analysis, clublog, db
from .categories import LABELS, MATRIX_CATEGORIES, MIXED, SAT, Profile
from .marks import Mark, check_mark
from .paper import PaperQSL, describe_entry, fills_in_profile, is_credited
from .parser import UploadError, parse_text, parse_upload
from .status_check import compare, parse_status
from .validate import HELD, REJECTED, validate

MAX_UPLOAD = 5 * 1024 * 1024
router = APIRouter()


def get_conn(request: Request):
    conn = db.connect(request.app.state.db_path)
    try:
        yield conn
    finally:
        conn.close()


def ref(request: Request):
    return request.app.state.reference


# ---------- shared view helpers ----------

def _rankings(conn):
    payload, fetched = db.get_external(conn, "clublog_most_wanted")
    return ({int(k): v for k, v in payload.items()} if payload else {}), fetched


def _entity(e, ranks):
    return {"dxcc": e.dxcc, "prefix": e.prefix, "name": e.lotw_name,
            "continent": e.continent, "cq_zone": e.cq_zone, "mw_rank": ranks.get(e.dxcc)}


class _Tags:
    """Pending marks and paper-card slots, looked up per entity."""

    def __init__(self, conn, credits, profile):
        self.marks, self.cards = {}, {}
        for mid, m in db.active_marks(conn):
            self.marks.setdefault(m.dxcc, {})[m.category] = {"id": mid, "state": m.state,
                                                             "note": m.note}
        for cid, c in db.active_cards(conn):
            for cat in fills_in_profile(c, credits, profile):
                self.cards.setdefault(c.dxcc, {}).setdefault(cat, []).append(
                    {"id": cid, "state": c.state})

    def of(self, dxcc):
        return {"marks": self.marks.get(dxcc, {}), "cards": self.cards.get(dxcc, {})}


def _context(conn):
    credits, snap = db.current_credits(conn)
    if snap is None:
        return None
    return credits, snap, db.get_profile(conn)


def _profile_json(p):
    return {"bands": list(p.bands), "modes": list(p.modes),
            "markable": list(p.markable_categories)}


def _snapshot_json(s):
    return {"id": s["id"], "imported_at": s["imported_at"], "saved_at": s["saved_at"],
            "source": s["source"], "callsign": s["callsign"], "status": s["status"],
            "rows_read": s["rows_read"], "warnings": json.loads(s["warnings"]),
            "totals": json.loads(s["totals_json"])}


NO_DATA = {"no_data": True, "message": "No import yet. Paste your LoTW Award Credit Matrix "
                                       "on the Import page."}


# ---------- health and status ----------

@router.get("/healthz")
def healthz():
    return {"status": "ok"}


@router.get("/api/status")
def status(request: Request):
    try:
        conn = db.connect(request.app.state.db_path)
        try:
            snap = db.current_snapshot(conn)
            credits = db.credits_of(conn, snap["id"]) if snap else {}
            check = db.latest_status_check(conn)
            _, mw_fetched = _rankings(conn)
            unknown = sorted(db.stored_dxccs(conn) - set(ref(request).by_dxcc))
        finally:
            conn.close()
    except Exception as exc:          # unreadable database: report it plainly
        return {"ok": False, "error": f"Database problem: {exc}"}
    out = {"ok": not unknown, "error": None, "callsign": snap["callsign"] if snap else None,
           "snapshot": ({"id": snap["id"], "imported_at": snap["imported_at"],
                         "saved_at": snap["saved_at"]} if snap else None),
           "entities_credited": sum(1 for c in credits.values() if MIXED in c),
           "most_wanted_fetched_at": mw_fetched, "last_status_check": None,
           "reference_problems": unknown}
    if unknown:
        out["error"] = ("Stored data has DXCC numbers the reference table doesn't know: "
                        f"{unknown}. The reference table may have been changed.")
    if check:
        r = json.loads(check["result_json"])
        out["last_status_check"] = {"checked_at": check["checked_at"],
                                    "snapshot_id": check["snapshot_id"],
                                    "reconciled": r["reconciled"],
                                    "pending_match": r["pending_match"]}
    return out


# ---------- import ----------

def _changes_json(ch, reference):
    name = lambda d: reference.by_dxcc[d].lotw_name  # noqa: E731
    return {"new_entities": [{"dxcc": d, "name": name(d)} for d in ch.new_entities],
            "new_slots": [{"dxcc": d, "name": name(d), "category": c} for d, c in ch.new_slots],
            "lost": [{"dxcc": d, "name": name(d), "category": c} for d, c in ch.lost]}


@router.post("/api/import/preview")
async def import_preview(request: Request, text: str | None = Form(None),
                         file: UploadFile | None = File(None), conn=Depends(get_conn)):
    reference = ref(request)
    if file is not None and file.filename:
        data = await file.read(MAX_UPLOAD + 1)
        if len(data) > MAX_UPLOAD:
            raise HTTPException(413, "The file is larger than 5 MB; that isn't a LoTW matrix.")
        try:
            parsed = parse_upload(file.filename, data)
        except UploadError as exc:
            raise HTTPException(422, str(exc))
        source = file.filename
    elif text:
        parsed, source = parse_text(text), "paste"
    else:
        raise HTTPException(422, "Paste the matrix or choose a file.")
    current, _ = db.current_credits(conn)
    res = validate(parsed, reference, current)
    out = {"status": res.status, "errors": res.errors, "warnings": res.warnings,
           "callsign": res.callsign, "rows_read": res.rows_read, "id": None}
    if res.status == REJECTED:
        return out                     # nothing stored
    profile = db.get_profile(conn)
    out["totals"] = res.totals
    out["summary"] = analysis.summarize(res.credits, reference, profile).__dict__
    out["changes"] = _changes_json(analysis.changes(current, res.credits, profile), reference)
    out["marks_to_clear"] = sum(1 for _, m in db.active_marks(conn)
                                if m.category in res.credits.get(m.dxcc, ()))
    out["cards_to_credit"] = sum(1 for _, c in db.active_cards(conn)
                                 if is_credited(c, res.credits))
    out["id"] = db.store_preview(conn, res, source, held=res.status == HELD)
    return out


class SaveBody(BaseModel):
    save_anyway: bool = False


@router.post("/api/import/{sid}/save")
def import_save(sid: int, body: SaveBody | None = None, conn=Depends(get_conn)):
    snap = db.get_snapshot(conn, sid)
    if snap is None or snap["status"] not in db.PENDING:
        raise HTTPException(404, "No import waiting with that id. Preview it again.")
    if snap["status"] == "held" and not (body and body.save_anyway):
        raise HTTPException(409, "This import was held for review. Check the warnings, then "
                                 "choose Save anyway.")
    cur = db.current_snapshot(conn)
    if (cur["id"] if cur else None) != snap["based_on"]:
        raise HTTPException(409, "The current data changed since this preview. Preview again.")
    cleared, credited = db.make_current(conn, sid)
    return {"saved": sid, "marks_cleared": cleared, "cards_credited": credited}


@router.post("/api/import/{sid}/discard")
def import_discard(sid: int, conn=Depends(get_conn)):
    db.discard(conn, sid)
    return {"discarded": sid}


# ---------- history and rollback ----------

@router.get("/api/snapshots")
def snapshots(conn=Depends(get_conn)):
    return {"snapshots": [_snapshot_json(s) for s in db.list_snapshots(conn)]}


@router.post("/api/snapshots/{sid}/make-current")
def snapshot_make_current(sid: int, conn=Depends(get_conn)):
    snap = db.get_snapshot(conn, sid)
    if snap is None or snap["status"] != "previous":
        raise HTTPException(409, "Only an earlier saved import can be made current.")
    cleared, credited = db.make_current(conn, sid)
    return {"current": sid, "marks_cleared": cleared, "cards_credited": credited}


@router.delete("/api/snapshots/{sid}")
def snapshot_delete(sid: int, conn=Depends(get_conn)):
    snap = db.get_snapshot(conn, sid)
    if snap is None:
        raise HTTPException(404, "No such import.")
    if snap["status"] == "current":
        raise HTTPException(409, "The current import can't be deleted.")
    db.delete_snapshot(conn, sid)
    return {"deleted": sid}


# ---------- views (profile applied here; filters in the browser) ----------

@router.get("/api/view/entities")
def view_entities(request: Request, conn=Depends(get_conn)):
    ctx = _context(conn)
    if ctx is None:
        return NO_DATA
    credits, snap, profile = ctx
    reference = ref(request)
    ranks, fetched = _rankings(conn)
    tags = _Tags(conn, credits, profile)
    sat_on = SAT in profile.modes
    rows = []
    for e in analysis.missing_entities(credits, reference):
        row = _entity(e, ranks) | tags.of(e.dxcc)
        # D44: show when a never-credited entity already has Satellite credit.
        row["sat_credited"] = (SAT in credits.get(e.dxcc, ())) if sat_on else None
        rows.append(row)
    # "Since last import": compare with the snapshot that was current when this
    # one was previewed (None on the first import, or if that one was deleted).
    since = None
    before = db.get_snapshot(conn, snap["based_on"]) if snap["based_on"] else None
    if before is not None:
        since = _changes_json(analysis.changes(db.credits_of(conn, before["id"]), credits,
                                               profile), reference)
        since["previous_saved_at"] = before["saved_at"] or before["imported_at"]
    return {"snapshot_id": snap["id"], "callsign": snap["callsign"],
            "imported_at": snap["imported_at"], "saved_at": snap["saved_at"],
            "profile": _profile_json(profile), "most_wanted_fetched_at": fetched,
            "summary": analysis.summarize(credits, reference, profile).__dict__,
            "since_last": since, "entities": rows}


@router.get("/api/view/slots")
def view_slots(request: Request, conn=Depends(get_conn)):
    ctx = _context(conn)
    if ctx is None:
        return NO_DATA
    credits, snap, profile = ctx
    reference = ref(request)
    ranks, _ = _rankings(conn)
    tags = _Tags(conn, credits, profile)
    needed = analysis.needed_slots(credits, reference, profile)
    sat = analysis.satellite_needs(credits, reference, profile)
    by_cat = analysis.slots_by_category(needed, profile, sat)
    cats = []
    for cat, dxccs in by_cat.items():
        ents = []
        for d in dxccs:
            e = reference.by_dxcc[d]
            ents.append(_entity(e, ranks) | tags.of(d) |
                        {"slots_needed": len(needed.get(d, ()))})
        cats.append({"category": cat, "label": LABELS[cat], "entities": ents})
    return {"snapshot_id": snap["id"], "callsign": snap["callsign"],
            "imported_at": snap["imported_at"], "saved_at": snap["saved_at"],
            "profile": _profile_json(profile),
            "summary": analysis.summarize(credits, reference, profile).__dict__,
            "categories": cats}


@router.get("/api/view/matrix")
def view_matrix(request: Request, conn=Depends(get_conn)):
    ctx = _context(conn)
    if ctx is None:
        return NO_DATA
    credits, snap, profile = ctx
    reference = ref(request)
    ranks, _ = _rankings(conn)
    tags = _Tags(conn, credits, profile)
    shown = (MIXED,) + profile.slot_categories
    rows = []
    for e in reference.current:
        have = credits.get(e.dxcc, frozenset())
        rows.append(_entity(e, ranks) | tags.of(e.dxcc) | {
            "credited": [c for c in MATRIX_CATEGORIES if c in have],
            "needed": [c for c in shown if c not in have]})
    return {"snapshot_id": snap["id"], "profile": _profile_json(profile),
            "columns": [{"category": c, "label": LABELS[c], "in_profile": c in shown}
                        for c in MATRIX_CATEGORIES],
            "entities": rows}


# ---------- settings ----------

class ProfileBody(BaseModel):
    bands: list[str]
    modes: list[str]


@router.get("/api/settings/profile")
def get_profile(conn=Depends(get_conn)):
    return _profile_json(db.get_profile(conn))


@router.put("/api/settings/profile")
def put_profile(body: ProfileBody, conn=Depends(get_conn)):
    try:
        p = Profile(bands=tuple(body.bands), modes=tuple(body.modes))
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    db.set_profile(conn, p)
    return _profile_json(p)


# ---------- pending marks ----------

class MarkBody(BaseModel):
    dxcc: int
    category: str
    state: str
    note: str = ""


class MarkPatch(BaseModel):
    state: str
    note: str = ""


@router.get("/api/marks")
def list_marks(conn=Depends(get_conn)):
    return {"marks": [{"id": i, **m.__dict__} for i, m in db.active_marks(conn)]}


@router.post("/api/marks")
def add_mark(request: Request, body: MarkBody, conn=Depends(get_conn)):
    credits, _ = db.current_credits(conn)
    mark = Mark(body.dxcc, body.category, body.state, body.note)
    problem = check_mark(mark, credits or {}, ref(request), db.get_profile(conn))
    if problem:
        raise HTTPException(422, problem)
    if any(m.dxcc == mark.dxcc and m.category == mark.category for _, m in db.active_marks(conn)):
        raise HTTPException(409, "That slot is already marked; change the existing mark.")
    return {"id": db.add_mark(conn, mark)}


@router.patch("/api/marks/{mid}")
def patch_mark(request: Request, mid: int, body: MarkPatch, conn=Depends(get_conn)):
    old = db.get_active_mark(conn, mid)
    if old is None:
        raise HTTPException(404, "No such active mark.")
    credits, _ = db.current_credits(conn)
    problem = check_mark(Mark(old.dxcc, old.category, body.state, body.note), credits or {},
                         ref(request), db.get_profile(conn))
    if problem:
        raise HTTPException(422, problem)
    db.update_mark(conn, mid, body.state, body.note)
    return {"id": mid}


@router.delete("/api/marks/{mid}")
def delete_mark(mid: int, conn=Depends(get_conn)):
    db.remove_mark(conn, mid)
    return {"removed": mid}


# ---------- paper QSL cards ----------

class CardBody(BaseModel):
    dxcc: int
    band: str | None = None
    mode: str
    state: str = "in_hand"
    call: str = ""
    qso_date: str = ""
    note: str = ""


class CardPatch(BaseModel):
    state: str
    note: str = ""


def _card_json(cid, c, credits, profile, reference):
    return {"id": cid, **c.__dict__, "name": reference.by_dxcc[c.dxcc].lotw_name,
            "prefix": reference.by_dxcc[c.dxcc].prefix,
            "fills": fills_in_profile(c, credits, profile)}


@router.get("/api/paper")
def list_cards(request: Request, conn=Depends(get_conn)):
    credits, _ = db.current_credits(conn)
    profile = db.get_profile(conn)
    return {"cards": [_card_json(i, c, credits or {}, profile, ref(request))
                      for i, c in db.active_cards(conn)]}


@router.post("/api/paper/preview")
def preview_card(request: Request, body: CardBody, conn=Depends(get_conn)):
    """What a card would fill, without saving it (the form's live preview)."""
    credits, _ = db.current_credits(conn)
    ok, message, slots = describe_entry(PaperQSL(**body.model_dump()), credits or {},
                                        db.get_profile(conn), ref(request))
    return {"ok": ok, "message": message, "fills": slots}


@router.post("/api/paper")
def add_card(request: Request, body: CardBody, conn=Depends(get_conn)):
    card = PaperQSL(**body.model_dump())
    credits, _ = db.current_credits(conn)
    ok, message, slots = describe_entry(card, credits or {}, db.get_profile(conn), ref(request))
    if not ok:
        raise HTTPException(422, message)
    return {"id": db.add_card(conn, card), "message": message, "fills": slots}


@router.patch("/api/paper/{cid}")
def patch_card(cid: int, body: CardPatch, conn=Depends(get_conn)):
    if db.get_active_card(conn, cid) is None:
        raise HTTPException(404, "No such card.")
    if body.state not in ("in_hand", "submitted"):
        raise HTTPException(422, f"Unknown card state {body.state!r}.")
    db.update_card(conn, cid, body.state, body.note)
    return {"id": cid}


@router.delete("/api/paper/{cid}")
def delete_card(cid: int, conn=Depends(get_conn)):
    db.delete_card(conn, cid)
    return {"deleted": cid}


# ---------- Account Status cross-check ----------

class TextBody(BaseModel):
    text: str


@router.post("/api/status-check")
def status_check(body: TextBody, conn=Depends(get_conn)):
    ctx = _context(conn)
    if ctx is None:
        raise HTTPException(409, "Import the matrix first; the check compares against it.")
    credits, snap, profile = ctx
    parsed = parse_status(body.text)
    if not parsed.ok:
        raise HTTPException(422, " ".join(parsed.errors))
    res = compare(parsed, credits, [m for _, m in db.active_marks(conn)], profile)
    line = lambda x: {"category": x.category, "label": LABELS[x.category],  # noqa: E731
                      "app": x.app, "lotw": x.lotw, "ok": x.ok}
    out = {"snapshot_id": snap["id"], "reconciled": res.reconciled,
           "pending_match": res.pending_match,
           "reconciliation": [line(x) for x in res.reconciliation],
           "pending": [line(x) for x in res.pending],
           "not_checked": res.not_checked}
    db.add_status_check(conn, snap["id"], out)
    return out


# ---------- Club Log Most Wanted ----------

@router.post("/api/clublog/refresh")
def clublog_refresh(request: Request, conn=Depends(get_conn)):
    try:
        ranks = clublog.fetch_rankings(ref(request), request.app.state.clublog_fetch)
    except clublog.ClubLogError as exc:
        _, fetched = _rankings(conn)
        raise HTTPException(502, f"{exc} Keeping the previous list"
                                 f"{' from ' + fetched if fetched else ' (none yet)'}.")
    db.set_external(conn, "clublog_most_wanted", {str(k): v for k, v in ranks.items()})
    _, fetched = _rankings(conn)
    return {"entities_ranked": len(ranks), "fetched_at": fetched}
