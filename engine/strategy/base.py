"""
BaseStrategy — 所有策略的基类。

用户继承这个类，实现 initialize() 和 on_bar()。
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from engine.core.bar_data import BarData
from engine.core.event import Direction, FillEvent, OrderEvent, OrderType, SignalEvent
from engine.portfolio.portfolio import Portfolio


class BaseStrategy(ABC):
    """策略基类。"""

    def __init__(self) -> None:
        self._bar_data: BarData | None = None
        self._portfolio: Portfolio | None = None
        self._signals: list[SignalEvent] = []
        self._pending_orders: list[OrderEvent] = []

    def _bind(self, bar_data: BarData, portfolio: Portfolio) -> None:
        """引擎调用，绑定数据和组合。"""
        self._bar_data = bar_data
        self._portfolio = portfolio

    @property
    def bar_data(self) -> BarData:
        assert self._bar_data is not None
        return self._bar_data

    @property
    def portfolio(self) -> Portfolio:
        assert self._portfolio is not None
        return self._portfolio

    def initialize(self) -> None:
        """策略初始化（可选覆盖）。"""
        pass

    @abstractmethod
    def on_bar(self) -> None:
        """每根 bar 调用一次 — 核心逻辑在这里。"""
        ...

    def on_fill(self, fill: FillEvent) -> None:
        """成交回报回调（可选覆盖）。"""
        pass

    # -----------------------------------------------------------------------
    # 策略便捷方法
    # -----------------------------------------------------------------------

    def buy(self, symbol: str, quantity: int) -> None:
        """发出买入信号。"""
        self._signals.append(SignalEvent(
            symbol=symbol,
            direction=Direction.LONG,
        ))
        self._pending_orders.append(OrderEvent(
            symbol=symbol,
            direction=Direction.LONG,
            quantity=quantity,
            order_type=OrderType.MARKET,
        ))

    def sell(self, symbol: str, quantity: int) -> None:
        """发出卖出信号。"""
        self._signals.append(SignalEvent(
            symbol=symbol,
            direction=Direction.SHORT,
        ))
        self._pending_orders.append(OrderEvent(
            symbol=symbol,
            direction=Direction.SHORT,
            quantity=quantity,
            order_type=OrderType.MARKET,
        ))

    def get_position(self, symbol: str) -> int:
        """查询当前持仓。"""
        return self.portfolio.get_position_quantity(symbol)

    def _collect_orders(self) -> list[OrderEvent]:
        """引擎调用，收集本次 bar 产生的订单。"""
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders
