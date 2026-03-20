"""
示例: ETF 动量轮动策略 — 多资产 + 市场状态过滤器。

用法: python -m examples.run_etf_momentum

策略:
- 宇宙: 10 只 ETF (美股/国际/债券/商品/REITs)
- 每月调仓，买入过去 6 个月涨幅前 3 的 ETF
- 市场状态过滤: SPY < 200 SMA 时全部转现金
- 使用 CachedFeed 缓存数据 (第二次运行秒级完成)

回测区间: 2015-01-01 ~ 2024-12-31 (10 年)
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.engine import BacktestEngine
from engine.data import YFinanceFeed, CachedFeed
from engine.analytics.metrics import print_report, calculate_metrics
from engine.analytics.chart import plot_backtest
from strategies.etf_momentum_rotation import ETFMomentumRotation


def main():
    # ── 配置 ──────────────────────────────────────────────────
    universe = [
        "SPY",   # S&P 500
        "QQQ",   # Nasdaq 100
        "IWM",   # Russell 2000 小盘
        "EFA",   # 发达市场
        "EEM",   # 新兴市场
        "TLT",   # 美国长期国债
        "IEF",   # 美国中期国债
        "GLD",   # 黄金
        "DBC",   # 大宗商品
        "VNQ",   # 房地产 REITs
    ]

    start = "2015-01-01"
    end = "2024-12-31"

    # ── 数据源 (带缓存) ──────────────────────────────────────
    feed = CachedFeed(YFinanceFeed(), cache_dir="data_cache")

    # ── 策略 1: 动量轮动 + 市场过滤 ──────────────────────────
    print("=" * 60)
    print("Strategy: ETF Momentum Rotation + Regime Filter")
    print(f"Universe: {', '.join(universe)}")
    print(f"Period: {start} ~ {end}")
    print("=" * 60)

    strategy = ETFMomentumRotation(
        universe=universe,
        regime_symbol="SPY",
        regime_sma_period=200,
        momentum_period=126,    # 6 个月
        rebalance_period=21,    # 每月调仓
        top_k=3,
        use_regime_filter=True,
    )

    engine = BacktestEngine(
        strategy=strategy,
        data_feed=feed,
        symbols=universe,
        start=start,
        end=end,
        initial_cash=100_000.0,
        commission_rate=0.001,
        slippage_rate=0.0005,
    )

    portfolio = engine.run()

    print("\n" + "=" * 60)
    print("RESULTS: Momentum Rotation + Regime Filter")
    print("=" * 60)
    print_report(portfolio)

    # 打印当前持仓
    print("\nCurrent Holdings:")
    for sym, pos in portfolio.positions.items():
        if pos.quantity != 0:
            bar = engine.bar_data.current(sym)
            mkt_val = pos.quantity * bar.close if bar else 0
            print(f"  {sym}: {pos.quantity} shares, "
                  f"avg_cost=${pos.avg_cost:.2f}, "
                  f"market_value=${mkt_val:,.2f}")

    # ── 策略 2: 纯买入持有 SPY 作为基准 ──────────────────────
    print("\n" + "=" * 60)
    print("BENCHMARK: Buy & Hold SPY")
    print("=" * 60)

    from strategies.buy_and_hold import BuyAndHold
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
    print_report(bench_portfolio)

    # ── 对比 ──────────────────────────────────────────────────
    m1 = calculate_metrics(portfolio)
    m2 = calculate_metrics(bench_portfolio)

    print("\n" + "=" * 60)
    print("COMPARISON: Momentum Rotation vs Buy & Hold SPY")
    print("=" * 60)
    print(f"{'Metric':<25} {'Momentum':>15} {'SPY B&H':>15}")
    print("-" * 55)
    comparisons = [
        ("Total Return", f"{m1['total_return']:.2%}", f"{m2['total_return']:.2%}"),
        ("CAGR", f"{m1['cagr']:.2%}", f"{m2['cagr']:.2%}"),
        ("Volatility", f"{m1['volatility']:.2%}", f"{m2['volatility']:.2%}"),
        ("Max Drawdown", f"{m1['max_drawdown']:.2%}", f"{m2['max_drawdown']:.2%}"),
        ("Sharpe Ratio", f"{m1['sharpe_ratio']:.2f}", f"{m2['sharpe_ratio']:.2f}"),
        ("Sortino Ratio", f"{m1['sortino_ratio']:.2f}", f"{m2['sortino_ratio']:.2f}"),
        ("Calmar Ratio", f"{m1['calmar_ratio']:.2f}", f"{m2['calmar_ratio']:.2f}"),
    ]
    for name, v1, v2 in comparisons:
        print(f"  {name:<23} {v1:>15} {v2:>15}")

    # ── 可视化 ────────────────────────────────────────────────
    plot_backtest(
        portfolio=portfolio,
        bar_data=engine.bar_data,
        title="ETF Momentum Rotation + Regime Filter (2015-2024)",
        save_path="backtest_etf_momentum.png",
        show=False,
    )
    print("\n✅ Chart saved to backtest_etf_momentum.png")


if __name__ == "__main__":
    main()
