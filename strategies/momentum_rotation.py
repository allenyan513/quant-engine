"""
动量轮动策略 — 第一个多标的策略。

规则:
- 每 rebalance_period 根 bar 调仓一次
- 计算每个标的过去 lookback_period 的收益率
- 买入涨幅最大的 top_k 只，等权分配
- 卖出不在 top_k 中的持仓
"""

import numpy as np

from engine.strategy.base import BaseStrategy


class MomentumRotation(BaseStrategy):

    def __init__(
        self,
        symbols: list[str],
        lookback_period: int = 60,
        rebalance_period: int = 20,
        top_k: int = 3,
        total_size: int = 300,
    ):
        super().__init__()
        self.symbols = symbols
        self.lookback_period = lookback_period
        self.rebalance_period = rebalance_period
        self.top_k = top_k
        self.size_per_stock = total_size // top_k
        self._bar_count = 0

    def on_bar(self) -> None:
        self._bar_count += 1

        # 只在调仓日操作
        if self._bar_count % self.rebalance_period != 0:
            return

        # 检查所有标的是否有足够数据
        for symbol in self.symbols:
            if not self.bar_data.has_enough_bars(symbol, self.lookback_period):
                return

        # 计算每个标的的动量（过去 N 期收益率）
        momentum: dict[str, float] = {}
        for symbol in self.symbols:
            closes = self.bar_data.history(symbol, "close", self.lookback_period)
            if len(closes) >= 2 and closes[0] != 0:
                momentum[symbol] = (closes[-1] / closes[0]) - 1.0
            else:
                momentum[symbol] = -np.inf

        # 排序，选 top_k
        ranked = sorted(momentum.items(), key=lambda x: x[1], reverse=True)
        winners = set(sym for sym, _ in ranked[:self.top_k])

        # 卖出不在 winners 中的持仓
        for symbol in self.symbols:
            pos = self.get_position(symbol)
            if pos > 0 and symbol not in winners:
                self.sell(symbol, pos)

        # 买入 winners 中还没持仓的
        for symbol in winners:
            pos = self.get_position(symbol)
            if pos == 0:
                self.buy(symbol, self.size_per_stock)
