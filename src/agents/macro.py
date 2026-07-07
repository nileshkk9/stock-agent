"""Macro analysis agent — RBI policy, budget, global cues, sector trends."""

from typing import Any

from src.agents.base import LLMAgent


class MacroAnalyst(LLMAgent):
    """Evaluates macro-economic factors affecting the stock and market."""

    name = "macro"

    def analyze(self, ticker: str, data: dict[str, Any]) -> dict[str, Any]:
        """Analyze macro context for a stock.

        Args:
            ticker: Stock symbol
            data: Dictionary with:
                - sector: industry sector
                - market_news: list of market-level news

        Returns:
            {
                "rating": "FAVORABLE" | "NEUTRAL" | "UNFAVORABLE",
                "confidence": 0-100,
                "score": -100 to 100,
                "factors": [],
                "risks": [],
                "reasoning": "...",
            }
        """
        sector = data.get("sector", "Unknown")
        market_news = data.get("market_news", [])

        news_text = "\n".join(
            f"- {n.get('title', '')}" for n in market_news[:5]
        ) if market_news else "No macro news available"

        prompt = f"""Analyze the macro-economic environment for {ticker} (Sector: {sector}, NSE India).

## Market News
{news_text}

## Current Indian Macro Context (July 2026)
- RBI repo rate: 6.25%
- GDP growth: ~6.5%
- Inflation: ~4.5%
- Monsoon: Normal forecast
- Budget 2026: Infrastructure & manufacturing focus
- FII flows: Volatile

## Instructions
Evaluate how the macro environment affects {ticker} specifically, considering:
1. Interest rate sensitivity (banks/NBFCs benefit from high rates, real estate suffers)
2. Government policy impact (infra push helps capital goods, PLI helps manufacturing)
3. Global factors (IT depends on US demand, metals on China)
4. Monsoon impact (agri, rural consumption)

Respond with ONLY a JSON object:
{{
    "rating": "FAVORABLE" or "NEUTRAL" or "UNFAVORABLE",
    "confidence": 0-100,
    "score": -100 to 100,
    "reasoning": "2-3 sentence macro analysis",
    "factors": ["factor1", "factor2"],
    "risks": ["risk1", "risk2"]
}}"""
        response = self.call_sync(prompt)
        result = self._parse_json_response(response)
        result["agent"] = self.name
        return result
