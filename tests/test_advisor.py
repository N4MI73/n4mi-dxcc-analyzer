"""Curation advisor (D55): HamAlert names, ranking, DX Monitor's Needed list, API.

tests/data/hamalert_names_checked.csv holds every current entity's name as
HamAlert's picker shows it, transcribed from Dan's screenshots of the whole
picker on 2026-11-15 (an earlier check on 2026-10-20 covered 78). They are
public entity names, not his data.
Everything else here is synthetic.
"""

import csv
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import advisor, dxmon
from app.categories import CW, DIGITAL, MIXED, PHONE, Profile
from app.main import create_app
from conftest import render_paste
from test_dxmon import TODAY, fake_dxmon

CHECKED = Path(__file__).resolve().parent / "data" / "hamalert_names_checked.csv"
ALL = frozenset({MIXED, CW, PHONE, DIGITAL, "160M", "80M", "40M", "30M", "20M",
                 "17M", "15M", "12M", "10M", "6M"})


@pytest.fixture(scope="module")
def names(reference):
    return advisor.Names(reference, advisor.load_overrides(reference))


# ---------- names ----------

def test_every_checked_name_matches_hamalert_exactly(names):
    rows = list(csv.DictReader(open(CHECKED, encoding="utf-8")))
    assert len(rows) == 340
    for r in rows:
        assert names[int(r["dxcc"])] == r["hamalert_name"], r


def test_overrides_are_the_renamed_entities(reference):
    assert advisor.load_overrides(reference) == {
        207: "Rodriguez I.", 462: "South Africa", 468: "Swaziland", 502: "Macedonia",
        518: "St Maarten"}


def test_bad_override_row_stops_start_up(reference, tmp_path):
    p = tmp_path / "o.csv"
    p.write_text("dxcc,hamalert_name,note\n81,Germany,deleted entity\n")
    with pytest.raises(ValueError, match="81"):
        advisor.load_overrides(reference, p)
    p.write_text("dxcc,hamalert_name,note\n468,,blank\n")
    with pytest.raises(ValueError):
        advisor.load_overrides(reference, p)


def test_every_current_entity_has_a_unique_name(reference, names):
    assert len(names.by_dxcc) == len(reference.current) == 340
    assert len(names.by_key) == 340


def test_place_matches_like_dx_monitor(names):
    # Exactly DX Monitor's rule: trimmed and lower-cased, nothing else.
    assert names.place("  amsterdam & st. paul is. ") == 10
    assert names.place("SWAZILAND") == 468
    assert names.place("Amsterdam &  St. Paul Is.") is None   # a doubled inner space never matches
    assert names.place("Kingdom of Eswatini") is None      # HamAlert doesn't use it
    assert names.place("U K Bases on Cyprus") is None       # LoTW's spelling isn't HamAlert's
    assert names.place("Amsterdam & St Paul Is") is None    # a missing dot doesn't match either


def test_title_case_details():
    assert advisor.title_name("COTE D'IVOIRE") == "Cote d'Ivoire"
    assert advisor.title_name("GUINEA-BISSAU") == "Guinea-Bissau"
    assert advisor.title_name("BANABA I. (OCEAN I.)") == "Banaba I. (Ocean I.)"
    assert advisor.title_name("UNITED NATIONS HQ") == "United Nations HQ"
    assert advisor.title_name("THE GAMBIA") == "The Gambia"


# ---------- ranking ----------

def _credits(reference, never=(), partial=None):
    """Every current entity fully credited, except `never` (no credits) and
    `partial` {dxcc: categories to remove}."""
    partial = partial or {}
    out = {}
    for e in reference.current:
        if e.dxcc in never:
            continue
        out[e.dxcc] = ALL - frozenset(partial.get(e.dxcc, ()))
    return out


def run(reference, names, credits, **kw):
    kw.setdefault("covered", set())
    kw.setdefault("ranks", {})
    return advisor.suggest(credits, reference, Profile(), names=names, **kw)


