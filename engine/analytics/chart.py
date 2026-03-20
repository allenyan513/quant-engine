"""
可视化 — Equity Curve + Drawdown + Benchmark 对比。
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
    benchmark: Portfolio | None = None,
    benchmark_label: str = "SPY Buy & Hold",
    title: str = "Backtest Result",
    save_path: str | Path | None = None,
    show: bool = True,
) -> None:
    """
    绘制回测结果图表。

    子图:
    1. Equity Curve（归一化收益率对比）
    2. Drawdown（回撤对比）
    3. 超额收益 (如有 benchmark)
    4. 标的价格（如有 bar_data）

    Args:
        portfolio:       策略 Portfolio
        bar_data:        标的行情数据 (可选)
        benchmark:       基准 Portfolio (可选，如 SPY 买入持有)
        benchmark_label: 基准在图例中的名称
        title:           图表标题
        save_path:       保存路径
        show:            是否显示
    """
    if len(portfolio.equity_curve) < 2:
        print("Not enough data to plot.")
        return

    timestamps = [t for t, _ in portfolio.equity_curve]
    equities = np.array([e for _, e in portfolio.equity_curve])

    # 归一化为百分比收益
    norm_equity = equities / equities[0] * 100

    # 回撤序列
    peak = np.maximum.accumulate(equities)
    drawdown = (equities - peak) / peak * 100

    metrics = calculate_metrics(portfolio)

    # ── 处理 benchmark ────────────────────────────────────────
    has_bench = benchmark is not None and len(benchmark.equity_curve) >= 2
    bench_norm = None
    bench_dd = None
    bench_metrics = None
    excess_return = None

    if has_bench:
        bench_ts = [t for t, _ in benchmark.equity_curve]
        bench_eq = np.array([e for _, e in benchmark.equity_curve])
        bench_norm = bench_eq / bench_eq[0] * 100

        bench_peak = np.maximum.accumulate(bench_eq)
        bench_dd = (bench_eq - bench_peak) / bench_peak * 100

        bench_metrics = calculate_metrics(benchmark)

        # 超额收益 (对齐长度)
        min_len = min(len(norm_equity), len(bench_norm))
        excess_return = norm_equity[:min_len] - bench_norm[:min_len]

    # ── 确定子图数量 ──────────────────────────────────────────
    has_price = bar_data is not None and len(bar_data.symbols) > 0

    rows = []
    ratios = []

    rows.append("equity")
    ratios.append(3)

    rows.append("drawdown")
    ratios.append(1.5)

    if has_bench:
        rows.append("excess")
        ratios.append(1.5)

    if has_price:
        rows.append("price")
        ratios.append(2)

    n_rows = len(rows)

    fig, axes = plt.subplots(
        n_rows, 1,
        figsize=(14, 3.5 * n_rows),
        gridspec_kw={"height_ratios": ratios},
        sharex=True,
    )
    if n_rows == 1:
        axes = [axes]

    fig.suptitle(title, fontsize=16, fontweight="bold", y=0.98)

    ax_idx = 0

    # ── 子图 1: Equity Curve (归一化) ─────────────────────────
    ax_eq = axes[ax_idx]
    ax_idx += 1

    ax_eq.plot(timestamps, norm_equity, color="#2196F3", linewidth=1.8,
               label="Strategy", zorder=3)
    ax_eq.fill_between(timestamps, norm_equity, 100, alpha=0.06, color="#2196F3")

    if has_bench:
        bench_timestamps = [t for t, _ in benchmark.equity_curve]
        ax_eq.plot(bench_timestamps, bench_norm, color="#FF9800", linewidth=1.5,
                   label=benchmark_label, linestyle="--", alpha=0.85, zorder=2)

    ax_eq.axhline(100, color="gray", linestyle="--", linewidth=0.8, alpha=0.5)

    # 标注指标
    if has_bench:
        info_text = (
            f"Strategy: {metrics['total_return']:.1%} ({metrics['cagr']:.1%} CAGR, "
            f"Sharpe {metrics['sharpe_ratio']:.2f}, "
            f"MaxDD {metrics['max_drawdown']:.1%})    "
            f"{benchmark_label}: {bench_metrics['total_return']:.1%} ({bench_metrics['cagr']:.1%} CAGR, "
            f"MaxDD {bench_metrics['max_drawdown']:.1%})"
        )
    else:
        info_text = (
            f"Return: {metrics['total_return']:.2%}  |  "
            f"CAGR: {metrics['cagr']:.2%}  |  "
            f"Sharpe: {metrics['sharpe_ratio']:.2f}  |  "
            f"MaxDD: {metrics['max_drawdown']:.2%}"
        )

    ax_eq.text(
        0.5, 1.02, info_text,
        transform=ax_eq.transAxes, ha="center", fontsize=9.5,
        color="#555555",
    )

    ax_eq.set_ylabel("Growth of $100")
    ax_eq.yaxis.set_major_formatter(FuncFormatter(lambda x, _: f"${x:,.0f}"))
    ax_eq.legend(loc="upper left", framealpha=0.9, fontsize=10)
    ax_eq.grid(True, alpha=0.3)

    # ── 子图 2: Drawdown ──────────────────────────────────────
    ax_dd = axes[ax_idx]
    ax_idx += 1

    ax_dd.fill_between(timestamps, drawdown, 0, color="#F44336", alpha=0.35,
                       label="Strategy")
    ax_dd.plot(timestamps, drawdown, color="#F44336", linewidth=0.8)

    if has_bench:
        bench_timestamps = [t for t, _ in benchmark.equity_curve]
        ax_dd.plot(bench_timestamps, bench_dd, color="#FF9800", linewidth=1.2,
                   linestyle="--", alpha=0.7, label=benchmark_label)

    # 标注策略最大回撤
    max_dd_idx = np.argmin(drawdown)
    ax_dd.annotate(
        f"{drawdown[max_dd_idx]:.1f}%",
        xy=(timestamps[max_dd_idx], drawdown[max_dd_idx]),
        xytext=(20, -15),
        textcoords="offset points",
        fontsize=9, color="#D32F2F", fontweight="bold",
        arrowprops=dict(arrowstyle="->", color="#D32F2F", lw=1.2),
    )

    # 标注基准最大回撤
    if has_bench:
        bench_max_dd_idx = np.argmin(bench_dd)
        ax_dd.annotate(
            f"{bench_dd[bench_max_dd_idx]:.1f}%",
            xy=(bench_timestamps[bench_max_dd_idx], bench_dd[bench_max_dd_idx]),
            xytext=(-60, -15),
            textcoords="offset points",
            fontsize=9, color="#E65100", fontweight="bold",
            arrowprops=dict(arrowstyle="->", color="#E65100", lw=1.2),
        )

    dd_min = drawdown.min()
    if has_bench:
        dd_min = min(dd_min, bench_dd.min())
    ax_dd.set_ylim(dd_min * 1.3, 1)
    ax_dd.set_ylabel("Drawdown (%)")
    ax_dd.legend(loc="lower left", framealpha=0.9, fontsize=9)
    ax_dd.grid(True, alpha=0.3)

    # ── 子图 3: 超额收益 ─────────────────────────────────────
    if has_bench:
        ax_ex = axes[ax_idx]
        ax_idx += 1

        excess_ts = timestamps[:len(excess_return)]
        ax_ex.fill_between(
            excess_ts, excess_return, 0,
            where=excess_return >= 0, color="#4CAF50", alpha=0.4,
        )
        ax_ex.fill_between(
            excess_ts, excess_return, 0,
            where=excess_return < 0, color="#F44336", alpha=0.4,
        )
        ax_ex.plot(excess_ts, excess_return, color="#333333", linewidth=0.8)
        ax_ex.axhline(0, color="gray", linestyle="-", linewidth=0.8, alpha=0.5)

        ax_ex.set_ylabel("Excess Return (%)")
        ax_ex.yaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{x:+.0f}%"))
        ax_ex.grid(True, alpha=0.3)

        # 标注最终超额
        final_excess = excess_return[-1]
        color = "#4CAF50" if final_excess >= 0 else "#F44336"
        sign = "+" if final_excess >= 0 else ""
        ax_ex.text(
            0.98, 0.95,
            f"Final: {sign}{final_excess:.1f}%",
            transform=ax_ex.transAxes, ha="right", va="top",
            fontsize=10, fontweight="bold", color=color,
            bbox=dict(boxstyle="round,pad=0.3", facecolor="white", edgecolor=color, alpha=0.8),
        )

    # ── 子图 4: 标的价格 ─────────────────────────────────────
    if has_price:
        ax_price = axes[ax_idx]
        ax_idx += 1

        for symbol in bar_data.symbols:
            bars = bar_data._bars[symbol]
            ts = [b.timestamp for b in bars]
            closes = [b.close for b in bars]
            ax_price.plot(ts, closes, linewidth=1.0, label=symbol, alpha=0.8)

        ax_price.set_ylabel("Price ($)")
        ax_price.yaxis.set_major_formatter(FuncFormatter(lambda x, _: f"${x:,.0f}"))
        ax_price.legend(loc="upper left", framealpha=0.9, fontsize=8, ncol=3)
        ax_price.grid(True, alpha=0.3)

    # ── X 轴格式 ─────────────────────────────────────────────
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    # 根据时间跨度自动调整间隔
    date_range = (timestamps[-1] - timestamps[0]).days
    if date_range > 365 * 5:
        axes[-1].xaxis.set_major_locator(mdates.MonthLocator(interval=6))
    elif date_range > 365 * 2:
        axes[-1].xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    else:
        axes[-1].xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    plt.xticks(rotation=45)

    plt.tight_layout()

    if save_path:
        fig.savefig(save_path, dpi=150, bbox_inches="tight")
        print(f"Chart saved to {save_path}")

    if show:
        plt.show()

    plt.close(fig)
