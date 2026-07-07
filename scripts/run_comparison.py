#!/usr/bin/env python3
"""
Stock Agent — Strategy Comparison Tracker

Runs two paper trading portfolios side-by-side:
    Portfolio A: Pure Trend+Momentum (rule-based)
    Portfolio B: Trend+Momentum + LLM Agent Filter

Tracks daily P&L for both + Nifty 50 benchmark.
Generates a comparison report showing which approach wins.
"""

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import yfinance as yf
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn

from src.config import config, load_universe
from src.data.nse_fetcher import NSEFetcher
from src.paper_trading.broker import PaperBroker, PaperPortfolio, _is_market_open
from src.reporting.telegram_bot import TelegramReporter

console = Console()

COMPARISON_FILE = Path(__file__).parent.parent / "data" / "comparison_state.json"
NIFTY_TRACKER = Path(__file__).parent.parent / "data" / "nifty_tracker.json"


# ══════════════════════════════════════════════════════════════════════
# COMPARISON TRACKER
# ══════════════════════════════════════════════════════════════════════


class ComparisonTracker:
    """Manages two paper trading portfolios for A/B strategy comparison.

    Portfolio A: Pure Trend+Momentum signals
    Portfolio B: Trend+Momentum signals filtered through LLM agents
    """

    def __init__(self, initial_capital: float = 1_000_000):
        self.initial_capital = initial_capital
        self.portfolio_a = PaperPortfolio(initial_cash=initial_capital)
        self.portfolio_b = PaperPortfolio(initial_cash=initial_capital)
        self.broker = PaperBroker()

        # Daily tracking
        self.history: list[dict] = []
        self._load()

    def _load(self):
        if COMPARISON_FILE.exists():
            try:
                data = json.loads(COMPARISON_FILE.read_text())
                self.history = data.get("history", [])
            except (json.JSONDecodeError, KeyError):
                pass

    def _save(self):
        COMPARISON_FILE.parent.mkdir(parents=True, exist_ok=True)
        COMPARISON_FILE.write_text(json.dumps({
            "history": self.history,
            "initial_capital": self.initial_capital,
            "started": self.history[0]["date"] if self.history else None,
        }, indent=2, default=str))

    def execute_signal_a(self, ticker: str, action: str, qty: int, price: float) -> dict | None:
        """Execute in Portfolio A (pure Trend+Momentum)."""
        if action == "HOLD" or qty <= 0:
            return None
        order = self.broker.place_order(ticker, action, qty, price)
        if order["status"] == "EXECUTED":
            self.portfolio_a.execute_order(order)
        return order

    def execute_signal_b(self, ticker: str, action: str, qty: int, price: float,
                         llm_approved: bool = False) -> dict | None:
        """Execute in Portfolio B (LLM-filtered). Only if LLM approves."""
        if action == "HOLD" or qty <= 0:
            return None
        if not llm_approved:
            return None  # LLM veto — don't trade
        order = self.broker.place_order(ticker, action, qty, price)
        if order["status"] == "EXECUTED":
            self.portfolio_b.execute_order(order)
        return order

    def get_daily_snapshot(self) -> dict:
        """Get comparison data for today."""
        fetcher = NSEFetcher()

        # Prices for all holdings across both portfolios
        all_tickers = set(self.portfolio_a.holdings.keys()) | set(self.portfolio_b.holdings.keys())
        prices = {}
        for t in all_tickers:
            p = fetcher.get_current_price(t)
            if p:
                prices[t] = p

        summary_a = self.portfolio_a.get_summary(prices)
        summary_b = self.portfolio_b.get_summary(prices)
        nifty = self._get_nifty_value()

        today = datetime.now().strftime("%Y-%m-%d")

        snapshot = {
            "date": today,
            "portfolio_a": {
                "value": summary_a["total_value"],
                "pnl": summary_a["pnl"],
                "pnl_pct": summary_a["pnl_pct"],
                "cash": summary_a["cash"],
                "holdings": len(summary_a.get("holdings", [])),
            },
            "portfolio_b": {
                "value": summary_b["total_value"],
                "pnl": summary_b["pnl"],
                "pnl_pct": summary_b["pnl_pct"],
                "cash": summary_b["cash"],
                "holdings": len(summary_b.get("holdings", [])),
            },
            "nifty": nifty,
            "nifty_return_pct": round((nifty / self._nifty_start - 1) * 100, 2) if self._nifty_start else 0,
        }

        # Append or update today
        existing = [h for h in self.history if h["date"] != today]
        existing.append(snapshot)
        self.history = sorted(existing, key=lambda x: x["date"])
        self._save()

        return snapshot

    @property
    def _nifty_start(self) -> float:
        """Nifty value when comparison started."""
        if self.history:
            return self.history[0].get("nifty", 20000)
        return 20000

    def _get_nifty_value(self) -> float:
        """Current Nifty 50 index value."""
        cache_key = "nifty_current"
        from src.data.nse_fetcher import _cached, _cache_set
        val = _cached(cache_key)
        if val:
            return val
        try:
            nifty = yf.Ticker("^NSEI")
            hist = nifty.history(period="5d")
            if not hist.empty:
                value = float(hist["Close"].iloc[-1])
                _cache_set(cache_key, value, ttl=300)
                return value
        except Exception:
            pass
        # Fallback: fetch from NSE fetcher
        try:
            fetcher = NSEFetcher()
            # Get Nifty via nsepython or yfinance
            nifty = yf.Ticker("^NSEI")
            return float(nifty.fast_info.last_price or 25000)
        except Exception:
            return 25000  # fallback

    def get_comparison_report(self) -> str:
        """Generate comparison report text."""
        if not self.history:
            return "No comparison data yet. Run analysis first."

        latest = self.history[-1]
        a = latest["portfolio_a"]
        b = latest["portfolio_b"]

        # Calculate who's winning
        a_return = (a["value"] / self.initial_capital - 1) * 100
        b_return = (b["value"] / self.initial_capital - 1) * 100
        nifty_return = latest.get("nifty_return_pct", 0)

        # Winner
        scores = {
            "Portfolio A (Rules)": a_return,
            "Portfolio B (LLM)": b_return,
            "Nifty 50": nifty_return,
        }
        winner = max(scores, key=scores.get)

        a_emoji = "🟢" if a["pnl"] > 0 else "🔴"
        b_emoji = "🟢" if b["pnl"] > 0 else "🔴"
        n_emoji = "🟢" if nifty_return > 0 else "🔴"

        lines = [
            f"⚔️ *Strategy Battle — {latest['date']}*",
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"",
            f"*Portfolio A — Pure Rules*",
            f"  💼 Value: ₹{a['value']:,.0f}",
            f"  {a_emoji} P&L: ₹{a['pnl']:+,.0f} ({a['pnl_pct']:+.1f}%)",
            f"  📦 Holdings: {a['holdings']} | 💰 Cash: ₹{a['cash']:,.0f}",
            f"  📈 Total: {a_return:+.1f}%",
            f"",
            f"*Portfolio B — LLM Filtered*",
            f"  💼 Value: ₹{b['value']:,.0f}",
            f"  {b_emoji} P&L: ₹{b['pnl']:+,.0f} ({b['pnl_pct']:+.1f}%)",
            f"  📦 Holdings: {b['holdings']} | 💰 Cash: ₹{b['cash']:,.0f}",
            f"  📈 Total: {b_return:+.1f}%",
            f"",
            f"*Nifty 50 Benchmark*",
            f"  {n_emoji} Return: {nifty_return:+.1f}%",
            f"",
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"🏆 *Leader:* {winner} (+{scores[winner]:+.1f}%)",
        ]

        # Week-over-week trend
        if len(self.history) >= 2:
            yesterday = self.history[-2]
            a_daily = a["value"] - yesterday["portfolio_a"]["value"]
            b_daily = b["value"] - yesterday["portfolio_b"]["value"]
            lines.append(f"")
            lines.append(f"📅 *Today's Change:*")
            da_emoji = "🟢" if a_daily > 0 else "🔴"
            db_emoji = "🟢" if b_daily > 0 else "🔴"
            lines.append(f"  A: {da_emoji} ₹{a_daily:+,.0f}")
            lines.append(f"  B: {db_emoji} ₹{b_daily:+,.0f}")

        return "\n".join(lines)

    def get_leaderboard(self) -> str:
        """Simple leaderboard for quick checks."""
        if not self.history:
            return "No data yet."

        latest = self.history[-1]
        a_ret = (latest["portfolio_a"]["value"] / self.initial_capital - 1) * 100
        b_ret = (latest["portfolio_b"]["value"] / self.initial_capital - 1) * 100
        n_ret = latest.get("nifty_return_pct", 0)

        return (
            f"⚔️ *Battle Leaderboard*\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"🥇 *{'AI (LLM)' if b_ret >= max(a_ret, n_ret) else 'Nifty' if n_ret >= max(a_ret, b_ret) else 'Rules'}*\n"
            f"\n"
            f"• Rules:   {a_ret:+.1f}%\n"
            f"• LLM:     {b_ret:+.1f}%\n"
            f"• Nifty:   {n_ret:+.1f}%\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"📅 Day {len(self.history)} | "
            f"{'🟢 LLM winning' if b_ret > a_ret else '🔴 Rules winning'}"
        )


