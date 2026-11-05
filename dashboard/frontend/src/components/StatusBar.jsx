import { fmtAge, fmtTime } from "../lib/format.js";
import { STALE_MS } from "../lib/telemetry.js";

const WS_LABEL = { open: "Connected", connecting: "Connecting…", reconnecting: "Reconnecting…" };

export default function StatusBar({ packet, status, wsState, lastReceivedAt, now }) {
  const source = packet?.source ?? status?.source ?? null;
  const ageMs = lastReceivedAt == null ? null : now - lastReceivedAt;
  const stale = packet != null && (ageMs > STALE_MS || status?.stale === true || wsState !== "open");
  const link = wsState !== "open" ? null : status == null ? null : status.connected;
  const linkLabel = link == null ? "Unknown" : link ? "Connected" : "Disconnected";

  return (
    <section className="status" aria-label="Connection status">
      {source === "MOCK" && (
        <div className="banner banner-mock" role="note">
          SIMULATED DATA (MOCK). Values are synthetic, not measured from the battery.
        </div>
      )}
      {source === "HARDWARE" && (
        <div className="banner banner-hw" role="note">HARDWARE: live sensor data reported by the BMS.</div>
      )}
      {stale && (
        <div className="banner banner-stale" role="alert">
          STALE: last telemetry received {fmtAge(ageMs)}. Values shown are the last ones received.
        </div>
      )}
      <div className="status-row">
        <span className="status-item">
          Source: <strong className={`badge badge-${(source ?? "none").toLowerCase()}`}>{source ?? "N/A"}</strong>
        </span>
        <span className="status-item">
          Backend: <strong className={`conn conn-${wsState}`}>{WS_LABEL[wsState]}</strong>
        </span>
        <span className="status-item">
          Data link: <strong className={`conn conn-${link ? "open" : link === false ? "down" : "unknown"}`}>{linkLabel}</strong>
          {status?.port ? <span className="muted"> ({status.port})</span> : null}
        </span>
        <span className="status-item">
          Last packet: <strong>{fmtTime(packet?.timestamp)}</strong>
          <span className="muted"> {packet ? `(${fmtAge(ageMs)})` : ""}</span>
        </span>
        {status?.packets_rejected ? (
          <span className="status-item warn-text">Rejected packets: {status.packets_rejected}</span>
        ) : null}
        {status?.db_write_errors ? (
          <span className="status-item fault-text">DB write errors: {status.db_write_errors}</span>
        ) : null}
      </div>
      {status?.last_error && <div className="muted small">Last link message: {status.last_error}</div>}
    </section>
  );
}
