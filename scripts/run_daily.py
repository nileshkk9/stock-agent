#!/usr/bin/env python3
"""
Stock Agent — Full Daily Pipeline

Orchestrates the complete daily flow:
    1. ANALYSIS (every N days): Scan stocks → LLM agents → BUY/SELL signals
    2. EXECUTION: Place paper trades for all signals (auto, since paper = no risk)
    3. REPORTING: Daily P&L, equity curve, holdings → terminal + Telegram

Usage:
    python scripts/run_daily.py              # full run
    python scripts/run_daily.py --dry-run    # analyze only, don't place trades
    python scripts/run_daily.py --force      # force analysis even if not analysis day
    python scripts/run_daily.py --tickers RELIANCE,TCS  # analyze specific stocks only
"""

import asyncio
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn

from src.config import config, load_universe
from src.data.nse_fetcher import NSEFetcher
from src.paper_trading.broker import PaperBroker, PaperPortfolio, _is_market_open
from src.reporting.telegram_bot import TelegramReporter

console = Console()

# ── Analysis tracking file ─────────────────────────────────────────────
STATE_FILE = Path(__file__).parent.parent / "data" / "pipeline_state.json"


def _load_state() -> dict:
    """Load pipeline state (last analysis date, etc.)."""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError:
            pass
    return {"last_analysis": None, "total_analyses": 0, "total_trades": 0}


def _save_state(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, default=str))


def _should_analyze_today(state: dict, force: bool = False) -> bool:
    """Check if today is an analysis day based on interval."""
    if force:
        return True
    last = state.get("last_analysis")
    if not last:
        return True  # First run
    last_date = datetime.strptime(last, "%Y-%m-%d")
    days_since = (datetime.now() - last_date).days
    return days_since >= config.analysis.interval_days


def _is_weekend() -> bool:
    return datetime.now().weekday() >= 5


# ══════════════════════════════════════════════════════════════════════
# PHASE 1: ANALYSIS
# ══════════════════════════════════════════════════════════════════════


async def _analyze_single_stock(
    ticker: str,
    fetcher: NSEFetcher,
    portfolio_summary: dict,
) -> dict | None:
    """Run full LLM agent pipeline on a single stock. Returns signal dict or None."""
    from src.agents.fundamental import FundamentalAnalyst
    from src.agents.technical import TechnicalAnalyst
    from src.agents.sentiment import SentimentAnalyst
    from src.agents.macro import MacroAnalyst
    from src.agents.researcher import ResearcherAgent
    from src.agents.risk_manager import RiskManager
    from src.agents.portfolio_manager import PortfolioManager

    try:
        # Fetch data
        current_price = fetcher.get_current_price(ticker)
        if not current_price:
            return None

        fundamentals = fetcher.get_fundamentals(ticker)
        price_df = fetcher.get_historical(ticker, period="3mo")

        # Run agents (lightweight agents first)
        fund = FundamentalAnalyst()
        tech = TechnicalAnalyst()
        sent = SentimentAnalyst()
        macro = MacroAnalyst()

        fund_result = fund.analyze(ticker, {"fundamentals": fundamentals})
        tech_result = tech.analyze(ticker, {"price_df": price_df})
        sent_result = sent.analyze(ticker, {"news": []})
        macro_result = macro.analyze(ticker, {
            "sector": fundamentals.get("sector", "Unknown"),
            "market_news": [],
        })

        # Researcher debate
        researcher = ResearcherAgent()
        research = researcher.analyze(ticker, {
            "fundamental": fund_result,
            "technical": tech_result,
            "sentiment": sent_result,
            "macro": macro_result,
        })

        # Risk Manager
        risk_mgr = RiskManager()
        risk = risk_mgr.analyze(ticker, {
            "researcher": research,
            "fundamentals": fundamentals,
            "portfolio": portfolio_summary,
        })

        # Portfolio Manager → final decision
        pm = PortfolioManager()
        decision = pm.analyze(ticker, {
            "researcher": research,
            "risk_manager": risk,
            "current_price": current_price,
            "portfolio": portfolio_summary,
        })

        return {
            "ticker": ticker,
            "price": current_price,
            "action": decision.get("action", "HOLD"),
            "quantity": decision.get("quantity", 0),
            "amount": decision.get("amount", 0),
            "order_type": decision.get("order_type", "MARKET"),
            "reasoning": decision.get("reasoning", ""),
            "recommendation": research.get("recommendation", "HOLD"),
            "confidence": research.get("confidence", 50),
            "risk_level": risk.get("risk_level", "MEDIUM"),
        }
    except Exception as e:
        console.print(f"[red]✗ {ticker}: {e}[/red]")
        return None


