"""Provisional UART telemetry frame, schema v0.

PROVISIONAL: not yet confirmed by the CE/firmware team.

One frame per line:   <compact JSON object>*<CRC-32 of the JSON bytes, 8 uppercase hex>\n
Example:              {"v":0,"seq":12,...}*1A2B3C4D\n

CRC-32 is zlib/IEEE (poly 0x04C11DB7, reflected, init and final XOR 0xFFFFFFFF; check value
of b"123456789" is 0xCBF43926). The STM32G4 CRC unit needs reversal and final XOR set to match.
Missing measurements are sent as JSON null, never as invented values.
"""
import json
import zlib

SCHEMA_VERSION = 0
REQUIRED_FIELDS = ("v", "seq", "mcu_ms", "state", "pack", "cells")
STATES = {"NORMAL", "BALANCING", "FAULT_DETECTED", "ISOLATED"}
MAX_LINE_BYTES = 4096  # budget is ~2,880 B/frame at 115,200 baud / 4 Hz


class FrameError(ValueError):
    def __init__(self, kind, detail=""):
        super().__init__(f"{kind}: {detail}" if detail else kind)
        self.kind = kind


def encode_frame(payload):
    body = json.dumps(payload, separators=(",", ":")).encode()
    return body + b"*%08X\n" % zlib.crc32(body)


def decode_frame(line, require_crc=True):
    """Validate one received line and return the payload dict, or raise FrameError."""
    line = line.rstrip(b"\r\n")
    if len(line) > MAX_LINE_BYTES:
        raise FrameError("oversize", f"{len(line)} bytes")
    body, sep, crc = line.rpartition(b"*")
    if not sep:
        if require_crc:
            raise FrameError("no_crc")
        body = line
    else:
        if len(crc) != 8:
            raise FrameError("bad_crc_field", repr(crc[:16]))
        try:
            expected = int(crc, 16)
        except ValueError:
            raise FrameError("bad_crc_field", repr(crc[:16]))
        if zlib.crc32(body) != expected:
            raise FrameError("crc_mismatch")
    try:
        obj = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise FrameError("bad_json", str(e))
    if not isinstance(obj, dict):
        raise FrameError("not_object")
    missing = [k for k in REQUIRED_FIELDS if k not in obj]
    if missing:
        raise FrameError("missing_fields", ",".join(missing))
    if obj["v"] != SCHEMA_VERSION:
        raise FrameError("bad_version", repr(obj["v"]))
    if not isinstance(obj["seq"], int) or obj["seq"] < 0:
        raise FrameError("bad_seq", repr(obj["seq"]))
    if obj["state"] not in STATES:
        raise FrameError("bad_state", repr(obj["state"]))
    if not isinstance(obj["cells"], list) or len(obj["cells"]) != 4:
        raise FrameError("bad_cells")
    return obj
