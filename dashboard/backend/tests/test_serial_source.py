import asyncio
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time

import pytest
import serial

from mock_serial_streamer import make_payload
from serial_frame import encode_frame
from serial_reader import SerialSource
from telemetry import LinkStatus


def frame(n):
    return encode_frame(make_payload(n, n * 250, random.Random(n)))


class FakeSerial:
    """Hands out chunks, then raises like a pulled USB cable."""
    def __init__(self, chunks, then_fail=True):
        self.chunks, self.then_fail = list(chunks), then_fail
        self.in_waiting = 0
        self.closed = False

    def read(self, n):
        if self.chunks:
            return self.chunks.pop(0)
        if self.then_fail:
            raise serial.SerialException("device disconnected")
        time.sleep(0.01)
        return b""

    def write(self, *_):
        raise AssertionError("dashboard must never write to the MCU")

    def close(self):
        self.closed = True


def collect(source, n, timeout=3.0):
    status = LinkStatus(transport="SERIAL", data_origin="UNVERIFIED")
    out = []

    async def run():
        async for p in source.packets(status):
            out.append(p)
            if len(out) == n:
                return
    asyncio.run(asyncio.wait_for(run(), timeout))
    return out, status


def test_reads_frames_split_across_chunks_and_rejects_bad_lines():
    data = frame(0) + b"junk line\n" + frame(1) + b"C1=3.7,STATE=NORMAL\n"
    chunks = [data[i:i + 13] for i in range(0, len(data), 13)]
    pkts, st = collect(SerialSource("fake", opener=lambda: FakeSerial(chunks, then_fail=False)), 3)
    assert [p.seq for p in pkts] == [0, 1, None]  # last one is the legacy key=value line
    assert st.packets_rejected == 1 and st.connected


def test_reconnects_after_disconnect():
    ports = [FakeSerial([frame(0), frame(1)]), FakeSerial([frame(2), frame(3)])]
    opened = []

    def opener():
        if not ports:
            raise serial.SerialException("no device")
        opened.append(ports.pop(0))
        return opened[-1]

    pkts, st = collect(SerialSource("fake", opener=opener, retry_s=0.01), 4)
    assert [p.seq for p in pkts] == [0, 1, 2, 3]
    assert st.reconnects == 1 and opened[0].closed


def test_source_applies_configured_origin():
    p = make_payload(0, 0, random.Random(0)); del p["src"]
    src = SerialSource("fake", origin="MEASURED",
                       opener=lambda: FakeSerial([encode_frame(p), frame(1)], then_fail=False))
    pkts, _ = collect(src, 2)
    assert [x.data_origin for x in pkts] == ["MEASURED", "SYNTHETIC"]  # frame(1) is marked MOCK


def test_retries_until_port_appears():
    attempts = {"n": 0}

    def opener():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise serial.SerialException("could not open port")
        return FakeSerial([frame(9)], then_fail=False)

    pkts, st = collect(SerialSource("fake", opener=opener, retry_s=0.01), 1)
    assert pkts[0].seq == 9 and attempts["n"] == 3 and st.reconnects == 0 and st.last_error is None


def test_disconnect_sets_status():
    status = LinkStatus(transport="SERIAL", data_origin="UNVERIFIED")
    src = SerialSource("fake", opener=lambda: FakeSerial([frame(0)]), retry_s=5)

    async def run():
        agen = src.packets(status)
        await agen.__anext__()
        try:
            await asyncio.wait_for(agen.__anext__(), 0.3)  # hits the disconnect, then sleeps
        except asyncio.TimeoutError:
            pass
    asyncio.run(run())
    assert status.connected is False and "disconnected" in status.last_error


def test_runaway_line_is_discarded():
    chunks = [b"x" * 5000, frame(4)]
    pkts, st = collect(SerialSource("fake", opener=lambda: FakeSerial(chunks, then_fail=False)), 1)
    assert pkts[0].seq is not None and st.packets_rejected >= 1


@pytest.mark.skipif(not shutil.which("socat"), reason="socat not installed")
def test_real_pty_with_phase0_streamer():
    work = tempfile.mkdtemp()
    tx, rx = os.path.join(work, "tx"), os.path.join(work, "rx")
    socat = subprocess.Popen(["socat", f"pty,raw,echo=0,link={tx}", f"pty,raw,echo=0,link={rx}"],
                             stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            if os.path.exists(tx) and os.path.exists(rx):
                break
            time.sleep(0.1)
        tools = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "tools")
        streamer = subprocess.Popen([sys.executable, os.path.join(tools, "mock_serial_streamer.py"),
                                     "--port", tx, "--duration", "3", "--interval", "0.1"],
                                    stderr=subprocess.DEVNULL)
        pkts, st = collect(SerialSource(rx, baud=115200), 10, timeout=5)
        streamer.wait(timeout=10)
    finally:
        socat.terminate()
    seqs = [p.seq for p in pkts]
    assert seqs == list(range(seqs[0], seqs[0] + 10)) and st.packets_rejected == 0
    # synthetic frames over a real serial link are labelled SERIAL + SYNTHETIC, never as hardware data
    assert all((p.transport, p.data_origin) == ("SERIAL", "SYNTHETIC") for p in pkts)
