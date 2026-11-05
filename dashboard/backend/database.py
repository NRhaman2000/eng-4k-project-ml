"""SQLite telemetry log: one row per accepted packet, plus an events table.

Columns keep the original names so /api/history stays compatible; values are
NULL where the source did not report them.

Migration never deletes data. Before an old schema is changed, the whole file
is copied to <db>.backup-<timestamp>.db using SQLite's online backup. Then the
old table is renamed (v0 to telemetry_legacy, v1/v2 to telemetry_legacy_vN, and an
old events table to events_legacy_vN) and row counts are checked. If the backup or the check fails, startup stops.
"""
import json
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "telemetry.db"
SCHEMA_VERSION = 3
LEGACY_TABLES = {0: "telemetry_legacy", 1: "telemetry_legacy_v1", 2: "telemetry_legacy_v2"}


class MigrationError(RuntimeError):
    pass

CELL_COLS = ["voltage", "temp", "soh", "balancing", "bypassed", "fault"]
COLUMNS = (
    ["timestamp", "transport", "data_origin", "seq", "mcu_ms", "scenario", "pack_voltage", "pack_current", "soc", "pack_soh"]
    + [f"cell{n}_{c}" for c in CELL_COLS for n in range(1, 5)]
    + ["balancing", "fault_active", "fault_cell", "fault_type", "system_state",
       "invalid_json", "warnings_json"]
)
EVENT_COLUMNS = ["timestamp", "transport", "data_origin", "seq", "kind", "cell", "detail", "message"]


def _sql_type(col):
    if col in ("timestamp", "transport", "data_origin", "scenario", "fault_type", "system_state", "invalid_json",
               "warnings_json") or col.endswith("_fault"):
        return "TEXT"
    if col in ("seq", "mcu_ms", "fault_cell", "fault_active", "balancing") or col.endswith(("_balancing", "_bypassed")):
        return "INTEGER"
    return "REAL"


def get_connection(path=None):
    return sqlite3.connect(path or DB_PATH)


def backup_db(path=None):
    """Copy the whole database with SQLite's online backup API. Returns the backup path."""
    src_path = Path(path or DB_PATH)
    dest = src_path.with_name(f"{src_path.stem}.backup-{datetime.now():%Y%m%d-%H%M%S}{src_path.suffix}")
    n = 1
    while dest.exists():
        dest = src_path.with_name(f"{src_path.stem}.backup-{datetime.now():%Y%m%d-%H%M%S}-{n}{src_path.suffix}")
        n += 1
    src, dst = sqlite3.connect(src_path), sqlite3.connect(dest)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return dest


def _count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def init_db(path=None):
    """Create or migrate the schema. Returns the backup path if a migration made one."""
    backup = None
    conn = get_connection(path)
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        has_old = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='telemetry'").fetchone()
        if version < SCHEMA_VERSION and has_old:
            legacy = LEGACY_TABLES.get(version, f"telemetry_legacy_v{version}")
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (legacy,)).fetchone():
                raise MigrationError(f"{legacy} already exists; refusing to overwrite it")
            before = _count(conn, "telemetry")
            conn.close()
            try:
                backup = backup_db(path)
            except Exception as e:
                raise MigrationError(f"backup failed, not migrating: {e}")
            check = sqlite3.connect(backup)
            try:
                if _count(check, "telemetry") != before:
                    raise MigrationError("backup row count does not match, not migrating")
            finally:
                check.close()
            conn = get_connection(path)
            conn.execute(f"ALTER TABLE telemetry RENAME TO {legacy}")
            if _count(conn, legacy) != before:
                conn.rollback()
                raise MigrationError(f"{legacy} row count changed during migration")
            has_events = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='events'").fetchone()
            if has_events:  # v2 events lack transport/data_origin: keep them alongside, unchanged
                ev_before = _count(conn, "events")
                conn.execute(f"ALTER TABLE events RENAME TO events_legacy_v{version}")
                if _count(conn, f"events_legacy_v{version}") != ev_before:
                    raise MigrationError("events row count changed during migration")
        cols = ",\n".join(f"{c} {_sql_type(c)}" for c in COLUMNS)
        conn.execute(f"""CREATE TABLE IF NOT EXISTS telemetry (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            {cols}
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL, transport TEXT, data_origin TEXT, seq INTEGER,
            kind TEXT NOT NULL, cell INTEGER, detail TEXT, message TEXT
        )""")
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.commit()
        # WAL: a long CSV export (an open read) must not block the ingestion loop's writes,
        # or live rows are lost with "database is locked". The setting persists in the file.
        conn.execute("PRAGMA journal_mode=WAL")
    finally:
        conn.close()
    return backup


def _row(packet):
    cells = {c.id: c for c in packet.cells}
    def b(x):
        return None if x is None else int(x)
    values = {
        "timestamp": packet.timestamp, "transport": packet.transport, "data_origin": packet.data_origin,
        "seq": packet.seq,
        "mcu_ms": packet.mcu_ms, "scenario": packet.scenario,
        "pack_voltage": packet.pack_voltage, "pack_current": packet.pack_current,
        "soc": packet.soc, "pack_soh": packet.pack_soh,
        "balancing": b(packet.balancing), "fault_active": int(packet.fault.active),
        "fault_cell": packet.fault.cell, "fault_type": packet.fault.type,
        "system_state": packet.system_state,
        "invalid_json": json.dumps([i.model_dump() for i in packet.invalid]) if packet.invalid else None,
        "warnings_json": json.dumps([w.model_dump() for w in packet.warnings]) if packet.warnings else None,
    }
    for n in range(1, 5):
        c = cells[n]
        values.update({f"cell{n}_voltage": c.voltage, f"cell{n}_temp": c.temperature,
                       f"cell{n}_soh": c.soh, f"cell{n}_balancing": b(c.balancing),
                       f"cell{n}_bypassed": b(c.bypassed), f"cell{n}_fault": c.fault})
    return [values[c] for c in COLUMNS]


def save_telemetry(packet, path=None):
    conn = get_connection(path)
    try:
        conn.execute(f"INSERT INTO telemetry ({','.join(COLUMNS)}) VALUES ({','.join('?' * len(COLUMNS))})",
                     _row(packet))
        conn.commit()
    finally:
        conn.close()


def get_recent_telemetry(limit=50, path=None):
    conn = get_connection(path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT * FROM telemetry ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def count_rows(path=None, table="telemetry"):
    conn = get_connection(path)
    try:
        return _count(conn, table)
    finally:
        conn.close()


def save_events(events, path=None):
    if not events:
        return
    conn = get_connection(path)
    try:
        conn.executemany(f"INSERT INTO events ({','.join(EVENT_COLUMNS)}) VALUES ({','.join('?' * len(EVENT_COLUMNS))})",
                         [[e.get(c) for c in EVENT_COLUMNS] for e in events])
        conn.commit()
    finally:
        conn.close()


def get_recent_events(limit=100, path=None):
    conn = get_connection(path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def get_legacy_telemetry(limit=50, path=None):
    """Rows kept from the prototype schema (telemetry_legacy). Empty if there are none."""
    conn = get_connection(path)
    conn.row_factory = sqlite3.Row
    try:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='telemetry_legacy'").fetchone():
            return {"total": 0, "rows": []}
        total = _count(conn, "telemetry_legacy")
        rows = conn.execute("SELECT * FROM telemetry_legacy ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    finally:
        conn.close()
    return {"total": total, "rows": [dict(r) for r in rows]}
