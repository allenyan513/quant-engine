"""
QC 日志辅助 — 在导出的 QC 策略中添加结构化日志，方便对账。

用法:
    在 QCExporter 生成的代码中，initialize() 末尾加入:
        self._qc_logger = QCLogger(self)

    在 on_order_event() 中加入:
        self._qc_logger.log_order(order_event)

    在 on_data() 中加入 (可选，记录每日净值):
        self._qc_logger.log_daily_equity()

    在 on_end_of_algorithm() 中加入:
        self._qc_logger.log_final_summary()
"""

# 这段代码可以直接复制到 QC 策略文件中
QC_LOGGER_CODE = '''\

class QCLogger:
    """结构化日志 — 方便与 quant-engine 对账。"""

    def __init__(self, algo):
        self._algo = algo
        self._daily_logged = set()

    def log_order(self, order_event):
        """记录订单成交。"""
        if order_event.status == OrderStatus.FILLED:
            direction = "BUY" if order_event.fill_quantity > 0 else "SELL"
            self._algo.log(
                f"Order filled: {direction} {abs(order_event.fill_quantity)} "
                f"{order_event.symbol} @ ${order_event.fill_price:.4f} "
                f"| Fee: ${order_event.order_fee.value.amount:.2f}"
            )

    def log_daily_equity(self):
        """记录每日净值 (在 on_data 中调用)。"""
        today = self._algo.time.date()
        if today not in self._daily_logged:
            self._daily_logged.add(today)
            equity = self._algo.portfolio.total_portfolio_value
            self._algo.log(f"Portfolio value: ${equity:,.2f}")

    def log_final_summary(self):
        """记录最终摘要。"""
        pv = self._algo.portfolio.total_portfolio_value
        cash = self._algo.portfolio.cash
        self._algo.log(f"=== FINAL SUMMARY ===")
        self._algo.log(f"Total Portfolio Value: ${pv:,.2f}")
        self._algo.log(f"Cash: ${cash:,.2f}")
        for kvp in self._algo.portfolio:
            pos = kvp.value
            if pos.invested:
                self._algo.log(
                    f"  {pos.symbol}: {pos.quantity} shares "
                    f"@ avg ${pos.average_price:.2f} "
                    f"| P&L: ${pos.unrealized_profit:,.2f}"
                )
'''
