"""Entity search index and entity report (D61). Synthetic data only."""

import pytest
from fastapi.testclient import TestClient

from app.categories import CW, DIGITAL, MIXED, PHONE
from app.main import create_app
from conftest import render_paste
from test_dxmon import TODAY, fake_dxmon

FALK, SOLOMON, SOMALIA, PALESTINE_DELETED = 141, 185, 232, 196
FALK_CREDITS = frozenset({MIXED, PHONE, "160M", "80M", "40M", "30M", "20M", "10M", "6M"})


def make_client(tmp_path, reference, fetch=None):
    app = create_app(db_path=tmp_path / "d.db", reference=reference,
                     clublog_fetch=lambda: b"{}", dxmon_fetch=fetch or fake_dxmon(),
                     today=lambda: TODAY)
    return TestClient(app)


def _import(c, reference, credits, save_anyway=False):
    p = c.post("/api/import/preview", data={"text": render_paste(reference, credits)}).json()
    r = c.post(f"/api/import/{p['id']}/save", json={"save_anyway": save_anyway})
    assert r.status_code == 200, r.text
    return p["id"]


@pytest.fixture
def base(credits, reference):
    out = dict(credits)
    out[FALK] = FALK_CREDITS
    out.pop(SOMALIA, None)                                   # never confirmed
    out[SOLOMON] = frozenset({MIXED, CW, PHONE, DIGITAL, "40M", "20M", "15M"})
    return out


# ---------- search index ----------

def test_index_lists_current_entities_only(tmp_path, reference):
    with make_client(tmp_path, reference) as c:
        r = c.get("/api/entities/index").json()
        assert r["has_data"] is False
        ids = {e["dxcc"] for e in r["entities"]}
        assert len(ids) == len(reference.current) == 340
        assert PALESTINE_DELETED not in ids and all(not reference.by_dxcc[d].deleted for d in ids)
        falk = next(e for e in r["entities"] if e["dxcc"] == FALK)
        assert falk["name"] == "Falkland Is." and falk["prefix"] == "VP8"
        assert "needed" not in falk                          # no import: no status


def test_index_status_and_aliases(tmp_path, reference, base):
    with make_client(tmp_path, reference) as c:
        complete = 1                                         # Canada: every profile slot
        base[complete] = frozenset({MIXED, CW, PHONE, DIGITAL, "160M", "80M", "40M", "30M",
                                    "20M", "17M", "15M", "12M", "10M", "6M"})
        _import(c, reference, base)
        idx = {e["dxcc"]: e for e in c.get("/api/entities/index").json()["entities"]}
        assert idx[SOMALIA]["new"] is True
        assert idx[FALK]["new"] is False and idx[FALK]["needed"] == 5 and idx[FALK]["pending"] == 0
        assert idx[complete]["needed"] == 0 and idx[complete]["pending"] == 0
        # Marks and cards move a slot from "needed" to "pending"; won't submit stays needed.
        c.post("/api/marks", json={"dxcc": FALK, "category": DIGITAL, "state": "awaiting"})
        c.post("/api/marks", json={"dxcc": FALK, "category": "12M", "state": "wont_submit"})
        c.post("/api/paper", json={"dxcc": FALK, "band": "15M", "mode": PHONE})
        f = next(e for e in c.get("/api/entities/index").json()["entities"] if e["dxcc"] == FALK)
        assert f["needed"] == 3 and f["pending"] == 2
        # The tested DXpedition spellings are searchable (eSwatini -> 468).
        assert "ESWATINI" in idx[468]["aliases"]


# ---------- report ----------

def test_report_rejects_deleted_and_unknown(tmp_path, reference):
    with make_client(tmp_path, reference) as c:
        assert c.get(f"/api/entity/{PALESTINE_DELETED}").status_code == 404
        assert c.get("/api/entity/9999").status_code == 404
        assert c.get("/api/entity/abc").status_code == 422
        r = c.get(f"/api/entity/{FALK}").json()             # before any import
        assert r["no_data"] and r["name"] == "Falkland Is." and r["lotw_name"] == "FALKLAND ISLANDS"


