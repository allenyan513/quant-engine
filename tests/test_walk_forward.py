"""Tests for Walk-Forward optimizer."""

import io
import sys
import pytest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import numpy as np

from engine.core.bar_data import Bar
from engine.data.data_feed import DataFeed
from engine.strategy.base import BaseStrategy
from engine.optimize.walk_forward import (
    WalkForwardOptimizer,
    WalkForwardResult,
    WindowResult,
)
from engine.portfolio.portfolio import Portfolio


# ---------------------------------------------------------------------------
# Test fixtures: synthetic data feed + simple strategy
# ---------------------------------------------------------------------------

class SyntheticFeed(DataFeed):
    """Generates synthetic price data for any date range."""

    def __init__(self, base_price=100.0, daily_return=0.0005, volatility=0.01):
        self.base_price = base_price
        self.daily_return = daily_return
        self.volatility = volatility

    def fetch(self, symbol: str, start: str, end: str) -> list[Bar]:
        start_dt = datetime.strptime(start, "%Y-%m-%d")
        end_dt = datetime.strptime(end, "%Y-%m-%d")

        bars = []
        price = self.base_price
        np.random.seed(hash(symbol + start) % 2**31)
        dt = start_dt

        while dt <= end_dt:
            # Skip weekends
            if dt.weekday() < 5:
                ret = self.daily_return + np.random.normal(0, self.volatility)
                price *= (1 + ret)
                bars.append(Bar(
                    symbol=symbol,
                    timestamp=dt,
                    open=price * 0.999,
                    high=price * 1.01,
                    low=price * 0.99,
                    close=price,
                    volume=1_000_000,
                ))
            dt += timedelta(days=1)

        return bars


class SimpleSMAStrategy(BaseStrategy):
    """Minimal SMA strategy for testing parameter optimization."""

    def __init__(self, symbol: str = "X", fast_period: int = 10, slow_period: int = 30, size: int = 100):
        super().__init__()
        self.symbol = symbol
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.size = size

    def on_bar(self) -> None:
        if not self.bar_data.has_enough_bars(self.symbol, self.slow_period):
            return

        closes = self.bar_data.history(self.symbol, "close", self.slow_period)
        fast_ma = np.mean(closes[-self.fast_period:])
        slow_ma = np.mean(closes)

        pos = self.get_position(self.symbol)

        if fast_ma > slow_ma and pos == 0:
            self.buy(self.symbol, self.size)
        elif fast_ma < slow_ma and pos > 0:
            self.sell(self.symbol, pos)


# ---------------------------------------------------------------------------
# WalkForwardResult tests (pure data class, no backtest needed)
# ---------------------------------------------------------------------------

class TestWalkForwardResult:
    def _make_result(self, n_windows=3):
        windows = []
        for i in range(n_windows):
            windows.append(WindowResult(
                window_idx=i + 1,
                train_start=f"{2018 + i}-01-01",
                train_end=f"{2020 + i}-12-31",
                test_start=f"{2021 + i}-01-01",
                test_end=f"{2021 + i}-12-31",
                best_params={"fast_period": 10, "slow_period": 50},
                train_score=1.5 - i * 0.3,
                test_metrics={
                    "sharpe_ratio": 0.8 - i * 0.2,
                    "total_return": 0.15 - i * 0.05,
                    "max_drawdown": -0.10 - i * 0.02,
                    "cagr": 0.12 - i * 0.03,
                },
                test_portfolio=Portfolio(initial_cash=100_000),
            ))
        return WalkForwardResult(
            strategy_name="TestStrategy",
            param_grid={"fast_period": [5, 10, 20], "slow_period": [30, 50, 100]},
            fixed_params={"symbol": "X", "size": 100},
            score_metric="sharpe_ratio",
            windows=windows,
            total_combos=9,
        )

    def test_test_returns(self):
        result = self._make_result()
        assert len(result.test_returns) == 3
        assert result.test_returns[0] == pytest.approx(0.15)

    def test_test_sharpes(self):
        result = self._make_result()
        assert len(result.test_sharpes) == 3
        assert result.test_sharpes[0] == pytest.approx(0.8)

    def test_param_stability(self):
        result = self._make_result()
        stability = result.param_stability
        assert "fast_period" in stability
        assert stability["fast_period"]["most_common"] == 10
        assert stability["fast_period"]["frequency"] == 1.0  # all windows chose 10

    def test_print_summary(self):
        result = self._make_result()
        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        result.print_summary()
        sys.stdout = old_stdout
        output = buf.getvalue()
        assert "Walk-Forward" in output
        assert "TestStrategy" in output
        assert "PASS" in output or "MARGINAL" in output or "FAIL" in output

    def test_save_report(self, tmp_path):
        result = self._make_result()
        # Add equity curves so OOS chart works
        for w in result.windows:
            dt = datetime(2024, 1, 1)
            w.test_portfolio.equity_curve = [
                (dt + timedelta(days=i), 100_000 + i * 100)
                for i in range(60)
            ]
            w.param_scores = [
                ({"fast_period": f, "slow_period": s}, np.random.random())
                for f in [5, 10, 20] for s in [30, 50, 100]
            ]

        out = result.save_report(output_dir=tmp_path / "wf_test")
        assert (out / "walk_forward_report.txt").exists()
        assert (out / "param_heatmap.png").exists()
        assert (out / "oos_equity.png").exists()
        assert (out / "window_comparison.png").exists()
        assert (out / "summary.csv").exists()


