"""
Club Log "Most Wanted" ranking — public, no account or API key.

Source: https://clublog.org/mostwanted.php?api=1
Format (checked 2026-10-04): a JSON object mapping rank to ADIF DXCC
number, both as strings, e.g. {"1": "344", "2": "123", ...}, 340 entries.
Rank 1 is the most wanted entity worldwide.

Fetched only when Dan asks (no schedule). A response is accepted only if it
passes every check below; otherwise the caller keeps the previous rankings.
"""

import json
import urllib.request

URL = "https://clublog.org/mostwanted.php?api=1"
USER_AGENT = "N4MI-DXCC-Analyzer (+https://github.com/N4MI73/n4mi-dxcc-analyzer)"
TIMEOUT_S = 15
MIN_ENTRIES, MAX_ENTRIES = 300, 400


class ClubLogError(Exception):
    """The ranking could not be fetched or failed validation."""


def fetch_raw(timeout=TIMEOUT_S):
    req = urllib.request.Request(URL, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                raise ClubLogError(f"Club Log answered HTTP {resp.status}.")
            return resp.read()
    except ClubLogError:
        raise
    except Exception as exc:
        raise ClubLogError(f"Could not reach Club Log: {exc}") from exc


def parse_rankings(data, reference):
    """Validate a Most Wanted response; return {dxcc: rank}."""
    try:
        obj = json.loads(data)
    except (ValueError, TypeError) as exc:
        raise ClubLogError("Club Log's response was not valid JSON.") from exc
    if not isinstance(obj, dict):
        raise ClubLogError("Club Log's response was not the expected ranking list.")
    if not MIN_ENTRIES <= len(obj) <= MAX_ENTRIES:
        raise ClubLogError(f"Club Log returned {len(obj)} entries; expected about 340.")
    rankings = {}
    current = {e.dxcc for e in reference.current}
    for rank, dxcc in obj.items():
        if not (_whole(rank) and _whole(dxcc)):
            raise ClubLogError("Club Log's response contained a non-numeric entry.")
        rank, dxcc = int(rank), int(dxcc)
        if dxcc not in current:
            raise ClubLogError(f"Club Log ranks DXCC {dxcc}, which is not a current entity.")
        if dxcc in rankings:
            raise ClubLogError(f"Club Log ranks DXCC {dxcc} twice.")
        rankings[dxcc] = rank
    if sorted(rankings.values()) != list(range(1, len(rankings) + 1)):
        raise ClubLogError("Club Log's ranks are not a simple 1, 2, 3 ... sequence.")
    return rankings


def _whole(v):
    """A positive whole number, as Club Log sends it (a digit string)."""
    if isinstance(v, int) and not isinstance(v, bool):
        return v > 0
    return isinstance(v, str) and v.isascii() and v.isdigit() and int(v) > 0


def fetch_rankings(reference, fetch=fetch_raw):
    """Fetch and validate. `fetch` is replaceable for tests."""
    return parse_rankings(fetch(), reference)
