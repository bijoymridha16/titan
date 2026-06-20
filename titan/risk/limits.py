"""Risk limit configuration. Read from settings; immutable for the trading session."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import time

from titan.config import settings


@dataclass(frozen=True)
class RiskLimits:
    capital: float
    max_risk_per_trade_pct: float
    max_daily_loss_pct: float
    max_daily_profit_pct: float
    max_weekly_loss_pct: float
    max_drawdown_pct: float
    max_consecutive_losses: int
    max_concurrent_positions: int
    intraday_square_off: time

    @classmethod
    def from_settings(cls) -> "RiskLimits":
        return cls(
            capital=settings.capital,
            max_risk_per_trade_pct=settings.max_risk_per_trade_pct,
            max_daily_loss_pct=settings.max_daily_loss_pct,
            max_daily_profit_pct=settings.max_daily_profit_pct,
            max_weekly_loss_pct=settings.max_weekly_loss_pct,
            max_drawdown_pct=settings.max_drawdown_pct,
            max_consecutive_losses=settings.max_consecutive_losses,
            max_concurrent_positions=settings.max_concurrent_positions,
            intraday_square_off=settings.intraday_square_off,
        )

    @property
    def max_risk_per_trade_inr(self) -> float:
        return self.capital * self.max_risk_per_trade_pct / 100.0

    @property
    def max_daily_loss_inr(self) -> float:
        return self.capital * self.max_daily_loss_pct / 100.0

    @property
    def max_daily_profit_inr(self) -> float:
        return self.capital * self.max_daily_profit_pct / 100.0

    @property
    def max_weekly_loss_inr(self) -> float:
        return self.capital * self.max_weekly_loss_pct / 100.0

    @property
    def max_drawdown_inr(self) -> float:
        return self.capital * self.max_drawdown_pct / 100.0
