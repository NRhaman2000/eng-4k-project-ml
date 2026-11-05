import { useEffect, useState } from "react";
import { fmt, fmtTime, onOff } from "../lib/format.js";
import { BACKEND } from "../lib/telemetry.js";

export default function HistoryTable({ backend = BACKEND }) {
  const [rows, setRows] = useState([]);
  const [error, setError] = useState(null);

  useEffect(() => {
    let stopped = false;
    const load = () =>
      fetch(`${backend}/api/history?limit=20`)
        .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
        .then((d) => { if (!stopped) { setRows(Array.isArray(d) ? d : []); setError(null); } })
        .catch((e) => !stopped && setError(e.message));
    load();
    const id = setInterval(load, 5000);
    return () => { stopped = true; clearInterval(id); };
  }, [backend]);

  return (
    <section className="panel" aria-label="Historical telemetry">
      <h2>Historical Telemetry (SQLite)</h2>
      {error && <p className="warn-text small">History unavailable: {error}</p>}
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Time</th><th>Source</th><th>Pack V</th><th>Pack I</th>
              <th>Cell 1</th><th>Cell 2</th><th>Cell 3</th><th>Cell 4</th>
              <th>Balancing</th><th>Fault</th><th>State</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr><td colSpan={11} className="muted">No history yet.</td></tr>
            ) : (
              rows.map((r) => (
                <tr key={r.id}>
                  <td>{fmtTime(r.timestamp)}</td>
                  <td>{r.source ?? ""}</td>
                  <td>{fmt(r.pack_voltage, 3, "V")}</td>
                  <td>{fmt(r.pack_current, 2, "A")}</td>
                  {[1, 2, 3, 4].map((n) => (
                    <td key={n} className={r[`cell${n}_bypassed`] ? "muted" : undefined}>
                      {fmt(r[`cell${n}_voltage`], 3, "V")}{r[`cell${n}_bypassed`] ? " (bypassed)" : ""}
                    </td>
                  ))}
                  <td>{onOff(r.balancing == null ? null : !!r.balancing)}</td>
                  <td className={r.fault_active ? "fault-text" : undefined}>
                    {r.fault_active ? `${r.fault_type ?? "FAULT"}${r.fault_cell ? ` / Cell ${r.fault_cell}` : ""}` : "None"}
                  </td>
                  <td>{r.system_state}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
