#!/usr/bin/env python3
"""
Stock Agent — 5-Year Backtest: Nifty 50

Strategies tested:
    1. Momentum Ranking 🆕 — top 10 stocks by 6mo+3mo momentum, monthly rotation
    2. Trend + Momentum — SMA50/200 + ROC filter
    3. MA Crossover — Golden/Death Cross
    4. RSI Mean Reversion — oversold/overbought
    5. Buy & Hold — equal-weight, never sell (benchmark)

Output: head-to-head comparison vs Nifty 50 index
"""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import yfinance as yf
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn

from src.config import config
from src.data.nse_fetcher import NSEFetcher
from src.backtest.engine import BacktestEngine

console = Console()


def fetch_nifty_return() -> float:
    try:
        nifty = yf.Ticker("^NSEI")
        df = nifty.history(period="5y")
        if not df.empty and len(df) > 100:
            return ((df["Close"].iloc[-1] - df["Close"].iloc[0]) / df["Close"].iloc[0]) * 100
    except Exception:
        pass
    return 0.0


def generate_ma_signals(price_data: dict) -> dict:
    signals = {}
    for ticker, df in price_data.items():
        df = df.copy()
        df["sma50"] = df["Close"].rolling(50).mean()
        df["sma200"] = df["Close"].rolling(200).mean()
        for idx in range(200, len(df)):
            dt = str(df.index[idx])[:10]
            signals.setdefault(dt, {})
            s50, s200 = df["sma50"].iloc[idx], df["sma200"].iloc[idx]
            p50, p200 = df["sma50"].iloc[idx - 1], df["sma200"].iloc[idx - 1]
            if s50 > s200 and p50 <= p200:
                signals[dt][ticker] = {"action": "BUY", "confidence": 70}
            elif s50 < s200 and p50 >= p200:
                signals[dt][ticker] = {"action": "SELL", "confidence": 70}
    return signals


def generate_rsi_signals(price_data: dict) -> dict:
    signals = {}
    for ticker, df in price_data.items():
        df = df.copy()
        delta = df["Close"].diff()
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta).where(delta < 0, 0.0)
        rs = gain.rolling(14).mean() / loss.rolling(14).mean().replace(0, float("nan"))
        df["rsi"] = 100 - (100 / (1 + rs))
        for idx in range(50, len(df)):
            dt = str(df.index[idx])[:10]
            signals.setdefault(dt, {})
            rsi, prsi = df["rsi"].iloc[idx], df["rsi"].iloc[idx - 1]
            if pd.isna(rsi) or pd.isna(prsi):
                continue
            if rsi > 30 and prsi <= 30:
                signals[dt][ticker] = {"action": "BUY", "confidence": 65}
            elif rsi < 70 and prsi >= 70:
                signals[dt][ticker] = {"action": "SELL", "confidence": 65}
    return signals