async def run_analysis(universe: list[str], portfolio_summary: dict) -> list[dict]:
    """Run LLM analysis on all stocks in universe. Returns list of signals."""

    console.print(Panel("[bold cyan]Phase 1: Stock Analysis[/bold cyan]", border_style="cyan"))
    console.print(f"Universe: {len(universe)} stocks | Risk: {config.analysis.risk_profile}\n")

    fetcher = NSEFetcher()
    signals = []

    # Limit stocks to avoid excessive API costs — analyze top N by market cap
    # For now, analyze all (can add cap later)
    tickers = universe[:20]  # Cap at 20 for cost control (40 LLM calls per analysis day)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Analyzing stocks...", total=len(tickers))

        for ticker in tickers:
            progress.update(task, description=f"Analyzing {ticker}...")
            result = await _analyze_single_stock(ticker, fetcher, portfolio_summary)
            if result:
                signals.append(result)
                action_emoji = "🟢" if result["action"] == "BUY" else "🔴" if result["action"] == "SELL" else "⚪"
                console.print(
                    f"  {action_emoji} {result['ticker']:12} → {result['action']:4} "
                    f"{result.get('quantity', 0):4} shares @ ₹{result['price']:,.2f} "
                    f"[dim]({result['recommendation']}, {result['confidence']}% confidence)[/dim]"
                )
            progress.advance(task)

    # Summary
    buys = [s for s in signals if s["action"] == "BUY"]
    sells = [s for s in signals if s["action"] == "SELL"]
    holds = [s for s in signals if s["action"] == "HOLD"]

    console.print(f"\n[bold]Analysis Complete:[/bold] 🟢 {len(buys)} BUY | 🔴 {len(sells)} SELL | ⚪ {len(holds)} HOLD")

    return signals


# ══════════════════════════════════════════════════════════════════════
# PHASE 2: EXECUTION
# ══════════════════════════════════════════════════════════════════════


def execute_signals(
    signals: list[dict],
    broker: PaperBroker,
    portfolio: PaperPortfolio,
    dry_run: bool = False,
) -> list[dict]:
    """Place paper trades for all actionable signals."""

    console.print(Panel("[bold yellow]Phase 2: Trade Execution[/bold yellow]", border_style="yellow"))

    actionable = [s for s in signals if s["action"] in ("BUY", "SELL")]
    if not actionable:
        console.print("[dim]No actionable signals — nothing to execute[/dim]")
        return []

    if dry_run:
        console.print("[yellow]DRY RUN — no trades placed[/yellow]")
        for s in actionable:
            emoji = "🟢" if s["action"] == "BUY" else "🔴"
            console.print(
                f"  {emoji} [dim]WOULD[/dim] {s['action']} {s['ticker']}: "
                f"{s.get('quantity', 0)} × ₹{s['price']:,.2f} = ₹{s.get('amount', 0):,.0f}"
            )
        return []

    orders_placed = []
    market_open = _is_market_open()

    if not market_open:
        console.print("[yellow]⚠ Market closed — trades will use last known prices[/yellow]")

    for s in actionable:
        ticker = s["ticker"]
        action = s["action"]
        quantity = s.get("quantity", 0)
        price = s["price"]
        order_type = s.get("order_type", "MARKET")

        if quantity <= 0:
            console.print(f"  [dim]Skip {ticker}: zero quantity[/dim]")
            continue

        # Check portfolio limits before buying
        if action == "BUY":
            estimated_cost = price * quantity
            if estimated_cost > portfolio.cash * 0.15:  # Max 15% per trade
                console.print(f"  [yellow]Skip {ticker}: exceeds position limit (₹{estimated_cost:,.0f})[/yellow]")
                continue

        order = broker.place_order(ticker, action, quantity, price, order_type)

        if order["status"] == "EXECUTED":
            portfolio.execute_order(order)
            orders_placed.append(order)
            emoji = "🟢" if action == "BUY" else "🔴"
            console.print(
                f"  {emoji} {action} {ticker}: {quantity} × ₹{price:,.2f} = ₹{quantity * price:,.0f}"
            )
        else:
            console.print(f"  [red]✗ {action} {ticker}: {order.get('error', 'Failed')}[/red]")

    console.print(f"\n[bold]Executed:[/bold] {len(orders_placed)} trades")
    return orders_placed


