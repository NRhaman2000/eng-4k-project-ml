"""End-to-end telemetry measurement: SIMULATED, synthetic frames over a PTY.

serial write (feeder) -> PTY -> backend (SERIAL transport: parse, assess, SQLite, broadcast)
  -> WebSocket -> client receipt.  Latency per frame = receipt time - write time,
matched by seq. All on one host, so both timestamps share one clock.

This is NOT a hardware measurement. A PTY moves bytes instantly. A real UART at
115,200 baud adds about frame_bytes * 10 / 115200 s of wire time per frame (about 41 ms for a
470-byte frame), which is reported separately as a computed estimate. Browser
rendering time is not included.

The run pulls the virtual cable once (kills socat, then recreates the PTY pair) to
measure loss and reconnection.

  python measure_e2e.py --duration 60 --outage-at 20 --outage 5
"""
import argparse
import asyncio
import json
import math
import os
import random
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from datetime import datetime, timezone

import serial
import websockets

from mock_serial_streamer import make_payload
from serial_frame import encode_frame

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.join(HERE, "..", "backend")


def percentile(xs, p):
    """Nearest-rank percentile; None for an empty list."""
    if not xs:
        return None
    s = sorted(xs)
    return s[max(0, math.ceil(p / 100 * len(s)) - 1)]


def start_pty(tx, rx):
    for f in (tx, rx):
        if os.path.lexists(f):
            os.remove(f)
    p = subprocess.Popen(["socat", f"pty,raw,echo=0,link={tx}", f"pty,raw,echo=0,link={rx}"],
                         stderr=subprocess.DEVNULL)
    for _ in range(100):
        if os.path.exists(tx) and os.path.exists(rx):
            return p
        time.sleep(0.05)
    raise RuntimeError("socat did not create the PTY pair")


class Feeder(threading.Thread):
    """Plays the MCU: one synthetic frame per interval; seq advances even while the link is down."""

    def __init__(self, port, interval):
        super().__init__(daemon=True)
        self.port, self.interval = port, interval
        self.sent, self.failed, self.sizes = {}, [], []
        self.stop = threading.Event()

    def run(self):
        ser, seq, start, rng = None, 0, time.monotonic(), random.Random(1)
        while not self.stop.is_set():
            frame = encode_frame(make_payload(seq, int((time.monotonic() - start) * 1000), rng))
            try:
                if ser is None:
                    ser = serial.Serial(self.port, 115200, write_timeout=0.5)
                ser.write(frame)  # no flush(): tcdrain has no timeout and hangs if the PTY vanishes mid-drain
                self.sent[seq] = time.time()
                self.sizes.append(len(frame))
            except (serial.SerialException, OSError):
                self.failed.append(seq)
                if ser is not None:
                    try:
                        ser.close()
                    except Exception:
                        pass
                ser = None
            seq += 1
            self.stop.wait(max(0.0, start + seq * self.interval - time.monotonic()))


