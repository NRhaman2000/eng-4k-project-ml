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
| `BMS_SOURCE` | `MOCK` | `MOCK` or `HARDWARE` |
| `BMS_SERIAL_PORT` | `/dev/ttyACM0` | e.g. `/dev/tty.usbmodem1103` on macOS, `COM5` on Windows |
| `BMS_BAUD` | `115200` | |
| `BMS_MOCK_SCENARIO` | `demo` | see section 3 |
| `BMS_MOCK_INTERVAL` | `0.25` | seconds per mock packet (`0.5` halves the speed) |
| `BMS_DB_PATH` | `backend/telemetry.db` | use a separate file for demos or tests |
| `VITE_BMS_BACKEND` (frontend) | `http://127.0.0.1:8000` | e.g. `VITE_BMS_BACKEND=http://lab-pc:8000 npm run dev` |

## 3. Mock scenarios

Every mock packet has `source: "MOCK"`, and the page shows an orange
**SIMULATED DATA (MOCK)** banner. Scenarios are deterministic: the same
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

1. Agree the frame format with CE. The current proposal is in
   `tools/serial_frame.py` and `tools/README.md`: one JSON line every 250 ms
   at 115,200 8N1, with a CRC-32 suffix. The legacy `C1=..,T1=..,STATE=..`
   key=value lines are also accepted.
2. If the confirmed format differs, change only `tools/serial_frame.py`
   (framing and CRC) and `frame_to_packet()` in `backend/serial_reader.py`
   (field mapping). Nothing else depends on the wire format.
3. Find the port: `ls /dev/tty.usb*` (macOS) or `ls /dev/ttyACM*` (Linux).
4. Start: `BMS_SOURCE=HARDWARE BMS_SERIAL_PORT=/dev/tty.usbmodem1103 BMS_DB_PATH=bench.db python -m uvicorn main:app`
5. Check `http://127.0.0.1:8000/api/status`. You should see
   `connected: true` and `packets_ok` increasing. If `packets_rejected`
   grows, `last_error` says why: CRC, missing field, wrong state name, and
   so on.
6. The page banner turns green: **HARDWARE: live sensor data**. Unplugging
   the cable shows **Disconnected**, and the backend retries every 1 to 5 s.

Without the board, you can rehearse the same path with a virtual cable:

```bash
socat pty,raw,echo=0,link=/tmp/ttyTX pty,raw,echo=0,link=/tmp/ttyRX &
BMS_SOURCE=HARDWARE BMS_SERIAL_PORT=/tmp/ttyRX python -m uvicorn main:app &
python ../tools/mock_serial_streamer.py --port /tmp/ttyTX --duration 120
```

These frames still say `"src":"MOCK"`, so they are labelled MOCK even
though they come in over the serial port.

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

Files are named `bms_<telemetry|events>_<mock|hardware>_<timestamp>.csv`.
They contain every stored row, oldest first, streamed straight from SQLite.

How to read them:

