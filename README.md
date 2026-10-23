# n4mi-dxcc-analyzer

A small self-hosted app that answers one operating question at a glance: **"What do I still need for DXCC on the bands and modes I actually work?"**

It reads the ARRL Logbook of the World (LoTW) **Award Credit Matrix**, which Dan pastes in, and shows:

- entities never credited;
- every band and mode slot still needed in the operating profile (160–6 m with CW, Phone and Digital by default; 2 m and Satellite can be switched on), counted the way LoTW counts them: never-confirmed entities are included and tagged NEW;
- the full band/mode matrix.

It runs LAN-only on a home NAS (FastAPI + SQLite + vanilla HTML/CSS/JS in Docker).

**How to use it:** see the [User Guide](User_Guide.md), including how to use it together with [DX Monitor](https://github.com/N4MI73/n4mi-dx-monitor).

## Install on Linux (native packages)

One-liner (Debian/Ubuntu, Fedora/RHEL, Arch, openSUSE — installs from the
latest GitHub Release when possible, otherwise from source):

```
curl -fsSL https://raw.githubusercontent.com/N4MI73/n4mi-dxcc-analyzer/main/install.sh | sudo bash
```

What you get: the app in `/opt/n4mi-dxcc-analyzer` (Python venv), a
`n4mi-dxcc-analyzer` systemd service on port 8086, data (SQLite `dxcc.db`)
in `/var/lib/n4mi-dxcc-analyzer`. Open `http://<this-host>:8086/`;
`/healthz` answers `{"status":"ok"}`.

| Format | Who it is for | Install |
|---|---|---|
| `.deb` | Debian, Ubuntu, Mint, Pop!_OS, Raspberry Pi OS | Download `n4mi-dxcc-analyzer_<version>_all.deb` from [Releases](https://github.com/N4MI73/n4mi-dxcc-analyzer/releases), then `sudo apt install ./n4mi-dxcc-analyzer_*_all.deb` |
| `.rpm` | Fedora, RHEL/Rocky/Alma, openSUSE | Download `n4mi-dxcc-analyzer-<version>-1.noarch.rpm` from [Releases](https://github.com/N4MI73/n4mi-dxcc-analyzer/releases), then `sudo dnf install ./n4mi-dxcc-analyzer-*.rpm` |
| `.AppImage` | Any distro, no root, try-before-you-install | Download `N4MI-DXCC-Analyzer-<version>-x86_64.AppImage` from [Releases](https://github.com/N4MI73/n4mi-dxcc-analyzer/releases), `chmod +x`, run it (first run creates `~/.local/share/n4mi-dxcc-analyzer/{venv,data}` and opens the browser) |

Packages are built by [`packaging/`](packaging/) (`build-deb.sh`,
`build-rpm.sh`, `build-appimage.sh`; version comes from `app/version.py`) and
by [`.github/workflows/packages.yml`](.github/workflows/packages.yml) on every
`v*` tag. To build locally: `bash packaging/build-deb.sh`, same for rpm and
AppImage; output goes to `dist/`.

Useful `install.sh` forms:

```
sudo bash install.sh --from-source                 # skip release lookup
sudo bash install.sh --port 8090                    # non-default port
sudo bash install.sh --deb ./n4mi-dxcc-analyzer_1.3.0_all.deb
sudo bash install.sh --rpm ./n4mi-dxcc-analyzer-1.3.0-1.noarch.rpm
sudo bash install.sh --appimage ./N4MI-DXCC-Analyzer-1.3.0-x86_64.AppImage
sudo bash install.sh --uninstall                    # keep data
sudo bash install.sh --uninstall --purge            # also delete /var/lib/n4mi-dxcc-analyzer
```

Uninstall for packages: `sudo apt remove n4mi-dxcc-analyzer`
(`purge` deletes the data dir), `sudo dnf remove n4mi-dxcc-analyzer`, or just
delete the AppImage. Service logs: `journalctl -u n4mi-dxcc-analyzer -e`.
Docker/NAS deployment below is unchanged and still supported.

## Status

**v1.0 released 2026-10-13; current release v1.3.0.** Deployed on the UGreen NAS (Docker, Portainer, port 8086). Since v1.0: DXpedition tags from DX Monitor, the Suggestions page for DX Monitor's Needed list, the user guide, the security review fixes, and the in-app Help page. The version running is shown beside the app's name on every page. What's in the repository:

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
| `app/exports.py` | CSV and workbook exports, including the DX Monitor bridge file |
| `app/dxmon.py` | Optional read-only link to DX Monitor: DXpeditions, Watched and Needed lists |
| `app/advisor.py` | Suggestions page: what to add to DX Monitor's Needed list, in HamAlert's spellings |
| `app/guide.py` | The Help page: renders `User_Guide.md` (and its `images/`) inside the app |
| `app/version.py` | The version number shown in the app; update it before tagging a release |
| `static/` | The web pages: plain HTML, CSS and JavaScript, no build step |
| `app/data/dxcc_entities.csv` | The 402 DXCC entities (340 current), with continent and CQ zone |
| `tools/build_reference.py` | Development only: rebuilds that table from the verified list and AD1C's `cty.csv` |
| `tools/make_guide_diagrams.py` | Development only: draws the guide's two copy-selection diagrams |

## Key rules

- **LoTW credit is the authority.** Confirmations that are not yet credited are never counted as credits.
- **Entities are identified by DXCC number**, never by name or prefix. Names differ between sources, and prefixes such as 3Y, HK0 and VP8 cover several entities.
- **Bands and modes are credited separately**, as ARRL does. Band-and-mode combinations are not slots.
- **Deleted entities are excluded** from every count.
- **A failed import changes nothing**, and a suspicious one needs a deliberate "Save anyway".

## Deploying on the NAS (Portainer)

1. In UGOS Files, create the folder `/volume2/docker/n4mi-dxcc-analyzer/data`. It holds the database (`dxcc.db`) and nothing else.
2. Portainer → **Stacks → Add stack → Repository**:
   - Repository URL `https://github.com/N4MI73/n4mi-dxcc-analyzer`, reference `refs/heads/main`, compose path `docker-compose.yml`
   - Authentication off; GitOps auto-updates off; no environment variables (no credentials in Phase 1)
3. Deploy. Check `http://192.168.6.29:8086/healthz` answers `{"status":"ok"}` and `http://192.168.6.29:8086/api/status` shows `"ok":true`.
4. Uptime Kuma: an HTTP monitor on `/healthz` (is the app up?) and a Keyword monitor on `/api/status` for `"ok":true` (is the database readable and the data folder mounted?).

**Updating:** commit and push, then Portainer → the stack → **Pull and redeploy** (`pull_policy: build` rebuilds from the repo).

**If the data folder isn't mounted**, every page shows "Data folder /app/data not found" instead of quietly starting with an empty database. **Losing the folder** costs only history: one fresh LoTW paste restores current credits; import history, pending marks and paper cards would be lost, so copy `dxcc.db` now and then (best with the stack stopped).

## Running locally

```
pip install -r requirements.txt
uvicorn app.main:create_app --factory --port 8086
```

Then open `http://localhost:8086/`. `http://localhost:8086/healthz` answers `{"status":"ok"}`. The database is created in `data/` (set `DATA_DIR` to put it elsewhere).

## Exports

The **Export** button on the list pages offers four files. All follow the operating profile, not a page's temporary filters.

| File | Contents |
|---|---|
| `dxcc_analysis_YYYY-MM-DD.xlsx` | Summary, Missing Entities, Missing Slots, By Band, Matrix, Pending Marks, Paper QSLs |
| `missing_entities.csv` | Never-credited entities with Most Wanted rank, marks and paper cards |
| `missing_slots.csv` | One row per entity with a need (never-confirmed entities flagged in the last column); one column per profile band and mode |
| `no_confirms.csv` | For DX Monitor (optional): a drop-in replacement for its `no_confirms.csv` (`Entity,Prefix`, no byte-order mark). See below. |

### Loading the list into DX Monitor

This is only for operators who also run DX Monitor; the analyzer works fully without it. DX Monitor builds `server/no_confirms.csv` into its Docker image and reads it once at start-up to seed its Trigger Builder picker. Copying the file to a folder on the server and restarting the container therefore has no effect. Instead:

1. Download `no_confirms.csv` from the **Export** menu.
2. In your local DX Monitor repository, replace `server/no_confirms.csv` with the downloaded file.
3. Commit and push the change.
4. In Portainer, open the `dxmon` stack and choose **Pull and redeploy**, so the image is rebuilt with the new file.

DX Monitor's Needed list stays curated by hand; the new file only changes which entities its picker offers.

## DXpeditions from DX Monitor (optional)

If you also run DX Monitor, enter its address in **Settings → DX Monitor** (for example `http://192.168.6.29:8083`), then **Test connection** and **Save**. Leave the address blank to keep every DX Monitor feature off; the analyzer works fully without it.

When it's on:

- **Missing Entities** tags each needed entity that has a DXpedition in DX Monitor's ADXO list: **ON AIR** while it's active, or its start date if it starts within 30 days. **NOT WATCHED** means it isn't on DX Monitor's Watched list. A **DXpeditions first** sort is added.
- The analyzer reads DX Monitor's `/api/adxo`, `/api/watched` and `/api/needed` (read-only) when Missing Entities opens, if its last try was over 15 minutes ago, or when you press **Refresh**. If DX Monitor doesn't answer, the last list received stays on screen with its time.
- ADXO names entities in its own spelling. The app matches them to DXCC entities by name and a built-in list of known spellings. Any name it can't place is listed in Settings with a suggestion for you to approve, choose another entity, or ignore; nothing is applied without you.
- The **For DX Monitor** export appears in the Export menu.

## Suggestions for DX Monitor

The **Suggestions** page lists the best targets for DX Monitor's hand-curated Needed list (its device holds 30 entries):

- **Entities:** your never-confirmed entities. DXpeditions on the air or starting within 30 days come first, then Club Log Most Wanted, easiest first. In DX Monitor, add each one with band and mode left unticked.
- **Band slots:** one suggestion per confirmed entity that still needs a band or mode. A suggestion that combines a needed band with a needed mode is worth 2 credits a contact, so those come first. The **Tick in DX Monitor** column shows exactly what to tick. Phone is SSB, and Digital is FT8 and FT4.
- **Filters:** band and continent tickboxes narrow the band-slot list, for example 12 m and 10 m off near solar minimum, or only 6 m in an Es season. They're saved. 160 m and 6 m are off by default.
- **What's left out:** anything awaiting credit or covered by a paper card. Won't-submit marks stay in, because that confirmation will never be credited.
- **Names** are HamAlert's spellings, because DX Monitor matches spots by HamAlert's entity name. Use **Copy**, and paste the name exactly into DX Monitor and your HamAlert trigger. They come from the ADIF entity names, plus a short tested override list (`app/data/hamalert_overrides.csv`) for the two entities HamAlert still lists under old names (Swaziland, Macedonia).
- **With DX Monitor switched on** (see above), suggestions already covered by its Needed list are tagged **ALREADY IN DX MONITOR**. The analyzer also reads DX Monitor's `/api/needed`, read-only. If that read fails, the DXpedition tags carry on and nothing is flagged. Needed entries whose name doesn't match any HamAlert entity are listed, because they would never get a hit.
- **Without DX Monitor,** the page works the same, just without the tags.

## Running the tests

Requires Python 3.11 or later.

```
pip install -r requirements-dev.txt
python -m pytest
```

All test data is synthetic. **Real LoTW exports, pastes and the database are never committed**; `.gitignore` excludes them.

## License

MIT. See `LICENSE`.
