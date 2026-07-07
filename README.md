# 📈 Stock Agent

**Multi-agent LLM-powered stock analysis & paper trading system for Indian markets (NSE).**

> Goal: Beat Nifty 50. If we can't, just buy the index fund.

[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

---

## 🧠 Architecture

```
                      ┌─────────────────────┐
                      │   DATA PIPELINE     │
                      │ yfinance + nsepython│
                      │     + SQLite cache  │
                      └──────────┬──────────┘
                                 │
              ┌──────────────────┼──────────────────┐
              ▼                  ▼                  ▼
    ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
    │   FUNDAMENTAL   │ │    TECHNICAL    │ │    SENTIMENT    │
    │     ANALYST     │ │     ANALYST     │ │     ANALYST     │
    │ PE, ROE, Debt,  │ │ RSI, MACD, MA,  │ │ News, Social,   │
    │ Growth, Moat    │ │ Volume, BBands  │ │ FII/DII Flow    │
    └────────┬────────┘ └────────┬────────┘ └────────┬────────┘
             │                   │                   │
             └───────────────────┼───────────────────┘
                                 │                   
                    ┌────────────┴────────────┐      
                    │    MACRO ANALYST        │      
                    │ RBI, Budget, Global,    │      
                    │ Crude, Monsoon          │      
                    └────────────┬────────────┘      
                                 │                   
                                 ▼                   
                    ┌─────────────────────────┐      
                    │   RESEARCHER DEBATE     │      
                    │   Bull Case vs Bear     │      
                    │   Final Recommendation  │      
                    └────────────┬────────────┘      
                                 │                   
                    ┌────────────┴────────────┐      
                    ▼                         ▼      
          ┌─────────────────┐       ┌─────────────────┐
          │  RISK MANAGER   │       │ PORTFOLIO MGR   │
          │ Position Size,  │──────▶│ BUY/SELL/HOLD   │
          │ Stop Loss, Beta │       │ + Quantity       │
          └─────────────────┘       └────────┬────────┘
                                             │
                              ┌──────────────┴──────────────┐
                              ▼                             ▼
                    ┌─────────────────┐           ┌─────────────────┐
                    │    BACKTEST     │           │  PAPER TRADING  │
                    │  (Backtrader)   │           │ (Kite Sandbox)  │
                    │  5-Year History │           │  Real NSE Data  │
                    └────────┬────────┘           └────────┬────────┘
                             │                             │
                             └──────────────┬──────────────┘
                                            ▼
                                  ┌─────────────────┐
                                  │    REPORTING    │
                                  │ Telegram + HTML │
                                  │    Dashboard    │
                                  └─────────────────┘
```

**7 specialized LLM agents** work together like a real trading firm:
1. **Fundamental Analyst** — PE, ROE, debt, growth, competitive moat
2. **Technical Analyst** — RSI, MACD, moving averages, Bollinger Bands, volume
3. **Sentiment Analyst** — News headlines, social media, FII/DII flows
4. **Macro Analyst** — RBI policy, budget, global cues, sector trends
5. **Researcher** — Synthesizes all 4 analysts, runs a bull vs bear debate
6. **Risk Manager** — Position sizing (Kelly Criterion), stop-loss, correlation
7. **Portfolio Manager** — Final BUY/SELL/HOLD + quantity decision

---

## 🚀 Quick Start

### Prerequisites
- Python 3.11+
- [Optional] Zerodha demat account for Kite paper trading
- [Optional] Telegram bot for daily reports

### Install

```bash
git clone https://github.com/nileshkk9/stock-agent.git
cd stock-agent
pip install -e ".[dev]"
```

### Configure

```bash
cp .env.example .env
# Edit .env with your API keys
```

At minimum, set:
```env
LLM_PROVIDER=openrouter        # or openai, anthropic, deepseek
LLM_API_KEY=your-key-here
LLM_MODEL=openai/gpt-4.1       # or your preferred model
```

### Usage

```bash
# Analyze a single stock
python scripts/run_analysis.py RELIANCE

# Run 5-year backtest
python scripts/run_backtest.py

# Start paper trading
python scripts/run_paper.py

# Send daily report to Telegram
python scripts/daily_report.py
```

---

## ⚙️ Configuration

All config lives in `config/` and `.env`.

| Config | File | Purpose |
|--------|------|---------|
| Stock universe | `config/universe.yaml` | Which stocks to track |
| Trading rules | `config/strategy.yaml` | Risk profiles, position sizing |
| Agent prompts | `config/prompts/*.txt` | LLM system prompts per agent |

### Risk Profiles

| Profile | Max Position | Stop Loss | Min Market Cap | Confidence |
|---------|:-----------:|:---------:|:--------------:|:----------:|
| Conservative | 5% | 3% | ₹50,000 Cr | 70% |
| Moderate | 10% | 5% | ₹10,000 Cr | 60% |
| Aggressive | 15% | 8% | ₹1,000 Cr | 50% |

```env
# .env
RISK_PROFILE=moderate     # conservative | moderate | aggressive
ANALYSIS_INTERVAL_DAYS=2  # Check every 2 days
```

---

## 📊 Paper Trading Flow

Every N days (configurable):

1. **LLM agents analyze** all stocks in universe
2. **Portfolio Manager generates** BUY/SELL signals
3. **Telegram message** sent to you with proposed trades
4. **You reply** `approve` / `approve TCS` / `reject` / custom
5. **Trades execute** in Zerodha Kite sandbox (or local simulator)
6. **Evening report** with portfolio value, P&L, and performance charts

---

## 📈 Backtest Strategy

The backtest engine uses `backtrader` (event-driven) with:
- 5-year historical data (2021-2026)
- Realistic brokerage (0.03%) and slippage
- Stop-loss execution
- Configurable position sizing
- Nifty 50 as benchmark

**Metrics tracked:**
- Total Return, CAGR, Sharpe Ratio, Sortino Ratio
- Max Drawdown, Win Rate, Profit Factor
- Alpha vs Nifty 50 benchmark

---

## 🗂️ Project Structure

```
stock-agent/
├── src/
│   ├── data/           # NSE data fetchers + cache
│   ├── agents/         # 7 LLM analyst agents
│   ├── backtest/       # Backtrader engine + metrics
│   ├── paper_trading/  # Kite sandbox + local simulator
│   └── reporting/      # Telegram bot + HTML dashboard
├── config/
│   ├── universe.yaml   # Nifty 50 + custom watchlist
│   ├── strategy.yaml   # Risk profiles, trading rules
│   └── prompts/        # LLM system prompts
├── scripts/
│   ├── run_analysis.py # Single stock deep-dive
│   ├── run_backtest.py # 5-year backtest
│   ├── run_paper.py    # Paper trading simulation
│   └── daily_report.py # Telegram daily digest
├── tests/
├── notebooks/
└── reports/            # Generated dashboards + CSVs
```

---

## 🔑 API Keys Needed

| Service | For | Free Tier |
|---------|-----|:---------:|
| LLM (OpenAI/Anthropic/OpenRouter) | Agent analysis | ❌ (pay-per-use) |
| Zerodha Kite Connect | Paper trading with real data | ✅ (sandbox free) |
| Telegram Bot | Daily reports & approvals | ✅ |

Zerodha Kite is optional — the system works with `yfinance` for data and a local simulator for paper trading.

---

## ⚠️ Disclaimer

**This is a research tool, not financial advice.** Past performance (even backtested) does not guarantee future results. LLMs hallucinate. Markets are unpredictable. Never invest money you can't afford to lose. The creator assumes no liability for trading decisions made using this software.

---

## 📝 License

MIT © [Nilesh Kumar Pandey](https://github.com/nileshkk9)
