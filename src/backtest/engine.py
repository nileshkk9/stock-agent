"""Backtesting engine using Backtrader."""

import logging
from datetime import datetime
from typing import Any, Callable

import backtrader as bt
import pandas as pd

logger = logging.getLogger(__name__)


class LLMSignalStrategy(bt.Strategy):
    """Backtrader strategy driven by LLM-generated signals."""

    params = (
        ("signals", {}),  # {date: {ticker: {"action": "BUY"/"SELL", "confidence": 0-100}}}
        ("max_position_pct", 10),
        ("stop_loss_pct", 5),
    )

    def __init__(self):
        self.signals = self.params.signals
        self.orders = {}

    def next(self):
        current_date = self.datas[0].datetime.date(0).isoformat()

        # Check for signals on this date
        day_signals = self.signals.get(current_date, {})

        for i, data in enumerate(self.datas):
            ticker = data._name
            signal = day_signals.get(ticker, {})
            action = signal.get("action")

            if action == "BUY" and not self.getposition(data).size:
                confidence = signal.get("confidence", 50)
                # Scale position by confidence
                target_pct = self.params.max_position_pct * (confidence / 100)
                size = int(self.broker.getcash() * target_pct / 100 / data.close[0])
                if size > 0:
                    self.buy(data=data, size=size)
                    logger.info(f"BUY {ticker}: {size} shares @ {data.close[0]:.2f}")

            elif action == "SELL" and self.getposition(data).size:
                self.close(data=data)
                logger.info(f"SELL {ticker}: closed position @ {data.close[0]:.2f}")

        # Apply stop-loss
        for i, data in enumerate(self.datas):
            pos = self.getposition(data)
            if pos.size > 0:
                entry_price = pos.price
                current_price = data.close[0]
                loss_pct = (entry_price - current_price) / entry_price * 100
                if loss_pct >= self.params.stop_loss_pct:
                    self.close(data=data)
                    logger.warning(
                        f"STOP-LOSS {data._name}: -{loss_pct:.1f}% @ {current_price:.2f}"
                    )


class BacktestEngine:
    """Run backtests using Backtrader with LLM-generated signals."""

    def __init__(self, initial_cash: float = 1_000_000, commission: float = 0.0003):
        self.initial_cash = initial_cash
        self.commission = commission

    def run(
        self,
        price_data: dict[str, pd.DataFrame],
        signals: dict[str, dict],  # {date: {ticker: {action, confidence}}}
        max_position_pct: float = 10.0,
        stop_loss_pct: float = 5.0,
    ) -> dict[str, Any]:
        """Run backtest and return performance metrics.

        Args:
            price_data: {ticker: DataFrame with OHLCV}
            signals: {date_str: {ticker: {action, confidence}}}
            max_position_pct: Max % of portfolio per position
            stop_loss_pct: Stop-loss threshold %

        Returns:
            {
                "total_return_pct": float,
                "cagr_pct": float,
                "sharpe_ratio": float,
                "max_drawdown_pct": float,
                "win_rate_pct": float,
                "total_trades": int,
                "benchmark_return_pct": float,
                "alpha_pct": float,
                "equity_curve": [...],
            }
        """
        cerebro = bt.Cerebro()
        cerebro.addstrategy(
            LLMSignalStrategy,
            signals=signals,
            max_position_pct=max_position_pct,
            stop_loss_pct=stop_loss_pct,
        )

        # Add data feeds
        for ticker, df in price_data.items():
            if df.empty:
                continue
            data_feed = bt.feeds.PandasData(
                dataname=df,
                datetime=None,  # Use index
                open="Open",
                high="High",
                low="Low",
                close="Close",
                volume="Volume" if "Volume" in df.columns else None,
                plot=False,
            )
            data_feed._name = ticker
            cerebro.adddata(data_feed)

        cerebro.broker.setcash(self.initial_cash)
        cerebro.broker.setcommission(commission=self.commission)

        # Track benchmark (equal-weighted portfolio of all stocks)
        cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")
        cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe", riskfreerate=0.06)
        cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
        cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")

        start_value = cerebro.broker.getvalue()
        results = cerebro.run()
        end_value = cerebro.broker.getvalue()

        strat = results[0]

        # Extract metrics
        total_return = ((end_value - start_value) / start_value) * 100

        # CAGR
        trades_analyzer = strat.analyzers.trades.get_analysis()
        sharpe = strat.analyzers.sharpe.get_analysis().get("sharperatio", 0) or 0
        drawdown = strat.analyzers.drawdown.get_analysis()
        max_dd = drawdown.get("max", {}).get("drawdown", 0) or 0

        # Win rate
        total_trades = trades_analyzer.get("total", {}).get("total", 0) or 0
        won = trades_analyzer.get("won", {}).get("total", 0) or 0
        win_rate = (won / total_trades * 100) if total_trades > 0 else 0

        # Benchmark (buy and hold equal weight)
        benchmark_return = self._calculate_benchmark_return(price_data)

        return {
            "total_return_pct": round(total_return, 2),
            "cagr_pct": round(total_return / max(len(price_data), 1) * (252 / 365), 2),
            "sharpe_ratio": round(sharpe, 3),
            "max_drawdown_pct": round(abs(max_dd), 2),
            "win_rate_pct": round(win_rate, 1),
            "total_trades": total_trades,
            "won_trades": won,
            "benchmark_return_pct": round(benchmark_return, 2),
            "alpha_pct": round(total_return - benchmark_return, 2),
            "final_value": round(end_value, 2),
        }

    def _calculate_benchmark_return(self, price_data: dict[str, pd.DataFrame]) -> float:
        """Calculate equal-weighted buy-and-hold return across all stocks."""
        returns = []
        for df in price_data.values():
            if df.empty or len(df) < 2:
                continue
            start_price = df["Close"].iloc[0]
            end_price = df["Close"].iloc[-1]
            returns.append((end_price - start_price) / start_price * 100)

        return sum(returns) / len(returns) if returns else 0.0
