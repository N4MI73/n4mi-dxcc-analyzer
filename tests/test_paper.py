from app.categories import CW, DEFAULT_PROFILE, MIXED, PHONE, SAT, Profile
from app.paper import (IN_HAND, SUBMITTED, PaperQSL, check_card, counts_by_state,
                       describe_entry, fills_in_profile, is_credited, would_fill)


def test_new_entity_card_fills_mixed_band_and_mode(reference):
    card = PaperQSL(3, "20M", CW)
    ok, msg, slots = describe_entry(card, {}, DEFAULT_PROFILE, reference)
    assert ok and slots == [MIXED, CW, "20M"]
    assert "Mixed" in msg and "20 m" in msg


def test_credited_entity_card_fills_only_missing_slots(reference):
    credits = {1: frozenset({MIXED, CW, "40M"})}
    assert fills_in_profile(PaperQSL(1, "20M", CW), credits, DEFAULT_PROFILE) == ["20M"]
    assert fills_in_profile(PaperQSL(1, "40M", PHONE), credits, DEFAULT_PROFILE) == [PHONE]


def test_card_adding_nothing_is_refused(reference):
    credits = {1: frozenset({MIXED, CW, "20M"})}
    ok, msg, slots = describe_entry(PaperQSL(1, "20M", CW), credits, DEFAULT_PROFILE, reference)
    assert not ok and "already credited" in msg and slots == []


def test_card_outside_profile_is_accepted_with_note(reference):
    credits = {1: frozenset({MIXED, CW})}
    ok, msg, slots = describe_entry(PaperQSL(1, "2M", CW), credits, DEFAULT_PROFILE, reference)
    assert ok and slots == [] and "outside your profile" in msg
    with_2m = Profile(bands=DEFAULT_PROFILE.bands + ("2M",))
    assert fills_in_profile(PaperQSL(1, "2M", CW), credits, with_2m) == ["2M"]


def test_validation(reference):
    assert check_card(PaperQSL(196, "20M", CW), reference)            # deleted entity
    assert check_card(PaperQSL(1, "11M", CW), reference)              # unknown band
    assert check_card(PaperQSL(1, "20M", "SSB"), reference)           # use the category, not SSB
    assert check_card(PaperQSL(1, None, CW), reference)               # band required
    assert check_card(PaperQSL(1, None, SAT), reference) is None      # satellite: no band
    assert "band" in check_card(PaperQSL(1, "2M", SAT), reference)    # satellite with a band
    assert check_card(PaperQSL(1, "20M", CW, state="lost"), reference)


def test_credited_after_import():
    card = PaperQSL(1, "20M", CW)
    assert not is_credited(card, {1: frozenset({MIXED, CW})})
    assert is_credited(card, {1: frozenset({MIXED, CW, "20M"})})
    assert would_fill(card, {}) == [MIXED, CW, "20M"]


def test_counts_by_state():
    cards = [PaperQSL(1, "20M", CW), PaperQSL(3, "15M", PHONE, SUBMITTED), PaperQSL(4, "17M", CW)]
    assert counts_by_state(cards) == {IN_HAND: 2, SUBMITTED: 1}


def test_cards_never_reach_the_lotw_check(credits):
    # The Account Status cross-check takes LoTW marks only; cards have their
    # own type, so they cannot be passed in by mistake as LoTW marks.
    from app.marks import counts_by_category
    import pytest
    with pytest.raises(AttributeError):
        counts_by_category([PaperQSL(1, "20M", CW)])


def test_satellite_card_counts_only_satellite(reference):
    # ARRL: Satellite DXCC is separate — no Mixed, mode or band credit.
    card = PaperQSL(3, None, SAT)
    assert card.categories == [SAT]
    with_sat = Profile(modes=(CW, PHONE, "DIGITAL", SAT))
    assert fills_in_profile(card, {}, with_sat) == [SAT]
    # Dan's profile doesn't track Satellite: even for a new entity it fills nothing.
    ok, msg, slots = describe_entry(card, {}, DEFAULT_PROFILE, reference)
    assert ok and slots == [] and "outside your profile" in msg
