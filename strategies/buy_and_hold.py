"""
买入持有策略 — 所有策略的对比基准。

规则:
- 第一根 bar 全仓买入
- 之后不动
"""

from engine.strategy.base import BaseStrategy


class BuyAndHold(BaseStrategy):

    def __init__(self, symbol: str, size: int = 100):
        super().__init__()
        self.symbol = symbol
        self.size = size
        self._bought = False

    def on_bar(self) -> None:
        if not self._bought:
            self.buy(self.symbol, self.size)
            self._bought = True
