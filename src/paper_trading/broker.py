"""Paper trading broker — multi-provider: Dhan Sandbox, Local Simulator, Kite.

Architecture:
    PaperBroker (facade)
    ├── LocalSimulatorBackend  ← enhanced local sim (default, zero setup)
    ├── DhanSandboxBackend     ← Dhan sandbox API (free, no Demat)
    └── KiteBackend            ← Zerodha Kite Connect (₹500/mo, future)
"""

import json
import logging
import random
from abc import ABC, abstractmethod
from datetime import datetime, time
from pathlib import Path
from typing import Any, Optional

import httpx

from src.config import config

logger = logging.getLogger(__name__)

ORDERS_FILE = Path(__file__).parent.parent.parent / "data" / "paper_orders.json"
PORTFOLIO_FILE = Path(__file__).parent.parent.parent / "data" / "paper_portfolio.json"
EQUITY_CURVE_FILE = Path(__file__).parent.parent.parent / "data" / "equity_curve.json"

# ── Market hours (NSE) ──────────────────────────────────────────────
MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)


def _is_market_open() -> bool:
    """Check if NSE is currently open (Mon-Fri, 9:15-15:30)."""
    now = datetime.now()
    if now.weekday() >= 5:  # Sat-Sun
        return False
    return MARKET_OPEN <= now.time() <= MARKET_CLOSE


# ══════════════════════════════════════════════════════════════════════
# Abstract Backend
# ══════════════════════════════════════════════════════════════════════


class BrokerBackend(ABC):
    """Abstract paper trading backend."""

    name: str = "base"

    @abstractmethod
    def connect(self) -> bool:
        """Initialize connection. Returns True if ready."""
        ...

    @abstractmethod
    def place_order(
        self,
        ticker: str,
        action: str,
        quantity: int,
        price: float,
        order_type: str = "MARKET",
        stop_loss: Optional[float] = None,
    ) -> dict:
        """Place a paper trade. Returns order dict."""
        ...

    @abstractmethod
    def get_positions(self) -> list[dict]:
        """Get current positions from broker."""
        ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """Cancel a pending order."""
        ...


# ══════════════════════════════════════════════════════════════════════
# Local Simulator Backend
# ══════════════════════════════════════════════════════════════════════


class LocalSimulatorBackend(BrokerBackend):
    """Enhanced local paper trading simulator.

    Features:
        - Realistic slippage (0.05-0.3% based on market cap proxy)
        - Market hours enforcement
        - Partial fills for large orders
        - Brokerage calculation (0.03% or ₹20 min)
    """

    name = "local_simulator"

    def __init__(self):
        self._connected = True  # Always available

    def connect(self) -> bool:
        logger.info("Local simulator ready (no external connection needed)")
        return True

    def place_order(
        self,
        ticker: str,
        action: str,
        quantity: int,
        price: float,
        order_type: str = "MARKET",
        stop_loss: Optional[float] = None,
    ) -> dict:
        # Slippage: simulate realistic fill price deviation
        slippage_pct = self._calculate_slippage(ticker, price)
        if action.upper() == "BUY":
            filled_price = round(price * (1 + slippage_pct), 2)
        else:
            filled_price = round(price * (1 - slippage_pct), 2)

        # Partial fill for large orders (>500 shares for stocks <₹1000)
        fill_pct = self._calculate_fill_pct(quantity, price)
        filled_qty = max(1, int(quantity * fill_pct))

        # Brokerage: 0.03% or ₹20 minimum
        brokerage = max(20, round(filled_price * filled_qty * 0.0003, 2))

        # Market hours warning
        market_open = _is_market_open()

        order = {
            "order_id": f"LOCAL_{datetime.now().strftime('%Y%m%d%H%M%S')}_{ticker}",
            "ticker": ticker,
            "action": action,
            "quantity": quantity,
            "filled_quantity": filled_qty,
            "price": price,
            "filled_price": filled_price,
            "order_type": order_type,
            "stop_loss": stop_loss,
            "status": "EXECUTED" if filled_qty > 0 else "REJECTED",
            "timestamp": datetime.now().isoformat(),
            "broker": self.name,
            "brokerage": brokerage,
            "slippage_pct": round(slippage_pct * 100, 3),
            "fill_pct": round(fill_pct * 100, 1),
            "market_open": market_open,
        }

        if not market_open:
            logger.warning(f"Order placed outside market hours: {ticker}")
        if filled_qty < quantity:
            logger.info(f"Partial fill: {filled_qty}/{quantity} shares of {ticker}")

        return order

    def _calculate_slippage(self, ticker: str, price: float) -> float:
        """Estimate slippage based on price (proxy for liquidity)."""
        if price < 100:
            return random.uniform(0.001, 0.005)  # 0.1-0.5% for penny stocks
        elif price < 500:
            return random.uniform(0.0005, 0.003)  # 0.05-0.3%
        elif price < 2000:
            return random.uniform(0.0003, 0.0015)  # 0.03-0.15%
        else:
            return random.uniform(0.0001, 0.001)  # 0.01-0.1% for large caps

    def _calculate_fill_pct(self, quantity: int, price: float) -> float:
        """Simulate partial fills for large orders."""
        if quantity <= 100:
            return 1.0
        elif quantity <= 500:
            return random.uniform(0.90, 1.0)
        elif quantity <= 2000:
            return random.uniform(0.75, 0.95)
        else:
            return random.uniform(0.60, 0.90)

    def get_positions(self) -> list[dict]:
        # Local simulator tracks positions locally via PaperPortfolio
        return []

    def cancel_order(self, order_id: str) -> bool:
        logger.info(f"Local simulator: cancel {order_id} (no-op)")
        return True


