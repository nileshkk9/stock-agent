#!/usr/bin/env python3
"""Generate and send daily stock analysis report via Telegram."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from rich.console import Console

from src.config import config, load_universe
from src.data.nse_fetcher import NSEFetcher
from src.reporting.telegram_bot import TelegramReporter

console = Console()


def main():
    console.print("[bold]Stock Agent — Daily Report[/bold]\n")

    reporter = TelegramReporter(config.telegram.bot_token, config.telegram.chat_id)

    if not config.telegram.bot_token:
        console.print("[red]TELEGRAM_BOT_TOKEN not set in .env[/red]")
        return

    # Load universe
    universe = load_universe()
    tickers = universe.get("nifty50", [])[:10]  # Top 10 for demo
    watchlist = universe.get("watchlist", [])
    all_tickers = tickers + watchlist

    fetcher = NSEFetcher()

    # Quick market summary
    console.print(f"Scanning {len(all_tickers)} stocks...\n")

    lines = ["📊 *Daily Market Scan*\n"]

    for ticker in all_tickers[:10]:  # Cap at 10 for cost
        fundamentals = fetcher.get_fundamentals(ticker)
        price = fetcher.get_current_price(ticker)

        if price:
            pe = fundamentals.get("pe_ratio", "N/A")
            lines.append(f"• *{ticker}*: ₹{price:,.2f} | PE: {pe}")
        else:
            lines.append(f"• *{ticker}*: No data")

    report = "\n".join(lines)
    console.print(report)

    reporter.send_message(report)
    console.print("\n[green]Report sent to Telegram![/green]")


if __name__ == "__main__":
    main()
