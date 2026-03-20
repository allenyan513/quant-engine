"""
全天候自适应动量策略 (All-Weather Adaptive Momentum)

核心思想: 不预判未来哪个板块会涨，让动量自己说话。

与之前策略的关键区别:
  1. 风险调整动量: return / volatility (类 Sharpe 排名)，不是原始回报
  2. 逆波动率加权: 波动大的少配，波动小的多配
  3. 逐资产绝对动量过滤: 每个资产独立判断趋势，不依赖单一大盘指标
  4. 全部过滤掉 → 100% 短期国债，安全等待

宇宙:
  - 美股: SPY (大盘), QQQ (科技), IWM (小盘)
  - 国际: EFA (发达), EEM (新兴)
  - 债券: TLT (长债), IEF (中债)
  - 商品: DBC (大宗)
  - 黄金: GLD
  - REITs: VNQ

适用周期:
  - 2000-2010 科技泡沫+金融危机 → 自动转向债券/黄金
  - 2010-2020 美股慢牛 → 自动集中美股
  - 2020-2024 暴涨暴跌 → 快速切换
"""

import numpy as np

from engine.strategy.base import BaseStrategy
from engine.indicators.trend import sma


# 默认多资产宇宙
DEFAULT_UNIVERSE = [
    "SPY",   # S&P 500
    "QQQ",   # Nasdaq 100
    "IWM",   # Russell 2000
    "EFA",   # 发达市场
    "EEM",   # 新兴市场
    "TLT",   # 美国长期国债
    "IEF",   # 美国中期国债
    "DBC",   # 大宗商品
    "GLD",   # 黄金
    "VNQ",   # REITs
]

SAFE_ASSET = "SHY"  # 短期国债


