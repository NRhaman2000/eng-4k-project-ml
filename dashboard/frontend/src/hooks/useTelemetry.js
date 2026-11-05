import { useEffect, useState } from "react";
import { BACKEND, mergeEvents, toPoint } from "../lib/telemetry.js";

export const MAX_POINTS = 1200; // 5 min at 4 Hz

/**
 * One WebSocket per page, reconnecting with backoff.
 * Messages: {type: "telemetry"|"status"|"event", data}. Receive-only: nothing is ever sent.
 */
export function useTelemetry(backend = BACKEND) {
  const [packet, setPacket] = useState(null);
  const [status, setStatus] = useState(null);
  const [events, setEvents] = useState([]);
  const [history, setHistory] = useState([]);
  const [wsState, setWsState] = useState("connecting");
  const [lastReceivedAt, setLastReceivedAt] = useState(null);

  useEffect(() => {
    let ws;
    let timer;
    let delay = 1000;
    let stopped = false;

    const onTelemetry = (d) => {
      setPacket(d);
      setLastReceivedAt(Date.now());
      const pt = toPoint(d);
      setHistory((h) => {
        const last = h[h.length - 1];
        if (last && last.t === pt.t && last.seq === pt.seq) return h; // same packet twice
        const next = [...h, pt];
        return next.length > MAX_POINTS ? next.slice(-MAX_POINTS) : next;
      });
    };

    const loadEvents = () =>
      fetch(`${backend}/api/events?limit=100`)
        .then((r) => (r.ok ? r.json() : []))
        .then((list) => !stopped && setEvents((prev) => mergeEvents(list, prev)))
        .catch(() => {});

    const connect = () => {
      ws = new WebSocket(backend.replace(/^http/, "ws") + "/ws");
      ws.onopen = () => {
        delay = 1000;
        setWsState("open");
        loadEvents();
      };
      ws.onmessage = (ev) => {
        let msg;
        try {
          msg = JSON.parse(ev.data);
        } catch {
          return; // ignore anything that is not JSON
        }
        if (msg?.type === "telemetry" && msg.data) onTelemetry(msg.data);
        else if (msg?.type === "status" && msg.data) setStatus(msg.data);
        else if (msg?.type === "event" && msg.data) setEvents((prev) => mergeEvents([msg.data], prev));
        else if (msg?.cells) onTelemetry(msg); // pre-envelope backend
      };
      ws.onclose = () => {
        if (stopped) return;
        setWsState("reconnecting");
        timer = setTimeout(connect, delay);
        delay = Math.min(delay * 2, 5000);
      };
    };

    connect();
    return () => {
      stopped = true;
      clearTimeout(timer);
      ws?.close();
    };
  }, [backend]);

  return { packet, status, events, history, wsState, lastReceivedAt };
}

export function useNow(intervalMs = 1000) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}
