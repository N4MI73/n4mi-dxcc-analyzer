from app.analysis import totals
from app.categories import BANDS, CW, DEFAULT_PROFILE, DIGITAL, MIXED, PHONE
from app.marks import AWAITING, WONT_SUBMIT, Mark
from app.status_check import compare, parse_status

LABEL = {MIXED: "Mixed", CW: "CW", PHONE: "Phone", DIGITAL: "Digital",
         **{b: b for b in BANDS}}


def status_text(credits, pending=None, star=True):
    """Synthetic Account Status paste in LoTW's layout (verified 2026-10-05)."""
    pending = pending or {}
    t = totals(credits)
    lines = ["DXCC", "Award\tNew LoTW QSLs\tLoTW QSLs in Process\tDXCC Credits Awarded\tTotal",
             "(All)\tTotal", "(Current)"]
    for cat in (MIXED, CW, PHONE, DIGITAL) + BANDS:
        new = pending.get(cat, 0)
        name = LABEL[cat] + (" *" if star and cat != "160M" else "")
        lines.append(f"{name}\t{new}\t0\t{t[cat]}\t{t[cat] + new}\t{t[cat] + new}")
    lines.append("70CM\t0\t0\t1\t1\t1")
    lines.append("Challenge *\t5\t0\t900\t---\t905")
    return "\r\n".join(lines)


def test_parse(credits):
    st = parse_status(status_text(credits, {PHONE: 4}))
    assert st.ok, st.errors
    assert st.rows[PHONE].new == 4 and st.rows[PHONE].pending == 4
    assert st.rows[MIXED].awarded == len(credits)
    assert "CHALLENGE" in st.rows and "70CM" in st.rows


def test_reconciles(credits):
    res = compare(parse_status(status_text(credits)), credits, [], DEFAULT_PROFILE)
    assert res.reconciled
    assert res.not_checked == ["70CM", "CHALLENGE"]
    assert len(res.reconciliation) == 15            # Mixed, CW, Phone, Digital, 160-2 m


def test_mismatch_detected(credits):
    text = status_text(credits)
    fewer = dict(credits)
    fewer.pop(next(iter(fewer)))
    res = compare(parse_status(text), fewer, [], DEFAULT_PROFILE)
    assert not res.reconciled
    bad = [x for x in res.reconciliation if not x.ok]
    assert any(x.category == MIXED and x.lotw == x.app + 1 for x in bad)


def test_pending_compare_counts_wont_submit(credits):
    st = parse_status(status_text(credits, {PHONE: 2, "15M": 1}))
    marks = [Mark(1, PHONE, AWAITING), Mark(3, PHONE, WONT_SUBMIT)]
    res = compare(st, credits, marks, DEFAULT_PROFILE)
    by = {x.category: x for x in res.pending}
    assert by[PHONE].ok
    assert not by["15M"].ok and by["15M"].lotw == 1 and by["15M"].app == 0
    assert "2M" not in by                            # outside the profile


def test_incomplete_table_rejected(credits):
    text = "\r\n".join(ln for ln in status_text(credits).split("\r\n") if not ln.startswith("20M"))
    st = parse_status(text)
    assert not st.ok and "20M" in st.errors[0].replace(" m", "M")


def test_unreadable_numbers(credits):
    text = status_text(credits).replace("Mixed *\t0", "Mixed *\tn/a")
    assert any("Mixed" in e for e in parse_status(text).errors)


def test_without_award_stars(credits):
    assert parse_status(status_text(credits, star=False)).ok


def test_wrong_table_rejected(credits):
    # Same row names, but not the DXCC Account Status headings.
    text = status_text(credits).replace("DXCC Credits Awarded", "WAS Credits Awarded")
    st = parse_status(text)
    assert not st.ok and "Account Status" in st.errors[0]


def test_reordered_columns_rejected(credits):
    text = status_text(credits).replace(
        "New LoTW QSLs\tLoTW QSLs in Process", "LoTW QSLs in Process\tNew LoTW QSLs")
    assert not parse_status(text).ok


def test_compare_refuses_incomplete_parse(credits):
    import pytest
    st = parse_status("nothing useful")
    with pytest.raises(ValueError):
        compare(st, credits, [], DEFAULT_PROFILE)


def test_unicode_digits_rejected_cleanly(credits):
    text = status_text(credits).replace("Mixed *\t0", "Mixed *\t³")
    assert any("Mixed" in e for e in parse_status(text).errors)
