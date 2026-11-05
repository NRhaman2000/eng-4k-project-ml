import { fmtTime } from "../lib/format.js";

const KIND_CLASS = {
  FAULT_REPORTED: "fault-text", CELL_BYPASSED: "fault-text", WARNING_RAISED: "warn-text",
  INVALID_READING: "warn-text", FAULT_CLEARED: "ok-text", CELL_RESTORED: "ok-text",
};

export default function FaultPanel({ packet, events }) {
  const f = packet.fault ?? {};
  const history = events.filter((e) => !e.kind.startsWith("BALANCING_")).slice(0, 50);
  return (
    <section className="panel" aria-label="Faults and recovery">
      <h2>Faults, Isolation and Recovery</h2>
      <p className="muted small">
        Faults and isolation are reported by the BMS firmware. Warnings are dashboard display thresholds
        (advisory only). This dashboard sends no commands to the BMS.
      </p>
      <div className="fault-now">
        <p>
          Firmware fault:{" "}
          <strong className={f.active ? "fault-text" : "ok-text"}>
            {f.active ? `${f.type ?? "UNSPECIFIED"}${f.cell ? ` on cell ${f.cell}` : ""}` : "None active"}
          </strong>
        </p>
        <p>
          Isolated cells:{" "}
          <strong>
            {(packet.cells ?? []).filter((c) => c.bypassed).map((c) => `Cell ${c.id}`).join(", ") || "None"}
          </strong>
        </p>
        {(packet.warnings ?? []).length > 0 && (
          <ul className="plain" aria-label="Dashboard warnings">
            {packet.warnings.map((w) => (
              <li key={`${w.code}${w.cell}`} className="warn-text">⚠ {w.message} (advisory)</li>
            ))}
          </ul>
        )}
        {(packet.invalid ?? []).length > 0 && (
          <ul className="plain" aria-label="Implausible readings">
            {packet.invalid.map((i) => (
              <li key={i.field} className="warn-text">
                {i.field} = {i.value}: {i.reason}. Shown as N/A.
              </li>
            ))}
          </ul>
        )}
      </div>
      <h3>History</h3>
      {history.length === 0 ? (
        <p className="muted">No events recorded yet.</p>
      ) : (
        <div className="table-wrap">
          <table className="table" aria-label="Fault history">
            <thead>
              <tr><th>Time</th><th>Source</th><th>Event</th><th>Cell</th><th>Detail</th></tr>
            </thead>
            <tbody>
              {history.map((e) => (
                <tr key={`${e.timestamp}${e.kind}${e.cell}${e.detail}`}>
                  <td>{fmtTime(e.timestamp)}</td>
                  <td>{e.source ?? ""}</td>
                  <td className={KIND_CLASS[e.kind]}>{e.kind}</td>
                  <td>{e.cell ?? ""}</td>
                  <td className="wrap">{e.message}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
