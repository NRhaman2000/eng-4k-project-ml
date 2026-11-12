import math

import pytest

from limits import assess
from simulator import packet_at


def base():
    return packet_at("normal", 0, timestamp="t")


@pytest.mark.parametrize("cell,field,value,code", [
    (2, "voltage", 2.41, "CELL_UNDERVOLTAGE"),
    (3, "voltage", 4.35, "CELL_OVERVOLTAGE"),
    (4, "temperature", 78.0, "CELL_OVERTEMPERATURE"),
    (1, "temperature", -12.0, "CELL_UNDERTEMPERATURE"),
])
def test_valid_but_unsafe_cell_reading_kept_with_warning(cell, field, value, code):
    p = base()
    setattr(p.cells[cell - 1], field, value)
    out = assess(p)
    assert getattr(out.cells[cell - 1], field) == value
    assert [(w.code, w.cell) for w in out.warnings] == [(code, cell)]
    assert out.invalid == [] and out.fault.active is False


def test_overcurrent_kept_with_warning_even_far_above_limit():
    p = base()
    p.pack_current = -85.0  # a short-circuit-scale reading is possible, so it is shown
    out = assess(p)
    assert out.pack_current == -85.0 and [w.code for w in out.warnings] == ["PACK_OVERCURRENT"]


@pytest.mark.parametrize("target,value", [
    ("cell_voltage", 9.9), ("cell_voltage", -0.4), ("cell_temp", 500.0),
    ("cell_soh", 140.0), ("pack_current", 400.0), ("cell_voltage", math.nan),
    ("cell_voltage", math.inf),
])
def test_physically_impossible_reading_nulled_and_recorded(target, value):
    p = base()
    if target == "cell_voltage":
        p.cells[0].voltage = value; field = "cells.1.voltage"
    elif target == "cell_temp":
        p.cells[0].temperature = value; field = "cells.1.temperature"
    elif target == "cell_soh":
        p.cells[0].soh = value; field = "cells.1.soh"
    else:
        p.pack_current = value; field = "pack_current"
    out = assess(p)
    assert [i.field for i in out.invalid] == [field]
    assert out.invalid[0].value == repr(value)
    assert out.model_dump_json()  # still serializable (NaN must not leak into JSON)
    # the other readings of the packet stay visible
    assert out.cells[1].voltage == p.cells[1].voltage and out.system_state == p.system_state


def test_assess_does_not_touch_firmware_fault_or_state():
    p = packet_at("undervoltage", 70, timestamp="t")
    out = assess(p)
    assert out.fault == p.fault and out.system_state == "ISOLATED"
    assert any(w.code == "CELL_UNDERVOLTAGE" and w.cell == 2 for w in out.warnings)


def test_none_values_are_not_flagged():
    p = base()
    p.cells[0].voltage = None
    p.pack_current = None
    out = assess(p)
    assert out.invalid == [] and out.warnings == []


def test_normal_packet_is_clean_and_input_unchanged():
    p = base()
    p.cells[0].voltage = 9.9
    assess(p)
    assert p.cells[0].voltage == 9.9  # assess works on a copy
    assert assess(base()).warnings == [] and assess(base()).invalid == []
