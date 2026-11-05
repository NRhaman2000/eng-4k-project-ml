"""Integration tests: firmware-like frames through the contract checker and the dashboard parser."""
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time

import pytest

from firmware_harness import Harness, read_serial
from mock_serial_streamer import make_payload
from serial_frame import encode_frame

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def fw(n=0, mutate=None, src=None):
    """A frame as real firmware would send it: no src marker unless given."""
    p = make_payload(n, n * 250, random.Random(n))
    del p["src"]
    if src:
        p["src"] = src
    if mutate:
        mutate(p)
    return encode_frame(p)


def run(lines):
    h = Harness()
    for i, line in enumerate(lines):
        h.feed(line, now=i * 0.25)
    return h.report()


def ok_stream(n=12, mutate=None):
    return [fw(i, mutate) for i in range(n)]


def test_valid_firmware_stream_is_compatible():
    r = run(ok_stream())
    assert r["verdict"] == "COMPATIBLE", r["warnings"] + r["problems"]
    assert r["accepted_by_dashboard"] == 12 and r["crc"] == {"ok": 12}
    assert r["fields"]["cells[].v"]["present"] == 48
    assert r["fields"]["pack.soc"]["verdict"] == "ALWAYS_NULL"  # optional: not a warning
    assert r["link"]["mcu_interval_ms_mean"] == 250.0 and r["link"]["missing_by_seq"] == 0


def test_missing_required_field_is_incompatible():
    r = run(ok_stream(mutate=lambda p: p.pop("seq")))
    assert r["verdict"] == "INCOMPATIBLE"
    assert r["fields"]["seq"]["verdict"] == "MISSING" and r["accepted_by_dashboard"] == 0
    assert any("seq" in p for p in r["problems"])


def test_missing_expected_field_is_a_warning_and_still_accepted():
    def drop_temp(p):
        for c in p["cells"]:
            del c["t"]
    r = run(ok_stream(mutate=drop_temp))
    assert r["verdict"] == "COMPATIBLE_WITH_WARNINGS" and r["accepted_by_dashboard"] == 12
    assert r["fields"]["cells[].t"]["verdict"] == "MISSING"
    assert any("cells[].t" in w for w in r["warnings"])


def test_sometimes_missing_field():
    lines = ok_stream(6) + [fw(i, lambda p: p["pack"].pop("i")) for i in range(6, 12)]
    r = run(lines)
    assert r["fields"]["pack.i"]["verdict"] == "SOMETIMES_MISSING"
    assert r["fields"]["pack.i"]["missing"] == 6 and r["fields"]["pack.i"]["present"] == 6


@pytest.mark.parametrize("mutate,field,example", [
    (lambda p: p["cells"][1].update(v=9.9), "cells[].v", "9.9 outside [0.0, 5.5]"),
    (lambda p: p["cells"][3].update(t=-80.0), "cells[].t", "-80.0 outside"),
    (lambda p: p["cells"][0].update(bal=1), "cells[].bal", "expected bool, got int"),
    (lambda p: p["pack"].update(i="1.2"), "pack.i", "expected number, got str"),
])
def test_invalid_values_reported_but_dashboard_keeps_the_packet(mutate, field, example):
    r = run(ok_stream(mutate=mutate))
    f = r["fields"][field]
    assert f["verdict"] == "INVALID" and example in f["invalid_examples"][0]
    assert r["verdict"] == "COMPATIBLE_WITH_WARNINGS"


@pytest.mark.parametrize("mutate,field", [
    (lambda p: p.update(state="IDLE"), "state"),
    (lambda p: p.update(v=1), "v"),
    (lambda p: p["cells"].pop(), "cells"),
    (lambda p: p.update(seq=-1), "seq"),
])
def test_structural_violations_are_incompatible(mutate, field):
    r = run(ok_stream(mutate=mutate))
    assert r["verdict"] == "INCOMPATIBLE" and r["accepted_by_dashboard"] == 0
    assert r["fields"][field]["verdict"] == "INVALID"
    assert r["rejected_samples"]


def test_unexpected_fields_are_listed_not_fatal():
    def extra(p):
        p["fw_version"] = "0.3.1"
        p["pack"]["temp"] = 31.0
        p["cells"][0]["r_int_mohm"] = 42
    r = run(ok_stream(mutate=extra))
    assert r["verdict"] == "COMPATIBLE_WITH_WARNINGS" and r["accepted_by_dashboard"] == 12
    assert set(r["unexpected_fields"]) == {"fw_version", "pack.temp", "cells[].r_int_mohm"}


def test_crc_problems_are_incompatible():
    good = fw(1)
    body = good.rpartition(b"*")[0]
    bad = bytearray(good); bad[12] ^= 1
    r = run([body + b"\n", bytes(bad), body + b"*XYZ\n"])
    assert r["crc"] == {"missing": 1, "mismatch": 1, "malformed": 1}
    assert r["verdict"] == "INCOMPATIBLE" and r["accepted_by_dashboard"] == 0


