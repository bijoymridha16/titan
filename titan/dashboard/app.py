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

from titan.config import settings

IST = ZoneInfo("Asia/Kolkata")
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
synth_on = (r.get("titan:mode:synthetic") == "1")
if synth_on:
    phase, phase_cls = "SIM OPEN", "pill-open"

_extra_pills = ""
if killed:
    _extra_pills += '<span class="pill pill-close">🛑 KILL</span>'
if synth_on:
    _extra_pills += '<span class="pill bg-warn">🧪 SYNTH</span>'

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
    f'<span class="market-clock">{now_ist.strftime("%a %d %b · %H:%M:%S")} IST</span>'
    '</div></div>',
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
    df = q("SELECT COALESCE(SUM(pnl),0) AS pnl FROM trades WHERE entry_ts::date = CURRENT_DATE")
    return float(df["pnl"].iloc[0]) if not df.empty else 0.0

def open_count() -> int:
    df = q("SELECT COUNT(*) AS c FROM trades WHERE exit_ts IS NULL")
    return int(df["c"].iloc[0]) if not df.empty else 0

equity = latest_equity(); pnl = today_pnl(); n_open = open_count()
dd_pct = max(0.0, (settings.capital - equity) / settings.capital * 100)
daily_cap = settings.capital * settings.max_daily_loss_pct / 100
dd_cap = settings.capital * settings.max_drawdown_pct / 100
loss = max(0.0, -pnl)

k = st.columns([1.4, 1.2, 1.0, 1.0, 1.0, 1.0])
k[0].metric("Equity (₹)", f"{equity:,.0f}", f"{equity - settings.capital:+,.0f}")
k[1].metric("Today P&L (₹)", f"{pnl:+,.0f}",
            delta_color="normal" if pnl >= 0 else "inverse")
k[2].metric("Drawdown", f"{dd_pct:.2f}%", f"cap {settings.max_drawdown_pct:.0f}%",
            delta_color="off")
k[3].metric("Daily loss", f"₹{loss:,.0f}", f"/ {daily_cap:,.0f}", delta_color="off")
k[4].metric("Open", str(n_open))
k[5].metric("Kill", "🛑 ON" if killed else "🟢 OFF")


# ─────────────────────────── tabs ───────────────────────────
tab_chart, tab_pos, tab_journal, tab_strat, tab_news, tab_risk, tab_sys = st.tabs(
    ["📈 Charts", "📊 Positions", "📒 Journal", "🤖 Strategies", "📰 News",
     "🛡️ Risk", "⚙️ System"]
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


# ─── tab: positions ───
with tab_pos:
    df = q("""SELECT strategy, symbol, side, qty, entry_price AS entry,
                     stop_loss AS sl, target, entry_ts
              FROM trades WHERE exit_ts IS NULL ORDER BY entry_ts DESC""")
    if df.empty:
        st.markdown('<div class="card" style="text-align:center;padding:30px;">'
                    '<span class="muted">No open positions</span></div>',
                    unsafe_allow_html=True)
    else:
        st.dataframe(df, use_container_width=True, hide_index=True)


# ─── tab: journal ───
with tab_journal:
    df = q("""SELECT entry_ts, exit_ts, strategy, symbol, side, qty,
                     entry_price, exit_price, pnl, exit_reason
              FROM trades WHERE exit_ts IS NOT NULL
              ORDER BY exit_ts DESC LIMIT 100""")
    if df.empty:
        st.markdown('<div class="card" style="text-align:center;padding:30px;">'
                    '<span class="muted">No closed trades</span></div>',
                    unsafe_allow_html=True)
    else:
        wins = int((df["pnl"] > 0).sum()); losses = int((df["pnl"] <= 0).sum())
        net = float(df["pnl"].sum())
        c = st.columns(4)
        c[0].metric("Trades", len(df))
        c[1].metric("Wins / Losses", f"{wins} / {losses}")
        c[2].metric("Win rate", f"{wins / max(len(df),1) * 100:.1f}%")
        c[3].metric("Net P&L", f"₹{net:+,.0f}",
                    delta_color="normal" if net >= 0 else "inverse")
        st.dataframe(df, use_container_width=True, hide_index=True)


# ─── tab: strategies ───
with tab_strat:
    all_strats = [
        ("orb", "Opening Range Breakout",
         "Trades the first breakout above / below the 09:15–09:30 range.",
         False),
        ("vwap_revert", "VWAP Mean Reversion",
         "Fades >2σ deviations from session VWAP back to the mean.",
         False),
        ("supertrend_adx", "Supertrend + ADX",
         "Trend-follows Supertrend flips when ADX > 20 (filters chop).",
         False),
        ("tsmom", "Time-Series Momentum (KILLED)",
         "20-day sign · vol-targeted daily rebalance. Walk-forward FAILED on "
         "3-equity universe — Sharpe -1.42 OOS. See docs/research/01_tsmom_results.md. "
         "Disabled by guard; needs NSE-50 universe to be viable.",
         True),
    ]
    on = set(r.smembers("titan:strategies:enabled") or [])
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
        state_txt = "ENABLED" if enabled else "DISABLED"
        state_cls = "up" if enabled and not stale else ("bg-warn" if enabled else "muted")
        st.markdown(f"""
        <div class="card" style="margin-bottom:10px;display:flex;
                                  align-items:center;gap:18px;">
          <div style="flex:2;">
            <div style="font-weight:700;font-size:1.0rem;">{label}</div>
            <div class="muted" style="margin-top:2px;">{name} · {descr}</div>
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
        b = cc[1].toggle("enable", key=key, disabled=killed,
                         help="killed by walk-forward" if killed else None)
        if killed:
            continue
        if b != enabled:
            verb = "start" if b else "stop"
            api("POST", f"/strategies/{name}/{verb}"); st.rerun()


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
        SELECT published_at, ticker, source, category,
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
        for _, r in news_df.head(100).iterrows():
            ts = r["published_at"].strftime("%d %b %H:%M") if r["published_at"] else "—"
            rows_html.append(f"""
            <tr>
              <td class="muted" style="white-space:nowrap;">{ts}</td>
              <td style="font-weight:700;">{r['ticker']}</td>
              <td class="muted" style="font-size:0.8rem;">{r['source']}</td>
              <td class="muted" style="font-size:0.8rem;">{r['category']}</td>
              <td>{_badge(r)}</td>
              <td class="muted" style="font-size:0.7rem;">{r['entity_conf']:.2f}</td>
              <td>{r['headline'][:180]}</td>
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
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("##### Daily loss budget")
        p1 = min(1.0, loss / daily_cap if daily_cap else 0)
        st.progress(p1, text=f"₹{loss:,.0f} of ₹{daily_cap:,.0f}  ({p1*100:.0f}%)")
        st.markdown("##### Drawdown budget")
        p2 = min(1.0, (settings.capital - equity) / dd_cap if dd_cap else 0)
        st.progress(p2, text=f"₹{settings.capital - equity:,.0f} of ₹{dd_cap:,.0f}  ({p2*100:.0f}%)")
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
    df = q("SELECT ts, kind, detail FROM risk_events ORDER BY ts DESC LIMIT 10")
    if df.empty:
        st.markdown('<span class="muted">No events</span>', unsafe_allow_html=True)
    else:
        st.dataframe(df, use_container_width=True, hide_index=True)


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
