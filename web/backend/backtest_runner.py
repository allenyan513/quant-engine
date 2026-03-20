"""Backtest runner — executes generated strategy code with progress streaming."""

from __future__ import annotations

import importlib
import sys
import traceback
import types
from datetime import datetime
from typing import Any, Callable

import numpy as np


def _make_serializable(v: Any) -> Any:
    """Convert numpy types to Python native types for JSON serialization."""
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return float(v)
    if isinstance(v, np.ndarray):
        return v.tolist()
    if isinstance(v, float) and (np.isnan(v) or np.isinf(v)):
        return None
    return v


def _serialize_dict(d: dict) -> dict:
    return {k: _make_serializable(v) for k, v in d.items()}


def load_strategy_class(code: str) -> type:
    """
    Dynamically load a strategy class from code string.
    Returns the first BaseStrategy subclass found.
    """
    # Create a temporary module
    mod = types.ModuleType("_dynamic_strategy")
    mod.__file__ = "<generated>"

    # Make engine importable
    exec(code, mod.__dict__)

    # Find the strategy class (first BaseStrategy subclass)
    from engine.strategy.base import BaseStrategy

    for name, obj in mod.__dict__.items():
        if (
            isinstance(obj, type)
            and issubclass(obj, BaseStrategy)
            and obj is not BaseStrategy
        ):
            return obj

    raise ValueError("No BaseStrategy subclass found in the generated code.")


