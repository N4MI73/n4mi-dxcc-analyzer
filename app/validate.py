"""
Decide whether a parsed matrix can become the current data.

Three outcomes (Phase 1 spec, section 5.3):

  rejected  Nothing is saved. Shape errors from the parser, an entity name
            not in the reference table, a Deleted flag that disagrees with
            the table, a duplicate entity, or a row count that differs from
            the table (a truncated or partial paste).
  held      Saved only if Dan deliberately chooses "Save anyway" (decision
            S6): any credit lower than in the current data, or a Mixed blank
            next to other credits. Credits normally only go up, so either
            almost certainly means a bad copy.
  clean     Normal preview, then Save.

Deleted entities are checked against the reference table and then dropped:
they never appear in credits, counts or views.

Satellite credits are stored but are not a tracked category (D11), so a
change in Satellite never holds an import.
"""

from dataclasses import dataclass, field

from .analysis import totals
from .categories import LABELS, MIXED, TRACKED

REJECTED, HELD, CLEAN = "rejected", "held", "clean"


@dataclass
class ValidationResult:
    status: str
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    credits: dict = field(default_factory=dict)    # dxcc -> frozenset(categories), current only
    totals: dict = field(default_factory=dict)
    rows_read: int = 0


def _names(reference, dxccs, limit=8):
    names = sorted(reference.by_dxcc[d].lotw_name for d in dxccs)
    more = f" and {len(names) - limit} more" if len(names) > limit else ""
    return ", ".join(names[:limit]) + more


def validate(parsed, reference, current=None):
    """Validate a ParseResult.

    `current` is the current snapshot's credits ({dxcc: frozenset}) or None
    on the first import.
    """
    res = ValidationResult(status=CLEAN, rows_read=len(parsed.rows))
    res.errors.extend(parsed.errors)
    if not parsed.rows and not parsed.errors:
        res.errors.append("No entity rows found. Nothing was imported.")

    seen = {}
    credits = {}
    for row in parsed.rows:
        ent = reference.lookup(row.name, row.deleted)
        if ent is None:
            if reference.name_exists(row.name):
                want = "deleted" if not row.deleted else "current"
                res.errors.append(
                    f"Line {row.line}: LoTW marks {row.name!r} as "
                    f"{'deleted' if row.deleted else 'current'}, but the reference table "
                    f"has it as {want}. The reference table may need an update.")
            else:
                res.errors.append(
                    f"Line {row.line}: LoTW lists {row.name!r}, which is not in the reference "
                    "table. This may be a new or renamed entity; the table needs a reviewed "
                    "update before this import can be accepted.")
            continue
        if ent.dxcc in seen:
            res.errors.append(f"Line {row.line}: {row.name!r} appears twice "
                              f"(also line {seen[ent.dxcc]}).")
            continue
        seen[ent.dxcc] = row.line
        if not ent.deleted and row.credits:
            credits[ent.dxcc] = row.credits

    if parsed.rows and not res.errors and len(seen) != len(reference):
        missing = [e.dxcc for e in reference.entities if e.dxcc not in seen]
        res.errors.append(
            f"Found {len(seen)} entity rows; the LoTW matrix has {len(reference)}. "
            f"The paste looks incomplete (missing: {_names(reference, missing)}).")

    if res.errors:
        res.status = REJECTED
        return res

    res.credits = credits
    res.totals = totals(credits)

    # --- Hold rules -------------------------------------------------------
    no_mixed = [d for d, c in credits.items() if MIXED not in c]
    if no_mixed:
        res.warnings.append(
            "Mixed is blank for entities that have other credits, which LoTW does not "
            f"normally show: {_names(reference, no_mixed)}.")

    if current is not None:
        old_totals = totals(current)
        for cat in TRACKED:
            if res.totals.get(cat, 0) < old_totals.get(cat, 0):
                res.warnings.append(
                    f"{LABELS[cat]} credits went down from {old_totals[cat]} to "
                    f"{res.totals.get(cat, 0)}.")
        lost = sorted(d for d, cats in current.items()
                      if (cats - credits.get(d, frozenset())) & set(TRACKED))
        if lost:
            res.warnings.append(f"These entities lost a credit: {_names(reference, lost)}.")

    if res.warnings:
        res.status = HELD
    return res
