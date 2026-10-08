"""
CSV and workbook exports (spec section 10; DXMon bridge D48).

Every export follows the operating PROFILE, never a page's temporary filters,
so a file always means the same thing.

Files:
  missing_entities.csv   never-credited entities with marks and paper cards
  missing_slots.csv      one row per entity with a profile band/mode need (never-
                         credited entities included, D51, flagged in the last
                         column); one column per profile band/mode:
                         Needed / Awaiting / Won't submit / Card
  no_confirms.csv        DXMon bridge: exactly "Entity","Prefix", LoTW names,
                         every field quoted, NO byte-order mark (DXMon reads plain
                         UTF-8 and looks up the column named exactly "Entity")
  dxcc_analysis_YYYY-MM-DD.xlsx   multi-sheet workbook
"""

import csv
import io

from . import analysis
from .categories import LABELS, MATRIX_CATEGORIES, MIXED, SAT
from .paper import fills_in_profile

MARK_TEXT = {"awaiting": "Awaiting", "wont_submit": "Won't submit"}


def user_text(value):
    """Text the user typed (notes, calls, dates) as a plain-text cell.

    Spreadsheets treat a cell starting with = + - @ (or a tab/CR) as a formula.
    A leading apostrophe keeps it as text in both the CSV and the workbook
    (review fix: a note like "=HYPERLINK(...)" must never become live)."""
    v = "" if value is None else str(value)
    return "'" + v if v[:1] in ("=", "+", "-", "@", "\t", "\r") else v
CARD_TEXT = {"in_hand": "In hand", "submitted": "Submitted"}
CONTINENT = {"AF": "Africa", "AS": "Asia", "OC": "Oceania", "EU": "Europe",
             "SA": "South America", "NA": "North America", "AN": "Antarctica"}


class ExportData:
    """Everything an export needs, gathered once."""

    def __init__(self, credits, reference, profile, marks, cards, rankings, snapshot,
                 status_check=None):
        self.credits, self.reference, self.profile = credits, reference, profile
        self.marks = {(m.dxcc, m.category): m for m in marks}
        self.cards = cards
        self.rankings = rankings
        self.snapshot = snapshot
        self.status_check = status_check
        # (dxcc, category) -> card states, for cards still filling that slot
        self.card_slots = {}
        for c in cards:
            for cat in fills_in_profile(c, credits, profile):
                self.card_slots.setdefault((c.dxcc, cat), []).append(c.state)
        self.missing = analysis.missing_entities(credits, reference)
        # Award view (D51): never-credited entities need every profile slot too.
        self.needed = analysis.needed_slots(credits, reference, profile, include_new=True)
        self.sat = analysis.satellite_needs(credits, reference, profile)
        self.columns = list(profile.bands) + list(profile.modes)   # bands first, as on screen

    def slot_state(self, dxcc, cat):
        """Text for one needed slot: mark first, then paper card, else Needed."""
        m = self.marks.get((dxcc, cat))
        parts = [MARK_TEXT[m.state]] if m else []
        if (dxcc, cat) in self.card_slots:
            parts.append("Card")
        return ", ".join(parts) or "Needed"

    def needs_of(self, dxcc):
        """Profile categories this entity still needs (Satellite included
        when in the profile, since Satellite needs span every entity, D44)."""
        need = list(self.needed.get(dxcc, ()))
        if SAT in self.profile.modes and dxcc in self.sat:
            need.append(SAT)
        return need


def _csv(rows, header):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(header)
    w.writerows(rows)
    return buf.getvalue().encode("utf-8")


def _label(cat):
    return LABELS[cat]


def missing_entities_rows(d):
    rows = []
    for e in d.missing:
        m = d.marks.get((e.dxcc, MIXED))
        cards = d.card_slots.get((e.dxcc, MIXED), [])
        rows.append([e.dxcc, e.prefix, e.lotw_name, CONTINENT.get(e.continent, e.continent),
                     e.cq_zone or "", d.rankings.get(e.dxcc, ""),
                     MARK_TEXT[m.state] if m else "", user_text(m.note) if m else "",
                     ", ".join(CARD_TEXT[s] for s in cards)])
    return rows


