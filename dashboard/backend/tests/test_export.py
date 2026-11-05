import asyncio
import csv
import io
import sqlite3

import pytest
from fastapi.testclient import TestClient

import database
from config import Config
from export import EVENT_COLUMNS, TELEMETRY_COLUMNS
from hub import TelemetryHub
from server import create_app
from simulator import packet_at


def read_csv(text):
    return list(csv.DictReader(io.StringIO(text)))


def fill(path, packets, transport="MOCK"):
    hub = TelemetryHub(source=None, transport=transport, db_path=path)

    async def run():
        for p in packets:
            await hub.publish(p)
    asyncio.run(run())
    return hub


@pytest.fixture
def client_db(tmp_path):
    path = str(tmp_path / "e.db")
    app = create_app(Config(db_path=path), source=_Idle())
    with TestClient(app) as c:
        yield c, path


class _Idle:
    async def packets(self, status):
        await asyncio.Event().wait()
        yield  # pragma: no cover


def test_headers_carry_units_and_origin():
    headers = [h for h, _ in TELEMETRY_COLUMNS]
    for h in ("timestamp_utc", "transport", "data_origin", "pack_voltage_V", "pack_current_A", "soc_pct",
              "pack_soh_pct", "cell1_voltage_V", "cell4_temp_C", "cell2_soh_pct", "cell3_bypassed",
              "firmware_fault_type", "dashboard_warnings", "implausible_readings"):
        assert h in headers
    assert [h for h, _ in EVENT_COLUMNS][:4] == ["event_id", "timestamp_utc", "transport", "data_origin"]


def test_telemetry_csv_matches_database_rows(client_db):
    client, path = client_db
    fill(path, [packet_at("undervoltage", t) for t in range(0, 125)])
    r = client.get("/api/export/telemetry.csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert 'attachment; filename="bms_telemetry_mock_' in r.headers["content-disposition"]
    rows = read_csv(r.text)
    db_rows = list(reversed(database.get_recent_telemetry(10_000, path)))  # oldest first
    assert len(rows) == len(db_rows) == 125
    for out, db in zip(rows, db_rows):
        for header, col in TELEMETRY_COLUMNS:
            if col in (None, "warnings_json", "invalid_json"):
                continue
            expected = "" if db[col] is None else str(db[col])
            assert out[header] == expected, (header, out[header], expected)
    assert all(r["data_origin"] == "SYNTHETIC" and r["transport"] == "MOCK" for r in rows)
    assert [int(r["row_id"]) for r in rows] == sorted(int(r["row_id"]) for r in rows)


def test_nulls_export_as_empty_and_isolation_is_visible(client_db):
    client, path = client_db
    fill(path, [packet_at("undervoltage", 70)])  # isolated phase
    row = read_csv(client.get("/api/export/telemetry.csv").text)[0]
    assert row["soc_pct"] == "" and row["pack_soh_pct"] == ""
    assert row["system_state"] == "ISOLATED" and row["cell2_bypassed"] == "1" and row["cell1_bypassed"] == "0"
    assert row["firmware_fault_type"] == "UNDERVOLTAGE" and row["firmware_fault_cell"] == "2"
    assert "CELL_UNDERVOLTAGE@2=" in row["dashboard_warnings"]


@pytest.mark.parametrize("origin", ["MEASURED", "UNVERIFIED", "SYNTHETIC"])
def test_serial_rows_keep_transport_and_origin_apart(client_db, origin):
    client, path = client_db
    p = packet_at("normal", 0).model_copy(update={"transport": "SERIAL", "data_origin": origin, "scenario": None})
    fill(path, [p], transport="SERIAL")
    row = read_csv(client.get("/api/export/telemetry.csv").text)[0]
    assert (row["transport"], row["data_origin"]) == ("SERIAL", origin)


def test_implausible_values_listed_and_nulls_empty(client_db):
    client, path = client_db
    p = packet_at("normal", 0).model_copy(update={"transport": "SERIAL", "data_origin": "MEASURED", "scenario": None})
    p.cells[3].temperature = 999.0
    p.cells[0].voltage = None
    fill(path, [p], transport="SERIAL")
    row = read_csv(client.get("/api/export/telemetry.csv").text)[0]
    assert row["transport"] == "SERIAL" and row["data_origin"] == "MEASURED"
    assert row["cell4_temp_C"] == "" and row["implausible_readings"] == "cells.4.temperature=999.0"
    assert row["cell1_voltage_V"] == "" and row["scenario"] == ""


def test_events_csv_matches_events_table(client_db):
    client, path = client_db
    fill(path, [packet_at("undervoltage", t) for t in range(0, 125)])
    r = client.get("/api/export/events.csv")
    assert 'filename="bms_events_mock_' in r.headers["content-disposition"]
    rows = read_csv(r.text)
    db = list(reversed(database.get_recent_events(10_000, path)))
    assert len(rows) == len(db) > 0
    assert [x["kind"] for x in rows] == [e["kind"] for e in db]
    kinds = {x["kind"] for x in rows}
    assert {"FAULT_REPORTED", "CELL_BYPASSED", "FAULT_CLEARED", "CELL_RESTORED"} <= kinds
    assert all(x["data_origin"] == "SYNTHETIC" and x["transport"] == "MOCK" for x in rows)


def test_empty_database_exports_header_only(client_db):
    client, _ = client_db
    lines = client.get("/api/export/telemetry.csv").text.strip().splitlines()
    assert lines == [",".join(h for h, _ in TELEMETRY_COLUMNS)]
    assert client.get("/api/export/events.csv").text.strip() == ",".join(h for h, _ in EVENT_COLUMNS)


def test_large_export_streams_in_chunks(tmp_path):
    from export import telemetry_csv
    path = str(tmp_path / "big.db")
    database.init_db(path)
    conn = sqlite3.connect(path)
    cols = ",".join(database.COLUMNS)
    row = database._row(packet_at("normal", 0))
    conn.executemany(f"INSERT INTO telemetry ({cols}) VALUES ({','.join('?' * len(database.COLUMNS))})", [row] * 1203)
    conn.commit(); conn.close()
    chunks = list(telemetry_csv(path))
    assert len(chunks) == 3  # 500 + 500 + 203 (header rides with the first chunk)
    assert sum(c.count("\n") for c in chunks) == 1204


def test_export_does_not_write_anything(client_db):
    client, path = client_db
    fill(path, [packet_at("demo", 0)])
    before = (database.count_rows(path), database.count_rows(path, "events"))
    client.get("/api/export/telemetry.csv"); client.get("/api/export/events.csv")
    assert (database.count_rows(path), database.count_rows(path, "events")) == before


def test_export_in_progress_does_not_block_live_writes(tmp_path):
    """Regression: a streaming export held a read lock and live writes failed with 'database is locked'."""
    import time
    from export import telemetry_csv
    path = str(tmp_path / "live.db")
    database.init_db(path)
    for t in range(1203):  # more than one 500-row chunk, so the export pauses mid-read
        database.save_telemetry(packet_at("normal", t), path)
    gen = telemetry_csv(path)
    first = next(gen)  # export now has an open read in progress
    start = time.monotonic()
    database.save_telemetry(packet_at("normal", 9999), path)  # the ingestion loop writing meanwhile
    assert time.monotonic() - start < 1.0
    rest = "".join(gen)
    assert (first + rest).count("\n") == 1204  # export is a consistent snapshot: header + 1203 rows
    assert database.count_rows(path) == 1204
    conn = sqlite3.connect(path)
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    conn.close()
