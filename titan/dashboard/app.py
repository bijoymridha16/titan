"""TITAN — live market terminal UI.

Dark theme, ticker tape, candlestick charts, market clock, big P&L.
Reads:
  - Redis: titan:ltp:<symbol>, titan:heartbeat:*, titan:kill, titan:strategies:enabled
  - Postgres: ohlcv, trades, equity_curve, risk_events, instruments
"""
from __future__ import annotations

import os
import time as _time
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
import pandas as pd
import plotly.graph_objects as go
import redis
import streamlit as st
from sqlalchemy import create_engine, text
from streamlit_autorefresh import st_autorefresh

from titan import clock
from titan.config import settings
from titan.decision.selector import REGIME_CANDIDATES
from titan.strategies.registry import BASE_STRATEGIES, KILLED_STRATEGIES

IST = ZoneInfo("Asia/Kolkata")

# human descriptions for every registered strategy (falls back to the name)
STRAT_DESC = {
    "orb": "Opening Range Breakout — first breakout of the 09:15–09:30 range.",
    "orb_confirmed": "ORB + confirmation — breakout needs volume expansion & EMA-slope agreement.",
    "vwap_revert": "VWAP Mean Reversion — fades >2σ deviations from session VWAP.",
    "vwap_rsi": "VWAP-revert + RSI gate — wider 2.5×ATR stop, fades only when RSI is exhausted.",
    "supertrend_adx": "Supertrend + ADX — trend-follows Supertrend flips when ADX>20.",
    "ma_cross": "MA Crossover — EMA(9/21) crossover with ATR stop.",
    "donchian": "Donchian Breakout — breaks the prior N-bar channel.",
    "momentum": "Momentum ROC — enters when rate-of-change flips sign.",
    "rsi_revert": "RSI Reversion — fades RSI crosses of oversold/overbought.",
    "bollinger_revert": "Bollinger Reversion — fades band touches back to the mid.",
    "bb_squeeze": "Bollinger Squeeze — breakout from a low-volatility compression.",
    "tsmom": "Time-Series Momentum (KILLED) — walk-forward FAILED; disabled by guard.",
}
API_BASE = os.getenv("TITAN_API_BASE", "http://localhost:8000")

st.set_page_config(
    page_title="TITAN · live",
    layout="wide",
    page_icon="🛡️",
    initial_sidebar_state="collapsed",
)

