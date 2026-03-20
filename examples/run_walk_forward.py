"""
示例: Walk-Forward 参数优化 — 验证 SMA Crossover 是否过拟合。

用法: python -m examples.run_walk_forward

对 AAPL 的 SMA 交叉策略做滚动验证:
- 参数空间: fast_period=[5,10,15,20,25], slow_period=[30,50,100,150,200]
- 训练 3 年，测试 1 年，滚动向前
- 优化目标: Sharpe Ratio
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.optimize import WalkForwardOptimizer
from engine.execution.fee_model import PerShareFeeModel
from strategies.sma_crossover import SMACrossover


def main():
    optimizer = WalkForwardOptimizer(
        strategy_cls=SMACrossover,
        param_grid={
            "fast_period": [5, 10, 15, 20, 25],
            "slow_period": [30, 50, 100, 150, 200],
        },
        fixed_params={"symbol": "AAPL", "size": 100},
        symbols=["AAPL"],
        train_years=3,
        test_years=1,
        start="2015-01-01",
        end="2025-12-31",
        score_metric="sharpe_ratio",
        initial_cash=100_000.0,
        fee_model=PerShareFeeModel(),
        slippage_rate=0.0005,
    )

    result = optimizer.run()
    result.print_summary()
    result.save_report()


if __name__ == "__main__":
    main()
