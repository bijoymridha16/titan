"""Strategy factory — expand parametrized families into many concrete variants
for the pre-live vetting harness.

This is the disciplined alternative to hand-porting 50 blog strategies (see
docs/09 P3): a handful of well-understood families × a parameter grid yields
50+ candidates, each a real Strategy instance, all run through the SAME
walk-forward ship/kill gate. History says most will be killed — that's the point.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Type

from titan.strategies.base import Strategy
from titan.strategies.library import (
    BollingerReversion, DonchianBreakout, MACrossover, MomentumROC, RSIReversion,
)

# family → parameter grid. Cartesian product of each grid = that family's variants.
PARAM_GRID: dict[Type[Strategy], dict[str, list]] = {
    MACrossover: {
        "fast": [5, 9, 12, 20],
        "slow": [21, 50, 100],
        "atr_mult": [2.0, 3.0],
    },
    DonchianBreakout: {
        "period": [10, 20, 55],
        "target_r": [1.5, 2.0, 3.0],
    },
    RSIReversion: {
        "period": [2, 7, 14],
        "lo": [20.0, 30.0],
        "hi": [70.0, 80.0],
    },
    BollingerReversion: {
        "period": [20, 50],
        "k": [2.0, 2.5, 3.0],
    },
    MomentumROC: {
        "lookback": [10, 20, 40, 60],
        "atr_mult": [2.0, 3.0],
    },
}


@dataclass(frozen=True)
class VariantSpec:
    key: str                 # unique id, e.g. "ma_cross.f9_s21_m2.0"
    family: str
    cls: Type[Strategy]
    params: dict

    def build(self, symbol: str) -> Strategy:
        return self.cls(symbol, dict(self.params))


def _slug(params: dict) -> str:
    return "_".join(f"{k[:3]}{v}" for k, v in params.items())


def _expand(cls: Type[Strategy], grid: dict[str, list]) -> list[VariantSpec]:
    keys = list(grid)
    out: list[VariantSpec] = []
    for combo in itertools.product(*(grid[k] for k in keys)):
        params = dict(zip(keys, combo))
        # skip nonsensical MA combos where fast >= slow
        if "fast" in params and "slow" in params and params["fast"] >= params["slow"]:
            continue
        out.append(VariantSpec(
            key=f"{cls.name}.{_slug(params)}",
            family=getattr(cls, "family", "generic"),
            cls=cls, params=params,
        ))
    return out


def all_variants() -> list[VariantSpec]:
    """Every (family × param-combo) variant — the full vetting candidate set."""
    out: list[VariantSpec] = []
    for cls, grid in PARAM_GRID.items():
        out.extend(_expand(cls, grid))
    return out


def variant_count() -> int:
    return len(all_variants())
