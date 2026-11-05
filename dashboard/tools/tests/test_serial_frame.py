import json
import random
import shutil
import subprocess
import sys
import os
import zlib

import pytest

from loopback_receiver import ReceiverStats, split_lines
from mock_serial_streamer import make_payload
from serial_frame import MAX_LINE_BYTES, FrameError, decode_frame, encode_frame


def frame(n=0, **overrides):
    p = make_payload(n, n * 250, random.Random(n))
    p.update(overrides)
    return encode_frame(p)


def with_crc(body: bytes) -> bytes:
    return body + b"*%08X\n" % zlib.crc32(body)


def kind(line, **kw):
    with pytest.raises(FrameError) as e:
        decode_frame(line, **kw)
    return e.value.kind


def test_roundtrip_keeps_nulls_and_mock_label():
    obj = decode_frame(frame(7))
    assert obj["seq"] == 7 and obj["src"] == "MOCK"
    assert obj["pack"]["soh"] is None and obj["cells"][0]["soh"] is None
    assert len(obj["cells"]) == 4


def test_frame_fits_link_budget():
    # 115,200 baud 8N1 / 4 frames per second = 2,880 bytes per frame
    assert len(frame(123456)) < 2880 / 4


def test_crc_mismatch_detected():
    b = bytearray(frame())
    b[10] ^= 0x01
    assert kind(bytes(b)) == "crc_mismatch"


def test_missing_crc_rejected_unless_optional():
    body = frame().rpartition(b"*")[0]
    assert kind(body + b"\n") == "no_crc"
    assert decode_frame(body + b"\n", require_crc=False)["seq"] == 0


@pytest.mark.parametrize("line,expected", [
    (b"not a json frame\n", "no_crc"),
    (b"{}*zzzzzzzz\n", "bad_crc_field"),
    (b"{}*1234\n", "bad_crc_field"),
    (with_crc(b"{not json"), "bad_json"),
    (with_crc(b"[1,2]"), "not_object"),
    (with_crc(b'{"v":0,"seq":1}'), "missing_fields"),
    (b"x" * (MAX_LINE_BYTES + 1), "oversize"),
])
def test_malformed_lines(line, expected):
    assert kind(line) == expected


@pytest.mark.parametrize("field,value,expected", [
    ("v", 1, "bad_version"),
    ("seq", -1, "bad_seq"),
    ("seq", "1", "bad_seq"),
    ("state", "EXPLODED", "bad_state"),
    ("cells", [], "bad_cells"),
])
def test_bad_field_values(field, value, expected):
    assert kind(frame(**{field: value})) == expected


def test_receiver_counts_gaps_and_out_of_order():
    s = ReceiverStats()
    for n in (0, 1, 4, 3, 5):
        s.process_line(frame(n), now=float(n))
    assert s.frames_ok == 5 and s.seq_gaps == 2 and s.seq_out_of_order == 1


def test_receiver_survives_bad_lines():
    s = ReceiverStats()
    data = frame(0) + b"garbage\n" + frame(1)
    buf = split_lines(b"", data, s, 0.0)
    assert buf == b"" and s.frames_ok == 2 and s.errors == {"no_crc": 1}


def test_split_lines_handles_partial_chunks():
    s = ReceiverStats()
    data = frame(0) + frame(1)
    buf = b""
    for i in range(0, len(data), 7):  # arrive in 7-byte chunks
        buf = split_lines(buf, data[i:i + 7], s, 0.0)
    assert s.frames_ok == 2 and buf == b""


def test_split_lines_discards_runaway_line():
    s = ReceiverStats()
    buf = split_lines(b"", b"x" * (MAX_LINE_BYTES + 1), s, 0.0)
    assert buf == b"" and s.errors["oversize"] == 1
    split_lines(buf, frame(0), s, 0.0)
    assert s.frames_ok == 1


@pytest.mark.skipif(not shutil.which("socat"), reason="socat not installed")
def test_short_loopback_end_to_end(tmp_path):
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    r = subprocess.run(
        [sys.executable, os.path.join(here, "run_loopback_test.py"), "--duration", "3",
         # 12 frames; lost seqs 4, 6, 9. The last frame (seq 11) must arrive or the
         # final loss is invisible to sequence counting.
         "--corrupt-every", "5", "--drop-every", "7", "--out-dir", str(tmp_path)],
        capture_output=True, text=True, timeout=60,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    result = json.loads(r.stdout.split("\nSaved:")[0])
    assert all(result["checks"].values())
    assert result["receiver"]["parse_failures_by_kind"] == {"crc_mismatch": 2}
    assert result["streamer"]["frames_scheduled"] == 12  # 3 s / 0.25 s, no extra frame
