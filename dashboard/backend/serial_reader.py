"""SERIAL transport: reads telemetry lines from a serial port (the ESP32-S3, or a test feeder).

Receive-only. This module never writes to the port: the dashboard has no
command path to the MCU (REQ-SE-03).

Two line formats are accepted, both PROVISIONAL until the CE team confirms:
  1. JSON frame v0 (see dashboard/tools/serial_frame.py): {...}*CRC32
  2. Legacy key=value: C1=3.712,...,STATE=NORMAL
Missing fields become None. Bad lines are counted and logged, never fatal.

Data origin: the backend cannot tell what is on the other end of the port, so
each packet gets the operator-configured origin (default UNVERIFIED). A line that
marks itself synthetic ("src":"MOCK" in JSON, SRC=MOCK in key=value) is always
SYNTHETIC. A frame can never promote itself to MEASURED.
"""
import asyncio
import logging
import os
import sys
from datetime import datetime, timezone

import serial
from pydantic import ValidationError

from telemetry import CellTelemetry, FaultTelemetry, TelemetryPacket

# shortcut: frame codec lives with the Phase 0 tools; move to a shared package if a third user appears
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
from serial_frame import MAX_LINE_BYTES, FrameError, decode_frame  # noqa: E402

log = logging.getLogger("bms.serial")


class ParseError(ValueError):
    pass


SYNTHETIC_MARKERS = {"MOCK", "SIM", "SIMULATED", "SYNTHETIC", "TEST"}


def _origin(marker, default):
    if isinstance(marker, str) and marker.strip().upper() in SYNTHETIC_MARKERS:
        return "SYNTHETIC"
    return default


def _now():
    return datetime.now(timezone.utc).isoformat()


def _num(values, key, cast=float):
    raw = values.get(key)
    if raw is None or raw == "" or raw.upper() in ("NA", "N/A", "NAN", "NONE", "NULL"):
        return None
    try:
        return cast(raw)
    except ValueError:
        raise ParseError(f"{key}={raw!r} is not a number")


def parse_serial_line(line, timestamp=None, origin="UNVERIFIED"):
    """Legacy key=value format, e.g. C1=3.712,...,T1=25.1,...,I=1.21,BAL=1,STATE=NORMAL."""
    values = {}
    for part in line.strip().split(","):
        if "=" in part:
            key, value = part.split("=", 1)
            values[key.strip().upper()] = value.strip()
    if "STATE" not in values:
        raise ParseError("key=value line has no STATE")
    cells = [
        CellTelemetry(id=n, voltage=_num(values, f"C{n}"), temperature=_num(values, f"T{n}"),
                      soh=_num(values, f"SOH{n}"))
        for n in range(1, 5)
    ]
    volts = [c.voltage for c in cells]
    pack_v = _num(values, "PV")
    if pack_v is None and None not in volts:
        pack_v = round(sum(volts), 3)
    fault_cell = _num(values, "FAULT_CELL", int)
    fault_type = values.get("FAULT_TYPE")
    bal = values.get("BAL")
    return TelemetryPacket(
        timestamp=timestamp or _now(),
        transport="SERIAL",
        data_origin=_origin(values.get("SRC"), origin),
        pack_voltage=pack_v,
        pack_current=_num(values, "I"),
        cells=cells,
        balancing=None if bal is None else bal == "1",
        fault=FaultTelemetry(
            active=values.get("FAULT") == "1",
            cell=fault_cell if fault_cell else None,
            type=None if fault_type in (None, "", "NONE") else fault_type,
        ),
        system_state=values["STATE"],
    )


