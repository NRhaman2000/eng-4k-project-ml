"""FastAPI app factory: REST + WebSocket on top of one shared ingestion loop."""
import asyncio
import logging
from contextlib import asynccontextmanager

from datetime import datetime

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

from config import Config
from export import events_csv, telemetry_csv
from database import get_legacy_telemetry, get_recent_events, get_recent_telemetry, init_db
from hub import TelemetryHub
from serial_reader import SerialSource
from simulator import MockSource

log = logging.getLogger("bms.server")


def make_source(config):
    if config.transport == "SERIAL":
        return SerialSource(config.serial_port, config.baud, origin=config.serial_data_origin)
    return MockSource(config.mock_scenario, config.mock_interval_s)


def create_app(config=None, source=None, heartbeat_s=1.0):
    config = config or Config.from_env()
    backup = init_db(config.db_path)
    if backup:
        log.warning("database migrated; full backup saved to %s", backup)
    origin = "SYNTHETIC" if config.transport == "MOCK" else config.serial_data_origin
    hub = TelemetryHub(source or make_source(config), config.transport, config.db_path, heartbeat_s, origin)

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
        return {"message": "BMS Telemetry Backend Running", "transport": config.transport,
                "data_origin": hub.status.data_origin}

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

    def csv_response(chunks, kind):
        name = f"bms_{kind}_{config.transport.lower()}_{datetime.now():%Y%m%d-%H%M%S}.csv"
        return StreamingResponse(chunks, media_type="text/csv; charset=utf-8",
                                 headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @app.get("/api/export/telemetry.csv")
    def export_telemetry():
        """All stored telemetry rows, oldest first. Units in headers; empty = not reported."""
        return csv_response(telemetry_csv(config.db_path), "telemetry")

    @app.get("/api/export/events.csv")
    def export_events():
        """All fault, isolation, balancing, state and warning events, oldest first."""
        return csv_response(events_csv(config.db_path), "events")

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

