"""
Optional cross-check against LoTW's Account Status table (spec section 7).

Dan copies the Account Status table from LoTW and pastes it. Verified format
(2026-10-05): a header split over several lines, then one tab-delimited row
per award:

    Mixed *<TAB>3<TAB>0<TAB>274<TAB>277<TAB>277
    ...
    Challenge *<TAB>21<TAB>0<TAB>1645<TAB>---<TAB>1666

Columns: award, New LoTW QSLs, LoTW QSLs in Process, DXCC Credits Awarded,
Total (All), Total (Current). "*" after the award name means the award has
been issued and is ignored.

Two checks against the current snapshot:
  1. Reconciliation: "DXCC Credits Awarded" must equal the app's count for
     Mixed, CW, Phone, Digital and every band in the matrix (160-2 m). A
     mismatch is a defect.
  2. Pending marks: for Mixed and each profile category, LoTW's pending
     count (New + In Process) is compared with Dan's active marks (awaiting
     + won't submit, since LoTW keeps listing a QSL Dan won't submit).
     Assumption A3, confirmed by Dan 2026-10-05.

Not checkable from the matrix: 70 cm (no matrix column), Challenge, Satellite.
"""

import re
from dataclasses import dataclass, field

from .analysis import totals
from .categories import BANDS, CW, DIGITAL, LABELS, MIXED, PHONE, TRACKED
from .marks import counts_by_category

AWARD_NAMES = {"MIXED": MIXED, "CW": CW, "PHONE": PHONE, "DIGITAL": DIGITAL,
               **{b: b for b in BANDS}, "70CM": "70CM", "CHALLENGE": "CHALLENGE"}
NOT_CHECKED = ("70CM", "CHALLENGE")


@dataclass(frozen=True)
class StatusRow:
    new: int
    in_process: int
    awarded: int

    @property
    def pending(self):
        return self.new + self.in_process


@dataclass
class StatusParse:
    rows: dict = field(default_factory=dict)       # category -> StatusRow
    errors: list = field(default_factory=list)

    @property
    def ok(self):
        return not self.errors


HEADINGS = ("new lotw qsls", "lotw qsls in process", "dxcc credits awarded")


def _int(v):
    v = v.strip().replace(",", "")
    return int(v) if re.fullmatch(r"[0-9]+", v) else None


def _is_heading_line(cells):
    """True for the line naming the columns, in LoTW's order (verified
    2026-10-05): Award, New LoTW QSLs, LoTW QSLs in Process, DXCC Credits
    Awarded, Total. The numbers are read by position, so the order matters."""
    low = [" ".join(c.lower().split()) for c in cells]
    return len(low) >= 4 and tuple(low[1:4]) == HEADINGS


def parse_status(text):
    out = StatusParse()
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    headings_seen = False
    for n, line in enumerate(text.split("\n"), 1):
        cells = [c.replace("\xa0", " ").strip() for c in line.split("\t")]
        if _is_heading_line(cells):
            headings_seen = True
            continue
        if len(cells) < 4:
            continue
        key = cells[0].replace("*", "").strip().upper()
        cat = AWARD_NAMES.get(key)
        if cat is None:
            continue                     # header fragments and anything else
        new, proc, awarded = _int(cells[1]), _int(cells[2]), _int(cells[3])
        if None in (new, proc, awarded):
            out.errors.append(f"Line {n}: could not read the numbers for {cells[0]!r}.")
            continue
        if cat in out.rows:
            out.errors.append(f"Line {n}: {cells[0]!r} appears twice.")
            continue
        out.rows[cat] = StatusRow(new, proc, awarded)
    if not headings_seen:
        out.errors.insert(0, "This does not look like LoTW's DXCC Account Status table (the line "
                             "with New LoTW QSLs, LoTW QSLs in Process, DXCC Credits Awarded "
                             "was not found).")
        return out
    missing = [LABELS[c] for c in TRACKED if c not in out.rows]
    if missing:
        out.errors.append("This does not look like the complete Account Status table "
                          f"(missing: {', '.join(missing)}).")
    return out


@dataclass(frozen=True)
class Line:
    category: str
    app: int
    lotw: int

    @property
    def ok(self):
        return self.app == self.lotw


@dataclass
class CheckResult:
    reconciliation: list          # Line(category, app count, LoTW awarded)
    pending: list                 # Line(category, marks, LoTW new+in process)
    not_checked: list

    @property
    def reconciled(self):
        return all(x.ok for x in self.reconciliation)

    @property
    def pending_match(self):
        return all(x.ok for x in self.pending)


def compare(status, credits, marks, profile):
    if not status.ok:
        raise ValueError("compare() needs a successfully parsed Account Status table.")
    app = totals(credits)
    recon = [Line(c, app.get(c, 0), status.rows[c].awarded) for c in TRACKED]
    mark_counts = counts_by_category(marks)
    pending = [Line(c, mark_counts.get(c, 0), status.rows[c].pending)
               for c in profile.markable_categories]
    return CheckResult(recon, pending, [c for c in NOT_CHECKED if c in status.rows])
