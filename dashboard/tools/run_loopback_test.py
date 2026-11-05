"""Mock serial loopback test (REQ-INT-01, mock data only).

Creates a linked pseudo-terminal pair with socat (a virtual null-modem cable),
runs the receiver on one end and the streamer on the other as separate
processes, then writes a combined result JSON.

Note: a PTY does not enforce baud-rate timing. Both ends are configured for
115,200 8N1, and wire load is reported analytically from bytes sent.

Usage:
  python run_loopback_test.py --duration 300
  python run_loopback_test.py --duration 60 --corrupt-every 50 --drop-every 75 --garbage-every 100
"""
import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--duration", type=float, default=300)
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--interval", type=float, default=0.25)
    p.add_argument("--corrupt-every", type=int, default=0)
    p.add_argument("--drop-every", type=int, default=0)
    p.add_argument("--garbage-every", type=int, default=0)
    p.add_argument("--out-dir", default=os.path.join(HERE, "results"))
    a = p.parse_args()

    if not shutil.which("socat"):
        sys.exit("socat not found (macOS: brew install socat; Ubuntu: sudo apt install socat)")
    os.makedirs(a.out_dir, exist_ok=True)
    work = tempfile.mkdtemp(prefix="bms_loopback_")
    tx, rx = os.path.join(work, "ttyTX"), os.path.join(work, "ttyRX")
    s_out, r_out = os.path.join(work, "streamer.json"), os.path.join(work, "receiver.json")

    socat = subprocess.Popen(
        ["socat", f"pty,raw,echo=0,link={tx}", f"pty,raw,echo=0,link={rx}"],
        stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(50):
            if os.path.exists(tx) and os.path.exists(rx):
                break
            time.sleep(0.1)
        else:
            sys.exit("socat did not create the PTY pair")

        py = sys.executable
        receiver = subprocess.Popen(
            [py, os.path.join(HERE, "loopback_receiver.py"), "--port", rx, "--baud", str(a.baud),
             "--duration", str(a.duration + 10), "--stats-out", r_out],
            stderr=subprocess.DEVNULL,
        )
        time.sleep(0.5)  # receiver opens its end before the first frame
        started = datetime.now(timezone.utc).isoformat(timespec="seconds")
        subprocess.run(
            [py, os.path.join(HERE, "mock_serial_streamer.py"), "--port", tx, "--baud", str(a.baud),
             "--interval", str(a.interval), "--duration", str(a.duration),
             "--corrupt-every", str(a.corrupt_every), "--drop-every", str(a.drop_every),
             "--garbage-every", str(a.garbage_every), "--stats-out", s_out],
            check=True, stderr=subprocess.DEVNULL,
        )
        receiver.wait(timeout=30)
    finally:
        socat.terminate()

    with open(s_out) as f:
        streamer = json.load(f)
    with open(r_out) as f:
        receiver_stats = json.load(f)

    injected = (streamer["frames_intentionally_corrupted"] + streamer["garbage_lines_injected"])
    result = {
        "test": "mock serial loopback (PTY via socat), synthetic data",
        "started_utc": started,
        "host": f"{platform.system()} {platform.release()} / Python {platform.python_version()}",
        "config": {"baud": a.baud, "framing": "8N1", "interval_s": a.interval, "duration_s": a.duration,
                   "corrupt_every": a.corrupt_every, "drop_every": a.drop_every,
                   "garbage_every": a.garbage_every},
        "streamer": streamer,
        "receiver": receiver_stats,
        "checks": {
            "all_written_lines_arrived": receiver_stats["lines_received"] == streamer["frames_written"],
            "bytes_match": receiver_stats["bytes_received"] == streamer["bytes_written"],
            "valid_frames_equal_written_minus_injected":
                receiver_stats["frames_valid"] == streamer["frames_written"] - injected,
            "parse_failures_equal_injected": receiver_stats["parse_failures"] == injected,
            # dropped, corrupted and garbage frames all leave a hole in the sequence
            "seq_gaps_equal_dropped_plus_injected":
                receiver_stats["frames_missing_by_seq"] == streamer["frames_intentionally_dropped"] + injected,
        },
    }
    name = "loopback_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".json"
    path = os.path.join(a.out_dir, name)
    with open(path, "w") as f:
        json.dump(result, f, indent=2)
        f.write("\n")
    print(json.dumps(result, indent=2))
    print(f"\nSaved: {path}")
    sys.exit(0 if all(result["checks"].values()) else 1)


if __name__ == "__main__":
    main()
