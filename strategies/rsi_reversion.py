"""
RSI 均值回归策略。

规则:
- RSI < oversold → 超卖，买入
- RSI > overbought → 超买，卖出
- 用 ATR 计算仓位大小（风险控制）
"""

from engine.indicators import rsi, atr
from engine.strategy.base import BaseStrategy


class RSIReversion(BaseStrategy):

    def __init__(
        self,
        symbol: str,
        period: int = 14,
        oversold: float = 30.0,
        overbought: float = 70.0,
        size: int = 100,
    ):
        super().__init__()
        self.symbol = symbol
        self.period = period
        self.oversold = oversold
        self.overbought = overbought
        self.size = size

    def on_bar(self) -> None:
        needed = self.period + 1
        if not self.bar_data.has_enough_bars(self.symbol, needed):
            return

        closes = self.bar_data.history(self.symbol, "close", needed)
        rsi_values = rsi(closes, self.period)
        current_rsi = rsi_values[-1]

        pos = self.get_position(self.symbol)

        # 超卖 → 买入
        if current_rsi < self.oversold and pos == 0:
            self.buy(self.symbol, self.size)

        # 超买 → 卖出
        elif current_rsi > self.overbought and pos > 0:
            self.sell(self.symbol, pos)