def run_backtest(
    code: str,
    symbols: list[str],
    start: str,
    end: str,
    initial_cash: float = 100_000.0,
    fee_model_name: str = "per_share",
    slippage_rate: float = 0.0005,
    on_progress: Callable[[str, float], None] | None = None,
) -> dict:
    """
    Execute a backtest with the given strategy code and parameters.

    Args:
        code: Python source code containing a BaseStrategy subclass
        symbols: List of ticker symbols
        start/end: Date range strings
        initial_cash: Starting capital
        fee_model_name: "per_share" | "percentage" | "zero"
        slippage_rate: Slippage rate
        on_progress: Callback(message, progress_pct) for progress updates

    Returns:
        dict with metrics, trades, equity_curve, benchmark_curve, drawdown_curve
    """
    def progress(msg: str, pct: float) -> None:
        if on_progress:
            on_progress(msg, pct)

    progress("Loading strategy code...", 0.05)

    # 1. Load strategy class
    strategy_cls = load_strategy_class(code)
    progress(f"Strategy class loaded: {strategy_cls.__name__}", 0.10)

    # 2. Instantiate strategy
    strategy = strategy_cls(symbols=symbols)
    progress("Strategy instantiated.", 0.15)

    # 3. Set up data feed and fee model
    from engine.data.cached_feed import CachedFeed
    from engine.data.data_feed import YFinanceFeed
    from engine.execution.fee_model import PerShareFeeModel, PercentageFeeModel, ZeroFeeModel

    fee_models = {
        "per_share": PerShareFeeModel,
        "percentage": PercentageFeeModel,
        "zero": ZeroFeeModel,
    }
    fee_model = fee_models.get(fee_model_name, PerShareFeeModel)()

    data_feed = CachedFeed(YFinanceFeed())
    progress("Data feed ready.", 0.20)

    # 4. Create and run engine
    from engine.engine import BacktestEngine

    engine = BacktestEngine(
        strategy=strategy,
        data_feed=data_feed,
        symbols=symbols,
        start=start,
        end=end,
        initial_cash=initial_cash,
        fee_model=fee_model,
        slippage_rate=slippage_rate,
    )

    # Monkey-patch the engine run loop to report progress
    original_run = engine.run

    def patched_run():
        # Load data
        progress("Fetching market data...", 0.25)
        for sym in engine.symbols:
            bars = engine.data_feed.fetch(sym, engine.start, engine.end)
            engine.bar_data.add_symbol_bars(sym, bars)
            progress(f"  {sym}: {len(bars)} bars loaded", 0.30)

        engine.strategy._bind(engine.bar_data, engine.portfolio)
        engine.strategy.initialize()

        max_bars = max(len(engine.bar_data._bars[s]) for s in engine.symbols)
        progress(f"Running backtest: {max_bars} bars...", 0.35)

        for i in range(max_bars):
            # Progress update every 10%
            if max_bars > 0 and i % max(1, max_bars // 20) == 0:
                pct = 0.35 + 0.55 * (i / max_bars)
                progress(f"Processing bar {i+1}/{max_bars}...", pct)

            current_bars = {}
            for symbol in engine.symbols:
                bar = engine.bar_data.advance(symbol)
                if bar is not None:
                    current_bars[symbol] = bar

            if not current_bars:
                break

            fills = engine.broker.fill_orders(engine.bar_data)
            for fill in fills:
                engine.portfolio.on_fill(fill)
                engine.trade_log.on_fill(fill)
                engine.strategy.on_fill(fill)

            from engine.core.bar_data import Bar
            timestamp = list(current_bars.values())[0].timestamp
            engine.portfolio.update_equity(engine.bar_data, timestamp)

            # Exposure & turnover
            equity = engine.portfolio.equity
            if equity > 0:
                long_val = 0.0
                short_val = 0.0
                curr_holdings = {}
                for sym, pos in engine.portfolio.positions.items():
                    if pos.quantity != 0:
                        b = engine.bar_data.current(sym)
                        if b:
                            mv = pos.quantity * b.close
                            curr_holdings[sym] = mv
                            if mv > 0:
                                long_val += mv
                            else:
                                short_val += mv
                engine.exposure_curve.append((timestamp, long_val / equity, short_val / equity))
                all_syms = set(curr_holdings) | set(engine._prev_holdings)
                delta = sum(
                    abs(curr_holdings.get(s, 0.0) - engine._prev_holdings.get(s, 0.0))
                    for s in all_syms
                )
                engine.turnover_curve.append((timestamp, delta / (2 * equity)))
                engine._prev_holdings = curr_holdings

            if engine.risk_manager is not None:
                risk_orders = engine.risk_manager.on_bar(engine.portfolio, engine.bar_data)
                for order in risk_orders:
                    engine.broker.submit_order(order)

            stop_orders = engine.strategy._collect_stop_orders()
            for order in stop_orders:
                engine.broker.submit_order(order)

            engine.strategy.on_bar()

            orders = engine.strategy._collect_orders()
            for order in orders:
                engine._submit_with_risk_check(order)

        progress("Fetching SPY benchmark...", 0.92)
        engine.benchmark_curve = engine._fetch_spy_benchmark()

        progress("Backtest complete!", 0.95)
        return engine.portfolio

    patched_run()

    # 5. Collect results
    progress("Computing metrics...", 0.96)

    from engine.analytics.metrics import calculate_metrics

    metrics = calculate_metrics(
        engine.portfolio,
        benchmark_curve=engine.benchmark_curve,
    )
    metrics = _serialize_dict(metrics)

    trade_summary = _serialize_dict(engine.trade_log.summary())

    # Trades list
    trades = []
    for t in engine.trade_log.trades:
        trades.append({
            "symbol": t.symbol,
            "direction": t.direction.name,
            "entry_time": t.entry_time.isoformat() if t.entry_time else "",
            "entry_price": round(t.entry_price, 2),
            "exit_time": t.exit_time.isoformat() if t.exit_time else "",
            "exit_price": round(t.exit_price, 2) if t.exit_price else 0,
            "quantity": t.quantity,
            "net_pnl": round(t.net_pnl, 2),
            "return_pct": round(t.return_pct * 100, 2),
            "holding_days": t.holding_days,
        })

    # Equity curve: [[timestamp_ms, value], ...]
    equity_curve = [
        [int(ts.timestamp() * 1000), round(val, 2)]
        for ts, val in engine.portfolio.equity_curve
    ]

    # Benchmark curve
    benchmark_curve = []
    if engine.benchmark_curve:
        benchmark_curve = [
            [int(ts.timestamp() * 1000), round(val, 2)]
            for ts, val in engine.benchmark_curve
        ]

    # Drawdown curve
    equities = np.array([v for _, v in engine.portfolio.equity_curve])
    peak = np.maximum.accumulate(equities)
    dd = ((equities - peak) / peak * 100).tolist()
    drawdown_curve = [
        [int(ts.timestamp() * 1000), round(d, 2)]
        for (ts, _), d in zip(engine.portfolio.equity_curve, dd)
    ]

    progress("Done!", 1.0)

    return {
        "metrics": metrics,
        "trade_summary": trade_summary,
        "trades": trades,
        "equity_curve": equity_curve,
        "benchmark_curve": benchmark_curve,
        "drawdown_curve": drawdown_curve,
    }
