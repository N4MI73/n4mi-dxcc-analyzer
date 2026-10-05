from app.categories import CW, DEFAULT_PROFILE, MIXED, SAT, Profile
from app.marks import AWAITING, WONT_SUBMIT, Mark, check_mark, cleared_by, counts_by_category


def test_mark_needed_slot_allowed(reference):
    credits = {1: frozenset({MIXED})}
    assert check_mark(Mark(1, CW, AWAITING), credits, reference, DEFAULT_PROFILE) is None


def test_mark_new_entity_and_its_bands(reference):
    # A never-credited entity can have Mixed and band marks (e.g. a new one
    # confirmed on 20 m and 15 m).
    for cat in (MIXED, "20M", "15M"):
        assert check_mark(Mark(3, cat, AWAITING), {}, reference, DEFAULT_PROFILE) is None


def test_mark_refused_when_already_credited(reference):
    credits = {1: frozenset({MIXED, CW})}
    assert "already credited" in check_mark(Mark(1, CW, AWAITING), credits, reference,
                                             DEFAULT_PROFILE)


def test_2m_and_satellite_not_markable_by_default(reference):
    for cat in ("2M", SAT):
        assert check_mark(Mark(1, cat, AWAITING), {}, reference, DEFAULT_PROFILE)
    with_2m = Profile(bands=DEFAULT_PROFILE.bands + ("2M",))
    assert check_mark(Mark(1, "2M", AWAITING), {}, reference, with_2m) is None


def test_deleted_entity_not_markable(reference):
    assert check_mark(Mark(196, MIXED, AWAITING), {}, reference, DEFAULT_PROFILE)


def test_bad_state(reference):
    assert check_mark(Mark(1, MIXED, "maybe"), {}, reference, DEFAULT_PROFILE)


def test_marks_clear_when_credited():
    marks = [Mark(1, CW, AWAITING), Mark(3, MIXED, AWAITING), Mark(4, "20M", WONT_SUBMIT)]
    new = {1: frozenset({MIXED, CW}), 4: frozenset({MIXED, "20M"})}
    assert cleared_by(marks, new) == [marks[0], marks[2]]


def test_counts_include_wont_submit():
    marks = [Mark(1, "PHONE", AWAITING), Mark(2, "PHONE", WONT_SUBMIT), Mark(3, CW, AWAITING)]
    assert counts_by_category(marks) == {"PHONE": 2, CW: 1}


def test_satellite_markable_only_when_in_profile(reference):
    with_sat = Profile(modes=("CW", "PHONE", "DIGITAL", SAT))
    assert check_mark(Mark(1, SAT, AWAITING), {}, reference, DEFAULT_PROFILE)
    assert check_mark(Mark(1, SAT, AWAITING), {}, reference, with_sat) is None
