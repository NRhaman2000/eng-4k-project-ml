"""Shared telemetry model. Every source (mock, serial JSON, serial key=value)
produces a TelemetryPacket; the frontend and the database only see this shape.

None means "not reported". It is never replaced with an invented value.
Structural rules (cell ids, states, types) are enforced here. Measurement
ranges are not: limits.py sorts readings into plausible / impossible / unsafe
so that a valid but dangerous reading is never thrown away.
"""
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

SystemState = Literal["NORMAL", "BALANCING", "FAULT_DETECTED", "ISOLATED"]
# How the data reached the backend.
Transport = Literal["MOCK", "SERIAL"]
# Whether the values are real. SERIAL data is UNVERIFIED unless the operator declares it MEASURED;
# frames that mark themselves synthetic are always SYNTHETIC.
DataOrigin = Literal["SYNTHETIC", "MEASURED", "UNVERIFIED"]


class CellTelemetry(BaseModel):
    id: int = Field(ge=1, le=4)
    voltage: Optional[float] = None
    temperature: Optional[float] = None
    soh: Optional[float] = None
    balancing: Optional[bool] = None
    bypassed: Optional[bool] = None
    fault: Optional[str] = None


class FaultTelemetry(BaseModel):
    """What the FIRMWARE reports. The dashboard never sets this itself."""
    active: bool = False
    cell: Optional[int] = Field(default=None, ge=1, le=4)
    type: Optional[str] = None


class InvalidReading(BaseModel):
    """A reading outside what the sensor can physically produce. Raw value kept, field nulled."""
    field: str           # e.g. "cells.2.voltage", "pack_current"
    value: str           # raw value as text (may be NaN/inf, which JSON can't carry)
    reason: str


class TelemetryWarning(BaseModel):
    """Advisory, host-computed display warning. Not a fault, triggers nothing."""
    code: str            # CELL_UNDERVOLTAGE, CELL_OVERVOLTAGE, CELL_OVERTEMPERATURE, CELL_UNDERTEMPERATURE, PACK_OVERCURRENT
    cell: Optional[int] = None
    value: float
    limit: float
    message: str


class TelemetryPacket(BaseModel):
    timestamp: str  # host receive time, ISO 8601 UTC
    transport: Transport
    data_origin: DataOrigin
    seq: Optional[int] = Field(default=None, ge=0)
    mcu_ms: Optional[int] = Field(default=None, ge=0)
    scenario: Optional[str] = None  # mock only
    pack_voltage: Optional[float] = None
    pack_current: Optional[float] = None
    soc: Optional[float] = None
    pack_soh: Optional[float] = None
    cells: List[CellTelemetry]
    balancing: Optional[bool] = None
    fault: FaultTelemetry = Field(default_factory=FaultTelemetry)
    system_state: SystemState
    invalid: List[InvalidReading] = Field(default_factory=list)
    warnings: List[TelemetryWarning] = Field(default_factory=list)

    @model_validator(mode="after")
    def four_distinct_cells(self):
        if sorted(c.id for c in self.cells) != [1, 2, 3, 4]:
            raise ValueError("cells must be exactly ids 1-4")
        self.cells.sort(key=lambda c: c.id)
        return self


class LinkStatus(BaseModel):
    transport: Transport
    data_origin: DataOrigin  # configured default; each packet carries its own
    connected: bool = False
    port: Optional[str] = None
    last_packet_at: Optional[str] = None
    packets_ok: int = 0
    packets_rejected: int = 0
    last_error: Optional[str] = None
    reconnects: int = 0
    db_write_errors: int = 0
