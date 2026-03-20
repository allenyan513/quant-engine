"""
Walk-Forward 参数优化 — 滚动训练/测试，验证策略是否过拟合。

流程:
1. 把回测区间切成滚动窗口: [train_window][test_window] → 向前滑动
2. 每个训练窗口: 穷举参数网格，选 score_metric 最优的参数
3. 用最优参数跑测试窗口 (Out-of-Sample)
4. 拼接所有测试期结果 → 策略的真实表现

用法:
    optimizer = WalkForwardOptimizer(
        strategy_cls=SMACrossover,
        param_grid={"fast_period": [5, 10, 20], "slow_period": [50, 100, 200]},
        fixed_params={"symbol": "AAPL", "size": 100},
        symbols=["AAPL"],
        train_years=3, test_years=1,
        start="2015-01-01", end="2025-12-31",
    )
    result = optimizer.run()
    result.save_report()
"""

from __future__ import annotations

import itertools
import io
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np

from engine.analytics.metrics import calculate_metrics, TradeLog
from engine.data import CachedFeed, YFinanceFeed
from engine.engine import BacktestEngine
from engine.portfolio.portfolio import Portfolio
from engine.strategy.base import BaseStrategy


@dataclass
class WindowResult:
    """单个滚动窗口的结果。"""
    window_idx: int
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    best_params: dict
    train_score: float
    test_metrics: dict
    test_portfolio: Portfolio
    # 训练期所有参数的得分 (用于热力图)
    param_scores: list[tuple[dict, float]] = field(default_factory=list)


