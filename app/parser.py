"""
Read the LoTW Award Credit Matrix into rows. No database, no reference
table — this module only checks the *shape* of the input. validate.py
checks the content.

Accepted inputs (all reduce to the same list of cell rows):
  * Text pasted from LoTW (tab-delimited). Verified format, 2026-09-30 and
    2026-10-05: two title lines, then a header split over three lines —
        Prefix
        (Sorted by)<TAB>Entity
        (Sort by)<TAB>Deleted<TAB>Mix<TAB>Ph ... <TAB>2
    then one row per entity: Prefix, Entity, Deleted, 16 credit cells.
    Credits are "X"; empty cells are a single space; deleted entities show
    "Yes"; Spratly Islands has a blank prefix.
  * The same table saved from a spreadsheet as .xlsx or .csv (Dan's
    current routine). There the header is one row
        Prefix, Entity, Deleted, Mix, Ph, ... 2
    followed by a "(Sorted by) / (Sort by)" row.

The account's callsign is taken from the "Name, Callsign" title line
(e.g. "Allen Marshall, N4MI"), so the app shows whose data it is without
hard-coding anyone's call. Only the callsign is kept, never the name.

Rules (strict on purpose — a credit landing in the wrong column would be
worse than a rejected paste):
  * The header's credit columns must read exactly Deleted, Mix, Ph, CW, RT,
    SAT, 160, 80, 40, 30, 20, 17, 15, 12, 10, 6, 2.
  * Lines before the header are ignored (titles).
  * After the header every non-blank row must be a 19-field entity row.
  * Credit cells must be X (any case) or blank; Deleted must be Yes or blank.
"""

import csv
import io
import re
from dataclasses import dataclass, field

from .categories import MATRIX_COLUMNS

EXPECTED_HEADER = ("deleted",) + tuple(label.lower() for label, _ in MATRIX_COLUMNS)
ROW_FIELDS = 3 + len(MATRIX_COLUMNS)          # prefix, entity, deleted, 16 cells
SORT_LABELS = {"(sorted by)", "(sort by)"}
CALLSIGN = re.compile(r"^(?=.*[0-9])(?=.*[A-Z])[A-Z0-9/]{3,15}$")
MAX_ERRORS = 20


@dataclass(frozen=True)
class MatrixRow:
    line: int            # 1-based line (or spreadsheet row) number, for messages
    prefix: str
    name: str
    deleted: bool
    credits: frozenset   # category codes with an X


@dataclass
class ParseResult:
    rows: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    callsign: str | None = None      # from the "Name, Callsign" title line, if found

    @property
    def ok(self):
        return not self.errors


class UploadError(ValueError):
    """The uploaded file could not be read at all."""


def _clean(value):
    """Cell value as trimmed text. Spreadsheet numbers (160) become '160'."""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).replace("\xa0", " ").strip()


def _trim(cells):
    """Drop trailing empty cells (spreadsheets and some editors add them)."""
    cells = list(cells)
    while cells and cells[-1] == "":
        cells.pop()
    return cells


def _header_index(cells):
    """Position of 'Deleted' if this row is the matrix header, else None.

    The expected columns must be the last non-empty cells on the line, so a
    new column added after "2" is noticed rather than silently ignored.
    """
    low = [c.lower() for c in cells]
    n = len(EXPECTED_HEADER)
    for i in range(len(low) - n + 1):
        if tuple(low[i:i + n]) == EXPECTED_HEADER and not any(low[i + n:]):
            return i
    return None


def _callsign_from_title(cells):
    """'Allen Marshall, N4MI' -> 'N4MI'; anything else -> None."""
    text = " ".join(c for c in cells if c)
    if "," not in text:
        return None
    candidate = text.rsplit(",", 1)[1].strip().upper()
    return candidate if CALLSIGN.match(candidate) else None


def _looks_like_header_attempt(cells):
    low = {c.lower() for c in cells}
    return "deleted" in low and "mix" in low


