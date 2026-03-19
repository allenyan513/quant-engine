"""
SMA 均线交叉策略 — Phase 1 示例。

规则:
- 短期均线上穿长期均线 → 买入
- 短期均线下穿长期均线 → 卖出
"""

from engine.strategy.base import BaseStrategy


class SMACrossover(BaseStrategy):

    def __init__(self, symbol: str, fast_period: int = 10, slow_period: int = 30, size: int = 100):
        super().__init__()
        self.symbol = symbol
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.size = size  # 每次交易的股数
        self._prev_fast: float | None = None
        self._prev_slow: float | None = None

    def on_bar(self) -> None:
        if not self.bar_data.has_enough_bars(self.symbol, self.slow_period):
            return

        fast = self.bar_data.history(self.symbol, "close", self.fast_period).mean()
        slow = self.bar_data.history(self.symbol, "close", self.slow_period).mean()

        pos = self.get_position(self.symbol)

        if self._prev_fast is not None and self._prev_slow is not None:
            # 金叉: 短期从下方穿越长期
            if self._prev_fast <= self._prev_slow and fast > slow:
                if pos == 0:
                    self.buy(self.symbol, self.size)

            # 死叉: 短期从上方穿越长期
            elif self._prev_fast >= self._prev_slow and fast < slow:
                if pos > 0:
                    self.sell(self.symbol, pos)

        self._prev_fast = fast
        self._prev_slow = slow