# ══════════════════════════════════════════════════════════════════════
# Dhan Sandbox Backend
# ══════════════════════════════════════════════════════════════════════


class DhanSandboxBackend(BrokerBackend):
    """Dhan Sandbox API — free paper trading, no Demat account needed.

    Sign up at https://developer.dhanhq.co/ to get:
        - client_id
        - access_token

    Sandbox details:
        - Base URL: https://sandbox.dhan.co/v2
        - Virtual ₹10L capital (resets daily)
        - All orders fill at price 100 (mock — test logic, not P&L)
        - No market data / WebSocket in sandbox
    """

    name = "dhan_sandbox"
    SANDBOX_URL = "https://sandbox.dhan.co/v2"

    # Dhan exchange segments
    NSE_EQ = "NSE_EQ"  # NSE Cash
    BSE_EQ = "BSE_EQ"  # BSE Cash
    NSE_FNO = "NSE_FNO"  # NSE Futures & Options

    # Dhan product types
    CNC = "CNC"  # Cash & Carry (delivery)
    INTRADAY = "INTRADAY"
    MTF = "MARGIN_TRADING"

    def __init__(self, client_id: str = "", access_token: str = ""):
        self.client_id = client_id or config.dhan.client_id
        self.access_token = access_token or config.dhan.access_token
        self._connected = False

    def connect(self) -> bool:
        if not self.client_id or not self.access_token:
            logger.warning("Dhan credentials not configured. Set DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN in .env")
            return False

        # Quick health check
        try:
            resp = httpx.get(
                f"{self.SANDBOX_URL}/funds",
                headers={
                    "access-token": self.access_token,
                    "client-id": self.client_id,
                    "Accept": "application/json",
                },
                timeout=10,
            )
            if resp.status_code == 200:
                self._connected = True
                logger.info("Dhan sandbox connected ✓")
                return True
            else:
                logger.warning(f"Dhan sandbox returned {resp.status_code}: {resp.text[:200]}")
                return False
        except Exception as e:
            logger.warning(f"Dhan sandbox connection failed: {e}")
            return False

    def place_order(
        self,
        ticker: str,
        action: str,
        quantity: int,
        price: float,
        order_type: str = "MARKET",
        stop_loss: Optional[float] = None,
    ) -> dict:
        if not self._connected:
            logger.warning("Dhan not connected, order not sent to sandbox")
            return {
                "order_id": f"DHAN_FAILED_{datetime.now().strftime('%Y%m%d%H%M%S')}",
                "ticker": ticker,
                "action": action,
                "quantity": quantity,
                "status": "REJECTED",
                "error": "Not connected",
                "broker": self.name,
            }

        # Map action to Dhan transaction type
        transaction_type = "BUY" if action.upper() == "BUY" else "SELL"

        # Dhan requires security_id (not ticker symbol directly)
        # For sandbox testing, we use a numeric ID — map if available
        security_id = self._ticker_to_security_id(ticker)

        payload = {
            "dhanClientId": self.client_id,
            "transactionType": transaction_type,
            "exchangeSegment": self.NSE_EQ,
            "productType": self.CNC,
            "orderType": order_type,
            "validity": "DAY",
            "securityId": str(security_id),
            "quantity": quantity,
            "price": price if order_type == "LIMIT" else 0,
        }

        if stop_loss and order_type == "STOP_LOSS":
            payload["triggerPrice"] = stop_loss

        try:
            resp = httpx.post(
                f"{self.SANDBOX_URL}/orders",
                headers={
                    "access-token": self.access_token,
                    "client-id": self.client_id,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                json=payload,
                timeout=15,
            )
            data = resp.json() if resp.text else {}

            if resp.status_code == 200:
                order_id = data.get("orderId", f"DHAN_{datetime.now().strftime('%Y%m%d%H%M%S')}")
                logger.info(f"Dhan sandbox order placed: {action} {quantity} {ticker} → #{order_id}")
                return {
                    "order_id": str(order_id),
                    "ticker": ticker,
                    "action": action,
                    "quantity": quantity,
                    "price": price,
                    "filled_price": 100,  # Sandbox always fills at 100
                    "order_type": order_type,
                    "stop_loss": stop_loss,
                    "status": "EXECUTED",
                    "timestamp": datetime.now().isoformat(),
                    "broker": self.name,
                    "brokerage": 0,
                    "dhan_response": data,
                }
            else:
                logger.error(f"Dhan order failed: {resp.status_code} — {resp.text[:300]}")
                return {
                    "order_id": f"DHAN_ERR_{datetime.now().strftime('%Y%m%d%H%M%S')}",
                    "ticker": ticker,
                    "action": action,
                    "quantity": quantity,
                    "status": "REJECTED",
                    "error": data.get("message", resp.text[:200]),
                    "broker": self.name,
                    "timestamp": datetime.now().isoformat(),
                }

        except Exception as e:
            logger.error(f"Dhan order exception: {e}")
            return {
                "order_id": f"DHAN_EXC_{datetime.now().strftime('%Y%m%d%H%M%S')}",
                "ticker": ticker,
                "action": action,
                "quantity": quantity,
                "status": "REJECTED",
                "error": str(e),
                "broker": self.name,
                "timestamp": datetime.now().isoformat(),
            }

    def _ticker_to_security_id(self, ticker: str) -> int:
        """Convert NSE ticker to Dhan security ID.

        Dhan requires numeric security IDs. For sandbox, we can use a
        simple hash or a lookup. Production would use Dhan's master contract file.
        """
        # Simple hash for sandbox testing
        # In production, load from Dhan's security master CSV
        return abs(hash(ticker)) % 100000

    def get_positions(self) -> list[dict]:
        if not self._connected:
            return []
        try:
            resp = httpx.get(
                f"{self.SANDBOX_URL}/positions",
                headers={
                    "access-token": self.access_token,
                    "client-id": self.client_id,
                    "Accept": "application/json",
                },
                timeout=10,
            )
            return resp.json() if resp.status_code == 200 else []
        except Exception:
            return []

    def cancel_order(self, order_id: str) -> bool:
        if not self._connected:
            return False
        try:
            resp = httpx.delete(
                f"{self.SANDBOX_URL}/orders/{order_id}",
                headers={
                    "access-token": self.access_token,
                    "client-id": self.client_id,
                },
                timeout=10,
            )
            return resp.status_code == 200
        except Exception:
            return False

    def get_funds(self) -> dict:
        """Get sandbox fund details."""
        if not self._connected:
            return {}
        try:
            resp = httpx.get(
                f"{self.SANDBOX_URL}/funds",
                headers={
                    "access-token": self.access_token,
                    "client-id": self.client_id,
                    "Accept": "application/json",
                },
                timeout=10,
            )
            return resp.json() if resp.status_code == 200 else {}
        except Exception:
            return {}


# ══════════════════════════════════════════════════════════════════════
# Kite Backend (kept for future)
# ══════════════════════════════════════════════════════════════════════


class KiteBackend(BrokerBackend):
    """Zerodha Kite Connect sandbox — ₹500/mo data, free order APIs."""

    name = "kite"

    def __init__(self):
        self._kite = None

    def connect(self) -> bool:
        if not config.kite.api_key:
            logger.info("Kite API key not configured")
            return False
        try:
            from kiteconnect import KiteConnect
            import os

            self._kite = KiteConnect(api_key=config.kite.api_key)
            token = os.getenv("KITE_ACCESS_TOKEN")
            if token:
                self._kite.set_access_token(token)
                logger.info("Kite connected ✓")
                return True
            else:
                logger.info("Kite needs OAuth login. Run: python scripts/kite_login.py")
                return False
        except ImportError:
            logger.warning("kiteconnect not installed")
            return False
        except Exception as e:
            logger.warning(f"Kite connection failed: {e}")
            return False

    def place_order(
        self,
        ticker: str,
        action: str,
        quantity: int,
        price: float,
        order_type: str = "MARKET",
        stop_loss: Optional[float] = None,
    ) -> dict:
        if not self._kite:
            return {
                "order_id": f"KITE_FAILED_{datetime.now().strftime('%Y%m%d%H%M%S')}",
                "status": "REJECTED",
                "error": "Kite not connected",
                "broker": self.name,
            }
        try:
            from kiteconnect import KiteConnect

            transaction_type = "BUY" if action.upper() == "BUY" else "SELL"
            order_id = self._kite.place_order(
                variety="regular",
                exchange="NSE",
                tradingsymbol=ticker,
                transaction_type=transaction_type,
                quantity=quantity,
                product="CNC",
                order_type=order_type,
            )
            return {
                "order_id": str(order_id),
                "ticker": ticker,
                "action": action,
                "quantity": quantity,
                "price": price,
                "status": "EXECUTED",
                "broker": self.name,
                "timestamp": datetime.now().isoformat(),
            }
        except Exception as e:
            logger.error(f"Kite order failed: {e}")
            return {
                "order_id": f"KITE_ERR_{datetime.now().strftime('%Y%m%d%H%M%S')}",
                "status": "REJECTED",
                "error": str(e),
                "broker": self.name,
            }

    def get_positions(self) -> list[dict]:
        if not self._kite:
            return []
        try:
            return self._kite.positions().get("net", [])
        except Exception:
            return []

    def cancel_order(self, order_id: str) -> bool:
        if not self._kite:
            return False
        try:
            self._kite.cancel_order(variety="regular", order_id=order_id)
            return True
        except Exception:
            return False


# ══════════════════════════════════════════════════════════════════════
# PaperBroker Facade
# ══════════════════════════════════════════════════════════════════════


class PaperBroker:
    """Facade that picks the best available paper trading backend.

    Priority (configurable via PAPER_TRADING_BROKER env var):
        - "dhan"  → DhanSandboxBackend
        - "kite"  → KiteBackend
        - "local" → LocalSimulatorBackend (default)
        - "auto"  → Try Dhan → Kite → Local in order
    """

    BACKENDS = {
        "dhan": DhanSandboxBackend,
        "kite": KiteBackend,
        "local": LocalSimulatorBackend,
    }

    def __init__(self, preferred: str = ""):
        self.backend: BrokerBackend
        self._backend_name: str = ""

        # Determine which backend to use
        import os

        choice = preferred or os.getenv("PAPER_TRADING_BROKER", "auto")

        if choice == "auto":
            self._auto_select()
        elif choice in self.BACKENDS:
            self._init_backend(choice)
        else:
            logger.warning(f"Unknown broker '{choice}', falling back to local")
            self._init_backend("local")

    def _auto_select(self):
        """Try backends in order: Dhan → Kite → Local."""
        for name in ["dhan", "kite"]:
            if self._init_backend(name):
                return
        logger.info("No external broker available, using local simulator")
        self._init_backend("local")

    def _init_backend(self, name: str) -> bool:
        backend_cls = self.BACKENDS[name]
        self.backend = backend_cls()
        self._backend_name = name

        if self.backend.connect():
            logger.info(f"Active broker: {self.backend.name} ({name})")
            return True
        return False

    @property
    def is_connected(self) -> bool:
        return getattr(self.backend, "_connected", True)

    @property
    def active_broker(self) -> str:
        return self._backend_name

    def place_order(
        self,
        ticker: str,
        action: str,
        quantity: int,
        price: float,
        order_type: str = "MARKET",
        stop_loss: Optional[float] = None,
    ) -> dict:
        order = self.backend.place_order(ticker, action, quantity, price, order_type, stop_loss)
        self._save_order(order)
        return order

    def get_positions(self) -> list[dict]:
        return self.backend.get_positions()

    def cancel_order(self, order_id: str) -> bool:
        return self.backend.cancel_order(order_id)

    def _save_order(self, order: dict):
        orders = []
        if ORDERS_FILE.exists():
            try:
                orders = json.loads(ORDERS_FILE.read_text())
            except json.JSONDecodeError:
                pass
        orders.append(order)
        ORDERS_FILE.parent.mkdir(parents=True, exist_ok=True)
        ORDERS_FILE.write_text(json.dumps(orders, indent=2, default=str))

    def get_order_history(self) -> list[dict]:
        if ORDERS_FILE.exists():
            try:
                return json.loads(ORDERS_FILE.read_text())
            except json.JSONDecodeError:
                pass
        return []


# ══════════════════════════════════════════════════════════════════════
# PaperPortfolio (unchanged — tracks cash, holdings, P&L locally)
# ══════════════════════════════════════════════════════════════════════


class PaperPortfolio:
    """Virtual paper trading portfolio tracker."""

    def __init__(self, initial_cash: float | None = None):
        self.initial_cash = initial_cash or config.paper_trading.initial_capital
        self.cash = self.initial_cash
        self.holdings: dict[str, dict] = {}
        self._load()

    def _load(self):
        if PORTFOLIO_FILE.exists():
            data = json.loads(PORTFOLIO_FILE.read_text())
            self.cash = data.get("cash", self.initial_cash)
            self.holdings = data.get("holdings", {})

    def _save(self):
        PORTFOLIO_FILE.parent.mkdir(parents=True, exist_ok=True)
        PORTFOLIO_FILE.write_text(
            json.dumps(
                {"cash": self.cash, "holdings": self.holdings},
                indent=2,
                default=str,
            )
        )

    def execute_order(self, order: dict):
        """Apply an executed order to the portfolio."""
        ticker = order["ticker"]
        action = order["action"].upper()
        # Use filled_quantity if available (partial fills), else quantity
        quantity = order.get("filled_quantity", order["quantity"])
        price = order.get("filled_price", order["price"])
        brokerage = order.get("brokerage", 0)

        if action == "BUY":
            cost = price * quantity + brokerage
            if cost > self.cash:
                logger.warning(
                    f"Insufficient cash for BUY {ticker}: need ₹{cost:,.0f}, have ₹{self.cash:,.0f}"
                )
                return

            self.cash -= cost
            if ticker in self.holdings:
                h = self.holdings[ticker]
                total_qty = h["quantity"] + quantity
                h["avg_price"] = (h["avg_price"] * h["quantity"] + price * quantity) / total_qty
                h["quantity"] = total_qty
            else:
                self.holdings[ticker] = {
                    "quantity": quantity,
                    "avg_price": price,
                    "first_bought": order["timestamp"],
                }

        elif action == "SELL":
            if ticker not in self.holdings:
                logger.warning(f"No holding for {ticker} to sell")
                return

            h = self.holdings[ticker]
            sell_qty = min(quantity, h["quantity"])
            proceeds = price * sell_qty - brokerage
            self.cash += proceeds

            h["quantity"] -= sell_qty
            if h["quantity"] <= 0:
                del self.holdings[ticker]

        self._save()

    def get_value(self, prices: dict[str, float]) -> float:
        holdings_value = sum(
            h["quantity"] * prices.get(ticker, h["avg_price"])
            for ticker, h in self.holdings.items()
        )
        return self.cash + holdings_value

    def get_summary(self, prices: dict[str, float]) -> dict:
        total_value = self.get_value(prices)
        pnl = total_value - self.initial_cash

        holdings_list = []
        for ticker, h in self.holdings.items():
            current_price = prices.get(ticker, h["avg_price"])
            holding_value = h["quantity"] * current_price
            cost_value = h["quantity"] * h["avg_price"]
            holdings_list.append(
                {
                    "ticker": ticker,
                    "quantity": h["quantity"],
                    "avg_price": h["avg_price"],
                    "current_price": current_price,
                    "value": round(holding_value, 2),
                    "pnl": round(holding_value - cost_value, 2),
                    "pnl_pct": round((current_price / h["avg_price"] - 1) * 100, 2),
                }
            )

        return {
            "cash": round(self.cash, 2),
            "holdings_value": round(total_value - self.cash, 2),
            "total_value": round(total_value, 2),
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl / self.initial_cash * 100, 2),
            "initial_capital": self.initial_cash,
            "holdings": holdings_list,
        }

    def reset(self):
        self.cash = self.initial_cash
        self.holdings = {}
        self._save()

    def snapshot_equity(self, prices: dict[str, float]) -> dict:
        """Record today's portfolio value in the equity curve.

        Call once per day (after market close) to build the equity curve.
        Returns the snapshot entry.
        """
        total = self.get_value(prices)
        today = datetime.now().strftime("%Y-%m-%d")

        entries = []
        if EQUITY_CURVE_FILE.exists():
            try:
                entries = json.loads(EQUITY_CURVE_FILE.read_text())
            except json.JSONDecodeError:
                pass

        # Don't duplicate same day
        if entries and entries[-1].get("date") == today:
            entries[-1] = {
                "date": today,
                "value": round(total, 2),
                "cash": round(self.cash, 2),
                "holdings_count": len(self.holdings),
            }
        else:
            entries.append({
                "date": today,
                "value": round(total, 2),
                "cash": round(self.cash, 2),
                "holdings_count": len(self.holdings),
            })

        EQUITY_CURVE_FILE.parent.mkdir(parents=True, exist_ok=True)
        EQUITY_CURVE_FILE.write_text(json.dumps(entries, indent=2))
        return entries[-1]

    def get_equity_curve(self) -> list[dict]:
        """Get historical equity curve data."""
        if EQUITY_CURVE_FILE.exists():
            try:
                return json.loads(EQUITY_CURVE_FILE.read_text())
            except json.JSONDecodeError:
                pass
        return []

    def get_todays_orders(self) -> list[dict]:
        """Get orders placed today."""
        today = datetime.now().strftime("%Y-%m-%d")
        orders = []
        if ORDERS_FILE.exists():
            try:
                all_orders = json.loads(ORDERS_FILE.read_text())
                orders = [o for o in all_orders if o.get("timestamp", "").startswith(today)]
            except json.JSONDecodeError:
                pass
        return orders

    def get_daily_pnl(self, prices: dict[str, float]) -> dict:
        """Calculate today's P&L vs yesterday's equity curve snapshot.

        Returns:
            {
                "today_value": float,
                "yesterday_value": float or None,
                "daily_pnl": float,
                "daily_pnl_pct": float,
                "realized_pnl": float,
                "unrealized_pnl": float,
                "new": bool,  # True if no prior snapshot
            }
        """
        today_value = self.get_value(prices)
        curve = self.get_equity_curve()

        yesterday_value = None
        if len(curve) >= 2:
            yesterday_value = curve[-2]["value"]
        elif len(curve) == 1:
            yesterday_value = self.initial_cash

        # Calculate realized P&L from today's orders
        todays_orders = self.get_todays_orders()
        realized_pnl = 0.0
        for order in todays_orders:
            if order.get("action", "").upper() == "SELL":
                qty = order.get("filled_quantity", order.get("quantity", 0))
                fill_price = order.get("filled_price", order.get("price", 0))
                # Estimate cost from holdings (approximate)
                realized_pnl += qty * fill_price * 0.01  # Placeholder — real calc needs cost basis

        # Unrealized = today change - realized
        unrealized_pnl = 0.0
        if yesterday_value:
            unrealized_pnl = (today_value - yesterday_value) - realized_pnl

        return {
            "today_value": round(today_value, 2),
            "yesterday_value": round(yesterday_value, 2) if yesterday_value else None,
            "daily_pnl": round(today_value - yesterday_value, 2) if yesterday_value else 0,
            "daily_pnl_pct": round((today_value / yesterday_value - 1) * 100, 2) if yesterday_value else 0,
            "realized_pnl": round(realized_pnl, 2),
            "unrealized_pnl": round(unrealized_pnl, 2),
            "new": yesterday_value is None,
        }
