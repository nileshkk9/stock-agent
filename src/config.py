"""Central configuration loaded from environment and YAML files."""

import os
from pathlib import Path
from typing import Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()

PROJECT_ROOT = Path(__file__).parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"


class LLMConfig(BaseModel):
    provider: str = Field(default_factory=lambda: os.getenv("LLM_PROVIDER", "openrouter"))
    model: str = Field(default_factory=lambda: os.getenv("LLM_MODEL", "openai/gpt-4.1"))
    api_key: str = Field(default_factory=lambda: os.getenv("LLM_API_KEY", ""))
    base_url: str | None = Field(default_factory=lambda: os.getenv("LLM_BASE_URL"))
    temperature: float = 0.3
    max_tokens: int = 8192


class KiteConfig(BaseModel):
    api_key: str = Field(default_factory=lambda: os.getenv("KITE_API_KEY", ""))
    api_secret: str = Field(default_factory=lambda: os.getenv("KITE_API_SECRET", ""))
    user_id: str = Field(default_factory=lambda: os.getenv("KITE_USER_ID", ""))
    password: str = Field(default_factory=lambda: os.getenv("KITE_PASSWORD", ""))
    totp_secret: str = Field(default_factory=lambda: os.getenv("KITE_TOTP_SECRET", ""))


class DhanConfig(BaseModel):
    client_id: str = Field(default_factory=lambda: os.getenv("DHAN_CLIENT_ID", ""))
    access_token: str = Field(default_factory=lambda: os.getenv("DHAN_ACCESS_TOKEN", ""))


class TwelveDataConfig(BaseModel):
    api_key: str = Field(default_factory=lambda: os.getenv("TWELVEDATA_API_KEY", ""))


class TelegramConfig(BaseModel):
    bot_token: str = Field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))
    chat_id: str = Field(default_factory=lambda: os.getenv("TELEGRAM_CHAT_ID", ""))


RiskProfile = Literal["conservative", "moderate", "aggressive"]


class RiskConfig(BaseModel):
    max_position_pct: float = 5.0
    max_sector_pct: float = 20.0
    stop_loss_pct: float = 3.0
    max_drawdown_pct: float = 15.0
    min_market_cap_cr: float = 50000  # ₹50,000 Cr minimum


class PaperTradingConfig(BaseModel):
    initial_capital: float = Field(
        default_factory=lambda: float(os.getenv("PAPER_TRADING_CAPITAL", "1000000"))
    )
    max_position_pct: float = Field(
        default_factory=lambda: float(os.getenv("MAX_POSITION_SIZE_PCT", "10"))
    )
    max_sector_pct: float = Field(
        default_factory=lambda: float(os.getenv("MAX_SECTOR_EXPOSURE_PCT", "30"))
    )
    stop_loss_pct: float = Field(
        default_factory=lambda: float(os.getenv("STOP_LOSS_PCT", "5"))
    )
    brokerage_pct: float = 0.03  # Zerodha: 0.03% or ₹20 per trade


class AnalysisConfig(BaseModel):
    interval_days: int = Field(
        default_factory=lambda: int(os.getenv("ANALYSIS_INTERVAL_DAYS", "2"))
    )
    risk_profile: RiskProfile = Field(
        default_factory=lambda: os.getenv("RISK_PROFILE", "moderate")  # type: ignore
    )
    universe: str = Field(default_factory=lambda: os.getenv("UNIVERSE", "nifty50"))
    backtest_years: int = 5


class AppConfig(BaseModel):
    llm: LLMConfig = LLMConfig()
    kite: KiteConfig = KiteConfig()
    dhan: DhanConfig = DhanConfig()
    twelvedata: TwelveDataConfig = TwelveDataConfig()
    telegram: TelegramConfig = TelegramConfig()
    paper_trading: PaperTradingConfig = PaperTradingConfig()
    analysis: AnalysisConfig = AnalysisConfig()

    @property
    def risk_profile_config(self) -> RiskConfig:
        """Return risk parameters based on selected profile."""
        profile = self.analysis.risk_profile
        if profile == "conservative":
            return RiskConfig(
                max_position_pct=5.0,
                max_sector_pct=20.0,
                stop_loss_pct=3.0,
                max_drawdown_pct=10.0,
                min_market_cap_cr=50000,
            )
        elif profile == "moderate":
            return RiskConfig(
                max_position_pct=10.0,
                max_sector_pct=30.0,
                stop_loss_pct=5.0,
                max_drawdown_pct=20.0,
                min_market_cap_cr=10000,
            )
        else:  # aggressive
            return RiskConfig(
                max_position_pct=15.0,
                max_sector_pct=40.0,
                stop_loss_pct=8.0,
                max_drawdown_pct=30.0,
                min_market_cap_cr=1000,
            )


config = AppConfig()


def load_universe() -> dict:
    """Load stock universe from YAML config."""
    path = CONFIG_DIR / "universe.yaml"
    if path.exists():
        with open(path) as f:
            return yaml.safe_load(f)
    return {"nifty50": [], "watchlist": []}


def load_strategy() -> dict:
    """Load strategy/trading rules from YAML config."""
    path = CONFIG_DIR / "strategy.yaml"
    if path.exists():
        with open(path) as f:
            return yaml.safe_load(f)
    return {}


def load_prompt(agent_name: str) -> str:
    """Load an agent's system prompt from config/prompts/."""
    path = CONFIG_DIR / "prompts" / f"{agent_name}.txt"
    if path.exists():
        return path.read_text()
    return ""
