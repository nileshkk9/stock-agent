#!/usr/bin/env python3
"""Run 5-year backtest with LLM-generated signals vs Nifty 50 benchmark."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
from rich.console import Console
from rich.table import Table

from src.config import config, load_universe
from src.data.nse_fetcher import NSEFetcher
from src.backtest.engine import BacktestEngine

console = Console()


def main():
    console.print("[bold]Stock Agent — 5-Year Backtest[/bold]\n")

    risk_cfg = config.risk_profile_config
    profile = config.analysis.risk_profile
    console.print(f"Risk Profile: [cyan]{profile}[/cyan]")
    console.print(f"Max Position: [cyan]{risk_cfg.max_position_pct}%[/cyan]")
    console.print(f"Stop Loss: [cyan]{risk_cfg.stop_loss_pct}%[/cyan]\n")

    # Load universe
    universe = load_universe()
    tickers = universe.get("nifty50", [])[:10]  # Top 10 for demo

    if not tickers:
        console.print("[red]No tickers in universe. Check config/universe.yaml[/red]")
        return

    console.print(f"Testing on {len(tickers)} stocks: {', '.join(tickers)}\n")

    # Fetch data
    fetcher = NSEFetcher()
    price_data = {}
    for ticker in tickers:
        console.print(f"Fetching {ticker}...", end=" ")
        df = fetcher.get_historical(ticker, period="5y")
        if not df.empty:
            price_data[ticker] = df
            console.print(f"[green]{len(df)} days[/green]")
        else:
            console.print(f"[red]No data[/red]")

    if len(price_data) < 2:
        console.print("[red]Need at least 2 stocks with data to run backtest[/red]")
        return

    # Generate mock signals (real version uses LLM agents on each date)
    # For now, a simple strategy: buy if price > 200-day MA, sell if < 50-day MA
    signals = {}
    for ticker, df in price_data.items():
        df = df.copy()
        if "Close" not in df.columns or len(df) < 200:
            continue

        df["sma50"] = df["Close"].rolling(50).mean()
        df["sma200"] = df["Close"].rolling(200).mean()

        for idx in range(200, len(df)):
            date_str = df.index[idx].strftime("%Y-%m-%d") if hasattr(df.index[idx], "strftime") else str(df.index[idx])[:10]

            if date_str not in signals:
                signals[date_str] = {}

            close = df["Close"].iloc[idx]
            sma50 = df["sma50"].iloc[idx]
            sma200 = df["sma200"].iloc[idx]

            # Golden cross: BUY signal
            if sma50 > sma200 and df["sma50"].iloc[idx - 1] <= df["sma200"].iloc[idx - 1]:
                signals[date_str][ticker] = {"action": "BUY", "confidence": 70}
            # Death cross: SELL signal
            elif sma50 < sma200 and df["sma50"].iloc[idx - 1] >= df["sma200"].iloc[idx - 1]:
                signals[date_str][ticker] = {"action": "SELL", "confidence": 70}

    console.print(f"\nGenerated {len(signals)} days of signals\n")

    # Run backtest
    engine = BacktestEngine(initial_cash=config.paper_trading.initial_capital)
    results = engine.run(
        price_data=price_data,
        signals=signals,
        max_position_pct=risk_cfg.max_position_pct,
        stop_loss_pct=risk_cfg.stop_loss_pct,
    )

    # Display results
    table = Table(title="Backtest Results (5 Years)")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="bold", justify="right")

    alpha = results["alpha_pct"]
    alpha_style = "[green]" if alpha > 0 else "[red]"

    table.add_row("Total Return", f"{results['total_return_pct']:+.1f}%")
    table.add_row("CAGR", f"{results['cagr_pct']:+.1f}%")
    table.add_row("Sharpe Ratio", f"{results['sharpe_ratio']:.2f}")
    table.add_row("Max Drawdown", f"-{results['max_drawdown_pct']:.1f}%")
    table.add_row("Win Rate", f"{results['win_rate_pct']:.0f}%")
    table.add_row("Total Trades", str(results["total_trades"]))
    table.add_row("Nifty 50 Benchmark", f"{results['benchmark_return_pct']:+.1f}%")
    table.add_row(f"{alpha_style}Alpha[/{alpha_style}]", f"{alpha_style}{alpha:+.1f}%[/{alpha_style}]")
    table.add_row("Final Value", f"₹{results['final_value']:,.0f}")

    console.print(table)

    if alpha > 0:
        console.print(f"\n[green]🎉 Strategy BEATS Nifty 50 by {alpha:.1f}%![/green]")
    else:
        console.print(f"\n[red]Strategy underperforms Nifty 50 by {abs(alpha):.1f}%[/red]")


if __name__ == "__main__":
    main()
