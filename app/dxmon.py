"""
DX Monitor DXpeditions (D54, post-v1.0) — optional.

When Dan enters DX Monitor's address in Settings, the app reads two of DX
Monitor's endpoints, read-only:

  GET /api/adxo     {"updated", "entry_count", "entries": [{"id", "dxcc",
                     "callsign", "begin", "end", "active", "qsl", "source",
                     "info"}]}   — "dxcc" is an entity NAME as ADXO spells it;
                     expired entries are already removed by DX Monitor.
  GET /api/watched  {"count", "entries": [{"id", "callsign", "dxcc",
                     "source_adxo_id", "note", "added", ...}]}
  GET /api/needed   {"count", "entries": [{"id", "entity", "band", "mode",
                     "note", "added", ...}]}  — D55, optional; "entity" is
                     HamAlert's spelling, band/mode comma-separated, blank = any
                     (checked against DX Monitor commit 98161c7, 2026-10-20)

(Checked against DX Monitor commit 6950a24, 2026-10-13.) Nothing is ever
sent to DX Monitor. /api/adxo also feeds the Propagation Dashboard, so this
module only reads it.

ADXO names are matched to DXCC entity numbers without guessing: exact match on
the LoTW or ADIF name after a conservative normalisation and a few standard
abbreviations, then a tested built-in alias list (data/adxo_aliases.csv), then
names Dan has approved in Settings. A name that still doesn't match is listed
in Settings with a suggestion for Dan to approve; it is never applied on its
own, and its DXpeditions simply get no tag until then.

Every response is validated before use; on any failure the caller keeps the
last good copy and says when it was obtained.
"""

import csv
import difflib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

TIMEOUT_S = 5                  # per network read
DEADLINE_S = 10                # whole request, however slowly data trickles in
MAX_BYTES = 2_000_000          # a real /api/adxo is about 25 kB
MAX_ENTRIES = 5000
WINDOW_DAYS = 30               # D54: scheduled DXpeditions tagged only within 30 days
AUTO_REFRESH_MIN = 15          # D54: refresh on page load if the last try is older
SUGGEST_MIN = 0.6
ALIASES_FILE = Path(__file__).resolve().parent / "data" / "adxo_aliases.csv"
USER_AGENT = "N4MI-DXCC-Analyzer (+https://github.com/N4MI73/n4mi-dxcc-analyzer)"


class DXMonError(Exception):
    """DX Monitor could not be reached, or its answer failed validation."""


# ---------- address ----------

