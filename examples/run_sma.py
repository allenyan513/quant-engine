"""
示例: 运行 SMA 交叉策略回测。

用法: python -m examples.run_sma
"""

import sys
import os

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.engine import BacktestEngine
from engine.data.data_feed import YFinanceFeed
from engine.analytics.metrics import print_report
from engine.analytics.chart import plot_backtest
from strategies.sma_crossover import SMACrossover


def main():
    # 策略参数
    symbol = "AAPL"
    strategy = SMACrossover(
        symbol=symbol,
        fast_period=10,
        slow_period=30,
        size=100,
    )

    # 创建引擎
    engine = BacktestEngine(
        strategy=strategy,
        data_feed=YFinanceFeed(),
        symbols=[symbol],
        start="2023-01-01",
        end="2024-12-31",
        initial_cash=100_000.0,
        commission_rate=0.001,
        slippage_rate=0.0005,
    )

    # 运行
    portfolio = engine.run()

    # 打印报告
    print_report(portfolio)

    # 打印持仓
    print("\nOpen Positions:")
    for sym, pos in portfolio.positions.items():
        if pos.quantity != 0:
            print(f"  {sym}: {pos.quantity} shares @ ${pos.avg_cost:.2f}")

    # 可视化
    plot_backtest(
        portfolio=portfolio,
        bar_data=engine.bar_data,
        title=f"SMA Crossover ({symbol}) — 2023-2024",
        save_path="backtest_result.png",
    )


if __name__ == "__main__":
    main()
