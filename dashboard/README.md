# BMS Telemetry Dashboard

Receive-only monitoring for the 4S fault-tolerant active BMS. The dashboard
displays and logs what the firmware reports. It never sends commands to the
MCU, and every bypass, isolation and shutdown decision stays in the STM32
firmware.

**Status:** runs on mock data. The serial path is tested against a PTY
loopback only (see `tools/README.md`). Hardware integration is not done, and
the packet format is provisional until the CE team confirms it.

## Architecture

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

| File (backend/) | Role |
| --- | --- |
| `main.py` | entry point (`uvicorn main:app`) |
| `server.py` | app factory: REST, WebSocket, starts the ingestion loop |
| `config.py` | settings from environment variables |
| `hub.py` | shared ingestion loop, broadcast, link status |
| `telemetry.py` | `TelemetryPacket` model: nullable fields, structural validation |
| `limits.py` | plausible / impossible / unsafe classification, advisory warnings |
| `events.py` | state, fault, bypass, balancing and warning history from consecutive packets |
| `simulator.py` | deterministic mock scenarios (MOCK) |
| `serial_reader.py` | serial source with reconnect; JSON v0 + key=value parsers (HARDWARE) |
| `database.py` | SQLite schema, migration, history queries |

## Run

```bash
cd dashboard/backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
python -m uvicorn main:app --reload            # http://127.0.0.1:8000, docs at /docs
```

Frontend:

```bash
cd dashboard/frontend
npm install          # run on your own machine; node_modules contains platform-specific binaries
npm run dev          # http://localhost:5173 (expects the backend at http://127.0.0.1:8000)
npm test             # Vitest + React Testing Library
npm run build && npm run lint
```

Point the frontend at another backend with `VITE_BMS_BACKEND=http://host:8000 npm run dev`.

| File (frontend/src/) | Role |
| --- | --- |
| `hooks/useTelemetry.js` | one WebSocket per page, reconnect with backoff, envelope routing, 5-min chart buffer |
| `lib/format.js` | every number goes through `fmt()`: null/NaN shows "N/A" |
| `lib/telemetry.js` | cell condition, voltage spread, event merging |
| `components/StatusBar.jsx` | MOCK/HARDWARE banner, backend and data-link state, last packet, stale warning |
| `components/PackSummary.jsx`, `CellCard.jsx` | pack and per-cell readings, bypass, firmware fault, advisory warnings |
| `components/FaultPanel.jsx`, `BalancingPanel.jsx` | current fault/isolation, warnings, invalid readings, history |
| `components/Charts.jsx` | voltage, temperature, pack V/I and SoH charts, 30 s to 5 min windows |
| `components/HistoryTable.jsx` | last 20 SQLite rows |

## Configuration (environment variables)

| Variable | Default | Meaning |
| --- | --- | --- |
| `BMS_SOURCE` | `MOCK` | `MOCK` or `HARDWARE` |
| `BMS_SERIAL_PORT` | `/dev/ttyACM0` | e.g. `/dev/tty.usbmodem1103` on macOS |
| `BMS_BAUD` | `115200` | |
| `BMS_MOCK_SCENARIO` | `demo` | `normal`, `balancing`, `undervoltage`, `overtemperature`, `overcurrent`, `demo` |
| `BMS_MOCK_INTERVAL` | `0.25` | seconds per mock packet |
| `BMS_DB_PATH` | `backend/telemetry.db` | |

Example: `BMS_SOURCE=HARDWARE BMS_SERIAL_PORT=/dev/tty.usbmodem1103 python -m uvicorn main:app`

## API

| Endpoint | Returns |
| --- | --- |
| `GET /api/latest` | most recent accepted packet; 503 before the first one. Read-only. |
| `GET /api/status` | source, connected, port, last packet time and age, `stale`, ok/rejected counts, last error, reconnects, DB write errors |
| `GET /api/history?limit=50` | newest rows from SQLite (limit 1-5000) |
| `GET /api/events?limit=100` | newest fault/state/bypass/balancing/warning events |
| `GET /api/legacy?limit=50` | rows kept from the prototype schema: `{"total": n, "rows": [...]}` |
| `WS /ws` | envelopes (below). Incoming messages are ignored: no command path. |

WebSocket messages are always `{"type": ..., "data": ...}`:

| type | when | data |
| --- | --- | --- |
| `status` | on connect, then every 1 s | same as `/api/status` |
| `telemetry` | on connect (latest), then every accepted packet | `TelemetryPacket` |
| `event` | when something changes | one events row |

The status heartbeat is how a serial disconnect or stalled stream reaches
the browser. `stale` is true when no packet has arrived for 2 s.

## Packet (`TelemetryPacket`)

Field names are kept from the prototype, so the current frontend still works.
New fields are additive. Real output of `packet_at("undervoltage", 70)`:

