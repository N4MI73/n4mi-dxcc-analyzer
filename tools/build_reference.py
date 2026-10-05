"""
Build app/data/dxcc_entities.csv — DEVELOPMENT ONLY, never run by the app.

Inputs:
  1. The verified DXCC name-to-number table (columns dxcc, lotw_name,
     adif_name, lotw_prefix, deleted, mapping), built 2026-10-01 from the
     ADIF 3.1.7 entity enumeration and checked by hand.
  2. cty.csv from country-files.com (AD1C's country file), which supplies
     each current entity's continent and CQ zone.

Output: the same table plus `continent` and `cq_zone` columns, written to
app/data/dxcc_entities.csv. Deleted entities get blank continent/zone.

Why a one-time build instead of downloading the country file at runtime
(decision S1, 2026-10-05): an entity's continent essentially never
changes, and a brand-new entity already needs a reviewed update to this
table, so its continent is added then. That keeps the running app free of
a download, a cache and a failure state.

Usage:
  python tools/build_reference.py <verified_table.csv> <cty.csv> [output.csv]

The script refuses to write anything unless every current entity is found
in cty.csv exactly once.
"""

import csv
import sys
from pathlib import Path

DEFAULT_OUT = Path(__file__).resolve().parent.parent / "app" / "data" / "dxcc_entities.csv"
FIELDS = ["dxcc", "lotw_name", "adif_name", "lotw_prefix", "deleted", "mapping",
          "continent", "cq_zone"]
CONTINENTS = {"AF", "AN", "AS", "EU", "NA", "OC", "SA"}


def read_cty(path):
    """Return {dxcc: (continent, cq_zone)} from cty.csv.

    cty.csv rows: prefix, name, dxcc, continent, cq, itu, lat, lon, utc, aliases.
    Rows whose prefix starts with '*' are WAE-only (e.g. Sicily, European
    Turkey) — not DXCC entities — and are skipped.
    """
    result = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.reader(f):
            if not row or row[0].startswith("*"):
                continue
            dxcc, cont, cq = int(row[2]), row[3].strip(), int(row[4])
            if dxcc in result:
                raise SystemExit(f"cty.csv lists DXCC {dxcc} twice")
            if cont not in CONTINENTS:
                raise SystemExit(f"cty.csv: unexpected continent {cont!r} for DXCC {dxcc}")
            result[dxcc] = (cont, cq)
    return result


def main(argv):
    if len(argv) not in (3, 4):
        raise SystemExit(__doc__)
    table_path, cty_path = argv[1], argv[2]
    out_path = Path(argv[3]) if len(argv) == 4 else DEFAULT_OUT

    cty = read_cty(cty_path)
    with open(table_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    missing = [r["lotw_name"] for r in rows
               if r["deleted"] != "yes" and int(r["dxcc"]) not in cty]
    if missing:
        raise SystemExit(f"Not in cty.csv: {missing}")
    current = {int(r["dxcc"]) for r in rows if r["deleted"] != "yes"}
    extra = sorted(set(cty) - current)
    if extra:
        raise SystemExit(f"cty.csv has DXCC numbers not current in the table: {extra}")

    for r in rows:
        if r["deleted"] == "yes":
            r["continent"], r["cq_zone"] = "", ""
        else:
            cont, cq = cty[int(r["dxcc"])]
            r["continent"], r["cq_zone"] = cont, str(cq)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: int(r["dxcc"])))
    print(f"Wrote {len(rows)} entities ({len(current)} current) to {out_path}")


if __name__ == "__main__":
    main(sys.argv)
