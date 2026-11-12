import { fmt, fmtTime, NA } from "../lib/format.js";
import { voltageSpread } from "../lib/telemetry.js";

export default function BalancingPanel({ packet, events }) {
  const cells = packet.cells ?? [];
  const reported = cells.filter((c) => c.balancing != null);
  const active = cells.filter((c) => c.balancing === true).map((c) => c.id);
  const spread = voltageSpread(cells);
  const recent = events.filter((e) => e.kind.startsWith("BALANCING_")).slice(0, 8);
  return (
    <section className="panel" aria-label="Active balancing">
      <h2>Active Balancing</h2>
      <p>
        Balancing cells:{" "}
        <strong>{reported.length === 0 ? NA : active.length ? active.map((id) => `Cell ${id}`).join(", ") : "None"}</strong>
      </p>
      <p>Cell voltage spread (max − min, cells in string): <strong>{spread == null ? NA : fmt(spread * 1000, 1, "mV")}</strong></p>
      <p>Charge-transfer direction: <strong>Not reported by firmware</strong></p>
      <h3>Recent balancing activity</h3>
      {recent.length === 0 ? (
        <p className="muted">No balancing activity recorded yet.</p>
      ) : (
        <ul className="plain">
          {recent.map((e) => (
            <li key={`${e.timestamp}${e.kind}${e.cell}`}>{fmtTime(e.timestamp)} {e.message}</li>
          ))}
        </ul>
      )}
    </section>
  );
}
