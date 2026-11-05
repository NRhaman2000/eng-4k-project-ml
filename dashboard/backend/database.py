"""SQLite telemetry log. One row per packet the ingestion loop accepts.

Columns keep the original names so /api/history stays compatible; values are
NULL where the source did not report them. The first start on an old database
renames the original table to telemetry_legacy instead of deleting it.
"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "telemetry.db"
SCHEMA_VERSION = 1

CELL_COLS = ["voltage", "temp", "soh", "balancing", "bypassed", "fault"]
COLUMNS = (
    ["timestamp", "source", "seq", "mcu_ms", "scenario", "pack_voltage", "pack_current", "soc", "pack_soh"]
    + [f"cell{n}_{c}" for c in CELL_COLS for n in range(1, 5)]
    + ["balancing", "fault_active", "fault_cell", "fault_type", "system_state"]
)


def _sql_type(col):
    if col in ("timestamp", "source", "scenario", "fault_type", "system_state") or col.endswith("_fault"):
        return "TEXT"
    if col in ("seq", "mcu_ms", "fault_cell", "fault_active", "balancing") or col.endswith(("_balancing", "_bypassed")):
        return "INTEGER"
    return "REAL"


def get_connection(path=None):
    return sqlite3.connect(path or DB_PATH)


def init_db(path=None):
    conn = get_connection(path)
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        has_old = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='telemetry'").fetchone()
        if version < SCHEMA_VERSION and has_old:
            conn.execute("ALTER TABLE telemetry RENAME TO telemetry_legacy")
        cols = ",\n".join(f"{c} {_sql_type(c)}" for c in COLUMNS)
        conn.execute(f"""CREATE TABLE IF NOT EXISTS telemetry (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            {cols}
        )""")
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.commit()
    finally:
        conn.close()


def _row(packet):
    cells = {c.id: c for c in packet.cells}
    def b(x):
        return None if x is None else int(x)
    values = {
        "timestamp": packet.timestamp, "source": packet.source, "seq": packet.seq,
        "mcu_ms": packet.mcu_ms, "scenario": packet.scenario,
        "pack_voltage": packet.pack_voltage, "pack_current": packet.pack_current,
        "soc": packet.soc, "pack_soh": packet.pack_soh,
        "balancing": b(packet.balancing), "fault_active": int(packet.fault.active),
        "fault_cell": packet.fault.cell, "fault_type": packet.fault.type,
        "system_state": packet.system_state,
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


def count_rows(path=None):
    conn = get_connection(path)
    try:
        return conn.execute("SELECT COUNT(*) FROM telemetry").fetchone()[0]
    finally:
        conn.close()