# ══════════════════════════════════════════════════════════════════════
# LLM AGENT FILTER
# ══════════════════════════════════════════════════════════════════════


async def llm_filter_signal(ticker: str, fetcher: NSEFetcher,
                             portfolio_summary: dict) -> tuple[str, float]:
    """Run LLM agents on a stock to decide if it's a BUY/SELL/HOLD.

    Returns: (verdict: BUY|SELL|HOLD, confidence: 0-100)
    """
    from src.agents.fundamental import FundamentalAnalyst
    from src.agents.technical import TechnicalAnalyst
    from src.agents.sentiment import SentimentAnalyst
    from src.agents.macro import MacroAnalyst
    from src.agents.researcher import ResearcherAgent
    from src.agents.risk_manager import RiskManager
    from src.agents.portfolio_manager import PortfolioManager

    try:
        current_price = fetcher.get_current_price(ticker)
        if not current_price:
            return "HOLD", 0

        fundamentals = fetcher.get_fundamentals(ticker)
        price_df = fetcher.get_historical(ticker, period="3mo")

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

        researcher = ResearcherAgent()
        research = researcher.analyze(ticker, {
            "fundamental": fund_result,
            "technical": tech_result,
            "sentiment": sent_result,
            "macro": macro_result,
        })

        risk_mgr = RiskManager()
        risk = risk_mgr.analyze(ticker, {
            "researcher": research,
            "fundamentals": fundamentals,
            "portfolio": portfolio_summary,
        })

        pm = PortfolioManager()
        decision = pm.analyze(ticker, {
            "researcher": research,
            "risk_manager": risk,
            "current_price": current_price,
            "portfolio": portfolio_summary,
        })

        return decision.get("action", "HOLD"), research.get("confidence", 50)

    except Exception as e:
        console.print(f"[red]LLM error for {ticker}: {e}[/red]")
        return "HOLD", 0


