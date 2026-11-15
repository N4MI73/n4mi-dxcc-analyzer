"""
Internal endpoints for the app's own pages (spec section 11).

These may change freely in Phase 1. The stable DXMon contract
(/api/v1/needs/...) is a separate Phase 2 design, documented in the brief
before DXMon depends on it, so a page redesign can never break DXMon.
"""

import json
from collections import Counter
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from . import advisor, analysis, clublog, db, dxmon, exports
from .categories import LABELS, MATRIX_CATEGORIES, MIXED, SAT, Profile
from .marks import AWAITING, Mark, check_mark
from .paper import PaperQSL, describe_entry, fills_in_profile, is_credited
from .parser import UploadError, parse_text, parse_upload
from .status_check import compare, parse_status
from .validate import HELD, REJECTED, validate
from .version import VERSION

MAX_UPLOAD = 5 * 1024 * 1024
router = APIRouter()


MAX_PASTE = 2_000_000          # a real matrix paste is about 40 kB
NOTE, CALL, DATE = 500, 20, 20  # length limits for user-typed fields


def get_conn(request: Request):
    # A database problem found at start-up is reported, not crashed on (spec 12).
    if request.app.state.db_error:
        raise HTTPException(503, request.app.state.db_error)
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
    if request.app.state.db_error:
        return {"ok": False, "error": request.app.state.db_error, "version": VERSION}
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
        return {"ok": False, "error": f"Database problem: {exc}", "version": VERSION}
    out = {"ok": not unknown, "error": None, "callsign": snap["callsign"] if snap else None,
           "snapshot": ({"id": snap["id"], "imported_at": snap["imported_at"],
                         "saved_at": snap["saved_at"]} if snap else None),
           "entities_credited": sum(1 for c in credits.values() if MIXED in c),
           "most_wanted_fetched_at": mw_fetched, "last_status_check": None,
           "reference_problems": unknown, "version": VERSION}
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
    name = reference.name_of
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
        if len(text) > MAX_PASTE:
            raise HTTPException(413, "That paste is far larger than a LoTW matrix.")
        parsed, source = parse_text(text), "paste"
    else:
        raise HTTPException(422, "Paste the matrix or choose a file.")
    current, cur_snap = db.current_credits(conn)
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
    out["id"] = db.store_preview(conn, res, source, held=res.status == HELD,
                                 based_on=cur_snap["id"] if cur_snap else None)
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
    try:
        cleared, credited = db.make_current(conn, sid, allowed=db.PENDING,
                                            expect_current=snap["based_on"])
    except db.NotPromotable as exc:
        raise HTTPException(409, str(exc))
    return {"saved": sid, "marks_cleared": cleared, "cards_credited": credited}


@router.post("/api/import/{sid}/discard")
def import_discard(sid: int, conn=Depends(get_conn)):
    db.discard(conn, sid)
    return {"discarded": sid}


# ---------- history and rollback ----------

@router.get("/api/snapshots")
def snapshots(request: Request, conn=Depends(get_conn)):
    reference = ref(request)
    out = []
    for s in db.list_snapshots(conn):
        j = _snapshot_json(s)
        # Marks this import cleared (spec 5.4): a rollback doesn't restore them,
        # so the history shows them for re-marking if needed.
        j["cleared_marks"] = [{"name": reference.name_of(r["dxcc"]), "category": r["category"],
                               "label": LABELS.get(r["category"], r["category"])}
                              for r in db.cleared_marks(conn, s["id"])]
        out.append(j)
    return {"snapshots": out}


