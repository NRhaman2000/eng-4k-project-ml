# Telemetry Contract (provisional, schema v0)

**Status: PROVISIONAL, awaiting confirmation from the Computer Engineering / firmware team.**
Nothing here has been tested with the STM32. The dashboard implements exactly this
contract today (`dashboard/tools/serial_frame.py`, `contract.py`,
`dashboard/backend/serial_reader.py`). If the firmware needs something different, tell
us and the dashboard side changes: the firmware does not have to match these names.

The dashboard is **receive-only**. It never writes to the serial port, and no command,
setpoint or acknowledgement is ever sent to the MCU.

## 1. Link and framing

| Item | Proposed value | Confirm? |
| --- | --- | --- |
| Physical link | USB virtual COM port (ST-LINK VCP) or UART-to-USB, MCU to host only | ☐ |
| Settings | 115,200 baud, 8 data bits, no parity, 1 stop bit, no flow control | ☐ |
| Rate | one frame every 250 ms (4 Hz) | ☐ |
| Frame | one line: compact JSON object, then `*`, then the CRC-32 as 8 hex digits, then `\n` | ☐ |
| CRC | CRC-32 (IEEE 802.3 / zlib, poly 0x04C11DB7 reflected, init 0xFFFFFFFF, final XOR 0xFFFFFFFF) over the JSON bytes only | ☐ |
| Line ending | `\n` (a trailing `\r` is tolerated) | ☐ |
| Max frame size | 4,096 bytes. A typical frame is about 470 bytes, about 16% of link capacity | ☐ |
| Other output on the same port | none. The dashboard counts any non-frame line (debug `printf`, boot banner, …) as a rejected packet and ignores it; the harness lists them as non-frame lines | ☐ |

Example frame (exactly as sent):

```
{"v":0,"seq":42,"mcu_ms":10500,"state":"BALANCING","pack":{"v":14.857,"i":1.198,"soc":null,"soh":null},"cells":[{"id":1,"v":3.7117,"t":25.05,"soh":null,"bal":false,"bypass":false,"fault":null},{"id":2,"v":3.729,"t":25.45,"soh":null,"bal":true,"bypass":false,"fault":null},{"id":3,"v":3.7214,"t":25.98,"soh":null,"bal":true,"bypass":false,"fault":null},{"id":4,"v":3.6949,"t":26.46,"soh":null,"bal":false,"bypass":false,"fault":null}],"faults":[]}*3BB314ED
```

Without the CRC suffix, the current dashboard rejects the frame. If the firmware cannot
compute CRC-32 (the STM32G4 has a hardware CRC unit), tell us, and we make it optional.

## 2. Fields

Levels: **required**: a frame without it is rejected. **expected**: the firmware should
send it; if absent, the dashboard shows N/A. **optional**: may be omitted. `null` is
always allowed for a measurement and means "not available". The dashboard never invents
a value.

| Field | Level | Type | Unit | Range / values | Meaning |
| --- | --- | --- | --- | --- | --- |
| `v` | required | int |  | 0 to 0 | schema version |
| `seq` | required | int |  | 0 to ∞ | frame counter, +1 per frame (detects loss) |
| `mcu_ms` | required | int | ms | 0 to ∞ | MCU uptime when the frame was built |
| `state` | required | enum |  | BALANCING, FAULT_DETECTED, ISOLATED, NORMAL | firmware safety state |
| `src` | optional | str |  |  | MOCK, SIM, SIMULATED, SYNTHETIC or TEST marks synthetic frames; omit on real hardware |
| `pack` | required | object |  |  | pack measurements |
| `pack.v` | expected | number | V | 0.0 to 25.0 | pack (string) voltage |
| `pack.i` | expected | number | A | -200.0 to 200.0 | pack current (sign convention TBD) |
| `pack.soc` | optional | number | % | 0.0 to 100.0 | state of charge estimate |
| `pack.soh` | optional | number | % | 0.0 to 100.0 | pack state of health estimate |
| `cells` | required | array[4] |  |  | exactly 4 cell objects, ids 1-4 |
| `cells[].id` | required | int |  | 1 to 4 | cell number |
| `cells[].v` | expected | number | V | 0.0 to 5.5 | cell voltage |
| `cells[].t` | expected | number | °C | -55.0 to 150.0 | cell temperature |
| `cells[].soh` | optional | number | % | 0.0 to 100.0 | TinyML SoH estimate |
| `cells[].bal` | expected | bool |  |  | cell's balancer active |
| `cells[].bypass` | expected | bool |  |  | cell bypassed / isolated |
| `cells[].fault` | expected | str |  |  | firmware fault on this cell, null if none |
| `faults` | optional | faults |  |  | active faults: [{"type": str, "cell": 1-4 or null}] |

