"""
唐奇安通道突破策略（海龟交易法简化版）。

规则:
- 价格突破 entry_period 日最高价 → 买入
- 价格跌破 exit_period 日最低价 → 卖出
- 用 ATR 做止损参考
"""

from engine.indicators import donchian, atr
from engine.strategy.base import BaseStrategy


class DonchianBreakout(BaseStrategy):

    def __init__(
        self,
        symbol: str,
        entry_period: int = 20,
        exit_period: int = 10,
        size: int = 100,
    ):
        super().__init__()
        self.symbol = symbol
        self.entry_period = entry_period
        self.exit_period = exit_period
        self.size = size

    def on_bar(self) -> None:
        needed = self.entry_period + 1
        if not self.bar_data.has_enough_bars(self.symbol, needed):
            return

        bar = self.bar_data.current(self.symbol)
        pos = self.get_position(self.symbol)

        highs = self.bar_data.history(self.symbol, "high", needed)
        lows = self.bar_data.history(self.symbol, "low", needed)

        # 入场通道: 用 entry_period 算（不含当前 bar → 用 [:-1]）
        entry_ch = donchian(highs[:-1], lows[:-1], self.entry_period)
        entry_upper = entry_ch.upper[-1]

        # 离场通道: 用 exit_period 算
        if len(highs) > self.exit_period:
            exit_ch = donchian(highs[:-1], lows[:-1], self.exit_period)
            exit_lower = exit_ch.lower[-1]
        else:
            exit_lower = None

        # 突破上轨 → 买入
        if pos == 0 and bar.close > entry_upper:
            self.buy(self.symbol, self.size)

        # 跌破下轨 → 卖出
        elif pos > 0 and exit_lower is not None and bar.close < exit_lower:
            self.sell(self.symbol, pos)
