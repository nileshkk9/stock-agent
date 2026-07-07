"""Researcher agent — orchestrates bull vs bear debate using all analyst outputs."""

from typing import Any

from src.agents.base import LLMAgent


class ResearcherAgent(LLMAgent):
    """Synthesizes all analyst views into a bull vs bear debate and makes a recommendation."""

    name = "researcher"

    def analyze(self, ticker: str, data: dict[str, Any]) -> dict[str, Any]:
        """Run the bull/bear debate and produce a synthesized recommendation.

        Args:
            ticker: Stock symbol
            data: Dictionary with analyst outputs:
                - fundamental: dict from FundamentalAnalyst
                - technical: dict from TechnicalAnalyst
                - sentiment: dict from SentimentAnalyst
                - macro: dict from MacroAnalyst

        Returns:
            {
                "recommendation": "STRONG_BUY" | "BUY" | "HOLD" | "SELL" | "STRONG_SELL",
                "confidence": 0-100,
                "bull_case": "...",
                "bear_case": "...",
                "verdict": "...",
                "weighted_score": 0-100,
                "agent": "researcher"
            }
        """
        fundamental = data.get("fundamental", {})
        technical = data.get("technical", {})
        sentiment = data.get("sentiment", {})
        macro = data.get("macro", {})

        prompt = f"""You are a senior equity researcher. Synthesize the following analyst reports for {ticker} into a bull case and bear case, then give a final verdict.

## Fundamental Analyst
Rating: {fundamental.get('rating', 'N/A')} (Score: {fundamental.get('score', 'N/A')})
Reasoning: {fundamental.get('reasoning', 'N/A')}
Strengths: {fundamental.get('strengths', [])}
Red Flags: {fundamental.get('red_flags', [])}

## Technical Analyst
Rating: {technical.get('rating', 'N/A')} (Score: {technical.get('score', 'N/A')})
Reasoning: {technical.get('reasoning', 'N/A')}
Signals: {technical.get('signals', [])}

## Sentiment Analyst
Rating: {sentiment.get('rating', 'N/A')} (Score: {sentiment.get('score', 'N/A')})
Reasoning: {sentiment.get('reasoning', 'N/A')}
Key Themes: {sentiment.get('key_themes', [])}

## Macro Analyst
Rating: {macro.get('rating', 'N/A')} (Score: {macro.get('score', 'N/A')})
Reasoning: {macro.get('reasoning', 'N/A')}
Factors: {macro.get('factors', [])}
Risks: {macro.get('risks', [])}

## Instructions
1. Build the strongest BULL case using all positive signals
2. Build the strongest BEAR case using all negative signals
3. Weigh both sides and give a FINAL VERDICT
4. Weight fundamental analysis highest (40%), then technical (30%), macro (20%), sentiment (10%)

Respond with ONLY a JSON object:
{{
    "recommendation": "STRONG_BUY" or "BUY" or "HOLD" or "SELL" or "STRONG_SELL",
    "confidence": 0-100,
    "bull_case": "Concise bull argument (2-3 sentences)",
    "bear_case": "Concise bear argument (2-3 sentences)",
    "verdict": "Final verdict with reasoning (2-3 sentences)",
    "weighted_score": 0-100
}}"""
        response = self.call_sync(prompt)
        result = self._parse_json_response(response)
        result["agent"] = self.name
        return result
