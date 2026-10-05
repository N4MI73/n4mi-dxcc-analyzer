"""
Pending marks — Dan's hand-entered notes that a needed slot has a LoTW
confirmation waiting (decision D27).

  awaiting     Confirmed in LoTW, not yet credited ("New LoTW QSLs" or
               "LoTW QSLs in Process").
  wont_submit  Confirmed in LoTW but Dan will not submit it (e.g. the
               Indonesia Phone QSL made via EchoLink).

Both still count as NEEDED; a mark is never a credit. Marks may be set on
Mixed (a new entity awaiting credit) and on the profile's bands and modes
(Dan, 2026-10-05: 160-6 m and CW/Phone/Digital; not 2 m, not Satellite).

A mark clears itself when an import shows that slot credited. Dan can also
clear one by hand. Importing the matrix is the normal way marks get
"checked off" — no separate step is needed.
"""

from collections import Counter
from dataclasses import dataclass

from .categories import LABELS

AWAITING, WONT_SUBMIT = "awaiting", "wont_submit"
STATES = (AWAITING, WONT_SUBMIT)


@dataclass(frozen=True)
class Mark:
    dxcc: int
    category: str
    state: str
    note: str = ""


def check_mark(mark, credits, reference, profile):
    """Return None if the mark may be set, otherwise a reason."""
    ent = reference.by_dxcc.get(mark.dxcc)
    if ent is None or ent.deleted:
        return "Not a current DXCC entity."
    if mark.state not in STATES:
        return f"Unknown mark state {mark.state!r}."
    if mark.category not in profile.markable_categories:
        return (f"{LABELS.get(mark.category, mark.category)} is not in the operating profile, "
                "so it cannot be marked.")
    if mark.category in credits.get(mark.dxcc, ()):
        return f"{ent.lotw_name} is already credited for {LABELS[mark.category]}."
    return None


def cleared_by(marks, credits):
    """Marks whose slot is credited in `credits` — they clear on import."""
    return [m for m in marks if m.category in credits.get(m.dxcc, ())]


def counts_by_category(marks):
    """Active marks per category (awaiting and won't-submit together)."""
    return dict(Counter(m.category for m in marks))
