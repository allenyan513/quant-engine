"""
杠杆反转策略 — TQQQ / SQQQ 双向交易。

核心思路:
  市场趋势向上 → 全仓 TQQQ (3x 做多纳指)
  市场趋势向下 → 全仓 SQQQ (3x 做空纳指)
  信号不明确    → 避险资产 SHY

反转判断信号 (多信号投票机制):
  1. SMA 交叉: 快线 (50) vs 慢线 (200)
  2. MACD: 柱状图方向 + 零轴位置
  3. RSI: 超买/超卖 + 中轴方向
  4. 价格 vs SMA: 收盘价与均线的相对位置
  5. 均线斜率: SMA50 的 N 日变化率

每个信号投 +1 (看多) 或 -1 (看空)，加总后:
  score >= bull_threshold → TQQQ
  score <= bear_threshold → SQQQ
  else → SHY (观望)
"""

import numpy as np

from engine.strategy.base import BaseStrategy
from engine.indicators.trend import sma, ema, macd
from engine.indicators.momentum import rsi


class LeveragedRegime(BaseStrategy):
    """
    杠杆反转策略。

    参数:
        bull_asset:         牛市资产 (默认 TQQQ)
        bear_asset:         熊市资产 (默认 SQQQ)
        safe_asset:         观望资产 (默认 SHY)
        reference:          参考标的 (用于计算指标, 默认 QQQ)
        fast_sma:           快速均线周期
        slow_sma:           慢速均线周期
        rsi_period:         RSI 周期
        macd_params:        MACD 参数 (fast, slow, signal)
        slope_period:       均线斜率计算周期
        bull_threshold:     做多阈值 (>= 此值持有 bull_asset)
        bear_threshold:     做空阈值 (<= 此值持有 bear_asset)
        rebalance_period:   调仓周期
    """

    def __init__(
        self,
        bull_asset: str = "TQQQ",
        bear_asset: str = "SQQQ",
        safe_asset: str = "SHY",
        reference: str = "QQQ",
        fast_sma: int = 50,
        slow_sma: int = 200,
        rsi_period: int = 14,
        macd_params: tuple[int, int, int] = (12, 26, 9),
        slope_period: int = 10,
        bull_threshold: int = 3,
        bear_threshold: int = -3,
        rebalance_period: int = 5,
    ):
        super().__init__()
        self.bull_asset = bull_asset
        self.bear_asset = bear_asset
        self.safe_asset = safe_asset
        self.reference = reference
        self.fast_sma = fast_sma
        self.slow_sma = slow_sma
        self.rsi_period = rsi_period
        self.macd_params = macd_params
        self.slope_period = slope_period
        self.bull_threshold = bull_threshold
        self.bear_threshold = bear_threshold
        self.rebalance_period = rebalance_period

        self._all_symbols = list(set([
            bull_asset, bear_asset, safe_asset, reference,
        ]))
        self._bar_count = 0
        self._current_holding: str | None = None
        self._min_bars = slow_sma + slope_period + 10

    @property
    def all_symbols(self) -> list[str]:
        return list(self._all_symbols)

    def on_bar(self) -> None:
        self._bar_count += 1

        if self._bar_count % self.rebalance_period != 0:
            return

        if not self.bar_data.has_enough_bars(self.reference, self._min_bars):
            return

        # 计算综合信号得分
        score = self._calculate_score()

        # 决定目标持仓
        if score >= self.bull_threshold:
            target = self.bull_asset
        elif score <= self.bear_threshold:
            target = self.bear_asset
        else:
            target = self.safe_asset

        # 持仓不变则不操作
        if target == self._current_holding:
            return

        # 切换持仓
        self._switch_to(target)

    def _calculate_score(self) -> int:
        """
        多信号投票，返回综合得分。

        范围: -5 (极度看空) 到 +5 (极度看多)
        """
        closes = self.bar_data.history(self.reference, "close", self._min_bars)

        score = 0

        # ── Signal 1: SMA 交叉 ──────────────────────────────
        sma_fast = sma(closes, self.fast_sma)
        sma_slow = sma(closes, self.slow_sma)

        if not np.isnan(sma_fast[-1]) and not np.isnan(sma_slow[-1]):
            if sma_fast[-1] > sma_slow[-1]:
                score += 1  # 金叉
            else:
                score -= 1  # 死叉

        # ── Signal 2: 价格 vs SMA200 ────────────────────────
        if not np.isnan(sma_slow[-1]):
            if closes[-1] > sma_slow[-1]:
                score += 1
            else:
                score -= 1

        # ── Signal 3: MACD 柱状图 ───────────────────────────
        macd_result = macd(closes, *self.macd_params)
        hist = macd_result.histogram

        if not np.isnan(hist[-1]):
            if hist[-1] > 0:
                score += 1  # 多头动量
            else:
                score -= 1  # 空头动量

        # ── Signal 4: RSI 方向 ──────────────────────────────
        rsi_values = rsi(closes, self.rsi_period)

        if not np.isnan(rsi_values[-1]):
            if rsi_values[-1] > 50:
                score += 1  # 多头区域
            else:
                score -= 1  # 空头区域

        # ── Signal 5: SMA50 斜率 ────────────────────────────
        if (not np.isnan(sma_fast[-1])
                and not np.isnan(sma_fast[-1 - self.slope_period])):
            slope = (sma_fast[-1] / sma_fast[-1 - self.slope_period]) - 1
            if slope > 0.01:  # 上升 > 1%
                score += 1
            elif slope < -0.01:  # 下降 > 1%
                score -= 1

        return score

    def _switch_to(self, target: str) -> None:
        """切换到目标资产。"""
        # 卖掉当前持仓
        if self._current_holding:
            pos = self.get_position(self._current_holding)
            if pos > 0:
                self.sell(self._current_holding, pos)

        # 买入新标的
        bar = self.bar_data.current(target)
        if bar and bar.close > 0:
            available = self.portfolio.equity * 0.98
            qty = int(available / bar.close)
            if qty > 0:
                self.buy(target, qty)
                self._current_holding = target

    def _has_enough_data(self) -> bool:
        for symbol in self._all_symbols:
            if not self.bar_data.has_enough_bars(symbol, self._min_bars):
                return False
        return True
