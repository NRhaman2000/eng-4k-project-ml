import asyncio

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from simulator import generate_telemetry


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


@app.get("/")
def root():
    return {
        "message": "BMS Telemetry Backend Running"
    }


@app.get("/api/latest")
def latest_telemetry():
    return generate_telemetry()


@app.websocket("/ws")
async def telemetry_websocket(websocket: WebSocket):
    await websocket.accept()

    try:
        while True:
            packet = generate_telemetry()

            await websocket.send_json(
                packet.model_dump()
            )

            await asyncio.sleep(1)

    except Exception:
        await websocket.close()