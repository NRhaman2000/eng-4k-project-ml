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
                        ├─ save once to SQLite (database.py)
                        ├─ keep as latest   -> GET /api/latest
                        └─ broadcast        -> WS /ws (every client gets the same packet)
```

| File (backend/) | Role |
| --- | --- |
| `main.py` | entry point (`uvicorn main:app`) |
| `server.py` | app factory: REST, WebSocket, starts the ingestion loop |
| `config.py` | settings from environment variables |
| `hub.py` | shared ingestion loop, broadcast, link status |
| `telemetry.py` | `TelemetryPacket` model: nullable fields, plausibility bounds |
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

Frontend (unchanged in this phase):

```bash
cd dashboard/frontend && npm install && npm run dev   # http://localhost:5173
```

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
| `GET /api/status` | source, connected, port, last packet time, ok/rejected counts, last error, reconnects, DB write errors |
| `GET /api/history?limit=50` | newest rows from SQLite (limit 1-5000) |
| `WS /ws` | sends the latest packet on connect, then every new packet. Incoming messages are ignored. |

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
- Packets are rejected (counted in `/api/status`, logged, ingestion continues) if they are malformed, fail the CRC, have an unknown `system_state`, don't have exactly cells 1-4, or contain physically implausible values (cell V outside 0-5, temperature outside -40-150 °C, SoH/SoC outside 0-100, |I| > 50 A). These bounds catch corrupted data. They are not safety limits.

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

One row per accepted packet, in table `telemetry`. On the first start against
a prototype database, the old table is renamed to `telemetry_legacy` (nothing
is deleted) and a new nullable table is created.

## Tests

```bash
cd dashboard/backend && python -m pytest tests -q   # 39 tests, no hardware needed
cd dashboard/tools   && python -m pytest tests -q   # 21 tests (Phase 0 frame + loopback)
```

The socat-based tests skip themselves if socat is not installed.

## Known limitations

- The WebSocket sends bare packets (as the current frontend expects), so a
  serial disconnect is visible only through `/api/status`, not pushed to the
  browser. Phase 2 changes the frontend and the message format together.
- The current frontend calls `.toFixed()` on SoH, voltage and temperature. A
  HARDWARE packet with a `null` there will crash it until Phase 2 adds N/A
  handling. MOCK mode always sends numbers.
- The broadcast is sequential: one slow client delays the others. That's fine
  for a few lab screens.
- No fault-event or state-transition tables, and no CSV export yet (planned).
