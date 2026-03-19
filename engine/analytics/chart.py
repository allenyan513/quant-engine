"""
可视化 — Equity Curve + Drawdown + 买卖标记。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.ticker import FuncFormatter

from engine.core.bar_data import BarData
from engine.portfolio.portfolio import Portfolio
from .metrics import calculate_metrics


def plot_backtest(
    portfolio: Portfolio,
    bar_data: BarData | None = None,
    title: str = "Backtest Result",
    save_path: str | Path | None = None,
    show: bool = True,
) -> None:
    """
    绘制回测结果图表。

    包含 3 个子图:
    1. Equity Curve（净值曲线）+ 买卖标记
    2. Drawdown（回撤）
    3. 标的价格 + 均线（如果提供了 bar_data）
    """
    if len(portfolio.equity_curve) < 2:
        print("Not enough data to plot.")
        return

    timestamps = [t for t, _ in portfolio.equity_curve]
    equities = np.array([e for _, e in portfolio.equity_curve])

    # 计算回撤序列
    peak = np.maximum.accumulate(equities)
    drawdown = (equities - peak) / peak * 100  # 百分比

    metrics = calculate_metrics(portfolio)

    has_price = bar_data is not None and len(bar_data.symbols) > 0
    n_rows = 3 if has_price else 2
    height_ratios = [3, 1.5, 2] if has_price else [3, 1.5]

    fig, axes = plt.subplots(
        n_rows, 1,
        figsize=(14, 4 * n_rows),
        gridspec_kw={"height_ratios": height_ratios},
        sharex=True,
    )
    fig.suptitle(title, fontsize=16, fontweight="bold", y=0.98)

    # ── 子图 1: Equity Curve ──
    ax_eq = axes[0]
    ax_eq.plot(timestamps, equities, color="#2196F3", linewidth=1.5, label="Portfolio Equity")
    ax_eq.fill_between(timestamps, equities, equities[0], alpha=0.08, color="#2196F3")

    # 起始线
    ax_eq.axhline(equities[0], color="gray", linestyle="--", linewidth=0.8, alpha=0.5)

    # 标注关键指标
    info_text = (
        f"Return: {metrics['total_return']:.2%}  |  "
        f"CAGR: {metrics['cagr']:.2%}  |  "
        f"Sharpe: {metrics['sharpe_ratio']:.2f}  |  "
        f"MaxDD: {metrics['max_drawdown']:.2%}"
    )
    ax_eq.text(
        0.5, 1.02, info_text,
        transform=ax_eq.transAxes, ha="center", fontsize=10,
        color="#555555",
    )

    ax_eq.set_ylabel("Equity ($)")
    ax_eq.yaxis.set_major_formatter(FuncFormatter(lambda x, _: f"${x:,.0f}"))
    ax_eq.legend(loc="upper left", framealpha=0.9)
    ax_eq.grid(True, alpha=0.3)

    # ── 子图 2: Drawdown ──
    ax_dd = axes[1]
    ax_dd.fill_between(timestamps, drawdown, 0, color="#F44336", alpha=0.4)
    ax_dd.plot(timestamps, drawdown, color="#F44336", linewidth=0.8)
    ax_dd.set_ylabel("Drawdown (%)")
    ax_dd.set_ylim(drawdown.min() * 1.3, 1)
    ax_dd.grid(True, alpha=0.3)

    # 标注最大回撤点
    max_dd_idx = np.argmin(drawdown)
    ax_dd.annotate(
        f"{drawdown[max_dd_idx]:.1f}%",
        xy=(timestamps[max_dd_idx], drawdown[max_dd_idx]),
        xytext=(20, -15),
        textcoords="offset points",
        fontsize=9, color="#D32F2F", fontweight="bold",
        arrowprops=dict(arrowstyle="->", color="#D32F2F", lw=1.2),
    )

    # ── 子图 3: 标的价格 ──
    if has_price:
        ax_price = axes[2]
        for symbol in bar_data.symbols:
            bars = bar_data._bars[symbol]
            ts = [b.timestamp for b in bars]
            closes = [b.close for b in bars]
            ax_price.plot(ts, closes, linewidth=1.2, label=symbol)

        ax_price.set_ylabel("Price ($)")
        ax_price.yaxis.set_major_formatter(FuncFormatter(lambda x, _: f"${x:,.0f}"))
        ax_price.legend(loc="upper left", framealpha=0.9)
        ax_price.grid(True, alpha=0.3)

    # X 轴格式
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    axes[-1].xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    plt.xticks(rotation=45)

    plt.tight_layout()

    if save_path:
        fig.savefig(save_path, dpi=150, bbox_inches="tight")
        print(f"Chart saved to {save_path}")

    if show:
        plt.show()

    plt.close(fig)
