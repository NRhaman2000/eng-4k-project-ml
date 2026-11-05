import BalancingPanel from "./components/BalancingPanel.jsx";
import CellCard from "./components/CellCard.jsx";
import Charts from "./components/Charts.jsx";
import FaultPanel from "./components/FaultPanel.jsx";
import HistoryTable from "./components/HistoryTable.jsx";
import PackSummary from "./components/PackSummary.jsx";
import StatusBar from "./components/StatusBar.jsx";
import { useNow, useTelemetry } from "./hooks/useTelemetry.js";
import "./dashboard.css";

export default function App() {
  const { packet, status, events, history, wsState, lastReceivedAt } = useTelemetry();
  const now = useNow(1000);

  return (
    <main className="dash">
      <h1>Fault-Tolerant Active BMS Dashboard</h1>
      <p className="muted small">Monitoring only. All protection decisions are made by the BMS firmware.</p>
      <StatusBar packet={packet} status={status} wsState={wsState} lastReceivedAt={lastReceivedAt} now={now} />
      {!packet ? (
        <h2 className="waiting">Waiting for BMS telemetry…</h2>
      ) : (
        <>
          <PackSummary packet={packet} />
          <h2>Cell Telemetry</h2>
          <div className="cells">
            {(packet.cells ?? []).map((c) => <CellCard key={c.id} cell={c} packet={packet} />)}
          </div>
          <div className="two-col">
            <FaultPanel packet={packet} events={events} />
            <BalancingPanel packet={packet} events={events} />
          </div>
          <Charts history={history} />
        </>
      )}
      <HistoryTable />
    </main>
  );
}