async def listen(url, until, recv, dup, status_log):
    while time.monotonic() < until:
        try:
            async with websockets.connect(url) as ws:
                while time.monotonic() < until:
                    try:
                        m = json.loads(await asyncio.wait_for(ws.recv(), 0.5))
                    except asyncio.TimeoutError:
                        continue
                    now = time.time()
                    if m["type"] == "telemetry":
                        seq = m["data"]["seq"]
                        if seq in recv:
                            dup.append(seq)
                        else:
                            recv[seq] = (now, m["data"]["transport"], m["data"]["data_origin"])
                    elif m["type"] == "status":
                        status_log.append((now, m["data"]["connected"]))
        except (OSError, websockets.exceptions.WebSocketException):
            await asyncio.sleep(0.2)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def measure(duration, outage_at, outage_s, interval=0.25):
    work = tempfile.mkdtemp(prefix="bms_e2e_")
    tx, rx, db = os.path.join(work, "tx"), os.path.join(work, "rx"), os.path.join(work, "e2e.db")
    port = free_port()
    socat = start_pty(tx, rx)
    backend = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--port", str(port), "--log-level", "warning"],
        cwd=BACKEND, env={**os.environ, "BMS_TRANSPORT": "SERIAL", "BMS_SERIAL_PORT": rx, "BMS_DB_PATH": db},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    recv, dup, status_log, events = {}, [], [], {}
    feeder = Feeder(tx, interval)
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=0.5)
                break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError("backend did not start")

        async def main():
            t0 = time.monotonic()
            lst = asyncio.create_task(listen(f"ws://127.0.0.1:{port}/ws", t0 + duration + 2, recv, dup, status_log))
            await asyncio.sleep(0.5)
            feeder.start()
            if outage_s > 0:
                await asyncio.sleep(outage_at)
                nonlocal socat
                socat.terminate(); socat.wait()
                events["down"] = time.time()
                await asyncio.sleep(outage_s)
                socat = start_pty(tx, rx)
                events["up"] = time.time()
            await asyncio.sleep(max(0.0, t0 + 0.5 + duration - time.monotonic()))
            feeder.stop.set()
            await lst
        asyncio.run(main())
        status = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=2).read())
        conn = sqlite3.connect(db)
        db_rows, db_distinct = conn.execute("SELECT COUNT(*), COUNT(DISTINCT seq) FROM telemetry").fetchone()
        conn.close()
    finally:
        feeder.stop.set()
        backend.terminate(); backend.wait(timeout=10)
        socat.terminate()

    lat = [(recv[s][0] - t) * 1000 for s, t in feeder.sent.items() if s in recv]
    written = len(feeder.sent)
    received = sum(1 for s in feeder.sent if s in recv)
    result = {
        "measurement": "SIMULATED: synthetic frames over a socat PTY on one host. Not a hardware measurement.",
        "started_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "config": {"duration_s": duration, "interval_s": interval, "outage_at_s": outage_at, "outage_s": outage_s},
        "labels_seen": sorted({f"{v[1]}/{v[2]}" for v in recv.values()}),
        "frames": {"scheduled": written + len(feeder.failed), "written": written,
                   "not_written_link_down": len(feeder.failed), "received": received,
                   "lost_after_write": written - received, "duplicates_at_client": len(dup),
                   "db_rows": db_rows, "db_distinct_seq": db_distinct},
        "delivery_rate_of_written_pct": round(100 * received / written, 2) if written else None,
        "latency_ms": {"n": len(lat), "min": round(min(lat), 2) if lat else None,
                       "p50": round(percentile(lat, 50), 2) if lat else None,
                       "p95": round(percentile(lat, 95), 2) if lat else None,
                       "p99": round(percentile(lat, 99), 2) if lat else None,
                       "max": round(max(lat), 2) if lat else None},
        "uart_wire_time_estimate_ms": round(1000 * (sum(feeder.sizes) / len(feeder.sizes)) * 10 / 115200, 1)
        if feeder.sizes else None,
        "uart_wire_time_note": "COMPUTED, not measured: mean frame bytes x 10 bits / 115,200 baud; add to latency for a real UART",
        "backend_status": {k: status[k] for k in ("packets_ok", "packets_rejected", "reconnects", "db_write_errors",
                                                  "connected", "last_error")},
    }
    if "down" in events:
        down, up = events["down"], events["up"]
        detect = next((t for t, c in status_log if t >= down and c is False), None)
        relink = next((t for t, c in status_log if t >= up and c is True), None)
        first = min((v[0] for v in recv.values() if v[0] >= up), default=None)
        first_back = min((v[0] for v in recv.values() if v[0] >= up), default=None)
        # outage window: cable pulled -> first frame delivered after replug (includes the backend's retry backoff)
        w_start, w_end = down - 0.5, (first_back if first_back else float("inf"))
        lost = sorted(s for s in feeder.sent if s not in recv)
        result["frames"]["lost_seqs"] = lost[:20]
        result["frames"]["lost_in_outage_window"] = sum(1 for s in lost if w_start <= feeder.sent[s] <= w_end)
        clean = [s for s, t in feeder.sent.items() if not (w_start <= t <= w_end)]
        result["delivery_rate_outside_outage_pct"] = (
            round(100 * sum(1 for x in clean if x in recv) / len(clean), 2) if clean else None)
        result["reconnection"] = {
            "outage_s": round(up - down, 2),
            "disconnect_shown_after_s": round(detect - down, 2) if detect else None,
            "link_connected_again_after_s": round(relink - up, 2) if relink else None,
            "first_frame_after_replug_s": round(first - up, 2) if first else None,
            "note": "includes the backend's 1-5 s retry backoff and the 1 s status heartbeat",
        }
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--duration", type=float, default=60)
    ap.add_argument("--outage-at", type=float, default=20, help="seconds after start to pull the virtual cable")
    ap.add_argument("--outage", type=float, default=5, help="seconds the cable stays unplugged (0 = none)")
    ap.add_argument("--interval", type=float, default=0.25)
    ap.add_argument("--json-out")
    a = ap.parse_args()
    r = measure(a.duration, a.outage_at, a.outage, a.interval)
    print(json.dumps(r, indent=2))
    if a.json_out:
        with open(a.json_out, "w") as f:
            json.dump(r, f, indent=2)
            f.write("\n")


if __name__ == "__main__":
    main()
