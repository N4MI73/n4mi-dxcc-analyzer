"""End-to-end tests of the internal API with FastAPI's test client.

Every test gets a fresh database in a temp folder; data is synthetic.
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.categories import CW, MIXED, SAT
from app.main import create_app
from conftest import render_paste, render_xlsx


@pytest.fixture
def client(tmp_path, reference):
    app = create_app(db_path=tmp_path / "t.db", reference=reference,
                     clublog_fetch=lambda: b"{}")
    with TestClient(app) as c:
        yield c


def _import(client, text, save_anyway=False):
    r = client.post("/api/import/preview", data={"text": text})
    assert r.status_code == 200, r.text
    p = r.json()
    if p["id"] is None:
        return p, None
    s = client.post(f"/api/import/{p['id']}/save", json={"save_anyway": save_anyway})
    return p, s


def test_health_and_empty_state(client):
    assert client.get("/healthz").json() == {"status": "ok"}
    st = client.get("/api/status").json()
    assert st["ok"] and st["snapshot"] is None
    for v in ("entities", "slots", "matrix"):
        assert client.get(f"/api/view/{v}").json()["no_data"] is True


def test_preview_saves_nothing_until_save(client, reference, credits):
    p = client.post("/api/import/preview", data={"text": render_paste(reference, credits)}).json()
    assert p["status"] == "clean" and p["id"] and p["callsign"] == "N0CALL"
    assert len(p["changes"]["new_entities"]) == sum(1 for c in credits.values() if MIXED in c)
    assert client.get("/api/status").json()["snapshot"] is None       # not saved yet
    assert client.post(f"/api/import/{p['id']}/save").status_code == 200
    st = client.get("/api/status").json()
    assert st["snapshot"]["id"] == p["id"] and st["callsign"] == "N0CALL"


def test_rejected_import_stores_nothing(client, reference, credits):
    text = render_paste(reference, credits).replace("\tX\t", "\tX\tX\t", 1)   # misaligned row
    p = client.post("/api/import/preview", data={"text": text}).json()
    assert p["status"] == "rejected" and p["id"] is None and p["errors"]
    assert client.get("/api/snapshots").json()["snapshots"] == []


def test_xlsx_upload(client, reference, credits):
    data = render_xlsx(reference, credits)
    r = client.post("/api/import/preview", files={"file": ("matrix.xlsx", data)})
    assert r.json()["status"] == "clean"
    r = client.post("/api/import/preview", files={"file": ("matrix.pdf", b"%PDF")})
    assert r.status_code == 422


def test_held_import_needs_save_anyway(client, reference, credits):
    _import(client, render_paste(reference, credits))
    fewer = dict(credits)
    victim = next(d for d, c in credits.items() if CW in c)
    fewer[victim] = credits[victim] - {CW}
    p = client.post("/api/import/preview", data={"text": render_paste(reference, fewer)}).json()
    assert p["status"] == "held" and p["changes"]["lost"]
    assert client.post(f"/api/import/{p['id']}/save").status_code == 409
    assert client.post(f"/api/import/{p['id']}/save",
                       json={"save_anyway": True}).status_code == 200


def test_stale_preview_is_refused(client, reference, credits):
    text = render_paste(reference, credits)
    a = client.post("/api/import/preview", data={"text": text}).json()
    b = client.post("/api/import/preview", data={"text": text}).json()
    # Only one preview may be pending: the earlier one was discarded.
    assert client.post(f"/api/import/{a['id']}/save").status_code == 404
    assert client.post(f"/api/import/{b['id']}/save").status_code == 200


def test_views_and_profile(client, reference, credits):
    _import(client, render_paste(reference, credits))
    ents = client.get("/api/view/entities").json()
    assert len(ents["entities"]) == ents["summary"]["entities_missing"]
    assert ents["entities"][0]["sat_credited"] is None                   # Satellite off
    slots = client.get("/api/view/slots").json()
    assert [c["category"] for c in slots["categories"]][:3] == ["CW", "PHONE", "DIGITAL"]
    assert SAT not in [c["category"] for c in slots["categories"]]
    matrix = client.get("/api/view/matrix").json()
    assert len(matrix["entities"]) == len(reference.current) and len(matrix["columns"]) == 16
    # Turn Satellite on: D44 — Satellite needs span every current entity.
    r = client.put("/api/settings/profile",
                   json={"bands": ["20M", "40M"], "modes": ["CW", "PHONE", "DIGITAL", "SAT"]})
    assert r.status_code == 200
    slots = client.get("/api/view/slots").json()
    sat = next(c for c in slots["categories"] if c["category"] == SAT)
    assert len(sat["entities"]) == len(reference.current)                 # none credited
    assert client.get("/api/view/entities").json()["entities"][0]["sat_credited"] is False
    assert client.put("/api/settings/profile",
                      json={"bands": ["11M"], "modes": []}).status_code == 422


def test_marks_clear_on_import(client, reference, credits):
    _import(client, render_paste(reference, credits))
    need = next(d for d, c in credits.items() if MIXED in c and CW not in c)
    r = client.post("/api/marks", json={"dxcc": need, "category": CW, "state": "awaiting"})
    assert r.status_code == 200
    mid = r.json()["id"]
    assert client.post("/api/marks", json={"dxcc": need, "category": CW,
                                           "state": "awaiting"}).status_code == 409
    assert client.post("/api/marks", json={"dxcc": need, "category": "2M",
                                           "state": "awaiting"}).status_code == 422
    tags = next(e for e in client.get("/api/view/matrix").json()["entities"] if e["dxcc"] == need)
    assert tags["marks"][CW]["state"] == "awaiting"
    assert client.patch(f"/api/marks/{mid}", json={"state": "wont_submit"}).status_code == 200
    newer = dict(credits)
    newer[need] = credits[need] | {CW}
    p, s = _import(client, render_paste(reference, newer))
    assert p["marks_to_clear"] == 1 and s.json()["marks_cleared"] == 1
    assert client.get("/api/marks").json()["marks"] == []


def test_paper_cards(client, reference, credits):
    _import(client, render_paste(reference, credits))
    new = next(e.dxcc for e in reference.current if e.dxcc not in credits)
    body = {"dxcc": new, "band": "20M", "mode": CW}
    pv = client.post("/api/paper/preview", json=body).json()
    assert pv["ok"] and pv["fills"] == [MIXED, CW, "20M"]
    assert client.get("/api/paper").json()["cards"] == []              # preview saved nothing
    cid = client.post("/api/paper", json=body).json()["id"]
    ent = next(e for e in client.get("/api/view/entities").json()["entities"] if e["dxcc"] == new)
    assert ent["cards"][MIXED] == [{"id": cid, "state": "in_hand"}]
    assert client.patch(f"/api/paper/{cid}", json={"state": "submitted"}).status_code == 200
    # Satellite card: Satellite only, so outside Dan's profile.
    sat = client.post("/api/paper", json={"dxcc": new, "mode": SAT}).json()
    assert sat["fills"] == [] and "outside your profile" in sat["message"]
    # A card adding nothing is refused.
    done = next(d for d, c in credits.items() if {MIXED, CW, "20M"} <= c)
    assert client.post("/api/paper", json={"dxcc": done, "band": "20M",
                                           "mode": CW}).status_code == 422
    # Import showing the 20 m CW card's slots credited marks it credited.
    newer = dict(credits)
    newer[new] = frozenset({MIXED, CW, "20M"})
    p, s = _import(client, render_paste(reference, newer))
    assert p["cards_to_credit"] == 1 and s.json()["cards_credited"] == 1
    assert [c["mode"] for c in client.get("/api/paper").json()["cards"]] == [SAT]


def test_rollback(client, reference, credits):
    first, _ = _import(client, render_paste(reference, credits))
    more = dict(credits)
    new = next(e.dxcc for e in reference.current if e.dxcc not in credits)
    more[new] = frozenset({MIXED, CW})
    second, _ = _import(client, render_paste(reference, more))
    assert client.delete(f"/api/snapshots/{second['id']}").status_code == 409   # current
    assert client.post(f"/api/snapshots/{first['id']}/make-current").status_code == 200
    statuses = {s["id"]: s["status"] for s in client.get("/api/snapshots").json()["snapshots"]}
    assert statuses == {first["id"]: "current", second["id"]: "previous"}
    assert client.delete(f"/api/snapshots/{second['id']}").status_code == 200


def test_status_check(client, reference, credits):
    assert client.post("/api/status-check", json={"text": "x"}).status_code == 409
    _import(client, render_paste(reference, credits))
    from test_status_check import status_text
    r = client.post("/api/status-check", json={"text": status_text(credits)})
    assert r.status_code == 200, r.text
    assert r.json()["reconciled"] and r.json()["pending_match"]
    assert client.get("/api/status").json()["last_status_check"]["reconciled"] is True


def test_clublog_refresh_failure_keeps_old(tmp_path, reference):
    good = json.dumps({str(i + 1): e.dxcc for i, e in enumerate(reference.current)}).encode()
    calls = iter([good, b"<html>error</html>"])
    app = create_app(db_path=tmp_path / "c.db", reference=reference,
                     clublog_fetch=lambda: next(calls))
    with TestClient(app) as c:
        r = c.post("/api/clublog/refresh")
        assert r.status_code == 200 and r.json()["entities_ranked"] == len(reference.current)
        fetched = r.json()["fetched_at"]
        r = c.post("/api/clublog/refresh")
        assert r.status_code == 502 and "Keeping the previous list" in r.json()["detail"]
        assert c.get("/api/status").json()["most_wanted_fetched_at"] == fetched


def test_pages_and_static_files(client):
    for path, script in (("/", "entities.js"), ("/slots", "slots.js"), ("/import", "import.js")):
        r = client.get(path)
        assert r.status_code == 200 and "text/html" in r.headers["content-type"]
        assert f"/static/{script}" in r.text
        assert client.get(f"/static/{script}").status_code == 200
    assert client.get("/static/common.js").status_code == 200
    assert client.get("/static/style.css").status_code == 200


def test_since_last_import(client, reference, credits):
    _import(client, render_paste(reference, credits))
    assert client.get("/api/view/entities").json()["since_last"] is None     # first import
    more = dict(credits)
    new = next(e.dxcc for e in reference.current if e.dxcc not in credits)
    more[new] = frozenset({MIXED, CW})
    _import(client, render_paste(reference, more))
    since = client.get("/api/view/entities").json()["since_last"]
    assert [e["dxcc"] for e in since["new_entities"]] == [new]
    assert since["new_slots"] == [{"dxcc": new, "name": reference.by_dxcc[new].lotw_name,
                                   "category": CW}]
