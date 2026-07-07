"""Telegram bot for daily reports and trade approval."""

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


class TelegramReporter:
    """Sends formatted stock analysis and portfolio updates via Telegram."""

    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self._enabled = bool(bot_token and chat_id)

    def send_message(self, text: str) -> bool:
        """Send a message via Telegram Bot API."""
        if not self._enabled:
            logger.info(f"[Telegram would send]: {text[:100]}...")
            return False

        import httpx

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        try:
            response = httpx.post(
                url,
                json={
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": "Markdown",
                },
                timeout=10,
            )
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")
            return False

    def send_daily_signals(self, signals: list[dict], date: str):
        """Send daily trading signals for approval."""
        if not signals:
            self.send_message(f"📊 *Daily Signals — {date}*\n\nNo actionable signals today.")
            return

        lines = [f"📊 *Daily Signals — {date}*\n"]

        total_orders = 0
        for s in signals:
            emoji = "🟢" if s["action"] == "BUY" else "🔴" if s["action"] == "SELL" else "⚪"
            lines.append(
                f"{emoji} *{s['action']}*: {s['ticker']} @ ₹{s.get('price', 0):,.2f}\n"
                f"   Qty: {s.get('quantity', 0)} shares | ₹{s.get('amount', 0):,.0f}\n"
                f"   Reason: {s.get('reasoning', 'N/A')[:100]}\n"
            )
            total_orders += 1

        lines.append("\n━━━━━━━━━━━━━━━")
        lines.append(f"_Reply_ *approve* _to execute all {total_orders} orders_")
        lines.append("_Reply_ *approve TICKER* _for one stock_")
        lines.append("_Reply_ *reject* _to skip today_")

        self.send_message("\n".join(lines))

    def send_portfolio_update(self, summary: dict):
        """Send portfolio summary."""
        pnl = summary.get("pnl", 0)
        pnl_emoji = "🟢" if pnl > 0 else "🔴" if pnl < 0 else "⚪"

        lines = [
            f"📈 *Portfolio Update*\n",
            f"💰 Cash: ₹{summary['cash']:,.0f}",
            f"📦 Holdings: ₹{summary['holdings_value']:,.0f}",
            f"💼 Total: ₹{summary['total_value']:,.0f}",
            f"{pnl_emoji} P&L: ₹{pnl:+,.0f} ({summary['pnl_pct']:+.1f}%)\n",
        ]

        if summary.get("holdings"):
            lines.append("*Holdings:*")
            for h in summary["holdings"]:
                pnl_e = "🟢" if h["pnl"] > 0 else "🔴" if h["pnl"] < 0 else "⚪"
                lines.append(
                    f"• {h['ticker']}: {h['quantity']} × ₹{h['current_price']:,.2f} = ₹{h['value']:,.0f} "
                    f"({pnl_e} {h['pnl_pct']:+.1f}%)"
                )

        self.send_message("\n".join(lines))

    def send_backtest_results(self, results: dict):
        """Send backtest performance summary."""
        alpha = results.get("alpha_pct", 0)
        alpha_emoji = "🟢" if alpha > 0 else "🔴"

        self.send_message(
            f"📊 *Backtest Results (5Y)*\n\n"
            f"💰 Total Return: *{results['total_return_pct']:+.1f}%*\n"
            f"📈 CAGR: *{results['cagr_pct']:+.1f}%*\n"
            f"📉 Max Drawdown: *-{results['max_drawdown_pct']:.1f}%*\n"
            f"🎯 Sharpe: *{results['sharpe_ratio']:.2f}*\n"
            f"✅ Win Rate: *{results['win_rate_pct']:.0f}%*\n"
            f"🔄 Trades: {results['total_trades']}\n\n"
            f"📊 Nifty 50: {results['benchmark_return_pct']:+.1f}%\n"
            f"{alpha_emoji} Alpha: *{alpha:+.1f}%*"
        )

    def send_analysis(self, ticker: str, result: dict):
        """Send single stock analysis."""
        rec = result.get("recommendation", "HOLD")
        emoji_map = {
            "STRONG_BUY": "🚀",
            "BUY": "🟢",
            "HOLD": "⚪",
            "SELL": "🔴",
            "STRONG_SELL": "💀",
        }
        emoji = emoji_map.get(rec, "⚪")

        self.send_message(
            f"{emoji} *{ticker}* — {rec}\n"
            f"Score: {result.get('weighted_score', result.get('score', 'N/A'))}/100\n"
            f"Confidence: {result.get('confidence', 'N/A')}%\n\n"
            f"*Bull Case:* {result.get('bull_case', result.get('reasoning', 'N/A'))[:200]}\n\n"
            f"*Bear Case:* {result.get('bear_case', 'N/A')[:200] if result.get('bear_case') else ''}"
        )
