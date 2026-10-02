import { useEffect, useState } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";

function App() {
  const [telemetry, setTelemetry] = useState(null);
  const [history, setHistory] = useState([]);

  useEffect(() => {
    const ws = new WebSocket("ws://127.0.0.1:8000/ws");

    ws.onopen = () => {
      console.log("Connected to BMS WebSocket");
    };

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);

      setTelemetry(data);

      setHistory((prev) => [
        ...prev,
        {
          time: new Date(data.timestamp).toLocaleTimeString(),
          cell1: data.cells[0].voltage,
          cell2: data.cells[1].voltage,
          cell3: data.cells[2].voltage,
          cell4: data.cells[3].voltage,
        },
      ].slice(-30));
    };

    ws.onerror = (error) => {
      console.error("WebSocket error:", error);
    };

    return () => {
      ws.close();
    };
  }, []);

  if (!telemetry) {
    return (
      <div style={{ padding: "40px", fontFamily: "Arial" }}>
        <h2>Connecting to BMS telemetry...</h2>
      </div>
    );
  }

  return (
    <div
      style={{
        padding: "32px",
        maxWidth: "1400px",
        margin: "0 auto",
        fontFamily: "Arial, sans-serif",
      }}
    >
      <h1>Fault-Tolerant Active BMS Dashboard</h1>

      <div
        style={{
          display: "flex",
          gap: "24px",
          flexWrap: "wrap",
          marginBottom: "30px",
        }}
      >
        <div>
          <strong>System Status:</strong> {telemetry.system_state}
        </div>

        <div>
          <strong>Pack Voltage:</strong>{" "}
          {telemetry.pack_voltage.toFixed(3)} V
        </div>

        <div>
          <strong>Pack Current:</strong>{" "}
          {telemetry.pack_current.toFixed(2)} A
        </div>

        <div>
          <strong>Balancing:</strong>{" "}
          {telemetry.balancing ? "ON" : "OFF"}
        </div>

        <div>
          <strong>Fault:</strong>{" "}
          {telemetry.fault.active
            ? `${telemetry.fault.type} on Cell ${telemetry.fault.cell}`
            : "No active fault"}
        </div>
      </div>

      <h2>Cell Telemetry</h2>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(4, 1fr)",
          gap: "20px",
          marginBottom: "40px",
        }}
      >
        {telemetry.cells.map((cell) => (
          <div
            key={cell.id}
            style={{
              border: "1px solid #ccc",
              borderRadius: "12px",
              padding: "20px",
              background: "white",
            }}
          >
            <h3>Cell {cell.id}</h3>

            <p>
              Voltage: <strong>{cell.voltage.toFixed(3)} V</strong>
            </p>

            <p>
              Temperature:{" "}
              <strong>{cell.temperature.toFixed(1)} °C</strong>
            </p>

            <p>
              State of Health:{" "}
              <strong>{cell.soh.toFixed(1)}%</strong>
            </p>
          </div>
        ))}
      </div>

      <h2>Real-Time Cell Voltage</h2>

      <div style={{ width: "100%", height: "400px" }}>
        <ResponsiveContainer>
          <LineChart data={history}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="time" />
            <YAxis domain={[3.5, 3.9]} />
            <Tooltip />
            <Legend />

            <Line
              type="monotone"
              dataKey="cell1"
              name="Cell 1"
              dot={false}
            />

            <Line
              type="monotone"
              dataKey="cell2"
              name="Cell 2"
              dot={false}
            />

            <Line
              type="monotone"
              dataKey="cell3"
              name="Cell 3"
              dot={false}
            />

            <Line
              type="monotone"
              dataKey="cell4"
              name="Cell 4"
              dot={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

export default App;