import shutil

import pytest

from measure_e2e import measure, percentile


def test_percentile_nearest_rank():
    xs = list(range(1, 101))
    assert [percentile(xs, p) for p in (50, 95, 99, 100)] == [50, 95, 99, 100]
    assert percentile([7], 95) == 7 and percentile([], 50) is None


@pytest.mark.skipif(not shutil.which("socat"), reason="socat not installed")
def test_end_to_end_with_one_outage():
    # 8 s after replug > the backend's 5 s maximum retry backoff, so a reconnect always fits
    r = measure(duration=14, outage_at=4, outage_s=2)
    f = r["frames"]
    assert r["measurement"].startswith("SIMULATED")
    assert r["labels_seen"] == ["SERIAL/SYNTHETIC"]  # synthetic serial input is never shown as hardware
    assert f["duplicates_at_client"] == 0 and f["db_rows"] == f["db_distinct_seq"] == f["received"]
    assert r["delivery_rate_outside_outage_pct"] == 100.0
    assert f["lost_after_write"] == f["lost_in_outage_window"]  # every loss is explained by the outage
    assert r["latency_ms"]["p95"] < 500  # REQ-SE-01 budget, loopback only
    rc = r["reconnection"]
    assert rc["disconnect_shown_after_s"] is not None and rc["first_frame_after_replug_s"] is not None
    assert r["backend_status"]["reconnects"] >= 1 and r["backend_status"]["db_write_errors"] == 0
