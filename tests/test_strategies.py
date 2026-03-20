"""新策略测试 — 用构造数据验证买卖逻辑。"""

import pytest

from engine.engine import BacktestEngine
from tests.helpers import MockDataFeed, make_bars

from strategies.buy_and_hold import BuyAndHold
from strategies.bollinger_reversion import BollingerReversion
from strategies.macd_crossover import MACDCrossover
from strategies.momentum_rotation import MomentumRotation


# =========================================================================
# BuyAndHold
# =========================================================================

class TestBuyAndHold:
    def test_buys_once(self):
        prices = [100.0, 110.0, 120.0, 130.0, 140.0]
        feed = MockDataFeed({"X": make_bars("X", prices)})
        strategy = BuyAndHold("X", size=100)

        engine = BacktestEngine(
            strategy=strategy, data_feed=feed,
            symbols=["X"], start="2024-01-01", end="2024-12-31",
            initial_cash=100_000.0, commission_rate=0.0, slippage_rate=0.0,
        )
        portfolio = engine.run()

        assert portfolio.get_position_quantity("X") == 100

    def test_equity_tracks_underlying(self):
        """上涨行情 → 净值应增加。"""
        prices = [100.0, 110.0, 120.0, 130.0, 140.0]
        feed = MockDataFeed({"X": make_bars("X", prices)})
        strategy = BuyAndHold("X", size=100)

        engine = BacktestEngine(
            strategy=strategy, data_feed=feed,
            symbols=["X"], start="2024-01-01", end="2024-12-31",
            initial_cash=100_000.0, commission_rate=0.0, slippage_rate=0.0,
        )
        portfolio = engine.run()

        assert portfolio.equity > 100_000.0

    def test_never_sells(self):
        """下跌行情也不卖。"""
        prices = [100.0, 90.0, 80.0, 70.0, 60.0]
        feed = MockDataFeed({"X": make_bars("X", prices)})
        strategy = BuyAndHold("X", size=100)

        engine = BacktestEngine(
            strategy=strategy, data_feed=feed,
            symbols=["X"], start="2024-01-01", end="2024-12-31",
            initial_cash=100_000.0, commission_rate=0.0, slippage_rate=0.0,
        )
        portfolio = engine.run()

        assert portfolio.get_position_quantity("X") == 100
        assert portfolio.realized_pnl == 0.0


# =========================================================================
# BollingerReversion
# =========================================================================

class TestBollingerReversion:
    def test_buys_when_price_drops_below_lower_band(self):
        """构造先稳后暴跌的数据，触发下轨买入。"""
        # 20 根稳定在 100，然后暴跌到 80
        prices = [100.0] * 20 + [80.0, 85.0, 90.0, 95.0, 100.0]
        feed = MockDataFeed({"X": make_bars("X", prices)})
        strategy = BollingerReversion("X", period=20, num_std=2.0, size=100)

        engine = BacktestEngine(
            strategy=strategy, data_feed=feed,
            symbols=["X"], start="2024-01-01", end="2024-12-31",
            initial_cash=100_000.0, commission_rate=0.0, slippage_rate=0.0,
        )
        portfolio = engine.run()

        # 暴跌后应触发买入
        # 可能已经在回归中轨时卖出了，所以检查有过交易
        assert portfolio.realized_pnl != 0.0 or portfolio.get_position_quantity("X") > 0

    def test_no_trade_in_stable_market(self):
        """价格一直在布林带内 → 不交易。"""
        # 微幅波动不足以触碰布林带
        prices = [100.0 + i * 0.01 for i in range(30)]
        feed = MockDataFeed({"X": make_bars("X", prices)})
        strategy = BollingerReversion("X", period=20, num_std=2.0, size=100)

        engine = BacktestEngine(
            strategy=strategy, data_feed=feed,
            symbols=["X"], start="2024-01-01", end="2024-12-31",
            initial_cash=100_000.0, commission_rate=0.0, slippage_rate=0.0,
        )
        portfolio = engine.run()

        assert portfolio.get_position_quantity("X") == 0


# =========================================================================
# MACDCrossover
# =========================================================================

