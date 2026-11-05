import sqlite3
import time
from contextlib import closing
from datetime import datetime
from pathlib import Path

from flask import current_app, g

TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
SCHEMA_VERSION = 3

SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
    code        TEXT PRIMARY KEY,
    mode        TEXT    NOT NULL DEFAULT 'kucing',
    claimed     INTEGER NOT NULL DEFAULT 0,
    capacity_g  REAL    NOT NULL,
    stock_g     REAL    NOT NULL,
    portion_g   REAL    NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    code        TEXT    NOT NULL REFERENCES devices(code),
    ts          TEXT    NOT NULL,
    kind        TEXT    NOT NULL CHECK (kind IN ('beri', 'tahan', 'buang', 'isi_ulang')),
    grams       REAL    NOT NULL DEFAULT 0,
    label       TEXT,
    confidence  REAL,
    thumbnail   TEXT,
    mode        TEXT,
    source      TEXT    NOT NULL DEFAULT 'esp32cam' CHECK (source IN ('esp32cam', 'upload', 'servo', 'sistem')),
    elapsed_ms  REAL,
    ref_id      INTEGER REFERENCES events(id)   -- 'buang' menunjuk ke pemberian yang sisanya dibuang
);
CREATE INDEX IF NOT EXISTS events_code_ts ON events(code, ts);
CREATE INDEX IF NOT EXISTS events_ref ON events(ref_id);
"""


def timestamp(moment=None):
    return (moment or datetime.now()).strftime(TIME_FORMAT)


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
    return g.db


def close_db(_error=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def archive_outdated(path):
    """A database from an older schema is moved aside (never deleted); a fresh one is built with demo data."""
    if not path.exists():
        return
    with closing(sqlite3.connect(path)) as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version >= SCHEMA_VERSION:
        return
    backup = path.with_name(f"{path.name}.v{version}-{int(time.time())}.bak")
    path.rename(backup)
    print(f"[purrfeed] skema database lama dipindah ke {backup.name}; database baru dibuat")


def init_app(app):
    path = Path(app.config["DATABASE"])
    path.parent.mkdir(parents=True, exist_ok=True)
    archive_outdated(path)
    with closing(sqlite3.connect(path)) as conn:
        conn.executescript(SCHEMA)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        if conn.execute("SELECT COUNT(*) FROM devices").fetchone()[0] == 0:
            seed_devices(conn, app.config)
        conn.commit()
    app.teardown_appcontext(close_db)


def seed_devices(conn, config):
    """Registered device IDs with a full tank and no history. Events only come from real classifications."""
    for code, mode in config["SEED_DEVICES"].items():
        conn.execute("INSERT INTO devices(code, mode, claimed, capacity_g, stock_g, portion_g) VALUES (?, ?, 0, ?, ?, ?)",
                     (code, mode, config["TANK_CAPACITY_G"], config["TANK_CAPACITY_G"], config["PORTION_G"]))


def get_device(code):
    return get_db().execute("SELECT * FROM devices WHERE code = ?", (code,)).fetchone()


def register_device(code, mode):
    """First contact from a provisioned device (PF-XXXXX): full tank, no history. No-op if it already exists."""
    config = current_app.config
    with get_db() as conn:
        conn.execute("INSERT OR IGNORE INTO devices(code, mode, claimed, capacity_g, stock_g, portion_g) VALUES (?, ?, 0, ?, ?, ?)",
                     (code, mode, config["TANK_CAPACITY_G"], config["TANK_CAPACITY_G"], config["PORTION_G"]))
    return get_device(code)


def claim_device(code, mode):
    with get_db() as conn:
        conn.execute("UPDATE devices SET mode = ?, claimed = 1 WHERE code = ?", (mode, code))


def record_event(conn, code, kind, grams=0.0, label=None, confidence=None, thumbnail=None,
                 mode=None, source="esp32cam", elapsed_ms=None, ref_id=None):
    cursor = conn.execute(
        "INSERT INTO events(code, ts, kind, grams, label, confidence, thumbnail, mode, source, elapsed_ms, ref_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (code, timestamp(), kind, grams, label, confidence, thumbnail, mode, source, elapsed_ms, ref_id))
    return cursor.lastrowid


def daily_totals(code, since):
    """Tank-level feeding per day (all modes), for the stock forecast."""
    return get_db().execute(
        "SELECT substr(ts, 1, 10) AS day, kind, SUM(grams) AS grams, COUNT(*) AS n FROM events "
        "WHERE code = ? AND ts >= ? AND kind IN ('beri', 'tahan') GROUP BY day, kind",
        (code, since.isoformat())).fetchall()


def events_since(code, mode, since):
    """Events of the active animal mode plus device-wide ones (mode NULL, e.g. refills), newest first."""
    return get_db().execute(
        "SELECT * FROM events WHERE code = ? AND ts >= ? AND (mode = ? OR mode IS NULL) ORDER BY ts DESC, id DESC",
        (code, since.isoformat(), mode)).fetchall()
