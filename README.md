# n4mi-dxcc-analyzer

A small self-hosted app that answers one operating question at a glance: **"What do I still need for DXCC on the bands and modes I actually work?"**

It reads the ARRL Logbook of the World (LoTW) **Award Credit Matrix**, which Dan pastes in, and shows:

- entities never credited;
- credited entities still missing bands or modes in the operating profile (160–6 m; CW, Phone and Digital by default);
- the full band/mode matrix.

It runs LAN-only on a home NAS (FastAPI + SQLite + vanilla HTML/CSS/JS in Docker).

## Status

**Phase 1, Build Step 1: core logic only.** There is no web interface or Docker setup yet. What exists:

| File | What it does |
|---|---|
| `app/categories.py` | DXCC categories (Mixed, CW, Phone, Digital, one per band) and the operating profile |
| `app/reference.py` | Loads the DXCC entity table, keyed on the ARRL DXCC entity number |
| `app/parser.py` | Reads the matrix from a LoTW paste, `.txt`, `.csv` or `.xlsx` |
| `app/validate.py` | Rejects bad imports; holds suspicious ones (any credit going down) for review |
| `app/analysis.py` | Missing entities, needed slots, totals, what changed between imports |
| `app/marks.py` | Rules for "awaiting credit" / "won't submit" marks |
| `app/status_check.py` | Cross-check against LoTW's Account Status table |
| `app/clublog.py` | Club Log Most Wanted ranking (public, no key), fetched only on request |
| `app/data/dxcc_entities.csv` | The 402 DXCC entities (340 current), with continent and CQ zone |
| `tools/build_reference.py` | Development only: rebuilds that table from the verified list and AD1C's `cty.csv` |

## Key rules

- **LoTW credit is the authority.** Confirmations that are not yet credited are never counted as credits.
- **Entities are identified by DXCC number**, never by name or prefix. Names differ between sources, and prefixes such as 3Y, HK0 and VP8 cover several entities.
- **Bands and modes are credited separately**, as ARRL does. Band-and-mode combinations are not slots.
- **Deleted entities are excluded** from every count.
- **A failed import changes nothing**, and a suspicious one needs a deliberate "Save anyway".

## Running the tests

Requires Python 3.11 or later.

```
pip install -r requirements-dev.txt
python -m pytest
```

All test data is synthetic. **Real LoTW exports, pastes and the database are never committed**; `.gitignore` excludes them.

## License

MIT. See `LICENSE`.
