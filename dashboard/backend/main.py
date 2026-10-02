import asyncio

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from simulator import generate_telemetry
from database import init_db, save_telemetry, get_recent_telemetry


app = FastAPI(
    title="Fault-Tolerant Active BMS Telemetry API"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

init_db()


@app.get("/")
def root():
    return {
        "message": "BMS Telemetry Backend Running"
    }


@app.get("/api/latest")
def latest_telemetry():
    packet = generate_telemetry()
    save_telemetry(packet)
    return packet


@app.get("/api/history")
def telemetry_history(limit: int = 50):
    return get_recent_telemetry(limit)


@app.websocket("/ws")
async def telemetry_websocket(websocket: WebSocket):
    await websocket.accept()

    try:
        while True:
            packet = generate_telemetry()

            save_telemetry(packet)

            await websocket.send_json(
                packet.model_dump()
            )

            await asyncio.sleep(1)

    except Exception:
        await websocket.close()