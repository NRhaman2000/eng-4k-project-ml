# BMS Telemetry Dashboard

Receive-only monitoring for the ENG4K 4S Fault-Tolerant Active BMS. The
dashboard displays and logs what the firmware reports. It sends nothing to
the MCU, and every bypass, isolation and shutdown decision stays in the
STM32 firmware.

**Status (Nov 2026):** works end to end on mock data. The serial path has
been tested only against a PTY loopback with synthetic frames (see
`tools/README.md`). **Hardware integration is not done**, and the packet
format is provisional until the CE team confirms it.

---

## 1. Install

Tested with Python 3.10 and Node 22. If `npm install` fails with
`Cannot read properties of null (reading 'edgesOut')` (seen with npm 10),
use `npx npm@11 install`. Optional: `socat` for the serial loopback tools
(`brew install socat`).

```bash
# backend (from the repo root)
cd dashboard/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt        # runtime + pytest/httpx

# frontend (second terminal)
cd dashboard/frontend
npm install                                 # always run on the machine that will run it
```

## 2. Start

```bash
# terminal 1: backend (MOCK demo by default)
cd dashboard/backend && source .venv/bin/activate
python -m uvicorn main:app                  # http://127.0.0.1:8000, API docs at /docs

# terminal 2: frontend
cd dashboard/frontend
npm run dev                                 # http://localhost:5173
```

On the first start against the old prototype database, the backend backs up
`telemetry.db` and migrates it (section 8). The log line names the backup
file.

Settings are environment variables:

| Variable | Default | Meaning |
| --- | --- | --- |
| `BMS_TRANSPORT` | `MOCK` | `MOCK` (in-process simulator) or `SERIAL` (serial port). `BMS_SOURCE=HARDWARE` still works as an alias for `SERIAL` |
| `BMS_SERIAL_DATA_ORIGIN` | `UNVERIFIED` | what SERIAL data is: `UNVERIFIED`, `MEASURED` (set this only when the STM32 is really connected) or `SYNTHETIC` |
| `BMS_SERIAL_PORT` | `/dev/ttyACM0` | e.g. `/dev/cu.usbmodem1103` on macOS (use `cu.`, not `tty.`), `COM5` on Windows |
| `BMS_BAUD` | `115200` | |
| `BMS_MOCK_SCENARIO` | `demo` | see section 3 |
| `BMS_MOCK_INTERVAL` | `0.25` | seconds per mock packet (`0.5` halves the speed) |
| `BMS_DB_PATH` | `backend/telemetry.db` | use a separate file for demos or tests |
| `VITE_BMS_BACKEND` (frontend) | `http://127.0.0.1:8000` | e.g. `VITE_BMS_BACKEND=http://lab-pc:8000 npm run dev` |

## 3. Mock scenarios

Every mock packet has `transport: "MOCK"` and `data_origin: "SYNTHETIC"`,
and the page shows an orange **SIMULATED DATA (MOCK)** banner. Scenarios are deterministic: the same
scenario, seed and tick always produce the same values. Each one loops.
The mock replays what the firmware is expected to report. It does not
model or control any hardware.

| Scenario | Loop | What happens |
| --- | --- | --- |
| `normal` | 10 s | NORMAL only |
| `balancing` | 20 s | NORMAL, then BALANCING: cells 2-3 balance, cell 3 pulled from 3.80 to 3.72 V |
| `undervoltage` | 30.5 s | cell 2 sags below 3.0 V (warning), FAULT_DETECTED, ISOLATED with cell 2 bypassed (pack drops to 3S, about 11.1 V), recovers while bypassed, NORMAL |
| `overtemperature` | 25.5 s | cell 4 heats past 60 °C, FAULT_DETECTED, ISOLATED while it cools, NORMAL |
| `overcurrent` | 12 s | pack current 6.2 A, FAULT_DETECTED (no cell), NORMAL |
| `demo` | 88 s | all of the above in one loop (timeline in section 10) |

```bash
BMS_MOCK_SCENARIO=undervoltage python -m uvicorn main:app
BMS_MOCK_SCENARIO=demo BMS_MOCK_INTERVAL=0.5 python -m uvicorn main:app   # slower, 176 s loop
```