def parse_cells(cell_rows):
    """Parse an iterable of (line_number, [cell, ...]) into a ParseResult."""
    result = ParseResult()
    header_found = False
    for line, raw in cell_rows:
        full = [_clean(c) for c in raw]
        cells = _trim(full)
        if not header_found:
            idx = _header_index(cells)
            if idx is not None:
                if idx not in (1, 2):
                    result.errors.append(f"Line {line}: the header columns are not where expected.")
                    return result
                header_found = True
            elif result.callsign is None and _callsign_from_title(cells):
                result.callsign = _callsign_from_title(cells)
                continue
            elif _looks_like_header_attempt(cells):
                result.errors.append(
                    f"Line {line}: the column headings do not match the LoTW matrix "
                    "(expected Deleted, Mix, Ph, CW, RT, SAT, 160, 80, 40, 30, 20, 17, 15, "
                    "12, 10, 6, 2). Nothing was imported.")
                return result
            continue

        if not cells or all(c == "" for c in cells):
            continue
        if {c.lower() for c in cells if c} <= SORT_LABELS:
            continue                       # the spreadsheet's "(Sorted by)" row
        if len(result.errors) >= MAX_ERRORS:
            result.errors.append("Too many problems to list; stopped reading. Nothing was imported.")
            return result
        if len(cells) < 2:
            # Prefix and entity name are always present (a blank prefix still
            # leaves an empty first cell before the name).
            result.errors.append(f"Line {line}: incomplete row {' | '.join(cells)!r}.")
            continue
        # Every entity row must arrive at full width. LoTW writes a single
        # space in each empty cell and spreadsheets keep empty cells, so a row
        # with fewer than 19 fields has a missing tab (its credits would shift
        # into the wrong columns) or was cut off mid-row. Fields beyond 19 are
        # allowed only if blank (trailing tabs).
        if len(full) < ROW_FIELDS or len(cells) > ROW_FIELDS:
            result.errors.append(
                f"Line {line} ({cells[1] if len(cells) > 1 else '?'}): "
                f"{len(cells) if len(cells) > ROW_FIELDS else len(full)} columns, expected "
                f"{ROW_FIELDS}. A tab may be missing or extra, or the row was cut off.")
            continue
        cells += [""] * (ROW_FIELDS - len(cells))
        prefix, name, deleted = cells[0], cells[1], cells[2]
        if not name:
            result.errors.append(f"Line {line}: entity name is blank.")
            continue
        if deleted.lower() not in ("", "yes"):
            result.errors.append(f"Line {line} ({name}): Deleted column reads {deleted!r}.")
            continue
        credits, bad = set(), []
        for (label, code), value in zip(MATRIX_COLUMNS, cells[3:]):
            v = value.upper()
            if v == "X":
                credits.add(code)
            elif v != "":
                bad.append(f"{label}={value!r}")
        if bad:
            result.errors.append(f"Line {line} ({name}): unexpected cell value {', '.join(bad)}.")
            continue
        result.rows.append(MatrixRow(line, prefix, name, deleted.lower() == "yes",
                                     frozenset(credits)))

    if not header_found:
        result.errors.append("No LoTW matrix header found (the line with Deleted, Mix, Ph, CW, "
                             "RT, SAT, 160 ... 2). Nothing was imported.")
    return result


def parse_text(text):
    """Parse pasted or .txt text. Tab-delimited; CRLF or LF line endings."""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    if not text.strip():
        return ParseResult(errors=["The paste is empty."])
    lines = text.split("\n")
    return parse_cells((i + 1, ln.split("\t")) for i, ln in enumerate(lines))


def _decode(data):
    """UTF-8 (with or without BOM), else Windows-1252; otherwise a clear error."""
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    raise UploadError("The file isn't readable text. Copy the matrix from LoTW again, or "
                      "save the file from Notepad as UTF-8.")


def parse_csv_bytes(data):
    text = _decode(data)
    try:
        reader = list(csv.reader(io.StringIO(text)))
    except csv.Error as exc:
        raise UploadError(f"The CSV file couldn't be read: {exc}") from exc
    return parse_cells((i + 1, row) for i, row in enumerate(reader))


def parse_xlsx_bytes(data):
    try:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:  # corrupt or not really a workbook
        raise UploadError(f"Could not open the spreadsheet: {exc}") from exc
    try:
        ws = wb.worksheets[0]
        rows = [(i + 1, list(r)) for i, r in enumerate(ws.iter_rows(values_only=True))]
    except Exception as exc:  # opens, but fails while reading
        raise UploadError(f"Could not read the spreadsheet: {exc}") from exc
    finally:
        wb.close()
    return parse_cells(rows)


def parse_upload(filename, data):
    """Dispatch an uploaded file by extension (.txt/.tsv, .csv, .xlsx)."""
    name = (filename or "").lower()
    if name.endswith(".xlsx"):
        return parse_xlsx_bytes(data)
    if name.endswith(".csv"):
        return parse_csv_bytes(data)
    if name.endswith((".txt", ".tsv")):
        return parse_text(_decode(data))
    raise UploadError("Unsupported file type. Use .txt, .csv or .xlsx.")