def test_entities_dxpeditions_first_then_easiest(reference, names):
    never = (232, 305, 299, 293, 1)          # Somalia, Bangladesh, W Malaysia, Viet Nam, Canada
    ranks = {232: 55, 305: 119, 299: 214, 293: 211, 1: 330}
    tags = {"305": [{"kind": "soon", "callsign": "S21HRG", "begin": "2026-10-16",
                     "end": "2026-10-20", "watched": False}],
            "232": [{"kind": "air", "callsign": "6O2M", "begin": "2026-10-05",
                     "end": "2026-10-25", "watched": True}]}
    out = run(reference, names, _credits(reference, never=never), ranks=ranks, dx_tags=tags)
    assert [e["dxcc"] for e in out["entities"]] == [232, 305, 1, 299, 293]
    assert out["entities"][0]["dxpedition"]["callsign"] == "6O2M"
    assert out["entities"][2]["hamalert_name"] == "Canada"
    assert out["entities_available"] == 5


def test_confirmations_in_hand_leave_an_entity_out_wont_submit_does_not(reference, names):
    credits = _credits(reference, never=(293, 330, 299))     # Viet Nam, Iran, W Malaysia
    covered = {(293, MIXED), (330, MIXED)}                    # awaiting mark / paper card
    out = run(reference, names, credits, covered=covered)
    assert [e["dxcc"] for e in out["entities"]] == [299]


def test_counts_limit_the_lists(reference, names):
    never = tuple(e.dxcc for e in reference.current[:30])
    out = run(reference, names, _credits(reference, never=never), n_entities=7)
    assert len(out["entities"]) == 7 and out["entities_available"] == 30


def test_band_slots_worth_two_first_and_160_6_left_out(reference, names):
    partial = {
        209: ("15M", "12M", CW),        # Belgium: two bands + CW -> worth 2
        227: ("20M",),                  # France: band only -> worth 1
        281: (PHONE, DIGITAL),          # Spain: modes only -> worth 1
        236: ("160M", "6M"),            # Greece: only 160/6 -> no suggestion
        239: ("160M", CW),              # Hungary: 160 dropped, CW left -> worth 1
    }
    ranks = {209: 300, 227: 320, 281: 310, 239: 290}
    out = run(reference, names, _credits(reference, partial=partial), ranks=ranks)
    s = {x["dxcc"]: x for x in out["slots"]}
    assert [x["dxcc"] for x in out["slots"]] == [209, 227, 281, 239]
    assert s[209]["credits"] == 2
    assert s[209]["dxmon_bands"] == ["15m", "12m"] and s[209]["dxmon_modes"] == ["cw"]
    assert s[227]["dxmon_bands"] == ["20m"] and s[227]["dxmon_modes"] == []
    assert s[281]["dxmon_bands"] == [] and s[281]["dxmon_modes"] == ["ssb", "ft8", "ft4"]
    assert s[239]["dxmon_modes"] == ["cw"] and s[239]["bands"] == []
    assert 236 not in s


def test_awaiting_and_card_slots_left_out_wont_submit_stays(reference, names):
    partial = {209: ("15M", CW), 227: ("20M",)}
    covered = {(209, CW), (227, "20M")}       # awaiting CW / a paper card for 20 m
    out = run(reference, names, _credits(reference, partial=partial), covered=covered)
    s = {x["dxcc"]: x for x in out["slots"]}
    assert s[209]["credits"] == 1 and s[209]["dxmon_bands"] == ["15m"]
    assert 227 not in s


def test_never_credited_entities_are_not_band_slots(reference, names):
    out = run(reference, names, _credits(reference, never=(209,)))
    assert out["slots"] == [] and out["slots_available"] == 0


def test_profile_without_a_band_is_respected(reference, names):
    credits = _credits(reference, partial={209: ("15M",)})
    out = advisor.suggest(credits, reference, Profile(bands=("20M", "10M")), covered=set(),
                          ranks={}, names=names)
    assert out["slots"] == []


# ---------- already in DX Monitor ----------

def entry(name, bands="", modes=""):
    return dxmon.parse_needed(json.dumps({"entries": [
        {"entity": name, "band": bands, "mode": modes}]}))[0][0]


