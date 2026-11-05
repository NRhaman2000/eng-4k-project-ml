"""Single telemetry ingestion loop shared by every WebSocket client.

source -> assess (limits) -> save once -> events -> latest -> broadcast to all clients.
WebSocket messages are envelopes: {"type": "telemetry"|"status"|"event", "data": ...}.
A status heartbeat goes out every second, so the browser sees a disconnect
even when no packets arrive. Monitoring only: nothing here talks to the MCU.
"""
import asyncio
import logging
import time
from datetime import datetime, timezone

from database import save_events, save_telemetry
from events import diff_events
from limits import assess
from telemetry import LinkStatus

log = logging.getLogger("bms.hub")

STALE_AFTER_S = 2.0  # 8 missed frames at 4 Hz


class TelemetryHub:
    def __init__(self, source, transport, db_path=None, heartbeat_s=1.0, data_origin=None):
        self.source = source
        self.db_path = db_path
        self.heartbeat_s = heartbeat_s
        default_origin = "SYNTHETIC" if transport == "MOCK" else "UNVERIFIED"
        self.status = LinkStatus(transport=transport, data_origin=data_origin or default_origin)
        self.latest = None
        self.clients = set()
        self.published = 0
        self._last_mono = None

    def status_payload(self):
        d = self.status.model_dump()
        age = None if self._last_mono is None else time.monotonic() - self._last_mono
        d["last_packet_age_s"] = None if age is None else round(age, 3)
        d["stale"] = age is None or age > STALE_AFTER_S
        d["server_time"] = datetime.now(timezone.utc).isoformat()
        return d

    async def _broadcast(self, message):
        # shortcut: sequential sends; one slow client delays the rest. Fine for a few lab screens.
        for ws in list(self.clients):
            try:
                await ws.send_json(message)
            except Exception:
                self.clients.discard(ws)

    async def publish(self, packet):
        packet = assess(packet)
        events = diff_events(self.latest, packet)
        try:
            save_telemetry(packet, self.db_path)
            save_events(events, self.db_path)
        except Exception as e:  # report the loss (REQ-SE-02) but keep the live stream going
            self.status.db_write_errors += 1
            self.status.last_error = f"database write failed: {e}"
            log.exception("database write failed")
        self.latest = packet
        self.published += 1
        self._last_mono = time.monotonic()
        self.status.packets_ok += 1
        self.status.last_packet_at = datetime.now(timezone.utc).isoformat()
        for e in events:
            await self._broadcast({"type": "event", "data": e})
        await self._broadcast({"type": "telemetry", "data": packet.model_dump()})

    async def heartbeat(self):
        while True:
            await asyncio.sleep(self.heartbeat_s)
            await self._broadcast({"type": "status", "data": self.status_payload()})

    async def run(self):
        while True:
            try:
                async for packet in self.source.packets(self.status):
                    await self.publish(packet)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # keep ingesting; a bug in one packet must not stop logging
                log.exception("ingestion loop error")
                self.status.last_error = f"ingestion error: {e}"
                await asyncio.sleep(1)