```json
{"timestamp":"2026-11-05T04:18:13.350127+00:00","source":"MOCK","seq":70,"mcu_ms":17500,"scenario":"undervoltage:uv_isolated","pack_voltage":11.1557,"pack_current":1.221,"soc":null,"pack_soh":null,
 "cells":[{"id":1,"voltage":3.7147,"temperature":24.96,"soh":92.0,"balancing":false,"bypassed":false,"fault":null},
          {"id":2,"voltage":2.9498,"temperature":25.43,"soh":85.0,"balancing":false,"bypassed":true,"fault":"UNDERVOLTAGE"},
          "...cells 3-4"],
 "balancing":false,"fault":{"active":true,"cell":2,"type":"UNDERVOLTAGE"},"system_state":"ISOLATED"}
```

- `timestamp` is the host receive time (UTC). `seq` and `mcu_ms` come from the firmware when it reports them.
- `null` means "not reported". The backend never fills in a value.
- `source` is `MOCK` or `HARDWARE`. Mock packets are always `MOCK`, including mock frames that arrive over a serial port.
- `invalid` and `warnings` are added by the backend (see below). `fault` is always exactly what the firmware reported.

### Validation: three tiers

| Tier | Example | What happens |
| --- | --- | --- |
| Malformed | bad JSON or CRC, missing `seq`/`state`/`cells`, unknown state, cell ids not 1-4, a number field that is text | packet rejected, counted in `/api/status`, logged; ingestion continues |
| Physically impossible | cell V outside 0-5.5, temperature outside -55 to 150 °C, SoH/SoC outside 0-100, pack V outside 0-25, \|I\| > 200 A, NaN/inf | packet kept; only that field becomes `null`, raw value recorded in `invalid[]`, shown as "N/A (sensor value not plausible)" |
| Valid but unsafe | cell < 3.0 V or > 4.2 V, > 60 °C or < 0 °C, \|I\| > 5.0 A | value kept and shown, advisory entry in `warnings[]`, logged as an event |

The unsafe thresholds (`limits.py`) are provisional display thresholds. They
never change `fault` or `system_state`, and they trigger nothing. Protection
decisions belong to the firmware.

Serial line formats accepted (both provisional):
1. JSON frame v0 `{...}*CRC32`, defined in `tools/serial_frame.py`
2. Legacy `C1=3.712,...,T1=25.1,...,I=1.21,SOH1=..,BAL=1,FAULT=0,FAULT_CELL=0,FAULT_TYPE=NONE,STATE=NORMAL`. A missing key or `NA` becomes null, and `PV=` optionally gives pack voltage.

## Mock scenarios

Deterministic: the same scenario, seed and tick always produce the same packet.
Each scenario loops. The mock scripts what the firmware would report; it
makes no decisions.

| Scenario | Sequence |
| --- | --- |
| `normal` | NORMAL only |
| `balancing` | NORMAL, then BALANCING (cells 2-3, cell 3 pulled down from 3.80 V) |
| `undervoltage` | cell 2 sags below 3.0 V, FAULT_DETECTED, ISOLATED (cell 2 bypassed, 3S pack), recovers, NORMAL |
| `overtemperature` | cell 4 heats past 60 °C, FAULT_DETECTED, ISOLATED while cooling, NORMAL |
| `overcurrent` | pack current 6.2 A, FAULT_DETECTED (no cell), NORMAL |
| `demo` | all of the above in one ~98 s loop |

Mock SoH values are fixed synthetic numbers labelled MOCK, so the current
frontend (which needs a number) keeps rendering. They are not model outputs.

## Database

Tables `telemetry` (one row per accepted packet, including `invalid_json` and
`warnings_json`) and `events`.

Migration from an older schema never deletes data:
1. The whole file is copied to `telemetry.backup-<YYYYmmdd-HHMMSS>.db` using SQLite's online backup, and the copy's row count is checked.
2. The old table is renamed: v0 to `telemetry_legacy`, v1 to `telemetry_legacy_v1`. Its row count is checked again.
3. If the backup or a count check fails, startup stops and nothing is changed.

Legacy rows are readable through `GET /api/legacy`. Backups are gitignored.

## Tests

```bash
cd dashboard/backend  && python -m pytest tests -q   # 60 tests, no hardware needed
cd dashboard/tools    && python -m pytest tests -q   # 21 tests (Phase 0 frame + loopback)
cd dashboard/frontend && npm test                     # 19 tests
```

The socat-based tests skip themselves if socat is not installed.

## Known limitations

- Not tested with the STM32. HARDWARE mode was exercised through a PTY with
  synthetic frames only. The packet format is provisional until the CE team
  confirms it.
- SoH values in MOCK mode are fixed synthetic numbers, not model output.
- The charge-transfer direction isn't in schema v0, so the dashboard shows
  "Not reported by firmware".
- The broadcast is sequential: one slow client delays the others. That's fine
  for a few lab screens.
- The chart history lives in the browser (up to 5 min at 4 Hz) and resets on
  reload. The SQLite history and events persist.
- No CSV export yet (planned).
