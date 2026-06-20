import type { Status } from "../api";

export function KpiStrip({ status }: { status: Status | null }) {
  const card = (label: string, value: string, tone = "#7e8aa3") => (
    <div style={{ background: "#131826", border: "1px solid #1f2740", borderRadius: 10,
      padding: "12px 14px", borderLeft: `3px solid ${tone}` }}>
      <div style={{ color: "#7e8aa3", fontSize: 11, textTransform: "uppercase",
        letterSpacing: "0.06em", fontWeight: 600 }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 800, marginTop: 4 }}>{value}</div>
    </div>
  );
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 10, marginTop: 12 }}>
      {card("Capital (₹)", status ? status.capital.toLocaleString() : "—", "#4ea3ff")}
      {card("Mode", status?.mode.toUpperCase() ?? "—", "#4ea3ff")}
      {card("Market", status ? (status.market_open ? "OPEN" : "CLOSED") : "—",
        status?.market_open ? "#16c784" : "#ea3943")}
      {card("Clock", status?.sim_mode ? "SIM" : "REAL", status?.sim_mode ? "#f7b500" : "#16c784")}
      {card("Kill", status?.kill_switch ? "🛑 ON" : "🟢 OFF", status?.kill_switch ? "#ea3943" : "#16c784")}
    </div>
  );
}
