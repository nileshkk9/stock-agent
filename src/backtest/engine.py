"""Backtesting engine — fixed Sharpe, Buy&Hold, + Momentum Ranking strategy."""

import logging
from datetime import datetime
from typing import Any

import backtrader as bt
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════
# STRATEGIES
# ══════════════════════════════════════════════════════════════════════


class TrendMomentumStrategy(bt.Strategy):
    """Trend-following + momentum filter.

    BUY:  SMA50 > SMA200 AND 20-day ROC > 0
    SELL: SMA50 < SMA200 OR stop-loss (5%)
    """

    params = (
        ("max_position_pct", 10),
        ("stop_loss_pct", 5),
    )

    def __init__(self):
        self.entry_prices = {}
        self.sma50 = {}
        self.sma200 = {}
        self.momentum = {}
        for d in self.datas:
            self.sma50[d._name] = bt.indicators.SMA(d.close, period=50)
            self.sma200[d._name] = bt.indicators.SMA(d.close, period=200)
            self.momentum[d._name] = bt.indicators.ROC(d.close, period=20)

    def next(self):
        for d in self.datas:
            ticker = d._name
            pos = self.getposition(d)
            if pd.isna(d.close[0]) or d.close[0] <= 0:
                continue

            sma50 = self.sma50[ticker][0]
            sma200 = self.sma200[ticker][0]
            mom = self.momentum[ticker][0]
            if pd.isna(sma50) or pd.isna(sma200) or pd.isna(mom):
                continue

            in_uptrend = sma50 > sma200
            positive_momentum = mom > 0
            in_downtrend = sma50 < sma200

            if in_uptrend and positive_momentum and pos.size == 0:
                size = self._size(d.close[0])
                if size > 0:
                    self.buy(data=d, size=size)
                    self.entry_prices[ticker] = d.close[0]

            elif in_downtrend and pos.size > 0:
                self.close(data=d)
                self.entry_prices.pop(ticker, None)

            elif pos.size > 0 and ticker in self.entry_prices:
                entry = self.entry_prices[ticker]
                if (entry - d.close[0]) / entry * 100 >= self.params.stop_loss_pct:
                    self.close(data=d)
                    self.entry_prices.pop(ticker, None)

    def _size(self, price: float) -> int:
        cash = self.broker.getcash()
        return max(1, int(cash * self.params.max_position_pct / 100 / price))


class MomentumRankingStrategy(bt.Strategy):
    """Concentrated momentum strategy — top 10 stocks by momentum score.

    Every month, rank all stocks by momentum (6-month + 3-month returns).
    Hold top 10. Rotate out of losers.

    This is the strategy many quant funds actually use for factor investing.
    """

    params = (
        ("top_n", 10),           # hold top 10 stocks
        ("max_position_pct", 10),  # 10% per stock = 100% allocated
        ("rebalance_days", 21),   # monthly rebalance (~21 trading days)
        ("stop_loss_pct", 5),
        ("momentum_6m", 126),    # ~6 months in trading days
        ("momentum_3m", 63),     # ~3 months
    )

    def __init__(self):
        self.entry_prices = {}
        self.roc_6m = {}
        self.roc_3m = {}
        for d in self.datas:
            self.roc_6m[d._name] = bt.indicators.ROC(d.close, period=self.params.momentum_6m)
            self.roc_3m[d._name] = bt.indicators.ROC(d.close, period=self.params.momentum_3m)

    def next(self):
        # Only act on first bar of each month (every ~21 days)
        if len(self) % self.params.rebalance_days != 0:
            # Still check stop-loss daily
            self._check_stop_loss()
            return

        # Rank stocks by momentum score
        scores = []
        for d in self.datas:
            ticker = d._name
            if pd.isna(d.close[0]) or d.close[0] <= 0:
                continue

            mom6 = self.roc_6m[ticker][0]
            mom3 = self.roc_3m[ticker][0]
            if pd.isna(mom6) or pd.isna(mom3):
                continue

            # Weight: 60% 6-month + 40% 3-month momentum
            score = mom6 * 0.6 + mom3 * 0.4
            scores.append((ticker, score, d))

        # Sort by momentum score descending
        scores.sort(key=lambda x: x[1], reverse=True)

        # Top N stocks to hold
        top_tickers = {s[0] for s in scores[: self.params.top_n]}

        # Sell stocks not in top N
        for d in self.datas:
            pos = self.getposition(d)
            if pos.size > 0 and d._name not in top_tickers:
                self.close(data=d)
                self.entry_prices.pop(d._name, None)

        # Buy top N stocks we don't already hold
        for ticker, score, d in scores[: self.params.top_n]:
            pos = self.getposition(d)
            if pos.size == 0 and not pd.isna(d.close[0]):
                size = self._size(d.close[0])
                if size > 0:
                    self.buy(data=d, size=size)
                    self.entry_prices[ticker] = d.close[0]

    def _size(self, price: float) -> int:
        cash = self.broker.getcash()
        # Distribute among top_n stocks
        per_stock = min(self.params.max_position_pct, 100.0 / self.params.top_n)
        return max(1, int(cash * per_stock / 100 / price))

    def _check_stop_loss(self):
        for d in self.datas:
            pos = self.getposition(d)
            if pos.size > 0 and d._name in self.entry_prices:
                entry = self.entry_prices[d._name]
                if not pd.isna(d.close[0]) and d.close[0] > 0:
                    if (entry - d.close[0]) / entry * 100 >= self.params.stop_loss_pct:
                        self.close(data=d)
                        self.entry_prices.pop(d._name, None)


