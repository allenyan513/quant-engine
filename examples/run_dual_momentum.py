"""
示例: 双动量策略 — 集中持有最强美股 ETF + 熊市避险。

用法: python -m examples.run_dual_momentum

策略:
- 攻击性资产: QQQ / SPY / IWM (选最强的一个全仓持有)
- 避险资产: SHY (短期国债)
- 每月调仓，过去 6 个月动量排名
- 双重过滤: 相对动量 + 绝对动量 + SPY 200 SMA

回测区间: 2015-01-01 ~ 2024-12-31 (10 年)
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.engine import BacktestEngine
from engine.data import YFinanceFeed, CachedFeed
from engine.execution.fee_model import PerShareFeeModel
from engine.analytics.metrics import print_report, calculate_metrics
from engine.analytics.chart import plot_backtest
from strategies.dual_momentum import DualMomentum
from strategies.buy_and_hold import BuyAndHold


def main():
    start = "2015-01-01"
    end = "2025-12-31"
    feed = CachedFeed(YFinanceFeed())

    # ── 双动量策略 ────────────────────────────────────────────
    # ── 配置矩阵: 测试多种参数组合 ─────────────────────────
    configs = [
        {
            "name": "QQQ only + SMA200 Filter",
            "offensive": ["QQQ"],
            "defensive": "SHY",
            "momentum_period": 126,
            "regime_sma": 200,
        },
        {
            "name": "TQQQ only + SMA200 Filter",
            "offensive": ["TQQQ"],
            "defensive": "SHY",
            "momentum_period": 126,
            "regime_sma": 200,
        },
        {
            "name": "TQQQ/QQQ Dual Mom (6mo, SMA200)",
            "offensive": ["TQQQ", "QQQ"],
            "defensive": "SHY",
            "momentum_period": 126,
            "regime_sma": 200,
        },
        {
            "name": "TQQQ only + SMA150 Filter",
            "offensive": ["TQQQ"],
            "defensive": "SHY",
            "momentum_period": 126,
            "regime_sma": 150,
        },
    ]

    results = []

    for cfg in configs:
        offensive = cfg["offensive"]
        defensive = cfg["defensive"]
        all_symbols = list(set(offensive + [defensive, "SPY"]))

        print("=" * 60)
        print(f"Strategy: {cfg['name']}")
        print("=" * 60)

        strategy = DualMomentum(
            offensive=offensive,
            defensive=defensive,
            regime_symbol="SPY",
            regime_sma=cfg["regime_sma"],
            momentum_period=cfg["momentum_period"],
            rebalance_period=21,
        )

        engine = BacktestEngine(
            strategy=strategy,
            data_feed=feed,
            symbols=all_symbols,
            start=start,
            end=end,
            initial_cash=100_000.0,
            fee_model=PerShareFeeModel(),
            slippage_rate=0.0005,
        )
        p = engine.run()
        m = calculate_metrics(p)
        results.append((cfg["name"], p, m, engine))
        print()

    # 用最佳结果做图
    best_idx = max(range(len(results)), key=lambda i: results[i][2]["total_return"])
    best_name, portfolio, _, engine = results[best_idx]
    print(f"\n>> Best config: {best_name}")

    # 下面的代码使用 best result
    offensive = configs[best_idx]["offensive"]
    defensive = configs[best_idx]["defensive"]
    all_symbols = list(set(offensive + [defensive, "SPY"]))

    # ── 基准: SPY 买入持有 ────────────────────────────────────
    bench_strategy = BuyAndHold(symbol="SPY", size=500)
    bench_engine = BacktestEngine(
        strategy=bench_strategy,
        data_feed=feed,
        symbols=["SPY"],
        start=start,
        end=end,
        initial_cash=100_000.0,
        fee_model=PerShareFeeModel(),
        slippage_rate=0.0005,
    )
    bench_portfolio = bench_engine.run()

    # ── 报告 ──────────────────────────────────────────────────
    m1 = calculate_metrics(portfolio)
    m2 = calculate_metrics(bench_portfolio)

    # ── 全配置对比表 ──────────────────────────────────────────
    print("\n" + "=" * 70)
    print("ALL CONFIGS vs SPY Buy & Hold")
    print("=" * 70)
    print(f"  {'Config':<40} {'Return':>10} {'CAGR':>8} {'MaxDD':>8} {'Sharpe':>8}")
    print("  " + "-" * 66)
    for name, _, m, _ in results:
        print(f"  {name:<40} {m['total_return']:>10.2%} {m['cagr']:>8.2%} "
              f"{m['max_drawdown']:>8.2%} {m['sharpe_ratio']:>8.2f}")
    print(f"  {'SPY Buy & Hold':<40} {m2['total_return']:>10.2%} {m2['cagr']:>8.2%} "
          f"{m2['max_drawdown']:>8.2%} {m2['sharpe_ratio']:>8.2f}")
    print("  " + "-" * 66)

    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    print_report(portfolio, benchmark_curve=bench_portfolio.equity_curve)

    print("\nCurrent Holding:")
    for sym, pos in portfolio.positions.items():
        if pos.quantity != 0:
            bar = engine.bar_data.current(sym)
            mkt_val = pos.quantity * bar.close if bar else 0
            print(f"  {sym}: {pos.quantity} shares, "
                  f"market_value=${mkt_val:,.2f}")

    # ── 对比表 ────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("COMPARISON: Dual Momentum vs SPY Buy & Hold")
    print("=" * 60)
    print(f"{'Metric':<25} {'Dual Momentum':>15} {'SPY B&H':>15}")
    print("-" * 55)
    rows = [
        ("Total Return", f"{m1['total_return']:.2%}", f"{m2['total_return']:.2%}"),
        ("CAGR", f"{m1['cagr']:.2%}", f"{m2['cagr']:.2%}"),
        ("Volatility", f"{m1['volatility']:.2%}", f"{m2['volatility']:.2%}"),
        ("Max Drawdown", f"{m1['max_drawdown']:.2%}", f"{m2['max_drawdown']:.2%}"),
        ("Sharpe Ratio", f"{m1['sharpe_ratio']:.2f}", f"{m2['sharpe_ratio']:.2f}"),
        ("Sortino Ratio", f"{m1['sortino_ratio']:.2f}", f"{m2['sortino_ratio']:.2f}"),
        ("Calmar Ratio", f"{m1['calmar_ratio']:.2f}", f"{m2['calmar_ratio']:.2f}"),
    ]
    for name, v1, v2 in rows:
        # 标记胜出方
        print(f"  {name:<23} {v1:>15} {v2:>15}")

    winner = "Dual Momentum" if m1['total_return'] > m2['total_return'] else "SPY B&H"
    print(f"\n  >> Winner by total return: {winner}")
    if m1['sharpe_ratio'] > m2['sharpe_ratio']:
        print(f"  >> Winner by risk-adjusted return (Sharpe): Dual Momentum")
    else:
        print(f"  >> Winner by risk-adjusted return (Sharpe): SPY B&H")

    # ── 可视化 ────────────────────────────────────────────────
    plot_backtest(
        portfolio=portfolio,
        bar_data=engine.bar_data,
        benchmark=bench_portfolio,
        benchmark_label="SPY Buy & Hold",
        title=f"Best: {best_name} vs SPY (2015-2024)",
        save_path="backtest_dual_momentum.png",
        show=False,
    )
    print("\n✅ Chart saved to backtest_dual_momentum.png")


if __name__ == "__main__":
    main()