Mock SoH values are fixed synthetic numbers (92.0 / 85.0 / 89.5 / 90.5 %),
not TinyML output. Mock SoC and pack SoH are not reported, so they show N/A.

## 4. Connecting the STM32 (once the protocol is confirmed)

1. Agree the frame format with CE. The contract to confirm is in
   [`docs/TELEMETRY_CONTRACT.md`](docs/TELEMETRY_CONTRACT.md): one JSON line
   every 250 ms at 115,200 8N1, with a CRC-32 suffix, plus the field list and
   15 open questions. The legacy `C1=..,T1=..,STATE=..` key=value lines are
   also accepted.
2. If the confirmed format differs, change only `tools/serial_frame.py`
   (framing and CRC) and `frame_to_packet()` in `backend/serial_reader.py`
   (field mapping). Nothing else depends on the wire format.
3. Find the port: `ls /dev/cu.usbmodem*` (macOS) or `ls /dev/ttyACM*` (Linux).
   On macOS, open the `cu.` device: the `tty.` one can block on open while it waits for carrier detect.
   Before starting the dashboard, check the firmware's output with the receive-only harness:
   `python ../tools/firmware_harness.py --port /dev/cu.usbmodem1103 --duration 60` (section 13).
4. Start, declaring that this port carries real measurements:
   `BMS_TRANSPORT=SERIAL BMS_SERIAL_DATA_ORIGIN=MEASURED BMS_SERIAL_PORT=/dev/cu.usbmodem1103 BMS_DB_PATH=bench.db python -m uvicorn main:app`.
   Without `BMS_SERIAL_DATA_ORIGIN=MEASURED`, serial data is labelled **UNVERIFIED**.
5. Check `http://127.0.0.1:8000/api/status`. You should see
   `connected: true` and `packets_ok` increasing. If `packets_rejected`
   grows, `last_error` says why: CRC, missing field, wrong state name, and
   so on.
6. The page banner turns green: **HARDWARE: MEASURED**. Unplugging the
   cable shows **Disconnected**, and the backend retries every 1 to 5 s.

Without the board, you can rehearse the same path with a virtual cable:

```bash
socat pty,raw,echo=0,link=/tmp/ttyTX pty,raw,echo=0,link=/tmp/ttyRX &
BMS_TRANSPORT=SERIAL BMS_SERIAL_PORT=/tmp/ttyRX python -m uvicorn main:app &
python ../tools/mock_serial_streamer.py --port /tmp/ttyTX --duration 120
```

These frames carry `"src":"MOCK"`, so the page shows **SERIAL TEST /
SYNTHETIC**: real serial transport, synthetic data. It shows that even if
`BMS_SERIAL_DATA_ORIGIN=MEASURED` is set, because a synthetic marker always
wins.

### Transport vs data origin

These are two independent labels, carried on every packet, event, database
row and CSV row:

| `transport` | `data_origin` | Banner | Meaning |
| --- | --- | --- | --- |
| `MOCK` | `SYNTHETIC` | SIMULATED DATA (MOCK) | in-process simulator |
| `SERIAL` | `SYNTHETIC` | SERIAL TEST / SYNTHETIC | real serial link, test frames marked synthetic (`src` = MOCK, SIM, SIMULATED, SYNTHETIC or TEST) |
| `SERIAL` | `UNVERIFIED` | SERIAL / ORIGIN NOT DECLARED | serial data the operator has not declared as real (the default) |
| `SERIAL` | `MEASURED` | HARDWARE: MEASURED | operator set `BMS_SERIAL_DATA_ORIGIN=MEASURED` and the frame is not marked synthetic |

A frame cannot promote itself to MEASURED: only the operator's setting can.
Data is never shown as hardware data unless it is MEASURED.

## 5. Validation (what happens to bad or dangerous readings)

| Tier | Example | Result |
| --- | --- | --- |
| Malformed | bad JSON or CRC, missing `seq`/`state`/`cells`, unknown state, cell ids not 1-4, text where a number belongs | packet rejected, counted in `/api/status`, logged; ingestion continues |
| Physically impossible | cell V outside 0-5.5, temperature outside -55 to 150 °C, SoH/SoC outside 0-100, pack V outside 0-25, \|I\| > 200 A, NaN | packet kept; only that field becomes empty/N/A, and the raw value is recorded and shown as "not plausible" |
| Valid but unsafe | cell < 3.0 V or > 4.2 V, > 60 °C or < 0 °C, \|I\| > 5.0 A | value kept and shown, plus an orange advisory warning and an event |

