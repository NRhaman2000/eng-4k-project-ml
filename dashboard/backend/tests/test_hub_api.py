import asyncio
import queue
import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

import database
from config import Config
from hub import TelemetryHub
from serial_reader import SerialSource
from server import create_app, make_source
from simulator import MockSource, packet_at
from telemetry import LinkStatus


class QueueSource:
    """Test source: the test decides exactly when a packet arrives."""
    def __init__(self, connected=True):
        self.q = queue.Queue()
        self.connected = connected

    async def packets(self, status):
        status.connected = self.connected
        while True:
            try:
                yield await asyncio.to_thread(self.q.get, True, 0.05)
            except queue.Empty:
                continue


class FakeWS:
    def __init__(self, fail=False):
        self.sent, self.fail = [], fail

    async def send_json(self, m):
        if self.fail:
            raise RuntimeError("client gone")
        self.sent.append(m)

    def of(self, kind):
        return [m["data"] for m in self.sent if m["type"] == kind]


def wait_for(cond, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return
        time.sleep(0.01)
    raise AssertionError("condition not met in time")


def recv(ws, kind):
    """Next message of a given type; skips status heartbeats and events in between."""
    for _ in range(200):
        m = ws.receive_json()
        assert set(m) == {"type", "data"} and m["type"] in ("telemetry", "status", "event")
        if m["type"] == kind:
            return m["data"]
    raise AssertionError(f"no {kind} message")


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "t.db")
    database.init_db(path)
    return path


@pytest.fixture
def api(tmp_path):
    src = QueueSource()
    path = str(tmp_path / "api.db")
    app = create_app(Config(db_path=path), source=src, heartbeat_s=0.05)
    with TestClient(app) as client:
        yield client, src, app.state.hub, path


# --- hub ---------------------------------------------------------------------

def test_publish_sends_identical_packet_to_all_clients_and_saves_once(db):
    hub = TelemetryHub(source=None, source_name="MOCK", db_path=db)
    a, b, c = FakeWS(), FakeWS(), FakeWS()
    hub.clients |= {a, b, c}
    asyncio.run(hub.publish(packet_at("demo", 7)))
    assert a.sent == b.sent == c.sent
    assert len(a.of("telemetry")) == 1 and a.of("telemetry")[0]["seq"] == 7
    assert database.count_rows(db) == 1


def test_broken_client_is_dropped_others_still_served(db):
    hub = TelemetryHub(source=None, source_name="MOCK", db_path=db)
    good, bad = FakeWS(), FakeWS(fail=True)
    hub.clients |= {good, bad}
    asyncio.run(hub.publish(packet_at("demo", 1)))
    asyncio.run(hub.publish(packet_at("demo", 2)))
    assert bad not in hub.clients and len(good.of("telemetry")) == 2


def test_db_failure_is_counted_and_stream_continues(db, monkeypatch):
    def boom(*a, **k):
        raise sqlite3.OperationalError("disk full")
    monkeypatch.setattr("hub.save_telemetry", boom)
    hub = TelemetryHub(source=None, source_name="MOCK", db_path=db)
    ws = FakeWS()
    hub.clients.add(ws)
    asyncio.run(hub.publish(packet_at("demo", 1)))
    assert len(ws.of("telemetry")) == 1 and hub.status.db_write_errors == 1
    assert "database write failed" in hub.status.last_error


def test_unsafe_reading_is_kept_flagged_and_logged(db):
    hub = TelemetryHub(source=None, source_name="HARDWARE", db_path=db)
    ws = FakeWS()
    hub.clients.add(ws)
    p = packet_at("normal", 0)
    p.cells[1].voltage = 2.41      # real undervoltage: must stay visible
    asyncio.run(hub.publish(p))
    sent = ws.of("telemetry")[0]
    assert sent["cells"][1]["voltage"] == 2.41
    assert [w["code"] for w in sent["warnings"]] == ["CELL_UNDERVOLTAGE"]
    assert sent["fault"]["active"] is False  # a dashboard warning never becomes a firmware fault
    row = database.get_recent_telemetry(1, db)[0]
    assert row["cell2_voltage"] == 2.41 and "CELL_UNDERVOLTAGE" in row["warnings_json"]
    assert any(e["kind"] == "WARNING_RAISED" for e in ws.of("event"))


