"""Single telemetry ingestion loop shared by every WebSocket client.

source -> validate -> save once to SQLite -> keep as latest -> broadcast to all clients.
Monitoring only: nothing here sends anything to the MCU.
"""
import asyncio
import logging
from datetime import datetime, timezone

from database import save_telemetry
from telemetry import LinkStatus

log = logging.getLogger("bms.hub")


class TelemetryHub:
    def __init__(self, source, source_name, db_path=None):
        self.source = source
        self.db_path = db_path
        self.status = LinkStatus(source=source_name)
        self.latest = None
        self.clients = set()
        self.published = 0

    async def publish(self, packet):
        try:
            save_telemetry(packet, self.db_path)
        except Exception as e:  # report the loss (REQ-SE-02) but keep the live stream going
            self.status.db_write_errors += 1
            self.status.last_error = f"database write failed: {e}"
            log.exception("database write failed")
        self.latest = packet
        self.published += 1
        self.status.packets_ok += 1
        self.status.last_packet_at = datetime.now(timezone.utc).isoformat()
        message = packet.model_dump()
        # shortcut: sequential sends; one slow client delays the rest. Fine for a few lab screens.
        for ws in list(self.clients):
            try:
                await ws.send_json(message)
            except Exception:
                self.clients.discard(ws)

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