def test_in_dx_monitor_flags(reference, names):
    credits = _credits(reference, never=(232, 305),
                       partial={209: ("15M", CW), 227: ("20M", "17M"), 281: (PHONE,)})
    needed = [entry("SOMALIA"),                      # whole entity
              entry("Bangladesh", "20m", "cw"),      # a slot only: not the whole entity
              entry("Belgium", "15m,12m", "cw,ssb"),  # catches Belgium 15 m CW
              entry("France", "40m"),                # doesn't catch France 20/17 m
              entry("Spain"),                        # whole entity covers the slot
              entry("Swaziland, maybe")]             # misspelled: never matches spots
    out = run(reference, names, credits, needed=needed)
    e = {x["dxcc"]: x["in_dx_monitor"] for x in out["entities"]}
    s = {x["dxcc"]: x["in_dx_monitor"] for x in out["slots"]}
    assert e == {232: True, 305: False}
    assert s == {209: True, 227: False, 281: True}
    assert out["dxmon_unmatched"] == ["Swaziland, maybe"]
    assert out["dxmon_needed_count"] == 6


def test_unknown_when_dx_monitor_list_is_missing(reference, names):
    out = run(reference, names, _credits(reference, never=(232,)), needed=None)
    assert out["entities"][0]["in_dx_monitor"] is None and out["dxmon_needed_count"] is None


def test_parse_needed():
    got = dxmon.parse_needed(json.dumps({"count": 3, "entries": [
        {"entity": " Belgium ", "band": "15m, 12M", "mode": "CW"},
        {"entity": "", "band": "20m"}, "junk"]}))
    assert got == ([{"name": "Belgium", "bands": ["12m", "15m"], "modes": ["cw"]}], 2)
    assert dxmon.parse_needed(json.dumps({"count": 0, "entries": []})) == ([], 0)
    # A list of strings is fine; any other form is refused, never read as "any".
    assert dxmon.parse_needed(json.dumps({"entries": [{"entity": "X", "band": ["20m", "15M"]}]}))[0][0]["bands"] == ["15m", "20m"]
    with pytest.raises(dxmon.DXMonError):
        dxmon.parse_needed(json.dumps({"entries": [{"entity": "X", "band": {"b": 1}}]}))
    for bad in (b"<html>404</html>", json.dumps({"needed": []})):
        with pytest.raises(dxmon.DXMonError):
            dxmon.parse_needed(bad)


# ---------- API ----------

def make_client(tmp_path, reference, fetch=None):
    app = create_app(db_path=tmp_path / "d.db", reference=reference,
                     clublog_fetch=lambda: b"{}", dxmon_fetch=fetch or fake_dxmon(),
                     today=lambda: TODAY)
    return TestClient(app)


def _import(c, reference, credits):
    p = c.post("/api/import/preview", data={"text": render_paste(reference, credits)}).json()
    c.post(f"/api/import/{p['id']}/save")


def test_api_without_dx_monitor(tmp_path, reference, credits):
    fetch = fake_dxmon()
    with make_client(tmp_path, reference, fetch) as c:
        assert c.get("/api/advisor").json()["no_data"]
        _import(c, reference, credits)
        v = c.get("/api/advisor").json()
        assert v["dxmon"]["enabled"] is False and fetch.calls == []
        assert len(v["entities"]) == 20 and len(v["slots"]) == 10
        assert all(x["in_dx_monitor"] is None for x in v["entities"] + v["slots"])
        assert c.get("/api/advisor", params={"entities": 0}).status_code == 422
        assert c.get("/api/advisor", params={"slots": 101}).status_code == 422


def test_api_with_dx_monitor(tmp_path, reference, credits):
    with make_client(tmp_path, reference) as c:
        _import(c, reference, credits)
        c.put("/api/settings/dxmon", json={"url": "http://dxmon.lan:8083"})
        v = c.get("/api/advisor", params={"entities": 63}).json()
        ents = {x["dxcc"]: x for x in v["entities"]}
        assert v["entities"][0]["dxcc"] == 232                 # Somalia: on the air
        assert ents[232]["dxpedition"]["kind"] == "air" and ents[232]["in_dx_monitor"] is True
        assert ents[180]["in_dx_monitor"] is False             # Mount Athos: not in Needed
        assert v["dxmon_needed_count"] == 1 and v["dxmon"]["needed_error"] is None


