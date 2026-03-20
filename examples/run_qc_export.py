"""
示例: 导出策略到 QuantConnect + 对账工作流。

用法: python -m examples.run_qc_export

流程:
  1. 用 Claude 将 SMA Crossover 策略翻译为 QC Python 代码
  2. 用 Claude 将 Dual Momentum 策略翻译为 QC Python 代码
  3. 展示如何用 reconciler 对比结果
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.export.quantconnect import QCExporter


def main():
    exporter = QCExporter()

    # ═══════════════════════════════════════════════════════════
    # 1. 导出 SMA Crossover
    # ═══════════════════════════════════════════════════════════
    print("=" * 60)
    print("  Exporting SMA Crossover → QuantConnect")
    print("=" * 60)

    qc_code = exporter.export(
        strategy_path="strategies/sma_crossover.py",
        start="2023-01-01",
        end="2025-12-31",
        initial_cash=100_000,
        commission_rate=0.001,
        output_path="qc_export_sma_crossover.py",
        strategy_kwargs={"symbol": "AAPL", "fast_period": 10, "slow_period": 30, "size": 100},
    )
    print(f"\nGenerated {len(qc_code)} chars")
    print("\n--- Preview ---")
    print(qc_code[:1500])
    print("...")

    # ═══════════════════════════════════════════════════════════
    # 2. 导出 Dual Momentum
    # ═══════════════════════════════════════════════════════════
    print("\n" + "=" * 60)
    print("  Exporting Dual Momentum → QuantConnect")
    print("=" * 60)

    qc_code2 = exporter.export(
        strategy_path="strategies/dual_momentum.py",
        start="2020-01-01",
        end="2025-12-31",
        initial_cash=100_000,
        commission_rate=0.001,
        output_path="qc_export_dual_momentum.py",
    )
    print(f"\nGenerated {len(qc_code2)} chars")

    # ═══════════════════════════════════════════════════════════
    # 使用说明
    # ═══════════════════════════════════════════════════════════
    print("\n" + "=" * 60)
    print("  WORKFLOW: How to compare with QuantConnect")
    print("=" * 60)
    print("""
  Step 1: Export strategy
    exporter = QCExporter()
    exporter.export("strategies/my_strategy.py",
                    start="2023-01-01", end="2025-12-31",
                    strategy_kwargs={"symbol": "AAPL"},
                    output_path="qc_my_strategy.py")

  Step 2: Run on QuantConnect
    - Copy qc_my_strategy.py contents to QuantConnect
    - Run backtest
    - Download results JSON (or copy log output)

  Step 3: Reconcile
    from engine.export.reconcile import QCReconciler

    reconciler = QCReconciler()
    report = reconciler.compare_from_log(
        qc_log_text=open("qc_results.json").read(),
        engine_portfolio=portfolio,
        engine_trade_log=engine.trade_log,
    )
    report.print_report()
    """)


if __name__ == "__main__":
    main()
