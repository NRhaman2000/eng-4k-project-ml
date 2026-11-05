"""Provisional telemetry contract (frame schema v0), as data.

PROVISIONAL: every field here needs confirmation from the CE/firmware team
(see dashboard/docs/TELEMETRY_CONTRACT.md, which embeds the table generated
from this file).

Levels:
  required  - the dashboard rejects a frame without it
  expected  - firmware should send it; if absent the dashboard shows N/A
  optional  - may be omitted
null is allowed for every measurement ("not available"); it is never invalid.
"""
import os
import sys

from serial_frame import SCHEMA_VERSION, STATES

# shortcut: ranges are borrowed from the backend so there is one copy; move both to a shared package if this grows
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))
from limits import CELL_PLAUSIBLE, PACK_PLAUSIBLE  # noqa: E402

N_CELLS = 4

# (path, level, type, unit, range or allowed values, meaning)
FIELDS = [
    ("v", "required", "int", "", (SCHEMA_VERSION, SCHEMA_VERSION), "schema version"),
    ("seq", "required", "int", "", (0, None), "frame counter, +1 per frame (detects loss)"),
    ("mcu_ms", "required", "int", "ms", (0, None), "MCU uptime when the frame was built"),
    ("state", "required", "enum", "", sorted(STATES), "firmware safety state"),
    ("src", "optional", "str", "", None, "MOCK, SIM, SIMULATED, SYNTHETIC or TEST marks synthetic frames; omit on real hardware"),
    ("pack", "required", "object", "", None, "pack measurements"),
    ("pack.v", "expected", "number", "V", PACK_PLAUSIBLE["pack_voltage"], "pack (string) voltage"),
    ("pack.i", "expected", "number", "A", PACK_PLAUSIBLE["pack_current"], "pack current (sign convention TBD)"),
    ("pack.soc", "optional", "number", "%", PACK_PLAUSIBLE["soc"], "state of charge estimate"),
    ("pack.soh", "optional", "number", "%", PACK_PLAUSIBLE["pack_soh"], "pack state of health estimate"),
    ("cells", "required", "array[4]", "", None, f"exactly {N_CELLS} cell objects, ids 1-{N_CELLS}"),
    ("cells[].id", "required", "int", "", (1, N_CELLS), "cell number"),
    ("cells[].v", "expected", "number", "V", CELL_PLAUSIBLE["voltage"], "cell voltage"),
    ("cells[].t", "expected", "number", "°C", CELL_PLAUSIBLE["temperature"], "cell temperature"),
    ("cells[].soh", "optional", "number", "%", CELL_PLAUSIBLE["soh"], "TinyML SoH estimate"),
    ("cells[].bal", "expected", "bool", "", None, "cell's balancer active"),
    ("cells[].bypass", "expected", "bool", "", None, "cell bypassed / isolated"),
    ("cells[].fault", "expected", "str", "", None, "firmware fault on this cell, null if none"),
    ("faults", "optional", "faults", "", None, "active faults: [{\"type\": str, \"cell\": 1-4 or null}]"),
]
KNOWN_TOP = {p for p, *_ in FIELDS if "." not in p and "[" not in p}
KNOWN_PACK = {p.split(".", 1)[1] for p, *_ in FIELDS if p.startswith("pack.")}
KNOWN_CELL = {p.split(".", 1)[1] for p, *_ in FIELDS if p.startswith("cells[].")}


def _type_ok(kind, value):
    if kind == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if kind == "bool":
        return isinstance(value, bool)
    if kind in ("str", "enum"):
        return isinstance(value, str)
    if kind == "object":
        return isinstance(value, dict)
    if kind.startswith("array") or kind == "faults":
        return isinstance(value, list)
    return True


def _judge(kind, rng, value):
    """'null' | 'invalid: why' | 'present'."""
    if value is None:
        return "null"
    if not _type_ok(kind, value):
        return f"invalid: expected {kind}, got {type(value).__name__}"
    if kind == "enum" and value not in rng:
        return f"invalid: {value!r} not one of {', '.join(rng)}"
    if kind in ("int", "number") and rng:
        lo, hi = rng
        if value != value or (lo is not None and value < lo) or (hi is not None and value > hi):
            return f"invalid: {value!r} outside [{lo}, {'∞' if hi is None else hi}]"
    if kind == "array[4]" and len(value) != N_CELLS:
        return f"invalid: {len(value)} entries, expected {N_CELLS}"
    if kind == "faults":  # the dashboard silently ignores entries that are not {"type": str, "cell": int|null}
        for e in value:
            if not (isinstance(e, dict) and isinstance(e.get("type"), str)
                    and (e.get("cell") is None or (isinstance(e["cell"], int) and 1 <= e["cell"] <= N_CELLS))):
                return f"invalid: entry {e!r} is not {{\"type\": str, \"cell\": 1-{N_CELLS} or null}}"
    return "present"


def check_frame(obj):
    """Per-field status for one decoded JSON object.

    Returns {"fields": {path: [status, ...]}, "unexpected": [path, ...]}. Cell fields get one
    status per cell. A status is "present", "null", "missing" or "invalid: <why>".
    """
    fields, unexpected = {}, []
    pack = obj.get("pack") if isinstance(obj.get("pack"), dict) else {}
    cells = obj.get("cells") if isinstance(obj.get("cells"), list) else []
    for path, _level, kind, _unit, rng, _ in FIELDS:
        if path.startswith("cells[]."):
            key = path.split(".", 1)[1]
            fields[path] = [("missing" if key not in c else _judge(kind, rng, c[key])) if isinstance(c, dict)
                            else "invalid: cell is not an object" for c in cells] or ["missing"]
        elif path.startswith("pack."):
            key = path.split(".", 1)[1]
            fields[path] = ["missing" if key not in pack else _judge(kind, rng, pack[key])]
        else:
            fields[path] = ["missing" if path not in obj else _judge(kind, rng, obj[path])]
    unexpected += sorted(k for k in obj if k not in KNOWN_TOP)
    unexpected += sorted(f"pack.{k}" for k in pack if k not in KNOWN_PACK)
    unexpected += sorted({f"cells[].{k}" for c in cells if isinstance(c, dict) for k in c if k not in KNOWN_CELL})
    return {"fields": fields, "unexpected": unexpected}


def markdown_table():
    rows = ["| Field | Level | Type | Unit | Range / values | Meaning |", "| --- | --- | --- | --- | --- | --- |"]
    for path, level, kind, unit, rng, meaning in FIELDS:
        if isinstance(rng, list):
            r = ", ".join(rng)
        elif rng:
            r = f"{rng[0]} to {'∞' if rng[1] is None else rng[1]}"
        else:
            r = ""
        rows.append(f"| `{path}` | {level} | {kind} | {unit} | {r} | {meaning} |")
    return "\n".join(rows)


if __name__ == "__main__":
    print(markdown_table())
