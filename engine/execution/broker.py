"""
SimulatedBroker — 模拟撮合引擎。

Phase 1: 简单市价单撮合（以下一根 bar 的 open 成交）。
后续: 滑点模型、限价单、部分成交。
"""

from __future__ import annotations

from engine.core.bar_data import BarData
from engine.core.event import Direction, FillEvent, OrderEvent, OrderType


class SimulatedBroker:
    """模拟经纪商。"""

    def __init__(
        self,
        commission_rate: float = 0.001,  # 0.1% 手续费
        slippage_rate: float = 0.0005,   # 0.05% 滑点
    ) -> None:
        self.commission_rate = commission_rate
        self.slippage_rate = slippage_rate
        self._pending_orders: list[OrderEvent] = []

    def submit_order(self, order: OrderEvent) -> None:
        """提交订单（下一根 bar 撮合）。"""
        self._pending_orders.append(order)

    def fill_orders(self, bar_data: BarData) -> list[FillEvent]:
        """
        尝试撮合所有待处理订单。

        市价单: 以当前 bar 的 open 价 + 滑点成交。
        """
        fills: list[FillEvent] = []
        remaining: list[OrderEvent] = []

        for order in self._pending_orders:
            bar = bar_data.current(order.symbol)
            if bar is None:
                remaining.append(order)
                continue

            if order.order_type == OrderType.MARKET:
                # 市价单以 open 价成交 + 滑点
                base_price = bar.open
                if order.direction == Direction.LONG:
                    fill_price = base_price * (1 + self.slippage_rate)
                else:
                    fill_price = base_price * (1 - self.slippage_rate)

                commission = fill_price * order.quantity * self.commission_rate

                fills.append(FillEvent(
                    symbol=order.symbol,
                    direction=order.direction,
                    quantity=order.quantity,
                    fill_price=fill_price,
                    commission=commission,
                    timestamp=bar.timestamp,
                ))
            elif order.order_type == OrderType.LIMIT:
                # Phase 1 先不实现限价单
                remaining.append(order)

        self._pending_orders = remaining
        return fills

    @property
    def pending_count(self) -> int:
        return len(self._pending_orders)