def test_impossible_reading_is_nulled_but_packet_kept(db):
    hub = TelemetryHub(source=None, source_name="HARDWARE", db_path=db)
    ws = FakeWS()
    hub.clients.add(ws)
    p = packet_at("normal", 0)
    p.cells[3].temperature = 999.0
    asyncio.run(hub.publish(p))
    sent = ws.of("telemetry")[0]
    assert sent["cells"][3]["temperature"] is None and sent["cells"][3]["voltage"] is not None
    assert sent["invalid"] == [{"field": "cells.4.temperature", "value": "999.0",
                                "reason": "outside physically possible range [-55.0, 150.0]"}]
    assert database.count_rows(db) == 1


def test_events_follow_fault_lifecycle(db):
    hub = TelemetryHub(source=None, source_name="MOCK", db_path=db)

    async def run():
        for t in range(0, 125):  # one full 122-tick loop, then back into NORMAL
            await hub.publish(packet_at("undervoltage", t))
    asyncio.run(run())
    kinds = [e["kind"] for e in reversed(database.get_recent_events(500, db))]
    assert kinds[0] == "STATE"
    for k in ("WARNING_RAISED", "FAULT_REPORTED", "CELL_BYPASSED", "FAULT_CLEARED", "CELL_RESTORED"):
        assert k in kinds, k
    assert kinds.index("FAULT_REPORTED") < kinds.index("CELL_BYPASSED") < kinds.index("CELL_RESTORED")
    # one event per change, not per packet
    assert kinds.count("FAULT_REPORTED") == 1 and kinds.count("CELL_BYPASSED") == 1


def test_status_payload_stale_logic():
    hub = TelemetryHub(source=None, source_name="MOCK")
    assert hub.status_payload()["stale"] is True  # nothing received yet
    hub._last_mono = time.monotonic()
    assert hub.status_payload()["stale"] is False
    hub._last_mono = time.monotonic() - 5
    s = hub.status_payload()
    assert s["stale"] is True and s["last_packet_age_s"] >= 5


# --- API / WebSocket -------------------------------------------------------------

def test_latest_is_read_only(api):
    client, src, hub, path = api
    assert client.get("/api/latest").status_code == 503
    src.q.put(packet_at("demo", 42))
    wait_for(lambda: hub.published == 1)
    seqs = [client.get("/api/latest").json()["seq"] for _ in range(5)]
    assert seqs == [42] * 5
    assert hub.published == 1 and database.count_rows(path) == 1


def test_two_websocket_clients_get_the_same_stream_no_duplicate_rows(api):
    client, src, hub, path = api
    with client.websocket_connect("/ws") as a, client.websocket_connect("/ws") as b:
        wait_for(lambda: len(hub.clients) == 2)
        for tick in (10, 11, 12):
            src.q.put(packet_at("undervoltage", tick))
            ma, mb = recv(a, "telemetry"), recv(b, "telemetry")
            assert ma == mb and ma["seq"] == tick
    assert database.count_rows(path) == 3  # one row per packet, not per client


def test_ws_sends_status_first_then_latest(api):
    client, src, hub, _ = api
    src.q.put(packet_at("demo", 3))
    wait_for(lambda: hub.published == 1)
    with client.websocket_connect("/ws") as ws:
        first = ws.receive_json()
        assert first["type"] == "status" and first["data"]["source"] == "MOCK"
        assert ws.receive_json() == {"type": "telemetry", "data": hub.latest.model_dump()}


def test_disconnect_reaches_browser_via_status(tmp_path):
    src = QueueSource(connected=False)  # e.g. serial port unplugged
    app = create_app(Config(db_path=str(tmp_path / "d.db"), source="HARDWARE"), source=src, heartbeat_s=0.05)
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        recv(ws, "status")
        st = recv(ws, "status")  # heartbeat, with no telemetry flowing at all
        assert st["source"] == "HARDWARE" and st["connected"] is False and st["stale"] is True


