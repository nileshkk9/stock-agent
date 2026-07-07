#!/usr/bin/env python3
"""LLM-powered backtest: 5 key dates over 5 years, with retries and shorter prompts."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd, numpy as np, yfinance as yf
from rich.console import Console
from rich.table import Table
from rich.progress import Progress

from src.config import config
from src.data.nse_fetcher import NSEFetcher
from src.backtest.engine import BacktestEngine
from src.agents.base import LLMAgent

console = Console()

TOP_TICKERS = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
    "BHARTIARTL", "ITC", "KOTAKBANK", "LT", "SBIN",
]

# 5 key dates
DATES = ["2021-12-31", "2022-12-31", "2023-12-31", "2024-12-31", "2025-06-30"]


class BacktestAnalyst(LLMAgent):
    name = "backtest"
    def analyze(self, t, d): raise NotImplementedError

    def analyze_batch(self, tickers, date, price_data, holdings=None):
        ctx = []
        for ticker in tickers:
            df = price_data.get(ticker)
            if df is None or df.empty: continue
            mask = df.index <= date
            hist = df[mask]
            if len(hist) < 252: continue
            recent = hist.tail(252)
            c = recent["Close"].values
            cp = float(c[-1])
            c3m = (c[-1]/c[-66]-1)*100 if len(c)>=66 else 0
            c6m = (c[-1]/c[-126]-1)*100 if len(c)>=126 else 0
            c1y = (c[-1]/c[0]-1)*100
            s50 = float(np.mean(c[-50:])) if len(c)>=50 else cp
            s200 = float(np.mean(c[-200:])) if len(c)>=200 else cp
            rsi = 50
            if len(c)>=15:
                d_ = np.diff(c[-15:])
                g = np.sum(d_[d_>0]) if np.any(d_>0) else 0
                l_ = abs(np.sum(d_[d_<0])) if np.any(d_<0) else 0.0001
                rsi = round(100-(100/(1+g/l_)),1)
            a50 = "Y" if cp>s50 else "N"
            a200 = "Y" if cp>s200 else "N"
            h = " [HELD]" if ticker in (holdings or []) else ""
            ctx.append(f"{ticker}: ₹{cp:,.0f} 3M:{c3m:+.1f}% 6M:{c6m:+.1f}% RSI:{rsi} >200MA:{a200}{h}")

        hn = f"\nHolding: {', '.join(holdings)}. SELL if below 200MA." if holdings else ""

        prompt = f"Date:{date}. ₹10L portfolio.{hn}\n{chr(10).join(ctx)}\n\nPick 2-4 BUY. SELL if broken. JSON only:\n{{\"TCS\":{{\"action\":\"BUY\",\"confidence\":80}}}}"
        resp = self.call_sync(prompt)
        raw = self._parse_json_response(resp)

        result = {}
        for t, v in raw.items():
            if isinstance(v, str): result[t] = {"action": v.upper(), "confidence": 50}
            elif isinstance(v, dict): result[t] = {"action": v.get("action","HOLD").upper(), "confidence": v.get("confidence",50)}
        return result


def fetch_nifty_return():
    try:
        nifty = yf.Ticker("^NSEI")
        df = nifty.history(period="5y")
        if not df.empty:
            return ((df["Close"].iloc[-1]-df["Close"].iloc[0])/df["Close"].iloc[0])*100
    except: pass
    return 0.0


def main():
    console.print("[bold]🤖 LLM Backtest — 5 Key Dates[/bold]\n")
    bench = fetch_nifty_return()
    console.print(f"Nifty 50: [cyan]{bench:+.1f}%[/cyan]\n")

    fetcher = NSEFetcher()
    price_data = {}
    with Progress() as p:
        t = p.add_task("Fetching...", total=len(TOP_TICKERS))
        for ticker in TOP_TICKERS:
            df = fetcher.get_historical(ticker, period="5y")
            if not df.empty and len(df)>=200: price_data[ticker] = df
            p.advance(t)
    console.print(f"Data: [green]{len(price_data)}/{len(TOP_TICKERS)}[/green]\n")

    console.print("[bold]LLM Analysis:[/bold]")
    analyst = BacktestAnalyst()
    all_signals = {}
    holdings = []

    for date_str in DATES:
        try:
            decisions = analyst.analyze_batch(list(price_data.keys()), date_str, price_data, holdings)
            buys = [t for t,d in decisions.items() if d.get("action")=="BUY"]
            sells = [t for t,d in decisions.items() if d.get("action")=="SELL"]
            console.print(f"  {date_str}: [green]{len(buys)}🟢[/green] [red]{len(sells)}🔴[/red]  BUY:{','.join(buys) if buys else '-'}  SELL:{','.join(sells) if sells else '-'}")

            for ticker, decision in decisions.items():
                action = decision.get("action","HOLD")
                if action in ("BUY","SELL"):
                    all_signals.setdefault(date_str,{})[ticker] = {"action":action,"confidence":decision.get("confidence",50)}
                if action=="BUY" and ticker not in holdings: holdings.append(ticker)
                elif action=="SELL" and ticker in holdings: holdings.remove(ticker)
        except Exception as e:
            console.print(f"  [red]{date_str}: {e}[/red]")

    console.print(f"\nSignal dates: [green]{len(all_signals)}[/green]")

    # Run backtests
    engine = BacktestEngine(initial_cash=1_000_000)
    r_llm = engine.run(price_data, all_signals, max_position_pct=15.0, stop_loss_pct=12.0)

    # MA Crossover baseline
    signals_ma = {}
    for ticker, df in price_data.items():
        df = df.copy()
        df["s50"] = df["Close"].rolling(50).mean()
        df["s200"] = df["Close"].rolling(200).mean()
        for idx in range(200, len(df)):
            ds = str(df.index[idx])[:10]
            if df["s50"].iloc[idx] > df["s200"].iloc[idx] and df["s50"].iloc[idx-1] <= df["s200"].iloc[idx-1]:
                signals_ma.setdefault(ds,{})[ticker] = {"action":"BUY","confidence":70}
            elif df["s50"].iloc[idx] < df["s200"].iloc[idx] and df["s50"].iloc[idx-1] >= df["s200"].iloc[idx-1]:
                signals_ma.setdefault(ds,{})[ticker] = {"action":"SELL","confidence":70}

    r_ma = engine.run(price_data, signals_ma, max_position_pct=10.0, stop_loss_pct=5.0)

    # Display
    console.print("\n")
    table = Table(title="📊 5-Year Backtest Results")
    table.add_column("Metric", style="cyan")
    table.add_column("LLM (5 dates)", justify="right", style="bold")
    table.add_column("MA Crossover", justify="right")
    table.add_column("Nifty 50", justify="right")

    a_llm = r_llm["total_return_pct"] - bench
    a_ma = r_ma["total_return_pct"] - bench

    for name, llm, ma in [
        ("Total Return", f"{r_llm['total_return_pct']:+.1f}%", f"{r_ma['total_return_pct']:+.1f}%"),
        ("Win Rate", f"{r_llm['win_rate_pct']:.0f}%", f"{r_ma['win_rate_pct']:.0f}%"),
        ("Max Drawdown", f"-{r_llm['max_drawdown_pct']:.1f}%", f"-{r_ma['max_drawdown_pct']:.1f}%"),
        ("Trades", str(r_llm["total_trades"]), str(r_ma["total_trades"])),
        ("Alpha", f"[{'green' if a_llm>0 else 'red'}]{a_llm:+.1f}%[/]", f"[{'green' if a_ma>0 else 'red'}]{a_ma:+.1f}%[/]"),
        ("Final Value", f"₹{r_llm['final_value']:,.0f}", f"₹{r_ma['final_value']:,.0f}"),
    ]:
        table.add_row(name, llm, ma, f"{bench:+.1f}%" if name == "Total Return" else "—")

    console.print(table)

    if a_llm > 0:
        console.print(f"\n[green]🎉 LLM beats Nifty by {a_llm:+.1f}%![/green]")
    else:
        console.print(f"\n[yellow]LLM lags Nifty by {abs(a_llm):.1f}%. More dates needed for better signals.[/yellow]")


if __name__ == "__main__":
    main()
