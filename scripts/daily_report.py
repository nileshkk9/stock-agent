#!/usr/bin/env python3
"""
Daily P&L Report — portfolio snapshot, today's orders, holdings, equity curve.

Usage:
    python scripts/daily_report.py            # terminal + Telegram
    python scripts/daily_report.py --cli      # terminal only, no Telegram
    python scripts/daily_report.py --chart    # also generate equity curve chart

Runs after market close (or anytime) to give you a clear picture of:
    1. Daily P&L (today vs yesterday)
    2. Today's orders (with fills, slippage, brokerage)
    3. Current holdings (with unrealized P&L per stock)
    4. Total portfolio + equity curve trend
"""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from src.config import config
from src.data.nse_fetcher import NSEFetcher
from src.paper_trading.broker import PaperBroker, PaperPortfolio, _is_market_open
from src.reporting.telegram_bot import TelegramReporter

console = Console()

# ── Helpers ───────────────────────────────────────────────────────────


def _fmt_pnl(value: float) -> tuple[str, str]:
    """Return (emoji, formatted string) for a P&L value."""
    if value > 0:
        return "🟢", f"+₹{value:,.0f}"
    elif value < 0:
        return "🔴", f"-₹{abs(value):,.0f}"
    return "⚪", "₹0"


def _fmt_pct(value: float) -> str:
    """Return coloured percentage string."""
    if value > 0:
        return f"[green]+{value:.2f}%[/green]"
    elif value < 0:
        return f"[red]{value:.2f}%[/red]"
    return "0.00%"


def _build_telegram_message(
    daily: dict,
    summary: dict,
    todays_orders: list[dict],
    equity_curve: list[dict],
) -> str:
    """Build a formatted Telegram message for the daily report."""

    today_str = datetime.now().strftime("%d %b %Y")
    market_status = "🟢" if _is_market_open() else "🔴"

    lines = [
        f"📊 *Daily P&L Report — {today_str}*",
        f"━━━━━━━━━━━━━━━━━━━━━━",
        "",
    ]

    # Total portfolio
    total = summary["total_value"]
    total_pnl = summary["pnl"]
    total_pnl_pct = summary["pnl_pct"]
    pnl_emoji = "🟢" if total_pnl > 0 else "🔴" if total_pnl < 0 else "⚪"

    lines.append(f"💼 *Portfolio:* ₹{total:,.0f}")
    lines.append(f"📈 *Total P&L:* {pnl_emoji} ₹{total_pnl:+,.0f} ({total_pnl_pct:+.1f}%)")
    lines.append(f"💰 Cash: ₹{summary['cash']:,.0f}  |  📦 Holdings: ₹{summary['holdings_value']:,.0f}")
    lines.append("")

    # Daily P&L
    if not daily.get("new"):
        daily_pnl = daily["daily_pnl"]
        daily_pnl_pct = daily["daily_pnl_pct"]
        dp_emoji = "🟢" if daily_pnl > 0 else "🔴" if daily_pnl < 0 else "⚪"
        lines.append(f"📅 *Today's Change:* {dp_emoji} ₹{daily_pnl:+,.0f} ({daily_pnl_pct:+.2f}%)")
        if daily["realized_pnl"] != 0:
            lines.append(f"   Realized: ₹{daily['realized_pnl']:+,.0f}")
        lines.append(f"   Unrealized: ₹{daily['unrealized_pnl']:+,.0f}")
    else:
        lines.append("📅 *Today:* First day — no prior snapshot yet")
    lines.append("")

    # Today's orders
    if todays_orders:
        lines.append(f"📋 *Today's Orders ({len(todays_orders)}):*")
        for o in todays_orders:
            emoji = "🟢" if o["action"].upper() == "BUY" else "🔴"
            qty = o.get("filled_quantity", o["quantity"])
            price = o.get("filled_price", o["price"])
            status = o.get("status", "?")
            lines.append(
                f"  {emoji} {o['action']} {o['ticker']}: {qty} × ₹{price:,.2f} "
                f"= ₹{qty * price:,.0f} [{status}]"
            )
            if "slippage_pct" in o:
                lines.append(f"     Slippage: {o['slippage_pct']}% | Brokerage: ₹{o.get('brokerage', 0)}")
    else:
        lines.append("📋 *No orders today*")
    lines.append("")

    # Holdings
    if summary.get("holdings"):
        lines.append(f"📦 *Holdings ({len(summary['holdings'])}):*")
        for h in summary["holdings"]:
            pnl_e = "🟢" if h["pnl"] > 0 else "🔴" if h["pnl"] < 0 else "⚪"
            lines.append(
                f"  • {h['ticker']}: {h['quantity']} × ₹{h['current_price']:,.2f} "
                f"= ₹{h['value']:,.0f} ({pnl_e} {h['pnl_pct']:+.1f}%)"
            )
    else:
        lines.append("📦 *No holdings* — all cash")
    lines.append("")

    # Equity curve trend (last 5 days)
    if len(equity_curve) >= 2:
        recent = equity_curve[-5:]
        lines.append("📈 *Recent Trend:*")
        for e in recent:
            pct_from_start = (e["value"] / config.paper_trading.initial_capital - 1) * 100
            lines.append(f"  {e['date']}: ₹{e['value']:,.0f} ({pct_from_start:+.1f}%)")
    lines.append("")

    lines.append(f"_Next analysis in {config.analysis.interval_days} days_")

    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────


