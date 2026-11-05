import { act, fireEvent, render, screen, within } from "@testing-library/react";
import App from "./App.jsx";
import { FakeWebSocket, cell, packet, status, stubFetch } from "./test/fakes.js";

beforeEach(() => {
  FakeWebSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeWebSocket);
  vi.stubGlobal("fetch", stubFetch({ "/api/history": [], "/api/events": [] }));
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

async function connected() {
  render(<App />);
  const ws = FakeWebSocket.latest();
  ws.open();
  await act(async () => {}); // let the mocked /api/history and /api/events fetches settle
  return ws;
}

test("waits for telemetry, then renders envelope data with MOCK label", async () => {
  const ws = await connected();
  expect(screen.getByText(/Waiting for BMS telemetry/)).toBeInTheDocument();
  ws.emit({ type: "status", data: status() });
  ws.emit({ type: "telemetry", data: packet({ pack_voltage: 14.812 }) });
  expect(screen.getByText("14.812 V")).toBeInTheDocument();
  expect(screen.getByText(/SIMULATED DATA \(MOCK\)/)).toBeInTheDocument();
  expect(screen.getAllByTestId(/^cell-/)).toHaveLength(4);
  expect(ws.url).toBe("ws://127.0.0.1:8000/ws");
  expect(ws.sent).toEqual([]); // monitoring only: the page never sends anything
});

test("HARDWARE packet full of nulls renders N/A everywhere without crashing", async () => {
  const ws = await connected();
  const nulls = { voltage: null, temperature: null, soh: null, balancing: null, bypassed: null, fault: null };
  ws.emit({
    type: "telemetry",
    data: packet({ source: "HARDWARE", pack_voltage: null, pack_current: null, balancing: null,
                   cells: [1, 2, 3, 4].map((i) => cell(i, nulls)) }),
  });
  expect(screen.getByText(/HARDWARE: live sensor data/)).toBeInTheDocument();
  expect(screen.queryByText(/SIMULATED DATA/)).not.toBeInTheDocument();
  for (const n of [1, 2, 3, 4]) expect(within(screen.getByTestId(`cell-${n}`)).getAllByText("N/A")).toHaveLength(5);
});

test("partial packet with missing optional keys still renders", async () => {
  const ws = await connected();
  ws.emit({ type: "telemetry", data: { timestamp: "2026-11-05T04:00:00Z", source: "HARDWARE", system_state: "NORMAL",
                                       cells: [{ id: 1 }, { id: 2 }, { id: 3 }, { id: 4 }] } });
  expect(screen.getByTestId("system-state")).toHaveTextContent("NORMAL");
  expect(screen.getByTestId("firmware-fault")).toHaveTextContent("None");
});

test("data link disconnect from status reaches the page", async () => {
  const ws = await connected();
  ws.emit({ type: "telemetry", data: packet() });
  ws.emit({ type: "status", data: status({ source: "HARDWARE", connected: false, stale: true, last_error: "disconnected: device unplugged" }) });
  expect(screen.getByText("Disconnected")).toBeInTheDocument();
  expect(screen.getByText(/device unplugged/)).toBeInTheDocument();
  expect(screen.getByRole("alert")).toHaveTextContent("STALE");
});

test("stale warning appears when telemetry stops arriving", async () => {
  vi.useFakeTimers();
  const ws = await connected();
  ws.emit({ type: "status", data: status() });
  ws.emit({ type: "telemetry", data: packet() });
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  act(() => vi.advanceTimersByTime(3500));
  expect(screen.getByRole("alert")).toHaveTextContent("STALE: last telemetry received 3 s ago.");
});

test("backend connection loss shows Reconnecting and opens a new socket", async () => {
  vi.useFakeTimers();
  const ws = await connected();
  ws.emit({ type: "telemetry", data: packet() });
  ws.drop();
  expect(screen.getByText("Reconnecting…")).toBeInTheDocument();
  act(() => vi.advanceTimersByTime(1100));
  expect(FakeWebSocket.instances.length).toBeGreaterThanOrEqual(2);
  FakeWebSocket.latest().open();
  await act(async () => {});
  expect(screen.getAllByText("Connected").length).toBeGreaterThan(0);
});

test("firmware states render: BALANCING, FAULT_DETECTED, ISOLATED", async () => {
  const ws = await connected();
  for (const s of ["BALANCING", "FAULT_DETECTED", "ISOLATED", "NORMAL"]) {
    ws.emit({ type: "telemetry", data: packet({ system_state: s }) });
    expect(screen.getByTestId("system-state")).toHaveTextContent(s);
  }
});

test("fault events show in history without duplicates", async () => {
  const ws = await connected();
  ws.emit({ type: "telemetry", data: packet() });
  const ev = { timestamp: "2026-11-05T04:00:05Z", source: "MOCK", seq: 20, kind: "FAULT_REPORTED", cell: 2,
               detail: "UNDERVOLTAGE", message: "Firmware reported UNDERVOLTAGE on cell 2" };
  ws.emit({ type: "event", data: ev });
  ws.emit({ type: "event", data: ev });
  const table = screen.getByRole("table", { name: "Fault history" });
  expect(within(table).getAllByText("Firmware reported UNDERVOLTAGE on cell 2")).toHaveLength(1);
});

test("duplicate telemetry is not added to the chart twice; window buttons switch", async () => {
  const ws = await connected();
  const p = packet({ seq: 5 });
  ws.emit({ type: "telemetry", data: p });
  ws.emit({ type: "telemetry", data: p });
  ws.emit({ type: "telemetry", data: packet({ seq: 6, timestamp: "2026-11-05T04:00:00.250+00:00" }) });
  expect(screen.getByTestId("chart-points")).toHaveTextContent("2 samples");
  const btn = screen.getByRole("button", { name: "5 min" });
  fireEvent.click(btn);
  expect(btn).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByRole("button", { name: "1 min" })).toHaveAttribute("aria-pressed", "false");
});

test("ignores malformed messages and accepts a pre-envelope packet", async () => {
  const ws = await connected();
  ws.emit("not json at all");
  ws.emit({ type: "unknown", data: 1 });
  expect(screen.getByText(/Waiting for BMS telemetry/)).toBeInTheDocument();
  ws.emit(packet({ pack_voltage: 13.5 }));
  expect(screen.getByText("13.500 V")).toBeInTheDocument();
});