# ─────────────────────────── theme ───────────────────────────
st.markdown("""
<style>
:root {
  --bg: #0b0f17; --panel: #131826; --panel2: #1a2032; --border: #1f2740;
  --txt: #e6e9ef; --mute: #7e8aa3; --accent: #4ea3ff;
  --up: #16c784; --dn: #ea3943; --warn: #f7b500;
}
.stApp { background: var(--bg); color: var(--txt); }
[data-testid="stHeader"] { background: transparent; }
[data-testid="stSidebar"] { background: var(--panel); border-right: 1px solid var(--border); }
div.block-container { padding-top: 0.5rem; padding-bottom: 1rem; max-width: 100%; }

h1, h2, h3, h4 { color: var(--txt); }
.stTabs [data-baseweb="tab-list"] {
  gap: 2px; border-bottom: 1px solid var(--border);
}
.stTabs [data-baseweb="tab"] {
  padding: 8px 18px; background: transparent; color: var(--mute);
  border-radius: 0; font-weight: 600;
}
.stTabs [aria-selected="true"] {
  background: var(--panel); color: var(--txt);
  border-bottom: 2px solid var(--accent);
}

[data-testid="stMetric"] {
  background: var(--panel); border: 1px solid var(--border);
  border-radius: 8px; padding: 10px 14px;
}
[data-testid="stMetricValue"] {
  font-size: 1.5rem; font-weight: 700; color: var(--txt);
}
[data-testid="stMetricLabel"] {
  color: var(--mute); font-size: 0.75rem; text-transform: uppercase;
  letter-spacing: 0.04em;
}

/* ticker tape */
.tape-wrap {
  background: var(--panel); border: 1px solid var(--border);
  border-radius: 8px; padding: 10px 14px; overflow: hidden;
  white-space: nowrap;
}
.tape-row {
  display: inline-flex; gap: 30px; align-items: center;
  animation: marquee 50s linear infinite;
}
@keyframes marquee {
  0%   { transform: translateX(0%); }
  100% { transform: translateX(-50%); }
}
.tape-item { display: inline-flex; gap: 10px; align-items: center; font-weight: 600; }
.tape-sym  { color: var(--txt); font-size: 0.95rem; }
.tape-px   { font-variant-numeric: tabular-nums; font-size: 0.95rem; }
.tape-chg  { font-size: 0.8rem; padding: 1px 6px; border-radius: 4px; }
.up { color: var(--up); }
.dn { color: var(--dn); }
.bg-up { background: rgba(22,199,132,0.15); color: var(--up); }
.bg-dn { background: rgba(234,57,67,0.15); color: var(--dn); }
.bg-warn { background: rgba(247,181,0,0.15); color: var(--warn); }

.card {
  background: var(--panel); border: 1px solid var(--border);
  border-radius: 8px; padding: 14px;
}

.pill {
  display: inline-block; padding: 2px 10px; border-radius: 12px;
  font-size: 0.72rem; font-weight: 700; letter-spacing: 0.04em;
}
.pill-open  { background: rgba(22,199,132,0.18); color: var(--up); }
.pill-close { background: rgba(234,57,67,0.18); color: var(--dn); }
.pill-pre   { background: rgba(247,181,0,0.18); color: var(--warn); }
.pill-paper { background: rgba(78,163,255,0.18); color: var(--accent); }
.pill-live  { background: rgba(234,57,67,0.22); color: var(--dn); }

.dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%;
       margin-right: 6px; vertical-align: middle; }
.dot-on  { background: var(--up); box-shadow: 0 0 6px var(--up); }
.dot-off { background: var(--dn); }
.dot-warn { background: var(--warn); }

.big-px {
  font-size: 2.2rem; font-weight: 700; font-variant-numeric: tabular-nums;
}
.muted { color: var(--mute); font-size: 0.78rem; }
.divider-soft { height: 1px; background: var(--border); margin: 12px 0; }
hr { border-color: var(--border) !important; }
.stProgress > div > div > div { background: var(--accent); }
.market-clock {
  font-variant-numeric: tabular-nums; font-size: 1.05rem;
  font-weight: 600; color: var(--txt);
}

/* tighter metric cards */
[data-testid="stMetricValue"] { font-size: 1.25rem !important; line-height: 1.2; }
[data-testid="stMetricDelta"] { font-size: 0.72rem !important; color: var(--mute) !important; }
[data-testid="stMetricDelta"] svg { display: none; }

/* dark selectbox */
[data-baseweb="select"] > div {
  background: var(--panel2) !important;
  border: 1px solid var(--border) !important;
  color: var(--txt) !important;
}
[data-baseweb="select"] svg { color: var(--mute) !important; }
[data-baseweb="popover"] { background: var(--panel2) !important; }
[data-baseweb="menu"] { background: var(--panel2) !important; color: var(--txt) !important; }
[data-baseweb="option"] { color: var(--txt) !important; }
[data-baseweb="option"]:hover { background: var(--panel) !important; }

/* slider in accent blue, not pink */
[data-baseweb="slider"] [role="slider"] {
  background: var(--accent) !important;
  border-color: var(--accent) !important;
}
[data-baseweb="slider"] > div > div > div { background: var(--accent) !important; }
[data-baseweb="slider"] div[style*="background"] { background: var(--accent) !important; }
[data-testid="stSlider"] [data-baseweb="slider"] > div > div { background: #2a3450 !important; }
[data-testid="stSlider"] label, [data-testid="stSlider"] span { color: var(--mute) !important; }

/* buttons */
.stButton button {
  background: var(--panel2); color: var(--txt);
  border: 1px solid var(--border); border-radius: 6px;
}
.stButton button:hover { border-color: var(--accent); }
.stButton button[kind="primary"] {
  background: #c0202c; border-color: #c0202c; color: white;
}

/* tabs spacing */
.stTabs { margin-top: 4px; }

.demo-badge {
  display: inline-block; background: rgba(247,181,0,0.15); color: var(--warn);
  padding: 2px 10px; border-radius: 12px; font-size: 0.72rem;
  font-weight: 700; letter-spacing: 0.04em; margin-left: 8px;
}

/* ── upgraded KPI strip ── */
.kpi-strip {
  display: grid; grid-template-columns: repeat(7, 1fr); gap: 10px;
  margin: 4px 0 10px 0;
}
@media (max-width: 1500px) { .kpi-strip { grid-template-columns: repeat(4, 1fr); } }
.kpi {
  background: var(--panel); border: 1px solid var(--border);
  border-radius: 10px; padding: 12px 14px; position: relative; overflow: hidden;
}
.kpi::before {
  content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 3px;
  background: var(--border);
}
.kpi.k-up::before   { background: var(--up); }
.kpi.k-dn::before   { background: var(--dn); }
.kpi.k-warn::before { background: var(--warn); }
.kpi.k-accent::before { background: var(--accent); }
.kpi-label {
  color: var(--mute); font-size: 0.68rem; text-transform: uppercase;
  letter-spacing: 0.06em; font-weight: 600; margin-bottom: 4px;
}
.kpi-val {
  font-size: 1.45rem; font-weight: 800; font-variant-numeric: tabular-nums;
  line-height: 1.1;
}
.kpi-val.k-up { color: var(--up); } .kpi-val.k-dn { color: var(--dn); }
.kpi-val.k-warn { color: var(--warn); } .kpi-val.k-accent { color: var(--accent); }
.kpi-sub { color: var(--mute); font-size: 0.72rem; margin-top: 3px;
           font-variant-numeric: tabular-nums; }
.kpi-bar { height: 5px; border-radius: 3px; background: #232b42;
           margin-top: 8px; overflow: hidden; }
.kpi-bar > span { display: block; height: 100%; border-radius: 3px; }
.bar-up > span   { background: linear-gradient(90deg,#0e9f6e,var(--up)); }
.bar-dn > span   { background: linear-gradient(90deg,#b32531,var(--dn)); }
.bar-warn > span { background: linear-gradient(90deg,#b98700,var(--warn)); }

/* regime pill colours */
.pill-trend      { background: rgba(22,199,132,0.18); color: var(--up); }
.pill-range      { background: rgba(78,163,255,0.18); color: var(--accent); }
.pill-crisis     { background: rgba(234,57,67,0.22); color: var(--dn); }
.pill-transition { background: rgba(247,181,0,0.18); color: var(--warn); }
.pill-neutral    { background: rgba(126,138,163,0.18); color: var(--mute); }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────── conns ───────────────────────────
@st.cache_resource
def _eng(): return create_engine(settings.db_url, pool_pre_ping=True)

@st.cache_resource
def _r(): return redis.from_url(settings.redis_url, decode_responses=True)

eng = _eng(); r = _r()

def q(sql, **p):
    try:
        with eng.connect() as cx:
            return pd.read_sql(text(sql), cx, params=p)
    except Exception:
        return pd.DataFrame()

def api(method, path, **kw):
    try:
        with httpx.Client(timeout=3.0) as c:
            return c.request(method, f"{API_BASE}{path}", **kw)
    except Exception:
        return None

# auto-refresh every 5s (live feel)
st_autorefresh(interval=5_000, key="refresh")


# ─────────────────────────── market state ───────────────────────────
def market_phase(now: datetime) -> tuple[str, str]:
    t = now.timetz().replace(tzinfo=None)
    if now.weekday() >= 5:
        return ("CLOSED", "pill-close")
    if t < time(9, 0):
        return ("PRE-OPEN", "pill-pre")
    if t < time(9, 15):
        return ("OPENING", "pill-pre")
    if t < time(15, 30):
        return ("OPEN", "pill-open")
    if t < time(16, 0):
        return ("POST-CLOSE", "pill-pre")
    return ("CLOSED", "pill-close")


_SYNTH_ANCHORS = {
    "NIFTY": 24_500.0, "BANKNIFTY": 52_000.0, "FINNIFTY": 24_000.0,
    "RELIANCE": 2_950.0, "HDFCBANK": 1_680.0, "ICICIBANK": 1_280.0,
}
_TF_MIN = {"1m": 1, "3m": 3, "5m": 5, "15m": 15}

def _synthetic_bars(symbol: str, tf: str, n: int) -> pd.DataFrame:
    """Geometric-brownian random walk. Deterministic per (symbol, tf, day)
    so the chart doesn't shimmer on each 5s refresh."""
    import numpy as np
    anchor = _SYNTH_ANCHORS.get(symbol, 1000.0)
    today = datetime.now(IST).date().toordinal()
    seed = abs(hash((symbol, tf, today))) % (2**32)
    rng = np.random.default_rng(seed)
    vol = 0.0012  # per-bar volatility ~12 bps
    rets = rng.normal(0, vol, size=n)
    close = anchor * np.exp(np.cumsum(rets))
    spread = anchor * 0.0006
    opens = np.concatenate([[anchor], close[:-1]])
    highs = np.maximum(opens, close) + rng.uniform(0, spread, n)
    lows  = np.minimum(opens, close) - rng.uniform(0, spread, n)
    vols  = rng.integers(50_000, 200_000, n)
    minutes = _TF_MIN[tf]
    end = datetime.now(IST).replace(second=0, microsecond=0)
    end = end - timedelta(minutes=end.minute % minutes)
    idx = pd.DatetimeIndex([end - timedelta(minutes=minutes * (n - 1 - i))
                            for i in range(n)])
    return pd.DataFrame({"ts": idx, "o": opens, "h": highs, "l": lows,
                         "c": close, "v": vols})


def get_ltp_map() -> dict[str, float]:
    out = {}
    for s in settings.symbols:
        v = r.get(f"titan:ltp:{s}")
        if v:
            try: out[s] = float(v)
            except Exception: pass
    return out


def get_prev_close_map() -> dict[str, float]:
    # last bar's open of "today" or last close before today as proxy
    out: dict[str, float] = {}
    df = q("""
        SELECT DISTINCT ON (symbol) symbol, c
        FROM ohlcv WHERE timeframe='5m' AND ts < (CURRENT_DATE)::timestamptz
        ORDER BY symbol, ts DESC
    """)
    for _, row in df.iterrows():
        out[row["symbol"]] = float(row["c"])
    return out


# ─────────────────────────── topbar ───────────────────────────
now_ist = datetime.now(IST)
phase, phase_cls = market_phase(now_ist)
killed = (r.get("titan:kill") == "1")
feed_hb = r.get("titan:heartbeat:feed")
feed_alive = False
if feed_hb:
    try:
        hb_dt = datetime.fromisoformat(feed_hb)
        if hb_dt.tzinfo is None:
            hb_dt = hb_dt.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - hb_dt).total_seconds()
        feed_alive = age < 60
    except Exception:
        pass

