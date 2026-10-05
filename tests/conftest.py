"""
Shared test fixtures.

All test data is SYNTHETIC: an invented credit pattern applied to the
public DXCC reference table, rendered in the exact LoTW paste format. No
real LoTW data is ever committed to this repository.
"""

import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.categories import MATRIX_CATEGORIES, MATRIX_COLUMNS, MIXED, SAT  # noqa: E402
from app.reference import load_reference  # noqa: E402

HEADER_LABELS = [label for label, _ in MATRIX_COLUMNS]


@pytest.fixture(scope="session")
def reference():
    return load_reference()


def synthetic_credits(reference):
    """Invented, deterministic credits: about 3/4 of entities credited,
    each with a varying spread of categories. Never Satellite."""
    credits = {}
    for e in reference.current:
        if e.dxcc % 4 == 0:
            continue                       # never credited
        cats = {MIXED}
        for i, cat in enumerate(MATRIX_CATEGORIES):
            if cat in (MIXED, SAT):
                continue
            if (e.dxcc * 7 + i * 3) % 5 != 0:
                cats.add(cat)
        credits[e.dxcc] = frozenset(cats)
    return credits


@pytest.fixture
def credits(reference):
    return synthetic_credits(reference)


def matrix_rows(reference, credits):
    """Rows as LoTW lists them: sorted by prefix, deleted entities included."""
    rows = []
    for e in sorted(reference.entities, key=lambda e: (e.prefix, e.lotw_name)):
        cats = credits.get(e.dxcc, frozenset()) if not e.deleted else frozenset()
        cells = ["X" if c in cats else "" for c in MATRIX_CATEGORIES]
        rows.append([e.prefix, e.lotw_name, "Yes" if e.deleted else ""] + cells)
    return rows


def render_paste(reference, credits, newline="\r\n"):
    """Render the exact LoTW paste layout (verified 2026-09-30, 2026-10-05)."""
    lines = [
        "DXCC Award Credit Report",
        "Test Operator, N0CALL",
        "Prefix",
        "(Sorted by)\tEntity",
        "(Sort by)\t" + "\t".join(["Deleted"] + HEADER_LABELS),
    ]
    for r in matrix_rows(reference, credits):
        # LoTW shows empty cells as a single space.
        lines.append("\t".join(c if c else " " for c in r))
    return newline.join(lines) + newline


def render_xlsx(reference, credits):
    """The spreadsheet route: one-line header, a (Sorted by) row, None blanks."""
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["DXCC Award Credit Report"])
    ws.append(["Test Operator, N0CALL"])
    ws.append(["Prefix", "Entity", "Deleted"] +
              [int(x) if x.isdigit() else x for x in HEADER_LABELS])
    ws.append(["(Sorted by)", "(Sort by)"])
    for r in matrix_rows(reference, credits):
        ws.append([c if c else None for c in r])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def render_csv(reference, credits):
    import csv
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["DXCC Award Credit Report"])
    w.writerow(["Prefix", "Entity", "Deleted"] + HEADER_LABELS)
    w.writerow(["(Sorted by)", "(Sort by)"])
    for r in matrix_rows(reference, credits):
        w.writerow(r)
    return buf.getvalue().encode("utf-8")


@pytest.fixture
def paste(reference, credits):
    return render_paste(reference, credits)
