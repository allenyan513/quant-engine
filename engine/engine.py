"""
BacktestEngine — 主事件循环。

职责:
1. 加载数据 → BarData
2. 逐 bar 推进时间
3. 驱动 Strategy → Broker → Portfolio 的事件流转
"""

from __future__ import annotations

from datetime import datetime

from engine.analytics.metrics import TradeLog
from engine.core.bar_data import Bar, BarData
from engine.data.data_feed import DataFeed
from engine.execution.broker import SimulatedBroker
from engine.execution.fee_model import FeeModel
from engine.portfolio.portfolio import Portfolio
from engine.risk.risk_manager import RiskManager
from engine.strategy.base import BaseStrategy

# Lazy imports for benchmark
_benchmark_cache: dict[str, list[tuple[datetime, float]]] = {}


class BacktestEngine:
    """回测引擎。"""

    def __init__(
        self,
        strategy: BaseStrategy,
        data_feed: DataFeed,
        symbols: list[str],
        start: str,
        end: str,
        initial_cash: float = 100_000.0,
        fee_model: FeeModel | None = None,
        slippage_rate: float = 0.0005,
        # 向后兼容
        commission_rate: float | None = None,
        risk_manager: RiskManager | None = None,
    ) -> None:
        self.strategy = strategy
        self.data_feed = data_feed
        self.symbols = symbols
        self.start = start
        self.end = end
        self.risk_manager = risk_manager

        self.bar_data = BarData()
        self.portfolio = Portfolio(initial_cash=initial_cash)
        self.trade_log = TradeLog()
        self.broker = SimulatedBroker(
            fee_model=fee_model,
            slippage_rate=slippage_rate,
            commission_rate=commission_rate,
        )

        # Exposure & Turnover time series
        self.exposure_curve: list[tuple[datetime, float, float]] = []
        self.turnover_curve: list[tuple[datetime, float]] = []
        self._prev_holdings: dict[str, float] = {}

        # Auto SPY benchmark (populated after run)
        self.benchmark_curve: list[tuple[datetime, float]] | None = None

    def run(self) -> Portfolio:
        """
        运行回测，返回 Portfolio。

        流程:
        1. 加载所有标的数据到 BarData
        2. 绑定策略
        3. 逐 bar 循环:
           a. 推进数据
           b. 撮合待处理订单（上一轮的）
           c. 更新组合净值
           d. 调用策略 on_bar()
           e. 收集策略产生的订单提交给 Broker
        """
        # Step 1: 加载数据
        print(f"Loading data for {self.symbols}...")
        for symbol in self.symbols:
            bars = self.data_feed.fetch(symbol, self.start, self.end)
            self.bar_data.add_symbol_bars(symbol, bars)
            print(f"  {symbol}: {len(bars)} bars loaded")

        # Step 2: 绑定
        self.strategy._bind(self.bar_data, self.portfolio)
        self.strategy.initialize()

        # Step 3: 事件循环
        # 找出所有标的的最大 bar 数量来确定循环次数
        max_bars = max(
            len(self.bar_data._bars[s]) for s in self.symbols
        )

        print(f"Running backtest: {max_bars} bars...")

        for i in range(max_bars):
            # 3a. 推进所有标的的数据
            current_bars: dict[str, Bar] = {}
            for symbol in self.symbols:
                bar = self.bar_data.advance(symbol)
                if bar is not None:
                    current_bars[symbol] = bar

            if not current_bars:
                break

            # 3b. 撮合上一轮的待处理订单
            fills = self.broker.fill_orders(self.bar_data)
            for fill in fills:
                self.portfolio.on_fill(fill)
                self.trade_log.on_fill(fill)
                self.strategy.on_fill(fill)

            # 3c. 更新组合净值
            timestamp = list(current_bars.values())[0].timestamp
            self.portfolio.update_equity(self.bar_data, timestamp)

            # 3c-2. 记录 Exposure & Turnover
            equity = self.portfolio.equity
            if equity > 0:
                long_val = 0.0
                short_val = 0.0
                curr_holdings: dict[str, float] = {}
                for sym, pos in self.portfolio.positions.items():
                    if pos.quantity != 0:
                        bar = self.bar_data.current(sym)
                        if bar:
                            mv = pos.quantity * bar.close
                            curr_holdings[sym] = mv
                            if mv > 0:
                                long_val += mv
                            else:
                                short_val += mv
                self.exposure_curve.append((
                    timestamp, long_val / equity, short_val / equity,
                ))
                # Turnover = sum(|delta_holdings|) / (2 * equity)
                all_syms = set(curr_holdings) | set(self._prev_holdings)
                delta = sum(
                    abs(curr_holdings.get(s, 0.0) - self._prev_holdings.get(s, 0.0))
                    for s in all_syms
                )
                self.turnover_curve.append((timestamp, delta / (2 * equity)))
                self._prev_holdings = curr_holdings

            # 3d-0. 风控 on_bar (回撤熔断清仓等)
            if self.risk_manager is not None:
                risk_orders = self.risk_manager.on_bar(
                    self.portfolio, self.bar_data,
                )
                for order in risk_orders:
                    self.broker.submit_order(order)

            # 3d. 检查止损管理器
            stop_orders = self.strategy._collect_stop_orders()
            for order in stop_orders:
                self.broker.submit_order(order)

            # 3e. 调用策略
            self.strategy.on_bar()

            # 3f. 收集订单 (经过风控过滤)
            orders = self.strategy._collect_orders()
            for order in orders:
                self._submit_with_risk_check(order)

        # 自动获取 SPY 基准
        self.benchmark_curve = self._fetch_spy_benchmark()

        print(f"Backtest complete. Final equity: ${self.portfolio.equity:,.2f}")
        return self.portfolio

    def _submit_with_risk_check(self, order) -> None:
        """提交订单，如果有 RiskManager 则先做风控检查。"""
        if self.risk_manager is None:
            self.broker.submit_order(order)
            return

        result = self.risk_manager.check_order(
            order, self.portfolio, self.bar_data,
        )
        if result.approved:
            self.broker.submit_order(
                result.adjusted_order if result.adjusted_order else order
            )

    def _fetch_spy_benchmark(self) -> list[tuple[datetime, float]] | None:
        """自动获取 SPY 数据，构建基准净值曲线（与 QC 一致）。"""
        try:
            from engine.data import CachedFeed, YFinanceFeed

            cache_key = f"SPY_{self.start}_{self.end}"
            if cache_key in _benchmark_cache:
                return _benchmark_cache[cache_key]

            feed = CachedFeed(YFinanceFeed())
            bars = feed.fetch("SPY", self.start, self.end)
            if not bars:
                return None

            # 用收盘价构建归一化净值曲线（初始值 = 策略初始资金）
            initial = self.portfolio.initial_cash
            base_price = bars[0].close
            curve = [
                (bar.timestamp, initial * bar.close / base_price)
                for bar in bars
            ]
            _benchmark_cache[cache_key] = curve
            return curve
        except Exception:
            return None
