#!/usr/bin/env python3
"""
Stock Agent — Live Status Bot

A Telegram bot that responds to commands for instant portfolio & price checks.
Runs as a background daemon.

Commands:
    /status   — Portfolio summary + today's P&L
    /holdings — Detailed holdings with live prices & P&L
    /price TICKER — Current price of any NSE stock
    /orders   — Today's paper trade orders
    /report   — Full daily report
    /watchlist — Prices for your watchlist
    /help     — Show all commands

Usage:
    python scripts/telegram_bot.py
    (runs forever, Ctrl+C to stop)
"""

import asyncio
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from src.config import config, load_universe
from src.data.nse_fetcher import NSEFetcher
from src.paper_trading.broker import PaperPortfolio, _is_market_open

# ── Helpers ───────────────────────────────────────────────────────────


def _emoji_pnl(value: float) -> str:
    if value > 0:
        return "🟢"
    elif value < 0:
        return "🔴"
    return "⚪"


def _fmt_rupees(value: float) -> str:
    """Format as ₹ with Indian number grouping."""
    if abs(value) >= 10000000:  # 1 Cr+
        return f"₹{value/10000000:.2f} Cr"
    elif abs(value) >= 100000:
        return f"₹{value/100000:,.2f} L"
    return f"₹{value:,.0f}"


