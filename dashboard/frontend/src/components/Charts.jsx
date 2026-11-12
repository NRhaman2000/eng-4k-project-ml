import { useState } from "react";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { CELL_COLORS } from "../lib/telemetry.js";

const WINDOWS = [
  { label: "30 s", ms: 30_000 },
  { label: "1 min", ms: 60_000 },
  { label: "2 min", ms: 120_000 },
  { label: "5 min", ms: 300_000 },
];

const clock = (t) => new Date(t).toLocaleTimeString();

function Chart({ title, data, lines, unit, domain }) {
  return (
    <figure className="chart">
      <figcaption>{title}</figcaption>
      <div className="chart-box">
        <ResponsiveContainer>
          <LineChart data={data} margin={{ top: 8, right: 16, bottom: 4, left: 4 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
            <XAxis dataKey="t" type="number" domain={["dataMin", "dataMax"]} tickFormatter={clock} minTickGap={40} />
            <YAxis domain={domain} unit={` ${unit}`} width={72} />
            <Tooltip labelFormatter={clock} formatter={(v) => (v == null ? "N/A" : `${v} ${unit}`)} />
            <Legend />
            {lines.map((l) => (
              <Line key={l.key} dataKey={l.key} name={l.name} stroke={l.color} dot={false}
                    isAnimationActive={false} connectNulls={false} />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </figure>
  );
}

const cells = (prefix) => [1, 2, 3, 4].map((n) => ({ key: `${prefix}${n}`, name: `Cell ${n}`, color: CELL_COLORS[n - 1] }));

export default function Charts({ history }) {
  const [windowMs, setWindowMs] = useState(60_000);
  const lastT = history.length ? history[history.length - 1].t : 0;
  const data = history.filter((p) => p.t >= lastT - windowMs);
  const hasSoh = data.some((p) => [1, 2, 3, 4].some((n) => p[`s${n}`] != null));
  return (
    <section className="panel" aria-label="Real-time charts">
      <div className="chart-head">
        <h2>Real-Time Telemetry</h2>
        <div role="group" aria-label="Chart time window" className="seg">
          {WINDOWS.map((w) => (
            <button key={w.ms} type="button" aria-pressed={w.ms === windowMs} onClick={() => setWindowMs(w.ms)}>
              {w.label}
            </button>
          ))}
        </div>
      </div>
      <p className="muted small" data-testid="chart-points">{data.length} samples in window</p>
      <div className="charts">
        <Chart title="Cell voltages" data={data} lines={cells("v")} unit="V" domain={[2.8, 4.3]} />
        <Chart title="Cell temperatures" data={data} lines={cells("t")} unit="°C" domain={[20, 45]} />
        <Chart title="Pack voltage" data={data} lines={[{ key: "pv", name: "Pack", color: "#0f766e" }]} unit="V" domain={[10, 17]} />
        <Chart title="Pack current" data={data} lines={[{ key: "i", name: "Pack", color: "#be123c" }]} unit="A" domain={[-2, 2]} />
        {hasSoh && <Chart title="SoH estimates" data={data} lines={cells("s")} unit="%" domain={[70, 100]} />}
      </div>
      {!hasSoh && <p className="muted small">SoH chart hidden: no SoH estimates reported in this window.</p>}
    </section>
  );
}
