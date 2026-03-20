"""
示例: 运行 SMA 交叉策略回测 (带 SPY 基准对比)。

用法: python -m examples.run_sma
"""

import sys
import os

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.engine import BacktestEngine
from engine.data import YFinanceFeed, CachedFeed
from engine.analytics.metrics import print_report
from engine.analytics.chart import plot_backtest
from strategies.sma_crossover import SMACrossover
from strategies.buy_and_hold import BuyAndHold


def main():
    feed = CachedFeed(YFinanceFeed())

    # ── 策略 ──────────────────────────────────────────────────
    symbol = "AAPL"
    start = "2023-01-01"
    end = "2025-12-31"

    strategy = SMACrossover(
        symbol=symbol,
        fast_period=10,
        slow_period=30,
        size=100,
    )

    engine = BacktestEngine(
        strategy=strategy,
        data_feed=feed,
        symbols=[symbol],
        start=start,
        end=end,
        initial_cash=100_000.0,
        commission_rate=0.001,
        slippage_rate=0.0005,
    )
    portfolio = engine.run()

    # ── 基准: SPY 买入持有 ────────────────────────────────────
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

    # ── 报告 ──────────────────────────────────────────────────
    print_report(portfolio, benchmark_curve=bench_portfolio.equity_curve)

    print("\nOpen Positions:")
    for sym, pos in portfolio.positions.items():
        if pos.quantity != 0:
            print(f"  {sym}: {pos.quantity} shares @ ${pos.avg_cost:.2f}")

    # ── 可视化 (带基准) ──────────────────────────────────────
    plot_backtest(
        portfolio=portfolio,
        bar_data=engine.bar_data,
        benchmark=bench_portfolio,
        benchmark_label="SPY Buy & Hold",
        title=f"SMA Crossover ({symbol}) vs SPY — 2023-2024",
        save_path="backtest_result.png",
        show=False,
    )


if __name__ == "__main__":
    main()
