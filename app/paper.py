"""
Paper QSL cards not yet credited (decision D41, 2026-10-07).

Many DXers hold paper QSLs until they have enough to take to a card
checker or mail to ARRL. A card is entered once, as its QSO — entity,
band and DXCC mode category — and the app works out which needed slots it
would fill. Confirmed by Dan: one card counts at the same time toward
Mixed, its mode category and its band.

States:
  in_hand    received, waiting until there are enough to submit
  submitted  sent to ARRL or checked by a card checker, awaiting credit

A card is never a credit. Its marks are shown with their own "CARD" tag,
kept apart from LoTW pending marks, and never compared with LoTW's
Account Status counts (LoTW knows nothing about paper cards). A card is
"credited" once an import shows every slot it could fill credited.

Satellite cards (ARRL DXCC rules, supplied by Dan 2026-10-07, decision D43):
Satellite DXCC is a completely separate award. A satellite confirmation counts
toward Satellite only — not Mixed, Phone, CW or Digital, and not any band.
So a Satellite card has no band and covers the Satellite category alone.
(Other cards still count toward Mixed, their mode and their band.)
"""

from dataclasses import dataclass

from .categories import BANDS, LABELS, MIXED, PROFILE_MODES, SAT

IN_HAND, SUBMITTED = "in_hand", "submitted"
STATES = (IN_HAND, SUBMITTED)


@dataclass(frozen=True)
class PaperQSL:
    dxcc: int
    band: str | None          # e.g. "20M"; always None for a Satellite card
    mode: str                 # CW, PHONE, DIGITAL or SAT
    state: str = IN_HAND
    call: str = ""
    qso_date: str = ""        # free text or ISO date, optional
    note: str = ""

    @property
    def categories(self):
        """Every DXCC category this card's QSO counts toward."""
        if self.mode == SAT:
            return [SAT]                 # Satellite DXCC is separate: no Mixed, mode or band credit
        return [MIXED, self.mode, self.band]


def check_card(card, reference):
    """Return None if the card's fields are valid, otherwise a reason."""
    ent = reference.by_dxcc.get(card.dxcc)
    if ent is None or ent.deleted:
        return "Not a current DXCC entity."
    if card.mode not in PROFILE_MODES:
        return f"Unknown mode category {card.mode!r} (use CW, Phone, Digital or Satellite)."
    if card.mode == SAT:
        if card.band is not None:
            return ("Satellite QSOs don't count toward band awards, so a Satellite card "
                    "has no band. Leave the band blank.")
    elif card.band is None:
        return "A band is required."
    elif card.band not in BANDS:
        return f"Unknown band {card.band!r}."
    if card.state not in STATES:
        return f"Unknown card state {card.state!r}."
    return None


def would_fill(card, credits):
    """Categories this card would add that are not yet credited (any profile)."""
    have = credits.get(card.dxcc, frozenset())
    return [c for c in card.categories if c not in have]


def fills_in_profile(card, credits, profile):
    """The needed slots this card fills within the operating profile.

    Mixed counts whenever the entity is not yet credited.
    """
    keep = (MIXED,) + profile.slot_categories
    return [c for c in would_fill(card, credits) if c in keep]


def describe_entry(card, credits, profile, reference):
    """Outcome of entering a card: (ok, message, slots_in_profile).

    Refused only when the card is invalid or would add no credit at all.
    A card that only adds credit outside the profile is accepted with a note.
    """
    problem = check_card(card, reference)
    if problem:
        return False, problem, []
    name = reference.by_dxcc[card.dxcc].lotw_name
    new = would_fill(card, credits)
    if not new:
        return False, f"{name}: everything this card covers is already credited.", []
    mine = fills_in_profile(card, credits, profile)
    if not mine:
        outside = ", ".join(LABELS[c] for c in new)
        return True, f"{name}: adds {outside}, which is outside your profile.", []
    return True, f"{name}: fills " + ", ".join(LABELS[c] for c in mine) + ".", mine


def is_credited(card, credits):
    """True once an import shows every category this card covers credited."""
    return not would_fill(card, credits)


def counts_by_state(cards):
    out = {IN_HAND: 0, SUBMITTED: 0}
    for c in cards:
        out[c.state] = out.get(c.state, 0) + 1
    return out
