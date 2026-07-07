"""Sentiment analysis agent — news, social media, market mood."""

from typing import Any

from src.agents.base import LLMAgent


class SentimentAnalyst(LLMAgent):
    """Analyzes news headlines and market sentiment for a stock."""

    name = "sentiment"

    def analyze(self, ticker: str, data: dict[str, Any]) -> dict[str, Any]:
        """Analyze sentiment from news headlines.

        Args:
            ticker: Stock symbol
            data: Dictionary with:
                - news: list of {title, source, published_at, snippet}

        Returns:
            {
                "rating": "BULLISH" | "NEUTRAL" | "BEARISH",
                "confidence": 0-100,
                "score": -100 to 100 (positive = bullish),
                "key_themes": [],
                "reasoning": "...",
            }
        """
        news = data.get("news", [])

        if not news:
            return {
                "rating": "NEUTRAL",
                "confidence": 50,
                "score": 0,
                "reasoning": "No recent news available",
                "key_themes": [],
                "agent": self.name,
            }

        headlines = "\n".join(
            f"- [{n.get('source', 'Unknown')}] {n.get('title', '')}: {n.get('snippet', '')}"
            for n in news[:10]
        )

        prompt = f"""Analyze the sentiment for {ticker} based on recent news headlines.

## Recent News
{headlines}

## Instructions
- Score sentiment from -100 (extremely bearish) to +100 (extremely bullish)
- Identify key themes driving sentiment
- Consider source credibility (Economic Times, Bloomberg > random blogs)

Respond with ONLY a JSON object:
{{
    "rating": "BULLISH" or "NEUTRAL" or "BEARISH",
    "confidence": 0-100,
    "score": -100 to 100,
    "reasoning": "2-3 sentence sentiment analysis",
    "key_themes": ["theme1", "theme2"]
}}"""
        response = self.call_sync(prompt)
        result = self._parse_json_response(response)
        result["agent"] = self.name
        return result
