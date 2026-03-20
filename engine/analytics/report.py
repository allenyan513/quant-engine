"""
BacktestReport — 回测结果输出到 outputs/<timestamp>/ 目录。

输出内容:
1. report.png       — 综合图表 (equity, drawdown, exposure, turnover)
2. report.txt       — 文本报告 (指标 + 交易摘要)
3. equity_curve.csv — 净值曲线
4. trades.csv       — 交易明细
5. exposure.csv     — 多空敞口时序
6. turnover.csv     — 换手率时序
"""

from __future__ import annotations

import csv
import io
from datetime import datetime
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.ticker import FuncFormatter

from engine.analytics.enhanced_charts import (
    plot_monthly_returns_heatmap,
    plot_pnl_attribution,
    plot_rolling_sharpe_beta,
)
from engine.analytics.metrics import TradeLog, calculate_metrics, get_environment_info
from engine.portfolio.portfolio import Portfolio


def generate_report(
    engine,
    benchmark: Portfolio | None = None,
    benchmark_label: str = "SPY Buy & Hold",
    strategy_name: str = "Strategy",
    output_dir: str | Path | None = None,
) -> Path:
    """
    生成完整回测报告，保存到 outputs/<timestamp>/ 目录。

    Benchmark 自动使用 engine.benchmark_curve (SPY)。
    也可以手动传入 benchmark Portfolio 覆盖。

    Args:
        engine: BacktestEngine 实例 (回测完成后)
        benchmark: 手动传入基准 Portfolio (覆盖自动 SPY)
        benchmark_label: 基准名称
        strategy_name: 策略名称
        output_dir: 自定义输出目录 (默认 outputs/<timestamp>)

    Returns:
        输出目录 Path
    """
    portfolio = engine.portfolio
    trade_log = engine.trade_log
    bar_data = engine.bar_data

    # 确定输出目录
    if output_dir is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = Path("outputs") / ts
    else:
        output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 确定 benchmark: 手动传入 > engine 自动 SPY
    if benchmark is not None:
        bench_curve = benchmark.equity_curve
    else:
        bench_curve = getattr(engine, "benchmark_curve", None)

    metrics = calculate_metrics(portfolio, benchmark_curve=bench_curve)

    # 1. 文本报告
    _write_text_report(
        output_dir / "report.txt",
        metrics, portfolio, trade_log, engine,
        bench_curve, benchmark_label, strategy_name,
    )

    # 2. 综合图表
    _plot_full_report(
        output_dir / "report.png",
        portfolio, engine, bench_curve, benchmark_label, strategy_name, metrics,
    )

    # 3. Enhanced charts
    plot_monthly_returns_heatmap(portfolio, output_dir / "monthly_returns.png")
    plot_rolling_sharpe_beta(portfolio, bench_curve, output_dir / "rolling_sharpe_beta.png")
    plot_pnl_attribution(trade_log, output_dir / "pnl_attribution.png")

    # 4. CSV 数据导出
    _write_equity_csv(output_dir / "equity_curve.csv", portfolio)
    _write_trades_csv(output_dir / "trades.csv", trade_log)
    _write_exposure_csv(output_dir / "exposure.csv", engine)
    _write_turnover_csv(output_dir / "turnover.csv", engine)

    print(f"\nReport saved to {output_dir}/")
    print(f"  report.png              — 综合图表")
    print(f"  monthly_returns.png     — 月度收益热力图")
    print(f"  rolling_sharpe_beta.png — 滚动 Sharpe/Beta")
    print(f"  pnl_attribution.png     — 按标的 PnL 归因")
    print(f"  report.txt              — 文本报告")
    print(f"  equity_curve.csv        — 净值曲线")
    print(f"  trades.csv              — 交易明细")
    print(f"  exposure.csv            — 多空敞口")
    print(f"  turnover.csv            — 换手率")

    return output_dir


# ---------------------------------------------------------------------------
# Text report
# ---------------------------------------------------------------------------

