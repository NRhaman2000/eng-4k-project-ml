import pytest

from simulator import SCENARIOS, MockSource, packet_at


def states(scenario, ticks):
    seq = []
    for t in range(ticks):
        s = packet_at(scenario, t).system_state
        if not seq or seq[-1] != s:
            seq.append(s)
    return seq


def length(scenario):
    return sum(n for _, n, _ in SCENARIOS[scenario])


def test_deterministic():
    a = packet_at("demo", 123, seed=4, timestamp="x").model_dump()
    b = packet_at("demo", 123, seed=4, timestamp="x").model_dump()
    assert a == b and a["source"] == "MOCK"


def test_normal_scenario_never_faults():
    for t in range(length("normal") * 3):
        p = packet_at("normal", t)
        assert p.system_state == "NORMAL" and not p.fault.active


def test_undervoltage_transitions_and_isolation():
    assert states("undervoltage", length("undervoltage")) == ["NORMAL", "FAULT_DETECTED", "ISOLATED"]
    assert states("undervoltage", length("undervoltage") + 5)[-1] == "NORMAL"  # loops back: recovery
    for t in range(length("undervoltage")):
        p = packet_at("undervoltage", t)
        if p.system_state == "ISOLATED":
            assert p.cells[1].bypassed and p.fault.cell == 2 and p.fault.type == "UNDERVOLTAGE"
            assert p.pack_voltage < 12.0  # string runs on 3 cells
            assert not any(c.bypassed for c in p.cells if c.id != 2)
        if p.system_state == "NORMAL":
            assert not p.fault.active and not any(c.bypassed for c in p.cells)


def test_overtemperature_and_overcurrent():
    ot = [packet_at("overtemperature", t) for t in range(length("overtemperature"))]
    assert {p.fault.cell for p in ot if p.fault.active} == {4}
    assert max(p.cells[3].temperature for p in ot) > 60
    oc = [packet_at("overcurrent", t) for t in range(length("overcurrent"))]
    faults = [p for p in oc if p.fault.active]
    assert faults and all(p.fault.cell is None and p.pack_current > 5 for p in faults)


def test_balancing_marks_balancing_cells():
    p = [packet_at("balancing", t) for t in range(length("balancing"))]
    bal = [x for x in p if x.system_state == "BALANCING"]
    assert bal and all(x.balancing and x.cells[1].balancing and x.cells[2].balancing for x in bal)


def test_demo_covers_all_states():
    assert set(states("demo", length("demo"))) == {"NORMAL", "BALANCING", "FAULT_DETECTED", "ISOLATED"}


def test_unknown_scenario():
    with pytest.raises(ValueError):
        MockSource("nope")
