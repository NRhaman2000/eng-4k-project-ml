import { fmt, onOff } from "../lib/format.js";

export default function PackSummary({ packet }) {
  const oc = (packet.warnings ?? []).some((w) => w.code === "PACK_OVERCURRENT");
  const f = packet.fault ?? {};
  return (
    <section className="summary" aria-label="Pack summary">
      <div>
        <span className="label">System state</span>
        <strong className={`state state-${packet.system_state}`} data-testid="system-state">{packet.system_state}</strong>
      </div>
      <div>
        <span className="label">Pack voltage</span>
        <strong>{fmt(packet.pack_voltage, 3, "V")}</strong>
      </div>
      <div>
        <span className="label">Pack current</span>
        <strong className={oc ? "warn-text" : undefined}>{fmt(packet.pack_current, 2, "A")}</strong>
      </div>
      <div>
        <span className="label">SoC (estimate)</span>
        <strong>{fmt(packet.soc, 1, "%")}</strong>
      </div>
      <div>
        <span className="label">Pack SoH (estimate)</span>
        <strong>{fmt(packet.pack_soh, 1, "%")}</strong>
      </div>
      <div>
        <span className="label">Balancing</span>
        <strong>{onOff(packet.balancing)}</strong>
      </div>
      <div>
        <span className="label">Firmware fault</span>
        <strong className={f.active ? "fault-text" : undefined} data-testid="firmware-fault">
          {f.active ? `${f.type ?? "UNSPECIFIED"}${f.cell ? ` on cell ${f.cell}` : ""}` : "None"}
        </strong>
      </div>
    </section>
  );
}
