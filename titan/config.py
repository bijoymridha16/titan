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

    universe: str = "NIFTY,BANKNIFTY,FINNIFTY,RELIANCE,HDFCBANK,ICICIBANK"

    # How an index/underlying signal is actually EXECUTED (D1). Default ETF —
    # tradable at ₹5K on the NSE cash path (e.g. NIFTY→NIFTYBEES). OPTION (weekly
    # ATM) and INDEX (paper-only, not directly tradable) are the alternatives;
    # the underlying→instrument map lives in config/instrument_map.yaml.
    instrument_kind: Literal["ETF", "OPTION", "INDEX", "EQUITY"] = "ETF"

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

    @property
    def autopilot_validated_set(self) -> set[str]:
        return {s.strip() for s in self.autopilot_validated.split(",") if s.strip()}


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