def test_awaiting_mark_and_card_through_the_api(tmp_path, reference, credits):
    with make_client(tmp_path, reference) as c:
        _import(c, reference, credits)
        before = {x["dxcc"] for x in c.get("/api/advisor", params={"entities": 100}).json()["entities"]}
        a, b = sorted(before)[:2]
        c.post("/api/marks", json={"dxcc": a, "category": MIXED, "state": "awaiting"})
        c.post("/api/paper", json={"dxcc": b, "band": "20M", "mode": CW})
        w = sorted(before)[2]
        c.post("/api/marks", json={"dxcc": w, "category": MIXED, "state": "wont_submit"})
        after = {x["dxcc"] for x in c.get("/api/advisor", params={"entities": 100}).json()["entities"]}
        assert after == before - {a, b}


def test_needed_list_failure_keeps_dxpedition_tags(tmp_path, reference, credits):
    fetch = fake_dxmon(needed=dxmon.DXMonError("DX Monitor answered HTTP 404; check the address."))
    with make_client(tmp_path, reference, fetch) as c:
        _import(c, reference, credits)
        v = c.put("/api/settings/dxmon", json={"url": "http://dxmon.lan:8083"}).json()
        assert v["ok"] and v["tags"]["232"]                    # DXpedition tags unaffected
        a = c.get("/api/advisor").json()
        assert "404" in a["dxmon"]["needed_error"]
        assert a["entities"][0]["dxpedition"]["callsign"] == "6O2M"
        assert all(x["in_dx_monitor"] is None for x in a["entities"])


# ---------- pending banner recount ----------

def test_status_check_banner_recounts_marks(tmp_path, reference, credits):
    from test_status_check import status_text
    with make_client(tmp_path, reference) as c:
        _import(c, reference, credits)
        need = next(d for d, cats in credits.items() if MIXED in cats and PHONE not in cats)
        r = c.post("/api/status-check", json={"text": status_text(credits, {PHONE: 1})}).json()
        assert r["pending_match"] is False
        latest = c.get("/api/status-check/latest").json()
        assert latest["pending_match"] is False and latest["marks_recounted"]
        # Marking the slot Won't submit now clears the banner without a new check.
        c.post("/api/marks", json={"dxcc": need, "category": PHONE, "state": "wont_submit"})
        latest = c.get("/api/status-check/latest").json()
        line = next(x for x in latest["pending"] if x["category"] == PHONE)
        assert line == line | {"app": 1, "lotw": 1, "ok": True}
        assert latest["pending_match"] is True


# ---------- band and continent filters (D57) ----------

def test_band_filter_replaces_the_fixed_160_6_rule(reference, names):
    credits = _credits(reference, partial={236: ("160M", "6M"), 209: ("80M", "12M", CW)})
    # Defaults: 160 m and 6 m off.
    assert {x["dxcc"] for x in run(reference, names, credits)["slots"]} == {209}
    # Tick 160 m, untick 80 m and 12 m: Greece appears; Belgium is CW on any band.
    out = run(reference, names, credits,
              slot_bands=("160M", "40M", "30M", "20M", "17M", "15M", "10M"))
    s = {x["dxcc"]: x for x in out["slots"]}
    assert s[236]["dxmon_bands"] == ["160m"] and s[236]["credits"] == 1
    assert s[209]["dxmon_bands"] == [] and s[209]["dxmon_modes"] == ["cw"]


def test_continent_filter_narrows_band_slots_only(reference, names):
    credits = _credits(reference, never=(305,), partial={209: ("15M",), 318: ("15M",)})
    out = run(reference, names, credits, slot_continents=("EU", "NA", "SA", "AF", "OC"))
    assert [x["dxcc"] for x in out["slots"]] == [209]          # China (Asia) left out
    assert [x["dxcc"] for x in out["entities"]] == [305]       # Bangladesh (Asia) stays