ENTITY_HEADER = ["DXCC", "Prefix", "Entity", "Continent", "CQ zone", "Most Wanted rank",
                 "Mark", "Mark note", "Paper card"]


def missing_entities_csv(d):
    return _csv(missing_entities_rows(d), ENTITY_HEADER)


def missing_slots_rows(d):
    rows = []
    for e in d.reference.current:
        need = d.needs_of(e.dxcc)
        if not need:
            continue
        new = MIXED not in d.credits.get(e.dxcc, ())
        rows.append([e.dxcc, e.prefix, e.lotw_name, len([c for c in need if c != SAT])]
                    + [d.slot_state(e.dxcc, c) if c in need else "" for c in d.columns]
                    + ["Yes" if new else ""])
    return rows


def missing_slots_header(d):
    # "Never confirmed" is last so earlier column positions stay as they were.
    return (["DXCC", "Prefix", "Entity", "Slots needed"] + [_label(c) for c in d.columns]
            + ["Never confirmed"])


def missing_slots_csv(d):
    return _csv(missing_slots_rows(d), missing_slots_header(d))


def no_confirms_csv(d):
    """DXMon bridge: same shape as DXMon's own no_confirms.csv (Entity,Prefix,
    all fields quoted, LoTW order = by prefix). No BOM, deliberately."""
    buf = io.StringIO()
    buf.write("Entity,Prefix\n")            # header unquoted, exactly like DXMon's file
    w = csv.writer(buf, quoting=csv.QUOTE_ALL, lineterminator="\n")
    for e in sorted(d.missing, key=lambda e: (e.prefix, e.lotw_name)):
        w.writerow([e.lotw_name, e.prefix])
    return buf.getvalue().encode("utf-8")


# ---------------------------------------------------------------- workbook

