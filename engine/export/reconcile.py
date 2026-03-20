"""
Reconciler — 对比 QuantConnect 回测结果与 quant-engine 结果，定位差异根因。

用法:
    from engine.export.reconcile import QCReconciler

    # 方式 1: 对比净值曲线 (QC 导出的 CSV)
    reconciler = QCReconciler()
    report = reconciler.compare_equity(
        qc_equity_csv="qc_equity.csv",
        engine_portfolio=portfolio,
    )

    # 方式 2: 对比订单成交记录 (QC 导出的 JSON)
    report = reconciler.compare_orders(
        qc_orders_json="qc_orders.json",
        engine_trade_log=trade_log,
    )

    # 方式 3: 从 QC 回测日志文本中解析
    report = reconciler.compare_from_log(
        qc_log_text=log_text,
        engine_portfolio=portfolio,
        engine_trade_log=trade_log,
    )

QC 数据获取方式:
    1. 在 QC 回测完成后，点击 "Results" → "Export" → 下载 JSON
    2. 或者在策略代码中加入 self.Log() 输出每笔交易和每日净值
    3. 本工具也支持直接粘贴 QC 控制台中的日志文本
"""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, date
from pathlib import Path

import numpy as np

from engine.analytics.metrics import TradeLog
from engine.portfolio.portfolio import Portfolio


@dataclass
class OrderRecord:
    """统一的订单记录格式。"""
    timestamp: datetime
    symbol: str
    direction: str     # "BUY" or "SELL"
    quantity: int
    fill_price: float
    commission: float = 0.0

    @property
    def value(self) -> float:
        return self.quantity * self.fill_price


@dataclass
class EquityPoint:
    """净值数据点。"""
    date: date
    equity: float


@dataclass
class Discrepancy:
    """单个差异项。"""
    category: str        # "equity", "order", "fill_price", "commission", "data"
    severity: str        # "HIGH", "MEDIUM", "LOW"
    date: date | None
    description: str
    our_value: float | str
    qc_value: float | str
    diff: float | str = ""
    likely_cause: str = ""


@dataclass
class ReconcileReport:
    """对账报告。"""
    discrepancies: list[Discrepancy] = field(default_factory=list)
    summary: dict = field(default_factory=dict)

    def print_report(self) -> None:
        """打印对账报告。"""
        print("\n" + "=" * 70)
        print("          RECONCILIATION REPORT: quant-engine vs QuantConnect")
        print("=" * 70)

        if not self.discrepancies:
            print("\n  ✓ No discrepancies found! Results match.")
            return

        # 按严重程度分组
        high = [d for d in self.discrepancies if d.severity == "HIGH"]
        medium = [d for d in self.discrepancies if d.severity == "MEDIUM"]
        low = [d for d in self.discrepancies if d.severity == "LOW"]

        if self.summary:
            print("\n── Summary ─────────────────────────────────────────────")
            for k, v in self.summary.items():
                if isinstance(v, float):
                    print(f"  {k}: {v:.4f}")
                else:
                    print(f"  {k}: {v}")

        if high:
            print(f"\n── HIGH severity ({len(high)}) ────────────────────────────────")
            for d in high[:20]:
                self._print_discrepancy(d)

        if medium:
            print(f"\n── MEDIUM severity ({len(medium)}) ──────────────────────────────")
            for d in medium[:20]:
                self._print_discrepancy(d)

        if low:
            print(f"\n── LOW severity ({len(low)}) ────────────────────────────────")
            for d in low[:10]:
                self._print_discrepancy(d)
            if len(low) > 10:
                print(f"  ... and {len(low) - 10} more")

        # 诊断建议
        print("\n── Diagnosis ───────────────────────────────────────────")
        causes = {}
        for d in self.discrepancies:
            if d.likely_cause:
                causes.setdefault(d.likely_cause, 0)
                causes[d.likely_cause] += 1

        if causes:
            for cause, count in sorted(causes.items(), key=lambda x: -x[1]):
                print(f"  [{count}x] {cause}")
        else:
            print("  No specific causes identified.")

        print("=" * 70)

    def _print_discrepancy(self, d: Discrepancy) -> None:
        date_str = d.date.strftime("%Y-%m-%d") if d.date else "N/A"
        print(f"  [{d.category}] {date_str}: {d.description}")
        print(f"    Ours: {d.our_value}  |  QC: {d.qc_value}  |  Diff: {d.diff}")
        if d.likely_cause:
            print(f"    → Likely cause: {d.likely_cause}")


