#!/usr/bin/env python3
"""
Stock Agent — Multi-Universe Backtest

Tests Trend+Momentum strategy across 3 universes:
    A: Nifty 50 (baseline — +43.4%)
    B: Nifty Next 50 (emerging large-caps — higher growth)
    C: Nifty 500 Top 200 (broad momentum capture)
"""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import yfinance as yf
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn

from src.config import config
from src.data.nse_fetcher import NSEFetcher
from src.backtest.engine import BacktestEngine

console = Console()

# ── Nifty Next 50 Constituents (approx — representative sample) ─────
NIFTY_NEXT_50 = [
    "ADANIPOWER", "ADANIGREEN", "AMBUJACEM", "BAJAJHLDNG", "BANKBARODA",
    "BERGEPAINT", "BOSCHLTD", "CADILAHC", "CANBK", "CHOLAFIN",
    "COLPAL", "CONCOR", "CUMMINSIND", "DABUR", "DLF",
    "GODREJCP", "HAVELLS", "HDFCAMC", "HINDZINC", "ICICIGI",
    "ICICIPRULI", "INDHOTEL", "IOC", "IRCTC", "JINDALSTEL",
    "JUBLFOOD", "LICHSGFIN", "LUPIN", "MARICO", "MUTHOOTFIN",
    "NAUKRI", "NMDC", "PAGEIND", "PIDILITIND", "PIIND",
    "PNB", "POLYCAB", "SBICARD", "SHREECEM", "SIEMENS",
    "SRF", "TATAPOWER", "TORNTPHARM", "TRENT", "TVSMOTOR",
    "UPL", "VEDL", "VOLTAS", "YESBANK", "ZOMATO",
]

# ── Nifty 500 additional stocks (beyond Nifty 50 + Next 50) ─────────
# Top 100 mid-caps by market cap — where momentum alpha lives
NIFTY_MIDCAP_TOP100 = [
    "ABB", "ACC", "ALKEM", "APOLLOTYRE", "ASHOKLEY",
    "ASTRAL", "ATUL", "AUBANK", "AUROPHARMA", "BAJAJELEC",
    "BALKRISIND", "BANDHANBNK", "BATAINDIA", "BHARATFORG", "BIOCON",
    "CANFINHOME", "CASTROLIND", "CGPOWER", "COROMANDEL", "CROMPTON",
    "DEEPAKNTR", "DELTACORP", "DHANI", "DIXON", "DRLAL",
    "EDELWEISS", "EICHERMOT", "EMAMILTD", "ESCORTS", "EXIDEIND",
    "FEDERALBNK", "FORTIS", "GAIL", "GLAND", "GLENMARK",
    "GMRINFRA", "GODREJPROP", "GRANULES", "GUJGASLTD", "HAL",
    "HINDCOPPER", "HONAUT", "IDEA", "IDFC", "IDFCFIRSTB",
    "INDIAMART", "INDIGO", "INDUSINDBK", "INDUSTOWER", "IPCALAB",
    "JKCEMENT", "JSWENERGY", "KALYANKJIL", "KANSAINER", "LALPATHLAB",
    "LAURUSLABS", "LODHA", "LTTS", "MAHABANK", "MANAPPURAM",
    "MAXHEALTH", "MFSL", "MINDTREE", "MOTHERSON", "MPHASIS",
    "MRF", "NAM-INDIA", "NAVINFLUOR", "NYKAA", "OBEROIRLTY",
    "PEL", "PERSISTENT", "PETRONET", "PHOENIXLTD", "POONAWALLA",
    "POWERGRID", "PRESTIGE", "RAJESHEXPO", "RBLBANK", "RECLTD",
    "SAIL", "SAPPHIRE", "SONACOMS", "STAR", "SUNDARMFIN",
    "SUNTV", "SYNGENE", "TANLA", "TATACHEM", "TATACOMM",
    "THERMAX", "TIINDIA", "TIMKEN", "TORNTPOWER", "TRIDENT",
    "UNIONBANK", "VGUARD", "VINATIORGA", "WHIRLPOOL", "ZYDUSLIFE",
]

# ── Fetch Nifty index returns ──────────────────────────────────────


def fetch_index_return(symbol: str, label: str) -> float:
    try:
        t = yf.Ticker(symbol)
        df = t.history(period="5y")
        if not df.empty and len(df) > 100:
            return ((df["Close"].iloc[-1] - df["Close"].iloc[0]) / df["Close"].iloc[0]) * 100
    except Exception:
        pass
    return 0.0


def fetch_data(tickers: list[str], label: str) -> dict:
    """Download 5yr data for a list of tickers."""
    fetcher = NSEFetcher()
    data = {}
    failed = []

    with Progress(SpinnerColumn(), TextColumn(f"[dim]{{task.description}}[/dim]"),
                  BarColumn(), TextColumn("{task.percentage:>3.0f}%"), console=console) as prog:
        task = prog.add_task(f"{label}", total=len(tickers))
        for t in tickers:
            prog.update(task, description=f"{label}: [dim]{t}[/dim]")
            df = fetcher.get_historical(t, period="5y")
            if not df.empty and len(df) >= 200:
                data[t] = df
            else:
                failed.append(t)
            prog.advance(task)

    console.print(f"  [green]{len(data)}[/green] stocks fetched", end="")
    if failed:
        console.print(f" | [red]{len(failed)} failed[/red]")
    else:
        console.print()
    return data