class TestMACDCrossover:
    def test_buys_on_uptrend(self):
        """持续上涨 → MACD 应产生买入信号。"""
        prices = [50.0 - i * 0.3 for i in range(40)] + [30.0 + i * 1.0 for i in range(30)]
        feed = MockDataFeed({"X": make_bars("X", prices)})
        strategy = MACDCrossover("X", fast_period=12, slow_period=26, signal_period=9, size=100)

        engine = BacktestEngine(
            strategy=strategy, data_feed=feed,
            symbols=["X"], start="2024-01-01", end="2024-12-31",
            initial_cash=100_000.0, commission_rate=0.0, slippage_rate=0.0,
        )
        portfolio = engine.run()

        assert portfolio.get_position_quantity("X") > 0

    def test_above_zero_filter(self):
        """above_zero_only=True 时，MACD<0 区域的金叉被过滤。"""
        # 从高到低再小幅反弹（MACD 仍 <0）
        prices = [100.0 - i * 1.0 for i in range(40)] + [62.0 + i * 0.3 for i in range(20)]
        feed = MockDataFeed({"X": make_bars("X", prices)})
        strategy = MACDCrossover(
            "X", fast_period=12, slow_period=26, signal_period=9,
            above_zero_only=True, size=100,
        )

        engine = BacktestEngine(
            strategy=strategy, data_feed=feed,
            symbols=["X"], start="2024-01-01", end="2024-12-31",
            initial_cash=100_000.0, commission_rate=0.0, slippage_rate=0.0,
        )
        portfolio = engine.run()

        # 小幅反弹不足以使 MACD>0，不应买入
        assert portfolio.get_position_quantity("X") == 0

    def test_no_trade_with_insufficient_data(self):
        prices = [100.0 + i for i in range(10)]
        feed = MockDataFeed({"X": make_bars("X", prices)})
        strategy = MACDCrossover("X", size=100)

        engine = BacktestEngine(
            strategy=strategy, data_feed=feed,
            symbols=["X"], start="2024-01-01", end="2024-12-31",
            initial_cash=100_000.0,
        )
        portfolio = engine.run()

        assert portfolio.get_position_quantity("X") == 0


# =========================================================================
# MomentumRotation
# =========================================================================

class TestMomentumRotation:
    def test_buys_top_performers(self):
        """涨最多的标的应被买入。"""
        # A 涨, B 跌, C 平
        n = 80
        prices_a = [100.0 + i * 1.0 for i in range(n)]  # 稳定上涨
        prices_b = [100.0 - i * 0.5 for i in range(n)]  # 稳定下跌
        prices_c = [100.0 + (i % 5) * 0.1 for i in range(n)]  # 横盘

        feed = MockDataFeed({
            "A": make_bars("A", prices_a),
            "B": make_bars("B", prices_b),
            "C": make_bars("C", prices_c),
        })
        strategy = MomentumRotation(
            symbols=["A", "B", "C"],
            lookback_period=60,
            rebalance_period=20,
            top_k=1,
            total_size=100,
        )

        engine = BacktestEngine(
            strategy=strategy, data_feed=feed,
            symbols=["A", "B", "C"], start="2024-01-01", end="2024-12-31",
            initial_cash=100_000.0, commission_rate=0.0, slippage_rate=0.0,
        )
        portfolio = engine.run()

        # A 涨最多，应持有 A
        assert portfolio.get_position_quantity("A") > 0
        assert portfolio.get_position_quantity("B") == 0

    def test_rotation_switches_holdings(self):
        """前半段 B 涨，后半段 A 涨 → 应从 B 换到 A。"""
        n = 120
        # A: 前60根跌，后60根涨
        prices_a = [100.0 - i * 0.3 for i in range(60)] + [82.0 + i * 1.5 for i in range(60)]
        # B: 前60根涨，后60根跌
        prices_b = [100.0 + i * 1.5 for i in range(60)] + [190.0 - i * 0.3 for i in range(60)]

        feed = MockDataFeed({
            "A": make_bars("A", prices_a),
            "B": make_bars("B", prices_b),
        })
        strategy = MomentumRotation(
            symbols=["A", "B"],
            lookback_period=40,
            rebalance_period=20,
            top_k=1,
            total_size=100,
        )

        engine = BacktestEngine(
            strategy=strategy, data_feed=feed,
            symbols=["A", "B"], start="2024-01-01", end="2024-12-31",
            initial_cash=100_000.0, commission_rate=0.0, slippage_rate=0.0,
        )
        portfolio = engine.run()

        # 最终应持有 A（后半段涨幅大）
        assert portfolio.get_position_quantity("A") > 0

    def test_no_trade_before_enough_data(self):
        prices = [100.0 + i for i in range(30)]
        feed = MockDataFeed({
            "A": make_bars("A", prices),
            "B": make_bars("B", prices),
        })
        strategy = MomentumRotation(
            symbols=["A", "B"], lookback_period=60, rebalance_period=20, top_k=1,
        )

        engine = BacktestEngine(
            strategy=strategy, data_feed=feed,
            symbols=["A", "B"], start="2024-01-01", end="2024-12-31",
            initial_cash=100_000.0,
        )
        portfolio = engine.run()

        assert portfolio.get_position_quantity("A") == 0
        assert portfolio.get_position_quantity("B") == 0