class QCReconciler:
    """QuantConnect 对账工具。"""

    # ── 净值曲线对比 ──────────────────────────────────────────

    def compare_equity(
        self,
        qc_equity_csv: str | None = None,
        qc_equity_data: list[EquityPoint] | None = None,
        engine_portfolio: Portfolio | None = None,
        tolerance_pct: float = 0.5,
    ) -> ReconcileReport:
        """
        对比每日净值曲线。

        Args:
            qc_equity_csv: QC 导出的净值 CSV 文件路径
            qc_equity_data: 或直接传入解析好的数据
            engine_portfolio: 我们引擎的 Portfolio 对象
            tolerance_pct: 偏差容忍度 (百分比)
        """
        report = ReconcileReport()

        if qc_equity_csv:
            qc_equity_data = self._parse_qc_equity_csv(qc_equity_csv)

        if not qc_equity_data or not engine_portfolio:
            report.discrepancies.append(Discrepancy(
                category="data",
                severity="HIGH",
                date=None,
                description="Missing data: need both QC equity and engine portfolio",
                our_value="N/A",
                qc_value="N/A",
            ))
            return report

        # 构建我们引擎的日期→净值映射
        engine_equity = {}
        for ts, eq in engine_portfolio.equity_curve:
            d = ts.date() if isinstance(ts, datetime) else ts
            engine_equity[d] = eq

        # 逐日对比
        total_points = 0
        mismatch_points = 0
        max_deviation = 0.0
        deviations = []

        for qc_point in qc_equity_data:
            if qc_point.date not in engine_equity:
                report.discrepancies.append(Discrepancy(
                    category="data",
                    severity="LOW",
                    date=qc_point.date,
                    description=f"Date exists in QC but not in engine",
                    our_value="missing",
                    qc_value=f"${qc_point.equity:,.2f}",
                    likely_cause="Data alignment: different trading calendars or weekend handling",
                ))
                continue

            engine_eq = engine_equity[qc_point.date]
            total_points += 1

            if qc_point.equity > 0:
                pct_diff = abs(engine_eq - qc_point.equity) / qc_point.equity * 100
            else:
                pct_diff = 0.0

            deviations.append(pct_diff)
            max_deviation = max(max_deviation, pct_diff)

            if pct_diff > tolerance_pct:
                mismatch_points += 1
                severity = "HIGH" if pct_diff > 5.0 else "MEDIUM" if pct_diff > 2.0 else "LOW"

                likely_cause = self._diagnose_equity_diff(pct_diff, engine_eq, qc_point.equity)

                report.discrepancies.append(Discrepancy(
                    category="equity",
                    severity=severity,
                    date=qc_point.date,
                    description=f"Equity divergence: {pct_diff:.2f}%",
                    our_value=f"${engine_eq:,.2f}",
                    qc_value=f"${qc_point.equity:,.2f}",
                    diff=f"{pct_diff:.2f}%",
                    likely_cause=likely_cause,
                ))

        report.summary = {
            "total_comparison_points": total_points,
            "mismatched_points": mismatch_points,
            "match_rate": f"{(1 - mismatch_points / total_points) * 100:.1f}%" if total_points > 0 else "N/A",
            "max_deviation_pct": max_deviation,
            "mean_deviation_pct": np.mean(deviations) if deviations else 0.0,
            "our_final_equity": engine_portfolio.equity,
            "qc_final_equity": qc_equity_data[-1].equity if qc_equity_data else 0.0,
        }

        return report

    # ── 订单对比 ──────────────────────────────────────────────

    def compare_orders(
        self,
        qc_orders_json: str | None = None,
        qc_orders_data: list[OrderRecord] | None = None,
        engine_trade_log: TradeLog | None = None,
        price_tolerance: float = 0.01,
    ) -> ReconcileReport:
        """
        对比交易订单记录。

        Args:
            qc_orders_json: QC 导出的订单 JSON 文件路径
            qc_orders_data: 或直接传入解析好的数据
            engine_trade_log: 我们引擎的 TradeLog
            price_tolerance: 价格偏差容忍度 (比例)
        """
        report = ReconcileReport()

        if qc_orders_json:
            qc_orders_data = self._parse_qc_orders_json(qc_orders_json)

        if not qc_orders_data or not engine_trade_log:
            report.discrepancies.append(Discrepancy(
                category="data",
                severity="HIGH",
                date=None,
                description="Missing data: need both QC orders and engine trade log",
                our_value="N/A",
                qc_value="N/A",
            ))
            return report

        # 从 TradeLog 构建订单列表
        engine_orders = self._trade_log_to_orders(engine_trade_log)

        report.summary = {
            "engine_order_count": len(engine_orders),
            "qc_order_count": len(qc_orders_data),
        }

        # 匹配订单 (按日期 + symbol + 方向)
        qc_idx = 0
        engine_idx = 0
        matched = 0
        unmatched_qc = []
        unmatched_engine = []

        qc_by_key = {}
        for order in qc_orders_data:
            key = (order.timestamp.date(), order.symbol, order.direction)
            qc_by_key.setdefault(key, []).append(order)

        engine_by_key = {}
        for order in engine_orders:
            key = (order.timestamp.date(), order.symbol, order.direction)
            engine_by_key.setdefault(key, []).append(order)

        all_keys = set(qc_by_key.keys()) | set(engine_by_key.keys())

        for key in sorted(all_keys):
            d, sym, direction = key
            qc_list = qc_by_key.get(key, [])
            eng_list = engine_by_key.get(key, [])

            if not qc_list:
                for order in eng_list:
                    report.discrepancies.append(Discrepancy(
                        category="order",
                        severity="HIGH",
                        date=d,
                        description=f"Order exists in engine but not QC: {direction} {order.quantity} {sym}",
                        our_value=f"{direction} {order.quantity} @ ${order.fill_price:.2f}",
                        qc_value="missing",
                        likely_cause="Signal divergence: different data or timing caused different trade decision",
                    ))
                continue

            if not eng_list:
                for order in qc_list:
                    report.discrepancies.append(Discrepancy(
                        category="order",
                        severity="HIGH",
                        date=d,
                        description=f"Order exists in QC but not engine: {direction} {order.quantity} {sym}",
                        our_value="missing",
                        qc_value=f"{direction} {order.quantity} @ ${order.fill_price:.2f}",
                        likely_cause="Signal divergence: different data or timing caused different trade decision",
                    ))
                continue

            # 有匹配 — 对比细节
            for i in range(max(len(qc_list), len(eng_list))):
                if i >= len(eng_list) or i >= len(qc_list):
                    break

                qc_order = qc_list[i]
                eng_order = eng_list[i]
                matched += 1

                # 对比数量
                if qc_order.quantity != eng_order.quantity:
                    report.discrepancies.append(Discrepancy(
                        category="order",
                        severity="MEDIUM",
                        date=d,
                        description=f"Quantity mismatch for {sym} {direction}",
                        our_value=str(eng_order.quantity),
                        qc_value=str(qc_order.quantity),
                        diff=str(eng_order.quantity - qc_order.quantity),
                        likely_cause="Position sizing: different equity at time of order → different share count",
                    ))

                # 对比成交价
                if eng_order.fill_price > 0:
                    price_diff_pct = abs(eng_order.fill_price - qc_order.fill_price) / eng_order.fill_price
                    if price_diff_pct > price_tolerance:
                        likely_cause = self._diagnose_price_diff(
                            eng_order.fill_price, qc_order.fill_price, price_diff_pct
                        )
                        report.discrepancies.append(Discrepancy(
                            category="fill_price",
                            severity="MEDIUM" if price_diff_pct < 0.05 else "HIGH",
                            date=d,
                            description=f"Fill price mismatch for {sym} {direction}",
                            our_value=f"${eng_order.fill_price:.4f}",
                            qc_value=f"${qc_order.fill_price:.4f}",
                            diff=f"{price_diff_pct:.4%}",
                            likely_cause=likely_cause,
                        ))

                # 对比手续费
                if qc_order.commission > 0 or eng_order.commission > 0:
                    comm_diff = abs(eng_order.commission - qc_order.commission)
                    if comm_diff > 0.01:
                        report.discrepancies.append(Discrepancy(
                            category="commission",
                            severity="LOW",
                            date=d,
                            description=f"Commission mismatch for {sym}",
                            our_value=f"${eng_order.commission:.2f}",
                            qc_value=f"${qc_order.commission:.2f}",
                            diff=f"${comm_diff:.2f}",
                            likely_cause="Commission model: engine uses percentage-based, QC may use per-share or tiered model",
                        ))

        report.summary["matched_orders"] = matched

        return report

    # ── 从 QC 日志文本解析 ────────────────────────────────────

    def compare_from_log(
        self,
        qc_log_text: str,
        engine_portfolio: Portfolio | None = None,
        engine_trade_log: TradeLog | None = None,
    ) -> ReconcileReport:
        """
        从 QC 回测日志文本中解析数据并对比。

        支持解析的格式:
          - "YYYY-MM-DD HH:MM:SS : Order filled: BUY 100 SPY @ $450.00"
          - "YYYY-MM-DD HH:MM:SS : Portfolio value: $105,234.56"
          - QC 标准的 backtest result JSON
        """
        # 尝试解析为 JSON
        try:
            data = json.loads(qc_log_text)
            return self._compare_from_qc_json(data, engine_portfolio, engine_trade_log)
        except (json.JSONDecodeError, ValueError):
            pass

        # 文本日志格式解析
        orders = []
        equity_points = []

        # 解析订单
        order_pattern = re.compile(
            r"(\d{4}-\d{2}-\d{2})\s+\S*\s*:?\s*"
            r"(?:Order\s+(?:filled|Filled)|OrderEvent).*?"
            r"(BUY|SELL|Buy|Sell)\s+(\d+)\s+(\w+)"
            r".*?(?:@|Price:?)\s*\$?([\d.,]+)"
        )
        for match in order_pattern.finditer(qc_log_text):
            dt = datetime.strptime(match.group(1), "%Y-%m-%d")
            direction = match.group(2).upper()
            quantity = int(match.group(3))
            symbol = match.group(4)
            price = float(match.group(5).replace(",", ""))
            orders.append(OrderRecord(
                timestamp=dt,
                symbol=symbol,
                direction=direction,
                quantity=quantity,
                fill_price=price,
            ))

        # 解析净值
        equity_pattern = re.compile(
            r"(\d{4}-\d{2}-\d{2})\s+\S*\s*:?\s*"
            r"(?:Portfolio\s+value|Equity|TotalPortfolioValue)\s*:?\s*\$?([\d.,]+)"
        )
        for match in equity_pattern.finditer(qc_log_text):
            d = datetime.strptime(match.group(1), "%Y-%m-%d").date()
            equity = float(match.group(2).replace(",", ""))
            equity_points.append(EquityPoint(date=d, equity=equity))

        # 执行对比
        report = ReconcileReport()

        if equity_points and engine_portfolio:
            eq_report = self.compare_equity(
                qc_equity_data=equity_points,
                engine_portfolio=engine_portfolio,
            )
            report.discrepancies.extend(eq_report.discrepancies)
            report.summary.update(eq_report.summary)

        if orders and engine_trade_log:
            ord_report = self.compare_orders(
                qc_orders_data=orders,
                engine_trade_log=engine_trade_log,
            )
            report.discrepancies.extend(ord_report.discrepancies)
            report.summary.update(ord_report.summary)

        if not orders and not equity_points:
            report.discrepancies.append(Discrepancy(
                category="data",
                severity="HIGH",
                date=None,
                description="Could not parse any data from the provided log text",
                our_value="N/A",
                qc_value="N/A",
                likely_cause="Unrecognized log format. Use QC's JSON export or add self.Log() to strategy.",
            ))

        return report

    # ── QC JSON 结果解析 ──────────────────────────────────────

    def _compare_from_qc_json(
        self,
        data: dict,
        engine_portfolio: Portfolio | None,
        engine_trade_log: TradeLog | None,
    ) -> ReconcileReport:
        """解析 QC 标准 JSON 导出格式。"""
        report = ReconcileReport()

        # QC JSON 结构:
        # { "Charts": { "Strategy Equity": { "Series": { "Equity": { "Values": [...] }}}},
        #   "Orders": { "1": { "Symbol": ..., "Quantity": ..., "Price": ... }, ... },
        #   "Statistics": { ... } }

        # 解析净值
        equity_points = []
        charts = data.get("Charts", {})
        equity_chart = charts.get("Strategy Equity", {})
        equity_series = equity_chart.get("Series", {}).get("Equity", {})
        for point in equity_series.get("Values", []):
            # QC 格式: {"x": timestamp_ms, "y": value}
            ts = datetime.fromtimestamp(point["x"] / 1000) if point["x"] > 1e9 else datetime.fromtimestamp(point["x"])
            equity_points.append(EquityPoint(date=ts.date(), equity=point["y"]))

        # 解析订单
        orders = []
        for order_id, order_data in data.get("Orders", {}).items():
            symbol = order_data.get("Symbol", {})
            if isinstance(symbol, dict):
                symbol = symbol.get("Value", "")

            quantity = order_data.get("Quantity", 0)
            direction = "BUY" if quantity > 0 else "SELL"
            price = order_data.get("Price", 0)

            time_str = order_data.get("Time", order_data.get("LastFillTime", ""))
            try:
                ts = datetime.fromisoformat(time_str.replace("Z", "+00:00")) if time_str else datetime.now()
            except (ValueError, AttributeError):
                ts = datetime.now()

            if abs(quantity) > 0 and price > 0:
                orders.append(OrderRecord(
                    timestamp=ts,
                    symbol=symbol,
                    direction=direction,
                    quantity=abs(quantity),
                    fill_price=price,
                    commission=order_data.get("OrderFee", {}).get("Value", {}).get("Amount", 0.0),
                ))

        # 对比
        if equity_points and engine_portfolio:
            eq_report = self.compare_equity(
                qc_equity_data=equity_points,
                engine_portfolio=engine_portfolio,
            )
            report.discrepancies.extend(eq_report.discrepancies)
            report.summary.update(eq_report.summary)

        if orders and engine_trade_log:
            ord_report = self.compare_orders(
                qc_orders_data=orders,
                engine_trade_log=engine_trade_log,
            )
            report.discrepancies.extend(ord_report.discrepancies)
            report.summary.update(ord_report.summary)

        # 对比统计指标
        stats = data.get("Statistics", {})
        if stats and engine_portfolio:
            self._compare_stats(stats, engine_portfolio, report)

        return report

    def _compare_stats(
        self, qc_stats: dict, engine_portfolio: Portfolio, report: ReconcileReport
    ) -> None:
        """对比 QC 和 engine 的统计指标。"""
        from engine.analytics.metrics import calculate_metrics

        engine_metrics = calculate_metrics(engine_portfolio)
        if not engine_metrics:
            return

        # 对比总回报
        qc_total_return_str = qc_stats.get("Total Net Profit", "0%")
        qc_total_return = self._parse_pct(qc_total_return_str)
        engine_total_return = engine_metrics.get("total_return", 0.0) * 100

        if abs(engine_total_return - qc_total_return) > 1.0:
            report.discrepancies.append(Discrepancy(
                category="equity",
                severity="HIGH",
                date=None,
                description="Total return mismatch",
                our_value=f"{engine_total_return:.2f}%",
                qc_value=f"{qc_total_return:.2f}%",
                diff=f"{engine_total_return - qc_total_return:.2f}%",
                likely_cause="Cumulative effect of fill price, commission, and data differences",
            ))

        # 对比 Sharpe
        qc_sharpe_str = qc_stats.get("Sharpe Ratio", "0")
        try:
            qc_sharpe = float(qc_sharpe_str)
        except ValueError:
            qc_sharpe = 0.0
        engine_sharpe = engine_metrics.get("sharpe_ratio", 0.0)

        if abs(engine_sharpe - qc_sharpe) > 0.2:
            report.discrepancies.append(Discrepancy(
                category="equity",
                severity="MEDIUM",
                date=None,
                description="Sharpe ratio mismatch",
                our_value=f"{engine_sharpe:.2f}",
                qc_value=f"{qc_sharpe:.2f}",
                diff=f"{engine_sharpe - qc_sharpe:.2f}",
                likely_cause="Different return/volatility calculation methodology",
            ))

        # 对比最大回撤
        qc_dd_str = qc_stats.get("Drawdown", "0%")
        qc_dd = abs(self._parse_pct(qc_dd_str))
        engine_dd = abs(engine_metrics.get("max_drawdown", 0.0) * 100)

        if abs(engine_dd - qc_dd) > 1.0:
            report.discrepancies.append(Discrepancy(
                category="equity",
                severity="MEDIUM",
                date=None,
                description="Max drawdown mismatch",
                our_value=f"{engine_dd:.2f}%",
                qc_value=f"{qc_dd:.2f}%",
                diff=f"{engine_dd - qc_dd:.2f}%",
                likely_cause="Different equity update frequency or calculation method",
            ))

    # ── 解析辅助方法 ──────────────────────────────────────────

    def _parse_qc_equity_csv(self, csv_path: str) -> list[EquityPoint]:
        """解析 QC 导出的净值 CSV。"""
        points = []
        with open(csv_path, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # QC CSV 格式可能有多种
                date_str = row.get("Date", row.get("date", row.get("Time", "")))
                equity_str = row.get("Equity", row.get("equity", row.get("Portfolio Value", "0")))

                try:
                    d = datetime.strptime(date_str.split(" ")[0], "%Y-%m-%d").date()
                    equity = float(equity_str.replace(",", "").replace("$", ""))
                    points.append(EquityPoint(date=d, equity=equity))
                except (ValueError, AttributeError):
                    continue

        return points

    def _parse_qc_orders_json(self, json_path: str) -> list[OrderRecord]:
        """解析 QC 导出的订单 JSON。"""
        with open(json_path, "r") as f:
            data = json.load(f)

        orders = []
        # 支持两种格式: list 或 dict
        items = data if isinstance(data, list) else data.values()

        for order_data in items:
            if isinstance(order_data, dict):
                symbol = order_data.get("Symbol", "")
                if isinstance(symbol, dict):
                    symbol = symbol.get("Value", "")

                quantity = order_data.get("Quantity", 0)
                price = order_data.get("Price", 0)
                direction = "BUY" if quantity > 0 else "SELL"

                time_str = order_data.get("Time", "")
                try:
                    ts = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    ts = datetime.now()

                if abs(quantity) > 0:
                    orders.append(OrderRecord(
                        timestamp=ts,
                        symbol=symbol,
                        direction=direction,
                        quantity=abs(quantity),
                        fill_price=price,
                    ))

        return orders

    def _trade_log_to_orders(self, trade_log: TradeLog) -> list[OrderRecord]:
        """将 TradeLog 转为 OrderRecord 列表。"""
        orders = []
        for trade in trade_log.trades:
            # 入场
            orders.append(OrderRecord(
                timestamp=trade.entry_time,
                symbol=trade.symbol,
                direction="BUY" if trade.direction.name == "LONG" else "SELL",
                quantity=trade.quantity,
                fill_price=trade.entry_price,
                commission=trade.commission / 2,  # 粗略分摊
            ))
            # 出场
            if trade.exit_time and trade.exit_price:
                orders.append(OrderRecord(
                    timestamp=trade.exit_time,
                    symbol=trade.symbol,
                    direction="SELL" if trade.direction.name == "LONG" else "BUY",
                    quantity=trade.quantity,
                    fill_price=trade.exit_price,
                    commission=trade.commission / 2,
                ))

        # 加上未平仓交易的入场
        for symbol, trade in trade_log._open_trades.items():
            orders.append(OrderRecord(
                timestamp=trade.entry_time,
                symbol=trade.symbol,
                direction="BUY" if trade.direction.name == "LONG" else "SELL",
                quantity=trade.quantity,
                fill_price=trade.entry_price,
                commission=trade.commission,
            ))

        orders.sort(key=lambda o: o.timestamp)
        return orders

    # ── 诊断辅助方法 ──────────────────────────────────────────

    def _diagnose_equity_diff(
        self, pct_diff: float, engine_eq: float, qc_eq: float
    ) -> str:
        """根据净值偏差模式推断原因。"""
        if engine_eq > qc_eq:
            if pct_diff < 2:
                return "Engine equity higher: likely lower commission/slippage model"
            elif pct_diff < 10:
                return "Engine equity significantly higher: check fill price model (slippage too low?) or data difference"
            else:
                return "Engine equity much higher: likely fundamental difference in data or order execution timing"
        else:
            if pct_diff < 2:
                return "Engine equity lower: likely higher commission/slippage model"
            elif pct_diff < 10:
                return "Engine equity significantly lower: check if engine is missing fills or has excessive slippage"
            else:
                return "Engine equity much lower: likely fundamental difference in trade signals"

    def _diagnose_price_diff(
        self, engine_price: float, qc_price: float, pct_diff: float
    ) -> str:
        """根据价格偏差推断原因。"""
        if pct_diff < 0.002:
            return "Slippage model difference: engine applies slippage differently from QC"
        elif pct_diff < 0.01:
            return "Fill price model: engine may use different bar field (open vs close) or slippage rate"
        else:
            return "Data difference: historical OHLCV data may differ between Yahoo Finance and QC's data provider"

    def _parse_pct(self, s: str) -> float:
        """解析百分比字符串，如 '12.34%' → 12.34。"""
        try:
            return float(s.replace("%", "").replace(",", "").strip())
        except (ValueError, AttributeError):
            return 0.0
