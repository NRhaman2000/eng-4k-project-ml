# Dashboard verification report: November 13 MVP readiness

**Date:** 2026-11-05. **Commit verified:** `main` at `5fb0afd` (PR #1 dashboard + PR #2 integration harness).
**Mode:** MOCK only. **All data is synthetic. No ESP32-S3 hardware was involved in any test below.**

Where it ran: automated tests in the Linux VM on the dev Mac (Python 3.10, Node 22). Browser
checks ran in headless Chrome (Playwright) in a Linux sandbox, from a fresh clone of `main`,
installed exactly as the README says, using `npm run dev`, two windows, and the
`demo` scenario at 0.25 s/packet. **Not yet run on macOS itself:** do one rehearsal there
(docs/DEMO_PROCEDURE.md).

## 1. Automated tests

| Suite | Result |
| --- | --- |
| Backend (pytest) | 80 passed |
| Tools: frame, loopback, firmware harness, e2e (pytest) | 69 passed |
| Frontend (Vitest + React Testing Library) | 27 passed |
| Frontend production build / lint (oxlint) | passes / 0 warnings, 0 errors |

## 2. Live MOCK demo (browser, real speed, synthetic data)

| Check | Measured | Result |
| --- | --- | --- |
| All four states shown | NORMAL, BALANCING, FAULT_DETECTED, ISOLATED | pass |
| State timeline vs documented 88 s loop | every change within 0.2-0.8 s of the documented time (BALANCING 10.2 s, FAULT_DETECTED 35.2 s, ISOLATED 35.7 s, NORMAL 50.9 s, FAULT_DETECTED 65.9 s, ISOLATED 66.6 s, NORMAL 76.8 s, overcurrent 86.6 s, NORMAL 88.7 s) | pass |
| Fault, isolation and recovery | cell 2 (UV) then cell 4 (OT) isolated; recovery to NORMAL both times; History shows FAULT_REPORTED, CELL_BYPASSED, FAULT_CLEARED, CELL_RESTORED, WARNING_RAISED/CLEARED | pass |
| State vs cell display consistency | 0 of 1,807 atomic reads showed ISOLATED without an isolated cell; database: 100 ISOLATED rows, all with a bypassed cell | pass |
| MOCK clearly identified | SIMULATED DATA (MOCK) banner and MOCK/SYNTHETIC badges in both windows; every CSV row MOCK/SYNTHETIC | pass |
| Two windows, same data | same last-packet time; 405 rows = 405 distinct seq (no duplicate writes) | pass |
| CSV export (page buttons) vs SQLite | 397 telemetry rows and 34 events, 0 mismatched cells; units in headers | pass |
| Stale warning on backend stop (Ctrl+C) | STALE banner after 0.3 s, Backend "Reconnecting…", last values stay frozen on screen | pass |
| Reconnect after restart | both windows Connected and STALE cleared 4.3 s after restart | pass |
| Persistence across restart | all 405 rows and 34 events kept; database in WAL mode | pass |
| External network use | no requests outside localhost (works without venue Wi-Fi) | pass |
| Console errors | none, apart from expected connection-refused messages while the backend was stopped | pass |

## 3. 10-minute soak (MOCK mode, synthetic demo scenario, one window)

| Minute | 0 | 1 | 3 | 5 | 7 | 9 | 10 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Browser JS heap after forced GC (MB) | 29.5 | 38.5 | 51.7 | 39.3 | 38.7 | 52.1 | 38.6 |
| Backend RSS (MB) | 53.8 | 54.0 | 54.1 | 54.1 | 54.1 | 54.1 | 54.1 |

No memory growth: the chart buffer stays at 240 points for the default 1-minute
window. 2,410 packets, 0 database write errors, database 0.65 MB after
10 minutes (about 4 MB/hour).

## 4. Data safety checks

- A copy of the real prototype `telemetry.db` (701 rows, schema v0) migrates to v3 with
  current `main`: a backup is made first, all 701 rows are in `telemetry_legacy`, and
  they're readable at `/api/legacy`. The demo uses a separate database, so this file is
  not touched unless the backend is started without `BMS_DB_PATH`.

- Demo restart procedure (Linux VM on the dev Mac, bash; zsh not available there): with
  `DEMO_DB` exported once, three stop/restart cycles of the backend reused the same file, and
  the rows grew 25, 50, 75. With `DEMO_DB` unset, `BMS_DB_PATH` becomes an empty string, which
  SQLite treats as a temporary per-connection database. The procedure therefore uses
  `${DEMO_DB:?…}`, which refuses to start instead (verified).

## 5. Issues that could affect the live demo

| # | Issue | Severity | Action |
| --- | --- | --- | --- |
| 1 | The dashboard Python venv doesn't exist on the dev Mac yet, and `pip install` needs internet | **must do before demo day** | DEMO_PROCEDURE.md section A |
| 2 | Not yet rehearsed on macOS itself (all checks ran on Linux) | **must do before demo day** | one full rehearsal of section C |
| 3 | Mac `node_modules` lacks the test packages (`npm test` fails); runtime packages are present and match the lockfile | low | `npm install` once (section A) |
| 4 | FAULT_DETECTED is on screen for only about 0.5 s per fault (by design: the OBJ-2 target is isolation within 1 ms) | presentation | point at it in History; or `BMS_MOCK_INTERVAL=0.5` |
| 5 | After a backend restart, reconnect takes up to about 5 s (frontend backoff) | presentation | expected; say so during the resilience check |
| 6 | An empty `BMS_DB_PATH` is not rejected by the backend (temporary database, no persistence) | low with the guarded command | procedure guards it; one-line backend check after the MVP |

No software defect was found that would block the MOCK demonstration.

## 6. Known limitations (unchanged)

- No ESP32-S3 testing. The serial path is tested only with a PTY loopback and synthetic frames;
  the frame format is provisional (docs/TELEMETRY_CONTRACT.md).
- Mock SoH values are fixed synthetic numbers. SoC and balancing direction are not reported.
- Warning thresholds (3.0 V, 4.2 V, 60 °C, 5 A) are provisional display values, not the firmware's.
- CSV export has no date filter (use one database per session). Chart history resets on reload.