@dataclass
class WalkForwardResult:
    """Walk-Forward 完整结果。"""
    strategy_name: str
    param_grid: dict[str, list]
    fixed_params: dict
    score_metric: str
    windows: list[WindowResult]
    total_combos: int

    @property
    def test_returns(self) -> list[float]:
        return [w.test_metrics.get("total_return", 0) for w in self.windows]

    @property
    def test_sharpes(self) -> list[float]:
        return [w.test_metrics.get("sharpe_ratio", 0) for w in self.windows]

    @property
    def param_stability(self) -> dict:
        """参数稳定性: 每个参数值出现的次数。"""
        stability = {}
        for key in self.param_grid:
            values = [w.best_params[key] for w in self.windows]
            counter = Counter(values)
            most_common_val, most_common_count = counter.most_common(1)[0]
            stability[key] = {
                "most_common": most_common_val,
                "frequency": most_common_count / len(self.windows),
                "distribution": dict(counter),
            }
        return stability

    def print_summary(self) -> None:
        """打印 Walk-Forward 结果摘要。"""
        n = len(self.windows)
        print(f"\n{'='*85}")
        print(f"  Walk-Forward Optimization: {self.strategy_name}")
        print(f"  {self.total_combos} param combos × {n} windows = "
              f"{self.total_combos * n} backtests")
        print(f"  Score metric: {self.score_metric}")
        print(f"{'='*85}")

        # Header
        print(f"\n  {'#':>2}  {'Train Period':<25} {'Test Period':<25} "
              f"{'Best Params':<30} {'Train':>7} {'Test':>7} {'Test Ret':>9}")
        print("  " + "-" * 108)

        for w in self.windows:
            params_str = ", ".join(f"{k}={v}" for k, v in w.best_params.items())
            test_score = w.test_metrics.get(self.score_metric, 0)
            test_ret = w.test_metrics.get("total_return", 0)
            print(f"  {w.window_idx:>2}  "
                  f"{w.train_start} ~ {w.train_end}   "
                  f"{w.test_start} ~ {w.test_end}   "
                  f"{params_str:<30} "
                  f"{w.train_score:>7.2f} "
                  f"{test_score:>7.2f} "
                  f"{test_ret:>8.1%}")

        print("  " + "-" * 108)

        # Combined OOS stats
        avg_sharpe = np.mean(self.test_sharpes)
        avg_return = np.mean(self.test_returns)
        positive_windows = sum(1 for r in self.test_returns if r > 0)

        print(f"\n  Combined OOS:  Avg Sharpe {avg_sharpe:.2f}  |  "
              f"Avg Return {avg_return:.1%}  |  "
              f"Win {positive_windows}/{n} windows")

        # Param stability
        stability = self.param_stability
        print(f"\n  Parameter Stability:")
        for key, info in stability.items():
            pct = info['frequency']
            val = info['most_common']
            dist_str = ", ".join(f"{v}({c}x)" for v, c in
                                sorted(info['distribution'].items()))
            print(f"    {key}: most_common={val} ({pct:.0%})  [{dist_str}]")

        # Verdict
        print()
        if avg_sharpe > 0.3 and positive_windows >= n * 0.6:
            print("  >> PASS: 策略在未知数据上表现稳定")
        elif avg_sharpe > 0 and positive_windows >= n * 0.5:
            print("  >> MARGINAL: 策略有一定效果，但不够稳健")
        else:
            print("  >> FAIL: 策略可能过拟合，OOS 表现差")
        print(f"{'='*85}")

    def save_report(self, output_dir: str | Path | None = None) -> Path:
        """保存完整报告到文件。"""
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.ticker import FuncFormatter

        if output_dir is None:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_dir = Path("outputs") / f"wf_{ts}"
        else:
            output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # 1. Text report
        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        self.print_summary()
        sys.stdout = old_stdout
        (output_dir / "walk_forward_report.txt").write_text(
            buf.getvalue(), encoding="utf-8")

        # 2. Parameter heatmap (if 2D grid)
        opt_keys = [k for k in self.param_grid if len(self.param_grid[k]) > 1]
        if len(opt_keys) >= 2:
            self._plot_heatmap(output_dir / "param_heatmap.png", opt_keys[0], opt_keys[1])

        # 3. OOS equity curve (stitched test periods)
        self._plot_oos_equity(output_dir / "oos_equity.png")

        # 4. Window comparison bar chart
        self._plot_window_bars(output_dir / "window_comparison.png")

        # 5. Summary CSV
        self._write_csv(output_dir / "summary.csv")

        plt.close("all")

        print(f"\nWalk-Forward report saved to {output_dir}/")
        print(f"  walk_forward_report.txt  — 文本报告")
        if len(opt_keys) >= 2:
            print(f"  param_heatmap.png        — 参数稳定性热力图")
        print(f"  oos_equity.png           — OOS 拼接净值曲线")
        print(f"  window_comparison.png    — 窗口对比图")
        print(f"  summary.csv              — 逐窗口明细")

        return output_dir

    def _plot_heatmap(self, path: Path, key_x: str, key_y: str) -> None:
        """参数热力图: 平均所有窗口的训练期得分。"""
        import matplotlib.pyplot as plt

        vals_x = sorted(self.param_grid[key_x])
        vals_y = sorted(self.param_grid[key_y])

        # Accumulate scores across all windows
        score_sum: dict[tuple, float] = {}
        score_cnt: dict[tuple, int] = {}

        for w in self.windows:
            for params, score in w.param_scores:
                k = (params[key_x], params[key_y])
                score_sum[k] = score_sum.get(k, 0) + score
                score_cnt[k] = score_cnt.get(k, 0) + 1

        grid = np.full((len(vals_y), len(vals_x)), np.nan)
        for iy, vy in enumerate(vals_y):
            for ix, vx in enumerate(vals_x):
                k = (vx, vy)
                if k in score_sum and score_cnt[k] > 0:
                    grid[iy, ix] = score_sum[k] / score_cnt[k]

        fig, ax = plt.subplots(figsize=(8, 6))
        im = ax.imshow(grid, cmap="RdYlGn", aspect="auto", origin="lower")
        ax.set_xticks(range(len(vals_x)))
        ax.set_xticklabels(vals_x)
        ax.set_yticks(range(len(vals_y)))
        ax.set_yticklabels(vals_y)
        ax.set_xlabel(key_x)
        ax.set_ylabel(key_y)
        ax.set_title(f"Avg {self.score_metric} across all train windows")
        fig.colorbar(im, ax=ax, label=self.score_metric)

        # Annotate values
        for iy in range(len(vals_y)):
            for ix in range(len(vals_x)):
                v = grid[iy, ix]
                if not np.isnan(v):
                    color = "white" if abs(v) > (np.nanmax(grid) - np.nanmin(grid)) * 0.6 + np.nanmin(grid) else "black"
                    ax.text(ix, iy, f"{v:.2f}", ha="center", va="center",
                            fontsize=8, color=color)

        # Mark best params from each window
        for w in self.windows:
            vx, vy = w.best_params.get(key_x), w.best_params.get(key_y)
            if vx in vals_x and vy in vals_y:
                ix, iy = vals_x.index(vx), vals_y.index(vy)
                ax.plot(ix, iy, "k*", markersize=10, markeredgecolor="white",
                        markeredgewidth=0.5)

        plt.tight_layout()
        fig.savefig(path, dpi=150, bbox_inches="tight")
        plt.close(fig)

    def _plot_oos_equity(self, path: Path) -> None:
        """拼接所有测试期净值曲线。"""
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 7),
                                        gridspec_kw={"height_ratios": [3, 1.2]},
                                        sharex=True)

        all_ts, all_eq = [], []
        colors = plt.cm.tab10(np.linspace(0, 1, len(self.windows)))

        for w, color in zip(self.windows, colors):
            ts = [t for t, _ in w.test_portfolio.equity_curve]
            eq = np.array([e for _, e in w.test_portfolio.equity_curve])
            if eq[0] > 0:
                norm = eq / eq[0] * 100
            else:
                norm = eq
            ax1.plot(ts, norm, color=color, linewidth=1.5, alpha=0.8,
                     label=f"W{w.window_idx} ({w.test_start[:4]})")
            all_ts.extend(ts)
            all_eq.extend(norm.tolist())

            # Return bar for bottom chart
            ret = w.test_metrics.get("total_return", 0)
            mid = ts[len(ts) // 2] if ts else ts[0]
            bar_color = "#4CAF50" if ret >= 0 else "#F44336"
            ax2.bar(mid, ret * 100, width=200, color=bar_color, alpha=0.7,
                    edgecolor="white", linewidth=0.5)

        ax1.axhline(100, color="gray", linestyle="--", linewidth=0.8, alpha=0.5)
        ax1.set_ylabel("Growth of $100 (per window)")
        ax1.set_title("Out-of-Sample Equity Curves (per test window)")
        ax1.legend(loc="upper left", fontsize=8, ncol=4)
        ax1.grid(True, alpha=0.3)

        ax2.axhline(0, color="gray", linewidth=0.8)
        ax2.set_ylabel("Return (%)")
        ax2.grid(True, alpha=0.3)

        ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
        plt.xticks(rotation=45)
        plt.tight_layout()
        fig.savefig(path, dpi=150, bbox_inches="tight")
        plt.close(fig)

    def _plot_window_bars(self, path: Path) -> None:
        """训练 vs 测试 Sharpe 对比柱状图。"""
        import matplotlib.pyplot as plt

        n = len(self.windows)
        x = np.arange(n)
        width = 0.35

        train_scores = [w.train_score for w in self.windows]
        test_scores = [w.test_metrics.get(self.score_metric, 0) for w in self.windows]

        fig, ax = plt.subplots(figsize=(10, 4.5))
        bars1 = ax.bar(x - width / 2, train_scores, width, label="Train (In-Sample)",
                        color="#2196F3", alpha=0.8)
        bars2 = ax.bar(x + width / 2, test_scores, width, label="Test (Out-of-Sample)",
                        color="#FF9800", alpha=0.8)

        ax.set_xlabel("Window")
        ax.set_ylabel(self.score_metric)
        ax.set_title(f"Train vs Test {self.score_metric} per Window")
        ax.set_xticks(x)
        labels = [f"W{w.window_idx}\n{w.test_start[:4]}" for w in self.windows]
        ax.set_xticklabels(labels)
        ax.legend()
        ax.axhline(0, color="gray", linewidth=0.8)
        ax.grid(True, alpha=0.3, axis="y")

        plt.tight_layout()
        fig.savefig(path, dpi=150, bbox_inches="tight")
        plt.close(fig)

    def _write_csv(self, path: Path) -> None:
        """逐窗口明细 CSV。"""
        import csv
        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            header = ["window", "train_start", "train_end", "test_start", "test_end"]
            param_keys = sorted(self.param_grid.keys())
            header += [f"best_{k}" for k in param_keys]
            header += ["train_score", "test_sharpe", "test_return",
                        "test_max_dd", "test_cagr"]
            writer.writerow(header)
            for w in self.windows:
                row = [w.window_idx, w.train_start, w.train_end,
                       w.test_start, w.test_end]
                row += [w.best_params.get(k, "") for k in param_keys]
                row += [
                    f"{w.train_score:.4f}",
                    f"{w.test_metrics.get('sharpe_ratio', 0):.4f}",
                    f"{w.test_metrics.get('total_return', 0):.4f}",
                    f"{w.test_metrics.get('max_drawdown', 0):.4f}",
                    f"{w.test_metrics.get('cagr', 0):.4f}",
                ]
                writer.writerow(row)


class WalkForwardOptimizer:
    """
    Walk-Forward 参数优化器。

    Args:
        strategy_cls: 策略类 (BaseStrategy 子类)
        param_grid: 参数搜索空间, e.g. {"fast_period": [5, 10, 20]}
        fixed_params: 不参与优化的固定参数, e.g. {"symbol": "AAPL", "size": 100}
        symbols: 回测标的列表
        train_years: 训练窗口年数
        test_years: 测试窗口年数
        start: 整体起始日期
        end: 整体结束日期
        score_metric: 优化目标指标 (calculate_metrics 输出的 key)
        initial_cash: 初始资金
        fee_model: 手续费模型
        slippage_rate: 滑点比例
        verbose: 是否打印进度
    """

    def __init__(
        self,
        strategy_cls: type[BaseStrategy],
        param_grid: dict[str, list],
        fixed_params: dict | None = None,
        symbols: list[str] | None = None,
        train_years: int = 3,
        test_years: int = 1,
        start: str = "2015-01-01",
        end: str = "2025-12-31",
        score_metric: str = "sharpe_ratio",
        initial_cash: float = 100_000.0,
        fee_model=None,
        slippage_rate: float = 0.0005,
        verbose: bool = True,
    ) -> None:
        self.strategy_cls = strategy_cls
        self.param_grid = param_grid
        self.fixed_params = fixed_params or {}
        self.symbols = symbols or []
        self.train_years = train_years
        self.test_years = test_years
        self.start = start
        self.end = end
        self.score_metric = score_metric
        self.initial_cash = initial_cash
        self.fee_model = fee_model
        self.slippage_rate = slippage_rate
        self.verbose = verbose

        # 生成所有参数组合
        keys = sorted(param_grid.keys())
        values = [param_grid[k] for k in keys]
        self._param_combos = [
            dict(zip(keys, combo)) for combo in itertools.product(*values)
        ]

        # 预加载数据 (避免每次回测重复下载)
        self._feed = CachedFeed(YFinanceFeed())

    def _generate_windows(self) -> list[tuple[str, str, str, str]]:
        """生成滚动窗口列表: [(train_start, train_end, test_start, test_end), ...]"""
        start_year = int(self.start[:4])
        end_year = int(self.end[:4])

        windows = []
        train_start_year = start_year

        while True:
            train_end_year = train_start_year + self.train_years
            test_start_year = train_end_year
            test_end_year = test_start_year + self.test_years

            if test_end_year > end_year:
                break

            windows.append((
                f"{train_start_year}-01-01",
                f"{train_end_year}-12-31",
                f"{test_start_year}-01-01",
                f"{test_end_year}-12-31",
            ))
            train_start_year += self.test_years  # slide by test_years

        return windows

    def _run_single_backtest(
        self, params: dict, start: str, end: str, quiet: bool = True,
    ) -> tuple[Portfolio, dict, TradeLog]:
        """运行单次回测，返回 (portfolio, metrics, trade_log)。"""
        all_params = {**self.fixed_params, **params}
        strategy = self.strategy_cls(**all_params)

        engine = BacktestEngine(
            strategy=strategy,
            data_feed=self._feed,
            symbols=self.symbols,
            start=start,
            end=end,
            initial_cash=self.initial_cash,
            fee_model=self.fee_model,
            slippage_rate=self.slippage_rate,
        )

        # Suppress print output during grid search
        if quiet:
            old_stdout = sys.stdout
            sys.stdout = io.StringIO()

        try:
            portfolio = engine.run()
        finally:
            if quiet:
                sys.stdout = old_stdout

        metrics = calculate_metrics(portfolio)
        return portfolio, metrics, engine.trade_log

    def run(self) -> WalkForwardResult:
        """运行 Walk-Forward 优化，返回结果。"""
        windows = self._generate_windows()

        if not windows:
            raise ValueError(
                f"无法生成窗口: start={self.start}, end={self.end}, "
                f"train={self.train_years}y, test={self.test_years}y"
            )

        n_combos = len(self._param_combos)
        n_windows = len(windows)

        if self.verbose:
            print(f"\nWalk-Forward Optimization")
            print(f"  Strategy: {self.strategy_cls.__name__}")
            print(f"  Params: {n_combos} combinations")
            print(f"  Windows: {n_windows}")
            print(f"  Total backtests: {n_combos * n_windows + n_windows}")
            print(f"  Score: {self.score_metric}")
            print()

        results: list[WindowResult] = []

        for w_idx, (tr_start, tr_end, te_start, te_end) in enumerate(windows):
            if self.verbose:
                print(f"  Window {w_idx + 1}/{n_windows}: "
                      f"train {tr_start}~{tr_end}  test {te_start}~{te_end}")

            # ── 训练期: 穷举参数 ──
            param_scores: list[tuple[dict, float]] = []
            best_score = -np.inf
            best_params = self._param_combos[0]

            for i, params in enumerate(self._param_combos):
                try:
                    _, metrics, _ = self._run_single_backtest(
                        params, tr_start, tr_end)
                    score = metrics.get(self.score_metric, -np.inf)
                    if np.isnan(score) or np.isinf(score):
                        score = -np.inf
                except Exception:
                    score = -np.inf

                param_scores.append((params, score))

                if score > best_score:
                    best_score = score
                    best_params = params

                if self.verbose and (i + 1) % max(1, n_combos // 4) == 0:
                    print(f"    ... {i + 1}/{n_combos} combos evaluated")

            if self.verbose:
                params_str = ", ".join(f"{k}={v}" for k, v in best_params.items())
                print(f"    Best: {params_str}  "
                      f"(train {self.score_metric}={best_score:.3f})")

            # ── 测试期: 用最优参数 ──
            test_portfolio, test_metrics, _ = self._run_single_backtest(
                best_params, te_start, te_end)

            test_score = test_metrics.get(self.score_metric, 0)
            test_ret = test_metrics.get("total_return", 0)
            if self.verbose:
                print(f"    Test:  {self.score_metric}={test_score:.3f}  "
                      f"return={test_ret:.1%}")
                print()

            results.append(WindowResult(
                window_idx=w_idx + 1,
                train_start=tr_start,
                train_end=tr_end,
                test_start=te_start,
                test_end=te_end,
                best_params=best_params,
                train_score=best_score,
                test_metrics=test_metrics,
                test_portfolio=test_portfolio,
                param_scores=param_scores,
            ))

        return WalkForwardResult(
            strategy_name=self.strategy_cls.__name__,
            param_grid=self.param_grid,
            fixed_params=self.fixed_params,
            score_metric=self.score_metric,
            windows=results,
            total_combos=n_combos,
        )