Unknown extra fields are ignored by the dashboard and listed by the compatibility
harness, so adding a field never breaks anything.

**The harness is deliberately stricter than the dashboard.** The dashboard's parser is
lenient so that a slightly-off frame still shows something. For example it accepts `"250"`
or `null` for `mcu_ms`, `0.0` for `v`, a non-object or missing `pack` (shown as N/A),
`"2"` as a cell id, `1`/`0` or `"3.7"` for booleans and numbers, and it ignores
`faults` entries that are not `{"type", "cell"}` objects. The harness reports all of these
against the contract, so the firmware can send exactly this format. It never passes a frame
the dashboard would reject (checked by a test). Its report shows both the contract verdict
and `accepted_by_dashboard`.

### Firmware states (`state`)

| Value | Meaning |
| --- | --- |
| `NORMAL` | all cells in the string, no active fault |
| `BALANCING` | one or more balancers active |
| `FAULT_DETECTED` | a fault was detected; isolation not yet complete |
| `ISOLATED` | a faulted cell is bypassed; the pack runs on fewer cells |

Any other value is rejected. If the firmware has more states (INIT, SHUTDOWN, …), we
add them.

### Fault reporting

Per cell: `cells[].fault` is a fault name string, or `null` for none. Pack level:
`faults` is a list of `{"type": "<NAME>", "cell": <1-4 or null>}`, empty when none.
Names currently used by the mock: `UNDERVOLTAGE`, `OVERTEMPERATURE`, `OVERCURRENT`.

## 3. Questions for the CE / firmware team

1. Link: VCP over the ST-LINK USB, or a separate UART pin plus adapter? Which macOS device appears (`/dev/cu.usbmodem…`)?
2. Confirm 115,200 8N1 and 250 ms, or give the real values.
3. Is JSON practical on the MCU (`snprintf` with floats needs `-u _printf_float` on newlib-nano)? If not, which format? The dashboard also accepts the legacy `C1=…,STATE=…` key=value lines.
4. CRC-32 as specified, a different CRC, or none? On the STM32G4 the hardware CRC unit uses the same
   polynomial, but to match zlib it must be set to reverse input by byte, reverse output, init
   0xFFFFFFFF, and the result XORed with 0xFFFFFFFF. The default settings give a different value.
   Check value: CRC-32 of the ASCII bytes `123456789` must be `CBF43926`.
5. Units: volts and °C as floats, or integers in mV and 0.1 °C? How many decimal places?
6. Current sign convention: is a positive `pack.i` discharge or charge?
7. Is `pack.v` measured directly or summed from the cells? When a cell is bypassed, which cells does it include?
8. `seq`: integer width and wrap-around (uint16 wraps every 4.5 h at 4 Hz; uint32 effectively never). Does it reset on reboot? `mcu_ms`: uint32, wrapping after 49.7 days?
9. The full list of `state` values and fault names, and whether several faults can be active at once.
10. Balancing: are `cells[].bal` and `bypass` available per cell? Can the charge-transfer direction or balancer pair be reported (a proposed `balance_dir` field)?
11. SoH: per cell, per pack, or both? How often is it updated, and is it `null` until the first estimate?
12. Is SoC available at all?
13. The firmware's real thresholds (UV, OV, OT, OC). The dashboard's advisory warnings currently use 3.0 V, 4.2 V, 60 °C and 5 A.
14. Test builds: will firmware test or simulation builds set `"src":"TEST"`, so their frames are labelled synthetic?
15. Can debug output go to a separate UART (or SWO), or be prefixed with `#`, so it doesn't share the telemetry line?

## 4. How to check a firmware build against this contract

Receive-only, from the repository root, with the backend virtual environment active:

```bash
ls /dev/cu.usbmodem*                                           # macOS; Linux: ls /dev/ttyACM*
python dashboard/tools/firmware_harness.py --port /dev/cu.usbmodemXXXX --duration 60 --json-out fw_report.json
# or offline, from a capture someone sends you:
python dashboard/tools/firmware_harness.py --file capture.txt
```

The report lists every field as present / null / missing / invalid, every unexpected
field, CRC results, sequence gaps, frame interval (from `mcu_ms`) and whether each line
would be accepted by the dashboard. The verdict is `COMPATIBLE`,
`COMPATIBLE_WITH_WARNINGS` or `INCOMPATIBLE` (exit code 0, 1 or 2).

To regenerate the field table after changing `tools/contract.py`:
`python dashboard/tools/contract.py` (a test fails if this file and the code disagree).
