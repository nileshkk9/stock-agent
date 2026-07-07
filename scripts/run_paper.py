#!/usr/bin/env python3
"""Start paper trading simulation and send daily signals."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from rich.console import Console

from src.config import config
from src.data.nse_fetcher import NSEFetcher
from src.paper_trading.broker import PaperBroker, PaperPortfolio
from src.reporting.telegram_bot import TelegramReporter

console = Console()


def main():
    console.print("[bold]Stock Agent — Paper Trading[/bold]\n")

    # Initialize
    broker = PaperBroker()
    portfolio = PaperPortfolio()
    fetcher = NSEFetcher()
    reporter = TelegramReporter(config.telegram.bot_token, config.telegram.chat_id)

    # Connect to Kite if available
    if config.kite.api_key:
        connected = broker.connect()
        if connected:
            console.print("[green]Connected to Kite sandbox[/green]")
        else:
            console.print("[yellow]Using local paper trading simulator[/yellow]")
    else:
        console.print("[yellow]Kite not configured. Using local simulator.[/yellow]")
        console.print("Set KITE_API_KEY and KITE_API_SECRET in .env for Kite sandbox.")

    # Show current portfolio
    prices = {}
    for ticker in list(portfolio.holdings.keys()):
        price = fetcher.get_current_price(ticker)
        if price:
            prices[ticker] = price

    summary = portfolio.get_summary(prices)

    console.print(f"\n💰 Cash: ₹{summary['cash']:,.0f}")
    console.print(f"📦 Holdings: ₹{summary['holdings_value']:,.0f}")
    console.print(f"💼 Total: ₹{summary['total_value']:,.0f}")
    console.print(f"📈 P&L: ₹{summary['pnl']:+,.0f} ({summary['pnl_pct']:+.1f}%)")

    if summary["holdings"]:
        console.print("\nHoldings:")
        for h in summary["holdings"]:
            pnl_emoji = "🟢" if h["pnl"] > 0 else "🔴"
            console.print(
                f"  {h['ticker']}: {h['quantity']} × ₹{h['current_price']:,.2f} = ₹{h['value']:,.0f} "
                f"({pnl_emoji} {h['pnl_pct']:+.1f}%)"
            )

    # Send update to Telegram
    if config.telegram.bot_token:
        reporter.send_portfolio_update(summary)

    console.print("\n[yellow]Paper trading mode active. Signals check runs every {} days.[/yellow]".format(
        config.analysis.interval_days
    ))


if __name__ == "__main__":
    main()
