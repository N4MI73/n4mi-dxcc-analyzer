"""
Curation advisor (D55, post-v1.0): what to put in DX Monitor's Needed list.

DX Monitor's Needed list is curated by hand (its device holds 30 entries), and
each entry is paired with a HamAlert trigger. This module suggests the entries
most likely to pay off. It never writes to DX Monitor; Dan adds what he wants.

Entities (never credited, Missing Entities):
  * left out when a confirmation is already in hand for Mixed: an "awaiting
    credit" mark or a paper card. A "won't submit" mark does NOT remove one:
    that confirmation will never be credited, so a new contact is still needed.
  * DXpeditions first (on the air, then starting within 30 days, from the
    DX Monitor tags of D54), then Club Log Most Wanted, easiest first.

Band slots (entities already credited for Mixed), one suggestion per entity:
  * bands: the profile's bands that Dan has left ticked in the advisor's band
    filter (D57; default everything but 160 m and 6 m, Dan 2026-10-14: too hard
    from EM83 for this purpose); modes: CW, Phone, Digital.
  * continents: only entities on continents left ticked (D57; default all).
  * a slot is left out when it is awaiting credit or covered by a paper card,
    as above; won't-submit slots stay in.
  * if the entity still needs a band AND a mode, the suggestion is "those bands
    with those modes": every spot DX Monitor matches is a contact worth 2
    credits (one band + one mode, Dan's credit rule). Otherwise it is the needed
    bands with any mode, or the needed modes on any band: worth 1.
  * order: credits per contact, then Most Wanted easiest first.

Names are HamAlert's spellings, because DX Monitor matches spots by HamAlert's
entity name (trimmed and lower-cased, nothing else). HamAlert uses Club Log's
DXCC data, whose names are the ADIF names in our reference table. Dan checked
78 names in HamAlert's picker on 2026-10-20 and the whole picker (all 340
current entities) on 2026-11-15. Five differ from ADIF and are listed in
data/hamalert_overrides.csv: two old names HamAlert keeps (Swaziland,
Macedonia) and three spellings of its own (Rodriguez I., South Africa,
St Maarten).

Modes in DX Monitor's terms: Phone = ssb, Digital = ft8 + ft4 (DX Monitor
offers cw, ssb, ft4 and ft8, the four HamAlert trigger modes).
"""

import csv
from pathlib import Path

from .analysis import missing_entities, most_wanted_key
from .categories import CW, DIGITAL, LABELS, MIXED, PHONE

OVERRIDES_FILE = Path(__file__).resolve().parent / "data" / "hamalert_overrides.csv"

# Profile band -> DX Monitor's band value (DX Monitor offers 160-6 m; 2 m and
# 60 m are not choices here).
DXMON_BANDS = {"160M": "160m", "80M": "80m", "40M": "40m", "30M": "30m", "20M": "20m",
               "17M": "17m", "15M": "15m", "12M": "12m", "10M": "10m", "6M": "6m"}
# D57 filter defaults: 160 m and 6 m off (D55), every continent on.
DEFAULT_SLOT_BANDS = ("80M", "40M", "30M", "20M", "17M", "15M", "12M", "10M")
CONTINENTS = {"AF": "Africa", "AS": "Asia", "EU": "Europe", "NA": "North America",
              "OC": "Oceania", "SA": "South America"}
DXMON_MODES = {CW: ["cw"], PHONE: ["ssb"], DIGITAL: ["ft8", "ft4"]}

DEFAULT_ENTITIES, DEFAULT_SLOTS = 20, 10
MAX_COUNT = 100

_LOWER = {"OF", "THE", "AND", "ON", "DA", "DE", "DU", "DES", "DEL"}
_UPPER = {"HQ", "ITU", "UK", "UN", "US", "USA"}


def title_name(adif):
    """ADIF names are upper case ("AMSTERDAM & ST. PAUL IS."); HamAlert shows them
    in title case ("Amsterdam & St. Paul Is."). Case doesn't matter for matching;
    this only makes the name read the way HamAlert's picker shows it."""
    words = adif.split()
    out = []
    for i, w in enumerate(words):
        core = w.strip("().,")
        if core in _UPPER:
            out.append(w)
        elif i > 0 and core in _LOWER:
            out.append(w.lower())
        else:
            out.append("-".join(_cap(part) for part in w.split("-")))
    return " ".join(out)


def _cap(word):
    lead = ""
    while word and not word[0].isalnum():
        lead, word = lead + word[0], word[1:]
    if word.upper().startswith("D'") and len(word) > 2:      # COTE D'IVOIRE
        return lead + "d'" + word[2:].capitalize()
    return lead + word.capitalize()


def _key(name):
    """DX Monitor's own matching form, exactly: leading and trailing spaces
    trimmed and lower-cased, nothing else. Spaces inside a name are NOT
    collapsed (DX Monitor's _normalize_entity_name; confirmed by the DX Monitor
    project 2026-10-20), so "St.  Paul" with two spaces never matches."""
    return (name or "").strip().lower()


def load_overrides(reference, path=OVERRIDES_FILE):
    """{dxcc: HamAlert name}. Every row must name a current entity, or the app
    refuses to start (a typo here would silently break a Needed entry)."""
    current = {e.dxcc for e in reference.current}
    out = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            dxcc, name = int(row["dxcc"]), (row["hamalert_name"] or "").strip()
            if dxcc not in current or not name:
                raise ValueError(f"hamalert_overrides.csv: row for DXCC {dxcc} is not a current "
                                 "entity or has no name.")
            out[dxcc] = name
    return out


