"""
Credit analysis — pure functions over a snapshot's credits.

A snapshot's credits are {dxcc: frozenset(category codes)} for current
entities with at least one credit. Only credits are stored; "needed" is
always computed from credits plus the operating profile, so changing the
profile never needs a re-import.

Definitions (confirmed by Dan, 2026-10-05, assumption A1):
  * Missing entity: a current entity with no Mixed credit. In LoTW's data
    Mixed is credited exactly when any non-satellite category is, so this
    means "never credited" (Satellite DXCC is a separate award, D43). The
    profile does not affect this list.
  * Needed slot: for an entity that has a Mixed credit, any profile band or
    mode without a credit.
  * Award view (D51, Dan 2026-10-08): the Band Slots tiles, chase lists and
    Full Matrix also count never-credited entities, which need every profile
    band and mode. That matches LoTW's per-category counts (Digital needed =
    current entities - Digital credits). needed_slots(include_new=True) gives
    this; the summary keeps the two parts separate.
"""

from collections import Counter
from dataclasses import dataclass

from .categories import MATRIX_CATEGORIES, MIXED, SAT


def totals(credits):
    """Credit count per matrix category (all 16, SAT included)."""
    c = Counter()
    for cats in credits.values():
        c.update(cats)
    return {cat: c.get(cat, 0) for cat in MATRIX_CATEGORIES}


def missing_entities(credits, reference):
    """Current entities never credited (no Mixed credit), by DXCC number."""
    return [e for e in reference.current if MIXED not in credits.get(e.dxcc, ())]


def needed_slots(credits, reference, profile, include_new=False):
    """{dxcc: [category, ...]} for credited entities missing profile band or
    mode slots. Satellite is not included: it is a separate award (D43), so
    its needs come from satellite_needs() instead.

    With include_new, never-credited entities are included too (they need
    every profile band and mode) — the award view, D51.

    Entities with every such slot credited are omitted.
    """
    slots = [c for c in profile.slot_categories if c != SAT]
    out = {}
    for e in reference.current:
        cats = credits.get(e.dxcc, frozenset())
        if MIXED not in cats and not include_new:
            continue
        need = [c for c in slots if c not in cats]
        if need:
            out[e.dxcc] = need
    return out


def satellite_needs(credits, reference, profile):
    """Current entities with no Satellite credit, across ALL current entities
    whether or not Mixed is credited (D44). Empty unless Satellite is in the
    profile."""
    if SAT not in profile.modes:
        return []
    return [e.dxcc for e in reference.current if SAT not in credits.get(e.dxcc, ())]


def slots_by_category(needed, profile, sat_needs=()):
    """{category: [dxcc, ...]} — the by-band chase lists.

    The Satellite list (when in the profile) is `sat_needs`, from
    satellite_needs().
    """
    out = {c: [] for c in profile.slot_categories}
    for dxcc, cats in needed.items():
        for c in cats:
            out[c].append(dxcc)
    if SAT in out:
        out[SAT] = list(sat_needs)
    return out


@dataclass
class Summary:
    entities_current: int
    entities_credited: int
    entities_missing: int
    complete: int          # credited entities with every band/mode profile slot credited
    one_slot_away: int     # credited entities missing exactly one band/mode profile slot
    slots_missing: int     # band/mode slots on credited entities (Satellite excluded)
    slots_missing_new: int = 0   # band/mode slots on never-credited entities (D51)
    satellite_missing: int | None = None   # D44; None unless Satellite is in the profile


def summarize(credits, reference, profile):
    needed = needed_slots(credits, reference, profile)
    every = needed_slots(credits, reference, profile, include_new=True)
    credited = sum(1 for e in reference.current if MIXED in credits.get(e.dxcc, ()))
    return Summary(
        entities_current=len(reference.current),
        entities_credited=credited,
        entities_missing=len(reference.current) - credited,
        complete=credited - len(needed),
        one_slot_away=sum(1 for v in needed.values() if len(v) == 1),
        slots_missing=sum(len(v) for v in needed.values()),
        slots_missing_new=sum(len(v) for d, v in every.items() if d not in needed),
        satellite_missing=(len(satellite_needs(credits, reference, profile))
                           if SAT in profile.modes else None),
    )


@dataclass
class Changes:
    new_entities: list     # dxcc newly credited for Mixed
    new_slots: list        # (dxcc, category) newly credited, excluding Mixed
    lost: list             # (dxcc, category) present before, absent now


def changes(old, new, profile=None):
    """What changed between two snapshots' credits (old may be None).

    With a profile, only Mixed and the profile's categories are reported
    (so Satellite or 2 m appear only for someone who tracks them).
    """
    keep = frozenset(MATRIX_CATEGORIES if profile is None else (MIXED,) + profile.slot_categories)
    old = old or {}
    new_entities, new_slots, lost = [], [], []
    for dxcc in sorted(set(old) | set(new)):
        before, after = old.get(dxcc, frozenset()), new.get(dxcc, frozenset())
        if MIXED in after and MIXED not in before:
            new_entities.append(dxcc)
        for cat in sorted((after - before) & keep):
            if cat != MIXED:
                new_slots.append((dxcc, cat))
        for cat in sorted((before - after) & keep):
            lost.append((dxcc, cat))
    return Changes(new_entities, new_slots, lost)


def most_wanted_key(rankings, easiest_first=True):
    """Sort key for Club Log Most Wanted ordering.

    Rank 1 is the most wanted (rarest). "Easiest first" puts the highest rank
    numbers (least wanted, usually most active) first. Unranked entities sort
    last either way.
    """
    def key(dxcc):
        rank = rankings.get(dxcc)
        if rank is None:
            return (1, 0)
        return (0, -rank if easiest_first else rank)
    return key