def _write_text_report(
    path: Path,
    metrics: dict,
    portfolio: Portfolio,
    trade_log: TradeLog,
    engine,
    bench_curve: list | None,
    benchmark_label: str,
    strategy_name: str,
) -> None:
    lines: list[str] = []
    w = lines.append

    w("=" * 60)
    w(f"  BACKTEST REPORT: {strategy_name}")
    w(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    w(f"  Period: {engine.start} ~ {engine.end}")
    w("=" * 60)

    w("")
    w("─── Performance ───────────────────────────────────────")
    w(f"  Initial Equity:     ${metrics['initial_equity']:>14,.2f}")
    w(f"  Final Equity:       ${metrics['final_equity']:>14,.2f}")
    w(f"  Total Return:       {metrics['total_return']:>14.2%}")
    w(f"  CAGR:               {metrics['cagr']:>14.2%}")
    w(f"  Volatility:         {metrics['volatility']:>14.2%}")
    w(f"  Max Drawdown:       {metrics['max_drawdown']:>14.2%}")

    w("")
    w("─── Risk-Adjusted ─────────────────────────────────────")
    w(f"  Sharpe Ratio:       {metrics['sharpe_ratio']:>14.2f}")
    w(f"  Sortino Ratio:      {metrics['sortino_ratio']:>14.2f}")
    w(f"  Calmar Ratio:       {metrics['calmar_ratio']:>14.2f}")
    w(f"  PSR:                {metrics['psr']:>14.2%}")
    w(f"  Expectancy:         {metrics['expectancy']:>14.6f}")
    w(f"  Win Rate (daily):   {metrics['win_rate']:>14.2%}")

    if "benchmark_return" in metrics:
        w("")
        w(f"─── vs {benchmark_label} ──────────────────────────────")
        w(f"  Benchmark Return:   {metrics['benchmark_return']:>14.2%}")
        w(f"  Alpha:              {metrics['alpha']:>14.2%}")
        w(f"  Beta:               {metrics['beta']:>14.4f}")
        w(f"  Information Ratio:  {metrics['information_ratio']:>14.2f}")
        w(f"  Tracking Error:     {metrics['tracking_error']:>14.4f}")
        w(f"  Treynor Ratio:      {metrics['treynor_ratio']:>14.2f}")

    # Exposure summary
    if engine.exposure_curve:
        long_ratios = [lr for _, lr, _ in engine.exposure_curve]
        short_ratios = [sr for _, _, sr in engine.exposure_curve]
        w("")
        w("─── Exposure ──────────────────────────────────────────")
        w(f"  Avg Long Ratio:     {np.mean(long_ratios):>14.2%}")
        w(f"  Avg Short Ratio:    {np.mean(short_ratios):>14.2%}")
        w(f"  Avg Net Exposure:   {np.mean(long_ratios) + np.mean(short_ratios):>14.2%}")

    # Turnover summary
    if engine.turnover_curve:
        turnovers = [t for _, t in engine.turnover_curve]
        w("")
        w("─── Turnover ──────────────────────────────────────────")
        w(f"  Avg Daily Turnover: {np.mean(turnovers):>14.4%}")
        w(f"  Total Turnover:     {np.sum(turnovers):>14.2%}")

    # Trade log
    ts = trade_log.summary()
    if ts.get("total_trades", 0) > 0:
        w("")
        w("─── Trades ────────────────────────────────────────────")
        w(f"  Total Trades:       {ts['total_trades']:>14d}")
        w(f"  Win / Loss:         {ts['winning_trades']:>6d} / {ts['losing_trades']:<6d}")
        w(f"  Trade Win Rate:     {ts['win_rate']:>14.2%}")
        w(f"  Avg Win:            ${ts['avg_win']:>14,.2f}")
        w(f"  Avg Loss:           ${ts['avg_loss']:>14,.2f}")
        w(f"  Profit Factor:      {ts['profit_factor']:>14.2f}")
        w(f"  Largest Win:        ${ts['largest_win']:>14,.2f}")
        w(f"  Largest Loss:       ${ts['largest_loss']:>14,.2f}")
        w(f"  Avg Holding Days:   {ts['avg_holding_days']:>14.1f}")
        w(f"  Total PnL:          ${ts['total_pnl']:>14,.2f}")

    # Current holdings
    holdings = [(sym, pos) for sym, pos in portfolio.positions.items() if pos.quantity != 0]
    if holdings:
        w("")
        w("─── Current Holdings ──────────────────────────────────")
        for sym, pos in sorted(holdings, key=lambda x: abs(x[1].quantity), reverse=True):
            bar = engine.bar_data.current(sym)
            mv = pos.quantity * bar.close if bar else 0
            pct = mv / portfolio.equity * 100 if portfolio.equity > 0 else 0
            w(f"  {sym:<10} {pos.quantity:>8} shares  ${mv:>12,.0f}  ({pct:>5.1f}%)")

    # Environment info
    env = get_environment_info(engine)
    w("")
    w("─── Environment ───────────────────────────────────────")
    w(f"  Python:             {env['python_version']}")
    w(f"  Platform:           {env['platform']}")
    w(f"  NumPy:              {env['numpy_version']}")
    w(f"  SciPy:              {env['scipy_version']}")
    w(f"  yfinance:           {env['yfinance_version']}")
    w(f"  matplotlib:         {env['matplotlib_version']}")
    if "strategy" in env:
        w(f"  Strategy:           {env['strategy']}")
        w(f"  Data Feed:          {env['data_feed']}")
        w(f"  Fee Model:          {env['fee_model']}")
        w(f"  Slippage Rate:      {env['slippage_rate']:.4%}")

    w("")
    w("=" * 60)

    path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------

def _plot_full_report(
    path: Path,
    portfolio: Portfolio,
    engine,
    bench_curve: list | None,
    benchmark_label: str,
    strategy_name: str,
    metrics: dict,
) -> None:
    from collections import defaultdict

    timestamps = [t for t, _ in portfolio.equity_curve]
    equities = np.array([e for _, e in portfolio.equity_curve])
    norm_equity = equities / equities[0] * 100

    peak = np.maximum.accumulate(equities)
    drawdown = (equities - peak) / peak * 100

    has_bench = bench_curve is not None and len(bench_curve) >= 2
    has_exposure = len(engine.exposure_curve) > 0
    has_turnover = len(engine.turnover_curve) > 0

    # Determine subplot layout: header + charts
    rows = ["equity", "drawdown"]
    ratios = [3, 1.5]
    if has_exposure:
        rows.append("exposure")
        ratios.append(1.5)
    if has_turnover:
        rows.append("turnover")
        ratios.append(1.2)

    n_chart_rows = len(rows)
    # Add header row for KPI banner (title + KPIs)
    all_ratios = [1.0] + ratios
    n_rows = 1 + n_chart_rows

    fig, axes = plt.subplots(
        n_rows, 1,
        figsize=(14, 3.2 * n_chart_rows + 2.0),
        gridspec_kw={"height_ratios": all_ratios},
    )

    # ── Header: title + KPI banner ──
    ax_header = axes[0]
    ax_header.set_xlim(0, 1)
    ax_header.set_ylim(0, 1)
    ax_header.axis("off")

    # Clean white background
    ax_header.add_patch(plt.Rectangle((0, 0), 1, 1,
                        transform=ax_header.transAxes, facecolor="white",
                        edgecolor="none", zorder=0))

    # ── Title row: strategy name (large) + period (muted) ──
    ax_header.text(0.02, 0.88, strategy_name,
                   transform=ax_header.transAxes, ha="left", va="top",
                   fontsize=16, fontweight="bold", color="#1a1a1a",
                   fontfamily="sans-serif")
    ax_header.text(0.98, 0.88, f"{engine.start}  ~  {engine.end}",
                   transform=ax_header.transAxes, ha="right", va="top",
                   fontsize=11, color="#999999", fontfamily="sans-serif")

    # Thin separator line between title and KPIs
    ax_header.plot([0.02, 0.98], [0.68, 0.68], transform=ax_header.transAxes,
                   color="#e8e8e8", linewidth=1.0, zorder=1)

    # ── KPI values ──
    final_equity = metrics["final_equity"]
    initial_equity = metrics["initial_equity"]
    net_profit = final_equity - initial_equity
    total_return = metrics["total_return"]
    sharpe = metrics["sharpe_ratio"]
    max_dd = metrics["max_drawdown"]
    psr_val = metrics["psr"]
    vol = metrics["volatility"]

    holdings_val = 0.0
    for sym, pos in portfolio.positions.items():
        if pos.quantity != 0:
            bar = engine.bar_data.current(sym)
            if bar:
                holdings_val += pos.quantity * bar.close

    total_fees = sum(t.commission for t in engine.trade_log.trades)

    kpis = [
        ("Equity",     f"${final_equity:,.0f}",   final_equity >= initial_equity),
        ("Net Profit", f"${net_profit:+,.0f}",     net_profit >= 0),
        ("Return",     f"{total_return:+.2%}",     total_return >= 0),
        ("Sharpe",     f"{sharpe:.3f}",            sharpe >= 0),
        ("Max DD",     f"{max_dd:.2%}",            False),
        ("PSR",        f"{psr_val:.2%}",           psr_val >= 0.5),
        ("Holdings",   f"${holdings_val:,.0f}",    holdings_val >= 0),
        ("Fees",       f"-${total_fees:,.0f}",     False),
        ("Volatility", f"{vol:.2%}",               vol < 0.2),
    ]

    n_kpis = len(kpis)
    pad_l, pad_r = 0.02, 0.02
    usable = 1.0 - pad_l - pad_r
    for i, (label, value, is_good) in enumerate(kpis):
        x = pad_l + usable * (i + 0.5) / n_kpis
        color = "#2e7d32" if is_good else "#c62828"
        ax_header.text(x, 0.42, value, transform=ax_header.transAxes,
                       ha="center", va="center", fontsize=14, fontweight="bold",
                       color=color, fontfamily="monospace")
        ax_header.text(x, 0.10, label, transform=ax_header.transAxes,
                       ha="center", va="center", fontsize=9,
                       color="#aaaaaa", fontweight="medium", fontfamily="sans-serif")

    # Bottom border of header
    ax_header.plot([0, 1], [0, 0], transform=ax_header.transAxes,
                   color="#e0e0e0", linewidth=1.5, zorder=1)

    # Share x-axis for chart rows only
    chart_axes = list(axes[1:])
    for ax in chart_axes[1:]:
        ax.sharex(chart_axes[0])

    ax_idx = 0

    # ── Equity Curve ──
    ax = chart_axes[ax_idx]; ax_idx += 1
    ax.plot(timestamps, norm_equity, color="#2196F3", linewidth=1.8, label="Strategy", zorder=3)
    ax.fill_between(timestamps, norm_equity, 100, alpha=0.06, color="#2196F3")

    if has_bench:
        bench_ts = [t for t, _ in bench_curve]
        bench_eq = np.array([e for _, e in bench_curve])
        bench_norm = bench_eq / bench_eq[0] * 100
        ax.plot(bench_ts, bench_norm, color="#FF9800", linewidth=1.5,
                label=benchmark_label, linestyle="--", alpha=0.85, zorder=2)

    ax.axhline(100, color="gray", linestyle="--", linewidth=0.8, alpha=0.5)
    ax.set_ylabel("Growth of $100")
    ax.yaxis.set_major_formatter(FuncFormatter(lambda x, _: f"${x:,.0f}"))
    ax.legend(loc="upper left", framealpha=0.9, fontsize=10)
    ax.grid(True, alpha=0.3)

    # ── Drawdown ──
    ax = chart_axes[ax_idx]; ax_idx += 1
    ax.fill_between(timestamps, drawdown, 0, color="#F44336", alpha=0.35, label="Strategy")
    ax.plot(timestamps, drawdown, color="#F44336", linewidth=0.8)

    if has_bench:
        bench_peak = np.maximum.accumulate(bench_eq)
        bench_dd = (bench_eq - bench_peak) / bench_peak * 100
        ax.plot(bench_ts, bench_dd, color="#FF9800", linewidth=1.2,
                linestyle="--", alpha=0.7, label=benchmark_label)

    max_dd_idx = np.argmin(drawdown)
    ax.annotate(
        f"{drawdown[max_dd_idx]:.1f}%",
        xy=(timestamps[max_dd_idx], drawdown[max_dd_idx]),
        xytext=(20, -15), textcoords="offset points",
        fontsize=9, color="#D32F2F", fontweight="bold",
        arrowprops=dict(arrowstyle="->", color="#D32F2F", lw=1.2),
    )
    dd_min = drawdown.min()
    if has_bench:
        dd_min = min(dd_min, bench_dd.min())
    ax.set_ylim(dd_min * 1.3, 1)
    ax.set_ylabel("Drawdown (%)")
    ax.legend(loc="lower left", framealpha=0.9, fontsize=9)
    ax.grid(True, alpha=0.3)

    # ── Exposure ──
    if has_exposure:
        ax = chart_axes[ax_idx]; ax_idx += 1
        exp_ts = [t for t, _, _ in engine.exposure_curve]
        long_r = np.array([lr for _, lr, _ in engine.exposure_curve])
        short_r = np.array([sr for _, _, sr in engine.exposure_curve])

        ax.fill_between(exp_ts, long_r, 0, color="#4CAF50", alpha=0.35, label="Long")
        ax.fill_between(exp_ts, short_r, 0, color="#F44336", alpha=0.35, label="Short")
        net = long_r + short_r
        ax.plot(exp_ts, net, color="#333333", linewidth=1.0, label="Net", alpha=0.8)

        ax.axhline(0, color="gray", linestyle="-", linewidth=0.5, alpha=0.5)
        ax.set_ylabel("Exposure")
        ax.legend(loc="upper right", framealpha=0.9, fontsize=8, ncol=3)
        ax.grid(True, alpha=0.3)

    # ── Turnover (aggregated monthly) ──
    if has_turnover:
        ax = chart_axes[ax_idx]; ax_idx += 1

        # Aggregate daily turnover → monthly sum
        monthly: dict[str, float] = defaultdict(float)
        for ts, tv in engine.turnover_curve:
            key = ts.strftime("%Y-%m")
            monthly[key] += tv

        month_dates = [datetime.strptime(k + "-15", "%Y-%m-%d") for k in sorted(monthly)]
        month_vals = [monthly[k] * 100 for k in sorted(monthly)]  # as percentage

        bar_width = 20  # ~20 days per bar
        bars = ax.bar(month_dates, month_vals, width=bar_width,
                       color="#7E57C2", alpha=0.7, edgecolor="#5E35B1", linewidth=0.3)

        # Color bars by intensity
        if month_vals:
            max_v = max(month_vals) if max(month_vals) > 0 else 1
            for bar, v in zip(bars, month_vals):
                alpha = 0.3 + 0.7 * (v / max_v)
                bar.set_alpha(alpha)

        ax.set_ylabel("Turnover (%/mo)")
        ax.yaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{x:.0f}%"))
        ax.grid(True, alpha=0.3)

    # ── X axis ──
    chart_axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    date_range = (timestamps[-1] - timestamps[0]).days
    if date_range > 365 * 5:
        chart_axes[-1].xaxis.set_major_locator(mdates.MonthLocator(interval=6))
    elif date_range > 365 * 2:
        chart_axes[-1].xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    else:
        chart_axes[-1].xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    plt.xticks(rotation=45)

    plt.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# CSV exports
# ---------------------------------------------------------------------------

def _write_equity_csv(path: Path, portfolio: Portfolio) -> None:
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "equity"])
        for ts, eq in portfolio.equity_curve:
            writer.writerow([ts.strftime("%Y-%m-%d"), f"{eq:.2f}"])


