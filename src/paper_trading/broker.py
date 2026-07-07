"""Paper trading broker integration — Zerodha Kite Connect sandbox."""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from src.config import config

logger = logging.getLogger(__name__)

ORDERS_FILE = Path(__file__).parent.parent.parent / "data" / "paper_orders.json"
PORTFOLIO_FILE = Path(__file__).parent.parent.parent / "data" / "paper_portfolio.json"


class PaperBroker:
    """Paper trading broker that mirrors Zerodha Kite sandbox or simulates locally."""

    def __init__(self):
        self._kite = None
        self._use_kite = bool(config.kite.api_key)
        self._sandbox_mode = False

    @property
    def is_connected(self) -> bool:
        return self._use_kite and self._kite is not None

    def connect(self) -> bool:
        """Connect to Kite sandbox if configured."""
        if not self._use_kite:
            logger.info("Kite not configured, using local simulator")
            return False

        try:
            from kiteconnect import KiteConnect

            self._kite = KiteConnect(api_key=config.kite.api_key)

            # Try stored access token first
            import os

            token = os.getenv("KITE_ACCESS_TOKEN")
            if token:
                self._kite.set_access_token(token)
                logger.info("Connected to Kite sandbox")
                return True

            # Need interactive login
            logger.info("Kite needs interactive login. Run: python scripts/kite_login.py")
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
        """Place a paper trade order.

        Returns:
            {"order_id": str, "status": "EXECUTED"|"PENDING", "filled_price": float}
        """
        order = {
            "order_id": f"PAPER_{datetime.now().strftime('%Y%m%d%H%M%S')}_{ticker}",
            "ticker": ticker,
            "action": action,
            "quantity": quantity,
            "price": price,
            "order_type": order_type,
            "stop_loss": stop_loss,
            "status": "EXECUTED",
            "filled_price": price,
            "timestamp": datetime.now().isoformat(),
            "brokerage": round(price * quantity * 0.0003, 2),
        }

        # If Kite connected, place real sandbox order
        if self._use_kite and self._kite:
            try:
                kite_order = self._place_kite_order(ticker, action, quantity, order_type)
                order["order_id"] = str(kite_order)
                order["broker"] = "kite_sandbox"
                logger.info(f"Kite sandbox order placed: {action} {quantity} {ticker}")
            except Exception as e:
                logger.error(f"Kite order failed: {e}, falling back to local")
                order["broker"] = "local_simulator"
        else:
            order["broker"] = "local_simulator"

        # Save to orders file
        self._save_order(order)
        return order

    def _place_kite_order(
        self, ticker: str, action: str, quantity: int, order_type: str
    ) -> int:
        """Place order via Kite Connect sandbox API."""
        exchange = "NSE"
        transaction_type = "BUY" if action.upper() == "BUY" else "SELL"
        product = "CNC"  # Cash and Carry (delivery)

        order_id = self._kite.place_order(
            variety="regular",
            exchange=exchange,
            tradingsymbol=ticker,
            transaction_type=transaction_type,
            quantity=quantity,
            product=product,
            order_type=order_type,
        )
        return order_id

    def get_positions(self) -> list[dict]:
        """Get current positions."""
        if self._use_kite and self._kite:
            try:
                positions = self._kite.positions()
                return positions.get("net", [])
            except Exception as e:
                logger.warning(f"Kite positions fetch failed: {e}")
        return []

    def _save_order(self, order: dict):
        """Persist order to JSON file."""
        orders = []
        if ORDERS_FILE.exists():
            orders = json.loads(ORDERS_FILE.read_text())
        orders.append(order)
        ORDERS_FILE.parent.mkdir(parents=True, exist_ok=True)
        ORDERS_FILE.write_text(json.dumps(orders, indent=2, default=str))

    def get_order_history(self) -> list[dict]:
        """Get all past orders."""
        if ORDERS_FILE.exists():
            return json.loads(ORDERS_FILE.read_text())
        return []


class PaperPortfolio:
    """Virtual paper trading portfolio tracker."""

    def __init__(self, initial_cash: float | None = None):
        self.initial_cash = initial_cash or config.paper_trading.initial_capital
        self.cash = self.initial_cash
        self.holdings: dict[str, dict] = {}
        self._load()

    def _load(self):
        """Load portfolio state from disk."""
        if PORTFOLIO_FILE.exists():
            data = json.loads(PORTFOLIO_FILE.read_text())
            self.cash = data.get("cash", self.initial_cash)
            self.holdings = data.get("holdings", {})

    def _save(self):
        """Persist portfolio state."""
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
        quantity = order["quantity"]
        price = order["filled_price"]
        brokerage = order.get("brokerage", 0)

        if action == "BUY":
            cost = price * quantity + brokerage
            if cost > self.cash:
                logger.warning(f"Insufficient cash for BUY {ticker}: need ₹{cost:,.0f}, have ₹{self.cash:,.0f}")
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
        """Get total portfolio value at current prices."""
        holdings_value = sum(
            h["quantity"] * prices.get(ticker, h["avg_price"])
            for ticker, h in self.holdings.items()
        )
        return self.cash + holdings_value

    def get_summary(self, prices: dict[str, float]) -> dict:
        """Get portfolio summary for reporting."""
        total_value = self.get_value(prices)
        pnl = total_value - self.initial_cash

        holdings_list = []
        for ticker, h in self.holdings.items():
            current_price = prices.get(ticker, h["avg_price"])
            holding_value = h["quantity"] * current_price
            cost_value = h["quantity"] * h["avg_price"]
            holdings_list.append({
                "ticker": ticker,
                "quantity": h["quantity"],
                "avg_price": h["avg_price"],
                "current_price": current_price,
                "value": round(holding_value, 2),
                "pnl": round(holding_value - cost_value, 2),
                "pnl_pct": round((current_price / h["avg_price"] - 1) * 100, 2),
            })

        return {
            "cash": round(self.cash, 2),
            "holdings_value": round(total_value - self.cash, 2),
            "total_value": round(total_value, 2),
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl / self.initial_cash * 100, 2),
            "initial_capital": self.initial_capital,
            "holdings": holdings_list,
        }

    def reset(self):
        """Reset portfolio to initial state."""
        self.cash = self.initial_cash
        self.holdings = {}
        self._save()