# ══════════════════════════════════════════════════════════════════════
# PHASE 3: REPORTING
# ══════════════════════════════════════════════════════════════════════


def generate_report(
    portfolio: PaperPortfolio,
    signals: list[dict],
    orders: list[dict],
    broker: PaperBroker,
    reporter: TelegramReporter,
    analysis_ran: bool,
) -> str:
    """Generate and deliver the daily report."""

    console.print(Panel("[bold green]Phase 3: Daily Report[/bold green]", border_style="green"))

    # Get current prices
    fetcher = NSEFetcher()
    prices = {}
    for ticker in portfolio.holdings:
        price = fetcher.get_current_price(ticker)
        if price:
            prices[ticker] = price

    # Portfolio summary
    summary = portfolio.get_summary(prices)
    daily = portfolio.get_daily_pnl(prices)
    portfolio.snapshot_equity(prices)
    equity_curve = portfolio.get_equity_curve()

    today_str = datetime.now().strftime("%d %b %Y")

    # ── Build Telegram message ──────────────────────────────────────
    total = summary["total_value"]
    pnl_emoji = "🟢" if summary["pnl"] > 0 else "🔴" if summary["pnl"] < 0 else "⚪"
    market_status = "🟢" if _is_market_open() else "🔴"

    lines = [
        f"📊 *Daily Report — {today_str}*",
        f"━━━━━━━━━━━━━━━━━━━━",
        "",
        f"💼 *Portfolio:* ₹{total:,.0f}",
        f"📈 *Total P&L:* {pnl_emoji} ₹{summary['pnl']:+,.0f} ({summary['pnl_pct']:+.1f}%)",
        f"💰 Cash: ₹{summary['cash']:,.0f} | 📦 Holdings: ₹{summary['holdings_value']:,.0f}",
        f"🏦 Broker: {broker.active_broker} | Market: {market_status}",
        "",
    ]

    # Daily change
    if not daily.get("new"):
        dp = daily["daily_pnl"]
        dpct = daily["daily_pnl_pct"]
        dp_emoji = "🟢" if dp > 0 else "🔴" if dp < 0 else "⚪"
        lines.append(f"📅 *Today:* {dp_emoji} ₹{dp:+,.0f} ({dpct:+.2f}%)")
    lines.append("")

    # Analysis results (if ran today)
    if analysis_ran:
        buys = [s for s in signals if s["action"] == "BUY"]
        sells = [s for s in signals if s["action"] == "SELL"]
        lines.append(f"🔍 *Analysis:* 🟢 {len(buys)} BUY | 🔴 {len(sells)} SELL")

        if buys:
            lines.append("*Top BUY signals:*")
            for s in buys[:5]:
                lines.append(
                    f"  🟢 {s['ticker']}: {s.get('quantity', 0)} shares @ ₹{s['price']:,.2f} "
                    f"({s.get('recommendation', '?')}, {s.get('confidence', '?')}%)"
                )
        lines.append("")

    # Today's orders
    if orders:
        lines.append(f"📋 *Orders Executed ({len(orders)}):*")
        for o in orders:
            emoji = "🟢" if o["action"].upper() == "BUY" else "🔴"
            qty = o.get("filled_quantity", o["quantity"])
            price = o.get("filled_price", o["price"])
            lines.append(f"  {emoji} {o['action']} {o['ticker']}: {qty} × ₹{price:,.2f}")
    lines.append("")

    # Holdings
    if summary.get("holdings"):
        lines.append(f"📦 *Holdings ({len(summary['holdings'])}):*")
        for h in summary["holdings"]:
            pnl_e = "🟢" if h["pnl"] > 0 else "🔴" if h["pnl"] < 0 else "⚪"
            lines.append(
                f"  • {h['ticker']}: {h['quantity']} × ₹{h['current_price']:,.2f} "
                f"({pnl_e} {h['pnl_pct']:+.1f}%)"
            )
    else:
        lines.append("📦 *No holdings*")

    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━")

    # Equity trend
    if len(equity_curve) >= 2:
        start = config.paper_trading.initial_capital
        pct = (total / start - 1) * 100
        lines.append(f"📈 Since start: {pct:+.1f}% | Snapshots: {len(equity_curve)} days")

    msg = "\n".join(lines)

    # ── Terminal display ────────────────────────────────────────────
    console.print(f"\n💼 Portfolio: ₹{total:,.0f} ({summary['pnl_pct']:+.1f}%)")
    console.print(f"📈 Today: {pnl_emoji} ₹{daily['daily_pnl']:+,.0f}")

    if summary.get("holdings"):
        console.print("\nHoldings:")
        for h in summary["holdings"]:
            pnl_e = "🟢" if h["pnl"] > 0 else "🔴"
            console.print(f"  {h['ticker']}: {h['quantity']} × ₹{h['current_price']:,.2f} ({pnl_e} {h['pnl_pct']:+.1f}%)")

    # ── Telegram ────────────────────────────────────────────────────
    if config.telegram.bot_token:
        sent = reporter.send_message(msg)
        if sent:
            console.print("\n[green]✓ Report sent to Telegram[/green]")
        else:
            console.print("\n[yellow]⚠ Telegram send failed[/yellow]")
    else:
        console.print("\n[dim]Telegram not configured — report shown above only[/dim]")

    return msg


