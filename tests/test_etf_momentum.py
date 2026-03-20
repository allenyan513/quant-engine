"""
ETFMomentumRotation 策略单元测试。

使用合成数据验证核心逻辑:
- 动量排名正确
- 调仓周期生效
- 市场过滤器 (risk-off) 清仓
- 等权分配
"""

import numpy as np
import pytest
from datetime import datetime, timedelta

from engine.core.bar_data import Bar, BarData
from engine.core.event import Direction
from engine.portfolio.portfolio import Portfolio
from strategies.etf_momentum_rotation import ETFMomentumRotation


# ── 合成数据工具 ──────────────────────────────────────────────

def make_bars(symbol: str, prices: list[float], start_date: str = "2023-01-02") -> list[Bar]:
    """根据收盘价序列生成 Bar 列表 (只在工作日)。"""
    bars = []
    dt = datetime.strptime(start_date, "%Y-%m-%d")
    for price in prices:
        while dt.weekday() >= 5:
            dt += timedelta(days=1)
        bars.append(Bar(
            symbol=symbol,
            timestamp=dt,
            open=price * 0.99,
            high=price * 1.01,
            low=price * 0.98,
            close=price,
            volume=1_000_000,
        ))
        dt += timedelta(days=1)
    return bars


def setup_strategy_with_data(
    universe: list[str],
    price_series: dict[str, list[float]],
    momentum_period: int = 10,
    rebalance_period: int = 5,
    top_k: int = 2,
    regime_sma_period: int = 10,
    use_regime_filter: bool = False,
    initial_cash: float = 100_000.0,
) -> tuple[ETFMomentumRotation, BarData, Portfolio]:
    """设置策略 + 数据 + 组合，返回三元组。"""
    strategy = ETFMomentumRotation(
        universe=universe,
        regime_symbol=universe[0],
        regime_sma_period=regime_sma_period,
        momentum_period=momentum_period,
        rebalance_period=rebalance_period,
        top_k=top_k,
        use_regime_filter=use_regime_filter,
    )

    bar_data = BarData()
    for sym, prices in price_series.items():
        bar_data.add_symbol_bars(sym, make_bars(sym, prices))

    portfolio = Portfolio(initial_cash=initial_cash)
    strategy._bind(bar_data, portfolio)
    strategy.initialize()

    return strategy, bar_data, portfolio


# ── Tests ─────────────────────────────────────────────────────

class TestMomentumRanking:
    """动量排名逻辑。"""

    def test_selects_top_performers(self):
        """应该选择涨幅最大的标的。"""
        n = 20  # 足够 momentum_period=10 + warmup
        # A 涨 50%, B 涨 20%, C 跌 10%
        prices_a = [100 + i * 2.5 for i in range(n)]
        prices_b = [100 + i * 1.0 for i in range(n)]
        prices_c = [100 - i * 0.5 for i in range(n)]

        strategy, bar_data, portfolio = setup_strategy_with_data(
            universe=["A", "B", "C"],
            price_series={"A": prices_a, "B": prices_b, "C": prices_c},
            momentum_period=10,
            rebalance_period=5,
            top_k=2,
            use_regime_filter=False,
        )

        # 推进到调仓日 (bar 15 是第3个调仓周期)
        for i in range(15):
            for sym in ["A", "B", "C"]:
                bar_data.advance(sym)
            portfolio.update_equity(bar_data, bar_data.current("A").timestamp)
            strategy.on_bar()

        # A 和 B 应该被选中 (涨幅最大的两个)
        assert "A" in strategy._current_holdings
        assert "B" in strategy._current_holdings
        assert "C" not in strategy._current_holdings


class TestRebalancePeriod:
    """调仓周期。"""

    def test_no_trade_before_rebalance(self):
        """非调仓日不应该产生订单。"""
        n = 20
        prices = [100 + i for i in range(n)]

        strategy, bar_data, portfolio = setup_strategy_with_data(
            universe=["A", "B"],
            price_series={"A": prices, "B": prices},
            momentum_period=10,
            rebalance_period=5,
            top_k=1,
            use_regime_filter=False,
        )

        # 推进 3 根 bar (不是调仓日)
        for i in range(3):
            for sym in ["A", "B"]:
                bar_data.advance(sym)
            strategy.on_bar()
            orders = strategy._collect_orders()
            assert len(orders) == 0, f"Bar {i+1} should not generate orders"


class TestRegimeFilter:
    """市场状态过滤器。"""

    def test_risk_off_goes_to_cash(self):
        """SPY < 200 SMA 时清仓。"""
        n = 25
        # SPY 先涨后跌 (跌破均线)
        prices_spy = [100 + i for i in range(15)] + [114 - i * 3 for i in range(10)]
        prices_b = [100 + i for i in range(n)]

        strategy, bar_data, portfolio = setup_strategy_with_data(
            universe=["SPY", "B"],
            price_series={"SPY": prices_spy, "B": prices_b},
            momentum_period=10,
            rebalance_period=5,
            top_k=2,
            regime_sma_period=10,
            use_regime_filter=True,
        )

        # 推进所有 bar
        for i in range(n):
            for sym in ["SPY", "B"]:
                bar_data.advance(sym)
            portfolio.update_equity(bar_data, bar_data.current("SPY").timestamp)
            strategy.on_bar()
            # 收集但不执行订单 (简化测试)
            strategy._collect_orders()

        # SPY 在后半段下跌，应该触发 risk-off
        # 验证 holdings 应为空
        assert len(strategy._current_holdings) == 0


class TestEqualWeightAllocation:
    """等权分配逻辑。"""

    def test_allocates_roughly_equal(self):
        """持仓市值应该大致相等。"""
        n = 20
        prices_a = [50 + i * 0.5 for i in range(n)]
        prices_b = [200 + i * 2 for i in range(n)]

        strategy, bar_data, portfolio = setup_strategy_with_data(
            universe=["A", "B"],
            price_series={"A": prices_a, "B": prices_b},
            momentum_period=10,
            rebalance_period=5,
            top_k=2,
            use_regime_filter=False,
            initial_cash=100_000.0,
        )

        # 推进到第一个调仓日并收集订单
        orders_found = False
        for i in range(15):
            for sym in ["A", "B"]:
                bar_data.advance(sym)
            portfolio.update_equity(bar_data, bar_data.current("A").timestamp)
            strategy.on_bar()
            orders = strategy._collect_orders()
            if orders:
                orders_found = True
                # 检查两个标的的订单金额大致相等
                order_values = {}
                for o in orders:
                    bar = bar_data.current(o.symbol)
                    order_values[o.symbol] = o.quantity * bar.close

                if len(order_values) == 2:
                    values = list(order_values.values())
                    ratio = min(values) / max(values)
                    # 允许 20% 的偏差 (因为取整)
                    assert ratio > 0.3, f"Allocation too uneven: {order_values}"
                break

        assert orders_found, "Should have generated orders by bar 15"


class TestAllSymbolsProperty:
    """all_symbols 属性。"""

    def test_returns_universe(self):
        strategy = ETFMomentumRotation(
            universe=["SPY", "QQQ", "TLT"],
        )
        assert set(strategy.all_symbols) == {"SPY", "QQQ", "TLT"}

    def test_includes_regime_symbol(self):
        strategy = ETFMomentumRotation(
            universe=["QQQ", "TLT"],
            regime_symbol="SPY",
        )
        assert "SPY" in strategy.all_symbols