def test_status_events_history_and_legacy_endpoints(api):
    client, src, hub, _ = api
    src.q.put(packet_at("undervoltage", 70))  # ticks 62-101 are the isolated phase
    wait_for(lambda: hub.published == 1)
    st = client.get("/api/status").json()
    assert st["source"] == "MOCK" and st["connected"] and st["packets_ok"] == 1 and st["stale"] is False
    row = client.get("/api/history?limit=5").json()[0]
    assert row["source"] == "MOCK" and row["system_state"] == "ISOLATED"
    assert row["fault_cell"] == 2 and isinstance(row["fault_cell"], int)
    assert row["cell2_bypassed"] == 1 and row["soc"] is None
    ev = client.get("/api/events").json()
    assert {e["kind"] for e in ev} >= {"STATE", "FAULT_REPORTED", "CELL_BYPASSED"}
    assert client.get("/api/legacy").json() == {"total": 0, "rows": []}
    assert client.get("/api/history?limit=0").status_code == 422


def test_mock_source_end_to_end(tmp_path):
    path = str(tmp_path / "m.db")
    app = create_app(Config(db_path=path, mock_interval_s=0.01))
    hub = app.state.hub
    with TestClient(app) as client, client.websocket_connect("/ws") as a, client.websocket_connect("/ws") as b:
        got_a = [recv(a, "telemetry") for _ in range(15)]
        got_b = [recv(b, "telemetry") for _ in range(15)]
    assert all(m["source"] == "MOCK" for m in got_a)
    by_seq_a = {m["seq"]: m for m in got_a}
    common = [m for m in got_b if m["seq"] in by_seq_a]
    assert len(common) >= 10 and all(by_seq_a[m["seq"]] == m for m in common)
    assert database.count_rows(path) == hub.published


# --- config / sources ----------------------------------------------------------

def test_source_selection(monkeypatch):
    assert isinstance(make_source(Config(source="MOCK")), MockSource)
    assert isinstance(make_source(Config(source="HARDWARE", serial_port="/dev/x")), SerialSource)
    monkeypatch.setenv("BMS_SOURCE", "hardware")
    monkeypatch.setenv("BMS_SERIAL_PORT", "/dev/ttyUSB9")
    c = Config.from_env()
    assert c.source == "HARDWARE" and c.serial_port == "/dev/ttyUSB9"
    monkeypatch.setenv("BMS_SOURCE", "wifi")
    with pytest.raises(ValueError):
        Config.from_env()


# --- database migration --------------------------------------------------------

def make_v0_db(path, rows=3):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE telemetry (id INTEGER PRIMARY KEY, timestamp TEXT NOT NULL, pack_voltage REAL NOT NULL)")
    conn.executemany("INSERT INTO telemetry (timestamp, pack_voltage) VALUES (?, ?)",
                     [(f"t{i}", 14.8 + i / 100) for i in range(rows)])
    conn.commit()
    conn.close()


def test_migration_backs_up_first_and_keeps_legacy_rows(tmp_path):
    path = str(tmp_path / "old.db")
    make_v0_db(path, rows=3)
    backup = database.init_db(path)
    assert backup is not None and backup.exists()
    b = sqlite3.connect(backup)
    assert b.execute("SELECT COUNT(*) FROM telemetry").fetchone()[0] == 3  # untouched copy of the original
    b.close()
    assert database.init_db(path) is None  # second start: no new migration, no new backup
    legacy = database.get_legacy_telemetry(10, path)
    assert legacy["total"] == 3 and {r["timestamp"] for r in legacy["rows"]} == {"t0", "t1", "t2"}
    assert database.count_rows(path) == 0
    database.save_telemetry(packet_at("demo", 0), path)
    assert database.count_rows(path) == 1 and database.count_rows(path, "telemetry_legacy") == 3


def test_migration_from_v1_keeps_rows_in_separate_table(tmp_path):
    path = str(tmp_path / "v1.db")
    make_v0_db(path, rows=2)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA user_version = 1")
    conn.commit()
    conn.close()
    database.init_db(path)
    assert database.count_rows(path, "telemetry_legacy_v1") == 2


def test_migration_refuses_when_backup_fails(tmp_path, monkeypatch):
    path = str(tmp_path / "old.db")
    make_v0_db(path, rows=2)

    def fail(_):
        raise OSError("disk full")
    monkeypatch.setattr(database, "backup_db", fail)
    with pytest.raises(database.MigrationError):
        database.init_db(path)
    conn = sqlite3.connect(path)  # original table untouched
    assert conn.execute("SELECT COUNT(*) FROM telemetry").fetchone()[0] == 2
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 0
    conn.close()
