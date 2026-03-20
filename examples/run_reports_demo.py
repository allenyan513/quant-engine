"""
Demo: 运行 3 个策略，生成完整报告到 outputs/ 目录。

用法: python -m examples.run_reports_demo
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.engine import BacktestEngine
from engine.data import YFinanceFeed, CachedFeed
from engine.analytics.report import generate_report
from strategies.sma_crossover import SMACrossover
from strategies.dual_momentum import DualMomentum
from strategies.all_weather_momentum import AllWeatherMomentum


def run_and_report(name, strategy, symbols, start, end, feed):
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")

    engine = BacktestEngine(
        strategy=strategy,
        data_feed=feed,
        symbols=symbols,
        start=start,
        end=end,
        initial_cash=100_000.0,
        commission_rate=0.001,
        slippage_rate=0.0005,
    )
    engine.run()

    output_dir = generate_report(
        engine=engine,
        strategy_name=name,
    )
    return output_dir


def main():
    feed = CachedFeed(YFinanceFeed())

    # ── 1. SMA Crossover (AAPL, 2 年) ──
    run_and_report(
        name="SMA Crossover (AAPL)",
        strategy=SMACrossover(symbol="AAPL", fast_period=10, slow_period=30, size=100),
        symbols=["AAPL"],
        start="2023-01-01",
        end="2025-12-31",
        feed=feed,
    )

    # ── 2. Dual Momentum (TQQQ, 10 年) ──
    offensive = ["TQQQ", "QQQ"]
    defensive = "SHY"
    run_and_report(
        name="Dual Momentum (TQQQ/QQQ)",
        strategy=DualMomentum(
            offensive=offensive,
            defensive=defensive,
            regime_symbol="SPY",
            regime_sma=200,
            momentum_period=126,
            rebalance_period=21,
        ),
        symbols=list(set(offensive + [defensive, "SPY"])),
        start="2015-01-01",
        end="2025-12-31",
        feed=feed,
    )

    # ── 3. All-Weather Momentum (10 资产, 10 年) ──
    universe = ["SPY", "QQQ", "IWM", "EFA", "EEM", "TLT", "IEF", "DBC", "GLD", "VNQ"]
    safe = "SHY"
    run_and_report(
        name="All-Weather Adaptive Momentum",
        strategy=AllWeatherMomentum(
            universe=universe,
            safe_asset=safe,
            momentum_period=126,
            volatility_period=63,
            trend_sma_period=200,
            rebalance_period=21,
            top_k=4,
        ),
        symbols=list(set(universe + [safe])),
        start="2016-01-01",
        end="2025-12-31",
        feed=feed,
    )

    print("\n" + "=" * 60)
    print("  All reports generated in outputs/")
    print("=" * 60)


if __name__ == "__main__":
    main()
