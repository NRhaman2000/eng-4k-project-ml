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


const tableHeader = {
  border: "1px solid #ddd",
  padding: "10px",
  textAlign: "left",
  background: "#f3f4f6",
};

const tableCell = {
  border: "1px solid #ddd",
  padding: "10px",
};


function App() {
  const [telemetry, setTelemetry] = useState(null);
  const [chartHistory, setChartHistory] = useState([]);
  const [historyRows, setHistoryRows] = useState([]);

  useEffect(() => {
    const ws = new WebSocket("ws://127.0.0.1:8000/ws");

    ws.onopen = () => {
      console.log("WebSocket connected");
    };

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);

      setTelemetry(data);

      setChartHistory((prev) => [
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

    ws.onclose = () => {
      console.log("WebSocket disconnected");
    };

    const loadHistory = async () => {
      try {
        const response = await fetch(
          "http://127.0.0.1:8000/api/history?limit=20"
        );

        const data = await response.json();

        setHistoryRows(data);
      } catch (error) {
        console.error("Failed to load history:", error);
      }
    };

    loadHistory();

    const historyInterval = setInterval(loadHistory, 5000);

    return () => {
      ws.close();
      clearInterval(historyInterval);
    };
  }, []);

  if (!telemetry) {
    return (
      <div
        style={{
          padding: "40px",
          fontFamily: "Arial, sans-serif",
        }}
      >
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
      <h1
        style={{
          marginBottom: "24px",
        }}
      >
        Fault-Tolerant Active BMS Dashboard
      </h1>

      <div
        style={{
          display: "flex",
          gap: "24px",
          flexWrap: "wrap",
          marginBottom: "30px",
        }}
      >
        <div>
          <strong>System Status:</strong>{" "}
          {telemetry.system_state}
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
<span
  style={{
    color: telemetry.fault.active ? "red" : "inherit",
    fontWeight: telemetry.fault.active ? "bold" : "normal",
  }}
>
  {telemetry.fault.active
    ? `${telemetry.fault.type} on Cell ${telemetry.fault.cell}`
    : "No active fault"}
</span>
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
  border:
    telemetry.fault.active &&
    telemetry.fault.cell === cell.id
      ? "3px solid red"
      : "1px solid #ccc",
  borderRadius: "12px",
  padding: "20px",
  background:
    telemetry.fault.active &&
    telemetry.fault.cell === cell.id
      ? "#ffe5e5"
      : "white",
}}
          >
            <h3>Cell {cell.id}</h3>

            <p>
              Voltage:{" "}
              <strong>{cell.voltage.toFixed(3)} V</strong>
            </p>

            <p>
              Temperature:{" "}
              <strong>
                {cell.temperature.toFixed(1)} °C
              </strong>
            </p>

            <p>
              State of Health:{" "}
              <strong>{cell.soh.toFixed(1)}%</strong>
            </p>
          </div>
        ))}
      </div>

      <h2>Real-Time Cell Voltage</h2>

      <div
        style={{
          width: "100%",
          height: "400px",
          marginBottom: "50px",
        }}
      >
        <ResponsiveContainer>
          <LineChart data={chartHistory}>
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

      <h2>Historical Telemetry</h2>

      <div
        style={{
          overflowX: "auto",
          marginBottom: "40px",
        }}
      >
        <table
          style={{
            width: "100%",
            borderCollapse: "collapse",
            background: "white",
          }}
        >
          <thead>
            <tr>
              <th style={tableHeader}>Time</th>
              <th style={tableHeader}>Pack V</th>
              <th style={tableHeader}>Current</th>
              <th style={tableHeader}>Cell 1</th>
              <th style={tableHeader}>Cell 2</th>
              <th style={tableHeader}>Cell 3</th>
              <th style={tableHeader}>Cell 4</th>
              <th style={tableHeader}>Balancing</th>
              <th style={tableHeader}>Fault</th>
              <th style={tableHeader}>State</th>
            </tr>
          </thead>

          <tbody>
            {historyRows.length === 0 ? (
              <tr>
                <td
                  colSpan="10"
                  style={{
                    ...tableCell,
                    textAlign: "center",
                  }}
                >
                  No historical telemetry available.
                </td>
              </tr>
            ) : (
              historyRows.map((row) => (
                <tr key={row.id}>
                  <td style={tableCell}>
                    {new Date(
                      row.timestamp
                    ).toLocaleTimeString()}
                  </td>

                  <td style={tableCell}>
                    {row.pack_voltage.toFixed(3)} V
                  </td>

                  <td style={tableCell}>
                    {row.pack_current.toFixed(2)} A
                  </td>

                  <td style={tableCell}>
                    {row.cell1_voltage.toFixed(3)} V
                  </td>

                  <td style={tableCell}>
                    {row.cell2_voltage.toFixed(3)} V
                  </td>

                  <td style={tableCell}>
                    {row.cell3_voltage.toFixed(3)} V
                  </td>

                  <td style={tableCell}>
                    {row.cell4_voltage.toFixed(3)} V
                  </td>

                  <td style={tableCell}>
                    {row.balancing ? "ON" : "OFF"}
                  </td>

                  <td style={tableCell}>
                    {row.fault_active
                      ? row.fault_type || "Active"
                      : "None"}
                  </td>

                  <td style={tableCell}>
                    {row.system_state}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default App;