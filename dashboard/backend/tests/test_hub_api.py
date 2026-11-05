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


class QueueSource:
    """Test source: the test decides exactly when a packet arrives."""
    def __init__(self):
        self.q = queue.Queue()

    async def packets(self, status):
        status.connected = True
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


def wait_for(cond, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return
        time.sleep(0.01)
    raise AssertionError("condition not met in time")


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "t.db")
    database.init_db(path)
    return path


@pytest.fixture
def api(tmp_path):
    src = QueueSource()
    app = create_app(Config(db_path=str(tmp_path / "api.db")), source=src)
    with TestClient(app) as client:
        yield client, src, app.state.hub, str(tmp_path / "api.db")


# --- hub ---------------------------------------------------------------------

def test_publish_sends_identical_packet_to_all_clients_and_saves_once(db):
    hub = TelemetryHub(source=None, source_name="MOCK", db_path=db)
    a, b, c = FakeWS(), FakeWS(), FakeWS()
    hub.clients |= {a, b, c}
    asyncio.run(hub.publish(packet_at("demo", 7)))
    assert a.sent == b.sent == c.sent and len(a.sent) == 1
    assert database.count_rows(db) == 1


def test_broken_client_is_dropped_others_still_served(db):
    hub = TelemetryHub(source=None, source_name="MOCK", db_path=db)
    good, bad = FakeWS(), FakeWS(fail=True)
    hub.clients |= {good, bad}
    asyncio.run(hub.publish(packet_at("demo", 1)))
    asyncio.run(hub.publish(packet_at("demo", 2)))
    assert bad not in hub.clients and len(good.sent) == 2


def test_db_failure_is_counted_and_stream_continues(db, monkeypatch):
    def boom(*a, **k):
        raise sqlite3.OperationalError("disk full")
    monkeypatch.setattr("hub.save_telemetry", boom)
    hub = TelemetryHub(source=None, source_name="MOCK", db_path=db)
    ws = FakeWS()
    hub.clients.add(ws)
    asyncio.run(hub.publish(packet_at("demo", 1)))
    assert len(ws.sent) == 1 and hub.status.db_write_errors == 1
    assert "database write failed" in hub.status.last_error


# --- API ---------------------------------------------------------------------

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
            ma, mb = a.receive_json(), b.receive_json()
            assert ma == mb and ma["seq"] == tick
    assert database.count_rows(path) == 3  # one row per packet, not per client


def test_new_client_gets_latest_immediately(api):
    client, src, hub, _ = api
    src.q.put(packet_at("demo", 3))
    wait_for(lambda: hub.published == 1)
    with client.websocket_connect("/ws") as ws:
        assert ws.receive_json()["seq"] == 3


def test_status_and_history(api):
    client, src, hub, _ = api
    src.q.put(packet_at("undervoltage", 70))  # ticks 62-101 are the isolated phase
    wait_for(lambda: hub.published == 1)
    st = client.get("/api/status").json()
    assert st["source"] == "MOCK" and st["connected"] and st["packets_ok"] == 1
    row = client.get("/api/history?limit=5").json()[0]
    assert row["source"] == "MOCK" and row["system_state"] == "ISOLATED"
    assert row["fault_cell"] == 2 and isinstance(row["fault_cell"], int)
    assert row["cell2_bypassed"] == 1 and row["soc"] is None
    assert isinstance(row["cell1_voltage"], float)
    assert client.get("/api/history?limit=0").status_code == 422


def test_mock_source_end_to_end(tmp_path):
    app = create_app(Config(db_path=str(tmp_path / "m.db"), mock_interval_s=0.01))
    hub = app.state.hub
    with TestClient(app) as client, client.websocket_connect("/ws") as a, client.websocket_connect("/ws") as b:
        got_a = [a.receive_json() for _ in range(15)]
        got_b = [b.receive_json() for _ in range(15)]
    assert all(m["source"] == "MOCK" for m in got_a)
    common = {m["seq"] for m in got_a} & {m["seq"] for m in got_b}
    assert len(common) >= 10
    by_seq_a = {m["seq"]: m for m in got_a}
    assert all(by_seq_a[m["seq"]] == m for m in got_b if m["seq"] in common)
    assert database.count_rows(str(tmp_path / "m.db")) == hub.published


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

def test_old_database_is_kept_as_legacy(tmp_path):
    path = str(tmp_path / "old.db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE telemetry (id INTEGER PRIMARY KEY, timestamp TEXT NOT NULL, pack_voltage REAL NOT NULL)")
    conn.execute("INSERT INTO telemetry (timestamp, pack_voltage) VALUES ('t', 14.8)")
    conn.commit(); conn.close()
    database.init_db(path)
    database.init_db(path)  # second start must not rename again
    conn = sqlite3.connect(path)
    assert conn.execute("SELECT COUNT(*) FROM telemetry_legacy").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM telemetry").fetchone()[0] == 0
    conn.close()
    database.save_telemetry(packet_at("demo", 0), path)  # nullable schema accepts the new packet
    assert database.count_rows(path) == 1
