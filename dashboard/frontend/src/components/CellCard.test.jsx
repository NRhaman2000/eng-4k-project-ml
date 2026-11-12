import { render, screen, within } from "@testing-library/react";
import CellCard from "./CellCard.jsx";
import { cell, packet } from "../test/fakes.js";

test("all-null cell renders N/A instead of crashing", () => {
  const c = { id: 3, voltage: null, temperature: undefined, soh: null, balancing: null, bypassed: null, fault: null };
  render(<CellCard cell={c} packet={packet({ cells: [cell(1), cell(2), c, cell(4)] })} />);
  const card = screen.getByTestId("cell-3");
  expect(within(card).getAllByText("N/A")).toHaveLength(5); // V, T, SoH, balancing, bypass
});

test("implausible reading is shown as N/A with an explanation", () => {
  const c = cell(4, { temperature: null });
  const p = packet({ invalid: [{ field: "cells.4.temperature", value: "999.0", reason: "outside physically possible range" }] });
  render(<CellCard cell={c} packet={p} />);
  expect(screen.getByText(/sensor value not plausible/)).toBeInTheDocument();
  expect(screen.getByTestId("cell-4")).toHaveAttribute("data-condition", "warning");
});

test("unsafe but valid reading stays visible with an advisory warning", () => {
  const c = cell(2, { voltage: 2.41 });
  const p = packet({ warnings: [{ code: "CELL_UNDERVOLTAGE", cell: 2, value: 2.41, limit: 3.0, message: "Cell 2 2.410 V below 3.0 V" }] });
  render(<CellCard cell={c} packet={p} />);
  expect(screen.getByText("2.410 V")).toBeInTheDocument();
  expect(screen.getByText(/below 3.0 V \(dashboard advisory\)/)).toBeInTheDocument();
});

test("isolated cell shows bypass and firmware fault", () => {
  const c = cell(2, { voltage: 2.95, bypassed: true, fault: "UNDERVOLTAGE" });
  render(<CellCard cell={c} packet={packet({ fault: { active: true, cell: 2, type: "UNDERVOLTAGE" } })} />);
  const card = screen.getByTestId("cell-2");
  expect(card).toHaveAttribute("data-condition", "isolated");
  expect(within(card).getByText("BYPASSED")).toBeInTheDocument();
  expect(within(card).getByText("UNDERVOLTAGE")).toBeInTheDocument();
});