@router.post("/api/snapshots/{sid}/make-current")
def snapshot_make_current(sid: int, conn=Depends(get_conn)):
    snap = db.get_snapshot(conn, sid)
    if snap is None or snap["status"] != "previous":
        raise HTTPException(409, "Only an earlier saved import can be made current.")
    try:
        cleared, credited = db.make_current(conn, sid, allowed=("previous",))
    except db.NotPromotable as exc:
        raise HTTPException(409, str(exc))
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
        row["credited"] = sorted(credits.get(e.dxcc, ()))   # for the mark menu
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
    # Award view (D51): never-credited entities are in every list, flagged "new".
    needed = analysis.needed_slots(credits, reference, profile, include_new=True)
    sat = analysis.satellite_needs(credits, reference, profile)
    by_cat = analysis.slots_by_category(needed, profile, sat)
    cats = []
    for cat, dxccs in by_cat.items():
        ents = []
        for d in dxccs:
            e = reference.by_dxcc[d]
            ents.append(_entity(e, ranks) | tags.of(d) |
                        {"slots_needed": len(needed.get(d, ())),
                         "new": MIXED not in credits.get(d, ()),
                         "credited": sorted(credits.get(d, ()))})
        new_n = sum(1 for x in ents if x["new"])
        cats.append({"category": cat, "label": LABELS[cat], "entities": ents,
                     "confirmed_count": len(ents) - new_n, "new_count": new_n})
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
            "needed": [c for c in shown if c not in have],
            "new": MIXED not in have})
    return {"snapshot_id": snap["id"], "callsign": snap["callsign"],
            "imported_at": snap["imported_at"], "saved_at": snap["saved_at"],
            "profile": _profile_json(profile),
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
    category: str = Field(max_length=10)
    state: str = Field(max_length=20)
    note: str = Field("", max_length=NOTE)


class MarkPatch(BaseModel):
    state: str = Field(max_length=20)
    note: str = Field("", max_length=NOTE)


@router.get("/api/marks")
def list_marks(request: Request, conn=Depends(get_conn)):
    reference = ref(request)
    return {"marks": [{"id": i, **m.__dict__, "name": reference.name_of(m.dxcc),
                       "prefix": reference.prefix_of(m.dxcc)} for i, m in db.active_marks(conn)]}


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
    band: str | None = Field(None, max_length=10)
    mode: str = Field(max_length=10)
    state: str = Field("in_hand", max_length=20)
    call: str = Field("", max_length=CALL)
    qso_date: str = Field("", max_length=DATE)
    note: str = Field("", max_length=NOTE)


class CardPatch(BaseModel):
    state: str = Field(max_length=20)
    note: str = Field("", max_length=NOTE)


def _card_json(cid, c, credits, profile, reference):
    return {"id": cid, **c.__dict__, "name": reference.name_of(c.dxcc),
            "prefix": reference.prefix_of(c.dxcc),
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
    text: str = Field(max_length=200_000)


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


@router.get("/api/status-check/latest")
def status_check_latest(conn=Depends(get_conn)):
    """The most recent Account Status check, as returned when it was run."""
    row = db.latest_status_check(conn)
    if row is None:
        return {"none": True}
    cur = db.current_snapshot(conn)
    out = json.loads(row["result_json"])
    # The LoTW pending numbers are as of the check; the marks side is recounted
    # now, so marking a slot (e.g. Won't submit) updates the banner at once
    # without re-running the check (raised by Dan 2026-10-13).
    counts = Counter(m.category for _, m in db.active_marks(conn))
    for x in out.get("pending", []):
        x["app"] = counts.get(x["category"], 0)
        x["ok"] = x["app"] == x["lotw"]
    out["pending_match"] = all(x["ok"] for x in out.get("pending", []))
    return out | {
        "checked_at": row["checked_at"], "marks_recounted": True,
        "is_current_import": bool(cur and cur["id"] == row["snapshot_id"])}


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


# ---------- DX Monitor DXpeditions (D54; optional) ----------

class DXMonURLBody(BaseModel):
    url: str = Field("", max_length=200)


class ADXONameBody(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    dxcc: int | None = None       # None = Ignore


def _dxmon_try(request, conn, url):
    """One fetch attempt; stores the result, or keeps the last good copy."""
    try:
        data = dxmon.fetch(url, request.app.state.dxmon_fetch)
    except dxmon.DXMonError as exc:
        db.set_external(conn, "dxmon_attempt", {"ok": False, "error": str(exc), "url": url})
        return False
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if data["needed"] is not None:
        data["needed_fetched_at"] = now
    else:
        # Only the Needed list failed: keep the last good one from this address
        # (with its time) rather than lose every "already in DX Monitor" tag.
        old, _ = db.get_external(conn, "dxmon")
        if old and old.get("url") == url and old.get("needed") is not None:
            data["needed"] = old["needed"]
            data["needed_skipped"] = old.get("needed_skipped", 0)
            data["needed_fetched_at"] = old.get("needed_fetched_at")
        else:
            data["needed_fetched_at"] = None
    db.set_external(conn, "dxmon", data | {"url": url})
    db.set_external(conn, "dxmon_attempt", {"ok": True, "error": None, "url": url})
    return True


def _age_min(stamp):
    if not stamp:
        return None
    return (datetime.now(timezone.utc) - datetime.fromisoformat(stamp)).total_seconds() / 60


def _matcher(request, conn):
    decisions = {d["name_norm"]: d["dxcc"] for d in db.adxo_decisions(conn)}
    return dxmon.Matcher(ref(request), request.app.state.adxo_builtin, decisions)


def _dxmon_view(request, conn, auto=True):
    url = db.get_setting(conn, "dxmon_url", "")
    if not url:
        return {"enabled": False}
    attempt, tried_at = db.get_external(conn, "dxmon_attempt")
    if auto and (attempt is None or attempt.get("url") != url
                 or _age_min(tried_at) >= dxmon.AUTO_REFRESH_MIN):
        _dxmon_try(request, conn, url)
        attempt, tried_at = db.get_external(conn, "dxmon_attempt")
    cache, fetched_at = db.get_external(conn, "dxmon")
    if cache and cache.get("url") != url:
        cache = None            # a list from a different address is not this one's
    reference = ref(request)
    entity = lambda d: reference.by_dxcc[d]  # noqa: E731
    out = {"enabled": True, "url": url, "tried_at": tried_at,
           "ok": bool(attempt and attempt["ok"]),
           "error": attempt["error"] if attempt else None,
           "fetched_at": fetched_at if cache else None,
           "adxo_updated": cache["adxo_updated"] if cache else None,
           "entry_count": len(cache["entries"]) if cache else 0,
           "watched_count": len(cache["watched"]) if cache else 0,
           "skipped": cache.get("skipped", 0) if cache else 0,
           "decisions": [{"name": d["adxo_name"], "name_norm": d["name_norm"],
                          "dxcc": d["dxcc"],
                          "entity": entity(d["dxcc"]).lotw_name if d["dxcc"] else None,
                          "decided_at": d["decided_at"]}
                         for d in db.adxo_decisions(conn)]}
    if cache:
        credits, _ = db.current_credits(conn)
        needed = ({e.dxcc for e in analysis.missing_entities(credits, reference)}
                  if credits is not None else set())
        out |= dxmon.build(cache, _matcher(request, conn), needed, request.app.state.today())
    return out


@router.get("/api/dxmon")
def dxmon_view(request: Request, auto: bool = True, conn=Depends(get_conn)):
    """DXpedition tags for Missing Entities. Refreshes from DX Monitor when the
    last try is over 15 minutes old; otherwise answers from the stored copy.
    Settings asks with auto=false, so it never waits on DX Monitor."""
    return _dxmon_view(request, conn, auto=auto)


@router.post("/api/dxmon/refresh")
def dxmon_refresh(request: Request, conn=Depends(get_conn)):
    url = db.get_setting(conn, "dxmon_url", "")
    if not url:
        raise HTTPException(409, "DX Monitor is off. Enter its address in Settings first.")
    _dxmon_try(request, conn, url)
    return _dxmon_view(request, conn, auto=False)


@router.post("/api/dxmon/test")
def dxmon_test(request: Request, body: DXMonURLBody):
    """Try an address without saving it."""
    try:
        url = dxmon.check_url(body.url)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    if not url:
        raise HTTPException(422, "Enter DX Monitor's address to test it.")
    try:
        data = dxmon.fetch(url, request.app.state.dxmon_fetch)
    except dxmon.DXMonError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "entry_count": len(data["entries"]),
            "watched_count": len(data["watched"]), "adxo_updated": data["adxo_updated"],
            "needed_count": None if data["needed"] is None else len(data["needed"]),
            "needed_error": data["needed_error"]}


@router.get("/api/settings/dxmon")
def get_dxmon_settings(conn=Depends(get_conn)):
    return {"url": db.get_setting(conn, "dxmon_url", "")}


@router.put("/api/settings/dxmon")
def put_dxmon_settings(request: Request, body: DXMonURLBody, conn=Depends(get_conn)):
    """Save the address ('' turns every DX Monitor feature off), then fetch once."""
    try:
        url = dxmon.check_url(body.url)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    db.set_setting(conn, "dxmon_url", url)
    if url:
        _dxmon_try(request, conn, url)
    return _dxmon_view(request, conn, auto=False)


@router.post("/api/dxmon/names")
def dxmon_decide(request: Request, body: ADXONameBody, conn=Depends(get_conn)):
    """Approve an ADXO spelling as an entity (or Ignore it). Only Dan does this."""
    name = body.name.strip()
    key = dxmon.normalize(name)
    if not key:
        raise HTTPException(422, "That name has no letters or digits.")
    if body.dxcc is not None:
        e = ref(request).by_dxcc.get(body.dxcc)
        if e is None or e.deleted:
            raise HTTPException(422, f"DXCC {body.dxcc} is not a current entity.")
    db.decide_adxo_name(conn, key, name, body.dxcc)
    return _dxmon_view(request, conn, auto=False)


@router.delete("/api/dxmon/names")
def dxmon_forget(request: Request, name_norm: str, conn=Depends(get_conn)):
    """Remove an approval or an Ignore; the name goes back to "needs your OK"."""
    if not db.forget_adxo_name(conn, name_norm[:200]):
        raise HTTPException(404, "No such approved or ignored name.")
    return _dxmon_view(request, conn, auto=False)


# ---------- curation advisor (D55; works without DX Monitor) ----------

class AdvisorSettings(BaseModel):
    entities: int = Field(advisor.DEFAULT_ENTITIES, ge=1, le=advisor.MAX_COUNT)
    slots: int = Field(advisor.DEFAULT_SLOTS, ge=1, le=advisor.MAX_COUNT)
    bands: list[str] = Field(default_factory=lambda: list(advisor.DEFAULT_SLOT_BANDS),
                             max_length=20)
    continents: list[str] = Field(default_factory=lambda: list(advisor.CONTINENTS),
                                  max_length=10)


def _advisor_settings(conn):
    """Stored advisor settings (D57), with defaults for anything missing or
    no longer valid (e.g. a band removed from DX Monitor's choices)."""
    try:
        st = AdvisorSettings(**(db.get_setting(conn, "advisor", {}) or {}))
    except Exception:
        st = AdvisorSettings()
    st.bands = [b for b in st.bands if b in advisor.DXMON_BANDS]
    st.continents = [c for c in st.continents if c in advisor.CONTINENTS]
    return st


def _advisor_settings_json(st):
    return st.model_dump() | {
        "default_bands": list(advisor.DEFAULT_SLOT_BANDS),
        "band_choices": [{"code": b, "label": LABELS[b]} for b in advisor.DXMON_BANDS],
        "continent_choices": [{"code": c, "label": n} for c, n in advisor.CONTINENTS.items()]}


@router.get("/api/settings/advisor")
def get_advisor_settings(conn=Depends(get_conn)):
    return _advisor_settings_json(_advisor_settings(conn))


@router.put("/api/settings/advisor")
def put_advisor_settings(body: AdvisorSettings, conn=Depends(get_conn)):
    bad = [b for b in body.bands if b not in advisor.DXMON_BANDS] + \
          [c for c in body.continents if c not in advisor.CONTINENTS]
    if bad:
        raise HTTPException(422, f"Unknown band or continent: {', '.join(map(str, bad))}.")
    body.bands = [b for b in advisor.DXMON_BANDS if b in body.bands]          # canonical order
    body.continents = [c for c in advisor.CONTINENTS if c in body.continents]
    db.set_setting(conn, "advisor", body.model_dump())
    return _advisor_settings_json(body)


@router.get("/api/advisor")
def advisor_view(request: Request, entities: int | None = None, slots: int | None = None,
                 auto: bool = True, conn=Depends(get_conn)):
    """Suggestions for DX Monitor's Needed list, using the saved counts and
    filters (D57). Reads DX Monitor only as the DXpedition tags do (auto-refresh
    after 15 minutes); never writes to it."""
    ctx = _context(conn)
    if ctx is None:
        return NO_DATA
    return _advisor_result(request, conn, ctx, entities, slots, auto)


def _advisor_result(request, conn, ctx, entities, slots, auto, whole=False):
    """The advisor's lists and their context; shared with the entity report,
    which asks for the whole ranking (whole=True) to find one entity's place."""
    credits, snap, profile = ctx
    st = _advisor_settings(conn)
    entities = st.entities if entities is None else entities
    slots = st.slots if slots is None else slots
    if whole:
        entities = slots = len(ref(request))
    elif not (1 <= entities <= advisor.MAX_COUNT and 1 <= slots <= advisor.MAX_COUNT):
        raise HTTPException(422, f"Ask for 1 to {advisor.MAX_COUNT} entities and band slots.")
    ranks, mw_fetched = _rankings(conn)
    # Already confirmed and waiting: awaiting marks and paper cards. Won't-submit
    # marks are not: that confirmation will never be credited.
    covered = {(m.dxcc, m.category) for _, m in db.active_marks(conn) if m.state == AWAITING}
    for _, c in db.active_cards(conn):
        covered |= {(c.dxcc, cat) for cat in fills_in_profile(c, credits, profile)}
    dx = _dxmon_view(request, conn, auto=auto)
    cache, _ = db.get_external(conn, "dxmon") if dx.get("enabled") else (None, None)
    if cache and cache.get("url") != dx.get("url"):
        cache = None
    needed = cache.get("needed") if cache else None
    # "not_fetched": a copy stored before this feature, or none yet.
    needed_state = ("off" if not dx.get("enabled") else
                    "not_fetched" if not cache or "needed" not in cache else
                    "failed" if needed is None else
                    "stale" if cache.get("needed_error") else "ok")
    out = advisor.suggest(credits, ref(request), profile, covered=covered, ranks=ranks,
                          names=request.app.state.hamalert_names,
                          dx_tags=dx.get("tags"), needed=needed,
                          n_entities=entities, n_slots=slots,
                          slot_bands=st.bands, slot_continents=st.continents)
    return out | {
        "settings": _advisor_settings_json(st),
        "snapshot_id": snap["id"], "imported_at": snap["imported_at"],
        "profile": _profile_json(profile), "most_wanted_fetched_at": mw_fetched,
        "dxmon": {"enabled": dx.get("enabled", False), "ok": dx.get("ok"),
                  "error": dx.get("error"), "tried_at": dx.get("tried_at"),
                  "fetched_at": dx.get("fetched_at"),
                  "needed_state": needed_state,
                  "needed_fetched_at": cache.get("needed_fetched_at") if cache else None,
                  "needed_skipped": cache.get("needed_skipped", 0) if cache else 0,
                  "needed_error": cache.get("needed_error") if cache else None}}


# ---------- entity search and report (D61) ----------

def _slot_status(cat, have, tags):
    """One category's state for the report: credited, or the strongest of
    awaiting / paper card / won't submit / needed (tags lists all of them)."""
    if cat in have:
        return "credited"
    m = tags["marks"].get(cat)
    if m and m["state"] == AWAITING:
        return "awaiting"
    if tags["cards"].get(cat):
        return "card"
    if m:
        return "wont_submit"
    return "needed"


@router.get("/api/entities/index")
def entities_index(request: Request, conn=Depends(get_conn)):
    """Every current entity, for the header search (D61). Deleted entities are
    left out. Each entry has the names it can be found by and a one-word status,
    worked out from the current import; the browser does the matching."""
    reference = ref(request)
    names = request.app.state.hamalert_names
    aliases = {}
    for key, d in request.app.state.adxo_builtin.items():
        aliases.setdefault(d, []).append(key)
    for row in db.adxo_decisions(conn):
        if row["dxcc"]:
            aliases.setdefault(row["dxcc"], []).append(row["adxo_name"])
    ctx = _context(conn)
    credits, profile = (ctx[0], ctx[2]) if ctx else (None, db.get_profile(conn))
    tags = _Tags(conn, credits, profile) if credits is not None else None
    shown = profile.markable_categories
    out = []
    for e in reference.current:
        row = {"dxcc": e.dxcc, "prefix": e.prefix, "name": names[e.dxcc],
               "lotw_name": e.lotw_name, "aliases": sorted(set(aliases.get(e.dxcc, ())))}
        if credits is not None:
            have = credits.get(e.dxcc, frozenset())
            states = [_slot_status(c, have, tags.of(e.dxcc)) for c in shown]
            row["new"] = MIXED not in have
            row["needed"] = sum(1 for x in states if x in ("needed", "wont_submit"))
            row["pending"] = sum(1 for x in states if x in ("awaiting", "card"))
        out.append(row)
    return {"has_data": credits is not None, "entities": out}


@router.get("/api/entity/{dxcc}")
def entity_report(request: Request, dxcc: int, conn=Depends(get_conn)):
    """Everything the app knows about one current entity (D61). Reads only
    stored data: DX Monitor is not contacted here (the page refreshes it
    separately), so the report never waits on another app."""
    reference = ref(request)
    e = reference.by_dxcc.get(dxcc)
    if e is None or e.deleted:
        raise HTTPException(404, f"DXCC {dxcc} is not a current entity.")
    ranks, mw_fetched = _rankings(conn)
    names = request.app.state.hamalert_names
    base = {"dxcc": e.dxcc, "prefix": e.prefix, "name": names[e.dxcc],
            "lotw_name": e.lotw_name, "adif_name": e.adif_name,
            "continent": e.continent, "cq_zone": e.cq_zone,
            "mw_rank": ranks.get(e.dxcc), "most_wanted_fetched_at": mw_fetched}
    ctx = _context(conn)
    if ctx is None:
        return base | NO_DATA
    credits, snap, profile = ctx
    have = credits.get(e.dxcc, frozenset())
    tags = _Tags(conn, credits, profile).of(e.dxcc)

    # When each credit first appeared: follow the chain of imports the current
    # one was built on (each import records the import it was checked
    # against). That is the real history of the current data: an import
    # rolled back from is not in it, so a later import can't look like it
    # removed that import's credits. The matrix has no QSO dates, so these
    # are import dates, not QSO dates.
    timeline, seen, sid = [], set(), snap["id"]
    while sid is not None and sid not in seen:
        s = conn.execute("SELECT id, imported_at, saved_at, based_on FROM snapshots "
                         "WHERE id = ? AND status IN ('current', 'previous')", (sid,)).fetchone()
        if s is None:
            break               # an earlier import was deleted: history starts here
        seen.add(sid)
        timeline.append(s)
        sid = s["based_on"]
    timeline.reverse()
    first_known = bool(timeline) and timeline[0]["based_on"] is None
    ids = [s["id"] for s in timeline]
    per = {i: set() for i in ids}
    if ids:
        marks = ",".join("?" * len(ids))
        for r in conn.execute(f"SELECT snapshot_id, category FROM snapshot_credits "
                              f"WHERE dxcc = ? AND snapshot_id IN ({marks})", [e.dxcc, *ids]):
            per[r["snapshot_id"]].add(r["category"])
    since, history, prev = {}, [], None
    for s in timeline:
        cur = per[s["id"]]
        when = s["saved_at"] or s["imported_at"]
        gained = [c for c in MATRIX_CATEGORIES if c in cur and (prev is None or c not in prev)]
        lost = [] if prev is None else [c for c in MATRIX_CATEGORIES if c in prev and c not in cur]
        for c in gained:
            since[c] = when
        for c in lost:
            since.pop(c, None)
        if gained or lost:
            history.append({"at": when, "first": prev is None and first_known,
                            "earliest": prev is None and not first_known,
                            "gained": gained, "lost": lost})
        prev = cur
    history.reverse()

    def row(c):
        st = _slot_status(c, have, tags)
        m = tags["marks"].get(c)
        return {"category": c, "label": LABELS[c], "status": st,
                "since": since.get(c) if st == "credited" else None,
                "mark": m, "cards": tags["cards"].get(c, [])}

    in_profile = list(profile.markable_categories)
    outside = [c for c in MATRIX_CATEGORIES if c not in in_profile]
    rows = [row(c) for c in in_profile]
    counts = Counter(r["status"] for r in rows)
    cards = [_card_json(cid, c, credits, profile, reference)
             for cid, c in db.active_cards(conn) if c.dxcc == e.dxcc]

    # DX Monitor, from the stored copy only (see the docstring).
    dx = _dxmon_view(request, conn, auto=False)
    dxm = {"enabled": dx.get("enabled", False)}
    if dxm["enabled"]:
        cache, _ = db.get_external(conn, "dxmon")
        if cache and cache.get("url") != dx.get("url"):
            cache = None
        dxm |= {"ok": dx.get("ok"), "error": dx.get("error"), "tried_at": dx.get("tried_at"),
                "fetched_at": dx.get("fetched_at")}
        if cache:
            dxm["dxpeditions"] = dxmon.dxpeditions_for(cache, _matcher(request, conn), e.dxcc,
                                                       request.app.state.today())
            needed = cache.get("needed")
            dxm["needed_state"] = ("not_fetched" if "needed" not in cache else
                                   "failed" if needed is None else
                                   "stale" if cache.get("needed_error") else "ok")
            dxm["needed"] = (None if needed is None else
                             [{"bands": x["bands"], "modes": x["modes"]} for x in needed
                              if names.place(x["name"]) == e.dxcc])
    adv = _advisor_result(request, conn, ctx, None, None, False, whole=True)
    suggestion = None
    for i, x in enumerate(adv["entities"]):
        if x["dxcc"] == e.dxcc:
            suggestion = {"list": "entities", "rank": i + 1,
                          "shown": i < adv["settings"]["entities"],
                          "top": adv["settings"]["entities"]}
    for i, x in enumerate(adv["slots"]):
        if x["dxcc"] == e.dxcc:
            suggestion = {"list": "slots", "rank": i + 1,
                          "shown": i < adv["settings"]["slots"],
                          "top": adv["settings"]["slots"],
                          "bands": x["bands"], "modes": x["modes"], "credits": x["credits"],
                          "dxmon_bands": x["dxmon_bands"], "dxmon_modes": x["dxmon_modes"]}

    return base | {
        "snapshot_id": snap["id"], "callsign": snap["callsign"],
        "imported_at": snap["imported_at"], "saved_at": snap["saved_at"],
        "profile": _profile_json(profile),
        "new": MIXED not in have,
        "credited": sorted(have),                 # for the mark menu
        "marks": tags["marks"], "cards_by_slot": tags["cards"],
        "summary": {"credited": counts["credited"], "total": len(rows),
                    "needed": counts["needed"] + counts["wont_submit"],
                    "awaiting": sum(1 for r in rows if r["mark"] and r["mark"]["state"] == AWAITING),
                    "card": sum(1 for r in rows if r["cards"])},
        "slots": rows,
        "outside": [{"category": c, "label": LABELS[c], "credited": c in have,
                     "since": since.get(c) if c in have else None} for c in outside],
        "paper_cards": cards, "history": history,
        "dxmon": dxm, "suggestion": suggestion}


# ---------- exports (follow the profile, never a page's filters) ----------

def _export_data(request, conn):
    ctx = _context(conn)
    if ctx is None:
        raise HTTPException(409, "Import the matrix first; there is nothing to export yet.")
    credits, snap, profile = ctx
    ranks, _ = _rankings(conn)
    chk = db.latest_status_check(conn)
    check = None
    if chk and chk["snapshot_id"] == snap["id"]:
        check = json.loads(chk["result_json"]) | {"checked_at": chk["checked_at"]}
    return exports.ExportData(credits, ref(request), profile,
                              [m for _, m in db.active_marks(conn)],
                              [c for _, c in db.active_cards(conn)], ranks, snap, check)


def _download(content, filename, media):
    return Response(content, media_type=media,
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


CSV_TYPE = "text/csv; charset=utf-8"


@router.get("/export/missing_entities.csv")
def export_missing_entities(request: Request, conn=Depends(get_conn)):
    return _download(exports.missing_entities_csv(_export_data(request, conn)),
                     "missing_entities.csv", CSV_TYPE)


@router.get("/export/missing_slots.csv")
def export_missing_slots(request: Request, conn=Depends(get_conn)):
    return _download(exports.missing_slots_csv(_export_data(request, conn)),
                     "missing_slots.csv", CSV_TYPE)


@router.get("/export/no_confirms.csv")
def export_no_confirms(request: Request, conn=Depends(get_conn)):
    """DXMon bridge (D48): drop-in replacement for DXMon's no_confirms.csv."""
    return _download(exports.no_confirms_csv(_export_data(request, conn)),
                     "no_confirms.csv", CSV_TYPE)


@router.get("/export/workbook.xlsx")
def export_workbook(request: Request, conn=Depends(get_conn)):
    return _download(exports.workbook(_export_data(request, conn)),
                     f"dxcc_analysis_{date.today().isoformat()}.xlsx",
                     "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
