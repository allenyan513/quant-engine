"""
示例: TQQQ/SQQQ 杠杆反转策略 — 多信号投票机制。

用法: python -m examples.run_leveraged_regime

测试不同阈值和信号灵敏度的效果:
- 激进模式: bull>=2, bear<=-2 (更频繁切换)
- 标准模式: bull>=3, bear<=-3 (需要更多信号确认)
- 保守模式: bull>=4, bear<=-4 (极少做空，多数时间观望)
- 纯做多模式: 只做 TQQQ + SHY (不做空, 作为基准)

回测区间: 2015-01-01 ~ 2024-12-31
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.engine import BacktestEngine
from engine.data import YFinanceFeed, CachedFeed
from engine.analytics.metrics import print_report, calculate_metrics
from engine.analytics.chart import plot_backtest
from strategies.leveraged_regime import LeveragedRegime
from strategies.dual_momentum import DualMomentum
from strategies.buy_and_hold import BuyAndHold


def main():
    start = "2015-01-01"
    end = "2025-12-31"
    feed = CachedFeed(YFinanceFeed())

    all_symbols = ["TQQQ", "SQQQ", "QQQ", "SPY", "SHY"]

    # ── 配置矩阵 ─────────────────────────────────────────────
    configs = [
        {
            "name": "Aggressive (bull>=2, bear<=-2, 5d)",
            "bull_threshold": 2,
            "bear_threshold": -2,
            "rebalance_period": 5,
        },
        {
            "name": "Standard (bull>=3, bear<=-3, 5d)",
            "bull_threshold": 3,
            "bear_threshold": -3,
            "rebalance_period": 5,
        },
        {
            "name": "Conservative (bull>=4, bear<=-4, 5d)",
            "bull_threshold": 4,
            "bear_threshold": -4,
            "rebalance_period": 5,
        },
        {
            "name": "Asymmetric (bull>=2, bear<=-4, 5d)",
            "bull_threshold": 2,
            "bear_threshold": -4,
            "rebalance_period": 5,
        },
    ]

    results = []

    for cfg in configs:
        print("=" * 60)
        print(f"Config: {cfg['name']}")
        print("=" * 60)

        strategy = LeveragedRegime(
            bull_asset="TQQQ",
            bear_asset="SQQQ",
            safe_asset="SHY",
            reference="QQQ",
            fast_sma=50,
            slow_sma=200,
            bull_threshold=cfg["bull_threshold"],
            bear_threshold=cfg["bear_threshold"],
            rebalance_period=cfg["rebalance_period"],
        )

        engine = BacktestEngine(
            strategy=strategy,
            data_feed=feed,
            symbols=all_symbols,
            start=start,
            end=end,
            initial_cash=100_000.0,
            commission_rate=0.001,
            slippage_rate=0.0005,
        )
        p = engine.run()
        m = calculate_metrics(p)
        results.append((cfg["name"], p, m, engine))
        print()

    # ── 基准 1: TQQQ + SMA200 (纯做多, 之前的最佳) ──────────
    print("=" * 60)
    print("Baseline: TQQQ + SMA200 (long only)")
    print("=" * 60)

    baseline_strategy = DualMomentum(
        offensive=["TQQQ"],
        defensive="SHY",
        regime_symbol="SPY",
        regime_sma=200,
        momentum_period=126,
        rebalance_period=21,
    )
    baseline_engine = BacktestEngine(
        strategy=baseline_strategy,
        data_feed=feed,
        symbols=["TQQQ", "SHY", "SPY"],
        start=start,
        end=end,
        initial_cash=100_000.0,
        commission_rate=0.001,
        slippage_rate=0.0005,
    )
    baseline_portfolio = baseline_engine.run()
    baseline_metrics = calculate_metrics(baseline_portfolio)

    # ── 基准 2: SPY 买入持有 ──────────────────────────────────
    bench_strategy = BuyAndHold(symbol="SPY", size=500)
    bench_engine = BacktestEngine(
        strategy=bench_strategy,
        data_feed=feed,
        symbols=["SPY"],
        start=start,
        end=end,
        initial_cash=100_000.0,
        commission_rate=0.001,
        slippage_rate=0.0005,
    )
    bench_portfolio = bench_engine.run()
    bench_metrics = calculate_metrics(bench_portfolio)

    # ── 全配置对比表 ──────────────────────────────────────────
    print("\n" + "=" * 80)
    print("ALL CONFIGS COMPARISON")
    print("=" * 80)
    print(f"  {'Config':<42} {'Return':>10} {'CAGR':>8} {'MaxDD':>8} {'Sharpe':>8} {'Calmar':>8}")
    print("  " + "-" * 76)

    for name, _, m, _ in results:
        print(f"  {name:<42} {m['total_return']:>10.1%} {m['cagr']:>8.1%} "
              f"{m['max_drawdown']:>8.1%} {m['sharpe_ratio']:>8.2f} {m['calmar_ratio']:>8.2f}")

    print("  " + "-" * 76)
    print(f"  {'TQQQ + SMA200 (long only)':<42} {baseline_metrics['total_return']:>10.1%} "
          f"{baseline_metrics['cagr']:>8.1%} {baseline_metrics['max_drawdown']:>8.1%} "
          f"{baseline_metrics['sharpe_ratio']:>8.2f} {baseline_metrics['calmar_ratio']:>8.2f}")
    print(f"  {'SPY Buy & Hold':<42} {bench_metrics['total_return']:>10.1%} "
          f"{bench_metrics['cagr']:>8.1%} {bench_metrics['max_drawdown']:>8.1%} "
          f"{bench_metrics['sharpe_ratio']:>8.2f} {bench_metrics['calmar_ratio']:>8.2f}")
    print("  " + "-" * 76)

    # ── 最佳配置详细报告 ─────────────────────────────────────
    best_idx = max(range(len(results)), key=lambda i: results[i][2]["total_return"])
    best_name, best_portfolio, best_metrics, best_engine = results[best_idx]

    print(f"\n🏆 Best config by return: {best_name}")

    # 找风险调整最优
    best_sharpe_idx = max(range(len(results)), key=lambda i: results[i][2]["sharpe_ratio"])
    print(f"🏆 Best config by Sharpe: {results[best_sharpe_idx][0]}")

    print("\n" + "=" * 60)
    print(f"DETAILED REPORT: {best_name}")
    print("=" * 60)
    print_report(best_portfolio, benchmark_curve=bench_portfolio.equity_curve)

    print("\nCurrent Holding:")
    for sym, pos in best_portfolio.positions.items():
        if pos.quantity != 0:
            bar = best_engine.bar_data.current(sym)
            mkt_val = pos.quantity * bar.close if bar else 0
            print(f"  {sym}: {pos.quantity} shares, market_value=${mkt_val:,.2f}")

    # ── 可视化 ────────────────────────────────────────────────
    plot_backtest(
        portfolio=best_portfolio,
        bar_data=best_engine.bar_data,
        benchmark=bench_portfolio,
        benchmark_label="SPY Buy & Hold",
        title=f"Leveraged Regime: {best_name} vs SPY (2015-2024)",
        save_path="backtest_leveraged_regime.png",
        show=False,
    )
    print("\n✅ Chart saved to backtest_leveraged_regime.png")


if __name__ == "__main__":
    main()
