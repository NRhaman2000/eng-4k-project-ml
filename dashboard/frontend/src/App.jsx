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

      setChartHistory((prev) =>
        [
          ...prev,
          {
            time: new Date(data.timestamp).toLocaleTimeString(),
            cell1: data.cells[0].voltage,
            cell2: data.cells[1].voltage,
            cell3: data.cells[2].voltage,
            cell4: data.cells[3].voltage,
          },
        ].slice(-30)
      );
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
          marginBottom: "28px",
        }}
      >
        Fault-Tolerant Active BMS Dashboard
      </h1>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(5, minmax(170px, 1fr))",
          gap: "20px",
          marginBottom: "36px",
          alignItems: "start",
        }}
      >
        <div>
          <strong>System Status:</strong>
          <div
            style={{
              marginTop: "6px",
              minHeight: "24px",
              fontWeight:
                telemetry.system_state === "FAULT_DETECTED"
                  ? "bold"
                  : "normal",
              color:
                telemetry.system_state === "FAULT_DETECTED"
                  ? "red"
                  : "inherit",
            }}
          >
            {telemetry.system_state}
          </div>
        </div>

        <div>
          <strong>Pack Voltage:</strong>
          <div
            style={{
              marginTop: "6px",
              minHeight: "24px",
            }}
          >
            {telemetry.pack_voltage.toFixed(3)} V
          </div>
        </div>

        <div>
          <strong>Pack Current:</strong>
          <div
            style={{
              marginTop: "6px",
              minHeight: "24px",
              color:
                telemetry.fault.active &&
                telemetry.fault.type === "OVERCURRENT"
                  ? "red"
                  : "inherit",
              fontWeight:
                telemetry.fault.active &&
                telemetry.fault.type === "OVERCURRENT"
                  ? "bold"
                  : "normal",
            }}
          >
            {telemetry.pack_current.toFixed(2)} A
          </div>
        </div>

        <div>
          <strong>Balancing:</strong>
          <div
            style={{
              marginTop: "6px",
              minHeight: "24px",
            }}
          >
            {telemetry.balancing ? "ON" : "OFF"}
          </div>
        </div>

        <div>
          <strong>Fault:</strong>
          <div
            style={{
              marginTop: "6px",
              minHeight: "48px",
              color: telemetry.fault.active ? "red" : "inherit",
              fontWeight: telemetry.fault.active ? "bold" : "normal",
            }}
          >
            {telemetry.fault.active
              ? telemetry.fault.cell
                ? `${telemetry.fault.type} on Cell ${telemetry.fault.cell}`
                : telemetry.fault.type
              : "No active fault"}
          </div>
        </div>
      </div>

      <h2
        style={{
          textAlign: "center",
          marginBottom: "20px",
        }}
      >
        Cell Telemetry
      </h2>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(4, 1fr)",
          gap: "20px",
          marginBottom: "46px",
        }}
      >
        {telemetry.cells.map((cell) => {
          const isFaultedCell =
            telemetry.fault.active &&
            telemetry.fault.cell === cell.id;

          return (
            <div
              key={cell.id}
              style={{
                border: isFaultedCell
                  ? "3px solid red"
                  : "1px solid #ccc",
                borderRadius: "12px",
                padding: "20px",
                minHeight: "200px",
                background: isFaultedCell
                  ? "#ffe5e5"
                  : "white",
                display: "flex",
                flexDirection: "column",
                justifyContent: "center",
              }}
            >
              <h3
                style={{
                  textAlign: "center",
                  marginBottom: "20px",
                }}
              >
                Cell {cell.id}
              </h3>

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
          );
        })}
      </div>

      <h2
        style={{
          textAlign: "center",
          marginBottom: "20px",
        }}
      >
        Real-Time Cell Voltage
      </h2>

      <div
        style={{
          width: "100%",
          height: "420px",
          marginBottom: "50px",
        }}
      >
        <ResponsiveContainer>
          <LineChart data={chartHistory}>
            <CartesianGrid strokeDasharray="3 3" />

            <XAxis dataKey="time" />

            <YAxis
              domain={[2.2, 3.9]}
              tickCount={6}
            />

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

      <h2
        style={{
          textAlign: "center",
          marginBottom: "20px",
        }}
      >
        Historical Telemetry
      </h2>

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

                  <td
                    style={{
                      ...tableCell,
                      color:
                        row.fault_active &&
                        row.fault_type === "OVERCURRENT"
                          ? "red"
                          : "inherit",
                      fontWeight:
                        row.fault_active &&
                        row.fault_type === "OVERCURRENT"
                          ? "bold"
                          : "normal",
                    }}
                  >
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

                  <td
                    style={{
                      ...tableCell,
                      color: row.fault_active
                        ? "red"
                        : "inherit",
                      fontWeight: row.fault_active
                        ? "bold"
                        : "normal",
                    }}
                  >
                    {row.fault_active
                      ? row.fault_cell
                        ? `${row.fault_type} / Cell ${row.fault_cell}`
                        : row.fault_type
                      : "None"}
                  </td>

                  <td
                    style={{
                      ...tableCell,
                      color:
                        row.system_state === "FAULT_DETECTED"
                          ? "red"
                          : "inherit",
                      fontWeight:
                        row.system_state === "FAULT_DETECTED"
                          ? "bold"
                          : "normal",
                    }}
                  >
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