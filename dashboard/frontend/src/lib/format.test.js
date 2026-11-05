import { fmt, fmtAge, fmtTime, NA, onOff } from "./format.js";
import { cellCondition, mergeEvents, toPoint, voltageSpread } from "./telemetry.js";

test("fmt never throws and shows N/A for missing values", () => {
  for (const v of [null, undefined, NaN, Infinity, "3.7", {}, true]) expect(fmt(v, 3, "V")).toBe(NA);
  expect(fmt(3.71234, 3, "V")).toBe("3.712 V");
  expect(fmt(0, 1)).toBe("0.0");
});

test("time helpers handle missing input", () => {
  expect(fmtTime(null)).toBe(NA);
  expect(fmtTime("not a date")).toBe(NA);
  expect(fmtAge(null)).toBe(NA);
  expect(fmtAge(500)).toBe("just now");
  expect(fmtAge(3200)).toBe("3 s ago");
  expect(onOff(null)).toBe(NA);
});

test("cell condition: firmware isolation and faults outrank dashboard warnings", () => {
  const p = { fault: { active: true, cell: 2, type: "UNDERVOLTAGE" }, warnings: [{ code: "CELL_UNDERVOLTAGE", cell: 2 }], invalid: [] };
  expect(cellCondition({ id: 2, bypassed: true }, p).kind).toBe("isolated");
  expect(cellCondition({ id: 2, bypassed: false }, p).kind).toBe("fault");
  expect(cellCondition({ id: 3 }, { ...p, warnings: [{ code: "X", cell: 3 }] }).kind).toBe("warning");
  expect(cellCondition({ id: 4 }, { invalid: [{ field: "cells.4.temperature" }] }).kind).toBe("warning");
  expect(cellCondition({ id: 1, balancing: true }, {}).kind).toBe("balancing");
  expect(cellCondition({ id: 1 }, {}).kind).toBe("normal");
});

test("voltage spread ignores missing and bypassed cells", () => {
  expect(voltageSpread([{ voltage: 3.7 }, { voltage: 3.75 }, { voltage: null }, { voltage: 2.9, bypassed: true }]))
    .toBeCloseTo(0.05);
  expect(voltageSpread([{ voltage: 3.7 }, { voltage: null }])).toBeNull();
});

test("toPoint keeps nulls; mergeEvents dedupes newest first", () => {
  const pt = toPoint({ timestamp: "2026-01-01T00:00:00Z", cells: [{ id: 1, voltage: null, temperature: 25 }] });
  expect(pt.v1).toBeNull();
  expect(pt.t1).toBe(25);
  const e1 = { timestamp: "2026-01-01T00:00:01Z", kind: "STATE", cell: null, detail: "a" };
  const e2 = { timestamp: "2026-01-01T00:00:02Z", kind: "FAULT_REPORTED", cell: 2, detail: "UV" };
  expect(mergeEvents([e1], [e2, { ...e1, id: 9 }])).toEqual([e2, e1]);
});
