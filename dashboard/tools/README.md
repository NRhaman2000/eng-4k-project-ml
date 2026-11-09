# Phase 0: Mock serial loopback test (REQ-INT-01, mock data only)

Checks that the provisional telemetry frame (one JSON line every 250 ms at
115,200 baud 8N1) gets from a sender to a receiver over a serial link intact.
It uses a pseudo-terminal pair as a virtual null-modem cable, so it runs
without the ESP32-S3 or either board.

**What this does not prove:** anything about the real ESP32-S3 UART, the
ribbon connector, or the firmware. A PTY does not enforce baud-rate timing
(bytes move as fast as the OS allows), so wire load is computed from bytes
sent, not measured on a wire. Hardware integration is not done.

## Files

| File | Purpose |
| --- | --- |
| `serial_frame.py` | Provisional frame v0: encode/decode, CRC-32, validation |
| `mock_serial_streamer.py` | Sends synthetic 4S frames (`"src":"MOCK"`) at a fixed interval |
| `loopback_receiver.py` | Receive-only: validates each line, counts failures by kind, never writes to the port |
| `run_loopback_test.py` | Creates the PTY pair (socat), runs both as separate processes, writes a result JSON |
| `contract.py` | Provisional field contract as data; `python contract.py` prints the table in `docs/TELEMETRY_CONTRACT.md` |
| `firmware_harness.py` | Receive-only compatibility report for a serial port or capture file |
| `measure_e2e.py` | SIMULATED end-to-end latency, delivery and reconnection measurement over a PTY |
| `tests/` | pytest suite (frame validation, malformed input, receiver counting, short end-to-end run) |

## Provisional frame v0 (not confirmed by firmware)

```
<compact JSON>*<CRC-32 of the JSON bytes, 8 hex digits>\n
```

One real frame (seq 42) exactly as sent, 468 bytes including the newline:

```
{"v":0,"seq":42,"mcu_ms":10500,"src":"MOCK","state":"NORMAL","pack":{"v":14.857,"i":1.198,"soc":null,"soh":null},"cells":[{"id":1,"v":3.7117,"t":25.05,"soh":null,"bal":false,"bypass":false,"fault":null},{"id":2,"v":3.729,"t":25.45,"soh":null,"bal":false,"bypass":false,"fault":null},{"id":3,"v":3.7214,"t":25.98,"soh":null,"bal":false,"bypass":false,"fault":null},{"id":4,"v":3.6949,"t":26.46,"soh":null,"bal":false,"bypass":false,"fault":null}],"faults":[]}*E261DD4F
```

- `null` means "not measured / not available". The host shows N/A and never fills in a value.
- `state` is one of `NORMAL`, `BALANCING`, `FAULT_DETECTED`, `ISOLATED`.
- `src` is optional. The mock streamer always sends `MOCK`, so the dashboard labels its frames SERIAL TEST / SYNTHETIC. Firmware frames may omit it. The backend then uses the operator's `BMS_SERIAL_DATA_ORIGIN` (default UNVERIFIED); a frame can never mark itself MEASURED.
- The CRC is zlib/IEEE CRC-32, the STM32G4 hardware CRC unit's default polynomial. It can be made optional (`decode_frame(..., require_crc=False)`) if firmware won't send it.
- Every field name and type here is a proposal for the CE team to accept or change.

## Reproduce

Needs Python 3.10+, `pyserial`, `pytest`, and `socat` (macOS: `brew install socat`, Ubuntu: `sudo apt install socat`).

```bash
cd dashboard/tools
python3 -m venv .venv && source .venv/bin/activate
pip install pyserial pytest

python -m pytest tests -q                       # unit + 3 s end-to-end test

python run_loopback_test.py --duration 300      # 5-minute clean run (REQ-SE-01 asks for >= 5 min)

# Fault-injection run: proves the receiver detects and counts bad frames
python run_loopback_test.py --duration 60 --corrupt-every 50 --drop-every 75 --garbage-every 100
```

Each run prints its result and saves it to `results/loopback_<timestamp>.json`
(gitignored). The exit code is 0 only if every check passes:

- every line written arrived, and the byte counts match
- valid frames = frames written minus injected bad frames
- parse failures = injected bad frames
- sequence gaps = dropped frames + injected bad frames

## Known limitations

- A PTY loopback tests framing, parsing and counting, not electrical behaviour or real baud timing.
- A frame lost after the last valid frame is invisible to sequence counting. The byte and line totals still catch it.
- The receiver keeps every arrival time in memory. That's fine for test runs (5 min is 1,200 floats), but the dashboard ingestion loop will not do this.
