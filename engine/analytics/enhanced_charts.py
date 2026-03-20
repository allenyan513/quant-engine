"""
Enhanced charts — 月度收益热力图 + 滚动 Sharpe/Beta + 按标的 PnL 归因。

作为 generate_report() 的补充图表输出。
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
from matplotlib.ticker import FuncFormatter

from engine.analytics.metrics import TradeLog
from engine.portfolio.portfolio import Portfolio


def plot_monthly_returns_heatmap(
    portfolio: Portfolio,
    path: Path,
) -> None:
    """
    月度收益热力图。

    行 = 年份, 列 = 月份 (1~12)
    颜色: 绿色 = 正收益, 红色 = 负收益
    """
    if len(portfolio.equity_curve) < 2:
        return

    # 计算月度收益
    monthly: dict[tuple[int, int], float] = {}  # (year, month) → return
    prev_equity = portfolio.equity_curve[0][1]
    prev_month = (portfolio.equity_curve[0][0].year, portfolio.equity_curve[0][0].month)

    for ts, eq in portfolio.equity_curve[1:]:
        cur_month = (ts.year, ts.month)
        if cur_month != prev_month:
            # 月份切换: 计算上月收益
            monthly[prev_month] = (eq / prev_equity) - 1 if prev_equity > 0 else 0
            prev_equity = eq
            prev_month = cur_month

    # 最后一个月
    last_ts, last_eq = portfolio.equity_curve[-1]
    last_month = (last_ts.year, last_ts.month)
    if last_month not in monthly and prev_equity > 0:
        monthly[last_month] = (last_eq / prev_equity) - 1

    if not monthly:
        return

    years = sorted(set(y for y, m in monthly))
    months = list(range(1, 13))

    # Build matrix
    data = np.full((len(years), 12), np.nan)
    for (y, m), ret in monthly.items():
        row = years.index(y)
        data[row, m - 1] = ret * 100  # percentage

    # Annual returns (rightmost column)
    annual_returns: list[float] = []
    for y in years:
        year_rets = [monthly.get((y, m), 0) for m in months if (y, m) in monthly]
        if year_rets:
            cum = 1.0
            for r in year_rets:
                cum *= (1 + r)
            annual_returns.append((cum - 1) * 100)
        else:
            annual_returns.append(np.nan)

    # Plot
    fig, ax = plt.subplots(figsize=(14, max(3, len(years) * 0.8 + 1.5)))

    # Color map: red for negative, green for positive
    vmax = max(abs(np.nanmin(data)), abs(np.nanmax(data)), 1)
    cmap = plt.cm.RdYlGn
    norm = mcolors.TwoSlopeNorm(vmin=-vmax, vcenter=0, vmax=vmax)

    im = ax.imshow(data, cmap=cmap, norm=norm, aspect="auto")

    # Annotate cells
    for i in range(len(years)):
        for j in range(12):
            val = data[i, j]
            if not np.isnan(val):
                color = "white" if abs(val) > vmax * 0.6 else "black"
                ax.text(j, i, f"{val:.1f}%", ha="center", va="center",
                        fontsize=9, color=color, fontweight="medium")

    # Annual return column annotation (right side)
    for i, ar in enumerate(annual_returns):
        if not np.isnan(ar):
            color = "#2e7d32" if ar >= 0 else "#c62828"
            ax.text(12.3, i, f"{ar:.1f}%", ha="left", va="center",
                    fontsize=10, color=color, fontweight="bold")

    ax.text(12.3, -0.7, "Year", ha="left", va="center",
            fontsize=9, color="#666666", fontweight="bold")

    month_labels = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    ax.set_xticks(range(12))
    ax.set_xticklabels(month_labels, fontsize=10)
    ax.set_yticks(range(len(years)))
    ax.set_yticklabels([str(y) for y in years], fontsize=10)
    ax.set_title("Monthly Returns (%)", fontsize=14, fontweight="bold", pad=15)

    fig.colorbar(im, ax=ax, shrink=0.6, label="Return (%)")
    plt.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_rolling_sharpe_beta(
    portfolio: Portfolio,
    benchmark_curve: list[tuple[datetime, float]] | None,
    path: Path,
    window: int = 63,  # ~3 months
) -> None:
    """
    滚动 Sharpe Ratio 和 Beta 曲线。

    Args:
        window: 滚动窗口大小（交易日数, 默认 63 ≈ 3个月）
    """
    if len(portfolio.equity_curve) < window + 1:
        return

    equities = np.array([e for _, e in portfolio.equity_curve])
    timestamps = [t for t, _ in portfolio.equity_curve]
    returns = np.diff(equities) / equities[:-1]

    has_bench = benchmark_curve is not None and len(benchmark_curve) >= 2

    # Rolling Sharpe
    rolling_sharpe = np.full(len(returns), np.nan)
    for i in range(window, len(returns)):
        w = returns[i - window:i]
        if w.std() > 0:
            rolling_sharpe[i] = w.mean() / w.std() * np.sqrt(252)

    # Rolling Beta (if benchmark available)
    rolling_beta = None
    if has_bench:
        bm_values = np.array([v for _, v in benchmark_curve])
        bm_returns = np.diff(bm_values) / bm_values[:-1]
        min_len = min(len(returns), len(bm_returns))
        aligned_ret = returns[:min_len]
        aligned_bm = bm_returns[:min_len]

        rolling_beta = np.full(min_len, np.nan)
        for i in range(window, min_len):
            r_w = aligned_ret[i - window:i]
            b_w = aligned_bm[i - window:i]
            cov = np.cov(r_w, b_w)
            if cov.shape == (2, 2) and cov[1, 1] > 0:
                rolling_beta[i] = cov[0, 1] / cov[1, 1]

    # Plot
    n_plots = 2 if rolling_beta is not None else 1
    fig, axes = plt.subplots(n_plots, 1, figsize=(14, 4 * n_plots), sharex=True)
    if n_plots == 1:
        axes = [axes]

    ts_plot = timestamps[1:]  # returns have len(equity) - 1

    # Sharpe
    ax = axes[0]
    ax.plot(ts_plot, rolling_sharpe, color="#2196F3", linewidth=1.2)
    ax.axhline(0, color="gray", linestyle="--", linewidth=0.8, alpha=0.5)
    ax.axhline(1, color="#4CAF50", linestyle=":", linewidth=0.8, alpha=0.5)
    ax.axhline(-1, color="#F44336", linestyle=":", linewidth=0.8, alpha=0.5)
    ax.fill_between(ts_plot, rolling_sharpe, 0, where=rolling_sharpe > 0,
                    color="#4CAF50", alpha=0.1)
    ax.fill_between(ts_plot, rolling_sharpe, 0, where=rolling_sharpe < 0,
                    color="#F44336", alpha=0.1)
    ax.set_ylabel(f"Rolling Sharpe ({window}d)")
    ax.set_title(f"Rolling Sharpe Ratio ({window}-day window)", fontsize=13, fontweight="bold")
    ax.grid(True, alpha=0.3)

    # Beta
    if rolling_beta is not None:
        ax = axes[1]
        ts_beta = ts_plot[:len(rolling_beta)]
        ax.plot(ts_beta, rolling_beta, color="#FF9800", linewidth=1.2)
        ax.axhline(1.0, color="gray", linestyle="--", linewidth=0.8, alpha=0.5)
        ax.axhline(0, color="gray", linestyle=":", linewidth=0.8, alpha=0.3)
        ax.set_ylabel(f"Rolling Beta ({window}d)")
        ax.set_title(f"Rolling Beta vs SPY ({window}-day window)", fontsize=13, fontweight="bold")
        ax.grid(True, alpha=0.3)

    plt.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_pnl_attribution(
    trade_log: TradeLog,
    path: Path,
) -> None:
    """
    按标的 PnL 归因图。

    水平条形图: 每个标的的总净 PnL (绿色正, 红色负)。
    """
    if not trade_log.trades:
        return

    # Aggregate PnL by symbol
    pnl_by_symbol: dict[str, float] = defaultdict(float)
    trades_by_symbol: dict[str, int] = defaultdict(int)
    for t in trade_log.trades:
        pnl_by_symbol[t.symbol] += t.net_pnl
        trades_by_symbol[t.symbol] += 1

    if not pnl_by_symbol:
        return

    # Sort by PnL
    sorted_items = sorted(pnl_by_symbol.items(), key=lambda x: x[1])
    symbols = [s for s, _ in sorted_items]
    pnls = [p for _, p in sorted_items]
    n_trades = [trades_by_symbol[s] for s in symbols]

    # Plot
    fig, ax = plt.subplots(figsize=(12, max(3, len(symbols) * 0.5 + 1)))

    colors = ["#4CAF50" if p >= 0 else "#F44336" for p in pnls]
    bars = ax.barh(range(len(symbols)), pnls, color=colors, alpha=0.8, edgecolor="white")

    # Labels
    ax.set_yticks(range(len(symbols)))
    ax.set_yticklabels(symbols, fontsize=10)

    # Annotate with PnL value and trade count
    for i, (p, n) in enumerate(zip(pnls, n_trades)):
        x_offset = max(abs(p) * 0.02, 50)
        if p >= 0:
            ax.text(p + x_offset, i, f"${p:+,.0f}  ({n} trades)",
                    va="center", fontsize=9, color="#2e7d32")
        else:
            ax.text(p - x_offset, i, f"${p:+,.0f}  ({n} trades)",
                    va="center", ha="right", fontsize=9, color="#c62828")

    ax.axvline(0, color="gray", linewidth=0.8)
    ax.set_xlabel("Net PnL ($)")
    ax.set_title("PnL Attribution by Symbol", fontsize=14, fontweight="bold")
    ax.xaxis.set_major_formatter(FuncFormatter(lambda x, _: f"${x:,.0f}"))
    ax.grid(True, axis="x", alpha=0.3)

    plt.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
