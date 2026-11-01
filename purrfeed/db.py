import random
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path

from flask import current_app, g

TIME_FORMAT = "%Y-%m-%d %H:%M:%S"

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
    kind        TEXT    NOT NULL CHECK (kind IN ('beri', 'tahan', 'isi_ulang')),
    grams       REAL    NOT NULL DEFAULT 0,
    label       TEXT,
    confidence  REAL,
    thumbnail   TEXT
);
CREATE INDEX IF NOT EXISTS events_code_ts ON events(code, ts);
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


def init_app(app):
    path = Path(app.config["DATABASE"])
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as conn:
        conn.executescript(SCHEMA)
        if conn.execute("SELECT COUNT(*) FROM devices").fetchone()[0] == 0:
            seed_devices(conn, app.config)
        conn.commit()
    app.teardown_appcontext(close_db)


def seed_devices(conn, config):
    """Demo devices; those marked True get seven days of simulated feeding history."""
    rnd = random.Random(42)
    capacity, portion, noise = config["TANK_CAPACITY_G"], config["PORTION_G"], config["PORTION_NOISE_G"]
    for code, with_history in config["SEED_DEVICES"].items():
        stock = capacity
        if with_history:
            events = simulated_history(code, capacity, portion, noise, rnd)
            conn.executemany(
                "INSERT INTO events(code, ts, kind, grams, label, confidence) VALUES (?, ?, ?, ?, ?, ?)", events)
            stock -= sum(event[3] for event in events if event[2] == "beri")
        conn.execute("INSERT INTO devices(code, capacity_g, stock_g, portion_g) VALUES (?, ?, ?, ?)",
                     (code, capacity, round(stock, 1), portion))


def simulated_history(code, capacity, portion, noise, rnd, days=7):
    start = datetime.combine(date.today() - timedelta(days=days), datetime.min.time())
    events = [(code, timestamp(start + timedelta(hours=6)), "isi_ulang", capacity, None, None)]
    for offset in range(days):
        day = start + timedelta(days=offset)
        for hour in sorted(rnd.sample([7, 12, 17, 21], rnd.choice([3, 4]))):
            moment = day + timedelta(hours=hour, minutes=rnd.randint(0, 50))
            grams = round(portion + rnd.uniform(-noise, noise), 1)
            events.append((code, timestamp(moment), "beri", grams, "kucing", round(rnd.uniform(0.85, 0.99), 3)))
        for _ in range(rnd.randint(0, 2)):
            moment = day + timedelta(hours=rnd.randint(8, 22), minutes=rnd.randint(0, 59))
            events.append((code, timestamp(moment), "tahan", 0, "nonkucing", round(rnd.uniform(0.7, 0.99), 3)))
    return events


def get_device(code):
    return get_db().execute("SELECT * FROM devices WHERE code = ?", (code,)).fetchone()


def claim_device(code, mode):
    with get_db() as conn:
        conn.execute("UPDATE devices SET mode = ?, claimed = 1 WHERE code = ?", (mode, code))


def record_event(conn, code, kind, grams=0.0, label=None, confidence=None, thumbnail=None):
    conn.execute(
        "INSERT INTO events(code, ts, kind, grams, label, confidence, thumbnail) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (code, timestamp(), kind, grams, label, confidence, thumbnail))


def daily_totals(code, since):
    return get_db().execute(
        "SELECT substr(ts, 1, 10) AS day, kind, SUM(grams) AS grams, COUNT(*) AS n FROM events "
        "WHERE code = ? AND ts >= ? AND kind IN ('beri', 'tahan') GROUP BY day, kind",
        (code, since.isoformat())).fetchall()


def recent_events(code, limit=20):
    return get_db().execute(
        "SELECT ts, kind, grams, label, confidence, thumbnail FROM events WHERE code = ? "
        "ORDER BY ts DESC, id DESC LIMIT ?", (code, limit)).fetchall()
