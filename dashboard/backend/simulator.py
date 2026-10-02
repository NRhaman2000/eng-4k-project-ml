import random
from datetime import datetime

from telemetry import (
    TelemetryPacket,
    CellTelemetry,
    FaultTelemetry,
)


def generate_telemetry() -> TelemetryPacket:
    cells = []

    voltage_ranges = [
        (3.68, 3.75),
        (3.65, 3.72),
        (3.70, 3.77),
        (3.66, 3.73),
    ]

    fault_active = random.random() < 0.08
    fault_cell = None
    fault_type = None
    system_state = "NORMAL"

    if fault_active:
        fault_cell = random.randint(1, 4)
        fault_type = "UNDERVOLTAGE"
        system_state = "FAULT_DETECTED"

    for i in range(4):
        min_voltage, max_voltage = voltage_ranges[i]

        voltage = round(random.uniform(min_voltage, max_voltage), 3)

        if fault_active and i + 1 == fault_cell:
            voltage = round(random.uniform(2.30, 2.49), 3)

        cell = CellTelemetry(
            id=i + 1,
            voltage=voltage,
            temperature=round(random.uniform(23, 30), 1),
            soh=round(random.uniform(85, 95), 1),
        )

        cells.append(cell)

    pack_voltage = round(
        sum(cell.voltage for cell in cells),
        3,
    )

    return TelemetryPacket(
        timestamp=datetime.now().isoformat(),
        pack_voltage=pack_voltage,
        pack_current=round(random.uniform(-2, 2), 2),
        cells=cells,
        balancing=random.choice([True, False]),
        fault=FaultTelemetry(
            active=fault_active,
            cell=fault_cell,
            type=fault_type,
        ),
        system_state=system_state,
    )