def main():
    console.print(Panel.fit(
        "[bold cyan]📊 5-Year Nifty 50 Backtest[/bold cyan]\n[dim]5 strategies × 50 stocks[/dim]",
        border_style="cyan",
    ))

    risk = config.risk_profile_config
    console.print(f"Risk: [yellow]{config.analysis.risk_profile}[/yellow] | "
                  f"Stop Loss: {risk.stop_loss_pct}% | "
                  f"Capital: ₹{config.paper_trading.initial_capital:,.0f}\n")

    # ═══ FETCH DATA ═══
    tickers = NSEFetcher.get_nifty50_symbols()
    fetcher = NSEFetcher()
    price_data = {}

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
                  BarColumn(), TextColumn("{task.percentage:>3.0f}%"), console=console) as prog:
        task = prog.add_task("Downloading 5yr data...", total=len(tickers))
        for t in tickers:
            prog.update(task, description=f"[dim]{t}[/dim]")
            df = fetcher.get_historical(t, period="5y")
            if not df.empty and len(df) >= 200:
                price_data[t] = df
            prog.advance(task)

    console.print(f"\n✅ {len(price_data)}/{len(tickers)} stocks downloaded\n")

    nifty_ret = fetch_nifty_return()
    console.print(f"[bold]Nifty 50 Index (5yr):[/bold] [blue]{nifty_ret:+.1f}%[/blue]\n")

    engine = BacktestEngine(initial_cash=config.paper_trading.initial_capital)
    results = {}

    # ── Strategy 1: Momentum Ranking 🆕 ──
    console.print("[bold cyan]1. Momentum Ranking[/bold cyan] (top 10, monthly rotation)")
    r1 = engine.run(price_data, strategy="momentum_ranking", top_n=10,
                    max_position_pct=10, stop_loss_pct=risk.stop_loss_pct)
    results["Momentum Rank"] = r1
    console.print(f"   {'🟢' if r1['total_return_pct']>0 else '🔴'} "
                  f"Return: {r1['total_return_pct']:+.1f}% | CAGR: {r1['cagr_pct']:+.1f}% | "
                  f"Sharpe: {r1['sharpe_ratio']:.2f} | DD: {r1['max_drawdown_pct']:.1f}% | "
                  f"Trades: {r1['total_trades']} | Win: {r1['win_rate_pct']:.0f}%\n")

    # ── Strategy 2: Trend + Momentum ──
    console.print("[bold cyan]2. Trend + Momentum[/bold cyan] (SMA50/200 + ROC)")
    r2 = engine.run(price_data, strategy="trend_momentum",
                    max_position_pct=risk.max_position_pct, stop_loss_pct=risk.stop_loss_pct)
    results["Trend+Momentum"] = r2
    console.print(f"   {'🟢' if r2['total_return_pct']>0 else '🔴'} "
                  f"Return: {r2['total_return_pct']:+.1f}% | CAGR: {r2['cagr_pct']:+.1f}% | "
                  f"Sharpe: {r2['sharpe_ratio']:.2f} | DD: {r2['max_drawdown_pct']:.1f}% | "
                  f"Trades: {r2['total_trades']} | Win: {r2['win_rate_pct']:.0f}%\n")

    # ── Strategy 3: MA Crossover ──
    console.print("[bold cyan]3. MA Crossover[/bold cyan] (50/200 Golden Cross)")
    sig_ma = generate_ma_signals(price_data)
    r3 = engine.run(price_data, signals=sig_ma, strategy="signal",
                    max_position_pct=risk.max_position_pct, stop_loss_pct=risk.stop_loss_pct)
    results["MA Crossover"] = r3
    console.print(f"   {'🟢' if r3['total_return_pct']>0 else '🔴'} "
                  f"Return: {r3['total_return_pct']:+.1f}% | CAGR: {r3['cagr_pct']:+.1f}% | "
                  f"Sharpe: {r3['sharpe_ratio']:.2f} | DD: {r3['max_drawdown_pct']:.1f}% | "
                  f"Trades: {r3['total_trades']} | Win: {r3['win_rate_pct']:.0f}%\n")

    # ── Strategy 4: RSI ──
    console.print("[bold cyan]4. RSI Mean Reversion[/bold cyan] (30/70)")
    sig_rsi = generate_rsi_signals(price_data)
    r4 = engine.run(price_data, signals=sig_rsi, strategy="signal",
                    max_position_pct=risk.max_position_pct, stop_loss_pct=risk.stop_loss_pct)
    results["RSI (30/70)"] = r4
    console.print(f"   {'🟢' if r4['total_return_pct']>0 else '🔴'} "
                  f"Return: {r4['total_return_pct']:+.1f}% | CAGR: {r4['cagr_pct']:+.1f}% | "
                  f"Sharpe: {r4['sharpe_ratio']:.2f} | DD: {r4['max_drawdown_pct']:.1f}% | "
                  f"Trades: {r4['total_trades']} | Win: {r4['win_rate_pct']:.0f}%\n")

    # ── Strategy 5: Buy & Hold ──
    console.print("[bold cyan]5. Buy & Hold[/bold cyan] (equal-weight, never sell)")
    r5 = engine.run(price_data, strategy="buy_hold",
                    max_position_pct=100/len(price_data), stop_loss_pct=99)
    results["Buy & Hold"] = r5
    console.print(f"   {'🟢' if r5['total_return_pct']>0 else '🔴'} "
                  f"Return: {r5['total_return_pct']:+.1f}% | CAGR: {r5['cagr_pct']:+.1f}% | "
                  f"Sharpe: {r5['sharpe_ratio']:.2f} | DD: {r5['max_drawdown_pct']:.1f}%\n")

    # ═══ COMPARISON TABLE ═══
    console.print()
    table = Table(title="🏆 5-Year Backtest — Nifty 50 Comparison",
                  caption=f"Risk: {config.analysis.risk_profile} | "
                          f"{len(price_data)} stocks | {datetime.now().strftime('%d %b %Y')}")

    table.add_column("Metric", style="cyan", width=15)
    table.add_column("Momentum\nRank 🆕", justify="right", style="bold yellow", width=11)
    table.add_column("Trend+\nMomentum", justify="right", width=11)
    table.add_column("MA\nCross", justify="right", width=11)
    table.add_column("RSI\n30/70", justify="right", width=11)
    table.add_column("Buy &\nHold", justify="right", width=11)
    table.add_column("Nifty\n50", justify="right", style="blue", width=11)

    metrics = [
        ("Return", "total_return_pct", "%"),
        ("CAGR", "cagr_pct", "%"),
        ("Sharpe", "sharpe_ratio", ""),
        ("Max DD", "max_drawdown_pct", "%"),
        ("Win Rate", "win_rate_pct", "%"),
        ("Trades", "total_trades", ""),
        ("Profit Factor", "profit_factor", ""),
        ("Avg Win", "avg_win", "₹"),
        ("Avg Loss", "avg_loss", "₹"),
        ("Final Value", "final_value", "₹"),
        ("Alpha", "alpha_pct", "%"),
    ]

    for name, key, fmt in metrics:
        def f(r, ftype):
            v = r[key]
            if ftype == "₹":
                return f"₹{v:,.0f}"
            if ftype == "%":
                return f"{v:+.1f}%"
            return f"{v:.2f}" if isinstance(v, float) else str(v)

        table.add_row(
            name,
            f(results["Momentum Rank"], fmt),
            f(results["Trend+Momentum"], fmt),
            f(results["MA Crossover"], fmt),
            f(results["RSI (30/70)"], fmt),
            f(results["Buy & Hold"], fmt),
            f"{nifty_ret:+.1f}%" if key == "total_return_pct" and fmt == "%" else "—",
        )

    console.print(table)

    # ═══ WINNER ═══
    ranked = sorted(results.items(), key=lambda x: x[1]["cagr_pct"] or x[1]["total_return_pct"], reverse=True)
    winner = ranked[0]
    w = winner[1]

    console.print(f"\n[bold green]🏆 Best: {winner[0]}[/bold green]")
    console.print(f"   {w['total_return_pct']:+.1f}% return | {w['cagr_pct']:+.1f}% CAGR | "
                  f"Sharpe {w['sharpe_ratio']:.2f} | DD {w['max_drawdown_pct']:.1f}%")

    if w["total_return_pct"] > nifty_ret:
        diff = w["total_return_pct"] - nifty_ret
        console.print(f"   ✅ Beats Nifty 50 by [green]+{diff:.1f}%[/green]")
    else:
        diff = nifty_ret - w["total_return_pct"]
        console.print(f"   ❌ Trails Nifty 50 by [red]{diff:.1f}%[/red]")

    # 2nd best for comparison
    if len(ranked) > 1:
        r2 = ranked[1][1]
        console.print(f"\n[bold]🥈 Runner-up: {ranked[1][0]}[/bold]")
        console.print(f"   {r2['total_return_pct']:+.1f}% return | {r2['cagr_pct']:+.1f}% CAGR")
        if r2["total_return_pct"] > nifty_ret:
            console.print(f"   ✅ Also beats Nifty 50!")


if __name__ == "__main__":
    main()
