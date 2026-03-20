"""Tests for enhanced chart functions."""

import pytest
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from engine.analytics.enhanced_charts import (
    plot_monthly_returns_heatmap,
    plot_pnl_attribution,
    plot_rolling_sharpe_beta,
)
from engine.analytics.metrics import TradeLog
from engine.core.event import Direction, FillEvent
from engine.portfolio.portfolio import Portfolio


def _portfolio_with_curve(n_days=500, initial=100_000, annual_return=0.10):
    """Create a portfolio with a realistic equity curve spanning multiple years."""
    p = Portfolio(initial_cash=initial)
    dt = datetime(2022, 1, 3)
    daily_ret = (1 + annual_return) ** (1 / 252) - 1
    eq = initial

    for i in range(n_days):
        # Add some noise
        noise = np.random.normal(daily_ret, 0.01)
        eq *= (1 + noise)
        p.equity_curve.append((dt + timedelta(days=i), eq))

    return p


def _trade_log_with_trades():
    """Create a TradeLog with mixed PnL trades across symbols."""
    tl = TradeLog()
    trades_data = [
        ("AAPL", Direction.LONG, 150.0, 160.0, 100),
        ("AAPL", Direction.LONG, 155.0, 145.0, 50),
        ("GOOG", Direction.LONG, 2800.0, 2900.0, 10),
        ("TSLA", Direction.LONG, 250.0, 230.0, 80),
        ("TSLA", Direction.SHORT, 240.0, 260.0, 40),
        ("MSFT", Direction.LONG, 300.0, 320.0, 60),
    ]

    for symbol, direction, entry, exit_p, qty in trades_data:
        # Open
        tl.on_fill(FillEvent(
            symbol=symbol, direction=direction, quantity=qty,
            fill_price=entry, commission=1.0,
            timestamp=datetime(2024, 1, 1),
        ))
        # Close
        close_dir = Direction.SHORT if direction == Direction.LONG else Direction.LONG
        tl.on_fill(FillEvent(
            symbol=symbol, direction=close_dir, quantity=qty,
            fill_price=exit_p, commission=1.0,
            timestamp=datetime(2024, 2, 1),
        ))

    return tl


def _benchmark_curve(n_days=500, initial=100_000):
    dt = datetime(2022, 1, 3)
    eq = initial
    curve = []
    for i in range(n_days):
        noise = np.random.normal(0.0003, 0.008)
        eq *= (1 + noise)
        curve.append((dt + timedelta(days=i), eq))
    return curve


class TestMonthlyReturnsHeatmap:
    def test_generates_png(self, tmp_path):
        np.random.seed(42)
        p = _portfolio_with_curve(n_days=600)
        path = tmp_path / "monthly.png"
        plot_monthly_returns_heatmap(p, path)
        assert path.exists()
        assert path.stat().st_size > 0

    def test_short_curve_no_crash(self, tmp_path):
        p = Portfolio(initial_cash=100_000)
        p.equity_curve = [
            (datetime(2024, 1, 1), 100_000),
        ]
        path = tmp_path / "monthly.png"
        plot_monthly_returns_heatmap(p, path)
        # Shouldn't crash, might not generate file with 1 point


class TestRollingSharpe:
    def test_generates_png(self, tmp_path):
        np.random.seed(42)
        p = _portfolio_with_curve(n_days=200)
        bench = _benchmark_curve(n_days=200)
        path = tmp_path / "rolling.png"
        plot_rolling_sharpe_beta(p, bench, path, window=30)
        assert path.exists()

    def test_without_benchmark(self, tmp_path):
        np.random.seed(42)
        p = _portfolio_with_curve(n_days=200)
        path = tmp_path / "rolling.png"
        plot_rolling_sharpe_beta(p, None, path, window=30)
        assert path.exists()

    def test_short_curve_skipped(self, tmp_path):
        p = Portfolio(initial_cash=100_000)
        p.equity_curve = [(datetime(2024, 1, i + 1), 100_000 + i * 100) for i in range(10)]
        path = tmp_path / "rolling.png"
        plot_rolling_sharpe_beta(p, None, path, window=63)
        # Too short, should skip gracefully
        assert not path.exists()


class TestPnLAttribution:
    def test_generates_png(self, tmp_path):
        tl = _trade_log_with_trades()
        path = tmp_path / "pnl.png"
        plot_pnl_attribution(tl, path)
        assert path.exists()
        assert path.stat().st_size > 0

    def test_empty_trades(self, tmp_path):
        tl = TradeLog()
        path = tmp_path / "pnl.png"
        plot_pnl_attribution(tl, path)
        assert not path.exists()

    def test_single_symbol(self, tmp_path):
        tl = TradeLog()
        tl.on_fill(FillEvent(
            symbol="AAPL", direction=Direction.LONG, quantity=100,
            fill_price=150.0, commission=1.0, timestamp=datetime(2024, 1, 1),
        ))
        tl.on_fill(FillEvent(
            symbol="AAPL", direction=Direction.SHORT, quantity=100,
            fill_price=160.0, commission=1.0, timestamp=datetime(2024, 2, 1),
        ))
        path = tmp_path / "pnl.png"
        plot_pnl_attribution(tl, path)
        assert path.exists()
