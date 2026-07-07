"""Risk manager agent — assesses portfolio risk, position sizing, stop-loss."""

from typing import Any

from src.agents.base import LLMAgent
from src.config import config


class RiskManager(LLMAgent):
    """Evaluates risk for a potential trade and determines position size."""

    name = "risk_manager"

    def analyze(self, ticker: str, data: dict[str, Any]) -> dict[str, Any]:
        """Assess risk and recommend position sizing.

        Args:
            ticker: Stock symbol
            data: Dictionary with:
                - researcher: dict from ResearcherAgent
                - fundamentals: dict with beta, market_cap, etc.
                - portfolio: current portfolio state
                - risk_profile: conservative/moderate/aggressive

        Returns:
            {
                "risk_level": "LOW" | "MEDIUM" | "HIGH" | "EXTREME",
                "max_position_pct": float,
                "suggested_allocation": float (₹),
                "stop_loss_pct": float,
                "risk_score": 0-100 (higher = riskier),
                "concerns": [],
                "agent": "risk_manager"
            }
        """
        researcher = data.get("researcher", {})
        fundamentals = data.get("fundamentals", {})
        portfolio = data.get("portfolio", {})
        risk_cfg = config.risk_profile_config

        beta = fundamentals.get("beta", 1.0)
        market_cap = fundamentals.get("market_cap", 0)
        recommendation = researcher.get("recommendation", "HOLD")
        confidence = researcher.get("confidence", 50)

        prompt = f"""Assess the risk for a potential trade in {ticker}.

## Stock Data
- Recommendation: {recommendation}
- Confidence: {confidence}%
- Beta: {beta}
- Market Cap: {market_cap}
- Max allowed position: {risk_cfg.max_position_pct}% of portfolio
- Stop-loss policy: {risk_cfg.stop_loss_pct}%

## Portfolio
{self._format_portfolio(portfolio)}

## Risk Rules
- Low risk: beta < 1.0, large cap, strong recommendation
- Medium risk: beta 1.0-1.5, mid cap, moderate confidence
- High risk: beta > 1.5, small cap, low confidence
- Never exceed max position size
- Consider correlation with existing holdings

Respond with ONLY a JSON object:
{{
    "risk_level": "LOW" or "MEDIUM" or "HIGH" or "EXTREME",
    "max_position_pct": 0-{risk_cfg.max_position_pct},
    "suggested_allocation": 0 (in ₹),
    "stop_loss_pct": 0-{risk_cfg.stop_loss_pct},
    "risk_score": 0-100,
    "concerns": ["concern1", "concern2"]
}}"""
        response = self.call_sync(prompt)
        result = self._parse_json_response(response)
        result["agent"] = self.name
        return result

    def _format_portfolio(self, portfolio: dict) -> str:
        if not portfolio:
            return "Empty portfolio (initial state)"
        lines = [f"- Cash: ₹{portfolio.get('cash', 0):,.0f}"]
        for holding in portfolio.get("holdings", []):
            lines.append(
                f"- {holding['ticker']}: {holding['quantity']} shares @ ₹{holding['avg_price']:,.2f} "
                f"(Value: ₹{holding['quantity'] * holding['avg_price']:,.0f})"
            )
        return "\n".join(lines)
