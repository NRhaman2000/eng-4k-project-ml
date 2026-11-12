import { fmt, NA, onOff } from "../lib/format.js";
import { cellCondition, cellWarnings, invalidFor } from "../lib/telemetry.js";

function Reading({ label, value, invalid }) {
  return (
    <p>
      {label}: <strong title={invalid ? `raw ${invalid.value}: ${invalid.reason}` : undefined}>{value}</strong>
      {invalid && <span className="warn-text small"> (sensor value not plausible)</span>}
    </p>
  );
}

export default function CellCard({ cell, packet }) {
  const cond = cellCondition(cell, packet);
  const warnings = cellWarnings(packet, cell.id);
  const inv = (f) => invalidFor(packet, `cells.${cell.id}.${f}`);
  const bypass = cell.bypassed === true ? "BYPASSED" : cell.bypassed === false ? "In string" : NA;
  return (
    <article className={`cell cell-${cond.kind}`} data-testid={`cell-${cell.id}`} data-condition={cond.kind}>
      <h3>
        Cell {cell.id} <span className={`tag tag-${cond.kind}`}>{cond.label}</span>
      </h3>
      <Reading label="Voltage" value={fmt(cell.voltage, 3, "V")} invalid={inv("voltage")} />
      <Reading label="Temperature" value={fmt(cell.temperature, 1, "°C")} invalid={inv("temperature")} />
      <Reading label="SoH (estimate)" value={fmt(cell.soh, 1, "%")} invalid={inv("soh")} />
      <p>Balancing: <strong>{onOff(cell.balancing)}</strong></p>
      <p>Bypass: <strong>{bypass}</strong></p>
      <p>
        Firmware fault: <strong className={cell.fault ? "fault-text" : undefined}>{cell.fault ?? "None"}</strong>
      </p>
      {warnings.map((w) => (
        <p key={w.code} className="warn-text small">⚠ {w.message} (dashboard advisory)</p>
      ))}
    </article>
  );
}
