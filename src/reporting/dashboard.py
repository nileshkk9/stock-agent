"""Interactive HTML dashboard for portfolio and backtest performance."""

from pathlib import Path
from typing import Any

import plotly.graph_objects as go
from plotly.subplots import make_subplots

REPORTS_DIR = Path(__file__).parent.parent.parent / "reports"


def generate_dashboard(
    equity_curve: list[dict],
    portfolio_summary: dict,
    backtest_results: dict | None = None,
    output_path: Path | None = None,
) -> str:
    """Generate an interactive HTML dashboard with Plotly.

    Args:
        equity_curve: [{date, value, benchmark_value}, ...]
        portfolio_summary: from PaperPortfolio.get_summary()
        backtest_results: from BacktestEngine.run()
        output_path: where to save HTML

    Returns:
        Path to generated HTML file
    """
    output_path = output_path or REPORTS_DIR / "dashboard.html"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fig = make_subplots(
        rows=3, cols=2,
        subplot_titles=(
            "Equity Curve vs Nifty 50",
            "Portfolio Allocation",
            "Monthly Returns",
            "Drawdown",
            "Performance Metrics",
            "Trade Log",
        ),
        specs=[
            [{"type": "scatter"}, {"type": "pie"}],
            [{"type": "bar"}, {"type": "scatter"}],
            [{"type": "table"}, {"type": "table"}],
        ],
        vertical_spacing=0.12,
        horizontal_spacing=0.12,
    )

    # 1. Equity Curve
    if equity_curve:
        dates = [e["date"] for e in equity_curve]
        values = [e["value"] for e in equity_curve]
        benchmarks = [e.get("benchmark_value", e["value"]) for e in equity_curve]

        fig.add_trace(
            go.Scatter(x=dates, y=values, name="Portfolio", line=dict(color="blue")),
            row=1, col=1,
        )
        fig.add_trace(
            go.Scatter(x=dates, y=benchmarks, name="Nifty 50", line=dict(color="gray", dash="dash")),
            row=1, col=1,
        )

    # 2. Portfolio Allocation Pie
    if portfolio_summary.get("holdings"):
        labels = [h["ticker"] for h in portfolio_summary["holdings"]]
        values_pie = [h["value"] for h in portfolio_summary["holdings"]]
        labels.append("Cash")
        values_pie.append(portfolio_summary["cash"])
        fig.add_trace(
            go.Pie(labels=labels, values=values_pie, hole=0.4),
            row=1, col=2,
        )

    # 3. Monthly Returns
    # (placeholder - real implementation computes from trade history)

    # 4. Drawdown
    if equity_curve:
        # Simple drawdown calculation
        peak = 0
        drawdowns = []
        for e in equity_curve:
            peak = max(peak, e["value"])
            dd = (e["value"] - peak) / peak * 100
            drawdowns.append(dd)
        fig.add_trace(
            go.Scatter(x=dates, y=drawdowns, name="Drawdown %", fill="tozeroy", line=dict(color="red")),
            row=2, col=2,
        )

    # 5. Performance Metrics Table
    if backtest_results:
        metrics_table = go.Table(
            header=dict(values=["Metric", "Value"]),
            cells=dict(values=[
                ["Total Return", "CAGR", "Sharpe", "Max Drawdown", "Win Rate", "Alpha vs Nifty"],
                [
                    f"{backtest_results['total_return_pct']:+.1f}%",
                    f"{backtest_results['cagr_pct']:+.1f}%",
                    f"{backtest_results['sharpe_ratio']:.2f}",
                    f"-{backtest_results['max_drawdown_pct']:.1f}%",
                    f"{backtest_results['win_rate_pct']:.0f}%",
                    f"{backtest_results['alpha_pct']:+.1f}%",
                ],
            ]),
        )
        fig.add_trace(metrics_table, row=3, col=1)

    # 6. Holdings Table
    if portfolio_summary.get("holdings"):
        holdings_table = go.Table(
            header=dict(values=["Ticker", "Qty", "Avg Price", "Current", "Value", "P&L %"]),
            cells=dict(values=[
                [h["ticker"] for h in portfolio_summary["holdings"]],
                [h["quantity"] for h in portfolio_summary["holdings"]],
                [f"₹{h['avg_price']:,.2f}" for h in portfolio_summary["holdings"]],
                [f"₹{h['current_price']:,.2f}" for h in portfolio_summary["holdings"]],
                [f"₹{h['value']:,.0f}" for h in portfolio_summary["holdings"]],
                [f"{h['pnl_pct']:+.1f}%" for h in portfolio_summary["holdings"]],
            ]),
        )
        fig.add_trace(holdings_table, row=3, col=2)

    fig.update_layout(
        height=1200,
        title_text=f"Stock Agent Dashboard — Portfolio: ₹{portfolio_summary.get('total_value', 0):,.0f}",
        showlegend=True,
    )

    fig.write_html(str(output_path))
    return str(output_path)