def frame_to_packet(obj, timestamp=None, origin="UNVERIFIED"):
    """Map a decoded v0 JSON frame to a TelemetryPacket."""
    pack = obj["pack"] if isinstance(obj["pack"], dict) else {}
    cells = []
    for c in obj["cells"]:
        if not isinstance(c, dict):
            raise ParseError("cell entry is not an object")
        cells.append(CellTelemetry(id=c.get("id"), voltage=c.get("v"), temperature=c.get("t"),
                                   soh=c.get("soh"), balancing=c.get("bal"), bypassed=c.get("bypass"),
                                   fault=c.get("fault")))
    faults = obj.get("faults") or []
    first = faults[0] if faults and isinstance(faults[0], dict) else {}
    cell_faults = [c for c in cells if c.fault]
    fault_type = first.get("type") or (cell_faults[0].fault if cell_faults else None)
    fault_cell = first.get("cell") or (cell_faults[0].id if cell_faults else None)
    bals = [c.balancing for c in cells]
    return TelemetryPacket(
        timestamp=timestamp or _now(),
        transport="SERIAL",
        data_origin=_origin(obj.get("src"), origin),
        seq=obj["seq"],
        mcu_ms=obj["mcu_ms"],
        pack_voltage=pack.get("v"),
        pack_current=pack.get("i"),
        soc=pack.get("soc"),
        pack_soh=pack.get("soh"),
        cells=cells,
        balancing=None if all(b is None for b in bals) else any(bals),
        fault=FaultTelemetry(active=fault_type is not None, cell=fault_cell, type=fault_type),
        system_state=obj["state"],
    )


def parse_line(line, timestamp=None, origin="UNVERIFIED"):
    """Parse one raw serial line (bytes or str) into a TelemetryPacket or raise ParseError."""
    if isinstance(line, str):
        line = line.encode()
    stripped = line.strip()
    if not stripped:
        raise ParseError("empty line")
    try:
        if stripped.startswith(b"{"):
            return frame_to_packet(decode_frame(stripped), timestamp, origin)
        return parse_serial_line(stripped.decode("ascii"), timestamp, origin)
    except FrameError as e:
        raise ParseError(f"frame {e}")
    except ValidationError as e:
        raise ParseError(f"invalid values: {e.errors()[0]['loc']} {e.errors()[0]['msg']}")
    except (UnicodeDecodeError, TypeError, KeyError) as e:
        raise ParseError(f"{type(e).__name__}: {e}")


class SerialSource:
    """Yields packets from a serial port; reconnects with backoff when the port drops."""

    def __init__(self, port, baud=115200, opener=None, retry_s=1.0, max_retry_s=5.0, origin="UNVERIFIED"):
        self.port, self.baud, self.origin = port, baud, origin
        self.opener = opener or (lambda: serial.Serial(port, baudrate=baud, timeout=0.2))
        self.retry_s, self.max_retry_s = retry_s, max_retry_s

    async def packets(self, status):
        status.port = self.port
        delay = self.retry_s
        first = True
        while True:
            try:
                ser = await asyncio.to_thread(self.opener)
            except (serial.SerialException, OSError) as e:
                status.connected = False
                status.last_error = f"open failed: {e}"
                await asyncio.sleep(delay)
                delay = min(delay * 2, self.max_retry_s)
                continue
            if not first:
                status.reconnects += 1
            first = False
            status.connected = True
            status.last_error = None
            delay = self.retry_s
            buf = b""
            try:
                while True:
                    data = await asyncio.to_thread(ser.read, max(1, getattr(ser, "in_waiting", 0) or 0))
                    if not data:
                        continue
                    buf += data
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        try:
                            yield parse_line(line, origin=self.origin)
                        except ParseError as e:
                            status.packets_rejected += 1
                            status.last_error = str(e)
                            log.warning("rejected serial line: %s", e)
                    if len(buf) > MAX_LINE_BYTES:
                        status.packets_rejected += 1
                        status.last_error = "line too long, discarded"
                        buf = b""
            except (serial.SerialException, OSError) as e:
                status.connected = False
                status.last_error = f"disconnected: {e}"
                log.warning("serial port lost: %s", e)
                try:
                    ser.close()
                except Exception:
                    pass
                await asyncio.sleep(delay)