# ── Command Handlers ───────────────────────────────────────────────────


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send welcome message."""
    await update.message.reply_text(
        "🚀 *Stock Agent — Live Status*\n\n"
        "Commands:\n"
        "/status — Portfolio & today's P&L\n"
        "/holdings — All holdings with live prices\n"
        "/price TICKER — Live price (e.g. /price RELIANCE)\n"
        "/orders — Today's trades\n"
        "/report — Full daily report\n"
        "/watchlist — Your watchlist prices\n"
        "/help — This message",
        parse_mode="Markdown",
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show portfolio summary + today's P&L."""
    await update.message.chat.send_action("typing")

    fetcher = NSEFetcher()
    portfolio = PaperPortfolio()

    # Get prices for holdings
    prices = {}
    for ticker in portfolio.holdings:
        price = fetcher.get_current_price(ticker)
        if price:
            prices[ticker] = price

    summary = portfolio.get_summary(prices)
    daily = portfolio.get_daily_pnl(prices)
    market = "🟢 OPEN" if _is_market_open() else "🔴 CLOSED"

    total = summary["total_value"]
    pnl_e = _emoji_pnl(summary["pnl"])

    lines = [
        f"📊 *Portfolio Status* — {market}",
        f"",
        f"💼 Total: *{_fmt_rupees(total)}*",
        f"💰 Cash: {_fmt_rupees(summary['cash'])}",
        f"📦 Holdings: {_fmt_rupees(summary['holdings_value'])}",
        f"{pnl_e} Total P&L: {summary['pnl']:+,.0f} ({summary['pnl_pct']:+.1f}%)",
    ]

    if not daily.get("new"):
        dp_e = _emoji_pnl(daily["daily_pnl"])
        lines.append(f"{dp_e} Today: {daily['daily_pnl']:+,.0f} ({daily['daily_pnl_pct']:+.2f}%)")

    lines.append(f"")
    lines.append(f"📈 Holdings: {len(summary.get('holdings', []))} stocks")

    if summary.get("holdings"):
        lines.append("")
        for h in summary["holdings"][:10]:
            e = _emoji_pnl(h["pnl"])
            lines.append(
                f"  {e} *{h['ticker']}*: {h['quantity']} × ₹{h['current_price']:,.2f} "
                f"= {_fmt_rupees(h['value'])} ({h['pnl_pct']:+.1f}%)"
            )

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def holdings_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show detailed holdings with live prices."""
    await update.message.chat.send_action("typing")

    fetcher = NSEFetcher()
    portfolio = PaperPortfolio()

    if not portfolio.holdings:
        await update.message.reply_text("📦 No holdings — all cash.")
        return

    lines = ["📦 *Holdings* — Live Prices\n"]
    total_value = 0

    for ticker, h in portfolio.holdings.items():
        price = fetcher.get_current_price(ticker)
        if not price:
            price = h["avg_price"]

        value = h["quantity"] * price
        cost = h["quantity"] * h["avg_price"]
        pnl = value - cost
        pnl_pct = (price / h["avg_price"] - 1) * 100
        total_value += value
        e = _emoji_pnl(pnl)

        lines.append(
            f"*{ticker}*: {h['quantity']} shares"
        )
        lines.append(
            f"  Avg: ₹{h['avg_price']:,.2f} → Now: ₹{price:,.2f} "
            f"({e} {pnl_pct:+.1f}%)"
        )
        lines.append(
            f"  Value: {_fmt_rupees(value)} | P&L: {pnl:+,.0f}"
        )
        lines.append("")

    lines.append(f"━━━━━━━━━━━━━━")
    lines.append(f"💼 Total holdings: {_fmt_rupees(total_value)}")

    # Split into chunks if too long (Telegram limit: 4096 chars)
    msg = "\n".join(lines)
    if len(msg) > 4000:
        # Send just the summary
        short = [f"📦 *{len(portfolio.holdings)} Holdings*\n"]
        for ticker, h in portfolio.holdings.items():
            price = fetcher.get_current_price(ticker) or h["avg_price"]
            pnl_pct = (price / h["avg_price"] - 1) * 100
            e = _emoji_pnl(price - h["avg_price"])
            short.append(f"  {e} {ticker}: {h['quantity']} × ₹{price:,.2f} ({pnl_pct:+.1f}%)")
        await update.message.reply_text("\n".join(short), parse_mode="Markdown")
    else:
        await update.message.reply_text(msg, parse_mode="Markdown")


async def price_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get live price for a ticker. Usage: /price RELIANCE"""
    if not context.args:
        await update.message.reply_text("Usage: /price TICKER\nExample: /price RELIANCE")
        return

    ticker = context.args[0].upper()
    await update.message.chat.send_action("typing")

    fetcher = NSEFetcher()
    price = fetcher.get_current_price(ticker)

    if price:
        info = fetcher.get_fundamentals(ticker)
        pe = info.get("pe_ratio", "N/A")
        mcap = info.get("market_cap", "N/A")
        if isinstance(mcap, (int, float)):
            mcap = _fmt_rupees(mcap)

        await update.message.reply_text(
            f"📈 *{ticker}*\n"
            f"💰 Price: *₹{price:,.2f}*\n"
            f"📊 P/E: {pe if pe else 'N/A'}\n"
            f"🏢 Mkt Cap: {mcap}\n"
            f"🕐 Last updated: just now",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text(f"❌ Could not fetch price for {ticker}")


async def orders_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show today's paper trade orders."""
    portfolio = PaperPortfolio()
    orders = portfolio.get_todays_orders()

    if not orders:
        await update.message.reply_text("📋 No orders placed today.")
        return

    lines = [f"📋 *Today's Orders ({len(orders)})*\n"]
    for o in orders:
        emoji = "🟢" if o["action"].upper() == "BUY" else "🔴"
        qty = o.get("filled_quantity", o["quantity"])
        price = o.get("filled_price", o["price"])
        status = o.get("status", "?")

        lines.append(
            f"{emoji} *{o['action']}* {o['ticker']}: {qty} × ₹{price:,.2f} = ₹{qty*price:,.0f}"
        )
        if o.get("slippage_pct"):
            lines.append(f"  Slip: {o['slippage_pct']}% | Brkg: ₹{o.get('brokerage', 0)} | {status}")
        lines.append("")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def report_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Full daily report (same as cron output)."""
    await update.message.chat.send_action("typing")
    await status(update, context)
    await orders_cmd(update, context)


async def watchlist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show prices for watchlist + Nifty top movers."""
    await update.message.chat.send_action("typing")

    universe = load_universe()
    watchlist = universe.get("watchlist", [])
    nifty = universe.get("nifty50", [])[:5]

    tickers = watchlist + nifty
    if not tickers:
        await update.message.reply_text("No watchlist configured. Add tickers to config/universe.yaml")
        return

    fetcher = NSEFetcher()
    lines = ["📋 *Watchlist Prices*\n"]

    for ticker in tickers:
        price = fetcher.get_current_price(ticker)
        if price:
            lines.append(f"  • *{ticker}*: ₹{price:,.2f}")
        else:
            lines.append(f"  • *{ticker}*: N/A")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def compare_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show A/B strategy comparison — Rules vs LLM."""
    await update.message.chat.send_action("typing")

    try:
        from scripts.run_comparison import ComparisonTracker
        tracker = ComparisonTracker()
        report = tracker.get_comparison_report()
        await update.message.reply_text(report, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(
            f"⚔️ *Strategy Battle*\n\n"
            f"No comparison data yet. Run:\n"
            f"`python scripts/run_comparison.py`\n\n"
            f"Error: {e}",
            parse_mode="Markdown",
        )


async def battle_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Quick leaderboard only."""
    await update.message.chat.send_action("typing")
    try:
        from scripts.run_comparison import ComparisonTracker
        tracker = ComparisonTracker()
        lb = tracker.get_leaderboard()
        await update.message.reply_text(lb, parse_mode="Markdown")
    except Exception:
        await update.message.reply_text("No battle data yet. Run `python scripts/run_comparison.py` first.")


# ── Main ───────────────────────────────────────────────────────────────


def main():
    token = config.telegram.bot_token
    if not token:
        print("❌ TELEGRAM_BOT_TOKEN not set in .env")
        sys.exit(1)

    app = Application.builder().token(token).build()

    # Register command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("holdings", holdings_cmd))
    app.add_handler(CommandHandler("price", price_cmd))
    app.add_handler(CommandHandler("orders", orders_cmd))
    app.add_handler(CommandHandler("report", report_cmd))
    app.add_handler(CommandHandler("watchlist", watchlist_cmd))
    app.add_handler(CommandHandler("compare", compare_cmd))
    app.add_handler(CommandHandler("battle", battle_cmd))

    print("🚀 Stock Agent Bot is running...")
    print("   Commands: /status /holdings /price /orders /report /watchlist /compare /battle")
    print("   Press Ctrl+C to stop")
    print()

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