def test_debug_text_and_legacy_lines():
    lines = [b"BMS fw v0.1 booting...\n", b"\n"] + ok_stream(10) + [
        b"C1=3.7,C2=3.7,C3=3.7,C4=3.7,I=1.0,STATE=NORMAL\n"]
    r = run(lines)
    assert r["verdict"] == "COMPATIBLE_WITH_WARNINGS"
    assert r["non_frame_samples"] == ["BMS fw v0.1 booting..."] and r["legacy_kv_lines"] == 1
    assert r["accepted_by_dashboard"] == 11 and r["lines"] == 12  # blank line ignored


def test_sequence_gaps_and_slow_rate_warn():
    lines = [encode_frame({**make_payload(i, i * 500, random.Random(i)), "src": None}) for i in range(0, 30, 2)]
    r = run(lines)
    assert r["link"]["missing_by_seq"] == 14 and r["link"]["mcu_interval_ms_mean"] == 1000.0
    assert any("sequence" in w for w in r["warnings"]) and any("frame interval" in w for w in r["warnings"])


def test_synthetic_frames_are_flagged():
    r = run([fw(i, src="MOCK") for i in range(5)])
    assert r["synthetic_frames"] == 5 and any("synthetic" in w for w in r["warnings"])


def test_no_frames():
    assert run([])["verdict"] == "NO_FRAMES"


class FakeSerial:
    def __init__(self, data):
        self.data, self.closed, self.in_waiting = list(data), False, 0

    def read(self, n):
        return self.data.pop(0) if self.data else b""

    def write(self, *_):
        raise AssertionError("the harness must never write to the MCU")

    def close(self):
        self.closed = True


def test_serial_reader_is_receive_only_and_handles_split_chunks():
    blob = b"".join(ok_stream(5))
    chunks = [blob[i:i + 7] for i in range(0, len(blob), 7)]
    fake = FakeSerial(chunks)
    h = Harness()
    read_serial("fake", 115200, 0.5, 0, h, opener=lambda: fake)
    assert fake.closed and h.report()["accepted_by_dashboard"] == 5


def test_cli_on_capture_file(tmp_path):
    cap = tmp_path / "cap.txt"
    cap.write_bytes(b"".join(ok_stream(8)))
    out = tmp_path / "r.json"
    p = subprocess.run([sys.executable, os.path.join(TOOLS, "firmware_harness.py"), "--file", str(cap),
                        "--json-out", str(out)], capture_output=True, text=True)
    assert p.returncode == 0, p.stdout
    assert "VERDICT: COMPATIBLE" in p.stdout and json.loads(out.read_text())["verdict"] == "COMPATIBLE"


@pytest.mark.skipif(not shutil.which("socat"), reason="socat not installed")
def test_harness_on_a_real_pty_with_the_phase0_streamer(tmp_path):
    work = tempfile.mkdtemp()
    tx, rx = os.path.join(work, "tx"), os.path.join(work, "rx")
    socat = subprocess.Popen(["socat", f"pty,raw,echo=0,link={tx}", f"pty,raw,echo=0,link={rx}"],
                             stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            if os.path.exists(tx) and os.path.exists(rx):
                break
            time.sleep(0.1)
        out = tmp_path / "r.json"
        harness = subprocess.Popen([sys.executable, os.path.join(TOOLS, "firmware_harness.py"), "--port", rx,
                                    "--duration", "4", "--json-out", str(out)], stdout=subprocess.PIPE, text=True)
        time.sleep(0.5)
        subprocess.run([sys.executable, os.path.join(TOOLS, "mock_serial_streamer.py"), "--port", tx,
                        "--duration", "3"], check=True, stderr=subprocess.DEVNULL)
        harness.wait(timeout=15)
    finally:
        socat.terminate()
    r = json.loads(out.read_text())
    assert harness.returncode == 1  # warnings only: the streamer marks its frames synthetic
    assert r["accepted_by_dashboard"] >= 11 and r["crc"].get("mismatch", 0) == 0 and not r["problems"]
    assert r["synthetic_frames"] == r["accepted_by_dashboard"] and r["link"]["host_rate_hz"]


def test_contract_doc_table_matches_code():
    from contract import markdown_table
    doc = open(os.path.join(TOOLS, "..", "docs", "TELEMETRY_CONTRACT.md"), encoding="utf-8").read()
    assert markdown_table() in doc, "docs/TELEMETRY_CONTRACT.md is out of date: run python tools/contract.py"


def test_contract_doc_example_frame_is_compatible():
    doc = open(os.path.join(TOOLS, "..", "docs", "TELEMETRY_CONTRACT.md"), encoding="utf-8").read()
    example = doc.split("Example frame (exactly as sent):\n\n```\n", 1)[1].split("\n```", 1)[0]
    r = run([example.encode() + b"\n"])
    assert r["verdict"] == "COMPATIBLE" and r["accepted_by_dashboard"] == 1, r["problems"] + r["warnings"]
