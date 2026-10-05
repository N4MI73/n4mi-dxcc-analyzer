"""
The DXCC entity reference table (app/data/dxcc_entities.csv).

Everything in the app is keyed on the ARRL DXCC entity number. Names and
prefixes differ between LoTW, ADIF, the country file and other sources
(e.g. LoTW "CAPE VERDE" vs country file "Cabo Verde", both DXCC 409), and
10 prefixes are shared by more than one current entity (3Y, HK0, VK0, VP8,
FO, ...), so neither can serve as an identity.

LoTW names are matched together with the matrix's Deleted flag, because one
name can belong to two entities: PALESTINE is both DXCC 510 (current, E4)
and DXCC 196 (deleted, ZC6/4X1).
"""

import csv
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parent / "data" / "dxcc_entities.csv"


@dataclass(frozen=True)
class Entity:
    dxcc: int
    lotw_name: str
    adif_name: str
    prefix: str
    deleted: bool
    continent: str
    cq_zone: int | None


def normalize_name(name):
    """Matching form of a LoTW entity name: trimmed, single-spaced, upper case."""
    return " ".join(str(name).replace("\xa0", " ").split()).upper()


class Reference:
    def __init__(self, entities):
        self.entities = tuple(sorted(entities, key=lambda e: e.dxcc))
        self.by_dxcc = {}
        self._by_name = {}
        for e in self.entities:
            if e.dxcc in self.by_dxcc:
                raise ValueError(f"Reference table lists DXCC {e.dxcc} twice")
            self.by_dxcc[e.dxcc] = e
            key = (normalize_name(e.lotw_name), e.deleted)
            if key in self._by_name:
                raise ValueError(f"Reference table lists {e.lotw_name!r} twice")
            self._by_name[key] = e
        self.current = tuple(e for e in self.entities if not e.deleted)

    def __len__(self):
        return len(self.entities)

    def lookup(self, name, deleted):
        """Entity for a LoTW name and Deleted flag, or None."""
        return self._by_name.get((normalize_name(name), bool(deleted)))

    def name_exists(self, name):
        """True if the name exists with either Deleted flag."""
        n = normalize_name(name)
        return (n, True) in self._by_name or (n, False) in self._by_name


def load_reference(path=DEFAULT_PATH):
    entities = []
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            entities.append(Entity(
                dxcc=int(r["dxcc"]),
                lotw_name=r["lotw_name"],
                adif_name=r["adif_name"],
                prefix=r["lotw_prefix"],
                deleted=r["deleted"] == "yes",
                continent=r.get("continent", "") or "",
                cq_zone=int(r["cq_zone"]) if r.get("cq_zone") else None,
            ))
    return Reference(entities)