def check_url(url):
    """Validate the DX Monitor address. Returns it tidied ('' means off)."""
    url = (url or "").strip().rstrip("/")
    if not url:
        return ""
    if len(url) > 200:
        raise ValueError("That address is too long.")
    p = urllib.parse.urlsplit(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise ValueError("Enter the address as http://host:port, for example "
                         "http://192.168.6.29:8083.")
    if p.username or p.password or p.query or p.fragment or p.path not in ("", "/"):
        raise ValueError("Enter only http://host:port, with no path, user name or extras.")
    try:
        p.port
    except ValueError as exc:
        raise ValueError("The port in that address isn't a number.") from exc
    return f"{p.scheme}://{p.netloc}"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """DX Monitor never redirects. Following one would let a chosen server bounce
    the request to some other address and path on the network, so any redirect
    is refused (security review DXCC-02, 2026-10-21)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "redirect refused", headers, fp)


_OPENER = urllib.request.build_opener(_NoRedirect)


def fetch_raw(url, timeout=TIMEOUT_S, deadline=DEADLINE_S):
    """GET one URL; return the body (at most MAX_BYTES).

    `timeout` limits each network read; `deadline` limits the whole request, so
    a server that sends a byte at a time can't hold a request open for long."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                               "Accept": "application/json"})
    end = time.monotonic() + deadline
    try:
        with _OPENER.open(req, timeout=timeout) as resp:
            if resp.status != 200:
                raise DXMonError(f"DX Monitor answered HTTP {resp.status}.")
            chunks, size = [], 0
            while True:
                chunk = resp.read1(65536)
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                if size > MAX_BYTES:
                    raise DXMonError("DX Monitor's answer was far larger than expected.")
                if time.monotonic() > end:
                    raise DXMonError(f"DX Monitor didn't finish answering within {deadline} seconds.")
    except DXMonError:
        raise
    except urllib.error.HTTPError as exc:
        if 300 <= exc.code < 400:
            raise DXMonError(f"DX Monitor answered with a redirect (HTTP {exc.code}), which the "
                             "analyzer doesn't follow; check the address.") from exc
        raise DXMonError(f"DX Monitor answered HTTP {exc.code}; check the address.") from exc
    except Exception as exc:
        raise DXMonError(f"DX Monitor didn't answer ({_reason(exc)}).") from exc
    return b"".join(chunks)


def _reason(exc):
    r = getattr(exc, "reason", None) or exc
    if isinstance(r, ConnectionRefusedError):
        return "connection refused; is the dxmon stack running?"
    text = str(r) or type(r).__name__
    if "timed out" in text:
        return "no reply within %d seconds" % TIMEOUT_S
    return re.sub(r"^\[Errno -?\d+\]\s*", "", text)


# ---------- validation ----------

def _json(data, what):
    try:
        return json.loads(data)
    except (ValueError, TypeError) as exc:
        raise DXMonError(f"DX Monitor's {what} wasn't valid JSON (is the address right?).") from exc


def _iso(v):
    try:
        return date.fromisoformat(v) if isinstance(v, str) and len(v) == 10 else None
    except ValueError:
        return None


def _text(v, limit=200):
    return v.strip()[:limit] if isinstance(v, str) else ""


def parse_adxo(data):
    """Validate /api/adxo. Returns (updated, entries); bad single entries are skipped."""
    obj = _json(data, "ADXO list")
    if not isinstance(obj, dict) or not isinstance(obj.get("entries"), list):
        raise DXMonError("DX Monitor's ADXO list wasn't in the expected form.")
    if len(obj["entries"]) > MAX_ENTRIES:
        raise DXMonError("DX Monitor's ADXO list was far longer than expected.")
    entries, skipped = [], 0
    for raw in obj["entries"]:
        if not isinstance(raw, dict):
            skipped += 1
            continue
        begin, end = _iso(raw.get("begin")), _iso(raw.get("end"))
        e = {"id": _text(raw.get("id"), 40), "name": _text(raw.get("dxcc"), 100),
             "callsign": _text(raw.get("callsign"), 30)}
        if not (e["id"] and e["name"] and e["callsign"] and begin and end and begin <= end):
            skipped += 1
            continue
        e.update(begin=begin.isoformat(), end=end.isoformat())
        entries.append(e)
    # An empty or mostly unreadable list means DX Monitor isn't ready or its
    # format changed: treat it as a failure, so the last good copy is kept
    # rather than every tag silently disappearing (review 2026-10-13).
    if not entries:
        raise DXMonError("DX Monitor's ADXO list had no usable DXpeditions"
                         + (f" ({skipped} unreadable)" if skipped else "") + ".")
    if skipped > len(entries):
        raise DXMonError(f"Most of DX Monitor's ADXO list was unreadable ({skipped} of "
                         f"{skipped + len(entries)} entries); its format may have changed.")
    updated = obj.get("updated") if isinstance(obj.get("updated"), str) else None
    return updated, entries, skipped


def parse_watched(data):
    """Validate /api/watched. Returns entries with the fields this app uses."""
    obj = _json(data, "Watched list")
    if not isinstance(obj, dict) or not isinstance(obj.get("entries"), list):
        raise DXMonError("DX Monitor's Watched list wasn't in the expected form.")
    if len(obj["entries"]) > MAX_ENTRIES:
        raise DXMonError("DX Monitor's Watched list was far longer than expected.")
    out = []
    for raw in obj["entries"]:
        if isinstance(raw, dict):
            out.append({"source_adxo_id": _text(raw.get("source_adxo_id"), 40),
                        "name": _text(raw.get("dxcc"), 100),
                        "callsign": _text(raw.get("callsign"), 30)})
    return out


def _split(v, limit=200):
    """DX Monitor stores several bands or modes as one comma-separated string
    (blank = any). A list of strings is accepted too; anything else means the
    format has changed, and is refused rather than read as "any"."""
    if v is None:
        return []
    if isinstance(v, list) and all(isinstance(x, str) for x in v):
        v = ",".join(v)
    if not isinstance(v, str):
        raise DXMonError("DX Monitor's Needed list has a band or mode in an unexpected form.")
    return sorted({p.strip().lower() for p in v[:limit].split(",") if p.strip()})


def parse_needed(data):
    """Validate /api/needed (D55). Returns (entries, skipped): the entity name as
    typed in DX Monitor (HamAlert's spelling) and the band and mode sets
    (empty = any). An empty list is valid: Dan may have no entries."""
    obj = _json(data, "Needed list")
    if not isinstance(obj, dict) or not isinstance(obj.get("entries"), list):
        raise DXMonError("DX Monitor's Needed list wasn't in the expected form.")
    if len(obj["entries"]) > MAX_ENTRIES:
        raise DXMonError("DX Monitor's Needed list was far longer than expected.")
    out, skipped = [], 0
    for raw in obj["entries"]:
        if isinstance(raw, dict) and _text(raw.get("entity"), 100):
            out.append({"name": _text(raw.get("entity"), 100),
                        "bands": _split(raw.get("band")), "modes": _split(raw.get("mode"))})
        else:
            skipped += 1
    return out, skipped


def fetch(base_url, fetcher=fetch_raw):
    """Fetch and validate the lists. Raises DXMonError; never returns partial data.

    The DXpedition and Watched lists must both succeed. The Needed list (D55,
    used only for the curation advisor's "already in DX Monitor" tags) is
    optional: if it fails, `needed` is None and `needed_error` says why, so an
    older DX Monitor or a hiccup there never costs the DXpedition tags."""
    updated, entries, skipped = parse_adxo(fetcher(base_url + "/api/adxo"))
    watched = parse_watched(fetcher(base_url + "/api/watched"))
    try:
        needed, needed_skipped = parse_needed(fetcher(base_url + "/api/needed"))
        needed_error = None
    except DXMonError as exc:
        needed, needed_skipped, needed_error = None, 0, str(exc)
    return {"adxo_updated": updated, "entries": entries, "skipped": skipped,
            "watched": watched, "needed": needed, "needed_skipped": needed_skipped,
            "needed_error": needed_error}


# ---------- names ----------

ABBREV = {"BR": "BRITISH", "ST": "SAINT", "STS": "SAINTS", "DEM": "DEMOCRATIC",
          "REP": "REPUBLIC", "N": "NORTH", "S": "SOUTH", "E": "EAST", "W": "WEST"}


def normalize(name):
    s = (name or "").upper().replace("&", " AND ")
    s = re.sub(r"[^A-Z0-9 ]+", " ", s)
    return " ".join(s.split())


def _variants(name):
    """The normalised name, plus abbreviations spelt out and a trailing Is/I expanded."""
    words = normalize(name).split()
    out = {" ".join(words)}
    full = [ABBREV.get(w, w) if i < len(words) - 1 or w not in ("S", "E", "W", "N") else w
            for i, w in enumerate(words)]
    for ws in (words, full):
        out.add(" ".join(ws))
        if ws and ws[-1] in ("IS", "I"):
            out.add(" ".join(ws[:-1] + ["ISLANDS"]))
            out.add(" ".join(ws[:-1] + ["ISLAND"]))
    return {v for v in out if v}


def load_builtin_aliases(reference, path=ALIASES_FILE):
    """The tested alias file: {normalised ADXO name: dxcc}. Every row must name a
    current entity, or the app refuses to load it (a typo must not go unnoticed)."""
    current = {e.dxcc for e in reference.current}
    out = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            dxcc = int(row["dxcc"])
            if dxcc not in current:
                raise ValueError(f"adxo_aliases.csv: {row['adxo_name']!r} names DXCC {dxcc}, "
                                 "which is not a current entity.")
            out[normalize(row["adxo_name"])] = dxcc
    return out


@dataclass
class Placed:
    dxcc: int | None
    how: str            # direct / builtin / approved / ignored / unplaced


class Matcher:
    def __init__(self, reference, builtin, decisions):
        """decisions: {normalised name: dxcc or None (ignored)} from the database."""
        self.reference = reference
        self.builtin = builtin
        self.decisions = decisions
        self.by_name = {}
        for e in reference.current:
            for n in (e.lotw_name, e.adif_name):
                self.by_name.setdefault(normalize(n), set()).add(e.dxcc)
        self.entities = {e.dxcc: e for e in reference.current}

    def place(self, name):
        hits = set()
        for v in _variants(name):
            hits |= self.by_name.get(v, set())
        if len(hits) == 1:
            return Placed(hits.pop(), "direct")
        key = normalize(name)
        # Dan's own decision outranks the built-in list, so a wrong built-in
        # row can always be overridden from Settings.
        if key in self.decisions:
            d = self.decisions[key]
            return Placed(d, "approved") if d is not None else Placed(None, "ignored")
        if key in self.builtin:
            return Placed(self.builtin[key], "builtin")
        return Placed(None, "unplaced")

    def suggest(self, name):
        """Best-looking entity for Dan to approve, or None. Never applied on its own."""
        best = None
        for e in self.reference.current:
            for cand in {normalize(e.lotw_name), normalize(e.adif_name)}:
                for v in _variants(name):
                    sc = difflib.SequenceMatcher(None, v, cand).ratio()
                    if best is None or sc > best[0]:
                        best = (sc, e)
        if best is None or best[0] < SUGGEST_MIN:
            return None
        e = best[1]
        return {"dxcc": e.dxcc, "name": e.lotw_name, "prefix": e.prefix}


# ---------- the view ----------

def _watched_index(watched, matcher):
    """Watched entries by ADXO id (with their entity and call), and by (entity, call)."""
    by_id, calls = {}, set()
    for w in watched:
        dxcc = matcher.place(w["name"]).dxcc
        call = w["callsign"].upper()
        if w["source_adxo_id"]:
            by_id.setdefault(w["source_adxo_id"], []).append((dxcc, call))
        if dxcc is not None and call:
            calls.add((dxcc, call))
    return by_id, calls


def _is_watched(e, dxcc, by_id, calls):
    call = e["callsign"].upper()
    # An id match counts only if the Watched entry agrees on the call or entity.
    if any(c == call or d == dxcc for d, c in by_id.get(e["id"], ())):
        return True
    return (dxcc, call) in calls


def dxpeditions_for(cache, matcher, dxcc, today, window=WINDOW_DAYS):
    """Every DXpedition in the stored list for one entity, for the entity report
    (D61): on the air, starting within the window ("soon"), or later. Unlike
    build(), this includes entities that are already credited, since a
    DXpedition is a chance at their missing band and mode slots too."""
    by_id, calls = _watched_index(cache["watched"], matcher)
    limit = today + timedelta(days=window)
    out = []
    for e in cache["entries"]:
        if matcher.place(e["name"]).dxcc != dxcc:
            continue
        begin, end = date.fromisoformat(e["begin"]), date.fromisoformat(e["end"])
        if end < today:
            continue
        kind = "air" if begin <= today else "soon" if begin <= limit else "later"
        out.append({"kind": kind, "callsign": e["callsign"], "begin": e["begin"],
                    "end": e["end"], "watched": _is_watched(e, dxcc, by_id, calls)})
    order = {"air": 0, "soon": 1, "later": 2}
    out.sort(key=lambda x: (order[x["kind"]], x["begin"], x["callsign"]))
    return out


def build(cache, matcher, needed, today, window=WINDOW_DAYS):
    """Tags for the needed entities, the summary line, and the names to settle.

    cache   — the stored result of fetch()
    needed  — DXCC numbers on Missing Entities
    today   — date used for "on the air" and the window (DX Monitor's own
              'active' flag is not trusted, since the stored copy may be old)
    """
    limit = today + timedelta(days=window)
    by_id, calls = _watched_index(cache["watched"], matcher)
    tags, later, names = {}, set(), {}
    counts = {"direct": 0, "builtin": 0, "approved": 0, "ignored": 0, "unplaced": 0}
    for e in cache["entries"]:
        p = matcher.place(e["name"])
        key = normalize(e["name"])      # "Somalia" and "SOMALIA" are one name
        if key not in names:
            names[key] = (p, e)
            counts[p.how] += 1
        if p.dxcc is None or p.dxcc not in needed:
            continue
        begin, end = date.fromisoformat(e["begin"]), date.fromisoformat(e["end"])
        if end < today:
            continue
        on_air = begin <= today
        if not on_air and begin > limit:
            later.add(p.dxcc)
            continue
        watched = _is_watched(e, p.dxcc, by_id, calls)
        tags.setdefault(p.dxcc, []).append({
            "kind": "air" if on_air else "soon", "callsign": e["callsign"],
            "begin": e["begin"], "end": e["end"], "watched": watched})
    for t in tags.values():
        t.sort(key=lambda x: (x["kind"] != "air", x["begin"], x["callsign"]))
    later -= set(tags)
    first = {d: t[0] for d, t in tags.items()}
    summary = {
        "on_air": sum(1 for t in first.values() if t["kind"] == "air"),
        "soon": sum(1 for t in first.values() if t["kind"] == "soon"),
        "not_watched": sum(1 for t in first.values() if not t["watched"]),
        "later": len(later),
    }
    unplaced = []
    for p, e in sorted(names.values(), key=lambda pe: pe[1]["name"].lower()):
        if p.how == "unplaced":
            unplaced.append({"name": e["name"], "example": f"{e['callsign']}, {e['begin']} to {e['end']}",
                             "suggestion": matcher.suggest(e["name"])})
    counts["names"] = len(names)
    return {"tags": {str(d): t for d, t in tags.items()}, "summary": summary,
            "names": counts, "unplaced": unplaced, "window_days": window}
