"""Receive-only telemetry receiver for the loopback test.

Opens the port read-only in practice: it never calls write(), so there is no
command path back to the MCU (REQ-SE-03). Each line is validated with
serial_frame.decode_frame; failures are counted by kind and ingestion continues.

Usage:
  python loopback_receiver.py --port /tmp/ttyBMS_RX --duration 305
"""
import argparse
import json
import sys
import time
from collections import Counter

import serial

from serial_frame import MAX_LINE_BYTES, FrameError, decode_frame


class ReceiverStats:
    def __init__(self):
        self.frames_ok = 0
        self.lines_total = 0
        self.bytes_received = 0
        self.errors = Counter()
        self.seq_gaps = 0           # frames missing according to sequence numbers
        self.seq_out_of_order = 0   # repeated or backwards sequence numbers
        self.last_seq = None
        self.first_seq = None
        self.arrivals = []

    def process_line(self, line, now):
        self.lines_total += 1
        try:
            obj = decode_frame(line)
        except FrameError as e:
            self.errors[e.kind] += 1
            return None
        seq = obj["seq"]
        if self.last_seq is None:
            self.first_seq = seq
        elif seq > self.last_seq + 1:
            self.seq_gaps += seq - self.last_seq - 1
        elif seq <= self.last_seq:
            self.seq_out_of_order += 1
        self.last_seq = max(seq, self.last_seq) if self.last_seq is not None else seq
        self.frames_ok += 1
        self.arrivals.append(now)
        return obj

    def summary(self):
        gaps = [b - a for a, b in zip(self.arrivals, self.arrivals[1:])]
        return {
            "role": "receiver",
            "lines_received": self.lines_total,
            "bytes_received": self.bytes_received,
            "frames_valid": self.frames_ok,
            "parse_failures": sum(self.errors.values()),
            "parse_failures_by_kind": dict(self.errors),
            "first_seq": self.first_seq,
            "last_seq": self.last_seq,
            "frames_missing_by_seq": self.seq_gaps,
            "frames_out_of_order": self.seq_out_of_order,
            "interarrival_ms_mean": round(1000 * sum(gaps) / len(gaps), 2) if gaps else None,
            "interarrival_ms_min": round(1000 * min(gaps), 2) if gaps else None,
            "interarrival_ms_max": round(1000 * max(gaps), 2) if gaps else None,
        }


def split_lines(buf, data, stats, now):
    """Append data to buf, process complete lines, return the leftover partial line."""
    buf += data
    while True:
        nl = buf.find(b"\n")
        if nl < 0:
            break
        stats.process_line(buf[: nl + 1], now)
        buf = buf[nl + 1 :]
    if len(buf) > MAX_LINE_BYTES:  # no newline in sight: discard and count, keep ingesting
        stats.errors["oversize"] += 1
        stats.lines_total += 1
        buf = b""
    return buf


def receive(port, baud, duration, idle_timeout=3.0):
    stats = ReceiverStats()
    ser = serial.Serial(port, baudrate=baud, bytesize=8, parity="N", stopbits=1, timeout=0.1)
    buf = b""
    start = time.monotonic()
    last_data = None
    try:
        while time.monotonic() - start < duration:
            data = ser.read(ser.in_waiting or 1)
            now = time.monotonic()
            if data:
                stats.bytes_received += len(data)
                last_data = now
                buf = split_lines(buf, data, stats, now)
            elif last_data is not None and now - last_data > idle_timeout:
                break  # streamer finished
    finally:
        ser.close()
    s = stats.summary()
    s["port"] = port
    s["baud"] = baud
    s["listen_duration_s"] = round(time.monotonic() - start, 3)
    s["partial_line_at_end_bytes"] = len(buf)
    return s


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--port", required=True)
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--duration", type=float, default=310)
    p.add_argument("--idle-timeout", type=float, default=3.0)
    p.add_argument("--stats-out")
    a = p.parse_args()
    s = receive(a.port, a.baud, a.duration, a.idle_timeout)
    out = json.dumps(s, indent=2)
    if a.stats_out:
        with open(a.stats_out, "w") as f:
            f.write(out + "\n")
    print(out, file=sys.stderr)


if __name__ == "__main__":
    main()
