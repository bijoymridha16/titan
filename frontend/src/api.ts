// Thin typed client over the FastAPI control plane.
// In dev, Vite proxies /api → :8000 (see vite.config.ts).
const BASE = "/api";

async function get<T>(path: string): Promise<T> {
  const r = await fetch(`${BASE}${path}`);
  if (!r.ok) throw new Error(`${path} → ${r.status}`);
  return r.json() as Promise<T>;
}

export interface Status {
  mode: string; sim_mode: boolean; market_open: boolean;
  kill_switch: boolean; capital: number; server_time_ist: string;
  limits: Record<string, number>;
}
export interface Autopilot {
  armed: boolean; regime: string | null; regime_reason: string | null;
  enabled_now: string[]; validated_strategies: string[];
}
export interface Bar { ts: string; o: number; h: number; l: number; c: number; v: number; }
export interface Trade {
  id: string; strategy: string; symbol: string; side: string; qty: number;
  entry_ts: string; entry_price: number; exit_ts: string | null;
  exit_price: number | null; pnl: number | null; regime: string | null;
  stop_loss: number | null; target: number | null;
}

export const api = {
  status: () => get<Status>("/status"),
  autopilot: () => get<Autopilot>("/autopilot"),
  bars: (symbol: string, tf = "5m", n = 200) =>
    get<Bar[]>(`/data/bars?symbol=${symbol}&tf=${tf}&n=${n}`),
  trades: (limit = 100) => get<Trade[]>(`/data/trades?limit=${limit}`),
  positions: () => get<Trade[]>("/data/positions"),
  leaderboard: () => get<any[]>("/data/leaderboard"),
  arm: () => fetch(`${BASE}/autopilot/arm`, { method: "POST" }),
  disarm: () => fetch(`${BASE}/autopilot/disarm`, { method: "POST" }),
  kill: () => fetch(`${BASE}/kill?reason=ui`, { method: "POST" }),
};
