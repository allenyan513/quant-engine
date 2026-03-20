"""
示例: 全天候自适应动量 — 跨周期验证。

用法: python -m examples.run_all_weather

在 3 个完全不同的市场环境中测试同一套参数:
  Period 1: 2005-2009 — 金融危机 (美股腰斩, 黄金/债券暴涨)
  Period 2: 2010-2019 — 慢牛 (美股持续上涨, 债券/商品弱)
  Period 3: 2020-2024 — 暴涨暴跌 (COVID崩盘→暴涨→加息→AI牛市)
  Full:     2005-2024 — 完整 20 年

核心问题: 同一个策略、同一套参数，能否在所有环境下都跑赢 SPY?
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.engine import BacktestEngine
from engine.data import YFinanceFeed, CachedFeed
from engine.analytics.metrics import print_report, calculate_metrics
from engine.analytics.chart import plot_backtest
from strategies.all_weather_momentum import AllWeatherMomentum
from strategies.buy_and_hold import BuyAndHold


def run_backtest(feed, strategy_cls, strategy_kwargs, symbols, start, end, initial_cash=100_000.0):
    """运行一次回测，返回 (portfolio, metrics, engine)。"""
    strategy = strategy_cls(**strategy_kwargs)
    engine = BacktestEngine(
        strategy=strategy,
        data_feed=feed,
        symbols=symbols,
        start=start,
        end=end,
        initial_cash=initial_cash,
        commission_rate=0.001,
        slippage_rate=0.0005,
    )
    portfolio = engine.run()
    metrics = calculate_metrics(portfolio)
    return portfolio, metrics, engine


def main():
    feed = CachedFeed(YFinanceFeed())

    # ── 资产宇宙 ──────────────────────────────────────────────
    universe = [
        "SPY", "QQQ", "IWM",   # 美股
        "EFA", "EEM",           # 国际
        "TLT", "IEF",           # 债券
        "DBC",                  # 商品
        "GLD",                  # 黄金
        "VNQ",                  # REITs
    ]
    safe = "SHY"
    all_symbols = list(set(universe + [safe]))

    strategy_kwargs = dict(
        universe=universe,
        safe_asset=safe,
        momentum_period=126,
        volatility_period=63,
        trend_sma_period=200,
        rebalance_period=21,
        top_k=4,
    )

    # ── 跨周期测试 ────────────────────────────────────────────
    # DBC 从 2006-02 开始有数据，所以从 2007 开始确保有足够 lookback
    periods = [
        ("2007-01-01", "2009-12-31", "Financial Crisis"),
        ("2010-01-01", "2019-12-31", "Long Bull Market"),
        ("2020-01-01", "2024-12-31", "COVID + Rate Hikes"),
        ("2007-01-01", "2024-12-31", "FULL PERIOD (18 years)"),
    ]

    all_results = []

    for start, end, label in periods:
        print("\n" + "=" * 70)
        print(f"  PERIOD: {label} ({start} ~ {end})")
        print("=" * 70)

        # 策略
        strat_p, strat_m, strat_e = run_backtest(
            feed, AllWeatherMomentum, strategy_kwargs,
            all_symbols, start, end,
        )

        # 基准: SPY 买入持有
        bench_p, bench_m, _ = run_backtest(
            feed, BuyAndHold, dict(symbol="SPY", size=500),
            ["SPY"], start, end,
        )

        all_results.append((label, start, end, strat_p, strat_m, bench_p, bench_m, strat_e))

    # ── 跨周期对比表 ──────────────────────────────────────────
    print("\n\n" + "=" * 90)
    print("CROSS-CYCLE VALIDATION: All-Weather Momentum vs SPY Buy & Hold")
    print("=" * 90)
    print(f"  {'Period':<28} {'Strategy':>10} {'SPY B&H':>10} {'Strat DD':>10} "
          f"{'SPY DD':>10} {'Strat SR':>10} {'Winner':>10}")
    print("  " + "-" * 86)

    strategy_wins = 0

    for label, start, end, _, sm, _, bm, _ in all_results:
        s_ret = sm['total_return']
        b_ret = bm['total_return']
        s_dd = sm['max_drawdown']
        b_dd = bm['max_drawdown']
        s_sr = sm['sharpe_ratio']

        winner = "Strategy" if s_ret > b_ret else "SPY"
        if s_ret > b_ret:
            strategy_wins += 1

        print(f"  {label:<28} {s_ret:>10.1%} {b_ret:>10.1%} {s_dd:>10.1%} "
              f"{b_dd:>10.1%} {s_sr:>10.2f} {winner:>10}")

    print("  " + "-" * 86)
    print(f"\n  Strategy wins {strategy_wins}/{len(all_results)} periods")

    # ── 全周期详细报告 ────────────────────────────────────────
    full_label, _, _, full_p, full_m, full_bp, full_bm, full_e = all_results[-1]

    print("\n" + "=" * 70)
    print(f"DETAILED REPORT: {full_label}")
    print("=" * 70)
    print_report(full_p, benchmark_curve=full_bp.equity_curve)

    print("\nCurrent Holdings:")
    for sym, pos in full_p.positions.items():
        if pos.quantity != 0:
            bar = full_e.bar_data.current(sym)
            mkt_val = pos.quantity * bar.close if bar else 0
            pct = mkt_val / full_p.equity * 100
            print(f"  {sym}: {pos.quantity} shares, "
                  f"${mkt_val:,.0f} ({pct:.1f}%)")

    # ── 可视化 ────────────────────────────────────────────────
    plot_backtest(
        portfolio=full_p,
        bar_data=full_e.bar_data,
        benchmark=full_bp,
        benchmark_label="SPY Buy & Hold",
        title="All-Weather Adaptive Momentum vs SPY (2007-2024)",
        save_path="backtest_all_weather.png",
        show=False,
    )
    print("\n✅ Chart saved to backtest_all_weather.png")


if __name__ == "__main__":
    main()
