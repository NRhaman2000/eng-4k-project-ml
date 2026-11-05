"""CSV export of stored telemetry and events, streamed straight from SQLite.

- Rows are in chronological order (oldest first).
- Units are in the column names: _V volts, _A amps, _C degrees C, _pct percent, _ms ms.
- Empty cell = not reported (NULL). Nothing is filled in.
- Booleans are 1/0.
- Every row has transport (MOCK = in-process simulator, SERIAL = serial port) and
  data_origin (SYNTHETIC, MEASURED, or UNVERIFIED = serial data whose origin was
  not declared), so a synthetic or unverified value can never pass as a measurement
  once the file leaves the dashboard.
"""
import csv
import io
import json
import sqlite3

from database import DB_PATH

TELEMETRY_COLUMNS = [
    # (csv header, db column)
    ("row_id", "id"), ("timestamp_utc", "timestamp"), ("transport", "transport"), ("data_origin", "data_origin"),
    ("seq", "seq"), ("mcu_uptime_ms", "mcu_ms"), ("scenario", "scenario"), ("system_state", "system_state"),
    ("pack_voltage_V", "pack_voltage"), ("pack_current_A", "pack_current"),
    ("soc_pct", "soc"), ("pack_soh_pct", "pack_soh"),
] + [h for n in range(1, 5) for h in (
    (f"cell{n}_voltage_V", f"cell{n}_voltage"), (f"cell{n}_temp_C", f"cell{n}_temp"),
    (f"cell{n}_soh_pct", f"cell{n}_soh"), (f"cell{n}_balancing", f"cell{n}_balancing"),
    (f"cell{n}_bypassed", f"cell{n}_bypassed"), (f"cell{n}_firmware_fault", f"cell{n}_fault"),
)] + [
    ("balancing", "balancing"), ("firmware_fault_active", "fault_active"),
    ("firmware_fault_cell", "fault_cell"), ("firmware_fault_type", "fault_type"),
    ("dashboard_warnings", "warnings_json"), ("implausible_readings", "invalid_json"),
]

EVENT_COLUMNS = [
    ("event_id", "id"), ("timestamp_utc", "timestamp"), ("transport", "transport"), ("data_origin", "data_origin"),
    ("seq", "seq"), ("kind", "kind"), ("cell", "cell"), ("detail", "detail"), ("message", "message"),
]


def _cell(value):
    return "" if value is None else value


def _warnings(raw):
    """JSON list -> 'CELL_UNDERVOLTAGE@2=2.41;PACK_OVERCURRENT=6.2' (empty if none)."""
    if not raw:
        return ""
    return ";".join(f"{w['code']}{'@' + str(w['cell']) if w.get('cell') else ''}={w['value']}" for w in json.loads(raw))


def _invalid(raw):
    """JSON list -> 'cells.4.temperature=999.0' (raw value that was replaced by empty)."""
    if not raw:
        return ""
    return ";".join(f"{i['field']}={i['value']}" for i in json.loads(raw))


def _rows(table, columns, path, batch=500):
    conn = sqlite3.connect(path or DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(f"SELECT * FROM {table} ORDER BY id ASC")
        while True:
            chunk = cur.fetchmany(batch)
            if not chunk:
                break
            for r in chunk:
                out = []
                for header, col in columns:
                    if col == "warnings_json":
                        out.append(_warnings(r[col]))
                    elif col == "invalid_json":
                        out.append(_invalid(r[col]))
                    else:
                        out.append(_cell(r[col]))
                yield out
    finally:
        conn.close()


def stream_csv(table, columns, path=None):
    """Yield CSV text chunks: header first, then one chunk per 500 rows."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow([h for h, _ in columns])
    n = 0
    for row in _rows(table, columns, path):
        w.writerow(row)
        n += 1
        if n % 500 == 0:
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate()
    yield buf.getvalue()


def telemetry_csv(path=None):
    return stream_csv("telemetry", TELEMETRY_COLUMNS, path)


def events_csv(path=None):
    return stream_csv("events", EVENT_COLUMNS, path)