def workbook(d):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    head_font = Font(bold=True, color="FFFFFF")
    head_fill = PatternFill("solid", fgColor="283040")
    need_fill = PatternFill("solid", fgColor="F5A524")
    pend_fill = PatternFill("solid", fgColor="FBE3B4")
    card_fill = PatternFill("solid", fgColor="D3ECFF")

    wb = Workbook()

    def sheet(title, header, rows, widths=None, fills=False):
        ws = wb.create_sheet(title)
        ws.append(header)
        for c in ws[1]:
            c.font, c.fill = head_font, head_fill
            c.alignment = Alignment(vertical="center")
        for r in rows:
            ws.append(r)
        ws.freeze_panes = "A2"
        if rows:
            ws.auto_filter.ref = ws.dimensions
        for i, h in enumerate(header, 1):
            longest = max([len(str(h))] + [len(str(r[i - 1])) for r in rows])
            w = (widths or {}).get(h) or max(8, min(40, longest + 2))
            ws.column_dimensions[get_column_letter(i)].width = w
        # User text was marked with a leading apostrophe by user_text(). In the
        # workbook, store the original text as a TEXT cell instead, so it reads
        # exactly as typed and can never run as a formula.
        for row in ws.iter_rows(min_row=2):
            for c in row:
                v = c.value
                if isinstance(v, str) and len(v) > 1 and v[0] == "'" and v[1] in "=+-@\t\r":
                    c.value = v[1:]
                    c.data_type = "s"
        if fills:
            for row in ws.iter_rows(min_row=2):
                for c in row:
                    if c.value == "Needed":
                        c.fill = need_fill
                    elif isinstance(c.value, str) and c.value.startswith(("Awaiting", "Won't")):
                        c.fill = pend_fill
                    elif c.value == "Card":
                        c.fill = card_fill
        return ws

    # Summary
    ws = wb.active
    ws.title = "Summary"
    s = analysis.summarize(d.credits, d.reference, d.profile)
    tot = analysis.totals(d.credits)
    snap = d.snapshot
    rows = [
        ("N4MI DXCC Analyzer — export", ""),
        ("Callsign", snap["callsign"] or ""),
        ("Matrix imported (UTC)", (snap["saved_at"] or snap["imported_at"] or "")[:16].replace("T", " ")),
        ("Profile bands", ", ".join(_label(b) for b in d.profile.bands)),
        ("Profile modes", ", ".join(_label(m) for m in d.profile.modes)),
        ("", ""),
        ("Current entities", s.entities_current),
        ("Entities credited (Mixed)", s.entities_credited),
        ("Never credited", s.entities_missing),
        ("Band and mode slots needed (award view)", s.slots_missing + s.slots_missing_new),
        ("  on credited entities", s.slots_missing),
        ("  on never-credited entities", s.slots_missing_new),
        ("Complete in profile", s.complete),
        ("One slot away", s.one_slot_away),
    ]
    if s.satellite_missing is not None:
        rows.append(("Satellite still needed", s.satellite_missing))
    chk = d.status_check
    if chk:
        recon = "matches LoTW in all categories" if chk["reconciled"] else "does NOT match LoTW"
        rows.append(("LoTW Account Status check", f"{recon} (checked {chk['checked_at'][:16].replace('T', ' ')} UTC)"))
    else:
        rows.append(("LoTW Account Status check", "not run for this import"))
    rows += [("", ""), ("Credits per category", "")]
    rows += [(_label(c), tot[c]) for c in MATRIX_CATEGORIES]
    rows += [("", ""), ("Pending marks and paper cards are never counted as credits.", "")]
    for r in rows:
        ws.append(list(r))
    ws["A1"].font = Font(bold=True, size=14)
    ws.column_dimensions["A"].width = 34
    ws.column_dimensions["B"].width = 60

    sheet("Missing Entities", ENTITY_HEADER, missing_entities_rows(d))
    sheet("Missing Slots", missing_slots_header(d), missing_slots_rows(d), fills=True)

    # By Band: missing count per profile category, with marks and cards
    by = []
    for c in d.columns:
        if c == SAT:
            ents = d.sat
        else:
            ents = [x for x, need in d.needed.items() if c in need]
        marked = sum(1 for x in ents if (x, c) in d.marks and d.marks[(x, c)].state == "awaiting")
        carded = sum(1 for x in ents if (x, c) in d.card_slots)
        new = sum(1 for x in ents if MIXED not in d.credits.get(x, ()))
        by.append([_label(c), len(ents), len(ents) - new, new, marked, carded])
    sheet("By Band", ["Band or mode", "Entities needed", "On credited entities",
                      "Never confirmed", "Awaiting credit", "Paper card"], by)

    # Matrix: every current entity, all 16 matrix columns, X = credited
    mrows = []
    for e in d.reference.current:
        have = d.credits.get(e.dxcc, frozenset())
        mrows.append([e.dxcc, e.prefix, e.lotw_name] + ["X" if c in have else "" for c in MATRIX_CATEGORIES])
    sheet("Matrix", ["DXCC", "Prefix", "Entity"] + [_label(c) for c in MATRIX_CATEGORIES], mrows,
          widths={_label(c): 8 for c in MATRIX_CATEGORIES})

    name, prefix = d.reference.name_of, d.reference.prefix_of
    prows = [[m.dxcc, prefix(m.dxcc), name(m.dxcc),
              "New entity (Mixed)" if m.category == MIXED else _label(m.category),
              MARK_TEXT[m.state], user_text(m.note)] for m in d.marks.values()]
    prows.sort(key=lambda r: (r[2], r[3]))
    sheet("Pending Marks", ["DXCC", "Prefix", "Entity", "Slot", "Mark", "Note"], prows)

    crows = [[c.dxcc, prefix(c.dxcc), name(c.dxcc),
              _label(c.band) if c.band else "", _label(c.mode), CARD_TEXT[c.state],
              ", ".join(_label(x) for x in fills_in_profile(c, d.credits, d.profile)) or "outside profile",
              user_text(c.call), user_text(c.qso_date), user_text(c.note)] for c in d.cards]
    sheet("Paper QSLs", ["DXCC", "Prefix", "Entity", "Band", "Mode", "Status", "Fills",
                         "Call", "QSO date", "Note"], crows)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()

