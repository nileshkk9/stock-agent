#!/usr/bin/env python3
"""Start paper trading simulation and send daily signals."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from rich.console import Console
from rich.table import Table

from src.config import config
from src.data.nse_fetcher import NSEFetcher
from src.paper_trading.broker import PaperBroker, PaperPortfolio, _is_market_open
from src.reporting.telegram_bot import TelegramReporter

console = Console()


def main():
    console.print("[bold cyan]Stock Agent — Paper Trading[/bold cyan]\n")

    # Initialize
    broker = PaperBroker()
    portfolio = PaperPortfolio()
    fetcher = NSEFetcher()
    reporter = TelegramReporter(config.telegram.bot_token, config.telegram.chat_id)

    # Show broker status
    market_status = "🟢 OPEN" if _is_market_open() else "🔴 CLOSED"

    table = Table(title="Paper Trading Status")
    table.add_column("Item", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("Broker", broker.active_broker)
    table.add_row("Connected", str(broker.is_connected))
    table.add_row("Market", market_status)
    table.add_row("Initial Capital", f"₹{portfolio.initial_cash:,.0f}")
    console.print(table)

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
        console.print("\n[bold]Holdings:[/bold]")
        for h in summary["holdings"]:
            pnl_emoji = "🟢" if h["pnl"] > 0 else "🔴"
            console.print(
                f"  {h['ticker']}: {h['quantity']} × ₹{h['current_price']:,.2f} = ₹{h['value']:,.0f} "
                f"({pnl_emoji} {h['pnl_pct']:+.1f}%)"
            )

    # Send update to Telegram
    if config.telegram.bot_token:
        reporter.send_portfolio_update(summary)

    console.print(
        f"\n[yellow]Paper trading active. Analysis runs every {config.analysis.interval_days} days.[/yellow]"
    )
    console.print(
        "[dim]Set PAPER_TRADING_BROKER=dhan (or local) in .env to choose backend.[/dim]"
    )


if __name__ == "__main__":
    main()
