"""Deterministic mock telemetry scenarios. MOCK DATA ONLY.

The mock replays what the firmware is expected to report (measurements and
firmware states). It does not decide anything: the thresholds below only
script when the mock firmware "reports" a fault. Real thresholds and every
bypass/isolation decision belong to the STM32 firmware.

Same scenario + seed + tick always gives the same packet (except timestamp).
"""
import asyncio
import math
import random
from datetime import datetime, timezone

from telemetry import CellTelemetry, FaultTelemetry, TelemetryPacket

BASE_V = [3.71, 3.69, 3.74, 3.70]
BASE_T = [25.0, 25.5, 26.0, 25.2]
MOCK_SOH = [92.0, 85.0, 89.5, 90.5]  # synthetic, labelled MOCK, until TinyML runs on the MCU


def _lerp(a, b, p):
    return a + (b - a) * p


# Each phase: (name, ticks, fn(p, cells, pack) -> None). p goes 0 -> 1 across the phase.
# cells: list of dicts (v, t, bal, bypass, fault); pack: dict (i, state, fault_type, fault_cell)

def normal(p, cells, pack):
    pack["state"] = "NORMAL"


def balancing(p, cells, pack):
    # cell 3 starts high and is pulled toward the others through the 2-3 balancer
    pack["state"] = "BALANCING"
    cells[2]["v"] = _lerp(3.80, 3.72, p)
    cells[1]["bal"] = cells[2]["bal"] = True


def uv_onset(p, cells, pack):
    pack["state"] = "NORMAL"
    cells[1]["v"] = _lerp(3.69, 2.95, p)


def uv_detected(p, cells, pack):
    pack.update(state="FAULT_DETECTED", fault_type="UNDERVOLTAGE", fault_cell=2)
    cells[1].update(v=2.95, fault="UNDERVOLTAGE")


def uv_isolated(p, cells, pack):
    pack.update(state="ISOLATED", fault_type="UNDERVOLTAGE", fault_cell=2)
    cells[1].update(v=2.95, fault="UNDERVOLTAGE", bypass=True)


def uv_recovering(p, cells, pack):
    # fault-injection resistor removed; cell still bypassed while it recovers
    pack.update(state="ISOLATED", fault_type="UNDERVOLTAGE", fault_cell=2)
    cells[1].update(v=_lerp(2.95, 3.66, p), fault="UNDERVOLTAGE", bypass=True)


def ot_onset(p, cells, pack):
    pack["state"] = "NORMAL"
    cells[3]["t"] = _lerp(26.0, 61.0, p)


def ot_detected(p, cells, pack):
    pack.update(state="FAULT_DETECTED", fault_type="OVERTEMPERATURE", fault_cell=4)
    cells[3].update(t=61.0, fault="OVERTEMPERATURE")


def ot_isolated(p, cells, pack):
    pack.update(state="ISOLATED", fault_type="OVERTEMPERATURE", fault_cell=4)
    cells[3].update(t=_lerp(61.0, 30.0, p), fault="OVERTEMPERATURE", bypass=True)


def oc_detected(p, cells, pack):
    pack.update(state="FAULT_DETECTED", fault_type="OVERCURRENT", fault_cell=None, i=6.2)


NORMAL = [("normal", 40, normal)]
BALANCING = [("balancing", 40, balancing)]
UNDERVOLTAGE = [("uv_onset", 20, uv_onset), ("uv_detected", 2, uv_detected),
                ("uv_isolated", 40, uv_isolated), ("uv_recovering", 20, uv_recovering)]
OVERTEMP = [("ot_onset", 20, ot_onset), ("ot_detected", 2, ot_detected), ("ot_isolated", 40, ot_isolated)]
OVERCURRENT = [("oc_detected", 8, oc_detected)]

SCENARIOS = {
    "normal": NORMAL,
    "balancing": NORMAL + BALANCING,
    "undervoltage": NORMAL + UNDERVOLTAGE,
    "overtemperature": NORMAL + OVERTEMP,
    "overcurrent": NORMAL + OVERCURRENT,
    "demo": NORMAL + BALANCING + NORMAL + UNDERVOLTAGE + NORMAL + OVERTEMP + NORMAL + OVERCURRENT,
}


def phase_at(scenario, tick):
    """Return (phase_name, fn, progress) for a tick; scenarios loop forever."""
    phases = SCENARIOS[scenario]
    tick %= sum(n for _, n, _ in phases)
    for name, n, fn in phases:
        if tick < n:
            return name, fn, (tick / (n - 1) if n > 1 else 1.0)
        tick -= n
    raise AssertionError("unreachable")


def packet_at(scenario, tick, seed=0, timestamp=None):
    name, fn, p = phase_at(scenario, tick)
    rng = random.Random(seed * 1_000_003 + tick)
    t = tick * 0.25
    cells = [{"v": BASE_V[i] + 0.004 * math.sin(t / 20 + i), "t": BASE_T[i],
              "bal": False, "bypass": False, "fault": None} for i in range(4)]
    pack = {"i": 1.2, "state": "NORMAL", "fault_type": None, "fault_cell": None}
    fn(p, cells, pack)
    for c in cells:
        c["v"] = round(c["v"] + rng.uniform(-0.002, 0.002), 4)
        c["t"] = round(c["t"] + rng.uniform(-0.1, 0.1), 2)
    i = round(pack["i"] + rng.uniform(-0.05, 0.05), 3)
    return TelemetryPacket(
        timestamp=timestamp or datetime.now(timezone.utc).isoformat(),
        transport="MOCK",
        data_origin="SYNTHETIC",
        seq=tick,
        mcu_ms=int(t * 1000),
        scenario=f"{scenario}:{name}",
        # a bypassed cell no longer contributes to the string voltage
        pack_voltage=round(sum(c["v"] for c in cells if not c["bypass"]), 4),
        pack_current=i,
        soc=None,
        pack_soh=None,
        cells=[CellTelemetry(id=k + 1, voltage=c["v"], temperature=c["t"], soh=MOCK_SOH[k],
                             balancing=c["bal"], bypassed=c["bypass"], fault=c["fault"])
               for k, c in enumerate(cells)],
        balancing=any(c["bal"] for c in cells),
        fault=FaultTelemetry(active=pack["fault_type"] is not None,
                             cell=pack["fault_cell"], type=pack["fault_type"]),
        system_state=pack["state"],
    )


class MockSource:
    def __init__(self, scenario="demo", interval_s=0.25, seed=0):
        if scenario not in SCENARIOS:
            raise ValueError(f"unknown mock scenario {scenario!r}; choose from {sorted(SCENARIOS)}")
        self.scenario, self.interval_s, self.seed = scenario, interval_s, seed

    async def packets(self, status):
        status.connected = True
        status.port = f"mock:{self.scenario}"
        tick = 0
        loop = asyncio.get_running_loop()
        start = loop.time()
        while True:
            yield packet_at(self.scenario, tick, self.seed)
            tick += 1
            await asyncio.sleep(max(0.0, start + tick * self.interval_s - loop.time()))
