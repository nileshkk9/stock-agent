#!/usr/bin/env python3
"""Run 5-year backtest with signal-based strategies vs Nifty 50 benchmark."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import yfinance as yf
from rich.console import Console
from rich.table import Table
from rich.progress import Progress

from src.config import config, load_universe
from src.data.nse_fetcher import NSEFetcher
from src.backtest.engine import BacktestEngine

console = Console()


def fetch_nifty50_benchmark() -> float:
    """Get Nifty 50 total return over 5 years."""
    try:
        nifty = yf.Ticker("^NSEI")
        df = nifty.history(period="5y")
        if not df.empty:
            start = df["Close"].iloc[0]
            end = df["Close"].iloc[-1]
            return ((end - start) / start) * 100
    except Exception:
        pass
    return 0.0


def main():
    console.print("[bold]Stock Agent — 5-Year Backtest (Nifty 50)[/bold]\n")

    risk_cfg = config.risk_profile_config
    profile = config.analysis.risk_profile
    console.print(f"Risk Profile: [cyan]{profile}[/cyan]")
    console.print(f"Max Position: [cyan]{risk_cfg.max_position_pct}%[/cyan]")
    console.print(f"Stop Loss: [cyan]{risk_cfg.stop_loss_pct}%[/cyan]")
    console.print(f"Initial Capital: [cyan]₹{config.paper_trading.initial_capital:,.0f}[/cyan]\n")

    # Load all 50 Nifty stocks
    universe = load_universe()
    tickers = universe.get("nifty50", [])
    console.print(f"Universe: [cyan]{len(tickers)} stocks[/cyan]\n")

    # Fetch Nifty 50 benchmark return
    console.print("Fetching Nifty 50 benchmark...", end=" ")
    benchmark_return = fetch_nifty50_benchmark()
    console.print(f"[green]{benchmark_return:+.1f}%[/green]\n")

    # Fetch data for all stocks
    fetcher = NSEFetcher()
    price_data = {}
    failed = []

    with Progress() as progress:
        task = progress.add_task("[cyan]Fetching 5 years of data...", total=len(tickers))
        for ticker in tickers:
            df = fetcher.get_historical(ticker, period="5y")
            if not df.empty and len(df) >= 200:
                price_data[ticker] = df
            else:
                failed.append(ticker)
            progress.advance(task)

    console.print(f"\nFetched: [green]{len(price_data)} stocks[/green]", end="")
    if failed:
        console.print(f" | Failed: [red]{len(failed)} ({', '.join(failed[:5])}...)[/red]")
    else:
        console.print()

    if len(price_data) < 5:
        console.print("[red]Need at least 5 stocks with data[/red]")
        return

    # Strategy 1: MA Crossover (Golden Cross / Death Cross)
    console.print("\n[bold]Strategy 1: MA Crossover (50/200-day)[/bold]")
    signals_ma = {}
    for ticker, df in price_data.items():
        df = df.copy()
        df["sma50"] = df["Close"].rolling(50).mean()
        df["sma200"] = df["Close"].rolling(200).mean()

        for idx in range(200, len(df)):
            date_str = (
                df.index[idx].strftime("%Y-%m-%d")
                if hasattr(df.index[idx], "strftime")
                else str(df.index[idx])[:10]
            )
            if date_str not in signals_ma:
                signals_ma[date_str] = {}

            sma50 = df["sma50"].iloc[idx]
            sma200 = df["sma200"].iloc[idx]
            prev_sma50 = df["sma50"].iloc[idx - 1]
            prev_sma200 = df["sma200"].iloc[idx - 1]

            # Golden cross: BUY
            if sma50 > sma200 and prev_sma50 <= prev_sma200:
                signals_ma[date_str][ticker] = {"action": "BUY", "confidence": 70}
            # Death cross: SELL
            elif sma50 < sma200 and prev_sma50 >= prev_sma200:
                signals_ma[date_str][ticker] = {"action": "SELL", "confidence": 70}

    console.print(f"Generated signals for [cyan]{len(signals_ma)}[/cyan] trading days")

    engine = BacktestEngine(initial_cash=config.paper_trading.initial_capital)
    results_ma = engine.run(
        price_data=price_data,
        signals=signals_ma,
        max_position_pct=risk_cfg.max_position_pct,
        stop_loss_pct=risk_cfg.stop_loss_pct,
    )

    # Strategy 2: RSI Mean Reversion (buy oversold, sell overbought)
    console.print("\n[bold]Strategy 2: RSI Mean Reversion (30/70)[/bold]")
    signals_rsi = {}
    for ticker, df in price_data.items():
        df = df.copy()
        # Compute RSI
        delta = df["Close"].diff()
        gain = delta.where(delta > 0, 0)
        loss = (-delta).where(delta < 0, 0)
        avg_gain = gain.rolling(14).mean()
        avg_loss = loss.rolling(14).mean()
        rs = avg_gain / avg_loss
        df["rsi"] = 100 - (100 / (1 + rs))

        for idx in range(50, len(df)):
            date_str = (
                df.index[idx].strftime("%Y-%m-%d")
                if hasattr(df.index[idx], "strftime")
                else str(df.index[idx])[:10]
            )
            if date_str not in signals_rsi:
                signals_rsi[date_str] = {}

            rsi = df["rsi"].iloc[idx]
            prev_rsi = df["rsi"].iloc[idx - 1]

            # RSI crosses above 30 from below = BUY (oversold recovery)
            if rsi > 30 and prev_rsi <= 30:
                signals_rsi[date_str][ticker] = {"action": "BUY", "confidence": 65}
            # RSI crosses below 70 from above = SELL (overbought)
            elif rsi < 70 and prev_rsi >= 70:
                signals_rsi[date_str][ticker] = {"action": "SELL", "confidence": 65}

    console.print(f"Generated signals for [cyan]{len(signals_rsi)}[/cyan] trading days")

    results_rsi = engine.run(
        price_data=price_data,
        signals=signals_rsi,
        max_position_pct=risk_cfg.max_position_pct,
        stop_loss_pct=risk_cfg.stop_loss_pct,
    )

    # Display comparison
    console.print("\n")
    table = Table(title="📊 5-Year Backtest Results — All 50 Nifty Stocks")
    table.add_column("Metric", style="cyan")
    table.add_column("MA Crossover", justify="right")
    table.add_column("RSI (30/70)", justify="right")
    table.add_column("Nifty 50", justify="right")

    entries = [
        ("Total Return", f"{results_ma['total_return_pct']:+.1f}%", f"{results_rsi['total_return_pct']:+.1f}%", f"{benchmark_return:+.1f}%"),
        ("CAGR", f"{results_ma['cagr_pct']:+.1f}%", f"{results_rsi['cagr_pct']:+.1f}%", "—"),
        ("Sharpe Ratio", f"{results_ma['sharpe_ratio']:.2f}", f"{results_rsi['sharpe_ratio']:.2f}", "—"),
        ("Max Drawdown", f"-{results_ma['max_drawdown_pct']:.1f}%", f"-{results_rsi['max_drawdown_pct']:.1f}%", "—"),
        ("Win Rate", f"{results_ma['win_rate_pct']:.0f}%", f"{results_rsi['win_rate_pct']:.0f}%", "—"),
        ("Total Trades", str(results_ma["total_trades"]), str(results_rsi["total_trades"]), "—"),
        ("Final Value", f"₹{results_ma['final_value']:,.0f}", f"₹{results_rsi['final_value']:,.0f}", "—"),
    ]

    for name, ma, rsi, nifty in entries:
        table.add_row(name, ma, rsi, nifty)

    console.print(table)

    # Alpha comparison
    alpha_ma = results_ma["total_return_pct"] - benchmark_return
    alpha_rsi = results_rsi["total_return_pct"] - benchmark_return

    console.print(f"\nMA Crossover Alpha: [{'green' if alpha_ma > 0 else 'red'}]{alpha_ma:+.1f}%[/{'green' if alpha_ma > 0 else 'red'}]")
    console.print(f"RSI Strategy Alpha:  [{'green' if alpha_rsi > 0 else 'red'}]{alpha_rsi:+.1f}%[/{'green' if alpha_rsi > 0 else 'red'}]")

    console.print("\n[yellow]Note: These use simple rule-based signals. The LLM agents should produce better signals.[/yellow]")
    console.print("[yellow]Run 'python scripts/run_analysis.py TICKER' to see LLM-powered analysis.[/yellow]")


if __name__ == "__main__":
    main()
