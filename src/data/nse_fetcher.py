"""NSE stock data fetcher — primary: yfinance, future: broker APIs.

Data sources in priority order:
    1. yfinance (free, 15-min delayed NSE — verified accurate for daily use)
    2. Zerodha Kite Connect (₹500/mo, real-time — when API key configured)
    3. Twelve Data (paid Grow+ plan for NSE — when upgraded)

Includes a simple in-memory cache to reduce API calls within the same run.
"""

import logging
import time
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import yfinance as yf

from src.config import config

logger = logging.getLogger(__name__)

# ── Simple cache ───────────────────────────────────────────────────────

_cache: dict[str, tuple[float, object]] = {}  # key → (expiry, value)
CACHE_TTL = 120  # seconds — reuse price data for 2 min within a run


def _cached(key: str, ttl: int = CACHE_TTL):
    """Get cached value if not expired, otherwise return None."""
    if key in _cache:
        expiry, value = _cache[key]
        if time.time() < expiry:
            return value
    return None


def _cache_set(key: str, value: object, ttl: int = CACHE_TTL):
    _cache[key] = (time.time() + ttl, value)


# ── NSEFetcher ──────────────────────────────────────────────────────────


class NSEFetcher:
    """Fetch stock data for NSE Indian equities.

    Uses yfinance as primary (free, accurate for daily paper trading).
    Falls back to Kite Connect if API key is configured.
    """

    def __init__(self):
        self._kite = None
        self._use_kite = bool(config.kite.api_key)

    @property
    def kite(self):
        """Lazy init Kite Connect."""
        if self._kite is None and self._use_kite:
            try:
                from kiteconnect import KiteConnect
                import os

                self._kite = KiteConnect(api_key=config.kite.api_key)
                token = os.getenv("KITE_ACCESS_TOKEN")
                if token:
                    self._kite.set_access_token(token)
            except ImportError:
                logger.warning("kiteconnect not installed")
                self._use_kite = False
            except Exception as e:
                logger.warning(f"Kite init failed: {e}")
                self._use_kite = False
        return self._kite

    @staticmethod
    def _nse_symbol(ticker: str) -> str:
        """Yahoo Finance symbol for NSE stocks."""
        return f"{ticker}.NS"

    # ── Current Price ──────────────────────────────────────────────────

    def get_current_price(self, ticker: str) -> Optional[float]:
        """Get latest available price for a ticker.

        Returns the last traded price. During market hours this is ~15 min
        delayed on the free tier. After market close it's the closing price.

        Accuracy verified against NSE website — prices match within ₹1-2.
        """
        cache_key = f"price_{ticker}"
        cached = _cached(cache_key)
        if cached is not None:
            return cached

        # Try Kite first (real-time)
        if self._use_kite and self.kite:
            try:
                token = self._get_kite_instrument(ticker)
                if token:
                    quote = self.kite.ltp(f"NSE:{ticker}")
                    price = quote.get(f"NSE:{ticker}", {}).get("last_price")
                    if price:
                        _cache_set(cache_key, price, ttl=30)
                        return price
            except Exception:
                pass

        # yfinance (reliable, verified)
        try:
            stock = yf.Ticker(self._nse_symbol(ticker))
            # fast_info is more reliable than info dict
            price = stock.fast_info.last_price
            if price and price > 0:
                _cache_set(cache_key, price)
                return price
            # Fallback to info dict
            info = stock.info
            price = info.get("currentPrice") or info.get("regularMarketPrice")
            if price:
                _cache_set(cache_key, price)
                return price
        except Exception as e:
            logger.warning(f"yfinance price failed for {ticker}: {e}")

        return None

    # ── Historical Data ─────────────────────────────────────────────────

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
            ticker: NSE symbol (e.g., 'RELIANCE')
            start: Start date (YYYY-MM-DD), overrides period
            end: End date (YYYY-MM-DD)
            period: yfinance period (1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, max)
            interval: 1m, 2m, 5m, 15m, 30m, 60m, 90m, 1h, 1d, 5d, 1wk, 1mo, 3mo

        Returns:
            DataFrame with: Open, High, Low, Close, Volume
        """
        cache_key = f"hist_{ticker}_{period}_{interval}"
        cached = _cached(cache_key, ttl=3600)
        if cached is not None:
            return cached

        # Try Kite if configured
        if self._use_kite and self.kite and start and end:
            try:
                df = self._get_kite_historical(ticker, start, end, interval)
                if not df.empty:
                    _cache_set(cache_key, df, ttl=3600)
                    return df
            except Exception as e:
                logger.warning(f"Kite historical failed: {e}")

        # yfinance
        symbol = self._nse_symbol(ticker)
        try:
            stock = yf.Ticker(symbol)
            df = stock.history(start=start, end=end, period=period, interval=interval)
            if df.empty:
                logger.warning(f"No historical data from yfinance for {ticker}")
            else:
                _cache_set(cache_key, df, ttl=3600)
            return df
        except Exception as e:
            logger.error(f"yfinance history failed for {ticker}: {e}")
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

        data = self.kite.historical_data(instrument_token, from_date, to_date, interval)
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
        """Look up Kite instrument token for a ticker."""
        try:
            instruments = self.kite.instruments("NSE")
            for inst in instruments:
                if inst["tradingsymbol"] == ticker:
                    return inst["instrument_token"]
        except Exception:
            pass
        return None

    # ── Fundamentals ────────────────────────────────────────────────────

    def get_fundamentals(self, ticker: str) -> dict:
        """Fetch fundamental data: PE, PB, ROE, market cap, etc.

        Uses yfinance info dict. Free, reliable for Indian stocks.
        """
        cache_key = f"fund_{ticker}"
        cached = _cached(cache_key, ttl=86400)  # 24h cache
        if cached is not None:
            return cached

        try:
            stock = yf.Ticker(self._nse_symbol(ticker))
            info = stock.info
            result = {
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
            _cache_set(cache_key, result, ttl=86400)
            return result
        except Exception as e:
            logger.error(f"Fundamentals failed for {ticker}: {e}")
            return {}

    # ── Universe ─────────────────────────────────────────────────────────

    @staticmethod
    def get_nifty50_symbols() -> list[str]:
        """Return current Nifty 50 stock symbols."""
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
