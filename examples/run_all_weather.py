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
from engine.execution.fee_model import PerShareFeeModel
from engine.analytics.metrics import print_report, calculate_metrics
from engine.analytics.chart import plot_backtest
from engine.analytics.report import generate_report
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
        fee_model=PerShareFeeModel(),
        slippage_rate=0.0005,
    )
    portfolio = engine.run()
    metrics = calculate_metrics(portfolio)
    return portfolio, metrics, engine


def main():
    feed = CachedFeed(YFinanceFeed())

    # ── 资产宇宙 ──────────────────────────────────────────────
    # 两套宇宙对比: 有 BTC vs 无 BTC
    base_universe = [
        "SPY", "QQQ", "IWM",   # 美股
        "EFA", "EEM",           # 国际
        "TLT", "IEF",           # 债券
        "DBC",                  # 商品
        "GLD",                  # 黄金
        "VNQ",                  # REITs
    ]
    btc_universe = base_universe + ["BTC-USD"]  # 加入比特币

    safe = "SHY"

    base_kwargs = dict(
        safe_asset=safe,
        momentum_period=126,
        volatility_period=63,
        trend_sma_period=200,
        rebalance_period=21,
        top_k=4,
    )

    # 两个策略配置
    configs = [
        ("All-Weather (no BTC)", dict(universe=base_universe, **base_kwargs)),
        ("All-Weather + BTC",    dict(universe=btc_universe, **base_kwargs)),
    ]

    # BTC-USD 从 2014-09 开始有数据, 需要 200 天 warmup → 从 2016 开始
    periods = [
        ("2016-01-01", "2019-12-31", "Pre-COVID Bull"),
        ("2020-01-01", "2025-12-31", "COVID + Rate Hikes"),
        ("2016-01-01", "2025-12-31", "FULL PERIOD (10 years)"),
    ]

    # ── 每个周期跑两套配置 + SPY 基准 ──────────────────────────
    # results[period_label] = {config_name: (portfolio, metrics, engine)}
    all_results: dict[str, dict] = {}

    for start, end, label in periods:
        print("\n" + "=" * 70)
        print(f"  PERIOD: {label} ({start} ~ {end})")
        print("=" * 70)

        period_results = {}

        for cfg_name, cfg_kwargs in configs:
            all_symbols = list(set(cfg_kwargs["universe"] + [safe]))
            p, m, e = run_backtest(
                feed, AllWeatherMomentum, cfg_kwargs,
                all_symbols, start, end,
            )
            period_results[cfg_name] = (p, m, e)

        # SPY 基准
        bench_p, bench_m, _ = run_backtest(
            feed, BuyAndHold, dict(symbol="SPY", size=500),
            ["SPY"], start, end,
        )
        period_results["SPY Buy & Hold"] = (bench_p, bench_m, None)

        all_results[label] = period_results

    # ── 大对比表 ──────────────────────────────────────────────
    config_names = [c[0] for c in configs] + ["SPY Buy & Hold"]

    print("\n\n" + "=" * 95)
    print("CROSS-CYCLE COMPARISON: All-Weather (no BTC) vs All-Weather + BTC vs SPY")
    print("=" * 95)
    print(f"  {'Period':<25}", end="")
    for cn in config_names:
        print(f" {cn:>20}", end="")
    print()
    print("  " + "-" * 90)

    for label in [p[2] for p in periods]:
        pr = all_results[label]
        print(f"  {label:<25}", end="")
        for cn in config_names:
            ret = pr[cn][1]['total_return']
            print(f" {ret:>20.1%}", end="")
        print()

    # MaxDD 行
    print()
    print(f"  {'MAX DRAWDOWN':<25}", end="")
    for cn in config_names:
        # 用 full period
        full_label = periods[-1][2]
        dd = all_results[full_label][cn][1]['max_drawdown']
        print(f" {dd:>20.1%}", end="")
    print()

    # Sharpe 行
    print(f"  {'SHARPE (full period)':<25}", end="")
    for cn in config_names:
        full_label = periods[-1][2]
        sr = all_results[full_label][cn][1]['sharpe_ratio']
        print(f" {sr:>20.2f}", end="")
    print()
    print("  " + "-" * 90)

    # ── BTC 版本详细报告 ──────────────────────────────────────
    full_label = periods[-1][2]
    btc_name = configs[1][0]
    btc_p, btc_m, btc_e = all_results[full_label][btc_name]
    bench_p = all_results[full_label]["SPY Buy & Hold"][0]

    print("\n" + "=" * 70)
    print(f"DETAILED REPORT: {btc_name} — {full_label}")
    print("=" * 70)
    print_report(btc_p, engine=btc_e)

    print("\nCurrent Holdings:")
    for sym, pos in btc_p.positions.items():
        if pos.quantity != 0:
            bar = btc_e.bar_data.current(sym)
            mkt_val = pos.quantity * bar.close if bar else 0
            pct = mkt_val / btc_p.equity * 100
            print(f"  {sym}: {pos.quantity} shares, "
                  f"${mkt_val:,.0f} ({pct:.1f}%)")

    # ── 输出完整报告 (benchmark 自动使用 SPY) ─────────────────
    generate_report(
        engine=btc_e,
        strategy_name=f"All-Weather + BTC ({periods[-1][0][:4]}-{periods[-1][1][:4]})",
    )


if __name__ == "__main__":
    main()