# ══════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════


async def main():
    dry_run = "--dry-run" in sys.argv
    force = "--force" in sys.argv
    tickers_arg = None

    for arg in sys.argv:
        if arg.startswith("--tickers="):
            tickers_arg = arg.split("=", 1)[1]

    console.print(Panel.fit(
        "[bold cyan]🚀 Stock Agent — Daily Pipeline[/bold cyan]\n"
        f"[dim]{datetime.now().strftime('%A, %d %B %Y — %H:%M IST')}[/dim]",
        border_style="cyan",
    ))

    # Init core components
    broker = PaperBroker()
    portfolio = PaperPortfolio()
    reporter = TelegramReporter(config.telegram.bot_token, config.telegram.chat_id)

    console.print(f"Broker: [green]{broker.active_broker}[/green] | Capital: ₹{portfolio.initial_cash:,.0f}")
    console.print(f"Market: {'🟢 OPEN' if _is_market_open() else '🔴 CLOSED'}")
    console.print(f"Risk profile: [yellow]{config.analysis.risk_profile}[/yellow]")
    console.print(f"Analysis interval: every {config.analysis.interval_days} days")

    # ── Phase 1: Analysis ───────────────────────────────────────────
    state = _load_state()
    analysis_ran = False
    signals = []

    if _is_weekend():
        console.print("\n[dim]Weekend — skipping analysis[/dim]")
    elif tickers_arg:
        # Custom tickers mode
        tickers = [t.strip().upper() for t in tickers_arg.split(",")]
        console.print(f"\n[bold]Custom analysis: {tickers}[/bold]")
        portfolio_summary = portfolio.get_summary({})
        signals = await run_analysis(tickers, portfolio_summary)
        analysis_ran = True
    elif _should_analyze_today(state, force):
        universe = load_universe()
        tickers = universe.get(config.analysis.universe, universe.get("nifty50", []))
        if not tickers:
            console.print("[red]No tickers in universe! Check config/universe.yaml[/red]")
            return

        portfolio_summary = portfolio.get_summary({})
        signals = await run_analysis(tickers, portfolio_summary)
        analysis_ran = True

        # Update state
        state["last_analysis"] = datetime.now().strftime("%Y-%m-%d")
        state["total_analyses"] = state.get("total_analyses", 0) + 1
    else:
        days_since = "unknown"
        if state.get("last_analysis"):
            last = datetime.strptime(state["last_analysis"], "%Y-%m-%d")
            days_since = (datetime.now() - last).days
        console.print(f"\n[dim]Skipping analysis — last ran {days_since} days ago (interval: {config.analysis.interval_days})[/dim]")

    # ── Phase 2: Execution ──────────────────────────────────────────
    orders = execute_signals(signals, broker, portfolio, dry_run)
    state["total_trades"] = state.get("total_trades", 0) + len(orders)
    _save_state(state)

    # ── Phase 3: Report ─────────────────────────────────────────────
    generate_report(portfolio, signals, orders, broker, reporter, analysis_ran)

    # ── Summary ─────────────────────────────────────────────────────
    console.print(f"\n[bold]Pipeline complete.[/bold]")
    console.print(f"Total analyses: {state['total_analyses']} | Total trades: {state['total_trades']}")
    console.print(f"[dim]Data: data/paper_orders.json | data/equity_curve.json[/dim]")


if __name__ == "__main__":
    asyncio.run(main())
