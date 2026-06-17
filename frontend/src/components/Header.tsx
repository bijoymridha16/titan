import type { Status, Autopilot } from "../api";

const regimeColor: Record<string, string> = {
  TREND: "#16c784", RANGE: "#4ea3ff", CRISIS: "#ea3943",
  TRANSITION: "#f7b500", CLOSED: "#7e8aa3",
};

export function Header({ status, autopilot }: { status: Status | null; autopilot: Autopilot | null }) {
  const pill = (text: string, color: string) => (
    <span style={{ background: color + "30", color, padding: "2px 10px",
      borderRadius: 12, fontSize: 12, fontWeight: 700 }}>{text}</span>
  );
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center",
      paddingBottom: 12, borderBottom: "1px solid #1f2740" }}>
      <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
        <span style={{ fontSize: 22, fontWeight: 800 }}>🛡️ TITAN</span>
        {status && pill(status.mode.toUpperCase(), "#4ea3ff")}
        {status && pill(status.sim_mode ? "🧪 SIM" : status.market_open ? "NSE OPEN" : "NSE CLOSED",
          status.market_open && !status.sim_mode ? "#16c784" : "#f7b500")}
        {autopilot?.regime && pill(`${autopilot.armed ? "🤖" : "👁"} ${autopilot.regime}`,
          regimeColor[autopilot.regime] ?? "#7e8aa3")}
      </div>
      <div style={{ fontVariantNumeric: "tabular-nums", color: "#e6e9ef" }}>
        {status?.server_time_ist ?? "—"} IST
      </div>
    </div>
  );
}
