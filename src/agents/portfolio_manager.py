"""Portfolio Manager agent — final decision maker, converts research into actionable orders."""

from typing import Any

from src.agents.base import LLMAgent


class PortfolioManager(LLMAgent):
    """Makes final BUY/SELL/HOLD decisions and determines order parameters."""

    name = "portfolio_manager"

    def analyze(self, ticker: str, data: dict[str, Any]) -> dict[str, Any]:
        """Decide if/what to trade.

        Args:
            ticker: Stock symbol
            data: Dictionary with:
                - researcher: dict from ResearcherAgent
                - risk_manager: dict from RiskManager
                - current_price: float
                - portfolio: current portfolio state

        Returns:
            {
                "action": "BUY" | "SELL" | "HOLD",
                "quantity": int,
                "amount": float (₹),
                "order_type": "MARKET" | "LIMIT",
                "limit_price": float | None,
                "reasoning": "...",
                "urgency": "IMMEDIATE" | "TODAY" | "WATCH",
                "agent": "portfolio_manager"
            }
        """
        researcher = data.get("researcher", {})
        risk_manager = data.get("risk_manager", {})
        current_price = data.get("current_price", 0)
        portfolio = data.get("portfolio", {})
        recommendation = researcher.get("recommendation", "HOLD")
        confidence = researcher.get("confidence", 50)
        risk_level = risk_manager.get("risk_level", "MEDIUM")
        max_allocation = risk_manager.get("suggested_allocation", 0)

        prompt = f"""You are the Portfolio Manager. Make a final trading decision for {ticker}.

## Research
- Recommendation: {recommendation} (Confidence: {confidence}%)
- Verdict: {researcher.get('verdict', 'N/A')}

## Risk Assessment
- Risk Level: {risk_level}
- Max Allocation: ₹{max_allocation:,.0f}
- Stop Loss: {risk_manager.get('stop_loss_pct', 5)}%

## Market
- Current Price: ₹{current_price:,.2f}

## Portfolio
{self._format_portfolio(portfolio)}

## Rules
- If recommendation is STRONG_BUY and risk <= MEDIUM → BUY
- If recommendation is BUY and risk <= HIGH → BUY (reduced size)
- If recommendation is STRONG_SELL → SELL entire position
- If recommendation is SELL and risk >= MEDIUM → SELL 50% position
- Otherwise → HOLD
- Never invest more than max_allocation
- Round quantity down to whole shares

Respond with ONLY a JSON object:
{{
    "action": "BUY" or "SELL" or "HOLD",
    "quantity": 0,
    "amount": 0.0,
    "order_type": "MARKET" or "LIMIT",
    "limit_price": null or float,
    "reasoning": "Concise explanation (1-2 sentences)",
    "urgency": "IMMEDIATE" or "TODAY" or "WATCH"
}}"""
        response = self.call_sync(prompt)
        result = self._parse_json_response(response)
        result["agent"] = self.name
        return result

    def _format_portfolio(self, portfolio: dict) -> str:
        if not portfolio or not portfolio.get("holdings"):
            return "No current holdings"
        lines = [f"- Cash: ₹{portfolio.get('cash', 0):,.0f}"]
        lines.append(f"- Total Value: ₹{portfolio.get('total_value', 0):,.0f}")
        for h in portfolio.get("holdings", []):
            lines.append(f"- {h['ticker']}: {h['quantity']} shares")
        return "\n".join(lines)
