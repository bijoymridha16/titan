"""Strategy ABC. Backtest, paper, and live all drive the same class via `on_bar()`.

A strategy returns Signals — never orders. The execution layer converts
Signals into Orders after the risk engine approves them.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Optional

import pandas as pd


class SignalKind(StrEnum):
    ENTRY_LONG = "ENTRY_LONG"
    ENTRY_SHORT = "ENTRY_SHORT"
    EXIT = "EXIT"


@dataclass
class Signal:
    ts: datetime
    symbol: str
    kind: SignalKind
    entry: float
    stop: float
    target: Optional[float] = None
    reason: str = ""
    confidence: float = 1.0  # (0,1] conviction — scales position size (clamped 0.1–1.0)

    @property
    def per_unit_risk(self) -> float:
        return abs(self.entry - self.stop)


class Strategy(ABC):
    name: str = "abstract"
    timeframe: str = "5m"

    def __init__(self, symbol: str, params: Optional[dict] = None):
        self.symbol = symbol
        self.params = params or {}

    @abstractmethod
    def on_bar(self, bars: pd.DataFrame) -> list[Signal]:
        """Called once per closed bar. `bars` is the full history up to and
        including the just-closed bar, indexed by ts ascending with columns
        o,h,l,c,v. Return zero or more signals for this bar's close."""
