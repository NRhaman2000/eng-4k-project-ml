import { render, screen, waitFor } from "@testing-library/react";
import HistoryTable from "./HistoryTable.jsx";

afterEach(() => vi.unstubAllGlobals());

test("export links point at the backend CSV endpoints", async () => {
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve([]) })));
  render(<HistoryTable backend="http://lab-pc:8000" />);
  expect(screen.getByRole("link", { name: "Export telemetry CSV" }))
    .toHaveAttribute("href", "http://lab-pc:8000/api/export/telemetry.csv");
  expect(screen.getByRole("link", { name: "Export events CSV" }))
    .toHaveAttribute("href", "http://lab-pc:8000/api/export/events.csv");
  await waitFor(() => expect(screen.getByText("No history yet.")).toBeInTheDocument());
});

test("history rows with nulls render N/A and bypassed cells are marked", async () => {
  const row = { id: 1, timestamp: "2026-11-05T04:00:00Z", source: "HARDWARE", pack_voltage: null, pack_current: 1.1,
    cell1_voltage: 3.7, cell2_voltage: 2.95, cell2_bypassed: 1, cell3_voltage: null, cell4_voltage: 3.7,
    balancing: null, fault_active: 1, fault_cell: 2, fault_type: "UNDERVOLTAGE", system_state: "ISOLATED" };
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve([row]) })));
  render(<HistoryTable backend="http://x" />);
  await waitFor(() => expect(screen.getByText("ISOLATED")).toBeInTheDocument());
  expect(screen.getByText("2.950 V (bypassed)")).toBeInTheDocument();
  expect(screen.getByText("UNDERVOLTAGE / Cell 2")).toBeInTheDocument();
  expect(screen.getAllByText("N/A").length).toBe(3); // pack V, cell 3, balancing
});

test("history fetch failure is shown, not thrown", async () => {
  vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new Error("Failed to fetch"))));
  render(<HistoryTable backend="http://x" />);
  await waitFor(() => expect(screen.getByText(/History unavailable: Failed to fetch/)).toBeInTheDocument());
});