def test_report_status_marks_and_cards(tmp_path, reference, base):
    with make_client(tmp_path, reference) as c:
        _import(c, reference, base)
        c.post("/api/marks", json={"dxcc": FALK, "category": DIGITAL, "state": "awaiting",
                                   "note": "FT8 Nov 2"})
        c.post("/api/marks", json={"dxcc": FALK, "category": "12M", "state": "wont_submit"})
        c.post("/api/paper", json={"dxcc": FALK, "band": "15M", "mode": PHONE, "call": "VP8AA"})
        r = c.get(f"/api/entity/{FALK}").json()
        st = {x["category"]: x["status"] for x in r["slots"]}
        assert st[MIXED] == st[PHONE] == st["160M"] == "credited"
        assert st[DIGITAL] == "awaiting" and st["15M"] == "card"
        assert st["12M"] == "wont_submit" and st[CW] == "needed" and st["17M"] == "needed"
        assert r["summary"] == {"credited": 9, "total": 14, "needed": 3, "awaiting": 1, "card": 1}
        dig = next(x for x in r["slots"] if x["category"] == DIGITAL)
        assert dig["mark"]["note"] == "FT8 Nov 2" and dig["since"] is None
        assert [x["category"] for x in r["outside"]] == ["SAT", "2M"]
        assert len(r["paper_cards"]) == 1 and r["paper_cards"][0]["fills"] == ["15M"]
        assert r["new"] is False and set(r["credited"]) == set(FALK_CREDITS)
        assert r["marks"][DIGITAL]["state"] == "awaiting"   # what the mark menu needs


def test_report_since_and_history(tmp_path, reference, base):
    with make_client(tmp_path, reference) as c:
        first = _import(c, reference, base)
        more = dict(base)
        more[FALK] = FALK_CREDITS | {"17M", CW}
        _import(c, reference, more)
        r = c.get(f"/api/entity/{FALK}").json()
        since = {x["category"]: x["since"] for x in r["slots"]}
        assert since["17M"] and since[MIXED] and since["17M"] >= since[MIXED]
        assert len(r["history"]) == 2
        newest, oldest = r["history"]
        assert newest["gained"] == [CW, "17M"] and not newest["first"] and newest["lost"] == []
        assert oldest["first"] and set(oldest["gained"]) == set(FALK_CREDITS)
        # Roll back to the first import: the later credits leave the report.
        assert c.post(f"/api/snapshots/{first}/make-current").status_code == 200
        r = c.get(f"/api/entity/{FALK}").json()
        st = {x["category"]: x for x in r["slots"]}
        assert st["17M"]["status"] == "needed" and st["17M"]["since"] is None
        assert len(r["history"]) == 1 and r["history"][0]["first"]


def test_history_after_a_rollback_and_a_new_import(tmp_path, reference, base):
    # X, then Y (adds 17 m), roll back to X, then Z (adds CW): Y is no longer
    # part of the current data's history, so Z must not look like it removed 17 m.
    with make_client(tmp_path, reference) as c:
        x = _import(c, reference, base)
        y = dict(base)
        y[FALK] = FALK_CREDITS | {"17M"}
        _import(c, reference, y)
        assert c.post(f"/api/snapshots/{x}/make-current").status_code == 200
        z = dict(base)
        z[FALK] = FALK_CREDITS | {CW}
        _import(c, reference, z)
        r = c.get(f"/api/entity/{FALK}").json()
        assert [h["gained"] for h in r["history"]][0] == [CW]
        assert all(h["lost"] == [] for h in r["history"]) and len(r["history"]) == 2
        assert next(x for x in r["slots"] if x["category"] == "17M")["status"] == "needed"


