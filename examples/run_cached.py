"""
示例: 数据缓存层 — 避免重复下载，加速回测迭代。

用法: python -m examples.run_cached

演示:
1. 第一次运行 → 从 yfinance 下载，耗时数秒，结果缓存到本地
2. 第二次运行 → 直接读缓存，毫秒级完成
3. 扩展日期范围 → 只下载缺失部分，智能合并
"""

import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.data import YFinanceFeed, CachedFeed
from engine.engine import BacktestEngine
from engine.analytics.metrics import print_report
from strategies.sma_crossover import SMACrossover


def main():
    # 用 CachedFeed 包装 YFinanceFeed
    inner = YFinanceFeed()
    feed = CachedFeed(inner, cache_dir="data_cache")

    symbol = "AAPL"

    # ── 第一次: 下载并缓存 ──────────────────────────────
    print("=" * 60)
    print("RUN 1: First fetch — downloads from yfinance")
    print("=" * 60)

    t0 = time.time()
    strategy1 = SMACrossover(symbol=symbol, fast_period=10, slow_period=30, size=100)
    engine1 = BacktestEngine(
        strategy=strategy1,
        data_feed=feed,
        symbols=[symbol],
        start="2023-01-01",
        end="2023-12-31",
        initial_cash=100_000.0,
    )
    portfolio1 = engine1.run()
    t1 = time.time()
    print(f"\n⏱  Run 1 took {t1 - t0:.2f}s")
    print_report(portfolio1)

    # 查看缓存信息
    info = feed.cache_info(symbol)
    print(f"\n📦 Cache info: {info}")

    # ── 第二次: 完全命中缓存 ──────────────────────────────
    print("\n" + "=" * 60)
    print("RUN 2: Same date range — cache hit, zero network")
    print("=" * 60)

    t0 = time.time()
    strategy2 = SMACrossover(symbol=symbol, fast_period=10, slow_period=30, size=100)
    engine2 = BacktestEngine(
        strategy=strategy2,
        data_feed=feed,
        symbols=[symbol],
        start="2023-01-01",
        end="2023-12-31",
        initial_cash=100_000.0,
    )
    portfolio2 = engine2.run()
    t2 = time.time()
    print(f"\n⏱  Run 2 took {t2 - t0:.2f}s (cache hit!)")

    # ── 第三次: 扩展日期范围 → 只下载缺失部分 ──────────────
    print("\n" + "=" * 60)
    print("RUN 3: Extended range 2022~2024 — only fetches missing dates")
    print("=" * 60)

    t0 = time.time()
    strategy3 = SMACrossover(symbol=symbol, fast_period=10, slow_period=30, size=100)
    engine3 = BacktestEngine(
        strategy=strategy3,
        data_feed=feed,
        symbols=[symbol],
        start="2022-01-01",
        end="2025-12-31",
        initial_cash=100_000.0,
    )
    portfolio3 = engine3.run()
    t3 = time.time()
    print(f"\n⏱  Run 3 took {t3 - t0:.2f}s (partial download)")
    print_report(portfolio3)

    # 查看更新后的缓存
    info = feed.cache_info(symbol)
    print(f"\n📦 Updated cache: {info}")

    print("\n✅ Done! Check data_cache/ for cached files.")


if __name__ == "__main__":
    main()
