"""
MACD 交叉策略。

规则:
- MACD 线上穿信号线 → 买入
- MACD 线下穿信号线 → 卖出
- 可选: 只在 MACD > 0（多头区域）时买入，过滤假信号
"""

import numpy as np

from engine.indicators import macd
from engine.strategy.base import BaseStrategy


class MACDCrossover(BaseStrategy):

    def __init__(
        self,
        symbol: str,
        fast_period: int = 12,
        slow_period: int = 26,
        signal_period: int = 9,
        above_zero_only: bool = False,
        size: int = 100,
    ):
        super().__init__()
        self.symbol = symbol
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.signal_period = signal_period
        self.above_zero_only = above_zero_only
        self.size = size
        self._prev_macd: float | None = None
        self._prev_signal: float | None = None

    def on_bar(self) -> None:
        needed = self.slow_period + self.signal_period
        if not self.bar_data.has_enough_bars(self.symbol, needed):
            return

        closes = self.bar_data.history(self.symbol, "close", needed)
        result = macd(closes, self.fast_period, self.slow_period, self.signal_period)

        cur_macd = result.macd_line[-1]
        cur_signal = result.signal_line[-1]

        if np.isnan(cur_macd) or np.isnan(cur_signal):
            return

        pos = self.get_position(self.symbol)

        if self._prev_macd is not None and self._prev_signal is not None:
            # MACD 上穿信号线 → 买入
            if self._prev_macd <= self._prev_signal and cur_macd > cur_signal:
                if self.above_zero_only and cur_macd <= 0:
                    pass  # 过滤: 不在多头区域
                elif pos == 0:
                    self.buy(self.symbol, self.size)

            # MACD 下穿信号线 → 卖出
            elif self._prev_macd >= self._prev_signal and cur_macd < cur_signal:
                if pos > 0:
                    self.sell(self.symbol, pos)

        self._prev_macd = cur_macd
        self._prev_signal = cur_signal
