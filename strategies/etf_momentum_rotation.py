"""
ETF 动量轮动策略 — 带市场状态过滤器。

核心规则:
1. 宇宙: 10-20 只 ETF，覆盖美股/国际/债券/商品
2. 每月调仓: 按过去 momentum_period 天回报率排序
3. 买入 top_k 只，等权分配 (按 dollar value)
4. 市场状态过滤: SPY < 200 SMA → 全部转现金 (risk-off)

为什么有效:
- 动量因子 (Jegadeesh & Titman 1993) 在跨资产层面持续有效
- 200 SMA 过滤器避开大熊市 (2008, 2020, 2022)
- 多资产分散降低单一市场风险

参考:
- Antonacci, G. "Dual Momentum Investing" (2014)
- Faber, M. "A Quantitative Approach to Tactical Asset Allocation" (2007)
"""

import numpy as np

from engine.strategy.base import BaseStrategy
from engine.indicators.trend import sma as SMA


# 默认 ETF 宇宙
DEFAULT_UNIVERSE = [
    "SPY",   # S&P 500
    "QQQ",   # Nasdaq 100
    "IWM",   # Russell 2000 小盘
    "EFA",   # 发达市场 (日欧澳)
    "EEM",   # 新兴市场
    "TLT",   # 美国长期国债
    "IEF",   # 美国中期国债
    "GLD",   # 黄金
    "DBC",   # 大宗商品
    "VNQ",   # 房地产 REITs
]


class ETFMomentumRotation(BaseStrategy):
    """
    ETF 动量轮动策略。

    参数:
        universe:          ETF 标的列表
        regime_symbol:     用于判断市场状态的标的 (默认 SPY)
        regime_sma_period: 市场状态 SMA 周期 (默认 200)
        momentum_period:   动量计算周期 (默认 126，约 6 个月)
        rebalance_period:  调仓周期，以交易日计 (默认 21，约 1 个月)
        top_k:             选入组合的 ETF 数量 (默认 3)
        use_regime_filter: 是否启用市场状态过滤 (默认 True)
    """

    def __init__(
        self,
        universe: list[str] | None = None,
        regime_symbol: str = "SPY",
        regime_sma_period: int = 200,
        momentum_period: int = 126,
        rebalance_period: int = 21,
        top_k: int = 3,
        use_regime_filter: bool = True,
    ):
        super().__init__()
        self.universe = universe or DEFAULT_UNIVERSE
        self.regime_symbol = regime_symbol
        self.regime_sma_period = regime_sma_period
        self.momentum_period = momentum_period
        self.rebalance_period = rebalance_period
        self.top_k = top_k
        self.use_regime_filter = use_regime_filter

        # 确保 regime_symbol 在 universe 中
        if self.regime_symbol not in self.universe:
            self.universe = [self.regime_symbol] + self.universe

        self._bar_count = 0
        self._current_holdings: set[str] = set()

        # 所需的最小 lookback
        self._min_bars = max(self.momentum_period, self.regime_sma_period)

    # ── 所有标的列表 (引擎需要) ──────────────────────────────

    @property
    def all_symbols(self) -> list[str]:
        """返回策略需要的所有标的。"""
        return list(self.universe)

    # ── 核心逻辑 ──────────────────────────────────────────────

    def on_bar(self) -> None:
        self._bar_count += 1

        # 只在调仓日操作
        if self._bar_count % self.rebalance_period != 0:
            return

        # 等待足够的历史数据
        if not self._has_enough_data():
            return

        # Step 1: 市场状态判断
        if self.use_regime_filter and self._is_risk_off():
            self._go_to_cash()
            return

        # Step 2: 计算动量排名
        rankings = self._rank_by_momentum()

        # Step 3: 选 top_k
        winners = set(sym for sym, _ in rankings[:self.top_k])

        # Step 4: 调仓 — 先卖后买
        self._rebalance(winners)

    # ── 市场状态过滤器 ──────────────────────────────────────

    def _is_risk_off(self) -> bool:
        """SPY < 200 SMA → risk-off，全部转现金。"""
        closes = self.bar_data.history(
            self.regime_symbol, "close", self.regime_sma_period
        )
        if len(closes) < self.regime_sma_period:
            return True  # 数据不足时保守处理

        sma_200 = SMA(closes, self.regime_sma_period)
        current_price = closes[-1]
        current_sma = sma_200[-1]

        return current_price < current_sma

    # ── 动量排名 ──────────────────────────────────────────────

    def _rank_by_momentum(self) -> list[tuple[str, float]]:
        """按过去 momentum_period 天的回报率排序。"""
        momentum_scores: list[tuple[str, float]] = []

        for symbol in self.universe:
            closes = self.bar_data.history(symbol, "close", self.momentum_period)
            if len(closes) < self.momentum_period:
                continue

            # 简单回报率
            ret = (closes[-1] / closes[0]) - 1.0

            # 可选: 跳过负动量的标的 (更保守)
            momentum_scores.append((symbol, ret))

        # 按回报率降序排列
        momentum_scores.sort(key=lambda x: x[1], reverse=True)
        return momentum_scores

    # ── 调仓逻辑 ──────────────────────────────────────────────

    def _rebalance(self, winners: set[str]) -> None:
        """
        等权调仓。

        按 dollar value 等权分配，而不是固定股数。
        """
        # 先卖出不在 winners 的持仓
        for symbol in list(self._current_holdings):
            if symbol not in winners:
                pos = self.get_position(symbol)
                if pos > 0:
                    self.sell(symbol, pos)
                self._current_holdings.discard(symbol)

        # 计算每个标的应分配的金额
        equity = self.portfolio.equity
        target_value_per_stock = equity / self.top_k * 0.95  # 留 5% 现金缓冲

        # 买入 winners 中需要调整的
        for symbol in winners:
            bar = self.bar_data.current(symbol)
            if bar is None:
                continue

            current_pos = self.get_position(symbol)
            current_value = current_pos * bar.close

            # 计算目标股数 (向下取整)
            target_shares = int(target_value_per_stock / bar.close)

            if current_pos == 0 and target_shares > 0:
                # 新建仓
                self.buy(symbol, target_shares)
                self._current_holdings.add(symbol)
            elif current_pos > 0:
                # 已持仓 — 调整到目标
                diff = target_shares - current_pos
                if diff > current_pos * 0.1:  # 偏差超过 10% 才调
                    self.buy(symbol, diff)
                elif diff < -current_pos * 0.1:
                    self.sell(symbol, abs(diff))
                # 偏差不大就不动，减少交易成本
                self._current_holdings.add(symbol)

    def _go_to_cash(self) -> None:
        """清空所有持仓。"""
        for symbol in list(self._current_holdings):
            pos = self.get_position(symbol)
            if pos > 0:
                self.sell(symbol, pos)
        self._current_holdings.clear()

    # ── 辅助方法 ──────────────────────────────────────────────

    def _has_enough_data(self) -> bool:
        """检查所有标的是否有足够的历史数据。"""
        for symbol in self.universe:
            if not self.bar_data.has_enough_bars(symbol, self._min_bars):
                return False
        return True