def main():
    cli_only = "--cli" in sys.argv
    show_chart = "--chart" in sys.argv

    console.print(Panel.fit("[bold cyan]Stock Agent — Daily P&L Report[/bold cyan]", border_style="cyan"))

    # Initialize
    broker = PaperBroker()
    portfolio = PaperPortfolio()
    fetcher = NSEFetcher()
    reporter = TelegramReporter(config.telegram.bot_token, config.telegram.chat_id)

    # Broker status
    market_status = "🟢 OPEN" if _is_market_open() else "🔴 CLOSED"
    console.print(f"Broker: [green]{broker.active_broker}[/green] | Market: {market_status}\n")

    # Fetch current prices for holdings
    prices = {}
    for ticker in list(portfolio.holdings.keys()):
        console.print(f"[dim]Fetching price: {ticker}...[/dim]", end=" ")
        price = fetcher.get_current_price(ticker)
        if price:
            prices[ticker] = price
            console.print(f"[green]₹{price:,.2f}[/green]")
        else:
            console.print("[red]failed[/red]")

    # ── Daily P&L ─────────────────────────────────────────────────────
    daily = portfolio.get_daily_pnl(prices)
    summary = portfolio.get_summary(prices)

    # ── Today's orders ─────────────────────────────────────────────────
    todays_orders = portfolio.get_todays_orders()

    # ── Equity curve snapshot ──────────────────────────────────────────
    portfolio.snapshot_equity(prices)
    equity_curve = portfolio.get_equity_curve()

    # ═════════════════════════════════════════════════════════════════
    # TERMINAL DISPLAY
    # ═════════════════════════════════════════════════════════════════

    # 1. Portfolio Summary Table
    table = Table(title="Portfolio Summary")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="bold")
    table.add_column("Change", style="green")

    table.add_row("Total Value", f"₹{summary['total_value']:,.0f}", "")
    table.add_row("Cash", f"₹{summary['cash']:,.0f}", "")
    table.add_row("Holdings Value", f"₹{summary['holdings_value']:,.0f}", "")
    table.add_row("Total P&L", f"₹{summary['pnl']:+,.0f}", f"{summary['pnl_pct']:+.2f}%")

    if not daily.get("new"):
        emoji, _ = _fmt_pnl(daily["daily_pnl"])
        table.add_row(
            "Today's Change",
            f"{emoji} ₹{daily['daily_pnl']:+,.0f}",
            f"{daily['daily_pnl_pct']:+.3f}%",
        )
        if daily["realized_pnl"] != 0:
            table.add_row("  └ Realized", f"₹{daily['realized_pnl']:+,.0f}", "")
        table.add_row("  └ Unrealized", f"₹{daily['unrealized_pnl']:+,.0f}", "")
    else:
        table.add_row("Today's Change", "[dim]First snapshot[/dim]", "")

    console.print(table)

    # 2. Today's Orders
    if todays_orders:
        console.print(f"\n[bold]📋 Today's Orders ({len(todays_orders)}):[/bold]")
        for o in todays_orders:
            emoji = "🟢" if o["action"].upper() == "BUY" else "🔴"
            qty = o.get("filled_quantity", o["quantity"])
            price = o.get("filled_price", o["price"])
            console.print(
                f"  {emoji} {o['action']:4} {o['ticker']:12} "
                f"{qty:4} × ₹{price:>10,.2f} = ₹{qty * price:>12,.0f} "
                f"[dim]({o.get('status', '?')})[/dim]"
            )
            if "slippage_pct" in o:
                console.print(
                    f"       Slippage: {o['slippage_pct']}% | "
                    f"Brokerage: ₹{o.get('brokerage', 0)} | "
                    f"Broker: {o.get('broker', '?')}"
                )
    else:
        console.print("\n[dim]No orders placed today[/dim]")

    # 3. Holdings
    if summary.get("holdings"):
        console.print(f"\n[bold]📦 Holdings ({len(summary['holdings'])}):[/bold]")
        htable = Table()
        htable.add_column("Ticker", style="cyan")
        htable.add_column("Qty", justify="right")
        htable.add_column("Avg ₹", justify="right")
        htable.add_column("Current ₹", justify="right")
        htable.add_column("Value", justify="right")
        htable.add_column("P&L %", justify="right")

        for h in summary["holdings"]:
            emoji = "🟢" if h["pnl"] > 0 else "🔴" if h["pnl"] < 0 else "⚪"
            htable.add_row(
                h["ticker"],
                str(h["quantity"]),
                f"{h['avg_price']:,.2f}",
                f"{h['current_price']:,.2f}",
                f"₹{h['value']:,.0f}",
                f"{emoji} {h['pnl_pct']:+.1f}%",
            )
        console.print(htable)

    # 4. Equity Curve
    if len(equity_curve) >= 2:
        console.print(f"\n[bold]📈 Equity Curve (last 7 days):[/bold]")
        start = config.paper_trading.initial_capital
        for e in equity_curve[-7:]:
            pct = (e["value"] / start - 1) * 100
            bar_len = max(0, min(30, int(pct * 3) if pct > 0 else 0))
            bar = "█" * bar_len
            emoji = "🟢" if pct >= 0 else "🔴"
            console.print(f"  {e['date']}: ₹{e['value']:>12,.0f} {emoji} {pct:+.2f}% {bar}")

    # ═════════════════════════════════════════════════════════════════
    # TELEGRAM DELIVERY
    # ═════════════════════════════════════════════════════════════════

    if not cli_only and config.telegram.bot_token:
        tg_msg = _build_telegram_message(daily, summary, todays_orders, equity_curve)
        sent = reporter.send_message(tg_msg)
        if sent:
            console.print("\n[green]✓ Report sent to Telegram[/green]")
        else:
            console.print("\n[yellow]⚠ Telegram send failed (check bot token)[/yellow]")

    # ═════════════════════════════════════════════════════════════════
    # DATA STORAGE
    # ═════════════════════════════════════════════════════════════════

    console.print(f"\n[dim]Portfolio: data/paper_portfolio.json[/dim]")
    console.print(f"[dim]Orders:    data/paper_orders.json ({len(broker.get_order_history())} total)[/dim]")
    console.print(f"[dim]Equity:    data/equity_curve.json ({len(equity_curve)} snapshots)[/dim]")


if __name__ == "__main__":
    main()
