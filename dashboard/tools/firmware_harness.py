"""Receive-only firmware integration harness.

Reads telemetry lines from a serial port (the STM32, or a test feeder) or from
a capture file, and reports how well they match the provisional contract
(contract.py) and whether the dashboard would accept them. It NEVER writes to
the port: no commands of any kind reach the MCU.

  python firmware_harness.py --port /dev/cu.usbmodem1103 --duration 60
  python firmware_harness.py --file capture.txt --json-out report.json

Capture a file for offline checks with e.g.:  cat /dev/cu.usbmodem1103 > capture.txt
Exit code: 0 COMPATIBLE, 1 COMPATIBLE_WITH_WARNINGS, 2 INCOMPATIBLE or NO_FRAMES.
"""
import argparse
import json
import os
import sys
import time
import zlib
from collections import Counter

from contract import FIELDS, check_frame

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))
from serial_reader import SYNTHETIC_MARKERS, ParseError, parse_line  # noqa: E402

EXPECTED_HZ = 4.0  # one frame every 250 ms (REQ-INT-01)


class Harness:
    def __init__(self):
        self.lines = self.frame_like = self.accepted = self.legacy_kv = self.synthetic = 0
        self.rejected = Counter()
        self.crc = Counter()
        self.non_frame, self.reject_samples = [], []
        self.fields = {p: Counter() for p, *_ in FIELDS}
        self.invalid_examples = {p: [] for p, *_ in FIELDS}
        self.unexpected = Counter()
        self.seqs, self.times, self.mcu_ms = [], [], []
        self.live = False  # host arrival times are only meaningful on a live port

    def feed(self, raw, now=None):
        now = time.monotonic() if now is None else now
        line = raw.rstrip(b"\r\n")
        if not line.strip():
            return
        self.lines += 1
        if not line.lstrip().startswith(b"{"):
            try:  # the dashboard still accepts the legacy key=value format
                parse_line(line)
                self.legacy_kv += 1
                self._accepted(None, now, None)
            except ParseError:
                if len(self.non_frame) < 5:
                    self.non_frame.append(line[:120].decode("utf-8", "replace"))
            return
        self.frame_like += 1
        body, sep, crc = line.rpartition(b"*")
        if not sep:
            self.crc["missing"] += 1
            body = line
        elif len(crc) != 8 or any(ch not in b"0123456789abcdefABCDEF" for ch in crc):
            self.crc["malformed"] += 1
        else:
            self.crc["ok" if zlib.crc32(body) == int(crc, 16) else "mismatch"] += 1
        try:
            obj = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            obj = None
        if isinstance(obj, dict):
            r = check_frame(obj)
            for path, statuses in r["fields"].items():
                for s in statuses:
                    self.fields[path]["invalid" if s.startswith("invalid") else s] += 1
                    if s.startswith("invalid") and len(self.invalid_examples[path]) < 3:
                        self.invalid_examples[path].append(s[len("invalid: "):])
            self.unexpected.update(r["unexpected"])
            if isinstance(obj.get("src"), str) and obj["src"].strip().upper() in SYNTHETIC_MARKERS:
                self.synthetic += 1
        try:
            pkt = parse_line(line)
            self._accepted(pkt.seq, now, pkt.mcu_ms)
        except ParseError as e:
            reason = str(e).split(":")[0] if str(e).startswith("frame ") else str(e)
            self.rejected[reason[:80]] += 1
            if len(self.reject_samples) < 5:
                self.reject_samples.append({"reason": str(e)[:160], "line": line[:160].decode("utf-8", "replace")})

    def _accepted(self, seq, now, mcu_ms):
        self.accepted += 1
        self.times.append(now)
        if seq is not None:
            self.seqs.append(seq)
        if mcu_ms is not None:
            self.mcu_ms.append(mcu_ms)

    def report(self):
        fields, reasons, warnings = {}, [], []
        for path, level, kind, *_ in FIELDS:
            c = self.fields[path]
            total = sum(c.values())
            if not total:
                verdict = "NOT_CHECKED"
            elif c["invalid"]:
                verdict = "INVALID"
            elif c["missing"] == total:
                verdict = "MISSING"
            elif c["missing"]:
                verdict = "SOMETIMES_MISSING"
            elif c["null"] == total:
                verdict = "ALWAYS_NULL"
            else:
                verdict = "OK"
            fields[path] = {"level": level, "present": c["present"], "null": c["null"], "missing": c["missing"],
                            "invalid": c["invalid"], "invalid_examples": self.invalid_examples[path], "verdict": verdict}
            # null is a normal value for text fields (fault = none); for measurements it means "not reported"
            problem = verdict in ("INVALID", "MISSING", "SOMETIMES_MISSING") or (
                verdict == "ALWAYS_NULL" and kind in ("number", "bool", "int"))
            if level == "required" and problem and verdict != "ALWAYS_NULL":
                reasons.append(f"required field {path}: {verdict}")
            elif level == "required" and verdict == "ALWAYS_NULL":
                reasons.append(f"required field {path} is always null")
            elif level == "expected" and problem:
                warnings.append(f"expected field {path}: {verdict} (dashboard shows N/A)")
            elif level == "optional" and verdict == "INVALID":
                warnings.append(f"optional field {path}: INVALID")
        gaps = sum(b - a - 1 for a, b in zip(self.seqs, self.seqs[1:]) if b > a + 1)
        backwards = sum(1 for a, b in zip(self.seqs, self.seqs[1:]) if b <= a)
        span = self.times[-1] - self.times[0] if self.live and len(self.times) > 1 else 0.0
        host_rate = (len(self.times) - 1) / span if span else None
        steps = [b - a for a, b in zip(self.mcu_ms, self.mcu_ms[1:]) if b > a]
        mcu_interval = sum(steps) / len(steps) if steps else None
        if self.rejected:
            reasons.append(f"{sum(self.rejected.values())} frame(s) rejected by the dashboard: "
                           + ", ".join(f"{k} x{v}" for k, v in self.rejected.most_common(3)))
        if self.unexpected:
            warnings.append("fields not in the contract (ignored by the dashboard): " + ", ".join(sorted(self.unexpected)))
        if self.non_frame:
            warnings.append(f"{self.lines - self.frame_like - self.legacy_kv} non-frame line(s), e.g. {self.non_frame[0]!r}")
        if self.legacy_kv:
            warnings.append(f"{self.legacy_kv} legacy key=value line(s): accepted, but outside the JSON v0 contract")
        if gaps or backwards:
            warnings.append(f"sequence: {gaps} missing frame(s), {backwards} repeat/backward step(s)")
        if mcu_interval and len(steps) >= 10 and abs(mcu_interval - 1000 / EXPECTED_HZ) > 0.10 * 1000 / EXPECTED_HZ:
            warnings.append(f"mean frame interval {mcu_interval:.0f} ms by mcu_ms, expected {1000 / EXPECTED_HZ:.0f} ms")
        if self.synthetic:
            warnings.append(f"{self.synthetic} frame(s) are marked synthetic (src=MOCK/SIM/TEST): not hardware data")
        if self.accepted == 0 and self.frame_like == 0:
            verdict = "NO_FRAMES"
        elif reasons:
            verdict = "INCOMPATIBLE"
        elif warnings:
            verdict = "COMPATIBLE_WITH_WARNINGS"
        else:
            verdict = "COMPATIBLE"
        return {
            "verdict": verdict, "problems": reasons, "warnings": warnings,
            "lines": self.lines, "frame_like_lines": self.frame_like, "accepted_by_dashboard": self.accepted,
            "rejected_by_dashboard": dict(self.rejected), "rejected_samples": self.reject_samples,
            "legacy_kv_lines": self.legacy_kv, "non_frame_samples": self.non_frame,
            "synthetic_frames": self.synthetic, "crc": dict(self.crc),
            "link": {"seq_first": self.seqs[0] if self.seqs else None, "seq_last": self.seqs[-1] if self.seqs else None,
                     "missing_by_seq": gaps, "repeat_or_backward": backwards,
                     "mcu_interval_ms_mean": round(mcu_interval, 1) if mcu_interval else None,
                     "host_span_s": round(span, 3) if span else None,
                     "host_rate_hz": round(host_rate, 3) if host_rate else None},
            "fields": fields, "unexpected_fields": dict(self.unexpected),
        }