The unsafe thresholds in `backend/limits.py` are provisional display
thresholds. They never change the firmware's `fault` or `system_state`,
and they trigger nothing.

## 6. CSV export

Use the **Export telemetry CSV** and **Export events CSV** buttons on the
page (Historical Telemetry section), or:

```bash
curl -OJ http://127.0.0.1:8000/api/export/telemetry.csv
curl -OJ http://127.0.0.1:8000/api/export/events.csv
```

Files are named `bms_<telemetry|events>_<mock|serial>_<timestamp>.csv`.
They contain every stored row, oldest first, streamed straight from SQLite.

How to read them:

- **Units are in the headers:** `_V` volts, `_A` amps (sign exactly as
  reported; the firmware's sign convention is not yet confirmed), `_C` °C, `_pct` percent, `mcu_uptime_ms` milliseconds.
  `timestamp_utc` is the host receive time.
- **An empty cell means "not reported".** Nothing is filled in. In pandas,
  `pd.read_csv(f)` turns these into NaN.
- **Booleans** (`cellN_balancing`, `cellN_bypassed`, `balancing`,
  `firmware_fault_active`) are `1`/`0`, or empty if not reported.
- **`transport` and `data_origin` are on every row** (see the table in section 4).
  Filter on `data_origin == MEASURED` before analysing real battery
  behaviour. Never mix SYNTHETIC, UNVERIFIED and MEASURED rows in one result.
- **`firmware_fault_*`** is what the firmware reported.
  **`dashboard_warnings`** lists advisory threshold crossings, e.g.
  `CELL_UNDERVOLTAGE@2=2.41`. **`implausible_readings`** lists raw values
  that were replaced by empty cells, e.g. `cells.4.temperature=999.0`.
- **events.csv** has one row per change: `STATE`, `FAULT_REPORTED`,
  `FAULT_CLEARED`, `CELL_BYPASSED`, `CELL_RESTORED`, `BALANCING_START`,
  `BALANCING_STOP`, `WARNING_RAISED`, `WARNING_CLEARED`,
  `INVALID_READING`, `READING_RESTORED`.

## 7. API

| Endpoint | Returns |
| --- | --- |
| `GET /api/latest` | most recent accepted packet; 503 before the first one. Read-only. |
| `GET /api/status` | transport, configured data origin, connected, port, last packet time and age, `stale`, ok/rejected counts, last error, reconnects, DB write errors |
| `GET /api/history?limit=50` | newest telemetry rows (limit 1-5000) |
| `GET /api/events?limit=100` | newest events |
| `GET /api/legacy?limit=50` | rows kept from the prototype schema: `{"total": n, "rows": [...]}` |
| `GET /api/export/telemetry.csv`, `/api/export/events.csv` | CSV downloads (section 6) |
| `WS /ws` | `{"type": "status"\|"telemetry"\|"event", "data": ...}`. Status on connect and every 1 s, latest telemetry on connect, then every packet and every event. Incoming messages are ignored. |

`stale` is true when no packet has arrived for 2 s.

## 8. Data storage

SQLite tables: `telemetry` (one row per accepted packet, written once
however many browsers are open) and `events`.

Migration from an older schema never deletes data:
1. The whole file is copied to `telemetry.backup-<YYYYmmdd-HHMMSS>.db` using SQLite's online backup, and the copy's row count is checked.
2. The old table is renamed: v0 to `telemetry_legacy`, v1/v2 to `telemetry_legacy_vN`, and an old events table to `events_legacy_vN`. Row counts are checked again.
3. If any step fails, startup stops and nothing is changed.

The old rows are readable at `/api/legacy`. Databases and backups are
gitignored.

## 9. Tests

```bash
cd dashboard/backend  && python -m pytest tests -q   # backend: 80 tests
cd dashboard/tools    && python -m pytest tests -q   # frame, loopback, firmware harness, e2e: 69 tests
cd dashboard/frontend && npm test                     # Vitest + React Testing Library: 27 tests
cd dashboard/frontend && npm run build && npm run lint   # lint is oxlint (the project's linter)
cd dashboard/tools    && python run_loopback_test.py --duration 300   # 5-min loopback measurement
```

None of these need hardware. The socat-based tests skip themselves if
socat is missing.

## 10. November 13 demonstration (MOCK mode)

The full step-by-step procedure (preparation, exact macOS startup commands, the timed
demo script, live checks and troubleshooting) is in
**[`docs/DEMO_PROCEDURE.md`](docs/DEMO_PROCEDURE.md)**. The latest verification results are
in [`docs/VERIFICATION_REPORT.md`](docs/VERIFICATION_REPORT.md).

In short: start the backend with a demo database
(`BMS_DB_PATH=demo.db python -m uvicorn main:app`), start the frontend (`npm run dev`), and
open http://localhost:5173 in two windows. The `demo` scenario loops every 88 s through
NORMAL, BALANCING, FAULT_DETECTED and ISOLATED. **All demo data is synthetic.**

## 11. Architecture

```
MOCK:      simulator.MockSource ─┐
SERIAL:    serial_reader.SerialSource (JSON frame v0 or legacy key=value) ─┤
                                                                           v
                     hub.TelemetryHub (one ingestion loop for the whole backend)
                        ├─ limits.assess: null impossible readings, flag unsafe ones
                        ├─ save once to SQLite + derive events (events.py)
                        ├─ keep as latest   -> GET /api/latest
                        └─ broadcast        -> WS /ws (every client gets the same messages)
```

| Backend file | Role |
| --- | --- |
| `main.py` / `server.py` | entry point / app factory: REST, WebSocket, CSV, starts the loop and heartbeat |
| `config.py` | environment settings |
| `hub.py` | ingestion loop, broadcast, link status, staleness |
| `telemetry.py` | `TelemetryPacket` model (nullable fields, structural checks) |
| `limits.py` | plausible / impossible / unsafe classification |
| `events.py` | history events from consecutive packets |
| `simulator.py` | deterministic mock scenarios |
| `serial_reader.py` | serial source with reconnect; JSON v0 and key=value parsers |
| `database.py` | schema, backup-first migration, queries |
| `export.py` | streaming CSV export |

| Frontend file (`src/`) | Role |
| --- | --- |
| `hooks/useTelemetry.js` | one WebSocket per page, reconnect with backoff, envelope routing, 5-min chart buffer |
| `lib/format.js` | every number goes through `fmt()`: null/NaN shows "N/A" |
| `lib/telemetry.js` | cell condition, voltage spread, event merging |
| `components/StatusBar.jsx` | transport + data-origin banner and badges, backend and data-link state, last packet, stale warning |
| `components/PackSummary.jsx`, `CellCard.jsx` | pack and per-cell readings, bypass, firmware fault, warnings |
| `components/FaultPanel.jsx`, `BalancingPanel.jsx` | current fault/isolation, warnings, implausible readings, history |
| `components/Charts.jsx` | voltage, temperature, pack V/I and SoH charts, 30 s to 5 min windows |
| `components/HistoryTable.jsx` | last 20 rows and the CSV export buttons |

## 12. Known limitations

- **No STM32 testing.** Latency and delivery figures in section 13 are SIMULATED. SERIAL transport was exercised only through a PTY with synthetic and unverified test frames, and the frame format is provisional. MEASURED has never been used with real data yet.
- Mock SoH values are fixed synthetic numbers, not model output. Mock SoC and pack SoH are not reported.
- Charge-transfer direction is not in schema v0, so it shows as "Not reported by firmware".
- The warning thresholds are provisional display values. Align them with the firmware's thresholds once known.
- FAULT_DETECTED lasts 0.5 s in the mock, so it's easy to miss live. It is always in the history and the CSV.
- Chart history lives in the browser (up to 5 min) and resets on reload. SQLite history, events and CSV persist.
- WebSocket broadcast is sequential: fine for a few lab screens, not for many clients.
- The exports have no date filter yet: they always contain the whole database. Use a fresh `BMS_DB_PATH` per test session.
- The frontend is JavaScript. A TypeScript migration is deferred until after the MVP.
- The repo root README's dashboard sections predate this work. This file is the current reference.

## 13. Firmware integration and performance (synthetic until the STM32 is connected)

### 13.1 Checking firmware output against the contract

`tools/firmware_harness.py` is **receive-only**: it opens the port, reads lines,
and never writes. For every line it reports:
- contract fit: each field present / null / missing / invalid, plus fields not in the contract
- framing: CRC ok / missing / mismatch / malformed, non-frame text such as debug prints
- link: sequence gaps, frame interval from `mcu_ms`, host arrival rate (live port only)
- dashboard acceptance: whether `backend/serial_reader.py` would ingest the line

```bash
python tools/firmware_harness.py --port /dev/cu.usbmodem1103 --duration 60 --json-out fw_report.json
python tools/firmware_harness.py --file capture.txt     # offline, from a saved capture
```

Verdict and exit code: `COMPATIBLE` 0, `COMPATIBLE_WITH_WARNINGS` 1,
`INCOMPATIBLE` / `NO_FRAMES` 2. Synthetic frames (`src` = MOCK, SIM, TEST)
are always called out as not hardware data.

### 13.2 End-to-end measurement (SIMULATED)

`tools/measure_e2e.py` runs the real backend in SERIAL mode on a socat PTY,
feeds synthetic frames, listens on the WebSocket, and pulls the virtual
cable once:

```bash
python tools/measure_e2e.py --duration 150 --outage-at 60 --outage 5 --json-out tools/results/e2e.json
```

Latency is measured from the serial write to the WebSocket client receiving
the frame (matched by `seq`, same host clock). It includes parsing,
validation, the SQLite write and the broadcast. It does not include UART
wire time or browser rendering.

**Measured 2026-11-05, Linux VM on the dev Mac, Python 3.10. SIMULATED (PTY,
synthetic frames), not hardware:**

| Metric (SIMULATED) | Result |
| --- | --- |
| Frames written / received | 580 / 567 over 150 s (20 more scheduled while the cable was out) |
| Delivery outside the outage | 100.00 % |
| Lost frames | 13, all inside the outage window (the cable pull, plus frames sent before the backend reopened the port) |
| Duplicates / DB rows vs distinct seq | 0 / 567 = 567 |
| Latency p50 / p95 / p99 / max | 13.5 / 18.2 / 25.4 / 35.7 ms |
| UART wire time at 115,200 baud | about 41 ms per 470-byte frame (**computed, not measured**); a real link adds this |
| Disconnect shown on the dashboard | 0.83 s after the cable pull |
| First frame after replug | 3.19 s (dominated by the backend's 1-5 s retry backoff) |

REQ-SE-01 (display within 500 ms) passes with a wide margin on the loopback.
It must be re-measured on the STM32 before it can be claimed.

### 13.3 macOS: run everything locally

Not yet run on macOS itself: the commands above were tested on Linux, and the paths below are the macOS equivalents.

```bash
brew install socat node python@3.11          # skip what you already have
cd ~/eng-4k-project-ml/dashboard/backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt          # backend + tools + tests

python -m pytest tests -q                    # backend
cd ../tools && python -m pytest tests -q     # contract, harness, loopback, e2e (uses socat)
cd ../frontend && npm install && npm test && npm run build && npm run lint

# run the dashboard (two terminals)
cd ~/eng-4k-project-ml/dashboard/backend && source .venv/bin/activate && python -m uvicorn main:app
cd ~/eng-4k-project-ml/dashboard/frontend && npm run dev         # open http://localhost:5173

# with the board plugged in (receive-only check first, then the dashboard)
ls /dev/cu.usbmodem*
python ../tools/firmware_harness.py --port /dev/cu.usbmodemXXXX --duration 60 --json-out fw_report.json
BMS_TRANSPORT=SERIAL BMS_SERIAL_PORT=/dev/cu.usbmodemXXXX python -m uvicorn main:app
```

The dashboard labels serial data **UNVERIFIED** until you add
`BMS_SERIAL_DATA_ORIGIN=MEASURED`. Only do that once the harness reports the
board's frames as `COMPATIBLE` (or with understood warnings).
