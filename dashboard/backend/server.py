"""FastAPI app factory: REST + WebSocket on top of one shared ingestion loop."""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from config import Config
from database import get_legacy_telemetry, get_recent_events, get_recent_telemetry, init_db
from hub import TelemetryHub
from serial_reader import SerialSource
from simulator import MockSource

log = logging.getLogger("bms.server")


def make_source(config):
    if config.source == "HARDWARE":
        return SerialSource(config.serial_port, config.baud)
    return MockSource(config.mock_scenario, config.mock_interval_s)


def create_app(config=None, source=None, heartbeat_s=1.0):
    config = config or Config.from_env()
    backup = init_db(config.db_path)
    if backup:
        log.warning("database migrated; full backup saved to %s", backup)
    hub = TelemetryHub(source or make_source(config), config.source, config.db_path, heartbeat_s)

    @asynccontextmanager
    async def lifespan(app):
        tasks = [asyncio.create_task(hub.run()), asyncio.create_task(hub.heartbeat())]
        yield
        for t in tasks:
            t.cancel()
        for t in tasks:
            try:
                await t
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
        return hub.status_payload()

    @app.get("/api/events")
    def events(limit: int = Query(100, ge=1, le=5000)):
        return get_recent_events(limit, config.db_path)

    @app.get("/api/legacy")
    def legacy_history(limit: int = Query(50, ge=1, le=5000)):
        """Rows kept from the prototype schema after migration."""
        return get_legacy_telemetry(limit, config.db_path)

    @app.get("/api/history")
    def telemetry_history(limit: int = Query(50, ge=1, le=5000)):
        return get_recent_telemetry(limit, config.db_path)

    @app.websocket("/ws")
    async def telemetry_websocket(websocket: WebSocket):
        await websocket.accept()
        await websocket.send_json({"type": "status", "data": hub.status_payload()})
        if hub.latest is not None:
            await websocket.send_json({"type": "telemetry", "data": hub.latest.model_dump()})
        hub.clients.add(websocket)
        try:
            while True:
                await websocket.receive_text()  # incoming messages are ignored: no command path
        except WebSocketDisconnect:
            pass
        finally:
            hub.clients.discard(websocket)

    return app