def main():
    console.print(Panel.fit(
        "[bold cyan]📊 Multi-Universe Backtest[/bold cyan]\n"
        "[dim]Trend+Momentum strategy × 3 universes × 5 years[/dim]",
        border_style="cyan",
    ))

    risk = config.risk_profile_config

    # ═══ UNIVERSE A: Nifty 50 ═══
    console.print("\n[bold]Universe A: Nifty 50[/bold] (large-cap)")
    tickers_a = NSEFetcher.get_nifty50_symbols()
    data_a = fetch_data(tickers_a, "Nifty 50")

    # ═══ UNIVERSE B: Nifty Next 50 ═══
    console.print("\n[bold]Universe B: Nifty Next 50[/bold] (emerging large-cap)")
    data_b = fetch_data(NIFTY_NEXT_50, "Next 50")

    # ═══ UNIVERSE C: Combined 200 (Nifty 50 + Next 50 + Midcap 100) ═══
    console.print("\n[bold]Universe C: Nifty 500 Top 200[/bold] (all-cap, best 200)")
    tickers_c = tickers_a + NIFTY_NEXT_50 + NIFTY_MIDCAP_TOP100
    # Deduplicate while preserving order
    seen = set()
    tickers_c = [x for x in tickers_c if not (x in seen or seen.add(x))]
    data_c = fetch_data(tickers_c[:200], "Top 200")

    # ═══ INDEX RETURNS ═══
    console.print("\n[bold]Index Benchmarks (5yr):[/bold]")
    nifty50_ret = fetch_index_return("^NSEI", "Nifty 50")
    nifty_next50_ret = fetch_index_return("^NSENIFTYNEXT50", "Nifty Next 50")
    # Nifty Midcap 150
    nifty_mid_ret = 0  # fallback

    console.print(f"  Nifty 50: [blue]{nifty50_ret:+.1f}%[/blue]")
    if nifty_next50_ret:
        console.print(f"  Nifty Next 50: [blue]{nifty_next50_ret:+.1f}%[/blue]")

    # ═══ BACKTEST ALL ═══
    engine = BacktestEngine(initial_cash=config.paper_trading.initial_capital)
    results = {}

    for name, data, idx_ret in [
        ("Nifty 50", data_a, nifty50_ret),
        ("Next 50", data_b, nifty_next50_ret or nifty50_ret),
        ("Top 200", data_c, nifty50_ret),
    ]:
        console.print(f"\n[bold cyan]Backtesting: {name}[/bold cyan] ({len(data)} stocks)")
        r = engine.run(data, strategy="trend_momentum",
                      max_position_pct=risk.max_position_pct,
                      stop_loss_pct=risk.stop_loss_pct)
        results[name] = r

        beat = "🟢 BEATS" if r["total_return_pct"] > idx_ret else "🔴 TRAILS"
        console.print(
            f"  Return: {r['total_return_pct']:+.1f}% | "
            f"CAGR: {r['cagr_pct']:+.1f}% | "
            f"Sharpe: {r['sharpe_ratio']:.2f} | "
            f"DD: {r['max_drawdown_pct']:.1f}% | "
            f"{beat} index by {r['total_return_pct'] - idx_ret:+.1f}%"
        )

    # ═══ COMPARISON TABLE ═══
    console.print("\n")
    table = Table(title="🏆 Multi-Universe Comparison — Trend+Momentum Strategy",
                  caption=f"Risk: {config.analysis.risk_profile} | 5 years | {datetime.now().strftime('%d %b %Y')}")

    table.add_column("Metric", style="cyan", width=14)
    for name in results:
        table.add_column(name, justify="right", width=12)
    table.add_column("Nifty 50\nIndex", justify="right", style="blue", width=12)

    metrics = [
        ("Return", "total_return_pct", "%"),
        ("CAGR", "cagr_pct", "%"),
        ("Sharpe", "sharpe_ratio", ""),
        ("Max DD", "max_drawdown_pct", "%"),
        ("Win Rate", "win_rate_pct", "%"),
        ("Trades", "total_trades", ""),
        ("Profit Factor", "profit_factor", ""),
        ("Final Value", "final_value", "₹"),
    ]

    for m_name, key, fmt in metrics:
        row = [m_name]
        for name in results:
            v = results[name][key]
            if fmt == "₹":
                row.append(f"₹{v:,.0f}")
            elif fmt == "%":
                row.append(f"{v:+.1f}%")
            else:
                row.append(f"{v:.2f}" if isinstance(v, float) else str(v))
        if fmt == "%" and key == "total_return_pct":
            row.append(f"{nifty50_ret:+.1f}%")
        else:
            row.append("—")
        table.add_row(*row)

    console.print(table)

    # ═══ WINNER ═══
    ranked = sorted(results.items(), key=lambda x: x[1]["cagr_pct"], reverse=True)
    winner = ranked[0]
    w = winner[1]

    console.print(f"\n[bold green]🏆 Best Universe: {winner[0]}[/bold green]")
    console.print(f"   {w['total_return_pct']:+.1f}% return | {w['cagr_pct']:+.1f}% CAGR | Sharpe {w['sharpe_ratio']:.2f}")

    if w["total_return_pct"] > nifty50_ret:
        console.print(f"   ✅ Beats Nifty 50 by [green]+{w['total_return_pct'] - nifty50_ret:.1f}%[/green]")
    else:
        console.print(f"   ❌ Trails Nifty 50 by [red]{nifty50_ret - w['total_return_pct']:.1f}%[/red]")

    # Check if any universe beat the index
    beaters = [(n, r) for n, r in results.items() if r["total_return_pct"] > nifty50_ret]
    if beaters:
        console.print(f"\n[green]✅ {len(beaters)}/{len(results)} universes beat Nifty 50:[/green]")
        for n, r in beaters:
            console.print(f"   {n}: +{r['total_return_pct']:.1f}% (alpha: +{r['total_return_pct'] - nifty50_ret:.1f}%)")


if __name__ == "__main__":
    main()
