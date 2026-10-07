from app.analysis import (changes, missing_entities, most_wanted_key, needed_slots,
                          slots_by_category, summarize, totals)
from app.categories import CW, DEFAULT_PROFILE, MIXED, PHONE, SAT, Profile


def test_totals_count_each_category(credits):
    t = totals(credits)
    assert t[MIXED] == len(credits)
    assert t[SAT] == 0
    assert t[CW] == sum(CW in c for c in credits.values())


def test_missing_entities_are_never_credited(credits, reference):
    missing = missing_entities(credits, reference)
    assert {e.dxcc for e in missing} == {e.dxcc for e in reference.current} - set(credits)
    assert all(not e.deleted for e in missing)


def test_profile_does_not_change_missing_entities(credits, reference):
    small = Profile(bands=("20M",), modes=(CW,))
    assert missing_entities(credits, reference) == missing_entities(credits, reference)
    assert needed_slots(credits, reference, small) != needed_slots(credits, reference, DEFAULT_PROFILE)


def test_needed_slots_follow_profile(reference):
    credits = {1: frozenset({MIXED, CW, PHONE, "20M"})}
    need = needed_slots(credits, reference, DEFAULT_PROFILE)
    assert need == {1: ["DIGITAL", "160M", "80M", "40M", "30M", "17M", "15M", "12M", "10M", "6M"]}
    no160 = Profile(bands=tuple(b for b in DEFAULT_PROFILE.bands if b != "160M"))
    assert "160M" not in needed_slots(credits, reference, no160)[1]


def test_2m_and_sat_not_needed_by_default(reference):
    credits = {1: frozenset({MIXED})}
    need = needed_slots(credits, reference, DEFAULT_PROFILE)[1]
    assert "2M" not in need and SAT not in need


def test_complete_entity_omitted(reference):
    full = frozenset({MIXED, *DEFAULT_PROFILE.slot_categories})
    assert needed_slots({1: full}, reference, DEFAULT_PROFILE) == {}


def test_slots_by_category(reference):
    credits = {1: frozenset({MIXED, CW}), 3: frozenset({MIXED, PHONE})}
    by_cat = slots_by_category(needed_slots(credits, reference, DEFAULT_PROFILE), DEFAULT_PROFILE)
    assert by_cat[CW] == [3] and by_cat[PHONE] == [1]
    assert sorted(by_cat["20M"]) == [1, 3]


def test_summarize(reference):
    full = frozenset({MIXED, *DEFAULT_PROFILE.slot_categories})
    credits = {1: full, 3: full - {"6M"}, 4: frozenset({MIXED})}
    s = summarize(credits, reference, DEFAULT_PROFILE)
    assert (s.entities_credited, s.entities_missing) == (3, 337)
    assert (s.complete, s.one_slot_away) == (1, 1)
    assert s.slots_missing == 1 + len(DEFAULT_PROFILE.slot_categories)


def test_changes():
    old = {1: frozenset({MIXED, CW}), 3: frozenset({MIXED, PHONE})}
    new = {1: frozenset({MIXED, CW, "20M"}), 3: frozenset({MIXED}), 4: frozenset({MIXED, "15M"})}
    ch = changes(old, new)
    assert ch.new_entities == [4]
    assert ch.new_slots == [(1, "20M"), (4, "15M")]
    assert ch.lost == [(3, PHONE)]
    assert changes(None, new).new_entities == [1, 3, 4]


def test_most_wanted_ordering():
    ranks = {10: 1, 20: 300, 30: 150}
    ids = [10, 20, 30, 40]
    assert sorted(ids, key=most_wanted_key(ranks, easiest_first=True)) == [20, 30, 10, 40]
    assert sorted(ids, key=most_wanted_key(ranks, easiest_first=False)) == [10, 30, 20, 40]


def test_profile_normalises_and_rejects_unknown():
    assert Profile(bands=("6M", "20M")).bands == ("20M", "6M")
    try:
        Profile(bands=("11M",))
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")


def test_changes_follow_profile():
    old = {1: frozenset({MIXED, SAT})}
    new = {1: frozenset({MIXED, "20M", "2M"})}
    ch = changes(old, new, DEFAULT_PROFILE)                  # Satellite and 2 m not tracked
    assert ch.lost == [] and ch.new_slots == [(1, "20M")]
    with_sat = Profile(modes=(CW, PHONE, "DIGITAL", SAT), bands=DEFAULT_PROFILE.bands + ("2M",))
    ch = changes(old, new, with_sat)
    assert ch.lost == [(1, SAT)] and ch.new_slots == [(1, "20M"), (1, "2M")]
    assert changes(old, new).lost == [(1, SAT)]              # no profile: everything


def test_sat_loss_holds_regardless_of_profile(reference, credits):
    from app.parser import parse_text
    from app.validate import HELD, validate
    from conftest import render_paste
    before = dict(credits)
    before[1] = credits[1] | {SAT}
    res = validate(parse_text(render_paste(reference, credits)), reference, before)
    assert res.status == HELD and any("Satellite" in w for w in res.warnings)


def test_satellite_profile_option(reference):
    assert SAT not in DEFAULT_PROFILE.slot_categories
    with_sat = Profile(modes=(CW, PHONE, "DIGITAL", SAT))
    assert with_sat.modes == (CW, PHONE, "DIGITAL", SAT)
    need = needed_slots({1: frozenset({MIXED, CW, PHONE})}, reference, with_sat)[1]
    assert SAT not in need and "DIGITAL" in need      # Satellite is separate (D43)


def test_satellite_needs_cover_all_entities(reference):
    # D44: Satellite needs span every current entity, Mixed-credited or not.
    from app.analysis import satellite_needs
    with_sat = Profile(modes=(CW, PHONE, "DIGITAL", SAT))
    credits = {1: frozenset({MIXED, CW}), 3: frozenset({SAT})}
    sat = satellite_needs(credits, reference, with_sat)
    assert 1 in sat and 3 not in sat and len(sat) == len(reference.current) - 1
    assert satellite_needs(credits, reference, DEFAULT_PROFILE) == []
    by_cat = slots_by_category(needed_slots(credits, reference, with_sat), with_sat, sat)
    assert by_cat[SAT] == sat and 3 not in by_cat[CW]
    s = summarize(credits, reference, with_sat)
    assert s.satellite_missing == len(sat) and s.entities_missing == len(reference.current) - 1
    assert summarize(credits, reference, DEFAULT_PROFILE).satellite_missing is None
