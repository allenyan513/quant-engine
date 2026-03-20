"""
示例: 带风险管理的唐奇安突破策略。

演示 Phase 2 新功能:
- ATR 仓位管理（自动计算仓位大小）
- 追踪止损（保护利润）
- 限价单入场（优化入场价格）
- TradeLog 交易日志
- 增强报告（Sortino / Calmar / 交易统计）

用法: python -m examples.run_risk_managed
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.engine import BacktestEngine
from engine.data import YFinanceFeed, CachedFeed
from engine.execution.fee_model import PerShareFeeModel
from engine.analytics.metrics import print_report
from engine.analytics.chart import plot_backtest
from engine.indicators import donchian, atr
from engine.risk.position_sizer import ATRSizer
from engine.strategy.base import BaseStrategy
from strategies.buy_and_hold import BuyAndHold


class RiskManagedBreakout(BaseStrategy):
    """
    带风险管理的唐奇安突破策略。

    相比原版 DonchianBreakout 的改进:
    1. 用 ATRSizer 自动计算仓位 — 每笔交易风险 1% 总资产
    2. 入场后设置 2x ATR 追踪止损 — 保护利润
    3. 用限价单入场 — 以突破价买入，避免追高
    """

    def __init__(
        self,
        symbol: str,
        entry_period: int = 20,
        exit_period: int = 10,
        atr_period: int = 20,
        trail_atr_mult: float = 2.0,
    ):
        super().__init__()
        self.symbol = symbol
        self.entry_period = entry_period
        self.exit_period = exit_period
        self.atr_period = atr_period
        self.trail_atr_mult = trail_atr_mult

        # 使用 ATR 仓位管理: 每笔交易风险 1%，止损距离 = 2x ATR
        self.position_sizer = ATRSizer(
            risk_pct=0.01,
            atr_period=atr_period,
            atr_multiplier=trail_atr_mult,
            max_position_pct=0.20,
        )

    def on_bar(self) -> None:
        needed = max(self.entry_period, self.atr_period) + 2
        if not self.bar_data.has_enough_bars(self.symbol, needed):
            return

        bar = self.bar_data.current(self.symbol)
        pos = self.get_position(self.symbol)

        highs = self.bar_data.history(self.symbol, "high", needed)
        lows = self.bar_data.history(self.symbol, "low", needed)
        closes = self.bar_data.history(self.symbol, "close", needed)

        # 计算当前 ATR
        atr_values = atr(highs, lows, closes, self.atr_period)
        current_atr = atr_values[-1]

        # 入场通道
        entry_ch = donchian(highs[:-1], lows[:-1], self.entry_period)
        entry_upper = entry_ch.upper[-1]

        if pos == 0:
            # ── 无仓位: 检查突破信号 ──
            if bar.close > entry_upper:
                # 用 ATRSizer 自动计算仓位大小
                qty = self.calculate_quantity(self.symbol)
                if qty > 0:
                    # 用限价单以突破价入场（避免追高）
                    self.buy_limit(self.symbol, qty, limit_price=entry_upper * 1.002)

        elif pos > 0:
            # ── 有仓位: 检查离场信号 ──
            exit_ch = donchian(highs[:-1], lows[:-1], self.exit_period)
            exit_lower = exit_ch.lower[-1]

            if bar.close < exit_lower:
                # 跌破离场通道 → 市价平仓，取消所有止损
                self.cancel_stops(self.symbol)
                self.sell(self.symbol, pos)

    def on_fill(self, fill) -> None:
        """成交后设置追踪止损。"""
        from engine.core.event import Direction
        if fill.direction == Direction.LONG:
            # 计算 ATR 用于追踪止损
            needed = self.atr_period + 2
            if self.bar_data.has_enough_bars(self.symbol, needed):
                highs = self.bar_data.history(self.symbol, "high", needed)
                lows = self.bar_data.history(self.symbol, "low", needed)
                closes = self.bar_data.history(self.symbol, "close", needed)
                atr_values = atr(highs, lows, closes, self.atr_period)
                current_atr = atr_values[-1]

                # 设置追踪止损: 距离 = trail_atr_mult × ATR
                trail_distance = current_atr * self.trail_atr_mult
                self.set_trailing_stop(
                    self.symbol,
                    trail_points=trail_distance,
                    quantity=fill.quantity,
                )
                print(f"  → Trailing stop set: {trail_distance:.2f} points "
                      f"({self.trail_atr_mult}x ATR={current_atr:.2f})")


def main():
    symbol = "AAPL"
    start = "2022-01-01"
    end = "2025-12-31"
    feed = CachedFeed(YFinanceFeed())

    strategy = RiskManagedBreakout(
        symbol=symbol,
        entry_period=20,
        exit_period=10,
        atr_period=20,
        trail_atr_mult=2.0,
    )

    engine = BacktestEngine(
        strategy=strategy,
        data_feed=feed,
        symbols=[symbol],
        start=start,
        end=end,
        initial_cash=100_000.0,
        fee_model=PerShareFeeModel(),
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
        fee_model=PerShareFeeModel(),
        slippage_rate=0.0005,
    )
    bench_portfolio = bench_engine.run()

    # ── 打印增强报告（含 Sortino / Calmar / 交易统计） ──
    print_report(
        portfolio=portfolio,
        trade_log=engine.trade_log,
        benchmark_curve=bench_portfolio.equity_curve,
    )

    # ── 打印交易明细 ──
    if engine.trade_log.trades:
        print("\n  TRADE LOG")
        print("  " + "-" * 70)
        print(f"  {'#':>3}  {'Symbol':<6} {'Dir':<6} {'Entry':>8} {'Exit':>8} "
              f"{'Qty':>5} {'PnL':>10} {'Days':>5}")
        print("  " + "-" * 70)
        for i, t in enumerate(engine.trade_log.trades, 1):
            dir_str = "LONG" if t.direction.value == 1 else "SHORT"
            exit_p = f"{t.exit_price:.2f}" if t.exit_price else "open"
            print(f"  {i:>3}  {t.symbol:<6} {dir_str:<6} {t.entry_price:>8.2f} "
                  f"{exit_p:>8} {t.quantity:>5} ${t.net_pnl:>9,.2f} {t.holding_days:>5}")
        print("  " + "-" * 70)

    # ── 持仓 ──
    print("\n  Open Positions:")
    has_pos = False
    for sym, pos in portfolio.positions.items():
        if pos.quantity != 0:
            has_pos = True
            print(f"    {sym}: {pos.quantity} shares @ ${pos.avg_cost:.2f}")
    if not has_pos:
        print("    (none)")

    # ── 可视化 (带基准对比) ──
    plot_backtest(
        portfolio=portfolio,
        bar_data=engine.bar_data,
        benchmark=bench_portfolio,
        benchmark_label="SPY Buy & Hold",
        title=f"Risk-Managed Breakout ({symbol}) vs SPY — 2022-2024",
        save_path="backtest_risk_managed.png",
        show=False,
    )


if __name__ == "__main__":
    main()
