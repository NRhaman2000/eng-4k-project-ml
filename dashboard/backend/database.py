import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "telemetry.db"


def get_connection():
    return sqlite3.connect(DB_PATH)


def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS telemetry (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            pack_voltage REAL NOT NULL,
            pack_current REAL NOT NULL,

            cell1_voltage REAL NOT NULL,
            cell2_voltage REAL NOT NULL,
            cell3_voltage REAL NOT NULL,
            cell4_voltage REAL NOT NULL,

            cell1_temp REAL NOT NULL,
            cell2_temp REAL NOT NULL,
            cell3_temp REAL NOT NULL,
            cell4_temp REAL NOT NULL,

            cell1_soh REAL NOT NULL,
            cell2_soh REAL NOT NULL,
            cell3_soh REAL NOT NULL,
            cell4_soh REAL NOT NULL,

            balancing INTEGER NOT NULL,
            fault_active INTEGER NOT NULL,
            fault_cell INTEGER,
            fault_type TEXT,
            system_state TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()


def save_telemetry(packet):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO telemetry (
            timestamp,
            pack_voltage,
            pack_current,

            cell1_voltage,
            cell2_voltage,
            cell3_voltage,
            cell4_voltage,

            cell1_temp,
            cell2_temp,
            cell3_temp,
            cell4_temp,

            cell1_soh,
            cell2_soh,
            cell3_soh,
            cell4_soh,

            balancing,
            fault_active,
            fault_cell,
            fault_type,
            system_state
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        packet.timestamp,
        packet.pack_voltage,
        packet.pack_current,

        packet.cells[0].voltage,
        packet.cells[1].voltage,
        packet.cells[2].voltage,
        packet.cells[3].voltage,

        packet.cells[0].temperature,
        packet.cells[1].temperature,
        packet.cells[2].temperature,
        packet.cells[3].temperature,

        packet.cells[0].soh,
        packet.cells[1].soh,
        packet.cells[2].soh,
        packet.cells[3].soh,

        int(packet.balancing),
        int(packet.fault.active),
        packet.fault.cell,
        packet.fault.type,
        packet.system_state,
    ))

    conn.commit()
    conn.close()


def get_recent_telemetry(limit=50):
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT *
        FROM telemetry
        ORDER BY id DESC
        LIMIT ?
    """, (limit,))

    rows = cursor.fetchall()
    conn.close()

    return [dict(row) for row in rows]