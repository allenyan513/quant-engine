"""
板块等权再平衡策略 — 验证分散化降低波动、提升 Sharpe 的效果。

规则:
- 持有指定资产，按目标权重配置
- 每月 (21 个交易日) 再平衡一次
- 再平衡时按最新市值调整到目标权重
"""

from engine.strategy.base import BaseStrategy


class SectorRebalance(BaseStrategy):
    """
    多资产等权/自定义权重再平衡策略。

    参数:
        allocations: dict[symbol, weight]，权重之和应为 1.0
        rebalance_period: 再平衡周期 (交易日)
    """

    def __init__(
        self,
        allocations: dict[str, float],
        rebalance_period: int = 21,
    ):
        super().__init__()
        self.allocations = allocations
        self.rebalance_period = rebalance_period
        self._bar_count = 0
        self._initialized = False

    def on_bar(self) -> None:
        self._bar_count += 1

        # 每 rebalance_period 个 bar 或首次建仓时再平衡
        if self._initialized and self._bar_count % self.rebalance_period != 0:
            return

        # 确保所有标的都有数据
        for symbol in self.allocations:
            if not self.bar_data.has_enough_bars(symbol, 1):
                return

        self._rebalance()
        self._initialized = True

    def _rebalance(self) -> None:
        equity = self.portfolio.equity

        for symbol, weight in self.allocations.items():
            bar = self.bar_data.current(symbol)
            if bar is None or bar.close <= 0:
                continue

            target_value = equity * weight
            current_pos = self.get_position(symbol)
            current_value = current_pos * bar.close
            diff_value = target_value - current_value
            diff_qty = int(diff_value / bar.close)

            if diff_qty > 0:
                self.buy(symbol, diff_qty)
            elif diff_qty < 0:
                self.sell(symbol, abs(diff_qty))