mode_cls = "pill-live" if settings.mode == "live" else "pill-paper"
# explicit simulation flag (honest): real clock + market-hours gate unless sim is ON
_sim_flag = r.get("titan:sim:enabled")
sim_on = (_sim_flag == "1") if _sim_flag is not None else settings.sim_mode
synth_data = (r.get("titan:mode:synthetic") == "1")
market_open_real = clock.is_market_open(now_ist)
if sim_on:
    phase, phase_cls = "SIM SESSION", "pill-pre"

_extra_pills = ""
if killed:
    _extra_pills += '<span class="pill pill-close">🛑 KILL</span>'
if sim_on:
    _extra_pills += '<span class="pill bg-warn">🧪 SIMULATION · not live market</span>'
elif not market_open_real:
    _extra_pills += '<span class="pill pill-close">⏸ TRADING PAUSED · NSE CLOSED</span>'

# auto-pilot regime pill (live decision from titan/decision)
_regime = r.get("titan:regime:current")
_autopilot_armed = r.get("titan:autopilot:enabled")
if _regime:
    _rcls = {"TREND": "pill-trend", "RANGE": "pill-range", "CRISIS": "pill-crisis",
             "TRANSITION": "pill-transition"}.get(_regime, "pill-neutral")
    _ap = "🤖" if _autopilot_armed == "1" else "👁"
    _extra_pills += f'<span class="pill {_rcls}">{_ap} {_regime}</span>'

st.markdown(
    '<div style="display:flex;justify-content:space-between;align-items:center;padding:10px 4px 12px 4px;">'
    '<div style="display:flex;gap:14px;align-items:center;">'
    '<span style="font-size:1.4rem;font-weight:800;letter-spacing:0.04em;">🛡️ TITAN</span>'
    f'<span class="pill {mode_cls}">{settings.mode.upper()}</span>'
    f'<span class="pill {phase_cls}">NSE · {phase}</span>'
    f'{_extra_pills}'
    '</div>'
    f'<div style="display:flex;gap:18px;align-items:center;">'
    f'<span class="muted"><span class="dot {"dot-on" if feed_alive else "dot-off"}"></span>feed</span>'
    f'<span class="market-clock">{now_ist.strftime("%a %d %b · %I:%M:%S %p")} IST</span>'
    + (f'<span class="pill bg-warn">sim {clock.sim_session_now(now_ist).strftime("%I:%M %p")}</span>'
       if sim_on else "")
    + '</div></div>',
    unsafe_allow_html=True,
)



# ─────────────────────────── ticker tape ───────────────────────────
ltps = get_ltp_map()
prevs = get_prev_close_map()

def fmt(p: float) -> str:
    return f"{p:,.2f}"

if ltps:
    items_html = []
    for sym in settings.symbols:
        px = ltps.get(sym)
        if px is None:
            items_html.append(f"""<span class="tape-item">
                <span class="tape-sym">{sym}</span>
                <span class="tape-px muted">—</span></span>""")
            continue
        prev = prevs.get(sym)
        if prev and prev > 0:
            chg = px - prev; pct = chg / prev * 100
            cls = "up" if chg >= 0 else "dn"
            bg = "bg-up" if chg >= 0 else "bg-dn"
            arrow = "▲" if chg >= 0 else "▼"
            items_html.append(f"""<span class="tape-item">
                <span class="tape-sym">{sym}</span>
                <span class="tape-px {cls}">{fmt(px)}</span>
                <span class="tape-chg {bg}">{arrow} {chg:+.2f} ({pct:+.2f}%)</span>
            </span>""")
        else:
            items_html.append(f"""<span class="tape-item">
                <span class="tape-sym">{sym}</span>
                <span class="tape-px">{fmt(px)}</span></span>""")
    row = "".join(items_html)
    st.markdown(f'<div class="tape-wrap"><div class="tape-row">{row}{row}</div></div>',
                unsafe_allow_html=True)
else:
    st.markdown(f"""
    <div class="tape-wrap">
      <span class="muted">📡 Waiting for live ticks — feed {'idle' if feed_alive else 'offline'}.
      Market opens 09:15 IST on weekdays.</span>
    </div>
    """, unsafe_allow_html=True)


# ─────────────────────────── KPI row ───────────────────────────
def latest_equity() -> float:
    df = q("SELECT equity FROM equity_curve ORDER BY ts DESC LIMIT 1")
    return float(df["equity"].iloc[0]) if not df.empty else settings.capital

def today_pnl() -> float:
    # Authoritative sim-day realized P&L, maintained by the supervisor's risk
    # state and reset at each new sim trading day (IST). The old
    # `entry_ts::date = CURRENT_DATE` query broke under the sim clock — sim dates
    # run ahead of the server's real (UTC) date, so almost nothing matched and
    # Today P&L / daily-profit / daily-loss were stuck at 0.
    v = r.get("titan:session:realized_pnl")
    if v is not None:
        try:
            return float(v)
        except (TypeError, ValueError):
            pass
    # fallback: realized P&L for the current IST day from closed trades
    df = q("SELECT COALESCE(SUM(pnl),0) AS pnl FROM trades "
           "WHERE (exit_ts AT TIME ZONE 'Asia/Kolkata')::date "
           "= (now() AT TIME ZONE 'Asia/Kolkata')::date")
    return float(df["pnl"].iloc[0]) if not df.empty else 0.0

def open_count() -> int:
    df = q("SELECT COUNT(*) AS c FROM trades WHERE exit_ts IS NULL")
    return int(df["c"].iloc[0]) if not df.empty else 0

equity = latest_equity(); pnl = today_pnl(); n_open = open_count()
dd_pct = max(0.0, (settings.capital - equity) / settings.capital * 100)
daily_cap = settings.capital * settings.max_daily_loss_pct / 100
profit_target = settings.capital * settings.max_daily_profit_pct / 100
dd_cap = settings.capital * settings.max_drawdown_pct / 100
loss = max(0.0, -pnl)
profit = max(0.0, pnl)
profit_locked = profit_target > 0 and profit >= profit_target
loss_halted = loss >= daily_cap

def _bar(pct: float, tone: str) -> str:
    w = max(0, min(100, pct * 100))
    return f'<div class="kpi-bar bar-{tone}"><span style="width:{w:.0f}%"></span></div>'

def kpi(label, val, sub="", tone="", bar_html=""):
    klass = f"kpi {('k-'+tone) if tone else ''}"
    vclass = f"kpi-val {('k-'+tone) if tone else ''}"
    return (f'<div class="{klass}"><div class="kpi-label">{label}</div>'
            f'<div class="{vclass}">{val}</div>'
            f'{f"<div class=kpi-sub>{sub}</div>" if sub else ""}{bar_html}</div>')

eq_tone = "up" if equity >= settings.capital else "dn"
pnl_tone = "up" if pnl >= 0 else "dn"
profit_pct_frac = (profit / profit_target) if profit_target else 0
loss_pct_frac = (loss / daily_cap) if daily_cap else 0