def test_history_when_the_first_import_was_deleted(tmp_path, reference, base):
    with make_client(tmp_path, reference) as c:
        first = _import(c, reference, base)
        more = dict(base)
        more[FALK] = FALK_CREDITS | {"17M"}
        _import(c, reference, more)
        assert c.delete(f"/api/snapshots/{first}").status_code == 200
        h = c.get(f"/api/entity/{FALK}").json()["history"]
        assert len(h) == 1 and h[0]["earliest"] and not h[0]["first"]


def test_report_history_shows_a_credit_removed(tmp_path, reference, base):
    with make_client(tmp_path, reference) as c:
        _import(c, reference, base)
        fewer = dict(base)
        fewer[FALK] = FALK_CREDITS - {"6M"}
        _import(c, reference, fewer, save_anyway=True)     # a decrease is held for review
        r = c.get(f"/api/entity/{FALK}").json()
        assert r["history"][0]["lost"] == ["6M"]
        assert next(x for x in r["slots"] if x["category"] == "6M")["status"] == "needed"


def test_report_new_entity_and_suggestion(tmp_path, reference, base):
    with make_client(tmp_path, reference) as c:
        _import(c, reference, base)
        r = c.get(f"/api/entity/{SOMALIA}").json()
        assert r["new"] is True and r["summary"]["credited"] == 0
        assert all(x["status"] == "needed" for x in r["slots"])
        adv = c.get("/api/advisor", params={"entities": 100}).json()
        rank = [x["dxcc"] for x in adv["entities"]].index(SOMALIA) + 1
        assert r["suggestion"]["list"] == "entities" and r["suggestion"]["rank"] == rank
        # Falklands needs bands and modes: it is in the band-slot ranking somewhere.
        f = c.get(f"/api/entity/{FALK}").json()["suggestion"]
        assert f is None or f["list"] == "slots"


def test_report_without_dx_monitor(tmp_path, reference, base):
    fetch = fake_dxmon()
    with make_client(tmp_path, reference, fetch) as c:
        _import(c, reference, base)
        r = c.get(f"/api/entity/{SOLOMON}").json()
        assert r["dxmon"] == {"enabled": False} and fetch.calls == []


def test_report_with_dx_monitor_uses_the_stored_copy(tmp_path, reference, base):
    fetch = fake_dxmon()
    with make_client(tmp_path, reference, fetch) as c:
        _import(c, reference, base)
        c.put("/api/settings/dxmon", json={"url": "http://dxmon.lan:8083"})
        n = len(fetch.calls)
        sol = c.get(f"/api/entity/{SOLOMON}").json()["dxmon"]
        assert len(fetch.calls) == n                         # the report never calls DX Monitor
        # A credited entity still shows its DXpedition (a chance at missing slots).
        assert sol["dxpeditions"] == [{"kind": "air", "callsign": "H44MS", "begin": "2026-10-03",
                                       "end": "2026-11-20", "watched": False}]
        assert sol["needed"] == [] and sol["ok"] is True
        som = c.get(f"/api/entity/{SOMALIA}").json()["dxmon"]
        assert [(x["kind"], x["callsign"], x["watched"]) for x in som["dxpeditions"]] == \
            [("air", "6O2M", True), ("later", "6O6X", False)]
        assert som["needed"] == [{"bands": [], "modes": []}]   # whole-entity Needed entry


def test_report_when_needed_list_unreadable(tmp_path, reference, base):
    from app import dxmon
    fetch = fake_dxmon(needed=dxmon.DXMonError("no /api/needed"))
    with make_client(tmp_path, reference, fetch) as c:
        _import(c, reference, base)
        c.put("/api/settings/dxmon", json={"url": "http://dxmon.lan:8083"})
        som = c.get(f"/api/entity/{SOMALIA}").json()["dxmon"]
        assert som["needed"] is None and som["dxpeditions"] and som["needed_state"] == "failed"


def test_entity_page_route(tmp_path, reference):
    with make_client(tmp_path, reference) as c:
        r = c.get("/entity")
        assert r.status_code == 200 and b"entity.js" in r.content
        assert c.get("/entity", params={"page": "../app/main.py"}).content == r.content
