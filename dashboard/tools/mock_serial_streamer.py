"""Mock 4S telemetry streamer: writes provisional v0 JSON frames to a serial port.

MOCK DATA ONLY. Every value is synthetic and every frame carries "src":"MOCK".
It does not model or drive any real BMS hardware.

Usage:
  python mock_serial_streamer.py --port /tmp/ttyBMS_TX --duration 300
Optional fault injection (to prove the receiver detects problems):
  --corrupt-every N   flip one byte after the CRC is computed, every Nth frame
  --drop-every N      skip sending every Nth frame (sequence number still advances)
  --garbage-every N   send a non-JSON line instead of every Nth frame
"""
import argparse
import json
import math
import random
import sys
import time

import serial

from serial_frame import SCHEMA_VERSION, encode_frame


def make_payload(seq, mcu_ms, rng):
    t = mcu_ms / 1000
    cells = []
    for i in range(4):
        cells.append({
            "id": i + 1,
            "v": round(3.70 + 0.03 * math.sin(t / 30 + i) + rng.uniform(-0.002, 0.002), 4),
            "t": round(25.0 + 0.5 * i + rng.uniform(-0.1, 0.1), 2),
            "soh": None,       # not available until TinyML runs on the MCU
            "bal": False,
            "bypass": False,
            "fault": None,
        })
    return {
        "v": SCHEMA_VERSION,
        "seq": seq,
        "mcu_ms": mcu_ms,
        "src": "MOCK",
        "state": "NORMAL",
        "pack": {
            "v": round(sum(c["v"] for c in cells), 4),
            "i": round(1.2 + rng.uniform(-0.05, 0.05), 3),
            "soc": None,
            "soh": None,
        },
        "cells": cells,
        "faults": [],
    }


def stream(port, baud, interval, duration, seed=0, corrupt_every=0, drop_every=0, garbage_every=0):
    rng = random.Random(seed)
    ser = serial.Serial(port, baudrate=baud, bytesize=8, parity="N", stopbits=1)
    sent = dropped = corrupted = garbage = 0
    bytes_sent = 0
    sizes = []
    lateness = []
    start = time.monotonic()
    seq = 0
    try:
        while True:
            if seq * interval >= duration:  # compare offsets, not start+offset, to avoid float rounding
                break
            deadline = start + seq * interval  # absolute schedule, no cumulative drift
            delay = deadline - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            lateness.append(time.monotonic() - deadline)
            frame = encode_frame(make_payload(seq, int((time.monotonic() - start) * 1000), rng))
            n = seq + 1
            if drop_every and n % drop_every == 0:
                dropped += 1
            else:
                if garbage_every and n % garbage_every == 0:
                    frame = b"not a json frame\n"
                    garbage += 1
                elif corrupt_every and n % corrupt_every == 0:
                    b = bytearray(frame)
                    b[10] ^= 0x01  # inside the JSON body, so the CRC must catch it
                    frame = bytes(b)
                    corrupted += 1
                ser.write(frame)
                ser.flush()
                sent += 1
                bytes_sent += len(frame)
                sizes.append(len(frame))
            seq += 1
    finally:
        ser.close()
    elapsed = time.monotonic() - start
    return {
        "role": "streamer",
        "port": port,
        "baud": baud,
        "interval_s": interval,
        "duration_s": round(elapsed, 3),
        "frames_scheduled": seq,
        "frames_written": sent,
        "frames_intentionally_dropped": dropped,
        "frames_intentionally_corrupted": corrupted,
        "garbage_lines_injected": garbage,
        "bytes_written": bytes_sent,
        "frame_bytes_min": min(sizes) if sizes else None,
        "frame_bytes_max": max(sizes) if sizes else None,
        "frame_bytes_mean": round(bytes_sent / sent, 1) if sent else None,
        # 8N1 = 10 bits on the wire per byte
        "link_utilization_pct": round(100 * bytes_sent * 10 / (baud * elapsed), 2) if elapsed else None,
        "send_lateness_ms_max": round(1000 * max(lateness), 3) if lateness else None,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--port", required=True)
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--interval", type=float, default=0.25)
    p.add_argument("--duration", type=float, default=300)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--corrupt-every", type=int, default=0)
    p.add_argument("--drop-every", type=int, default=0)
    p.add_argument("--garbage-every", type=int, default=0)
    p.add_argument("--stats-out")
    a = p.parse_args()
    stats = stream(a.port, a.baud, a.interval, a.duration, a.seed, a.corrupt_every, a.drop_every, a.garbage_every)
    out = json.dumps(stats, indent=2)
    if a.stats_out:
        with open(a.stats_out, "w") as f:
            f.write(out + "\n")
    print(out, file=sys.stderr)


if __name__ == "__main__":
    main()
