import { useEffect, useState } from "react";
import { api, type Status, type Autopilot } from "./api";
import { Header } from "./components/Header";
import { KpiStrip } from "./components/KpiStrip";
import { Chart } from "./components/Chart";

// Foundation shell for the React rebuild (D3). Polls status/autopilot and renders
// the header + KPI strip + a TradingView-Lightweight-Charts candlestick with trade
// markers. Remaining tabs (Journal, Strategies, Analytics, Risk) are the parity
// checklist in frontend/README.md.
export function App() {
  const [status, setStatus] = useState<Status | null>(null);
  const [autopilot, setAutopilot] = useState<Autopilot | null>(null);
  const [symbol, setSymbol] = useState("NIFTY");

  useEffect(() => {
    const tick = async () => {
      try {
        setStatus(await api.status());
        setAutopilot(await api.autopilot());
      } catch { /* backend not up yet */ }
    };
    tick();
    const id = setInterval(tick, 5000);
    return () => clearInterval(id);
  }, []);

  return (
    <div style={{ padding: 16, maxWidth: 1500, margin: "0 auto" }}>
      <Header status={status} autopilot={autopilot} />
      <KpiStrip status={status} />
      <div style={{ margin: "12px 0", display: "flex", gap: 8 }}>
        {["NIFTY", "SENSEX", "BANKNIFTY", "RELIANCE"].map((s) => (
          <button key={s} onClick={() => setSymbol(s)}
            style={{ background: s === symbol ? "#1a2032" : "transparent",
                     color: "#e6e9ef", border: "1px solid #1f2740",
                     borderRadius: 6, padding: "4px 12px", cursor: "pointer" }}>
            {s}
          </button>
        ))}
      </div>
      <Chart symbol={symbol} />
    </div>
  );
}