class SignalStrategy(bt.Strategy):
    """Signal-driven — uses pre-generated BUY/SELL signals with optional LLM filter."""

    params = (
        ("signals", {}),
        ("max_position_pct", 10),
        ("stop_loss_pct", 5),
        ("llm_filter", None),   # {"ticker": "BUY"/"SELL"/"HOLD"} — LLM approval
        ("min_confidence", 60),
    )

    def __init__(self):
        self.signals = self.params.signals
        self.entry_prices = {}

    def next(self):
        current_date = self.datas[0].datetime.date(0).isoformat()
        day_signals = self.signals.get(current_date, {})

        for d in self.datas:
            ticker = d._name
            if ticker not in day_signals:
                continue

            signal = day_signals[ticker]
            action = signal.get("action")
            pos = self.getposition(d)
            confidence = signal.get("confidence", 50)

            if pd.isna(d.close[0]) or d.close[0] <= 0:
                continue

            # LLM combo filter: only trade if LLM also approves
            if self.params.llm_filter and ticker in self.params.llm_filter:
                llm_vote = self.params.llm_filter[ticker]
                if action == "BUY" and llm_vote not in ("BUY", "STRONG_BUY"):
                    continue
                if action == "SELL" and llm_vote not in ("SELL", "STRONG_SELL"):
                    continue

            if action == "BUY" and pos.size == 0 and confidence >= self.params.min_confidence:
                target_pct = self.params.max_position_pct * (confidence / 100)
                cash = self.broker.getcash()
                size = int(cash * target_pct / 100 / d.close[0])
                if size > 0:
                    self.buy(data=d, size=size)
                    self.entry_prices[ticker] = d.close[0]

            elif action == "SELL" and pos.size > 0:
                self.close(data=d)
                self.entry_prices.pop(ticker, None)

        # Stop-loss
        for d in self.datas:
            pos = self.getposition(d)
            if pos.size > 0 and d._name in self.entry_prices:
                entry = self.entry_prices[d._name]
                if not pd.isna(d.close[0]) and d.close[0] > 0:
                    if (entry - d.close[0]) / entry * 100 >= self.params.stop_loss_pct:
                        self.close(data=d)
                        self.entry_prices.pop(d._name, None)


class BuyAndHoldStrategy(bt.Strategy):
    """Equal-weight buy & hold with proper first-bar execution."""

    def __init__(self):
        self.bought = False

    def next(self):
        if self.bought:
            return
        # Buy on first bar with valid data
        ready = all(not pd.isna(d.close[0]) and d.close[0] > 0 for d in self.datas)
        if not ready:
            return
        per_stock_pct = 100.0 / len(self.datas)
        for d in self.datas:
            cash = self.broker.getcash()
            size = int(cash * per_stock_pct / 100 / d.close[0])
            if size > 0:
                self.buy(data=d, size=size)
        self.bought = True