# ══════════════════════════════════════════════════════════════════════
# TREND+MOMENTUM SIGNAL GENERATION
# ══════════════════════════════════════════════════════════════════════


def generate_trend_signals(fetcher: NSEFetcher,
                           tickers: list[str]) -> list[dict]:
    """Generate Trend+Momentum signals for a list of stocks.

    Returns: [{ticker, action, qty, price, sma50, sma200, momentum}]
    """
    signals = []

    for ticker in tickers:
        try:
            df = fetcher.get_historical(ticker, period="6mo")
            if df.empty or len(df) < 200:
                continue

            price = df["Close"].iloc[-1]
            sma50 = df["Close"].rolling(50).mean().iloc[-1]
            sma200 = df["Close"].rolling(200).mean().iloc[-1]

            # Momentum: 20-day rate of change
            mom = (df["Close"].iloc[-1] / df["Close"].iloc[-21] - 1) * 100 if len(df) >= 21 else 0

            in_uptrend = sma50 > sma200
            positive_momentum = mom > 0

            if in_uptrend and positive_momentum:
                # Buy signal
                qty = max(1, int(100000 / price))  # ~₹1L per position
                signals.append({
                    "ticker": ticker,
                    "action": "BUY",
                    "qty": qty,
                    "price": price,
                    "sma50": round(sma50, 2),
                    "sma200": round(sma200, 2),
                    "momentum": round(mom, 2),
                })

        except Exception as e:
            console.print(f"[dim]Signal error {ticker}: {e}[/dim]")
            continue

    # Sort by momentum strength (strongest first)
    signals.sort(key=lambda s: s["momentum"], reverse=True)
    return signals