def test_advisor_settings_are_saved_and_used(tmp_path, reference, credits):
    with make_client(tmp_path, reference) as c:
        d = c.get("/api/settings/advisor").json()
        assert d["entities"] == 20 and d["slots"] == 10
        assert d["bands"] == ["80M", "40M", "30M", "20M", "17M", "15M", "12M", "10M"]
        assert [x["code"] for x in d["continent_choices"]] == ["AF", "AS", "EU", "NA", "OC", "SA"]
        bad = c.put("/api/settings/advisor", json={"bands": ["2M"]})
        assert bad.status_code == 422
        assert c.put("/api/settings/advisor", json={"slots": 0}).status_code == 422
        r = c.put("/api/settings/advisor", json={"entities": 5, "slots": 3,
                                                  "bands": ["20M", "15M", "40M"],
                                                  "continents": ["EU", "AS"]}).json()
        assert r["bands"] == ["40M", "20M", "15M"] and r["continents"] == ["AS", "EU"]
        _import(c, reference, credits)
        v = c.get("/api/advisor").json()
        assert len(v["entities"]) == 5 and len(v["slots"]) == 3
        assert v["settings"]["bands"] == ["40M", "20M", "15M"]
        allowed = {"40m", "20m", "15m"}
        for s in v["slots"]:
            assert set(s["dxmon_bands"]) <= allowed
            assert reference.by_dxcc[s["dxcc"]].continent in ("EU", "AS")
        # A query count still overrides for one request.
        assert len(c.get("/api/advisor", params={"entities": 9}).json()["entities"]) == 9


# ---------- review fixes (2026-10-20) ----------

def test_needed_list_failure_keeps_the_last_good_list(tmp_path, reference, credits):
    state = {"fail": False}
    good = fake_dxmon()

    def fetch(url, timeout=dxmon.TIMEOUT_S):
        if state["fail"] and url.endswith("/api/needed"):
            raise dxmon.DXMonError("DX Monitor answered HTTP 502; check the address.")
        return good(url)
    with make_client(tmp_path, reference, fetch) as c:
        _import(c, reference, credits)
        c.put("/api/settings/dxmon", json={"url": "http://dxmon.lan:8083"})
        first = c.get("/api/advisor", params={"entities": 63}).json()
        assert first["dxmon"]["needed_state"] == "ok"
        state["fail"] = True
        c.post("/api/dxmon/refresh")
        v = c.get("/api/advisor", params={"entities": 63}).json()
        assert v["dxmon"]["needed_state"] == "stale" and "502" in v["dxmon"]["needed_error"]
        assert v["dxmon"]["needed_fetched_at"] == first["dxmon"]["needed_fetched_at"]
        assert v["dxmon_needed_count"] == 1
        assert next(x for x in v["entities"] if x["dxcc"] == 232)["in_dx_monitor"] is True
        # A different address never inherits the old address's list.
        c.put("/api/settings/dxmon", json={"url": "http://other.lan:8083"})
        w = c.get("/api/advisor").json()
        assert w["dxmon"]["needed_state"] == "failed" and w["dxmon_needed_count"] is None


def test_copy_from_before_this_feature_reads_as_not_fetched(tmp_path, reference, credits):
    with make_client(tmp_path, reference) as c:
        _import(c, reference, credits)
        c.put("/api/settings/dxmon", json={"url": "http://dxmon.lan:8083"})
        conn = __import__("sqlite3").connect(tmp_path / "d.db")
        row = json.loads(conn.execute("SELECT payload_json FROM external_data WHERE name='dxmon'").fetchone()[0])
        for k in ("needed", "needed_error", "needed_fetched_at", "needed_skipped"):
            row.pop(k, None)
        conn.execute("UPDATE external_data SET payload_json=? WHERE name='dxmon'", (json.dumps(row),))
        conn.commit()
        conn.close()
        v = c.get("/api/advisor", params={"auto": "false"}).json()
        assert v["dxmon"]["needed_state"] == "not_fetched" and v["dxmon_needed_count"] is None


def test_connection_test_reports_the_needed_list(tmp_path, reference):
    with make_client(tmp_path, reference) as c:
        t = c.post("/api/dxmon/test", json={"url": "http://dxmon.lan:8083"}).json()
        assert t["ok"] and t["needed_count"] == 1 and t["needed_error"] is None
    old = fake_dxmon(needed=dxmon.DXMonError("DX Monitor answered HTTP 404; check the address."))
    with make_client(tmp_path / "b", reference, old) as c:
        t = c.post("/api/dxmon/test", json={"url": "http://dxmon.lan:8083"}).json()
        assert t["ok"] and t["needed_count"] is None and "404" in t["needed_error"]


def test_settings_carry_the_default_bands(tmp_path, reference):
    with make_client(tmp_path, reference) as c:
        assert c.get("/api/settings/advisor").json()["default_bands"] == list(advisor.DEFAULT_SLOT_BANDS)
