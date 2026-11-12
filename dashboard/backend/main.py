"""Entry point.

Run:  python -m uvicorn main:app --reload        (from dashboard/backend)
Configure with BMS_TRANSPORT=MOCK|SERIAL, BMS_SERIAL_DATA_ORIGIN, BMS_SERIAL_PORT, BMS_BAUD,
BMS_MOCK_SCENARIO, BMS_MOCK_INTERVAL, BMS_DB_PATH (see config.py).
"""
from server import create_app

app = create_app()