cards = [
    kpi("Equity (₹)", f"{equity:,.0f}", f"{equity - settings.capital:+,.0f} vs start", eq_tone),
    kpi("Today P&L (₹)", f"{pnl:+,.0f}",
        ("🔒 profit locked" if profit_locked else ("⛔ loss halt" if loss_halted else "session active")),
        pnl_tone),
    kpi("Daily profit",
        f"₹{profit:,.0f}" + (" 🔒" if profit_locked else ""),
        f"target ₹{profit_target:,.0f} · {profit_pct_frac*100:.0f}%",
        "up", _bar(profit_pct_frac, "up")),
    kpi("Daily loss",
        f"₹{loss:,.0f}" + (" ⛔" if loss_halted else ""),
        f"cap ₹{daily_cap:,.0f} · {loss_pct_frac*100:.0f}%",
        "dn", _bar(loss_pct_frac, "dn")),
    kpi("Drawdown", f"{dd_pct:.2f}%", f"cap {settings.max_drawdown_pct:.0f}%",
        "warn" if dd_pct > settings.max_drawdown_pct * 0.6 else "",
        _bar((settings.capital - equity) / dd_cap if dd_cap else 0, "warn")),
    kpi("Open positions", str(n_open), f"max {settings.max_concurrent_positions}", "accent"),
    kpi("Kill switch", "🛑 ON" if killed else "🟢 OFF",
        "halted" if killed else "armed & ready", "dn" if killed else "up"),
]
st.markdown(f'<div class="kpi-strip">{"".join(cards)}</div>', unsafe_allow_html=True)


# ─────────────────────────── tabs ───────────────────────────
(tab_chart, tab_pos, tab_journal, tab_strat, tab_analytics, tab_news,
 tab_risk, tab_sys) = st.tabs(
    ["📈 Charts", "📊 Positions", "📒 Journal", "🤖 Strategies", "🔬 Analytics",
     "📰 News", "🛡️ Risk", "⚙️ System"]
)


