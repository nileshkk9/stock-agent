"""Technical analysis agent — RSI, MACD, moving averages, patterns."""

from typing import Any

import numpy as np
import pandas as pd

from src.agents.base import LLMAgent


class TechnicalAnalyst(LLMAgent):
    """Evaluates technical indicators and chart patterns."""

    name = "technical"

    def analyze(self, ticker: str, data: dict[str, Any]) -> dict[str, Any]:
        """Analyze technical indicators.

        Args:
            ticker: Stock symbol
            data: Dictionary with:
                - price_df: DataFrame with OHLCV (optional, for direct computation)
                - indicators: pre-computed dict of indicator values

        Returns:
            {
                "rating": "BUY" | "HOLD" | "SELL",
                "confidence": 0-100,
                "score": 0-100,
                "reasoning": "...",
                "indicators": {},
                "signals": []
            }
        """
        price_df = data.get("price_df")
        if price_df is not None and not price_df.empty:
            indicators = self._compute_indicators(price_df)
        else:
            indicators = data.get("indicators", {})

        prompt = f"""Analyze technical indicators for {ticker} on NSE India.

## Technical Indicators
{self._format_indicators(indicators)}

## Guidelines
- RSI > 70: overbought (bearish signal)
- RSI < 30: oversold (bullish signal)
- MACD above signal line: bullish
- Price above 50-day MA: bullish trend
- Price above 200-day MA: long-term bullish

Respond with ONLY a JSON object:
{{
    "rating": "BUY" or "HOLD" or "SELL",
    "confidence": 0-100,
    "score": 0-100,
    "reasoning": "2-3 sentence technical analysis",
    "signals": ["signal1", "signal2"],
    "key_levels": {{"support": value, "resistance": value}}
}}"""
        response = self.call_sync(prompt)
        result = self._parse_json_response(response)
        result["agent"] = self.name
        result["indicators"] = indicators
        return result

    def _compute_indicators(self, df: pd.DataFrame) -> dict:
        """Compute technical indicators from OHLCV data."""
        close = df["Close"].values
        high = df["High"].values
        low = df["Low"].values
        volume = df["Volume"].values if "Volume" in df else None

        indicators = {}

        # RSI (14-day)
        rsi = self._compute_rsi(close, 14)
        indicators["rsi"] = round(float(rsi[-1]), 1) if len(rsi) > 0 else None

        # MACD
        ema12 = self._ema(close, 12)
        ema26 = self._ema(close, 26)
        macd_line = ema12 - ema26
        signal_line = self._ema(macd_line, 9)
        indicators["macd"] = round(float(macd_line[-1]), 2) if len(macd_line) > 0 else None
        indicators["macd_signal"] = round(float(signal_line[-1]), 2) if len(signal_line) > 0 else None
        indicators["macd_histogram"] = (
            round(float(macd_line[-1] - signal_line[-1]), 2)
            if len(macd_line) > 0
            else None
        )

        # Moving Averages
        indicators["sma_50"] = round(float(np.mean(close[-50:])), 2) if len(close) >= 50 else None
        indicators["sma_200"] = round(float(np.mean(close[-200:])), 2) if len(close) >= 200 else None
        indicators["current_price"] = round(float(close[-1]), 2) if len(close) > 0 else None

        # Bollinger Bands
        if len(close) >= 20:
            sma20 = np.mean(close[-20:])
            std20 = np.std(close[-20:])
            indicators["bb_upper"] = round(float(sma20 + 2 * std20), 2)
            indicators["bb_lower"] = round(float(sma20 - 2 * std20), 2)

        # Volume trend
        if volume is not None and len(volume) >= 20:
            indicators["volume_trend"] = "increasing" if np.mean(volume[-5:]) > np.mean(volume[-20:]) else "decreasing"

        # Support/Resistance (simple: recent lows/highs)
        if len(close) >= 20:
            indicators["support"] = round(float(np.min(low[-20:])), 2)
            indicators["resistance"] = round(float(np.max(high[-20:])), 2)

        return indicators

    def _compute_rsi(self, prices: np.ndarray, period: int = 14) -> np.ndarray:
        """Compute Relative Strength Index."""
        deltas = np.diff(prices)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)

        avg_gains = np.zeros_like(prices, dtype=float)
        avg_losses = np.zeros_like(prices, dtype=float)

        if len(gains) >= period:
            avg_gains[period] = np.mean(gains[:period])
            avg_losses[period] = np.mean(losses[:period])

            for i in range(period + 1, len(prices)):
                avg_gains[i] = (avg_gains[i - 1] * (period - 1) + gains[i - 1]) / period
                avg_losses[i] = (avg_losses[i - 1] * (period - 1) + losses[i - 1]) / period

        rs = np.divide(avg_gains, avg_losses, out=np.zeros_like(avg_gains), where=avg_losses != 0)
        rsi = 100 - (100 / (1 + rs))
        rsi[:period] = 50  # neutral for early values
        return rsi

    def _ema(self, prices: np.ndarray, period: int) -> np.ndarray:
        """Compute Exponential Moving Average."""
        ema = np.zeros_like(prices, dtype=float)
        if len(prices) > 0:
            ema[0] = prices[0]
            multiplier = 2 / (period + 1)
            for i in range(1, len(prices)):
                ema[i] = (prices[i] - ema[i - 1]) * multiplier + ema[i - 1]
        return ema

    def _format_indicators(self, indicators: dict) -> str:
        lines = []
        for k, v in indicators.items():
            lines.append(f"- {k}: {v}")
        return "\n".join(lines) if lines else "No indicators computed"
