#!/usr/bin/env python3
"""Analyze a single stock using all LLM agents."""

import argparse
import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data.nse_fetcher import NSEFetcher
from src.agents.fundamental import FundamentalAnalyst
from src.agents.technical import TechnicalAnalyst
from src.agents.sentiment import SentimentAnalyst
from src.agents.macro import MacroAnalyst
from src.agents.researcher import ResearcherAgent
from src.agents.risk_manager import RiskManager
from src.agents.portfolio_manager import PortfolioManager
from rich.console import Console
from rich.table import Table

console = Console()


async def analyze(ticker: str):
    """Run full analysis pipeline on a stock."""
    fetcher = NSEFetcher()

    # 1. Fetch data
    console.print(f"[bold]Fetching data for {ticker}...[/bold]")
    fundamentals = fetcher.get_fundamentals(ticker)
    price_df = fetcher.get_historical(ticker, period="6mo")
    current_price = fetcher.get_current_price(ticker)

    if not current_price:
        console.print(f"[red]Could not get price for {ticker}[/red]")
        return

    console.print(f"[green]Current Price: ₹{current_price:,.2f}[/green]")

    # 2. Run analysts
    console.print("\n[bold]Running analysis agents...[/bold]")

    fund_agent = FundamentalAnalyst()
    tech_agent = TechnicalAnalyst()
    sent_agent = SentimentAnalyst()
    macro_agent = MacroAnalyst()

    fund_result = fund_agent.analyze(ticker, {"fundamentals": fundamentals})
    tech_result = tech_agent.analyze(ticker, {"price_df": price_df})
    sent_result = sent_agent.analyze(ticker, {"news": []})
    macro_result = macro_agent.analyze(ticker, {
        "sector": fundamentals.get("sector", "Unknown"),
        "market_news": [],
    })

    # 3. Researcher debate
    researcher = ResearcherAgent()
    research_result = researcher.analyze(ticker, {
        "fundamental": fund_result,
        "technical": tech_result,
        "sentiment": sent_result,
        "macro": macro_result,
    })

    # 4. Risk Manager
    risk_mgr = RiskManager()
    risk_result = risk_mgr.analyze(ticker, {
        "researcher": research_result,
        "fundamentals": fundamentals,
        "portfolio": {},
    })

    # 5. Portfolio Manager
    pm = PortfolioManager()
    pm_result = pm.analyze(ticker, {
        "researcher": research_result,
        "risk_manager": risk_result,
        "current_price": current_price,
        "portfolio": {},
    })

    # Display results
    console.print("\n")
    table = Table(title=f"{ticker} Analysis Summary")
    table.add_column("Agent", style="cyan")
    table.add_column("Rating", style="bold")
    table.add_column("Score", justify="right")
    table.add_column("Confidence", justify="right")

    table.add_row("Fundamental", fund_result.get("rating", "N/A"),
                  str(fund_result.get("score", "N/A")), str(fund_result.get("confidence", "N/A")))
    table.add_row("Technical", tech_result.get("rating", "N/A"),
                  str(tech_result.get("score", "N/A")), str(tech_result.get("confidence", "N/A")))
    table.add_row("Sentiment", sent_result.get("rating", "N/A"),
                  str(sent_result.get("score", "N/A")), str(sent_result.get("confidence", "N/A")))
    table.add_row("Macro", macro_result.get("rating", "N/A"),
                  str(macro_result.get("score", "N/A")), str(macro_result.get("confidence", "N/A")))
    table.add_row("---", "---", "---", "---")
    table.add_row("[bold]Researcher[/bold]", f"[bold]{research_result.get('recommendation', 'N/A')}[/bold]",
                  str(research_result.get("weighted_score", "N/A")), str(research_result.get("confidence", "N/A")))
    table.add_row("[bold]Risk Manager[/bold]",
                  f"[bold]{risk_result.get('risk_level', 'N/A')}[/bold]",
                  str(risk_result.get("risk_score", "N/A")), "N/A")
    table.add_row("[bold]Portfolio Mgr[/bold]",
                  f"[bold]{pm_result.get('action', 'N/A')}[/bold]",
                  str(pm_result.get("amount", "N/A")), "N/A")

    console.print(table)

    console.print(f"\n[bold]Verdict:[/bold] {research_result.get('verdict', 'N/A')}")
    console.print(f"[bold]Action:[/bold] {pm_result.get('action', 'N/A')} — {pm_result.get('reasoning', 'N/A')}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Analyze a stock using LLM agents")
    parser.add_argument("ticker", nargs="?", help="NSE stock ticker (e.g., RELIANCE, TCS)")
    args = parser.parse_args()

    if not args.ticker:
        ticker = input("Enter NSE ticker: ").strip().upper()
    else:
        ticker = args.ticker.upper()

    asyncio.run(analyze(ticker))
