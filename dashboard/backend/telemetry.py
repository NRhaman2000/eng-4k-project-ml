"""Shared telemetry model. Every source (mock, serial JSON, serial key=value)
produces a TelemetryPacket; the frontend and the database only see this shape.

None means "not reported". It is never replaced with an invented value.
Bounds are physical plausibility limits used to reject corrupted data, not
safety thresholds: those live in the STM32 firmware.
"""
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

SystemState = Literal["NORMAL", "BALANCING", "FAULT_DETECTED", "ISOLATED"]
Source = Literal["MOCK", "HARDWARE"]


class CellTelemetry(BaseModel):
    id: int = Field(ge=1, le=4)
    voltage: Optional[float] = Field(default=None, ge=0.0, le=5.0)
    temperature: Optional[float] = Field(default=None, ge=-40.0, le=150.0)
    soh: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    balancing: Optional[bool] = None
    bypassed: Optional[bool] = None
    fault: Optional[str] = None


class FaultTelemetry(BaseModel):
    active: bool = False
    cell: Optional[int] = Field(default=None, ge=1, le=4)
    type: Optional[str] = None


class TelemetryPacket(BaseModel):
    timestamp: str  # host receive time, ISO 8601 UTC
    source: Source
    seq: Optional[int] = Field(default=None, ge=0)
    mcu_ms: Optional[int] = Field(default=None, ge=0)
    scenario: Optional[str] = None  # mock only
    pack_voltage: Optional[float] = Field(default=None, ge=0.0, le=25.0)
    pack_current: Optional[float] = Field(default=None, ge=-50.0, le=50.0)
    soc: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    pack_soh: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    cells: List[CellTelemetry]
    balancing: Optional[bool] = None
    fault: FaultTelemetry = Field(default_factory=FaultTelemetry)
    system_state: SystemState

    @model_validator(mode="after")
    def four_distinct_cells(self):
        if sorted(c.id for c in self.cells) != [1, 2, 3, 4]:
            raise ValueError("cells must be exactly ids 1-4")
        self.cells.sort(key=lambda c: c.id)
        return self


class LinkStatus(BaseModel):
    source: Source
    connected: bool = False
    port: Optional[str] = None
    last_packet_at: Optional[str] = None
    packets_ok: int = 0
    packets_rejected: int = 0
    last_error: Optional[str] = None
    reconnects: int = 0
    db_write_errors: int = 0