def _write_trades_csv(path: Path, trade_log: TradeLog) -> None:
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "symbol", "direction", "entry_time", "entry_price",
            "exit_time", "exit_price", "quantity", "pnl",
            "commission", "net_pnl", "return_pct", "holding_days",
        ])
        for t in trade_log.trades:
            writer.writerow([
                t.symbol,
                t.direction.name,
                t.entry_time.strftime("%Y-%m-%d") if t.entry_time else "",
                f"{t.entry_price:.4f}",
                t.exit_time.strftime("%Y-%m-%d") if t.exit_time else "",
                f"{t.exit_price:.4f}" if t.exit_price else "",
                t.quantity,
                f"{t.pnl:.2f}",
                f"{t.commission:.2f}",
                f"{t.net_pnl:.2f}",
                f"{t.return_pct:.4f}",
                t.holding_days,
            ])


def _write_exposure_csv(path: Path, engine) -> None:
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "long_ratio", "short_ratio", "net_exposure"])
        for ts, lr, sr in engine.exposure_curve:
            writer.writerow([
                ts.strftime("%Y-%m-%d"),
                f"{lr:.4f}", f"{sr:.4f}", f"{lr + sr:.4f}",
            ])


def _write_turnover_csv(path: Path, engine) -> None:
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "turnover"])
        for ts, tv in engine.turnover_curve:
            writer.writerow([ts.strftime("%Y-%m-%d"), f"{tv:.6f}"])
