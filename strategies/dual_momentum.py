"""
双动量策略 (Dual Momentum) — 绝对动量 + 相对动量。

核心规则:
1. 相对动量: 在攻击性资产池 (QQQ, SPY, IWM) 中选过去 lookback 期涨幅最大的
2. 绝对动量: 该资产回报 > 0 (趋势向上) → 持有; 否则 → 避险资产 (SHY/TLT)
3. 市场过滤: SPY < 200 SMA → 强制切换到避险资产
4. 每月调仓一次

为什么能跑赢 SPY:
- 牛市中自动集中到最强资产 (QQQ 在 2015-2024 涨 ~500%)
- 熊市中切换到债券避险 (避开 2022 的 -33%)
- 不分散到弱势跨资产类别

参考:
- Antonacci, G. "Dual Momentum Investing" (2014)
- 改良版: 加入 200 SMA 过滤器 + 多级避险
"""

from engine.strategy.base import BaseStrategy
from engine.indicators.trend import sma


# 攻击性资产池 — 全部是美股，不分散到弱资产
OFFENSIVE_ASSETS = ["QQQ", "SPY", "IWM"]

# 避险资产
DEFENSIVE_ASSET = "SHY"  # 短期国债，熊市避风港


class DualMomentum(BaseStrategy):
    """
    双动量策略。

    参数:
        offensive:        攻击性资产列表
        defensive:        避险资产
        regime_symbol:    市场状态判断标的
        regime_sma:       市场状态 SMA 周期
        momentum_period:  动量计算周期 (默认 126 天 ≈ 6 个月)
        rebalance_period: 调仓周期 (默认 21 天 ≈ 1 个月)
    """

    def __init__(
        self,
        offensive: list[str] | None = None,
        defensive: str = DEFENSIVE_ASSET,
        regime_symbol: str = "SPY",
        regime_sma: int = 200,
        momentum_period: int = 126,
        rebalance_period: int = 21,
    ):
        super().__init__()
        self.offensive = offensive or list(OFFENSIVE_ASSETS)
        self.defensive = defensive
        self.regime_symbol = regime_symbol
        self.regime_sma = regime_sma
        self.momentum_period = momentum_period
        self.rebalance_period = rebalance_period

        # 所有需要的标的
        self._all_symbols: list[str] = list(set(
            self.offensive + [self.defensive, self.regime_symbol]
        ))

        self._bar_count = 0
        self._current_holding: str | None = None
        self._min_bars = max(self.momentum_period, self.regime_sma)

    @property
    def all_symbols(self) -> list[str]:
        return list(self._all_symbols)

    def on_bar(self) -> None:
        self._bar_count += 1

        if self._bar_count % self.rebalance_period != 0:
            return

        if not self._has_enough_data():
            return

        # Step 1: 确定目标持仓
        target = self._select_target()

        # Step 2: 如果目标和当前持仓一样，不动
        if target == self._current_holding:
            return

        # Step 3: 卖掉旧持仓
        if self._current_holding:
            pos = self.get_position(self._current_holding)
            if pos > 0:
                self.sell(self._current_holding, pos)

        # Step 4: 买入新目标 (全仓, 留 2% 现金缓冲)
        bar = self.bar_data.current(target)
        if bar and bar.close > 0:
            available = self.portfolio.equity * 0.98
            qty = int(available / bar.close)
            if qty > 0:
                self.buy(target, qty)
                self._current_holding = target

    def _select_target(self) -> str:
        """
        选择目标持仓。

        决策树:
        1. 在攻击性资产中选动量最强的
        2. 该资产自身 < 200 SMA (趋势向下) → 避险资产 (绝对动量)
        3. 该资产过去 momentum_period 回报 < 0 → 避险资产
        4. 否则 → 持有最强资产
        """
        # 计算各攻击性资产的动量
        best_symbol = None
        best_momentum = -float("inf")

        for symbol in self.offensive:
            closes = self.bar_data.history(symbol, "close", self.momentum_period)
            if len(closes) < self.momentum_period:
                continue
            ret = (closes[-1] / closes[0]) - 1.0

            if ret > best_momentum:
                best_momentum = ret
                best_symbol = symbol

        if best_symbol is None:
            return self.defensive

        # 绝对动量过滤: 最强资产也必须处于上升趋势
        closes = self.bar_data.history(best_symbol, "close", self.regime_sma)
        if len(closes) >= self.regime_sma:
            sma_val = sma(closes, self.regime_sma)
            if closes[-1] < sma_val[-1]:
                return self.defensive

        # 回报必须 > 0
        if best_momentum <= 0:
            return self.defensive

        return best_symbol

    def _has_enough_data(self) -> bool:
        for symbol in self._all_symbols:
            if not self.bar_data.has_enough_bars(symbol, self._min_bars):
                return False
        return True
