"""
SQLite storage (plain sqlite3, one file).

Only credited cells are stored; "needed" is always computed from credits
plus the profile, so a profile change never needs a re-import.

Snapshot status: preview / held (waiting for Save or Discard), current,
previous, discarded. Nothing becomes current without Dan's Save.

Privacy: the paste itself is NOT stored — its "Name, Callsign" line holds
Dan's name, and only the callsign is kept (D39). The snapshot stores the
parsed credits, totals and warnings, which is everything the app needs.
"""

import json
import sqlite3
from datetime import datetime, timezone

from .categories import DEFAULT_PROFILE, Profile
from .marks import Mark
from .paper import PaperQSL

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id           INTEGER PRIMARY KEY,
    imported_at  TEXT NOT NULL,
    source       TEXT NOT NULL,          -- paste / file name
    callsign     TEXT,
    status       TEXT NOT NULL,          -- preview, held, current, previous, discarded
    based_on     INTEGER,                -- the current snapshot when previewed
    warnings     TEXT NOT NULL DEFAULT '[]',
    totals_json  TEXT NOT NULL DEFAULT '{}',
    rows_read    INTEGER NOT NULL DEFAULT 0,
    saved_at     TEXT
);
CREATE TABLE IF NOT EXISTS snapshot_credits (
    snapshot_id  INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    dxcc         INTEGER NOT NULL,
    category     TEXT NOT NULL,
    PRIMARY KEY (snapshot_id, dxcc, category)
);
CREATE TABLE IF NOT EXISTS pending_marks (
    id                  INTEGER PRIMARY KEY,
    dxcc                INTEGER NOT NULL,
    category            TEXT NOT NULL,
    state               TEXT NOT NULL,   -- awaiting / wont_submit
    note                TEXT NOT NULL DEFAULT '',
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    cleared_at          TEXT,
    cleared_reason      TEXT,            -- credited / removed
    cleared_by_snapshot INTEGER
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_mark
    ON pending_marks (dxcc, category) WHERE cleared_at IS NULL;
CREATE TABLE IF NOT EXISTS paper_qsls (
    id                   INTEGER PRIMARY KEY,
    dxcc                 INTEGER NOT NULL,
    band                 TEXT,           -- NULL for a Satellite card
    mode                 TEXT NOT NULL,
    state                TEXT NOT NULL,  -- in_hand / submitted
    call                 TEXT NOT NULL DEFAULT '',
    qso_date             TEXT NOT NULL DEFAULT '',
    note                 TEXT NOT NULL DEFAULT '',
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL,
    credited_at          TEXT,
    credited_by_snapshot INTEGER
);
CREATE TABLE IF NOT EXISTS status_checks (
    id           INTEGER PRIMARY KEY,
    checked_at   TEXT NOT NULL,
    snapshot_id  INTEGER,
    result_json  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS external_data (
    name          TEXT PRIMARY KEY,
    fetched_at    TEXT NOT NULL,
    payload_json  TEXT NOT NULL
);
"""

PENDING = ("preview", "held")


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path):
    # One connection per request; FastAPI may open it in one worker thread and
    # use it in another, but never from two threads at once.
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init(conn):
    conn.executescript(SCHEMA)
    conn.commit()


# ---------- snapshots ----------

def current_snapshot(conn):
    return conn.execute("SELECT * FROM snapshots WHERE status = 'current'").fetchone()


def get_snapshot(conn, sid):
    return conn.execute("SELECT * FROM snapshots WHERE id = ?", (sid,)).fetchone()


def credits_of(conn, sid):
    out = {}
    for r in conn.execute("SELECT dxcc, category FROM snapshot_credits WHERE snapshot_id = ?", (sid,)):
        out.setdefault(r["dxcc"], set()).add(r["category"])
    return {d: frozenset(c) for d, c in out.items()}


def current_credits(conn):
    snap = current_snapshot(conn)
    return (credits_of(conn, snap["id"]) if snap else None), snap


class NotPromotable(Exception):
    """The snapshot can't become current (anymore); the message says why."""


def store_preview(conn, result, source, held, based_on):
    """Store a validated import awaiting Save. Any earlier unsaved preview is
    discarded, so only one can be pending at a time.

    `based_on` is the id of the snapshot the import was VALIDATED against
    (review fix: not whatever is current at the moment of storing), so Save
    can refuse if the current data has changed since."""
    conn.execute("UPDATE snapshots SET status = 'discarded' WHERE status IN ('preview', 'held')")
    sid = conn.execute(
        "INSERT INTO snapshots (imported_at, source, callsign, status, based_on, warnings, "
        "totals_json, rows_read) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (now(), source, result.callsign, "held" if held else "preview",
         based_on, json.dumps(result.warnings), json.dumps(result.totals),
         result.rows_read)).lastrowid
    conn.executemany(
        "INSERT INTO snapshot_credits (snapshot_id, dxcc, category) VALUES (?, ?, ?)",
        [(sid, d, c) for d, cats in result.credits.items() for c in cats])
    conn.commit()
    return sid


_ANY = object()


def make_current(conn, sid, allowed, expect_current=_ANY):
    """Make a snapshot current; the old current becomes previous.

    All checks and writes happen in ONE locked transaction (BEGIN IMMEDIATE),
    so two requests at once can't both pass the checks (review fix):
      * the snapshot's status must still be in `allowed`;
      * if `expect_current` is given, the current snapshot must still be that
        one (None = no current data yet).
    Raises NotPromotable otherwise; nothing is changed.
    Returns (marks_cleared, cards_credited)."""
    if conn.in_transaction:
        # Callers must only have READ before calling; an uncommitted write here
        # would be swept into (or rolled back with) this transaction.
        raise RuntimeError("make_current() needs a connection with no open transaction")
    conn.execute("BEGIN IMMEDIATE")
    try:
        snap = get_snapshot(conn, sid)
        if snap is None or snap["status"] not in allowed:
            raise NotPromotable("That import can't be made current. Preview it again.")
        cur = current_snapshot(conn)
        if expect_current is not _ANY and (cur["id"] if cur else None) != expect_current:
            raise NotPromotable("The current data changed since this preview. Preview again.")
        ts = now()
        conn.execute("UPDATE snapshots SET status = 'previous' WHERE status = 'current'")
        conn.execute("UPDATE snapshots SET status = 'current', saved_at = COALESCE(saved_at, ?) "
                     "WHERE id = ?", (ts, sid))
        credits = credits_of(conn, sid)
        cleared = 0
        for mid, mark in active_marks(conn):
            if mark.category in credits.get(mark.dxcc, ()):
                conn.execute("UPDATE pending_marks SET cleared_at = ?, cleared_reason = 'credited', "
                             "cleared_by_snapshot = ? WHERE id = ?", (ts, sid, mid))
                cleared += 1
        credited = 0
        for cid, card in active_cards(conn):
            if all(c in credits.get(card.dxcc, ()) for c in card.categories):
                conn.execute("UPDATE paper_qsls SET credited_at = ?, credited_by_snapshot = ? "
                             "WHERE id = ?", (ts, sid, cid))
                credited += 1
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return cleared, credited


def discard(conn, sid):
    conn.execute("UPDATE snapshots SET status = 'discarded' WHERE id = ? AND status IN "
                 "('preview', 'held')", (sid,))
    conn.commit()


def list_snapshots(conn):
    return conn.execute("SELECT id, imported_at, saved_at, source, callsign, status, warnings, "
                        "totals_json, rows_read FROM snapshots WHERE status != 'discarded' "
                        "ORDER BY id DESC").fetchall()


def delete_snapshot(conn, sid):
    conn.execute("DELETE FROM snapshots WHERE id = ?", (sid,))
    conn.commit()


def stored_dxccs(conn):
    """Every DXCC number the database refers to: credits, active marks, cards."""
    return {r[0] for r in conn.execute(
        "SELECT dxcc FROM snapshot_credits UNION SELECT dxcc FROM pending_marks "
        "WHERE cleared_at IS NULL UNION SELECT dxcc FROM paper_qsls WHERE credited_at IS NULL")}


def cleared_marks(conn, sid):
    """Marks that this snapshot's import cleared (shown in the history, spec 5.4)."""
    return conn.execute("SELECT dxcc, category, state FROM pending_marks "
                        "WHERE cleared_by_snapshot = ? AND cleared_reason = 'credited' "
                        "ORDER BY dxcc, category", (sid,)).fetchall()


# ---------- settings ----------

def get_profile(conn):
    r = conn.execute("SELECT value FROM settings WHERE key = 'profile'").fetchone()
    if not r:
        return DEFAULT_PROFILE
    v = json.loads(r["value"])
    return Profile(bands=tuple(v["bands"]), modes=tuple(v["modes"]))


def set_profile(conn, profile):
    conn.execute("INSERT INTO settings (key, value) VALUES ('profile', ?) "
                 "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                 (json.dumps({"bands": list(profile.bands), "modes": list(profile.modes)}),))
    conn.commit()


# ---------- pending marks ----------

def active_marks(conn):
    return [(r["id"], Mark(r["dxcc"], r["category"], r["state"], r["note"]))
            for r in conn.execute("SELECT * FROM pending_marks WHERE cleared_at IS NULL "
                                  "ORDER BY id")]


def add_mark(conn, mark):
    ts = now()
    mid = conn.execute("INSERT INTO pending_marks (dxcc, category, state, note, created_at, "
                       "updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                       (mark.dxcc, mark.category, mark.state, mark.note, ts, ts)).lastrowid
    conn.commit()
    return mid


def get_active_mark(conn, mid):
    r = conn.execute("SELECT * FROM pending_marks WHERE id = ? AND cleared_at IS NULL",
                     (mid,)).fetchone()
    return Mark(r["dxcc"], r["category"], r["state"], r["note"]) if r else None


def update_mark(conn, mid, state, note):
    conn.execute("UPDATE pending_marks SET state = ?, note = ?, updated_at = ? WHERE id = ?",
                 (state, note, now(), mid))
    conn.commit()


def remove_mark(conn, mid):
    conn.execute("UPDATE pending_marks SET cleared_at = ?, cleared_reason = 'removed' "
                 "WHERE id = ? AND cleared_at IS NULL", (now(), mid))
    conn.commit()


# ---------- paper QSL cards ----------

def _card(r):
    return PaperQSL(r["dxcc"], r["band"], r["mode"], r["state"], r["call"], r["qso_date"],
                    r["note"])


def active_cards(conn):
    return [(r["id"], _card(r)) for r in
            conn.execute("SELECT * FROM paper_qsls WHERE credited_at IS NULL ORDER BY id")]


def get_active_card(conn, cid):
    r = conn.execute("SELECT * FROM paper_qsls WHERE id = ? AND credited_at IS NULL",
                     (cid,)).fetchone()
    return _card(r) if r else None


def add_card(conn, card):
    ts = now()
    cid = conn.execute(
        "INSERT INTO paper_qsls (dxcc, band, mode, state, call, qso_date, note, created_at, "
        "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (card.dxcc, card.band, card.mode, card.state, card.call, card.qso_date, card.note,
         ts, ts)).lastrowid
    conn.commit()
    return cid


def update_card(conn, cid, state, note):
    conn.execute("UPDATE paper_qsls SET state = ?, note = ?, updated_at = ? WHERE id = ?",
                 (state, note, now(), cid))
    conn.commit()


def delete_card(conn, cid):
    conn.execute("DELETE FROM paper_qsls WHERE id = ?", (cid,))
    conn.commit()


# ---------- status checks and external data ----------

def add_status_check(conn, snapshot_id, result):
    conn.execute("INSERT INTO status_checks (checked_at, snapshot_id, result_json) "
                 "VALUES (?, ?, ?)", (now(), snapshot_id, json.dumps(result)))
    conn.commit()


def latest_status_check(conn):
    return conn.execute("SELECT * FROM status_checks ORDER BY id DESC LIMIT 1").fetchone()


def get_external(conn, name):
    r = conn.execute("SELECT * FROM external_data WHERE name = ?", (name,)).fetchone()
    return (json.loads(r["payload_json"]), r["fetched_at"]) if r else (None, None)


def set_external(conn, name, payload):
    conn.execute("INSERT INTO external_data (name, fetched_at, payload_json) VALUES (?, ?, ?) "
                 "ON CONFLICT(name) DO UPDATE SET fetched_at = excluded.fetched_at, "
                 "payload_json = excluded.payload_json", (name, now(), json.dumps(payload)))
    conn.commit()
