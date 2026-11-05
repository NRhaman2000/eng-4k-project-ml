import random

import pytest

from mock_serial_streamer import make_payload
from serial_frame import encode_frame
from serial_reader import ParseError, parse_line

KV = ("C1=3.712,C2=3.684,C3=3.741,C4=3.699,T1=25.1,T2=26.0,T3=24.8,T4=25.4,I=1.21,"
      "SOH1=91.4,SOH2=88.2,SOH3=93.0,SOH4=90.1,BAL=1,FAULT=0,FAULT_CELL=0,FAULT_TYPE=NONE,STATE=NORMAL")


def v0(**overrides):
    p = make_payload(5, 1250, random.Random(0))
    p.update(overrides)
    return encode_frame(p)


def test_json_frame_maps_fields_and_keeps_nulls():
    pk = parse_line(v0())
    assert pk.seq == 5 and pk.mcu_ms == 1250 and pk.system_state == "NORMAL"
    assert pk.source == "MOCK"  # the streamer labels itself
    assert pk.cells[0].soh is None and pk.soc is None and pk.pack_soh is None
    assert pk.pack_voltage is not None and pk.fault.active is False


def test_json_frame_without_src_is_hardware():
    p = make_payload(1, 250, random.Random(0))
    del p["src"]
    assert parse_line(encode_frame(p)).source == "HARDWARE"


def test_json_frame_faults_and_bypass():
    p = make_payload(1, 250, random.Random(0))
    p["state"] = "ISOLATED"
    p["cells"][1].update(bypass=True, fault="UNDERVOLTAGE")
    p["faults"] = [{"type": "UNDERVOLTAGE", "cell": 2}]
    pk = parse_line(encode_frame(p))
    assert pk.fault.active and pk.fault.cell == 2 and pk.fault.type == "UNDERVOLTAGE"
    assert pk.cells[1].bypassed is True and pk.system_state == "ISOLATED"


def test_legacy_key_value_still_parses():
    pk = parse_line(KV)
    assert pk.source == "HARDWARE" and pk.balancing is True
    assert pk.pack_voltage == pytest.approx(14.836, abs=1e-3)
    assert pk.cells[3].soh == 90.1 and pk.fault.cell is None and pk.fault.type is None


def test_key_value_missing_fields_become_none():
    pk = parse_line("C1=3.7,C3=3.7,C4=NA,I=1.0,STATE=NORMAL")
    assert pk.cells[1].voltage is None and pk.cells[3].voltage is None
    assert pk.pack_voltage is None  # not summed when a cell is missing
    assert pk.cells[0].soh is None and pk.balancing is None


@pytest.mark.parametrize("line", [
    b"",
    b"garbage without equals",
    b"C1=3.7,STATE=NORMAL,I=abc",                      # not a number
    b"C1=3.7,I=1.0",                                   # no STATE
    b"C1=3.7,STATE=EXPLODED",                          # unknown state
    b'{"v":0}*00000000',                               # bad CRC
    b"\xff\xfe=1,STATE=NORMAL",                        # not ASCII
])
def test_invalid_lines_rejected(line):
    with pytest.raises(ParseError):
        parse_line(line)


def test_json_frame_with_bad_cell_ids_rejected():
    p = make_payload(1, 250, random.Random(0))
    p["cells"][3]["id"] = 1
    with pytest.raises(ParseError):
        parse_line(encode_frame(p))


def test_out_of_range_values_parse_and_are_left_to_limits():
    # range checks moved to limits.assess so unsafe readings are never dropped at parse time
    p = make_payload(1, 250, random.Random(0))
    p["cells"][0]["soh"] = 140
    assert parse_line(encode_frame(p)).cells[0].soh == 140
    assert parse_line("C1=9.9,T1=500,STATE=NORMAL").cells[0].voltage == 9.9


def test_non_numeric_json_value_rejected():
    p = make_payload(1, 250, random.Random(0))
    p["cells"][0]["v"] = "high"
    with pytest.raises(ParseError):
        parse_line(encode_frame(p))