# ══════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════


async def main():
    console.print(Panel.fit(
        "[bold cyan]⚔️ Strategy Battle — A/B Comparison[/bold cyan]\n"
        "[dim]Portfolio A: Rules   |   Portfolio B: Rules + LLM[/dim]",
        border_style="cyan",
    ))

    tracker = ComparisonTracker(initial_capital=config.paper_trading.initial_capital)
    reporter = TelegramReporter(config.telegram.bot_token, config.telegram.chat_id)
    fetcher = NSEFetcher()

    console.print(f"Capital: ₹{tracker.initial_capital:,.0f} each")
    console.print(f"Market: {'🟢 OPEN' if _is_market_open() else '🔴 CLOSED'}\n")

    # ── Step 1: Generate Trend+Momentum signals ────────────────────
    universe = load_universe()
    tickers = universe.get("nifty50", NSEFetcher.get_nifty50_symbols())[:30]

    console.print(f"[bold]Scanning {len(tickers)} stocks for signals...[/bold]")

    signals = generate_trend_signals(fetcher, tickers)
    console.print(f"Trend signals: [green]{len(signals)} BUY[/green]\n")

    if not signals:
        console.print("[yellow]No actionable signals today[/yellow]")
        return

    # ── Step 2: Execute Portfolio A (all signals) ──────────────────
    console.print("[bold cyan]Portfolio A — Pure Rules[/bold cyan]")
    orders_a = []
    for s in signals[:10]:  # Top 10 by momentum
        order = tracker.execute_signal_a(s["ticker"], s["action"], s["qty"], s["price"])
        if order:
            orders_a.append(order)
            console.print(f"  🟢 BUY {s['ticker']}: {s['qty']} × ₹{s['price']:,.2f} "
                         f"(mom: {s['momentum']:+.1f}%)")
    console.print(f"  Executed: {len(orders_a)} trades\n")

    # ── Step 3: LLM filter + Execute Portfolio B ───────────────────
    console.print("[bold cyan]Portfolio B — LLM Filtered[/bold cyan]")

    # Get portfolio A summary for LLM context
    summary_a = tracker.portfolio_a.get_summary({})
    orders_b = []
    llm_approvals = 0
    llm_rejections = 0

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
                  console=console) as progress:
        task = progress.add_task("Running LLM agents...", total=min(len(signals), 10))

        for s in signals[:10]:
            progress.update(task, description=f"LLM analyzing {s['ticker']}...")

            verdict, confidence = await llm_filter_signal(s["ticker"], fetcher, summary_a)

            if verdict in ("BUY", "STRONG_BUY"):
                order = tracker.execute_signal_b(
                    s["ticker"], s["action"], s["qty"], s["price"], llm_approved=True
                )
                if order:
                    orders_b.append(order)
                    console.print(f"  🟢 BUY {s['ticker']}: {s['qty']} × ₹{s['price']:,.2f} "
                                 f"[green](LLM: {verdict}, {confidence}%)[/green]")
                llm_approvals += 1
            else:
                llm_rejections += 1
                console.print(f"  🔴 SKIP {s['ticker']}: [red]LLM says {verdict}[/red]")

            progress.advance(task)

    console.print(f"\n  LLM Approved: [green]{llm_approvals}[/green] | "
                  f"Rejected: [red]{llm_rejections}[/red] | "
                  f"Executed: {len(orders_b)} trades\n")

    # ── Step 4: Comparison Report ──────────────────────────────────
    console.print("[bold green]📊 Comparison Report[/bold green]")

    snapshot = tracker.get_daily_snapshot()
    report = tracker.get_comparison_report()
    console.print(report)

    # ── Step 5: Send to Telegram ───────────────────────────────────
    if config.telegram.bot_token:
        reporter.send_message(report)
        console.print("\n[green]✓ Report sent to Telegram[/green]")

    # Show leaderboard
    console.print(f"\n{tracker.get_leaderboard()}")

    console.print(f"\n[dim]Data saved: data/comparison_state.json[/dim]")


if __name__ == "__main__":
    asyncio.run(main())
