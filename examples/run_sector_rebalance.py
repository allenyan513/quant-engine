"""
示例: 50% XLK (科技) + 50% XLE (能源) 月度再平衡策略。

验证分散化投资的效果: 负相关资产组合能否提升 Sharpe Ratio。

用法: python -m examples.run_sector_rebalance
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.engine import BacktestEngine
from engine.data import YFinanceFeed, CachedFeed
from engine.execution.fee_model import PerShareFeeModel
from engine.analytics.metrics import print_report, calculate_metrics
from strategies.sector_rebalance import SectorRebalance
from strategies.buy_and_hold import BuyAndHold


def main():
    start = "2020-01-01"
    end = "2026-03-27"
    feed = CachedFeed(YFinanceFeed())

    # ── 50/50 XLK + XLE 再平衡策略 ──────────────────────────
    strategy = SectorRebalance(
        allocations={"XLK": 0.50, "XLE": 0.50},
        rebalance_period=21,
    )
    engine = BacktestEngine(
        strategy=strategy,
        data_feed=feed,
        symbols=["XLK", "XLE"],
        start=start,
        end=end,
        initial_cash=100_000.0,
        fee_model=PerShareFeeModel(),
        slippage_rate=0.0005,
    )
    portfolio = engine.run()

    # ── 单独 XLK 买入持有 ────────────────────────────────────
    xlk_strategy = BuyAndHold(symbol="XLK", size=700)
    xlk_engine = BacktestEngine(
        strategy=xlk_strategy,
        data_feed=feed,
        symbols=["XLK"],
        start=start,
        end=end,
        initial_cash=100_000.0,
        fee_model=PerShareFeeModel(),
        slippage_rate=0.0005,
    )
    xlk_portfolio = xlk_engine.run()

    # ── 单独 XLE 买入持有 ────────────────────────────────────
    xle_strategy = BuyAndHold(symbol="XLE", size=2200)
    xle_engine = BacktestEngine(
        strategy=xle_strategy,
        data_feed=feed,
        symbols=["XLE"],
        start=start,
        end=end,
        initial_cash=100_000.0,
        fee_model=PerShareFeeModel(),
        slippage_rate=0.0005,
    )
    xle_portfolio = xle_engine.run()

    # ── 计算指标 ──────────────────────────────────────────────
    m_combo = calculate_metrics(portfolio)
    m_xlk = calculate_metrics(xlk_portfolio)
    m_xle = calculate_metrics(xle_portfolio)

    # ── 对比表 ────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("50% XLK + 50% XLE Rebalance vs Single Asset Buy & Hold")
    print(f"Period: {start} ~ {end}")
    print("=" * 70)
    print(f"  {'Metric':<25} {'50/50 Combo':>15} {'XLK Only':>15} {'XLE Only':>15}")
    print("  " + "-" * 70)
    rows = [
        ("Total Return", m_combo['total_return'], m_xlk['total_return'], m_xle['total_return']),
        ("CAGR", m_combo['cagr'], m_xlk['cagr'], m_xle['cagr']),
        ("Volatility", m_combo['volatility'], m_xlk['volatility'], m_xle['volatility']),
        ("Max Drawdown", m_combo['max_drawdown'], m_xlk['max_drawdown'], m_xle['max_drawdown']),
        ("Sharpe Ratio", m_combo['sharpe_ratio'], m_xlk['sharpe_ratio'], m_xle['sharpe_ratio']),
        ("Sortino Ratio", m_combo['sortino_ratio'], m_xlk['sortino_ratio'], m_xle['sortino_ratio']),
        ("Calmar Ratio", m_combo['calmar_ratio'], m_xlk['calmar_ratio'], m_xle['calmar_ratio']),
    ]
    for name, v1, v2, v3 in rows:
        if name in ("Sharpe Ratio", "Sortino Ratio", "Calmar Ratio"):
            print(f"  {name:<25} {v1:>15.2f} {v2:>15.2f} {v3:>15.2f}")
        else:
            print(f"  {name:<25} {v1:>15.2%} {v2:>15.2%} {v3:>15.2%}")

    # Sharpe 对比结论
    print("\n  " + "-" * 70)
    sharpes = {"50/50 Combo": m_combo['sharpe_ratio'],
               "XLK Only": m_xlk['sharpe_ratio'],
               "XLE Only": m_xle['sharpe_ratio']}
    best = max(sharpes, key=sharpes.get)
    print(f"  >> Best Sharpe Ratio: {best} ({sharpes[best]:.2f})")
    print(f"  >> Diversification benefit: combo Sharpe ({m_combo['sharpe_ratio']:.2f}) "
          f"vs avg single ({(m_xlk['sharpe_ratio'] + m_xle['sharpe_ratio'])/2:.2f})")

    # ── 详细报告 ──────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("DETAILED REPORT: 50/50 XLK + XLE Rebalance")
    print("=" * 70)
    print_report(portfolio, trade_log=engine.trade_log, engine=engine)


if __name__ == "__main__":
    main()
