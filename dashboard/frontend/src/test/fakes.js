import { act } from "@testing-library/react";

export class FakeWebSocket {
  static instances = [];
  constructor(url) {
    this.url = url;
    this.sent = [];
    this.closed = false;
    FakeWebSocket.instances.push(this);
  }
  send(m) { this.sent.push(m); }
  close() { this.closed = true; }
  // test helpers
  open() { act(() => this.onopen?.()); }
  emit(obj) { act(() => this.onmessage?.({ data: typeof obj === "string" ? obj : JSON.stringify(obj) })); }
  drop() { act(() => this.onclose?.()); }
  static latest() { return FakeWebSocket.instances[FakeWebSocket.instances.length - 1]; }
}

export function cell(id, over = {}) {
  return { id, voltage: 3.7, temperature: 25.0, soh: 90.0, balancing: false, bypassed: false, fault: null, ...over };
}

export function packet(over = {}) {
  return {
    timestamp: "2026-11-05T04:00:00.000+00:00", source: "MOCK", seq: 1, mcu_ms: 250, scenario: "demo:normal",
    pack_voltage: 14.8, pack_current: 1.2, soc: null, pack_soh: null,
    cells: [1, 2, 3, 4].map((i) => cell(i)), balancing: false,
    fault: { active: false, cell: null, type: null }, system_state: "NORMAL", invalid: [], warnings: [],
    ...over,
  };
}

export function status(over = {}) {
  return { source: "MOCK", connected: true, port: "mock:demo", last_packet_at: null, packets_ok: 1,
           packets_rejected: 0, last_error: null, reconnects: 0, db_write_errors: 0,
           last_packet_age_s: 0.1, stale: false, server_time: "2026-11-05T04:00:00+00:00", ...over };
}

export function stubFetch(routes = {}) {
  return vi.fn((url) => {
    const key = Object.keys(routes).find((k) => url.includes(k));
    return Promise.resolve({ ok: true, json: () => Promise.resolve(key ? routes[key] : []) });
  });
}
