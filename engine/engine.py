"""
BacktestEngine — 主事件循环。

职责:
1. 加载数据 → BarData
2. 逐 bar 推进时间
3. 驱动 Strategy → Broker → Portfolio 的事件流转
"""

from __future__ import annotations

from datetime import datetime

from engine.analytics.metrics import TradeLog
from engine.core.bar_data import Bar, BarData
from engine.data.data_feed import DataFeed
from engine.execution.broker import SimulatedBroker
from engine.portfolio.portfolio import Portfolio
from engine.strategy.base import BaseStrategy


class BacktestEngine:
    """回测引擎。"""

    def __init__(
        self,
        strategy: BaseStrategy,
        data_feed: DataFeed,
        symbols: list[str],
        start: str,
        end: str,
        initial_cash: float = 100_000.0,
        commission_rate: float = 0.001,
        slippage_rate: float = 0.0005,
    ) -> None:
        self.strategy = strategy
        self.data_feed = data_feed
        self.symbols = symbols
        self.start = start
        self.end = end

        self.bar_data = BarData()
        self.portfolio = Portfolio(initial_cash=initial_cash)
        self.trade_log = TradeLog()
        self.broker = SimulatedBroker(
            commission_rate=commission_rate,
            slippage_rate=slippage_rate,
        )

    def run(self) -> Portfolio:
        """
        运行回测，返回 Portfolio。

        流程:
        1. 加载所有标的数据到 BarData
        2. 绑定策略
        3. 逐 bar 循环:
           a. 推进数据
           b. 撮合待处理订单（上一轮的）
           c. 更新组合净值
           d. 调用策略 on_bar()
           e. 收集策略产生的订单提交给 Broker
        """
        # Step 1: 加载数据
        print(f"Loading data for {self.symbols}...")
        for symbol in self.symbols:
            bars = self.data_feed.fetch(symbol, self.start, self.end)
            self.bar_data.add_symbol_bars(symbol, bars)
            print(f"  {symbol}: {len(bars)} bars loaded")

        # Step 2: 绑定
        self.strategy._bind(self.bar_data, self.portfolio)
        self.strategy.initialize()

        # Step 3: 事件循环
        # 找出所有标的的最大 bar 数量来确定循环次数
        max_bars = max(
            len(self.bar_data._bars[s]) for s in self.symbols
        )

        print(f"Running backtest: {max_bars} bars...")

        for i in range(max_bars):
            # 3a. 推进所有标的的数据
            current_bars: dict[str, Bar] = {}
            for symbol in self.symbols:
                bar = self.bar_data.advance(symbol)
                if bar is not None:
                    current_bars[symbol] = bar

            if not current_bars:
                break

            # 3b. 撮合上一轮的待处理订单
            fills = self.broker.fill_orders(self.bar_data)
            for fill in fills:
                self.portfolio.on_fill(fill)
                self.trade_log.on_fill(fill)
                self.strategy.on_fill(fill)

            # 3c. 更新组合净值
            timestamp = list(current_bars.values())[0].timestamp
            self.portfolio.update_equity(self.bar_data, timestamp)

            # 3d. 检查止损管理器
            stop_orders = self.strategy._collect_stop_orders()
            for order in stop_orders:
                self.broker.submit_order(order)

            # 3e. 调用策略
            self.strategy.on_bar()

            # 3f. 收集订单
            orders = self.strategy._collect_orders()
            for order in orders:
                self.broker.submit_order(order)

        # 处理最后的待处理订单
        print(f"Backtest complete. Final equity: ${self.portfolio.equity:,.2f}")
        return self.portfolio
