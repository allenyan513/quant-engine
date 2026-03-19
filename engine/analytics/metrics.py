"""
回测结果分析 — Phase 1 基础指标。
"""

from __future__ import annotations

import numpy as np

from engine.portfolio.portfolio import Portfolio


def calculate_metrics(portfolio: Portfolio) -> dict:
    """计算核心回测指标。"""
    if len(portfolio.equity_curve) < 2:
        return {}

    equities = np.array([e for _, e in portfolio.equity_curve])
    timestamps = [t for t, _ in portfolio.equity_curve]

    # 收益率序列
    returns = np.diff(equities) / equities[:-1]

    # 总收益
    total_return = (equities[-1] / equities[0]) - 1

    # 年化收益 (假设252个交易日)
    n_days = (timestamps[-1] - timestamps[0]).days
    if n_days > 0:
        cagr = (equities[-1] / equities[0]) ** (365 / n_days) - 1
    else:
        cagr = 0.0

    # 最大回撤
    peak = np.maximum.accumulate(equities)
    drawdown = (equities - peak) / peak
    max_drawdown = drawdown.min()

    # Sharpe Ratio (年化，假设无风险利率 = 0)
    if returns.std() > 0:
        sharpe = returns.mean() / returns.std() * np.sqrt(252)
    else:
        sharpe = 0.0

    # 胜率
    winning_days = (returns > 0).sum()
    total_days = len(returns)
    win_rate = winning_days / total_days if total_days > 0 else 0.0

    return {
        "total_return": total_return,
        "cagr": cagr,
        "max_drawdown": max_drawdown,
        "sharpe_ratio": sharpe,
        "win_rate": win_rate,
        "total_trades_days": total_days,
        "initial_equity": equities[0],
        "final_equity": equities[-1],
        "realized_pnl": portfolio.realized_pnl,
    }


def print_report(portfolio: Portfolio) -> None:
    """打印回测报告。"""
    metrics = calculate_metrics(portfolio)
    if not metrics:
        print("No data to report.")
        return

    print("\n" + "=" * 50)
    print("           BACKTEST REPORT")
    print("=" * 50)
    print(f"  Initial Equity:   ${metrics['initial_equity']:>12,.2f}")
    print(f"  Final Equity:     ${metrics['final_equity']:>12,.2f}")
    print(f"  Total Return:     {metrics['total_return']:>12.2%}")
    print(f"  CAGR:             {metrics['cagr']:>12.2%}")
    print(f"  Max Drawdown:     {metrics['max_drawdown']:>12.2%}")
    print(f"  Sharpe Ratio:     {metrics['sharpe_ratio']:>12.2f}")
    print(f"  Win Rate (daily): {metrics['win_rate']:>12.2%}")
    print(f"  Realized PnL:     ${metrics['realized_pnl']:>12,.2f}")
    print("=" * 50)
