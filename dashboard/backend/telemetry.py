from pydantic import BaseModel
from typing import List, Optional


class CellTelemetry(BaseModel):
    id: int
    voltage: float
    temperature: float
    soh: float


class FaultTelemetry(BaseModel):
    active: bool
    cell: Optional[int] = None
    type: Optional[str] = None


class TelemetryPacket(BaseModel):
    timestamp: str
    pack_voltage: float
    pack_current: float
    cells: List[CellTelemetry]
    balancing: bool
    fault: FaultTelemetry
    system_state: str