from app.categories import CW, MIXED, PHONE
from app.parser import parse_text
from app.validate import CLEAN, HELD, REJECTED, validate
from conftest import render_paste


def run(text, reference, current=None):
    return validate(parse_text(text), reference, current)


def test_clean_first_import(paste, reference, credits):
    res = run(paste, reference)
    assert res.status == CLEAN, res.errors
    assert res.credits == credits
    assert res.rows_read == 402


def test_deleted_entities_never_counted(paste, reference):
    res = run(paste, reference)
    assert all(not reference.by_dxcc[d].deleted for d in res.credits)


def test_increase_is_clean(reference, credits):
    old = dict(credits)
    old.pop(1)                                   # Canada not yet credited before
    res = run(render_paste(reference, credits), reference, current=old)
    assert res.status == CLEAN


def test_unknown_entity_rejected(paste, reference):
    res = run(paste.replace("\tCANADA\t", "\tNEW ISLAND\t"), reference)
    assert res.status == REJECTED
    assert any("NEW ISLAND" in e and "not in the reference" in e for e in res.errors)
    assert res.credits == {}


def test_deleted_flag_mismatch_rejected(paste, reference):
    res = run(paste.replace("BLENHEIM REEF\tYes", "BLENHEIM REEF\t "), reference)
    assert res.status == REJECTED
    assert any("BLENHEIM REEF" in e and "deleted" in e for e in res.errors)


def test_duplicate_row_rejected(paste, reference):
    line = next(ln for ln in paste.split("\r\n") if "\tCANADA\t" in ln)
    res = run(paste + line + "\r\n", reference)
    assert res.status == REJECTED and any("twice" in e for e in res.errors)


def test_truncated_paste_rejected(paste, reference):
    lines = paste.split("\r\n")
    res = run("\r\n".join(lines[:200]), reference)
    assert res.status == REJECTED
    assert any("incomplete" in e for e in res.errors)


def test_parser_errors_reject(paste, reference):
    res = run(paste.replace("Mix\tPh", "Ph\tMix"), reference)
    assert res.status == REJECTED


def test_decrease_is_held(reference, credits):
    lower = dict(credits)
    lower[1] = credits[1] - {CW}
    res = run(render_paste(reference, lower), reference, current=credits)
    assert res.status == HELD
    assert any("CW credits went down" in w for w in res.warnings)
    assert any("CANADA" in w and "lost a credit" in w for w in res.warnings)
    assert res.credits == lower                  # still available for "Save anyway"


def test_entity_disappearing_is_held(reference, credits):
    lower = dict(credits)
    del lower[1]
    res = run(render_paste(reference, lower), reference, current=credits)
    assert res.status == HELD


def test_mixed_blank_with_other_credits_is_held(reference, credits):
    odd = dict(credits)
    odd[1] = frozenset({PHONE})
    res = run(render_paste(reference, odd), reference)
    assert res.status == HELD
    assert any("Mixed is blank" in w for w in res.warnings)


def test_identical_reimport_is_clean(paste, reference, credits):
    assert run(paste, reference, current=credits).status == CLEAN
    assert MIXED in run(paste, reference).credits[1]


def test_satellite_only_entity_is_not_held(reference, credits):
    # Satellite DXCC is separate (D43): Mixed stays blank for a satellite-only credit.
    from app.categories import SAT
    sat_only = dict(credits)
    missing = next(e.dxcc for e in reference.current if e.dxcc not in credits)
    sat_only[missing] = frozenset({SAT})
    res = run(render_paste(reference, sat_only), reference)
    assert res.status == CLEAN, res.warnings
