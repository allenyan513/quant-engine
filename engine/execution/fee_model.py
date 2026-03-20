"""
手续费模型 — 可插拔的手续费计算。

内置模型:
- ZeroFeeModel: 零手续费
- PerShareFeeModel: 按股数收费 (IB 模式: $0.005/股, 最低 $1, 最高 0.5%)
- PercentageFeeModel: 按成交金额比例收费
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class FeeModel(ABC):
    """手续费模型基类。"""

    @abstractmethod
    def calculate(self, fill_price: float, quantity: int) -> float:
        """
        计算手续费。

        Args:
            fill_price: 成交价格
            quantity: 成交数量

        Returns:
            手续费金额 (≥ 0)
        """
        ...


class ZeroFeeModel(FeeModel):
    """零手续费。"""

    def calculate(self, fill_price: float, quantity: int) -> float:
        return 0.0


class PerShareFeeModel(FeeModel):
    """
    按股数收费 (Interactive Brokers Fixed 模式)。

    默认参数:
    - per_share: $0.005/股
    - min_fee: $1.00 每笔最低
    - max_pct: 0.5% 每笔最高 (占成交金额)
    """

    def __init__(
        self,
        per_share: float = 0.005,
        min_fee: float = 1.0,
        max_pct: float = 0.005,
    ) -> None:
        self.per_share = per_share
        self.min_fee = min_fee
        self.max_pct = max_pct

    def calculate(self, fill_price: float, quantity: int) -> float:
        raw = quantity * self.per_share
        trade_value = fill_price * quantity
        max_fee = trade_value * self.max_pct
        return max(self.min_fee, min(raw, max_fee))


class PercentageFeeModel(FeeModel):
    """按成交金额比例收费。"""

    def __init__(self, rate: float = 0.001) -> None:
        self.rate = rate

    def calculate(self, fill_price: float, quantity: int) -> float:
        return fill_price * quantity * self.rate
