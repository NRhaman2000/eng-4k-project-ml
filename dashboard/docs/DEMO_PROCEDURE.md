# November 13 MVP demo: procedure (MOCK mode, macOS)

Everything shown is **synthetic data from the mock simulator**. The page says so
in an orange **SIMULATED DATA (MOCK)** banner. No ESP32-S3 is involved. The demo needs
no internet once installed (verified: the page requests nothing outside the laptop).

## A. Before demo day (needs internet, about 15 min)

```bash
cd ~/eng-4k-project-ml
git switch main && git pull --ff-only

# backend: its own virtual environment (do not reuse the root .venv, which is the ML environment)
cd dashboard/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

# frontend
cd ../frontend
npm install                     # if it fails with "edgesOut": npx npm@11 install

# check everything once
brew install socat                              # for the serial loopback tests
cd ../backend && python -m pytest tests -q      # expect 80 passed (1 skips without socat)
cd ../tools   && python -m pytest tests -q      # expect 69 passed (3 skip without socat)
cd ../frontend && npm test                      # expect 27 passed
```

Then do one full rehearsal of section C.

## B. On the day, 10 minutes before

1. Plug in the charger. Turn on Do Not Disturb (Focus), and close Zoom, Teams and anything else using ports 8000 or 5173.
2. Check the ports are free (no output means free):
   `lsof -nP -iTCP:8000 -sTCP:LISTEN; lsof -nP -iTCP:5173 -sTCP:LISTEN`
3. Open three Terminal tabs:

```bash
# Tab 1: backend. Pick the demo database name ONCE, so a restart (↑ Enter) reuses it and history survives
cd ~/eng-4k-project-ml/dashboard/backend && source .venv/bin/activate
export DEMO_DB=demo-$(date +%H%M).db
BMS_DB_PATH=${DEMO_DB:?run the export DEMO_DB line first} python -m uvicorn main:app

# Tab 2: frontend
cd ~/eng-4k-project-ml/dashboard/frontend && npm run dev

# Tab 3: keep the Mac awake for the whole demo (Ctrl+C when done)
caffeinate -dims
```

4. Open **http://localhost:5173** in **two** browser windows side by side.
5. Check both windows show:
   - the orange **SIMULATED DATA (MOCK)** banner
   - Transport **MOCK**, Data origin **SYNTHETIC**, Backend **Connected**
   - four cell cards, and charts that are moving
6. Optional health check: `curl -s http://127.0.0.1:8000/api/status`. You should see `"connected":true`, `"transport":"MOCK"` and `"db_write_errors":0`.

## C. Demo script (`demo` scenario, 88 s loop, repeats)

The times below were measured in the browser on 2026-11-05 **in MOCK mode** (synthetic
data, not the BMS). They count from backend start, and each later loop repeats them 88 s later.

| Time | State on screen | Point to |
| --- | --- | --- |
| 0-10 s | NORMAL | four cells about 3.70 V, pack about 14.8 V, charts updating 4 times per second |
| 10-20 s | BALANCING | cells 2 and 3 marked BALANCING (blue); the balancing activity list |
| 30-35 s | NORMAL + warning | cell 2 falls in the voltage chart; an orange advisory warning appears below 3.0 V |
| 35.2 s | FAULT_DETECTED (about 0.5 s) | firmware reports UNDERVOLTAGE on cell 2. **Easy to miss**: point at it in the History table afterwards |
| 35.7-50.9 s | ISOLATED | cell 2 card **ISOLATED (bypassed)**; pack voltage drops to about 11.1 V (3S); History shows FAULT_REPORTED then CELL_BYPASSED |
| 50.9 s | NORMAL | FAULT_CLEARED and CELL_RESTORED: recovery and reconfiguration |
| 60-66 s | NORMAL then FAULT_DETECTED | cell 4 temperature climbs past 60 °C |
| 66.6-76.8 s | ISOLATED | cell 4 bypassed while it cools |
| 86.6-88.7 s | FAULT_DETECTED | pack overcurrent 6.2 A (pack-level, no cell); then the loop restarts |

Then three live checks:

1. **Two windows, one source:** both windows show the same values and the same "Last packet" time. One backend loop broadcasts to every client and writes each packet to the database once.
2. **Resilience:** in Tab 1 press **Ctrl+C**.
   - Both windows show **Backend: Reconnecting…** and a red **STALE** banner within a second. The last values stay on screen.
   - Press **↑ then Enter** in the same Tab 1 to restart the backend with the same `$DEMO_DB`. Both windows reconnect, and STALE clears on its own (measured 4.3 s in MOCK mode).
   - Restart only in Tab 1: `DEMO_DB` exists only in that tab. In a new tab the guarded command refuses to start ("run the export DEMO_DB line first") instead of silently using a broken database. Re-run the `export` line with the **same** name, e.g. `export DEMO_DB=demo-1405.db`.
   - History survives the restart, because it's the same database file.
3. **Export:** click **Export telemetry CSV** and **Export events CSV**, and open them in Excel/Numbers. Show:
   - the units in the headers (`cell1_voltage_V`, `pack_current_A`, …)
   - `transport = MOCK` and `data_origin = SYNTHETIC` on every row
   - the isolation events with timestamps in the events file

**Say clearly:**
- All data is synthetic.
- Faults and isolation shown are what the firmware is *expected* to report. The dashboard sends no commands to the BMS.
- The serial path is implemented and was tested with a pseudo-terminal loopback and synthetic frames, not with the ESP32-S3 yet.

## D. If something goes wrong

| Symptom | Fix |
| --- | --- |
| `address already in use` in Tab 1 or 2 | `lsof -nP -iTCP:8000 -sTCP:LISTEN` (or 5173), then `kill <PID>`, then start again |
| Page stuck on "Waiting for BMS telemetry…" | Tab 1 isn't running or crashed: restart it. The page reconnects by itself |
| Red STALE banner that doesn't clear | the backend stopped: check Tab 1 and restart it |
| Blank page or Vite error in Tab 2 | `npm install` in `dashboard/frontend`, then `npm run dev` again |
| `ModuleNotFoundError` in Tab 1 | the venv isn't active: `source .venv/bin/activate` |
| `DEMO_DB: run the export DEMO_DB line first` | you're in a new tab: `export DEMO_DB=<the same name as before>`, then start again |
| Need to show a fault sooner | restart Tab 1 with `BMS_MOCK_SCENARIO=undervoltage`: fault at 15 s, 30.5 s loop |
| Audience needs it slower | restart Tab 1 with `BMS_MOCK_INTERVAL=0.5`: every phase takes twice as long, 176 s loop |

## E. After the demo

Ctrl+C in all three tabs. The demo database (`$DEMO_DB`, e.g. `demo-1405.db`) stays in
`dashboard/backend/`. It's gitignored, so delete it when you no longer need it.
