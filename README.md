# n4mi-dxcc-analyzer

A small self-hosted app that answers one operating question at a glance: **"What do I still need for DXCC on the bands and modes I actually work?"**

It reads the ARRL Logbook of the World (LoTW) **Award Credit Matrix**, which Dan pastes in, and shows:

- entities never credited;
- credited entities still missing bands or modes in the operating profile (160–6 m with CW, Phone and Digital by default; 2 m and Satellite can be switched on);
- the full band/mode matrix.

It runs LAN-only on a home NAS (FastAPI + SQLite + vanilla HTML/CSS/JS in Docker).

## Status

**Phase 1, Build Step 2b-2: core logic, storage, the internal API and all six pages** (Missing Entities, Missing Band Slots, Full Matrix, Paper QSLs, Import, Settings). Exports and Docker come next. What exists:

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
| `app/paper.py` | Paper QSL cards not yet credited: what each card would fill |
| `app/db.py` | SQLite storage: imports, credits, marks, paper cards, settings |
| `app/api.py` | Internal endpoints for the app's own pages (not the DXMon contract) |
| `app/main.py` | App setup, `/healthz`, start-up check |
| `static/` | The web pages: plain HTML, CSS and JavaScript, no build step |
| `app/data/dxcc_entities.csv` | The 402 DXCC entities (340 current), with continent and CQ zone |
| `tools/build_reference.py` | Development only: rebuilds that table from the verified list and AD1C's `cty.csv` |

## Key rules

- **LoTW credit is the authority.** Confirmations that are not yet credited are never counted as credits.
- **Entities are identified by DXCC number**, never by name or prefix. Names differ between sources, and prefixes such as 3Y, HK0 and VP8 cover several entities.
- **Bands and modes are credited separately**, as ARRL does. Band-and-mode combinations are not slots.
- **Deleted entities are excluded** from every count.
- **A failed import changes nothing**, and a suspicious one needs a deliberate "Save anyway".

## Running locally

```
pip install -r requirements.txt
uvicorn app.main:create_app --factory --port 8086
```

Then open `http://localhost:8086/`. `http://localhost:8086/healthz` answers `{"status":"ok"}`. The database is created in `data/` (set `DATA_DIR` to put it elsewhere).

## Running the tests

Requires Python 3.11 or later.

```
pip install -r requirements-dev.txt
python -m pytest
```

All test data is synthetic. **Real LoTW exports, pastes and the database are never committed**; `.gitignore` excludes them.

## License

MIT. See `LICENSE`.