# ─── tab: charts ───
with tab_chart:
    c1, c2, c3 = st.columns([2, 1, 1])
    symbol = c1.selectbox("Symbol", settings.symbols, index=0,
                          label_visibility="collapsed")
    tf = c2.selectbox("TF", ["1m", "3m", "5m", "15m"], index=2,
                      label_visibility="collapsed")
    bars_n = c3.select_slider("Bars", options=[60, 120, 240, 480], value=120,
                              label_visibility="collapsed")

    px = ltps.get(symbol); prev = prevs.get(symbol)
    # if no live LTP, derive one from the chart series (synth or real backfill)
    fallback_px = None
    if px is None:
        try:
            preview = _synthetic_bars(symbol, tf, bars_n)
            fallback_px = float(preview["c"].iloc[-1])
            fallback_prev = float(preview["o"].iloc[max(0, len(preview) - 12)])
        except Exception:
            fallback_prev = None
    px_show = px if px is not None else fallback_px
    prev_show = prev if prev is not None else (fallback_prev if px is None else None)
    px_cls = ""
    if px_show is not None and prev_show is not None:
        px_cls = "up" if px_show >= prev_show else "dn"
    elif px_show is not None:
        px_cls = "muted"
    px_str = f"₹{px_show:,.2f}" if px_show is not None else "—"
    chg_html = ""
    if px_show is not None and prev_show is not None and prev_show > 0:
        chg = px_show - prev_show; pct = chg / prev_show * 100
        arrow = "▲" if chg >= 0 else "▼"
        chg_html = f' <span class="muted">{arrow} {chg:+.2f} ({pct:+.2f}%)</span>'

    st.markdown(f"""
    <div class="card" style="margin-top:8px;display:flex;
                justify-content:space-between;align-items:center;">
      <div>
        <div class="muted">{symbol} · {tf}</div>
        <div class="big-px {px_cls}">{px_str}{chg_html}</div>
      </div>
      <div style="text-align:right;">
        <div class="muted">feed</div>
        <div><span class="dot {'dot-on' if feed_alive else 'dot-off'}"></span>
             {'live' if feed_alive else 'offline'}</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    df = q("""
        SELECT ts, o, h, l, c, v FROM ohlcv
        WHERE symbol=:s AND timeframe=:tf
        ORDER BY ts DESC LIMIT :n
    """, s=symbol, tf=tf, n=bars_n)

    use_demo = df.empty
    if use_demo:
        df = _synthetic_bars(symbol, tf, bars_n)
        st.markdown(
            '<div style="margin:6px 0 4px 0;">'
            '<span class="demo-badge">⚠ DEMO DATA — synthetic random walk · not real market</span>'
            '</div>', unsafe_allow_html=True)

    if True:
        df = df.sort_values("ts")
        # VWAP overlay (cumulative since session start)
        tp = (df["h"] + df["l"] + df["c"]) / 3
        vwap = (tp * df["v"]).cumsum() / df["v"].replace(0, 1).cumsum()

        fig = go.Figure()
        fig.add_trace(go.Candlestick(
            x=df["ts"], open=df["o"], high=df["h"], low=df["l"], close=df["c"],
            increasing=dict(line=dict(color="#16c784"), fillcolor="#16c784"),
            decreasing=dict(line=dict(color="#ea3943"), fillcolor="#ea3943"),
            name=symbol, showlegend=False,
        ))
        fig.add_trace(go.Scatter(x=df["ts"], y=vwap, line=dict(color="#f7b500", width=1.4),
                                 name="VWAP"))

        # ── trade overlays: see your trades on the chart ──
        n_trades_shown = 0
        if not use_demo:
            tmin, tmax = df["ts"].min(), df["ts"].max()
            tr = q("""
                SELECT entry_ts, exit_ts, side, entry_price, exit_price, pnl,
                       stop_loss, target, strategy
                FROM trades
                WHERE symbol=:s AND entry_ts BETWEEN :a AND :b
                ORDER BY entry_ts
            """, s=symbol, a=tmin.to_pydatetime(), b=tmax.to_pydatetime())
            if not tr.empty:
                n_trades_shown = len(tr)
                longs = tr[tr["side"] == "BUY"]
                shorts = tr[tr["side"] == "SELL"]
                if not longs.empty:
                    fig.add_trace(go.Scatter(
                        x=longs["entry_ts"], y=longs["entry_price"], mode="markers",
                        marker=dict(symbol="triangle-up", size=13, color="#16c784",
                                    line=dict(width=1.2, color="#0b0f17")),
                        name="long entry",
                        hovertext=[f"{r.strategy} LONG @ {r.entry_price:.2f}" for r in longs.itertuples()],
                        hoverinfo="text"))
                if not shorts.empty:
                    fig.add_trace(go.Scatter(
                        x=shorts["entry_ts"], y=shorts["entry_price"], mode="markers",
                        marker=dict(symbol="triangle-down", size=13, color="#ea3943",
                                    line=dict(width=1.2, color="#0b0f17")),
                        name="short entry",
                        hovertext=[f"{r.strategy} SHORT @ {r.entry_price:.2f}" for r in shorts.itertuples()],
                        hoverinfo="text"))
                # closed trades → P&L-coloured connector + exit X
                # NB: never name the loop var `r` — it would shadow the module
                # redis client `r` and break later tabs (Streamlit runs in module scope).
                for trow in tr[tr["exit_ts"].notna()].itertuples():
                    color = "#16c784" if (trow.pnl or 0) >= 0 else "#ea3943"
                    fig.add_trace(go.Scatter(
                        x=[trow.entry_ts, trow.exit_ts], y=[trow.entry_price, trow.exit_price],
                        mode="lines+markers", line=dict(color=color, width=1.3, dash="dot"),
                        marker=dict(symbol="x", size=9, color=color),
                        showlegend=False,
                        hovertext=[f"entry {trow.entry_price:.2f}",
                                   f"exit {trow.exit_price:.2f} · P&L {trow.pnl:+.0f}"],
                        hoverinfo="text"))
                # open positions → SL / TP guide lines
                for trow in tr[tr["exit_ts"].isna()].itertuples():
                    if trow.stop_loss:
                        fig.add_hline(y=float(trow.stop_loss), line=dict(color="#ea3943", width=1, dash="dash"),
                                      annotation_text="SL", annotation_position="right",
                                      annotation_font_color="#ea3943")
                    if trow.target:
                        fig.add_hline(y=float(trow.target), line=dict(color="#16c784", width=1, dash="dash"),
                                      annotation_text="TP", annotation_position="right",
                                      annotation_font_color="#16c784")
            caption = (f"▲▼ {n_trades_shown} trade(s) on chart"
                       if n_trades_shown else "no trades in this window yet")
            st.markdown(f'<div class="muted" style="margin:2px 0 -8px 6px;">{caption}</div>',
                        unsafe_allow_html=True)

        fig.update_layout(
            height=480, margin=dict(l=10, r=10, t=10, b=10),
            template="plotly_dark",
            paper_bgcolor="#131826", plot_bgcolor="#131826",
            xaxis=dict(rangeslider=dict(visible=False), gridcolor="#1f2740"),
            yaxis=dict(gridcolor="#1f2740"),
            font=dict(color="#e6e9ef"),
        )
        st.plotly_chart(fig, use_container_width=True)

        # volume bars
        fv = go.Figure()
        colors = ["#16c784" if c >= o else "#ea3943"
                  for c, o in zip(df["c"], df["o"])]
        fv.add_trace(go.Bar(x=df["ts"], y=df["v"], marker=dict(color=colors), showlegend=False))
        fv.update_layout(height=140, margin=dict(l=10, r=10, t=4, b=10),
                         template="plotly_dark",
                         paper_bgcolor="#131826", plot_bgcolor="#131826",
                         xaxis=dict(gridcolor="#1f2740"),
                         yaxis=dict(gridcolor="#1f2740", title="vol"),
                         font=dict(color="#e6e9ef"))
        st.plotly_chart(fv, use_container_width=True)


# P&L colouring for tables (green profit / red loss / muted flat)
def _pnl_color(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "color:#8a93a6;"
    return f"color:{'#16c784' if v > 0 else ('#ea3943' if v < 0 else '#8a93a6')};font-weight:600;"


# ─── tab: positions ───
with tab_pos:
    df = q("""SELECT strategy, symbol, side, qty, entry_price,
                     stop_loss, target,
                     (entry_ts AT TIME ZONE 'Asia/Kolkata') AS entry_ts
              FROM trades WHERE exit_ts IS NULL ORDER BY entry_ts DESC""")
    if df.empty:
        st.markdown('<div class="card" style="text-align:center;padding:30px;">'
                    '<span class="muted">No open positions</span></div>',
                    unsafe_allow_html=True)
    else:
        # live mark-to-market from the latest LTP in Redis
        ltps = {}
        for sym in df["symbol"].unique():
            v = r.get(f"titan:ltp:{sym}")
            ltps[sym] = float(v) if v else None

        def _mtm(row):
            ltp = ltps.get(row["symbol"])
            entry = float(row["entry_price"]); qty = int(row["qty"])
            if ltp is None:
                return pd.Series({"LTP": None, "P&L (₹)": None, "Return %": None})
            sign = 1 if row["side"] == "BUY" else -1
            pnl = (ltp - entry) * sign * qty
            ret = (pnl / (entry * qty) * 100) if entry and qty else 0.0
            return pd.Series({"LTP": ltp, "P&L (₹)": pnl, "Return %": ret})

        mtm = df.apply(_mtm, axis=1)
        df = pd.concat([df, mtm], axis=1)
        df["Direction"] = df["side"].map(lambda s: "🟢 LONG" if s == "BUY" else "🔴 SHORT")

        tot = float(df["P&L (₹)"].dropna().sum())
        winners = int((df["P&L (₹)"] > 0).sum()); losers = int((df["P&L (₹)"] < 0).sum())
        m = st.columns(4)
        m[0].metric("Open positions", len(df))
        m[1].metric("Winning / Losing", f"{winners} / {losers}")
        m[2].metric("Unrealized P&L", f"₹{tot:+,.0f}",
                    delta_color="normal" if tot >= 0 else "inverse")
        m[3].metric("Mark", "live LTP")

        disp = df[["strategy", "symbol", "Direction", "qty", "entry_price", "LTP",
                   "stop_loss", "target", "P&L (₹)", "Return %", "entry_ts"]].rename(
            columns={"strategy": "Strategy", "symbol": "Symbol", "qty": "Qty",
                     "entry_price": "Entry", "stop_loss": "Stop", "target": "Target",
                     "entry_ts": "Entered (IST)"})
        sty = (disp.style
               .map(_pnl_color, subset=["P&L (₹)", "Return %"])
               .format({"Entry": "₹{:,.2f}", "LTP": "₹{:,.2f}", "Stop": "₹{:,.2f}",
                        "Target": "₹{:,.2f}", "P&L (₹)": "₹{:+,.0f}", "Return %": "{:+.2f}%",
                        "Entered (IST)": lambda t: t.strftime("%m-%d %I:%M %p") if pd.notna(t) else "—"},
                       na_rep="—"))
        st.dataframe(sty, use_container_width=True, hide_index=True)
        st.caption("P&L is live mark-to-market vs the latest traded price. "
                   "🟢 LONG profits when price rises; 🔴 SHORT profits when price falls.")


# ─── tab: journal ───
with tab_journal:
    df = q("""SELECT (entry_ts AT TIME ZONE 'Asia/Kolkata') AS entry_ts,
                     (exit_ts  AT TIME ZONE 'Asia/Kolkata') AS exit_ts,
                     strategy, symbol, side, qty,
                     entry_price, exit_price, pnl, exit_reason,
                     EXTRACT(EPOCH FROM (exit_ts - entry_ts))/60.0 AS held_min
              FROM trades WHERE exit_ts IS NOT NULL
              ORDER BY exit_ts DESC LIMIT 100""")
    if df.empty:
        st.markdown('<div class="card" style="text-align:center;padding:30px;">'
                    '<span class="muted">No closed trades</span></div>',
                    unsafe_allow_html=True)
    else:
        wins = int((df["pnl"] > 0).sum()); losses = int((df["pnl"] <= 0).sum())
        net = float(df["pnl"].sum())
        gross_w = float(df.loc[df["pnl"] > 0, "pnl"].sum())
        gross_l = float(-df.loc[df["pnl"] <= 0, "pnl"].sum())
        pf = (gross_w / gross_l) if gross_l else float("inf")
        c = st.columns(5)
        c[0].metric("Trades", len(df))
        c[1].metric("Wins / Losses", f"{wins} / {losses}")
        c[2].metric("Win rate", f"{wins / max(len(df),1) * 100:.1f}%")
        c[3].metric("Profit factor", f"{pf:.2f}" if pf != float("inf") else "∞")
        c[4].metric("Net P&L", f"₹{net:+,.0f}",
                    delta_color="normal" if net >= 0 else "inverse")

        df["Result"] = df["pnl"].map(lambda v: "✅ WIN" if v > 0 else "❌ LOSS")
        df["Direction"] = df["side"].map(lambda s: "LONG" if s in ("BUY", "LONG") else "SHORT")
        df["Return %"] = df.apply(
            lambda x: (float(x["pnl"]) / (float(x["entry_price"]) * int(x["qty"])) * 100)
            if x["entry_price"] and x["qty"] else 0.0, axis=1)

        disp = df[["exit_ts", "strategy", "symbol", "Direction", "qty", "entry_price",
                   "exit_price", "pnl", "Return %", "exit_reason", "Result", "held_min"]].rename(
            columns={"exit_ts": "Closed (IST)", "strategy": "Strategy", "symbol": "Symbol",
                     "qty": "Qty", "entry_price": "Entry", "exit_price": "Exit",
                     "pnl": "P&L (₹)", "exit_reason": "Reason", "held_min": "Held (min)"})
        sty = (disp.style
               .map(_pnl_color, subset=["P&L (₹)", "Return %"])
               .format({"Entry": "₹{:,.2f}", "Exit": "₹{:,.2f}", "P&L (₹)": "₹{:+,.0f}",
                        "Return %": "{:+.2f}%", "Held (min)": "{:.0f}",
                        "Closed (IST)": lambda t: t.strftime("%m-%d %I:%M %p") if pd.notna(t) else "—"},
                       na_rep="—"))
        st.dataframe(sty, use_container_width=True, hide_index=True)
        st.caption("Each row is a CLOSED trade. P&L = realized profit/loss after the exit. "
                   "Exit reason: `target` (hit profit), `stop` (hit stop-loss), `signal_exit` (strategy flip).")


# ─── tab: strategies ───
with tab_strat:
    on = set(r.smembers("titan:strategies:enabled") or [])
    # regimes that arm each strategy (from the decision engine's map)
    regime_for = {n: [reg for reg, names in REGIME_CANDIDATES.items() if n in names]
                  for n in BASE_STRATEGIES}
    # render order: currently-active first, then the rest, killed last
    names = sorted(BASE_STRATEGIES.keys(),
                   key=lambda n: (n in KILLED_STRATEGIES, n not in on, n))
    all_strats = [(n, n.replace("_", " ").upper(),
                   STRAT_DESC.get(n, n), n in KILLED_STRATEGIES) for n in names]

    # ── auto-pilot control bar ──
    _ap_flag = r.get("titan:autopilot:enabled")
    autopilot_armed = (_ap_flag == "1")
    _regime_now = r.get("titan:regime:current") or "—"
    _regime_reason = r.get("titan:regime:reason") or ""
    active_now = sorted(n for n in on if n in BASE_STRATEGIES)
    ap_c = st.columns([3, 1, 1])
    if autopilot_armed:
        active_html = ("".join(
            f'<span style="background:#16c78422;color:#16c784;border:1px solid #16c784;'
            f'border-radius:10px;padding:1px 8px;margin-right:6px;font-weight:600;">{n}</span>'
            for n in active_now) or '<span class="muted">none armed in this regime</span>')
        ap_c[0].markdown(
            f'<div class="card" style="border-color:#16c784;">'
            f'<span style="font-weight:700;">🤖 AUTO-PILOT ARMED</span> '
            f'<span class="muted">· regime <b>{_regime_now}</b> · auto-selecting by regime '
            f'(manual toggles read-only)</span>'
            f'<div style="margin-top:6px;"><span class="muted" style="font-size:0.72rem;">'
            f'ACTIVE NOW &nbsp;</span>{active_html}</div>'
            f'<div class="muted" style="margin-top:4px;font-size:0.72rem;">{_regime_reason}</div></div>',
            unsafe_allow_html=True)
    else:
        ap_c[0].markdown(
            f'<div class="card" style="border-color:#1f2740;">'
            f'<span style="font-weight:700;">👁 AUTO-PILOT OBSERVE-ONLY</span> '
            f'<span class="muted">· regime <b>{_regime_now}</b> · classifying only; '
            f'manual toggles active</span>'
            f'<div class="muted" style="margin-top:4px;font-size:0.72rem;">{_regime_reason}</div></div>',
            unsafe_allow_html=True)
    if autopilot_armed:
        if ap_c[1].button("Disarm auto-pilot", use_container_width=True):
            api("POST", "/autopilot/disarm"); st.rerun()
    else:
        if ap_c[1].button("Arm auto-pilot", type="primary", use_container_width=True):
            api("POST", "/autopilot/arm"); st.rerun()

    st.markdown('<div style="height:6px;"></div>', unsafe_allow_html=True)
    for name, label, descr, killed in all_strats:
        enabled = name in on
        hb = r.get(f"titan:heartbeat:{name}")
        age = "—"; stale = True
        if hb:
            try:
                hb_dt = datetime.fromisoformat(hb)
                if hb_dt.tzinfo is None:
                    hb_dt = hb_dt.replace(tzinfo=timezone.utc)
                secs = (datetime.now(timezone.utc) - hb_dt).total_seconds()
                age = f"{secs:.0f}s ago"; stale = secs > 120
            except Exception: pass
        dot_cls = "dot-on" if (enabled and not stale) else ("dot-warn" if enabled else "dot-off")
        # State wording differs under auto-pilot (it OWNS selection) vs manual.
        if killed:
            state_txt, state_cls = "KILLED", "dn"
        elif autopilot_armed:
            state_txt, state_cls = ("🟢 ACTIVE", "up") if enabled else ("IDLE", "muted")
        else:
            state_txt, state_cls = ("ENABLED", "up") if enabled else ("DISABLED", "muted")
        regs = regime_for.get(name, [])
        regimes_txt = ", ".join(str(rg).split(".")[-1] for rg in regs) or "—"
        # highlight whole card green when active under auto-pilot
        border = "#16c784" if (enabled and autopilot_armed) else "#1f2740"
        st.markdown(f"""
        <div class="card" style="margin-bottom:10px;display:flex;
                                  align-items:center;gap:18px;border-color:{border};">
          <div style="flex:2;">
            <div style="font-weight:700;font-size:1.0rem;">{label}</div>
            <div class="muted" style="margin-top:2px;">{name} · {descr}</div>
          </div>
          <div style="flex:0.7;text-align:center;">
            <div class="muted" style="font-size:0.7rem;">ARMED IN</div>
            <div style="font-weight:600;font-size:0.8rem;">{regimes_txt}</div>
          </div>
          <div style="flex:0.6;text-align:center;">
            <div class="muted" style="font-size:0.7rem;">HEARTBEAT</div>
            <div style="font-weight:600;">{age}</div>
          </div>
          <div style="flex:0.6;text-align:center;">
            <div class="muted" style="font-size:0.7rem;">STATE</div>
            <div><span class="dot {dot_cls}"></span>
                 <span class="{state_cls}">{state_txt}</span></div>
          </div>
        </div>
        """, unsafe_allow_html=True)
        # Redis is the source of truth: force session_state to match Redis
        # before rendering. Without this, the toggle's persisted widget state
        # disagrees with Redis on each rerun and the diff below fires /stop,
        # silently wiping `titan:strategies:enabled` (2026-06-15 incident).
        key = f"strat_{name}"
        st.session_state[key] = enabled
        cc = st.columns([5, 1])
        # When auto-pilot is armed it owns strategy selection — manual toggles are
        # read-only so the dashboard can't fight the decision engine.
        b = cc[1].toggle("enable", value=enabled, key=key,
                         disabled=killed or autopilot_armed,
                         help="killed by walk-forward" if killed
                         else ("managed by auto-pilot — disarm to toggle manually"
                               if autopilot_armed else None))
        if killed or autopilot_armed:
            continue
        if b != enabled:
            verb = "start" if b else "stop"
            api("POST", f"/strategies/{name}/{verb}"); st.rerun()


# ─── tab: analytics (surfaces the P5 capture: every signal, fill, decision) ───
with tab_analytics:
    st.markdown('<div style="height:6px;"></div>', unsafe_allow_html=True)
    st.caption("Pre-live evidence base — built from every signal, order attempt and "
               "fill we capture (including the ones we rejected).")

    # 1) signal funnel: generated → accepted vs rejected
    fun = q("SELECT accepted, COUNT(*) n FROM signals GROUP BY accepted")
    total = int(fun["n"].sum()) if not fun.empty else 0
    acc = int(fun[fun["accepted"] == True]["n"].sum()) if not fun.empty else 0  # noqa: E712
    rej = total - acc
    fc = st.columns(4)
    fc[0].metric("Signals generated", total)
    fc[1].metric("Accepted (→ order)", acc)
    fc[2].metric("Rejected", rej)
    fc[3].metric("Acceptance rate", f"{(acc/total*100) if total else 0:.0f}%")

    if total == 0:
        st.info("No signals captured yet. Once strategies run, every signal "
                "(accepted or rejected) is recorded here.")
    else:
        a1, a2 = st.columns(2)
        with a1:
            st.markdown("##### Why signals were rejected")
            rr = q("""SELECT reason, COUNT(*) n FROM (
                          SELECT LEFT(split_part(COALESCE(reject_reason,'(accepted)'),
                                                 'session halted: ', -1), 48) reason
                          FROM signals WHERE accepted=false
                      ) s GROUP BY reason ORDER BY n DESC LIMIT 10""")
            if rr.empty:
                st.markdown('<span class="muted">No rejections.</span>', unsafe_allow_html=True)
            else:
                fig_r = go.Figure(go.Bar(
                    x=rr["n"], y=rr["reason"], orientation="h",
                    marker=dict(color="#ea3943")))
                fig_r.update_layout(height=240, margin=dict(l=10, r=10, t=10, b=10),
                                    template="plotly_dark", paper_bgcolor="#131826",
                                    plot_bgcolor="#131826", font=dict(color="#e6e9ef"),
                                    xaxis=dict(gridcolor="#1f2740"),
                                    yaxis=dict(autorange="reversed"))
                st.plotly_chart(fig_r, use_container_width=True)
        with a2:
            st.markdown("##### Fill slippage — realized vs modeled")
            sl = q("""SELECT AVG(realized_slippage_bps) realized,
                             AVG(modeled_slippage_bps) modeled, COUNT(*) n
                      FROM fills""")
            if sl.empty or (sl["n"].iloc[0] or 0) == 0:
                st.markdown('<span class="muted">No fills yet.</span>', unsafe_allow_html=True)
            else:
                sc = st.columns(2)
                sc[0].metric("Realized (bps)", f"{(sl['realized'].iloc[0] or 0):.2f}")
                sc[1].metric("Modeled (bps)", f"{(sl['modeled'].iloc[0] or 0):.2f}")
                st.caption(f"{int(sl['n'].iloc[0])} fills. Realized ≈ modeled means the "
                           "paper cost model is faithful — trust it less when they diverge.")

        # 2) per-strategy × per-regime performance (the key pre-live question)
        st.markdown("##### Performance by strategy × market regime")
        perf = q("""
            SELECT strategy, COALESCE(regime,'—') regime,
                   COUNT(*) trades,
                   SUM(CASE WHEN pnl>0 THEN 1 ELSE 0 END) wins,
                   ROUND(AVG(pnl)::numeric,1) avg_pnl,
                   ROUND(SUM(pnl)::numeric,1) net_pnl
            FROM trades WHERE exit_ts IS NOT NULL
            GROUP BY strategy, regime ORDER BY net_pnl DESC NULLS LAST
        """)
        if perf.empty:
            st.markdown('<span class="muted">No closed trades yet — regime-conditioned '
                        'P&L appears once trades close.</span>', unsafe_allow_html=True)
        else:
            perf["win_rate"] = (perf["wins"] / perf["trades"] * 100).round(0).astype(int).astype(str) + "%"
            st.dataframe(perf[["strategy", "regime", "trades", "win_rate", "avg_pnl", "net_pnl"]],
                         use_container_width=True, hide_index=True)

        # 3) recent rejected signals — "what we skipped, and why"
        st.markdown("##### Recent rejected signals (what we skipped & why)")
        rj = q("""SELECT to_char(ts AT TIME ZONE 'Asia/Kolkata','MM-DD HH12:MI AM') ts, strategy, symbol, kind,
                         regime,
                         LEFT(split_part(reject_reason,'session halted: ',-1),60) reject_reason
                  FROM signals WHERE accepted=false ORDER BY ts DESC LIMIT 25""")
        if rj.empty:
            st.markdown('<span class="muted">No rejected signals.</span>', unsafe_allow_html=True)
        else:
            st.dataframe(rj, use_container_width=True, hide_index=True)


# ─── tab: news ───
with tab_news:
    st.markdown('<div style="height:6px;"></div>', unsafe_allow_html=True)
    nf = st.columns([1, 1, 1, 3])
    hours = nf[0].selectbox("Lookback", [6, 24, 72, 168], index=1,
                            format_func=lambda h: f"{h}h" if h < 168 else "7d",
                            key="news_hours")
    only_fires = nf[1].toggle("Fires only", value=False, key="news_fires_only")
    min_score = nf[2].slider("Min score", 0.0, 1.0, 0.0, 0.05, key="news_min_score")

    news_df = q("""
        SELECT (published_at AT TIME ZONE 'Asia/Kolkata') AS published_at,
               ticker, source, category,
               sentiment_label, sentiment_score, entity_conf,
               would_fire, fire_reason, headline
        FROM news_signals
        WHERE published_at >= NOW() - (:h::text || ' hours')::interval
        ORDER BY published_at DESC LIMIT 500
    """, h=hours)

    if news_df.empty:
        st.info("No news signals in this window. Run "
                "`python -m titan.news.ingest --hours 24 --csv` to populate.")
    else:
        if only_fires:
            news_df = news_df[news_df["would_fire"]]
        news_df = news_df[news_df["sentiment_score"] >= min_score]
        # summary KPIs
        kpi = st.columns(4)
        kpi[0].metric("Events", len(news_df))
        kpi[1].metric("Distinct tickers", news_df["ticker"].nunique())
        kpi[2].metric("Would fire", int(news_df["would_fire"].sum()))
        kpi[3].metric("Earnings cat", int((news_df["category"] == "earnings").sum()))

        # render with coloured sentiment + fire badge
        def _badge(row):
            sent = row["sentiment_label"]
            color = {"positive": "#16c784", "negative": "#ea3943",
                     "neutral": "#9aa4b2"}[sent]
            fire = ("<span style='background:#f7b500;color:#000;padding:1px 6px;"
                    "border-radius:6px;font-weight:700;'>FIRE</span>"
                    if row["would_fire"] else "")
            return (f"<span style='color:{color};font-weight:600;'>"
                    f"{sent[:3].upper()} {row['sentiment_score']:.2f}</span> {fire}")

        # use a manual table because Streamlit's dataframe doesn't render HTML
        rows_html = []
        for _, nr in news_df.head(100).iterrows():  # not `r` — would shadow redis client
            ts = nr["published_at"].strftime("%d %b %I:%M %p") if nr["published_at"] else "—"
            rows_html.append(f"""
            <tr>
              <td class="muted" style="white-space:nowrap;">{ts}</td>
              <td style="font-weight:700;">{nr['ticker']}</td>
              <td class="muted" style="font-size:0.8rem;">{nr['source']}</td>
              <td class="muted" style="font-size:0.8rem;">{nr['category']}</td>
              <td>{_badge(nr)}</td>
              <td class="muted" style="font-size:0.7rem;">{nr['entity_conf']:.2f}</td>
              <td>{nr['headline'][:180]}</td>
            </tr>""")
        st.markdown(f"""
        <table style="width:100%;border-collapse:collapse;">
          <thead>
            <tr style="border-bottom:1px solid #2a3243;">
              <th style="text-align:left;padding:4px 6px;" class="muted">When</th>
              <th style="text-align:left;padding:4px 6px;" class="muted">Ticker</th>
              <th style="text-align:left;padding:4px 6px;" class="muted">Source</th>
              <th style="text-align:left;padding:4px 6px;" class="muted">Category</th>
              <th style="text-align:left;padding:4px 6px;" class="muted">Sentiment</th>
              <th style="text-align:left;padding:4px 6px;" class="muted">Conf</th>
              <th style="text-align:left;padding:4px 6px;" class="muted">Headline</th>
            </tr>
          </thead>
          <tbody>{''.join(rows_html)}</tbody>
        </table>
        """, unsafe_allow_html=True)


# ─── tab: risk ───
with tab_risk:
    # session status banner (truthful — published by the supervisor)
    sess_status = r.get("titan:session:status")
    sess_reason = r.get("titan:session:reason") or ""
    if profit_locked or sess_status == "HALTED" and "profit" in sess_reason.lower():
        st.markdown('<div class="card" style="border-color:#16c784;">'
                    '<span class="up" style="font-weight:700;">🔒 PROFIT LOCKED</span> '
                    f'<span class="muted">— daily target ₹{profit_target:,.0f} reached; '
                    'new entries paused to protect gains. Open positions still exit on SL/TP.</span></div>',
                    unsafe_allow_html=True)
    elif loss_halted or sess_status == "HALTED":
        st.markdown('<div class="card" style="border-color:#ea3943;">'
                    f'<span class="dn" style="font-weight:700;">⛔ SESSION HALTED</span> '
                    f'<span class="muted">— {sess_reason or "daily loss cap reached"}.</span></div>',
                    unsafe_allow_html=True)
    else:
        st.markdown('<div class="card" style="border-color:#1f2740;">'
                    '<span class="up" style="font-weight:700;">✓ SESSION ACTIVE</span> '
                    '<span class="muted">— within all risk budgets.</span></div>',
                    unsafe_allow_html=True)
    st.markdown('<div style="height:10px;"></div>', unsafe_allow_html=True)

    c1, c2 = st.columns(2)
    with c1:
        # st.progress requires [0,1]; clamp (profit can push raw values negative)
        _clamp = lambda x: max(0.0, min(1.0, x))
        st.markdown("##### 🟢 Daily profit target (lock)")
        pp = _clamp(profit / profit_target if profit_target else 0)
        st.progress(pp, text=f"₹{profit:,.0f} of ₹{profit_target:,.0f}  ({pp*100:.0f}%)"
                    + ("  🔒 LOCKED" if profit_locked else ""))
        st.markdown("##### 🔴 Daily loss budget")
        p1 = _clamp(loss / daily_cap if daily_cap else 0)
        st.progress(p1, text=f"₹{loss:,.0f} of ₹{daily_cap:,.0f}  ({p1*100:.0f}%)")
        st.markdown("##### 📉 Drawdown budget")
        dd_inr = max(0.0, settings.capital - equity)
        p2 = _clamp(dd_inr / dd_cap if dd_cap else 0)
        st.progress(p2, text=f"₹{dd_inr:,.0f} of ₹{dd_cap:,.0f}  ({p2*100:.0f}%)")
    with c2:
        cc = st.columns(2)
        if killed:
            if cc[0].button("Clear kill switch", use_container_width=True):
                r.delete("titan:kill"); r.delete("titan:kill:reason"); st.rerun()
        else:
            if cc[0].button("🛑 TRIGGER KILL", type="primary", use_container_width=True):
                api("POST", "/kill", params={"reason": "dashboard"}); st.rerun()
        if cc[1].button("⚡ Flatten all", use_container_width=True, disabled=killed):
            api("POST", "/flatten")

    st.markdown("##### Recent risk events")
    df = q("SELECT (ts AT TIME ZONE 'Asia/Kolkata') AS ts, kind, detail "
           "FROM risk_events ORDER BY ts DESC LIMIT 15")
    if df.empty:
        st.markdown('<span class="muted">No risk events yet — halts, profit-locks and '
                    'kills will appear here once they fire.</span>', unsafe_allow_html=True)
    else:
        def _detail(d):
            if not isinstance(d, dict):
                return str(d or "")
            bits = []
            if d.get("reason"): bits.append(str(d["reason"]))
            if d.get("realized_pnl_today") is not None:
                bits.append(f"day P&L ₹{d['realized_pnl_today']:+,.0f}")
            if d.get("consecutive_losses"): bits.append(f"streak {d['consecutive_losses']}")
            return " · ".join(bits)
        df["When (IST)"] = df["ts"].dt.strftime("%m-%d %I:%M %p")
        df["Detail"] = df["detail"].map(_detail)
        st.dataframe(df[["When (IST)", "kind", "Detail"]].rename(columns={"kind": "Event"}),
                     use_container_width=True, hide_index=True)


# ─── tab: system ───
with tab_sys:
    s = st.columns(4)
    s[0].metric("Mode", settings.mode.upper())
    try: r.ping(); s[1].metric("Redis", "OK")
    except Exception: s[1].metric("Redis", "DOWN")
    try:
        with eng.connect() as cx: cx.execute(text("SELECT 1"))
        s[2].metric("Postgres", "OK")
    except Exception: s[2].metric("Postgres", "DOWN")
    res = api("GET", "/status")
    s[3].metric("API", "OK" if res and res.status_code == 200 else "DOWN")

    # ── feed health (from feed_supervisor) + market state ──
    s2 = st.columns(4)
    feed_status = r.get("titan:feed:status") or ("SIM" if sim_on else "—")
    feed_age = r.get("titan:feed:age_s")
    s2[0].metric("Feed", feed_status,
                 f"{feed_age}s ago" if feed_age else None, delta_color="off")
    s2[1].metric("Market", "OPEN" if clock.is_market_open(now_ist) else "CLOSED")
    s2[2].metric("Clock", "SIM" if sim_on else "REAL")
    s2[3].metric("Source", "synthetic" if synth_data else ("real WS" if not sim_on else "—"))
    if not sim_on and not clock.is_market_open(now_ist):
        st.caption("Real mode + market closed → feed supervisor keeps the WS down and "
                   "nothing trades. The feed auto-connects at 09:15 IST on trading days.")

    st.markdown("##### Universe (resolved tokens)")
    df = q("""
        SELECT name, exch_seg, token, symbol, lotsize
        FROM instruments
        WHERE name = ANY(:names)
          AND (instrumenttype='AMXIDX' OR symbol LIKE '%-EQ')
          AND exch_seg='NSE'
    """, names=settings.symbols)
    if not df.empty:
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.markdown('<span class="muted">Run <code>python -m titan.data.instruments</code> '
                    'to load the scrip master.</span>', unsafe_allow_html=True)


def run():
    os.system(f"streamlit run {__file__}")
