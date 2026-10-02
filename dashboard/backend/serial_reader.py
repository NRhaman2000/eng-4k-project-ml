from telemetry import (
    TelemetryPacket,
    CellTelemetry,
    FaultTelemetry,
)


def parse_serial_line(line: str) -> TelemetryPacket:
    """
    Convert one STM32 serial line into the same TelemetryPacket
    shape used by simulator.py.

    Expected future format example:
    C1=3.712,C2=3.684,C3=3.741,C4=3.699,
    T1=25.1,T2=26.0,T3=24.8,T4=25.4,
    I=1.21,SOH1=91.4,SOH2=88.2,SOH3=93.0,SOH4=90.1,
    BAL=1,FAULT=0,FAULT_CELL=0,FAULT_TYPE=NONE,STATE=NORMAL
    """

    values = {}

    parts = line.strip().split(",")

    for part in parts:
        if "=" not in part:
            continue

        key, value = part.split("=", 1)
        values[key.strip()] = value.strip()

    cells = [
        CellTelemetry(
            id=1,
            voltage=float(values["C1"]),
            temperature=float(values["T1"]),
            soh=float(values["SOH1"]),
        ),
        CellTelemetry(
            id=2,
            voltage=float(values["C2"]),
            temperature=float(values["T2"]),
            soh=float(values["SOH2"]),
        ),
        CellTelemetry(
            id=3,
            voltage=float(values["C3"]),
            temperature=float(values["T3"]),
            soh=float(values["SOH3"]),
        ),
        CellTelemetry(
            id=4,
            voltage=float(values["C4"]),
            temperature=float(values["T4"]),
            soh=float(values["SOH4"]),
        ),
    ]

    fault_active = values.get("FAULT", "0") == "1"

    fault_cell_raw = int(values.get("FAULT_CELL", "0"))
    fault_cell = fault_cell_raw if fault_cell_raw > 0 else None

    fault_type_raw = values.get("FAULT_TYPE", "NONE")
    fault_type = None if fault_type_raw == "NONE" else fault_type_raw

    return TelemetryPacket(
        timestamp=values.get("TIME", ""),
        pack_voltage=round(
            sum(cell.voltage for cell in cells),
            3,
        ),
        pack_current=float(values["I"]),
        cells=cells,
        balancing=values.get("BAL", "0") == "1",
        fault=FaultTelemetry(
            active=fault_active,
            cell=fault_cell,
            type=fault_type,
        ),
        system_state=values.get("STATE", "NORMAL"),
    )