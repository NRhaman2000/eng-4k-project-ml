"""Backend settings, read from environment variables."""
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Config:
    transport: str = "MOCK"              # MOCK (in-process simulator) or SERIAL
    serial_data_origin: str = "UNVERIFIED"  # UNVERIFIED, MEASURED (operator-declared) or SYNTHETIC
    serial_port: str = "/dev/ttyACM0"
    baud: int = 115200
    mock_scenario: str = "demo"
    mock_interval_s: float = 0.25
    db_path: str = str(Path(__file__).parent / "telemetry.db")

    @classmethod
    def from_env(cls):
        c = cls(
            # BMS_SOURCE=HARDWARE is the older spelling of BMS_TRANSPORT=SERIAL
            transport=os.getenv("BMS_TRANSPORT", os.getenv("BMS_SOURCE", cls.transport)).upper().replace("HARDWARE", "SERIAL"),
            serial_data_origin=os.getenv("BMS_SERIAL_DATA_ORIGIN", cls.serial_data_origin).upper(),
            serial_port=os.getenv("BMS_SERIAL_PORT", cls.serial_port),
            baud=int(os.getenv("BMS_BAUD", cls.baud)),
            mock_scenario=os.getenv("BMS_MOCK_SCENARIO", cls.mock_scenario),
            mock_interval_s=float(os.getenv("BMS_MOCK_INTERVAL", cls.mock_interval_s)),
            db_path=os.getenv("BMS_DB_PATH", cls.db_path),
        )
        if c.transport not in ("MOCK", "SERIAL"):
            raise ValueError(f"BMS_TRANSPORT must be MOCK or SERIAL, got {c.transport!r}")
        if c.serial_data_origin not in ("UNVERIFIED", "MEASURED", "SYNTHETIC"):
            raise ValueError(f"BMS_SERIAL_DATA_ORIGIN must be UNVERIFIED, MEASURED or SYNTHETIC, got {c.serial_data_origin!r}")
        return c
