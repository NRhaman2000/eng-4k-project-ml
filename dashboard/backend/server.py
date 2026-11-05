"""FastAPI app factory: REST + WebSocket on top of one shared ingestion loop."""
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from config import Config
from database import get_recent_telemetry, init_db
from hub import TelemetryHub
from serial_reader import SerialSource
from simulator import MockSource


def make_source(config):
    if config.source == "HARDWARE":
        return SerialSource(config.serial_port, config.baud)
    return MockSource(config.mock_scenario, config.mock_interval_s)


def create_app(config=None, source=None):
    config = config or Config.from_env()
    init_db(config.db_path)
    hub = TelemetryHub(source or make_source(config), config.source, config.db_path)

    @asynccontextmanager
    async def lifespan(app):
        task = asyncio.create_task(hub.run())
        yield
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    app = FastAPI(title="Fault-Tolerant Active BMS Telemetry API", lifespan=lifespan)
    app.state.hub = hub
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])

    @app.get("/")
    def root():
        return {"message": "BMS Telemetry Backend Running", "source": config.source}

    @app.get("/api/latest")
    def latest_telemetry():
        """Most recent accepted packet. Read-only: generates and saves nothing."""
        if hub.latest is None:
            raise HTTPException(status_code=503, detail="no telemetry received yet")
        return hub.latest

    @app.get("/api/status")
    def link_status():
        return hub.status

    @app.get("/api/history")
    def telemetry_history(limit: int = Query(50, ge=1, le=5000)):
        return get_recent_telemetry(limit, config.db_path)

    @app.websocket("/ws")
    async def telemetry_websocket(websocket: WebSocket):
        await websocket.accept()
        if hub.latest is not None:
            await websocket.send_json(hub.latest.model_dump())
        hub.clients.add(websocket)
        try:
            while True:
                await websocket.receive_text()  # incoming messages are ignored: no command path
        except WebSocketDisconnect:
            pass
        finally:
            hub.clients.discard(websocket)

    return app