# ---------------------------------------------------------------------------
# Window generation tests
# ---------------------------------------------------------------------------

class TestWindowGeneration:
    def test_basic_windows(self):
        optimizer = WalkForwardOptimizer.__new__(WalkForwardOptimizer)
        optimizer.start = "2015-01-01"
        optimizer.end = "2025-12-31"
        optimizer.train_years = 3
        optimizer.test_years = 1

        windows = optimizer._generate_windows()
        assert len(windows) > 0

        # First window: train 2015~2017, test 2018
        assert windows[0] == ("2015-01-01", "2018-12-31", "2018-01-01", "2019-12-31")

    def test_no_windows_if_range_too_short(self):
        optimizer = WalkForwardOptimizer.__new__(WalkForwardOptimizer)
        optimizer.start = "2023-01-01"
        optimizer.end = "2024-12-31"
        optimizer.train_years = 3
        optimizer.test_years = 1

        windows = optimizer._generate_windows()
        assert len(windows) == 0

    def test_sliding_by_test_years(self):
        optimizer = WalkForwardOptimizer.__new__(WalkForwardOptimizer)
        optimizer.start = "2010-01-01"
        optimizer.end = "2025-12-31"
        optimizer.train_years = 3
        optimizer.test_years = 2

        windows = optimizer._generate_windows()
        # Check windows slide by test_years (2)
        if len(windows) >= 2:
            y1 = int(windows[0][0][:4])
            y2 = int(windows[1][0][:4])
            assert y2 - y1 == 2


# ---------------------------------------------------------------------------
# Integration test with synthetic data
# ---------------------------------------------------------------------------

class TestWalkForwardIntegration:
    def test_run_with_synthetic_data(self):
        """Full walk-forward run with synthetic data (no network needed)."""
        feed = SyntheticFeed()

        optimizer = WalkForwardOptimizer(
            strategy_cls=SimpleSMAStrategy,
            param_grid={
                "fast_period": [5, 10],
                "slow_period": [20, 30],
            },
            fixed_params={"symbol": "X", "size": 50},
            symbols=["X"],
            train_years=2,
            test_years=1,
            start="2018-01-01",
            end="2023-12-31",
            score_metric="sharpe_ratio",
            initial_cash=100_000,
            verbose=False,
        )
        # Patch the feed
        optimizer._feed = feed

        result = optimizer.run()

        assert isinstance(result, WalkForwardResult)
        assert len(result.windows) > 0
        assert result.total_combos == 4  # 2 * 2

        for w in result.windows:
            assert w.best_params is not None
            assert "fast_period" in w.best_params
            assert "slow_period" in w.best_params
            assert w.test_metrics is not None
            assert "sharpe_ratio" in w.test_metrics

    def test_run_raises_on_no_windows(self):
        feed = SyntheticFeed()
        optimizer = WalkForwardOptimizer(
            strategy_cls=SimpleSMAStrategy,
            param_grid={"fast_period": [10]},
            fixed_params={"symbol": "X"},
            symbols=["X"],
            train_years=5,
            test_years=3,
            start="2023-01-01",
            end="2024-12-31",
            verbose=False,
        )
        optimizer._feed = feed

        with pytest.raises(ValueError, match="无法生成窗口"):
            optimizer.run()
