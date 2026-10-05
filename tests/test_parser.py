import pytest

from app.categories import MIXED
from app.parser import UploadError, parse_text, parse_upload
from conftest import render_csv, render_paste, render_xlsx


def by_name(result):
    return {(r.name, r.deleted): r for r in result.rows}


def test_paste_parses_all_rows(paste, reference, credits):
    res = parse_text(paste)
    assert res.ok, res.errors
    assert len(res.rows) == 402
    rows = by_name(res)
    for e in reference.current:
        assert rows[(e.lotw_name, False)].credits == credits.get(e.dxcc, frozenset())


def test_lf_line_endings_and_trailing_tabs(reference, credits):
    text = render_paste(reference, credits, newline="\n").replace("\n", "\t\n")
    res = parse_text(text)
    assert res.ok, res.errors[:3]
    assert len(res.rows) == 402


def test_non_breaking_spaces_are_blank(reference, credits):
    res = parse_text(render_paste(reference, credits).replace("\t \t", "\t\xa0\t"))
    assert res.ok, res.errors[:3]


def test_deleted_and_blank_prefix_rows(paste):
    rows = by_name(parse_text(paste))
    assert rows[("ABU AIL ISLANDS", True)].deleted
    assert rows[("SPRATLY ISLANDS", False)].prefix == ""


def test_lowercase_x_accepted(reference, credits):
    text = render_paste(reference, credits).replace("\tX\t", "\tx\t", 3)
    assert parse_text(text).ok


def test_empty_paste():
    res = parse_text("   \n ")
    assert not res.ok and "empty" in res.errors[0]


def test_no_header():
    res = parse_text("CANADA\tX\tX\n")
    assert not res.ok and "header" in res.errors[0]


def test_reordered_columns_rejected(paste):
    bad = paste.replace("Mix\tPh\tCW", "Mix\tCW\tPh")
    res = parse_text(bad)
    assert not res.ok and "column headings" in res.errors[0]
    assert res.rows == []


def test_missing_column_rejected(paste):
    res = parse_text(paste.replace("\tSAT\t", "\t"))
    assert not res.ok


def test_bad_cell_value(paste):
    bad = paste.replace("CANADA\t \tX", "CANADA\t \tY")
    res = parse_text(bad)
    assert any("CANADA" in e and "'Y'" in e for e in res.errors)


def test_bad_deleted_value(paste):
    bad = paste.replace("BLENHEIM REEF\tYes", "BLENHEIM REEF\tNo")
    res = parse_text(bad)
    assert any("BLENHEIM REEF" in e for e in res.errors)


def test_too_many_columns(paste):
    bad = paste.replace("CANADA\t \tX", "CANADA\t \tX\tX\tX\tX\tX", 1)
    assert any("columns" in e for e in parse_text(bad).errors)


def test_error_list_is_capped():
    header = "(Sort by)\tDeleted\tMix\tPh\tCW\tRT\tSAT\t160\t80\t40\t30\t20\t17\t15\t12\t10\t6\t2\n"
    text = header + "".join(f"P\tE{i}\tMaybe\n" for i in range(100))
    errors = parse_text(text).errors
    assert len(errors) <= 21 and "Too many problems" in errors[-1]


def test_xlsx_upload_matches_paste(reference, credits, paste):
    x = parse_upload("matrix.xlsx", render_xlsx(reference, credits))
    assert x.ok, x.errors[:3]
    assert {k: r.credits for k, r in by_name(x).items()} == \
           {k: r.credits for k, r in by_name(parse_text(paste)).items()}


def test_csv_upload_handles_commas_in_prefixes(reference, credits):
    res = parse_upload("matrix.csv", render_csv(reference, credits))
    assert res.ok, res.errors[:3]
    assert by_name(res)[("VIET NAM", False)].prefix == "3W, XV"


def test_txt_upload(paste):
    assert parse_upload("matrix.txt", paste.encode("utf-8")).ok


def test_unsupported_upload():
    with pytest.raises(UploadError):
        parse_upload("matrix.pdf", b"%PDF")


def test_corrupt_xlsx():
    with pytest.raises(UploadError):
        parse_upload("matrix.xlsx", b"not a workbook")


def test_mixed_column_maps_to_mixed(paste):
    assert MIXED in by_name(parse_text(paste))[("UNITED STATES OF AMERICA", False)].credits


# --- Misaligned rows (independent review, 2026-10-05) -----------------------

def _canada_line(paste):
    return next(ln for ln in paste.split("\r\n") if "\tCANADA\t" in ln)


def test_missing_tab_rejected(paste):
    line = _canada_line(paste)
    bad = paste.replace(line, line.replace("\t \t", "\t", 1))
    res = parse_text(bad)
    assert not res.ok and any("CANADA" in e and "tab" in e for e in res.errors)


def test_extra_tab_rejected(paste):
    line = _canada_line(paste)
    cells = line.split("\t")
    shifted = "\t".join(cells[:4] + ["X"] + cells[4:-1] + [cells[-1], "X"])
    res = parse_text(paste.replace(line, shifted))
    assert not res.ok


def test_row_cut_off_mid_line_rejected(paste):
    lines = paste.rstrip("\r\n").split("\r\n")
    lines.append(_canada_line(paste)[:30])          # a partial final row
    res = parse_text("\r\n".join(lines))
    assert not res.ok


def test_trailing_blank_fields_allowed(paste):
    assert parse_text(paste.replace("\r\n", "\t\t\r\n")).ok


def test_extra_header_column_rejected(paste):
    res = parse_text(paste.replace("\t6\t2\r\n", "\t6\t2\t70\r\n", 1))
    assert not res.ok


def test_excel_copied_text_with_empty_cells(reference, credits):
    # Copying from Excel gives tab-separated text with truly empty cells.
    from conftest import matrix_rows, HEADER_LABELS
    lines = ["Prefix\tEntity\tDeleted\t" + "\t".join(HEADER_LABELS), "(Sorted by)\t(Sort by)"]
    lines += ["\t".join(r) for r in matrix_rows(reference, credits)]
    res = parse_text("\r\n".join(lines))
    assert res.ok, res.errors[:3]
