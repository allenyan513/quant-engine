"""
布林带均值回归策略。

规则:
- 价格跌破下轨 → 买入（超卖反弹）
- 价格突破上轨 → 卖出（超买回落）
- 可选: 价格回归中轨时平仓
"""

from engine.indicators import bollinger
from engine.strategy.base import BaseStrategy


class BollingerReversion(BaseStrategy):

    def __init__(
        self,
        symbol: str,
        period: int = 20,
        num_std: float = 2.0,
        exit_at_middle: bool = True,
        size: int = 100,
    ):
        super().__init__()
        self.symbol = symbol
        self.period = period
        self.num_std = num_std
        self.exit_at_middle = exit_at_middle
        self.size = size

    def on_bar(self) -> None:
        if not self.bar_data.has_enough_bars(self.symbol, self.period):
            return

        closes = self.bar_data.history(self.symbol, "close", self.period)
        bands = bollinger(closes, self.period, self.num_std)

        price = closes[-1]
        upper = bands.upper[-1]
        middle = bands.middle[-1]
        lower = bands.lower[-1]

        pos = self.get_position(self.symbol)

        # 跌破下轨 → 买入
        if price < lower and pos == 0:
            self.buy(self.symbol, self.size)

        elif pos > 0:
            if self.exit_at_middle:
                # 回归中轨 → 平仓
                if price >= middle:
                    self.sell(self.symbol, pos)
            else:
                # 突破上轨 → 平仓
                if price > upper:
                    self.sell(self.symbol, pos)
