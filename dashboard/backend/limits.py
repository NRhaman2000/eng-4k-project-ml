"""Sort readings into plausible, physically impossible, and valid-but-unsafe.

Impossible: outside what the sensor or ADC can produce (open thermistor, bit
  flip, NaN). The field is set to None and the raw value goes in packet.invalid.
  The rest of the packet is still shown and logged.
Unsafe: physically possible but outside normal operation (UV, OV, OT, OC). The
  value is kept and a Warning is added.

These are DISPLAY thresholds only. They are provisional, they don't change
packet.fault, and they trigger nothing. Every protection decision (bypass,
isolation, shutdown) is made by the STM32 firmware.
"""
import math

from telemetry import InvalidReading, TelemetryWarning as Warn

# physically possible range per sensor
CELL_PLAUSIBLE = {"voltage": (0.0, 5.5), "temperature": (-55.0, 150.0), "soh": (0.0, 100.0)}
PACK_PLAUSIBLE = {"pack_voltage": (0.0, 25.0), "pack_current": (-200.0, 200.0),
                  "soc": (0.0, 100.0), "pack_soh": (0.0, 100.0)}

# advisory display thresholds (NMC 18650 typical; the firmware's thresholds are authoritative)
CELL_UV = 3.0     # V, report 1.2 cut-off
CELL_OV = 4.2     # V
CELL_OT = 60.0    # degC
CELL_UT = 0.0     # degC
PACK_OC = 5.0     # A, OBJ-3 continuous load limit


def _check(value, lo, hi):
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        return "not a finite number"
    if value < lo or value > hi:
        return f"outside physically possible range [{lo}, {hi}]"
    return None


def assess(packet):
    """Return a copy with impossible values nulled into .invalid and unsafe ones flagged in .warnings."""
    p = packet.model_copy(deep=True)
    invalid, warnings = list(p.invalid), []
    for field, (lo, hi) in PACK_PLAUSIBLE.items():
        reason = _check(getattr(p, field), lo, hi)
        if reason:
            invalid.append(InvalidReading(field=field, value=repr(getattr(p, field)), reason=reason))
            setattr(p, field, None)
    for c in p.cells:
        for field, (lo, hi) in CELL_PLAUSIBLE.items():
            reason = _check(getattr(c, field), lo, hi)
            if reason:
                invalid.append(InvalidReading(field=f"cells.{c.id}.{field}", value=repr(getattr(c, field)), reason=reason))
                setattr(c, field, None)
        if c.voltage is not None and c.voltage < CELL_UV:
            warnings.append(Warn(code="CELL_UNDERVOLTAGE", cell=c.id, value=c.voltage, limit=CELL_UV,
                                    message=f"Cell {c.id} {c.voltage:.3f} V below {CELL_UV} V"))
        if c.voltage is not None and c.voltage > CELL_OV:
            warnings.append(Warn(code="CELL_OVERVOLTAGE", cell=c.id, value=c.voltage, limit=CELL_OV,
                                    message=f"Cell {c.id} {c.voltage:.3f} V above {CELL_OV} V"))
        if c.temperature is not None and c.temperature > CELL_OT:
            warnings.append(Warn(code="CELL_OVERTEMPERATURE", cell=c.id, value=c.temperature, limit=CELL_OT,
                                    message=f"Cell {c.id} {c.temperature:.1f} °C above {CELL_OT} °C"))
        if c.temperature is not None and c.temperature < CELL_UT:
            warnings.append(Warn(code="CELL_UNDERTEMPERATURE", cell=c.id, value=c.temperature, limit=CELL_UT,
                                    message=f"Cell {c.id} {c.temperature:.1f} °C below {CELL_UT} °C"))
    if p.pack_current is not None and abs(p.pack_current) > PACK_OC:
        warnings.append(Warn(code="PACK_OVERCURRENT", value=p.pack_current, limit=PACK_OC,
                                message=f"Pack current {p.pack_current:.2f} A exceeds ±{PACK_OC} A"))
    p.invalid, p.warnings = invalid, warnings
    return p