class AllWeatherMomentum(BaseStrategy):
    """
    全天候自适应动量策略。

    参数:
        universe:          资产宇宙
        safe_asset:        避险资产 (所有资产都趋势向下时持有)
        momentum_period:   动量计算周期 (默认 126 ≈ 6 个月)
        volatility_period: 波动率计算周期 (默认 63 ≈ 3 个月)
        trend_sma_period:  趋势判断 SMA 周期 (默认 200)
        rebalance_period:  调仓周期 (默认 21 ≈ 1 个月)
        top_k:             持仓数量 (默认 4)
    """

    def __init__(
        self,
        universe: list[str] | None = None,
        safe_asset: str = SAFE_ASSET,
        momentum_period: int = 126,
        volatility_period: int = 63,
        trend_sma_period: int = 200,
        rebalance_period: int = 21,
        top_k: int = 4,
    ):
        super().__init__()
        self.universe = universe or list(DEFAULT_UNIVERSE)
        self.safe_asset = safe_asset
        self.momentum_period = momentum_period
        self.volatility_period = volatility_period
        self.trend_sma_period = trend_sma_period
        self.rebalance_period = rebalance_period
        self.top_k = top_k

        self._bar_count = 0
        self._current_holdings: set[str] = set()
        self._min_bars = max(momentum_period, trend_sma_period, volatility_period)

    @property
    def all_symbols(self) -> list[str]:
        return list(set(self.universe + [self.safe_asset]))

    # ── 核心逻辑 ──────────────────────────────────────────────

    def on_bar(self) -> None:
        self._bar_count += 1

        if self._bar_count % self.rebalance_period != 0:
            return

        if not self._has_enough_data():
            return

        # Step 1: 按风险调整动量排名
        rankings = self._rank_by_risk_adjusted_momentum()

        # Step 2: 逐资产绝对动量过滤 (价格 > SMA → 趋势向上)
        filtered = self._apply_absolute_momentum_filter(rankings)

        # Step 3: 取 top_k
        selected = [sym for sym, _ in filtered[:self.top_k]]

        if not selected:
            # 所有资产都趋势向下 → 全部转避险
            self._go_to_safe()
            return

        # Step 4: 逆波动率加权
        weights = self._compute_inverse_volatility_weights(selected)

        # Step 5: 调仓
        self._rebalance(weights)

    # ── 风险调整动量排名 ──────────────────────────────────────

    def _rank_by_risk_adjusted_momentum(self) -> list[tuple[str, float]]:
        """
        按 return / volatility 排序 (类似 Sharpe 排名)。

        不用原始回报排名的原因:
        - TQQQ 涨 30% 但波动 60% → 风险调整 = 0.5
        - TLT 涨 5% 但波动 8% → 风险调整 = 0.625
        - TLT 排名更高! 这才是理性的资产选择
        """
        scores: list[tuple[str, float]] = []

        for symbol in self.universe:
            closes = self.bar_data.history(symbol, "close", self.momentum_period)
            if len(closes) < self.momentum_period:
                continue

            # 原始回报
            raw_return = (closes[-1] / closes[0]) - 1.0

            # 日回报率的年化波动率
            daily_returns = np.diff(closes) / closes[:-1]
            volatility = np.std(daily_returns) * np.sqrt(252)

            # 风险调整动量 (return / vol)
            if volatility > 0.01:  # 防止除零
                score = raw_return / volatility
            else:
                score = raw_return * 100  # 波动极低的资产给高分

            scores.append((symbol, score))

        scores.sort(key=lambda x: x[1], reverse=True)
        return scores

    # ── 绝对动量过滤 ─────────────────────────────────────────

    def _apply_absolute_momentum_filter(
        self, rankings: list[tuple[str, float]]
    ) -> list[tuple[str, float]]:
        """
        逐资产过滤: 只保留价格 > SMA 的资产。

        不像之前用 SPY < 200 SMA 作为全局开关:
        - 2022 年: SPY 跌破 200 SMA，但 GLD、DBC 趋势向上
        - 全局过滤器会错过这些机会
        - 逐资产过滤器会自动买入 GLD + DBC
        """
        filtered = []
        for symbol, score in rankings:
            closes = self.bar_data.history(symbol, "close", self.trend_sma_period)
            if len(closes) < self.trend_sma_period:
                continue

            sma_values = sma(closes, self.trend_sma_period)
            if np.isnan(sma_values[-1]):
                continue

            # 只保留趋势向上的资产
            if closes[-1] > sma_values[-1]:
                filtered.append((symbol, score))

        return filtered

    # ── 逆波动率加权 ─────────────────────────────────────────

    def _compute_inverse_volatility_weights(
        self, selected: list[str]
    ) -> dict[str, float]:
        """
        逆波动率加权: 波动大的少配，波动小的多配。

        为什么不等权?
        - SPY 年化波动 ~16%, TLT ~15%, GLD ~15%, DBC ~25%
        - 等权分配意味着 DBC 贡献了不成比例的组合风险
        - 逆波动率让每个持仓对组合的风险贡献大致相等
        """
        inv_vols: dict[str, float] = {}

        for symbol in selected:
            closes = self.bar_data.history(symbol, "close", self.volatility_period)
            if len(closes) < self.volatility_period:
                continue

            daily_returns = np.diff(closes) / closes[:-1]
            vol = np.std(daily_returns) * np.sqrt(252)
            vol = max(vol, 0.01)  # 防止极端值
            inv_vols[symbol] = 1.0 / vol

        if not inv_vols:
            return {}

        # 归一化，留 2% 现金缓冲
        total = sum(inv_vols.values())
        weights = {sym: (iv / total) * 0.98 for sym, iv in inv_vols.items()}
        return weights

    # ── 调仓 ──────────────────────────────────────────────────

    def _rebalance(self, target_weights: dict[str, float]) -> None:
        """按目标权重调仓。"""
        target_symbols = set(target_weights.keys())

        # 收集所有需要检查的持仓 (包括避险资产)
        all_held = set(self._current_holdings)
        if self.get_position(self.safe_asset) > 0:
            all_held.add(self.safe_asset)

        # 先卖出不在目标中的持仓
        for symbol in list(all_held):
            if symbol not in target_symbols:
                pos = self.get_position(symbol)
                if pos > 0:
                    self.sell(symbol, pos)
                self._current_holdings.discard(symbol)

        equity = self.portfolio.equity

        for symbol, weight in target_weights.items():
            bar = self.bar_data.current(symbol)
            if bar is None or bar.close <= 0:
                continue

            target_value = equity * weight
            target_shares = int(target_value / bar.close)

            current_pos = self.get_position(symbol)
            current_value = current_pos * bar.close

            if current_pos == 0 and target_shares > 0:
                self.buy(symbol, target_shares)
                self._current_holdings.add(symbol)
            elif current_pos > 0:
                diff = target_shares - current_pos
                # 偏差超过 10% 才调整
                if abs(diff) > current_pos * 0.1:
                    if diff > 0:
                        self.buy(symbol, diff)
                    elif diff < 0:
                        self.sell(symbol, abs(diff))
                self._current_holdings.add(symbol)

    def _go_to_safe(self) -> None:
        """所有资产趋势向下，全部转避险。"""
        for symbol in list(self._current_holdings):
            pos = self.get_position(symbol)
            if pos > 0:
                self.sell(symbol, pos)
        self._current_holdings.clear()

        # 买入避险资产
        bar = self.bar_data.current(self.safe_asset)
        if bar and bar.close > 0:
            available = self.portfolio.equity * 0.98
            qty = int(available / bar.close)
            if qty > 0:
                self.buy(self.safe_asset, qty)
                self._current_holdings.add(self.safe_asset)

    # ── 辅助 ──────────────────────────────────────────────────

    def _has_enough_data(self) -> bool:
        for symbol in self.universe:
            if not self.bar_data.has_enough_bars(symbol, self._min_bars):
                return False
        return True
