"""Performance metrics for backtest results."""

from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass
class BacktestResult:
    """Structured backtest result with computed metrics."""

    total_return_pct: float
    cagr_pct: float
    sharpe_ratio: float
    max_drawdown_pct: float
    win_rate_pct: float
    total_trades: int
    won_trades: int
    benchmark_return_pct: float
    alpha_pct: float
    final_value: float

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BacktestResult":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def summary(self) -> str:
        """Human-readable summary."""
        alpha_emoji = "🟢" if self.alpha_pct > 0 else "🔴"
        return (
            f"Total Return: {self.total_return_pct:+.1f}% | "
            f"CAGR: {self.cagr_pct:+.1f}% | "
            f"Sharpe: {self.sharpe_ratio:.2f}\n"
            f"Max DD: {self.max_drawdown_pct:.1f}% | "
            f"Win Rate: {self.win_rate_pct:.0f}% | "
            f"Trades: {self.total_trades}\n"
            f"Benchmark: {self.benchmark_return_pct:+.1f}% | "
            f"{alpha_emoji} Alpha: {self.alpha_pct:+.1f}%"
        )

    def beats_benchmark(self) -> bool:
        return self.alpha_pct > 0


def compute_rolling_sharpe(returns: np.ndarray, window: int = 252) -> np.ndarray:
    """Compute rolling Sharpe ratio."""
    if len(returns) < window:
        return np.array([0])
    rolling_mean = np.convolve(returns, np.ones(window) / window, mode="valid")
    rolling_std = np.array(
        [np.std(returns[i : i + window]) for i in range(len(returns) - window + 1)]
    )
    with np.errstate(divide="ignore", invalid="ignore"):
        sharpe = np.where(rolling_std > 0, rolling_mean / rolling_std * np.sqrt(252), 0)
    return sharpe


def compute_sortino(returns: np.ndarray, risk_free: float = 0.06) -> float:
    """Compute Sortino ratio (downside deviation only)."""
    excess = returns - risk_free / 252
    downside = excess[excess < 0]
    if len(downside) == 0:
        return float("inf")
    downside_std = np.std(downside)
    return float(np.mean(excess) / downside_std * np.sqrt(252)) if downside_std > 0 else 0.0
