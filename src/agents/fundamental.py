"""Fundamental analysis agent — evaluates financials, ratios, intrinsic value."""

from typing import Any

from src.agents.base import LLMAgent


class FundamentalAnalyst(LLMAgent):
    """Evaluates company fundamentals: PE, ROE, debt, growth, competitive position."""

    name = "fundamental"

    def analyze(self, ticker: str, data: dict[str, Any]) -> dict[str, Any]:
        """Analyze fundamentals and return a rating with reasoning.

        Args:
            ticker: Stock symbol
            data: Dictionary with keys:
                - fundamentals: dict from NSEFetcher.get_fundamentals()
                - price_history: summary stats of recent prices

        Returns:
            {
                "rating": "BUY" | "HOLD" | "SELL",
                "confidence": 0-100,
                "score": 0-100,
                "reasoning": "Detailed analysis",
                "key_metrics": {},
                "red_flags": [],
                "strengths": []
            }
        """
        fundamentals = data.get("fundamentals", {})
        price_info = data.get("price_history", {})

        prompt = f"""Analyze the fundamentals of {ticker} (NSE India) and provide a BUY/HOLD/SELL rating.

## Financial Data
{self._format_fundamentals(fundamentals)}

## Price Context
{self._format_price_info(price_info)}

## Indian Market Context
- Nifty 50 average PE: ~22-24
- GDP growth target: 6.5%
- RBI repo rate: 6.25%

Respond with ONLY a JSON object:
{{
    "rating": "BUY" or "HOLD" or "SELL",
    "confidence": 0-100,
    "score": 0-100 (higher = better),
    "reasoning": "2-3 sentence analysis",
    "key_metrics": {{"pe": value, "roe": value, ...}},
    "red_flags": ["concern1", ...],
    "strengths": ["strength1", ...]
}}"""
        response = self.call_sync(prompt)
        result = self._parse_json_response(response)
        result["agent"] = self.name
        return result

    def _format_fundamentals(self, data: dict) -> str:
        lines = []
        mapping = {
            "pe_ratio": "P/E Ratio",
            "forward_pe": "Forward P/E",
            "pb_ratio": "P/B Ratio",
            "roe": "ROE (%)",
            "debt_to_equity": "Debt/Equity",
            "market_cap": "Market Cap",
            "revenue_growth": "Revenue Growth (%)",
            "profit_margins": "Profit Margins (%)",
            "dividend_yield": "Dividend Yield (%)",
            "beta": "Beta",
            "sector": "Sector",
            "industry": "Industry",
        }
        for key, label in mapping.items():
            val = data.get(key)
            if val is not None:
                lines.append(f"- {label}: {val}")
        return "\n".join(lines) if lines else "No fundamental data available"

    def _format_price_info(self, data: dict) -> str:
        lines = []
        if data:
            for k, v in data.items():
                lines.append(f"- {k}: {v}")
        return "\n".join(lines) if lines else "No price data"