- **Units are in the headers:** `_V` volts, `_A` amps (sign exactly as
  reported; the firmware's sign convention is not yet confirmed), `_C` °C, `_pct` percent, `mcu_uptime_ms` milliseconds.
  `timestamp_utc` is the host receive time.
- **An empty cell means "not reported".** Nothing is filled in. In pandas,
  `pd.read_csv(f)` turns these into NaN.
- **Booleans** (`cellN_balancing`, `cellN_bypassed`, `balancing`,
  `firmware_fault_active`) are `1`/`0`, or empty if not reported.
- **`source` and `data_origin` are on every row.**
  `SYNTHETIC (mock simulator, not measured)` vs `MEASURED (hardware)`.
  Filter on these before any analysis. Never mix them in a result.
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
| `GET /api/status` | source, connected, port, last packet time and age, `stale`, ok/rejected counts, last error, reconnects, DB write errors |
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
2. The old table is renamed: v0 to `telemetry_legacy`, v1 to `telemetry_legacy_v1`. Its row count is checked again.
3. If any step fails, startup stops and nothing is changed.

The old rows are readable at `/api/legacy`. Databases and backups are
gitignored.

## 9. Tests

```bash
cd dashboard/backend  && python -m pytest tests -q   # backend: 68 tests
cd dashboard/tools    && python -m pytest tests -q   # Phase 0 frame + PTY loopback: 21 tests
cd dashboard/frontend && npm test                     # Vitest + React Testing Library: 22 tests
cd dashboard/frontend && npm run build && npm run lint   # lint is oxlint (the project's linter)
cd dashboard/tools    && python run_loopback_test.py --duration 300   # 5-min loopback measurement
```

None of these need hardware. The socat-based tests skip themselves if
socat is missing.

## 10. November 13 demonstration (MOCK mode)

**Before (10 min):**
1. `git pull`, then `pip install -r requirements-dev.txt` and `npm install` (section 1).
2. Use a clean demo database, so the history and CSV show only the demo:
   `cd dashboard/backend && BMS_DB_PATH=demo.db python -m uvicorn main:app`
3. `cd dashboard/frontend && npm run dev`, then open http://localhost:5173 in **two** browser windows side by side.
4. Check both show the orange **SIMULATED DATA (MOCK)** banner, Backend **Connected**, and four cell cards.

**Demo loop timeline** (`demo` scenario, 88 s, repeats; times from backend start or loop start):

| Time | State | Point to |
| --- | --- | --- |
| 0-10 s | NORMAL | four cells about 3.70 V, pack about 14.8 V, live charts |
| 10-20 s | BALANCING | cells 2 and 3 marked BALANCING (blue), the spread shrinking, balancing activity list |
| 30-35 s | NORMAL + warning | cell 2 voltage falls in the chart; an orange advisory warning appears below 3.0 V |
| 35 s | FAULT_DETECTED (0.5 s) | firmware reports UNDERVOLTAGE on cell 2; easy to miss live, so show it in the history table afterwards |
| 35.5-50.5 s | ISOLATED | cell 2 card **ISOLATED (bypassed)**, pack voltage steps down to about 11.1 V (3S), history shows FAULT_REPORTED then CELL_BYPASSED |
| 50.5 s | NORMAL | FAULT_CLEARED and CELL_RESTORED: recovery and reconfiguration |
| 60.5-76 s | NORMAL, FAULT_DETECTED, ISOLATED | cell 4 overtemperature past 60 °C, isolated while cooling |
| 86-88 s | FAULT_DETECTED | pack overcurrent 6.2 A (pack-level, no cell) |

**Talking points / live checks:**
- Both windows show identical values: one backend loop, broadcast to every client, one database row per packet.
- **Monitoring only:** the fault and isolation decisions shown are reported by the firmware. The dashboard sends no commands.
- **Resilience:** press Ctrl+C on the backend. Both windows show **Reconnecting…** and a red **STALE** banner, and keep the last values. Restart it, and they recover within about 5 s on their own.
- **Data export:** click **Export telemetry CSV** and **Export events CSV**. Open in Excel and show the units in the headers, `data_origin = SYNTHETIC`, and the isolation events with timestamps.
- Slower pace if needed: `BMS_MOCK_INTERVAL=0.5` doubles every phase (176 s loop).

**Say clearly:** all data in the demo is synthetic. The serial path was
validated with a PTY loopback (Section 6.3.4), not with the STM32.

## 11. Architecture

```
MOCK:      simulator.MockSource ─┐
HARDWARE:  serial_reader.SerialSource (JSON frame v0 or legacy key=value) ─┤
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
| `components/StatusBar.jsx` | MOCK/HARDWARE banner, backend and data-link state, last packet, stale warning |
| `components/PackSummary.jsx`, `CellCard.jsx` | pack and per-cell readings, bypass, firmware fault, warnings |
| `components/FaultPanel.jsx`, `BalancingPanel.jsx` | current fault/isolation, warnings, implausible readings, history |
| `components/Charts.jsx` | voltage, temperature, pack V/I and SoH charts, 30 s to 5 min windows |
| `components/HistoryTable.jsx` | last 20 rows and the CSV export buttons |

## 12. Known limitations

- **No STM32 testing.** HARDWARE mode was exercised only through a PTY with synthetic frames, and the frame format is provisional.
- Mock SoH values are fixed synthetic numbers, not model output. Mock SoC and pack SoH are not reported.
- Charge-transfer direction is not in schema v0, so it shows as "Not reported by firmware".
- The warning thresholds are provisional display values. Align them with the firmware's thresholds once known.
- FAULT_DETECTED lasts 0.5 s in the mock, so it's easy to miss live. It is always in the history and the CSV.
- Chart history lives in the browser (up to 5 min) and resets on reload. SQLite history, events and CSV persist.
- WebSocket broadcast is sequential: fine for a few lab screens, not for many clients.
- The exports have no date filter yet: they always contain the whole database. Use a fresh `BMS_DB_PATH` per test session.
- The frontend is JavaScript. A TypeScript migration is deferred until after the MVP.
- The repo root README's dashboard sections predate this work. This file is the current reference.
