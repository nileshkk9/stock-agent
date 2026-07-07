"""Data fetching layer for NSE Indian stocks.

Primary: Zerodha Kite Connect (real-time, verified data)
Fallback: yfinance (free, historical) + nsepython (NSE direct)
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import yfinance as yf

from src.config import config

logger = logging.getLogger(__name__)


class NSEFetcher:
    """Fetch stock data from NSE/BSE via multiple sources."""

    def __init__(self):
        self._kite = None
        self._use_kite = bool(config.kite.api_key)

    @property
    def kite(self):
        """Lazy init Kite Connect."""
        if self._kite is None and self._use_kite:
            try:
                from kiteconnect import KiteConnect

                self._kite = KiteConnect(api_key=config.kite.api_key)
                # Note: full auth requires interactive login flow
                # For now, use stored access token if available
                import os

                token = os.getenv("KITE_ACCESS_TOKEN")
                if token:
                    self._kite.set_access_token(token)
            except ImportError:
                logger.warning("kiteconnect not installed, falling back to yfinance")
                self._use_kite = False
            except Exception as e:
                logger.warning(f"Kite Connect init failed: {e}, falling back to yfinance")
                self._use_kite = False
        return self._kite

    def _nse_symbol(self, ticker: str) -> str:
        """Convert ticker to Yahoo Finance NSE format."""
        return f"{ticker}.NS"

    def get_historical(
        self,
        ticker: str,
        start: str | None = None,
        end: str | None = None,
        period: str = "5y",
        interval: str = "1d",
    ) -> pd.DataFrame:
        """Fetch historical OHLCV data.

        Args:
            ticker: NSE symbol (e.g., 'RELIANCE', 'TCS')
            start: Start date (YYYY-MM-DD)
            end: End date (YYYY-MM-DD)
            period: yfinance period string
            interval: yfinance interval

        Returns:
            DataFrame with columns: Open, High, Low, Close, Volume
        """
        # Try Kite first
        if self._use_kite and self.kite and start and end:
            try:
                return self._get_kite_historical(ticker, start, end, interval)
            except Exception as e:
                logger.warning(f"Kite historical failed for {ticker}: {e}")

        # Fallback to yfinance
        symbol = self._nse_symbol(ticker)
        try:
            stock = yf.Ticker(symbol)
            df = stock.history(start=start, end=end, period=period, interval=interval)
            if df.empty:
                logger.warning(f"No data from yfinance for {ticker}")
            return df
        except Exception as e:
            logger.error(f"yfinance failed for {ticker}: {e}")
            return pd.DataFrame()

    def _get_kite_historical(
        self, ticker: str, start: str, end: str, interval: str = "day"
    ) -> pd.DataFrame:
        """Fetch historical data via Kite Connect."""
        from_date = datetime.strptime(start, "%Y-%m-%d")
        to_date = datetime.strptime(end, "%Y-%m-%d")

        instrument_token = self._get_kite_instrument(ticker)
        if not instrument_token:
            raise ValueError(f"Instrument not found for {ticker}")

        data = self.kite.historical_data(
            instrument_token, from_date, to_date, interval
        )
        df = pd.DataFrame(data)
        if not df.empty:
            df["date"] = pd.to_datetime(df["date"])
            df.set_index("date", inplace=True)
            df.rename(
                columns={"open": "Open", "high": "High", "low": "Low", "close": "Close"},
                inplace=True,
            )
        return df

    def _get_kite_instrument(self, ticker: str) -> Optional[int]:
        """Look up instrument token for a ticker."""
        try:
            instruments = self.kite.instruments("NSE")
            for inst in instruments:
                if inst["tradingsymbol"] == ticker:
                    return inst["instrument_token"]
        except Exception:
            pass
        return None

    def get_current_price(self, ticker: str) -> Optional[float]:
        """Get latest price for a ticker."""
        if self._use_kite and self.kite:
            try:
                token = self._get_kite_instrument(ticker)
                if token:
                    quote = self.kite.ltp(f"NSE:{ticker}")
                    return quote.get(f"NSE:{ticker}", {}).get("last_price")
            except Exception:
                pass

        # yfinance fallback
        try:
            stock = yf.Ticker(self._nse_symbol(ticker))
            info = stock.info
            return info.get("currentPrice") or info.get("regularMarketPrice")
        except Exception:
            return None

    def get_fundamentals(self, ticker: str) -> dict:
        """Fetch fundamental data for a stock."""
        try:
            stock = yf.Ticker(self._nse_symbol(ticker))
            info = stock.info
            return {
                "pe_ratio": info.get("trailingPE"),
                "forward_pe": info.get("forwardPE"),
                "pb_ratio": info.get("priceToBook"),
                "roe": info.get("returnOnEquity"),
                "debt_to_equity": info.get("debtToEquity"),
                "market_cap": info.get("marketCap"),
                "revenue_growth": info.get("revenueGrowth"),
                "profit_margins": info.get("profitMargins"),
                "dividend_yield": info.get("dividendYield"),
                "beta": info.get("beta"),
                "sector": info.get("sector"),
                "industry": info.get("industry"),
            }
        except Exception as e:
            logger.error(f"Fundamentals fetch failed for {ticker}: {e}")
            return {}

    def get_nifty50_symbols(self) -> list[str]:
        """Return list of current Nifty 50 stock symbols."""
        # Standard Nifty 50 as of 2026
        return [
            "RELIANCE", "TCS", "HDFCBANK", "INFY", "HINDUNILVR",
            "ICICIBANK", "KOTAKBANK", "BHARTIARTL", "ITC", "SBIN",
            "BAJFINANCE", "LT", "AXISBANK", "ASIANPAINT", "MARUTI",
            "SUNPHARMA", "TITAN", "WIPRO", "HCLTECH", "ULTRACEMCO",
            "NTPC", "POWERGRID", "ADANIPORTS", "ADANIENT", "NESTLEIND",
            "BAJAJFINSV", "M&M", "TATAMOTORS", "TECHM", "JSWSTEEL",
            "TATASTEEL", "GRASIM", "BRITANNIA", "CIPLA", "DRREDDY",
            "APOLLOHOSP", "COALINDIA", "ONGC", "SBILIFE", "HDFCLIFE",
            "EICHERMOT", "DIVISLAB", "HEROMOTOCO", "BPCL", "HINDALCO",
            "TATACONSUM", "BAJAJ-AUTO", "BEL", "INDUSINDBK", "TRENT",
        ]
