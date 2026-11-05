export const STALE_MS = 2000; // 8 missed frames at 4 Hz
export const CELL_COLORS = ["#2563eb", "#d97706", "#059669", "#9333ea"];
export const BACKEND = import.meta.env.VITE_BMS_BACKEND || "http://127.0.0.1:8000";

export function cellWarnings(packet, id) {
  return (packet?.warnings ?? []).filter((w) => w.cell === id);
}

export function invalidFor(packet, field) {
  return (packet?.invalid ?? []).find((i) => i.field === field);
}

/** One label per cell. Firmware-reported conditions outrank dashboard warnings. */
export function cellCondition(cell, packet) {
  const firmwareFault = !!cell.fault || (packet?.fault?.active && packet?.fault?.cell === cell.id);
  if (cell.bypassed) return { kind: "isolated", label: "ISOLATED (bypassed)" };
  if (firmwareFault) return { kind: "fault", label: "FAULT" };
  const advisory = cellWarnings(packet, cell.id).length > 0
    || (packet?.invalid ?? []).some((i) => i.field.startsWith(`cells.${cell.id}.`));
  if (advisory) return { kind: "warning", label: "WARNING" };
  if (cell.balancing) return { kind: "balancing", label: "BALANCING" };
  return { kind: "normal", label: "NORMAL" };
}

/** Max minus min of the reported voltages of cells still in the string; null if fewer than 2. */
export function voltageSpread(cells = []) {
  const v = cells.filter((c) => !c.bypassed && typeof c.voltage === "number" && Number.isFinite(c.voltage))
    .map((c) => c.voltage);
  return v.length < 2 ? null : Math.max(...v) - Math.min(...v);
}

export function toPoint(p) {
  const pt = { t: Date.parse(p.timestamp), seq: p.seq ?? null, pv: p.pack_voltage ?? null, i: p.pack_current ?? null };
  for (const c of p.cells ?? []) {
    pt[`v${c.id}`] = c.voltage ?? null;
    pt[`t${c.id}`] = c.temperature ?? null;
    pt[`s${c.id}`] = c.soh ?? null;
  }
  return pt;
}

export function eventKey(e) {
  return `${e.timestamp}|${e.kind}|${e.cell ?? ""}|${e.detail ?? ""}`;
}

/** Merge event lists newest first, without duplicates. */
export function mergeEvents(a, b, max = 200) {
  const seen = new Set();
  const out = [];
  for (const e of [...a, ...b].sort((x, y) => (x.timestamp < y.timestamp ? 1 : x.timestamp > y.timestamp ? -1 : 0))) {
    const k = eventKey(e);
    if (!seen.has(k)) {
      seen.add(k);
      out.push(e);
    }
  }
  return out.slice(0, max);
}