# ══════════════════════════════════════════════════════════════════════
# ENGINE
# ══════════════════════════════════════════════════════════════════════


class BacktestEngine:
    """Run backtests with robust metrics extraction."""

    def __init__(self, initial_cash: float = 1_000_000, commission: float = 0.0003):
        self.initial_cash = initial_cash
        self.commission = commission

    def run(
        self,
        price_data: dict[str, pd.DataFrame],
        signals: dict[str, dict] | None = None,
        strategy: str = "trend_momentum",
        max_position_pct: float = 10.0,
        stop_loss_pct: float = 5.0,
        llm_filter: dict[str, str] | None = None,
        top_n: int = 10,
    ) -> dict[str, Any]:
        """Run backtest.

        Args:
            price_data: {ticker: OHLCV DataFrame}
            signals: {date: {ticker: {action, confidence}}} — for 'signal' strategy
            strategy: 'trend_momentum' | 'momentum_ranking' | 'signal' | 'buy_hold'
            max_position_pct: max % per position
            stop_loss_pct: stop-loss %
            llm_filter: {ticker: "BUY"/"SELL"/"HOLD"} — LLM combo filter
            top_n: number of stocks for momentum_ranking strategy

        Returns:
            Metrics dict
        """
        cerebro = bt.Cerebro(stdstats=False)  # Disable default observers (cleaner)

        # Strategy selection
        if strategy == "trend_momentum":
            cerebro.addstrategy(TrendMomentumStrategy,
                              max_position_pct=max_position_pct,
                              stop_loss_pct=stop_loss_pct)
        elif strategy == "momentum_ranking":
            cerebro.addstrategy(MomentumRankingStrategy,
                              top_n=top_n,
                              max_position_pct=max_position_pct,
                              stop_loss_pct=stop_loss_pct)
        elif strategy == "signal":
            cerebro.addstrategy(SignalStrategy,
                              signals=signals or {},
                              max_position_pct=max_position_pct,
                              stop_loss_pct=stop_loss_pct,
                              llm_filter=llm_filter)
        elif strategy == "buy_hold":
            cerebro.addstrategy(BuyAndHoldStrategy)
        else:
            raise ValueError(f"Unknown strategy: {strategy}")

        # Add data feeds
        for ticker, df in price_data.items():
            if df.empty or len(df) < 50:
                continue
            if not isinstance(df.index, pd.DatetimeIndex):
                df = df.copy()
                df.index = pd.to_datetime(df.index)

            feed = bt.feeds.PandasData(
                dataname=df, datetime=None,
                open="Open", high="High", low="Low", close="Close",
                volume="Volume" if "Volume" in df.columns else None,
                plot=False,
            )
            feed._name = ticker
            cerebro.adddata(feed)

        cerebro.broker.setcash(self.initial_cash)
        cerebro.broker.setcommission(commission=self.commission)

        # Analyzers
        cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")
        cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
        cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")
        cerebro.addanalyzer(bt.analyzers.SharpeRatio_A, _name="sharpe",
                           riskfreerate=0.06, timeframe=bt.TimeFrame.Days,
                           annualize=True, stddev_sample=True)

        start_val = float(cerebro.broker.getvalue())
        results = cerebro.run()
        strat = results[0]

        # End value — robust extraction
        end_val = float(cerebro.broker.getvalue())
        if pd.isna(end_val) or end_val <= 0:
            end_val = float(cerebro.broker.getcash())
            for d in cerebro.datas:
                pos = cerebro.broker.getposition(d)
                if pos.size > 0 and not pd.isna(d.close[0]):
                    end_val += pos.size * float(d.close[0])
        if pd.isna(end_val) or end_val <= 0:
            t = strat.analyzers.trades.get_analysis()
            pnl = t.get("pnl", {}).get("net", {}).get("total", 0) or 0
            end_val = start_val + float(pnl)

        total_return = ((end_val - start_val) / start_val) * 100

        # CAGR
        years = self._estimate_years(price_data)
        cagr = ((end_val / start_val) ** (1 / years) - 1) * 100 if years > 0 and end_val > 0 else 0.0

        # Sharpe — try backtrader, fall back to manual
        sharpe_dict = strat.analyzers.sharpe.get_analysis()
        sharpe = sharpe_dict.get("sharperatio")
        if sharpe is None or pd.isna(sharpe):
            # Manual Sharpe from trade returns
            sharpe = self._manual_sharpe(strat, years)

        # Drawdown
        dd_dict = strat.analyzers.drawdown.get_analysis()
        max_dd = dd_dict.get("max", {}).get("drawdown", 0) or 0

        # Trade stats
        td = strat.analyzers.trades.get_analysis()
        total_trades = td.get("total", {}).get("total", 0) or 0
        won = td.get("won", {}).get("total", 0) or 0
        lost = td.get("lost", {}).get("total", 0) or 0
        win_rate = (won / total_trades * 100) if total_trades > 0 else 0

        wpnl = td.get("won", {}).get("pnl", {})
        lpnl = td.get("lost", {}).get("pnl", {})
        avg_win = float(wpnl.get("average", 0) or 0)
        avg_loss = abs(float(lpnl.get("average", 0) or 0))

        gw = float(wpnl.get("total", 0) or 0)
        gl = abs(float(lpnl.get("total", 0) or 0))
        profit_factor = gw / gl if gl > 0 else (float("inf") if gw > 0 else 0.0)

        # Benchmark
        bench = self._calc_benchmark(price_data)

        return {
            "total_return_pct": round(total_return, 2),
            "cagr_pct": round(cagr, 2),
            "sharpe_ratio": round(float(sharpe or 0), 3),
            "max_drawdown_pct": round(float(abs(max_dd or 0)), 2),
            "win_rate_pct": round(win_rate, 1),
            "total_trades": total_trades,
            "won_trades": won,
            "lost_trades": lost,
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "profit_factor": round(float(profit_factor), 2),
            "benchmark_return_pct": round(bench, 2),
            "alpha_pct": round(total_return - bench, 2),
            "final_value": round(end_val, 2),
            "start_value": round(start_val, 2),
            "years": round(years, 2),
        }

    def _manual_sharpe(self, strat, years: float) -> float:
        """Calculate Sharpe from trade P&L list when analyzer fails."""
        try:
            td = strat.analyzers.trades.get_analysis()
            # Try to extract closed trade P&Ls
            closed = td.get("closed", [])
            if not closed:
                # Fall back: estimate from won/lost stats
                wpnl = td.get("won", {}).get("pnl", {})
                lpnl = td.get("lost", {}).get("pnl", {})
                avg_w = float(wpnl.get("average", 0) or 0)
                avg_l = abs(float(lpnl.get("average", 0) or 0))
                won = td.get("won", {}).get("total", 0) or 0
                lost = td.get("lost", {}).get("total", 0) or 0
                if won + lost == 0:
                    return 0.0
                mean_return = (avg_w * won - avg_l * lost) / (won + lost)
                # Approximate std dev
                returns = [avg_w] * int(won) + [-avg_l] * int(lost)
                std = np.std(returns) if returns else 1
                if std == 0:
                    return 0.0
                daily_sharpe = mean_return / std
                return round(daily_sharpe * np.sqrt(252), 3)
        except Exception:
            pass
        return 0.0

    def _estimate_years(self, price_data: dict) -> float:
        max_days = 0
        for df in price_data.values():
            if not df.empty:
                days = (df.index[-1] - df.index[0]).days
                max_days = max(max_days, days)
        return max_days / 365.25

    def _calc_benchmark(self, price_data: dict) -> float:
        returns = []
        for df in price_data.values():
            if df.empty or len(df) < 2:
                continue
            start = df["Close"].iloc[0]
            end = df["Close"].iloc[-1]
            if start > 0:
                returns.append((end - start) / start * 100)
        return sum(returns) / len(returns) if returns else 0.0
