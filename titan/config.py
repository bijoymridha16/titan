from __future__ import annotations

from datetime import time
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TITAN_", env_file=".env", extra="ignore")

    mode: Literal["paper", "live"] = "paper"
    env: str = "dev"
    # Explicit SIMULATION switch. When False (default), the clock is real and the
    # RiskEngine market-hours gate blocks all trading outside real NSE hours.
    # When True (opt-in), a labeled simulation clock runs the pipeline any time.
    # Can be overridden live via the `titan:sim:enabled` Redis key / API.
    sim_mode: bool = False

    capital: float = 500_000.0
    max_risk_per_trade_pct: float = 1.0
    max_daily_loss_pct: float = 2.0
    # Daily PROFIT target (profit-lock). Once realized PnL today reaches this,
    # the engine stops opening new positions for the day to protect gains —
    # the positive mirror of max_daily_loss_pct. 0 disables the lock.
    max_daily_profit_pct: float = 4.0
    max_weekly_loss_pct: float = 5.0
    max_drawdown_pct: float = 10.0
    max_consecutive_losses: int = 5
    max_concurrent_positions: int = 3
    intraday_square_off: time = time(15, 15)

    db_url: str = "postgresql+psycopg://titan:titan@localhost:5432/titan"
    redis_url: str = "redis://localhost:6379/0"

    # ─── feed resilience (manifesto Scenario A) ───
    # Two-stage staleness handling. The SOFT threshold reacts fast: when no tick
    # heartbeat has arrived for this many seconds the supervisor bridges the gap
    # with REST LTP polling (keeps downstream + heartbeat alive) WHILE the WS
    # tries to recover — far less disruptive than a full restart. The HARD
    # threshold is the give-up point: restart the feed process with backoff.
    feed_rest_bridge_after_s: int = 5    # soft → REST LTP bridge
    feed_stale_after_s: int = 30         # hard → restart feed process
    feed_rest_fallback: bool = True      # master switch for the REST bridge

    # ─── tick sanitization (manifesto Scenario A: corrupted-quote rejection) ───
    # Angel's WS has been observed emitting wildly wrong prices. A tick deviating
    # more than N std-devs from the trailing volume-weighted price is treated as
    # an infrastructure anomaly: dropped from the OHLCV path and parked on the
    # dead-letter stream `ticks:deadletter:<symbol>` for later inspection.
    tick_filter_enabled: bool = True
    tick_outlier_sigma: float = 4.0
    tick_filter_window_s: int = 300      # trailing window for VWAP / std (5 min)
    tick_filter_min_samples: int = 20    # accept-all until the window has this many

    # ─── order idempotency (manifesto Scenario A) ───
    # TTL of the per-(strategy,symbol) dispatch lock. Held during send; kept for
    # the full TTL if the broker response is ambiguous (timeout) so a retry can't
    # double-fire before the order is reconciled.
    order_lock_ttl_s: int = 30

    # ─── OPS throttle (manifesto Scenario B: 2026 rate caps) ───
    # Client-side token bucket so order dispatch never exceeds the per-segment
    # orders-per-second cap. max_ops = sustained rate; ops_burst = max burst.
    max_ops: float = 10.0
    ops_burst: int = 10

    # ─── exchange Strategy IDs (manifesto Scenario B: SEBI 2026 traceability) ───
    # Per-strategy exchange-registered IDs, embedded in every order payload.
    # Format: "orb:NSE12345,vwap_revert:NSE67890". `strategy_id_default` (or the
    # ALGO_ID env) is the fallback when a strategy has no specific mapping.
    strategy_ids: str = ""
    strategy_id_default: str = ""

    @property
    def strategy_id_map(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for pair in self.strategy_ids.split(","):
            pair = pair.strip()
            if ":" in pair:
                name, sid = pair.split(":", 1)
                if name.strip() and sid.strip():
                    out[name.strip()] = sid.strip()
        return out

    universe: str = "NIFTY,BANKNIFTY,FINNIFTY,RELIANCE,HDFCBANK,ICICIBANK"

    # How an index/underlying signal is actually EXECUTED (D1). Default ETF —
    # tradable at ₹5K on the NSE cash path (e.g. NIFTY→NIFTYBEES). OPTION (weekly
    # ATM) and INDEX (paper-only, not directly tradable) are the alternatives;
    # the underlying→instrument map lives in config/instrument_map.yaml.
    instrument_kind: Literal["ETF", "OPTION", "INDEX", "EQUITY"] = "ETF"

    # ─── options pivot (manifesto Multiplier 1 / Scenario C) ───
    # 2026 index lot sizes (configurable — these are exchange-set and revised
    # periodically; verify against the current NSE circular before live).
    lot_sizes: str = "NIFTY:65,BANKNIFTY:30,FINNIFTY:60,MIDCPNIFTY:120,SENSEX:20"
    # ATM strike rounding step per underlying.
    option_strike_steps: str = "NIFTY:50,BANKNIFTY:100,FINNIFTY:50,SENSEX:100"
    option_expiry_weekday: int = 3       # Mon=0…Sun=6; weekly expiry (verify per index)
    option_offset_steps: int = 0         # 0 = ATM; +n = n strikes OTM
    option_exchange: str = "NFO"
    # Execution style: MARKET, or MIDPOINT_LIMIT (peg a limit to bid-ask midpoint,
    # cancel if unfilled within limit_fill_timeout_s — kills negative slippage).
    order_exec_mode: Literal["MARKET", "MIDPOINT_LIMIT"] = "MARKET"
    limit_fill_timeout_s: int = 15

    # ─── margin velocity (manifesto Multiplier 3) ───
    # Pre-trade SPAN+Exposure margin check via the batch endpoint. When the ATM
    # contract's margin won't fit available capital (after a buffer), step OTM to
    # a cheaper strike rather than eat a broker rejection. Off by default — it
    # needs the live margin API; enable once creds/whitelist are in place.
    margin_check_enabled: bool = False
    margin_buffer_pct: float = 5.0
    margin_max_otm_steps: int = 5

    @property
    def lot_size_map(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for pair in self.lot_sizes.split(","):
            if ":" in pair:
                k, v = pair.split(":", 1)
                try:
                    out[k.strip().upper()] = int(v)
                except ValueError:
                    pass
        return out

    @property
    def strike_step_map(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for pair in self.option_strike_steps.split(","):
            if ":" in pair:
                k, v = pair.split(":", 1)
                try:
                    out[k.strip().upper()] = float(v)
                except ValueError:
                    pass
        return out

    # ─── live-trading safety gates ───
    live_enabled: bool = False
    live_max_order_value: float = 25_000.0
    live_allowed_products: str = "INTRADAY"
    live_allowed_exchanges: str = "NSE"
    live_dry_run: bool = True

    @property
    def allowed_products_set(self) -> set[str]:
        return {p.strip().upper() for p in self.live_allowed_products.split(",") if p.strip()}

    @property
    def allowed_exchanges_set(self) -> set[str]:
        return {e.strip().upper() for e in self.live_allowed_exchanges.split(",") if e.strip()}

    @property
    def symbols(self) -> list[str]:
        return [s.strip() for s in self.universe.split(",") if s.strip()]

    # ─── auto-pilot (decision-driven strategy selection) ───
    # Master switch. When 0, auto_pilot still classifies regime + logs decisions
    # but does NOT touch the enabled set (observe-only / shadow). Flip to 1 to let
    # it actually arm/disarm strategies. Can also be toggled live via the API
    # (Redis key titan:autopilot:enabled overrides this default at runtime).
    autopilot_enabled: bool = False
    # The ONLY strategies auto-pilot is ever allowed to enable. A strategy must
    # have passed its walk-forward ship/kill gate to be listed here. This closes
    # AUTOPSY_FINDINGS H1: unvalidated strategies can never be auto-armed.
    # (vwap_revert / supertrend_adx stay OUT until they have a results doc.)
    autopilot_validated: str = "orb"
    # How often (seconds) the loop re-classifies regime and reconciles the set.
    autopilot_interval_s: int = 30
    # Reference symbol whose bars define the market regime (index proxy).
    autopilot_ref_symbol: str = "NIFTY"

    # ─── regime classifier thresholds (deterministic; no ML, no black box) ───
    regime_adx_trend: float = 22.0      # ADX >= this  → trending
    regime_adx_range: float = 18.0      # ADX <  this  → ranging
    regime_vol_crisis_pctile: float = 0.90   # realized-vol percentile → crisis
    regime_vix_crisis: float = 25.0     # India VIX >= this → crisis (only if VIX feed present)
    regime_lookback_bars: int = 200     # window for ADX / vol percentile

    # ─── predictive news override (manifesto Multiplier 2: FinBERT) ───
    # When the live FinBERT negative-sentiment probability for the universe
    # reaches this, force CRISIS *before* lagging ADX/ATR confirm — disarming
    # trend strategies ahead of the price move. Fed via Redis `titan:news:neg_p`.
    regime_news_override: bool = True
    regime_news_crisis_p: float = 0.85

    @property
    def autopilot_validated_set(self) -> set[str]:
        return {s.strip() for s in self.autopilot_validated.split(",") if s.strip()}

    # ─── self-healing walk-forward daemon (manifesto §3) ───
    # Re-runs the walk-forward vetting on a schedule and re-promotes survivors so
    # the validated allowlist tracks live edge and decayed strategies are demoted
    # automatically. weekday: Mon=0 … Sun=6 (default Sat). hour: IST.
    wf_daemon_weekday: int = 5
    wf_daemon_hour: int = 18
    wf_daemon_tf: str = "5m"
    wf_daemon_max_bars: int = 0   # 0 = all available history


class NewsSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NEWS_", env_file=".env", extra="ignore")

    user_agent: str = "TITAN-research/0.1"
    scrape_enabled: bool = False
    finbert_model: str = "ProsusAI/finbert"
    batch_size: int = 16
    http_timeout: int = 15
    rate_sleep_s: float = 2.0


class AlgoSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    algo_id: str = Field(default="", alias="ALGO_ID")


class AngelOneSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ANGELONE_", env_file=".env", extra="ignore")

    api_key: str = ""
    client_code: str = ""
    password: str = ""
    totp_secret: str = ""


class AlertSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: str = Field(default="", alias="TELEGRAM_CHAT_ID")


settings = Settings()
angelone_settings = AngelOneSettings()
alert_settings = AlertSettings()
news_settings = NewsSettings()
algo_settings = AlgoSettings()
