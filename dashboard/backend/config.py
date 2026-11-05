"""Backend settings, read from environment variables."""
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Config:
    source: str = "MOCK"                 # MOCK or HARDWARE
    serial_port: str = "/dev/ttyACM0"
    baud: int = 115200
    mock_scenario: str = "demo"
    mock_interval_s: float = 0.25
    db_path: str = str(Path(__file__).parent / "telemetry.db")

    @classmethod
    def from_env(cls):
        c = cls(
            source=os.getenv("BMS_SOURCE", cls.source).upper(),
            serial_port=os.getenv("BMS_SERIAL_PORT", cls.serial_port),
            baud=int(os.getenv("BMS_BAUD", cls.baud)),
            mock_scenario=os.getenv("BMS_MOCK_SCENARIO", cls.mock_scenario),
            mock_interval_s=float(os.getenv("BMS_MOCK_INTERVAL", cls.mock_interval_s)),
            db_path=os.getenv("BMS_DB_PATH", cls.db_path),
        )
        if c.source not in ("MOCK", "HARDWARE"):
            raise ValueError(f"BMS_SOURCE must be MOCK or HARDWARE, got {c.source!r}")
        return c