class Names:
    """HamAlert's spelling for every current entity, and the reverse lookup used
    to place DX Monitor's Needed entries."""

    def __init__(self, reference, overrides):
        self.by_dxcc = {e.dxcc: overrides.get(e.dxcc) or title_name(e.adif_name)
                        for e in reference.current}
        self.by_key = {}
        for d, n in self.by_dxcc.items():
            if _key(n) in self.by_key:
                raise ValueError(f"Two entities share the HamAlert name {n!r}.")
            self.by_key[_key(n)] = d

    def __getitem__(self, dxcc):
        return self.by_dxcc[dxcc]

    def place(self, name):
        return self.by_key.get(_key(name))


def _dx_score(tags):
    if not tags:
        return 0
    return 2 if tags[0]["kind"] == "air" else 1


def _catches(entry, bands, modes):
    """Would this DX Monitor Needed entry catch spots for the suggestion?
    Empty sets mean "any" on both sides."""
    band_ok = not entry["bands"] or not bands or bool(set(entry["bands"]) & set(bands))
    mode_ok = not entry["modes"] or not modes or bool(set(entry["modes"]) & set(modes))
    return band_ok and mode_ok


def suggest(credits, reference, profile, *, covered, ranks, names, dx_tags=None,
            needed=None, n_entities=DEFAULT_ENTITIES, n_slots=DEFAULT_SLOTS,
            slot_bands=DEFAULT_SLOT_BANDS, slot_continents=tuple(CONTINENTS)):
    """The advisor's lists.

    covered  — {(dxcc, category)} already confirmed and waiting: awaiting marks
               and paper cards (won't-submit marks are NOT in it)
    ranks    — Club Log Most Wanted {dxcc: rank}
    dx_tags  — DX Monitor tags by DXCC number (dxmon.build()["tags"], keys str)
    needed   — DX Monitor's Needed entries (dxmon.parse_needed), or None when
               DX Monitor is off or its list couldn't be read
    slot_bands, slot_continents — the band-slot filters (D57); they narrow the
               band-slot list only, never the entity list
    """
    dx_tags = dx_tags or {}
    mw = most_wanted_key(ranks, easiest_first=True)
    by_entry = {}
    unmatched = []
    for entry in needed or ():
        d = names.place(entry["name"])
        if d is None:
            unmatched.append(entry["name"])
        else:
            by_entry.setdefault(d, []).append(entry)

    def in_dx(d, bands, modes, whole=False):
        if needed is None:
            return None             # unknown: DX Monitor off or its list unreadable
        if whole:                   # an entity suggestion needs a whole-entity entry
            return any(not x["bands"] and not x["modes"] for x in by_entry.get(d, ()))
        return any(_catches(x, bands, modes) for x in by_entry.get(d, ()))

    # Entities
    ents = []
    for e in missing_entities(credits, reference):
        if (e.dxcc, MIXED) in covered:
            continue
        tags = dx_tags.get(str(e.dxcc), [])
        ents.append((e, tags))
    ents.sort(key=lambda et: (-_dx_score(et[1]), mw(et[0].dxcc), et[0].lotw_name))
    entities = []
    for e, tags in ents[:n_entities]:
        t = tags[0] if tags else None
        entities.append({
            "dxcc": e.dxcc, "hamalert_name": names[e.dxcc], "lotw_name": e.lotw_name,
            "prefix": e.prefix, "mw_rank": ranks.get(e.dxcc),
            "dxpedition": ({"kind": t["kind"], "callsign": t["callsign"], "begin": t["begin"],
                            "end": t["end"], "watched": t["watched"]} if t else None),
            "in_dx_monitor": in_dx(e.dxcc, [], [], whole=True)})

    # Band slots
    bands_ok = [b for b in profile.bands if b in DXMON_BANDS and b in slot_bands]
    conts = set(slot_continents)
    modes_ok = [m for m in profile.modes if m in DXMON_MODES]
    cands = []
    for e in reference.current:
        have = credits.get(e.dxcc, frozenset())
        if MIXED not in have or e.continent not in conts:
            continue
        nb = [b for b in bands_ok if b not in have and (e.dxcc, b) not in covered]
        nm = [m for m in modes_ok if m not in have and (e.dxcc, m) not in covered]
        if not nb and not nm:
            continue
        if nb and nm:
            use_b, use_m, worth = nb, nm, 2
        elif nb:
            use_b, use_m, worth = nb, [], 1
        else:
            use_b, use_m, worth = [], nm, 1
        cands.append((e, use_b, use_m, worth))
    cands.sort(key=lambda c: (-c[3], mw(c[0].dxcc), c[0].lotw_name))
    slots = []
    for e, b, m, worth in cands[:n_slots]:
        dm_bands = [DXMON_BANDS[x] for x in b]
        dm_modes = [t for x in m for t in DXMON_MODES[x]]
        slots.append({
            "dxcc": e.dxcc, "hamalert_name": names[e.dxcc], "lotw_name": e.lotw_name,
            "prefix": e.prefix, "mw_rank": ranks.get(e.dxcc),
            "bands": [LABELS[x] for x in b], "modes": [LABELS[x] for x in m],
            "dxmon_bands": dm_bands, "dxmon_modes": dm_modes, "credits": worth,
            "in_dx_monitor": in_dx(e.dxcc, dm_bands, dm_modes)})

    return {"entities": entities, "slots": slots,
            "entities_available": len(ents), "slots_available": len(cands),
            "dxmon_needed_count": None if needed is None else len(needed),
            "dxmon_unmatched": sorted(set(unmatched), key=str.casefold)}