def summary_text(r, source):
    out = [f"Firmware compatibility report ({source})", f"VERDICT: {r['verdict']}"]
    out += [f"  PROBLEM: {p}" for p in r["problems"]] + [f"  warning: {w}" for w in r["warnings"]]
    out.append(f"lines {r['lines']}, frame-like {r['frame_like_lines']}, accepted {r['accepted_by_dashboard']}, "
               f"rejected {sum(r['rejected_by_dashboard'].values())}, CRC {r['crc']}")
    lk = r["link"]
    out.append(f"seq {lk['seq_first']}..{lk['seq_last']}, missing {lk['missing_by_seq']}, "
               f"frame interval {lk['mcu_interval_ms_mean']} ms (mcu_ms), host rate {lk['host_rate_hz']} Hz")
    out.append(f"{'field':16} {'level':9} {'present':>7} {'null':>5} {'missing':>7} {'invalid':>7}  verdict")
    for path, f in r["fields"].items():
        out.append(f"{path:16} {f['level']:9} {f['present']:>7} {f['null']:>5} {f['missing']:>7} {f['invalid']:>7}  {f['verdict']}"
                   + (f"  e.g. {f['invalid_examples'][0]}" if f["invalid_examples"] else ""))
    return "\n".join(out)


def read_serial(port, baud, duration, max_frames, h, opener=None):
    """Receive-only: read() and close() are the only calls made on the port."""
    import serial
    ser = (opener or (lambda: serial.Serial(port, baudrate=baud, timeout=0.2)))()
    h.live = True
    buf, end = b"", time.monotonic() + duration
    try:
        while time.monotonic() < end and (not max_frames or h.lines < max_frames):
            data = ser.read(max(1, getattr(ser, "in_waiting", 0) or 0))
            buf += data
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                h.feed(line)
            if len(buf) > 8192:  # no newline for 8 KB: not line-framed at all
                h.feed(buf[:200]); buf = b""
    finally:
        ser.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--port", help="serial port, e.g. /dev/cu.usbmodem1103 (macOS) or /dev/ttyACM0")
    src.add_argument("--file", help="capture file with one line per frame")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--duration", type=float, default=30.0, help="seconds to listen on --port")
    ap.add_argument("--frames", type=int, default=0, help="stop after this many lines (0 = no limit)")
    ap.add_argument("--json-out")
    a = ap.parse_args()
    h = Harness()
    if a.file:
        with open(a.file, "rb") as f:
            for line in f:
                h.feed(line)
        source = f"file {a.file}"
    else:
        read_serial(a.port, a.baud, a.duration, a.frames, h)
        source = f"port {a.port} @ {a.baud} baud, {a.duration:.0f} s"
    r = h.report()
    r["input"] = source
    print(summary_text(r, source))
    if a.json_out:
        with open(a.json_out, "w") as f:
            json.dump(r, f, indent=2)
            f.write("\n")
    sys.exit({"COMPATIBLE": 0, "COMPATIBLE_WITH_WARNINGS": 1}.get(r["verdict"], 2))


if __name__ == "__main__":
    main()
