# quant-engine

事件驱动的量化回测引擎，Python 实现。用于策略研究、回测和与 QuantConnect 对比验证。

## 快速命令

```bash
python -m pytest tests/ -x -q          # 运行测试 (194 tests)
python -m examples.run_sma             # 运行 SMA 交叉策略示例
python -m examples.run_dual_momentum   # 运行双动量策略示例
python -m examples.run_all_weather     # 运行全天候策略示例
python -m examples.run_qc_export       # 导出策略到 QuantConnect
```

## 目录结构

```
engine/                         # 核心引擎框架
├── core/
│   ├── bar_data.py            # Bar (OHLCV K线) + BarData (数据视图，防止 look-ahead bias)
│   └── event.py               # 事件类: MarketEvent, SignalEvent, OrderEvent, FillEvent
│                              #   枚举: Direction(LONG/SHORT), OrderType(MARKET/LIMIT/STOP/STOP_LIMIT)
├── data/
│   ├── data_feed.py           # DataFeed 基类 + YFinanceFeed (Yahoo日线) + CSVFeed
│   └── cached_feed.py         # CachedFeed — 装饰器模式，本地 CSV 缓存，智能增量更新
├── execution/
│   └── broker.py              # SimulatedBroker — 模拟撮合 (滑点 + 手续费)
│                              #   MARKET: 下根bar open+滑点
│                              #   LIMIT: bar.low≤limit→min(limit,open)成交
│                              #   STOP: 穿越stop_price后+滑点成交
├── portfolio/
│   └── portfolio.py           # Position (持仓+均价) + Portfolio (现金+持仓+净值曲线)
├── strategy/
│   └── base.py                # BaseStrategy 抽象基类 — 所有策略的父类
├── indicators/
│   ├── trend.py               # sma(), ema(), macd() → 返回 np.ndarray
│   ├── momentum.py            # rsi() (Wilder smoothing)
│   ├── volatility.py          # atr(), bollinger()
│   └── breakout.py            # Donchian channel
├── risk/
│   ├── position_sizer.py      # FixedFractionSizer, ATRSizer
│   └── stop_manager.py        # FixedStop, TrailingStop — 引擎每bar自动检查
├── analytics/
│   ├── metrics.py             # TradeLog (交易配对) + calculate_metrics() + print_report()
│   └── chart.py               # plot_backtest() — matplotlib 可视化
├── export/
│   ├── quantconnect.py        # QCExporter — 用 Claude API 翻译策略到 QC (snake_case API)
│   ├── reconcile.py           # QCReconciler — 对比 QC 和 engine 的回测结果
│   └── qc_logging.py          # QCLogger — QC 策略日志辅助代码片段
└── engine.py                  # BacktestEngine — 主事件循环

strategies/                     # 策略实现
├── buy_and_hold.py            # 基准策略: 第一根bar全仓买入
├── sma_crossover.py           # 均线交叉 (金叉买/死叉卖)
├── dual_momentum.py           # 双动量 (相对+绝对动量, 月度调仓)
├── all_weather_momentum.py    # 全天候自适应动量 (10资产, 逆波动率加权, top4持仓)
├── macd_crossover.py          # MACD 信号线交叉
├── rsi_reversion.py           # RSI 均值回归
├── bollinger_reversion.py     # 布林带均值回归
├── donchian_breakout.py       # Donchian 通道突破
├── momentum_rotation.py       # 动量轮动
├── etf_momentum_rotation.py   # ETF 动量轮动
└── leveraged_regime.py        # TQQQ/SQQQ 杠杆 regime 策略

examples/                       # 可运行的示例脚本 (python -m examples.run_xxx)
tests/                          # pytest 测试 (194 tests)
data_cache/                     # 本地数据缓存 (CSV + meta.json, 17个symbol)
```

## 核心 API

### 策略编写 (BaseStrategy)

```python
from engine.strategy.base import BaseStrategy
from engine.indicators import sma

class MyStrategy(BaseStrategy):
    def __init__(self, symbol: str, period: int = 20):
        super().__init__()
        self.symbol = symbol
        self.period = period

    def on_bar(self) -> None:
        # 数据访问
        if not self.bar_data.has_enough_bars(self.symbol, self.period):
            return
        closes = self.bar_data.history(self.symbol, "close", self.period)  # → np.ndarray
        bar = self.bar_data.current(self.symbol)  # → Bar (.open/.high/.low/.close/.volume)

        # 仓位查询
        pos = self.get_position(self.symbol)   # → int
        equity = self.portfolio.equity          # → float
        cash = self.portfolio.cash              # → float

        # 下单
        self.buy(self.symbol, 100)              # 市价买入
        self.sell(self.symbol, 100)             # 市价卖出
        self.buy_limit(self.symbol, 100, 150.0) # 限价买入
        self.sell_limit(self.symbol, 100, 160.0)# 限价卖出

        # 风控
        self.set_stop_loss(self.symbol, 140.0)
        self.set_take_profit(self.symbol, 170.0)
        self.set_trailing_stop(self.symbol, trail_pct=0.05)
        self.cancel_stops(self.symbol)
```

### 运行回测

```python
from engine.engine import BacktestEngine
from engine.data import CachedFeed, YFinanceFeed
from engine.analytics.metrics import print_report

engine = BacktestEngine(
    strategy=MyStrategy(symbol="AAPL"),
    data_feed=CachedFeed(YFinanceFeed()),
    symbols=["AAPL"],
    start="2023-01-01",
    end="2025-12-31",
    initial_cash=100_000.0,
    commission_rate=0.001,   # 0.1%
    slippage_rate=0.0005,    # 0.05%
)
portfolio = engine.run()  # 自动获取 SPY 基准
print_report(portfolio, trade_log=engine.trade_log, engine=engine)  # 自动 vs SPY

# 输出完整报告到 outputs/<timestamp>/
from engine.analytics.report import generate_report
generate_report(engine, strategy_name="My Strategy")
# → outputs/20260320_143000/
#     report.png, report.txt, equity_curve.csv,
#     trades.csv, exposure.csv, turnover.csv
```

### 引擎事件循环 (每 bar)

```
1. bar_data.advance()           → 推进所有标的到下根 bar
2. broker.fill_orders()         → 撮合上一轮的待处理订单
3. portfolio.update_equity()    → 按最新价格更新净值
3b. 记录 exposure/turnover      → 多空敞口 + 换手率时序
4. strategy._collect_stop_orders() → 检查止损触发
5. strategy.on_bar()            → 调用策略逻辑
6. strategy._collect_orders()   → 收集新订单提交给 broker
7. _fetch_spy_benchmark()       → 回测结束后自动获取 SPY 基准
```

订单在提交后的**下一根 bar** 撮合（模拟真实延迟）。

### QuantConnect 导出

```python
from engine.export.quantconnect import QCExporter

exporter = QCExporter()  # 需要 ANTHROPIC_API_KEY 环境变量
qc_code = exporter.export(
    strategy_path="strategies/sma_crossover.py",
    start="2023-01-01", end="2025-12-31",
    strategy_kwargs={"symbol": "AAPL", "size": 100},
    output_path="qc_sma.py",
)
```

用 Claude API 翻译策略代码，自动使用 QC 最新的 PEP8 snake_case API。

### 对账工具

```python
from engine.export.reconcile import QCReconciler

reconciler = QCReconciler()
report = reconciler.compare_from_log(
    qc_log_text=open("qc_results.json").read(),
    engine_portfolio=portfolio,
    engine_trade_log=engine.trade_log,
)
report.print_report()  # 按严重程度分级的差异报告 + 根因诊断
```

## 指标函数

所有指标都是纯函数，输入 `np.ndarray`，输出 `np.ndarray`（前 N-1 个值为 NaN）：

```python
from engine.indicators.trend import sma, ema, macd
from engine.indicators.momentum import rsi
from engine.indicators.volatility import atr, bollinger

sma(closes, 20)           # → np.ndarray, 简单移动平均
ema(closes, 20)           # → np.ndarray, 指数移动平均
macd(closes, 12, 26, 9)   # → MACDResult(.macd_line, .signal_line, .histogram)
rsi(closes, 14)           # → np.ndarray, RSI (Wilder smoothing)
atr(highs, lows, closes, 14)  # → np.ndarray, ATR
bollinger(closes, 20, 2.0)    # → BollingerResult(.upper, .middle, .lower)
```

## 回测指标

`calculate_metrics()` 输出 (自动 vs SPY 基准):

| 指标 | 说明 |
|---|---|
| total_return, cagr | 总收益 / 年化收益 |
| max_drawdown | 最大回撤 |
| sharpe_ratio | 夏普比率 |
| sortino_ratio | 索提诺比率 (下行波动) |
| calmar_ratio | 卡尔玛比率 (CAGR/MaxDD) |
| psr | Probabilistic Sharpe Ratio (Sharpe 为正的概率) |
| expectancy | 每日期望收益 |
| alpha, beta | vs SPY (自动获取) |
| information_ratio | 信息比率 |
| tracking_error | 跟踪误差 |
| treynor_ratio | 特雷诺比率 |

`engine.exposure_curve` — 每 bar (timestamp, long_ratio, short_ratio)
`engine.turnover_curve` — 每 bar (timestamp, turnover)

## 关键设计决策

- **事件驱动**: MarketEvent → SignalEvent → OrderEvent → FillEvent，松耦合
- **防 look-ahead bias**: BarData 只暴露 <= current_index 的数据
- **订单延迟一 bar 成交**: 本 bar 下单，下 bar 撮合（模拟真实延迟）
- **市价单以 open+滑点 成交**: 不用 close（避免不现实的成交假设）
- **数据缓存**: CachedFeed 装饰器模式，本地 CSV + meta.json，智能增量更新
- **策略与引擎解耦**: 策略只通过 bar_data/portfolio/buy/sell 交互，不知道引擎内部
- **自动 SPY 基准**: engine.run() 后自动获取 SPY 数据，计算 Alpha/Beta 等
- **QC 导出用 LLM 翻译**: 比 AST 硬编码转译更可靠，能处理复杂策略

## 依赖

numpy, scipy, yfinance, matplotlib, anthropic (仅 QC 导出需要)

## Roadmap

做完一个删一个。

### 近期 (复杂度低)

- [ ] **组合级风控** — 全局最大回撤熔断 + 单标的最大仓位限制，目前只有单标的止损
- [ ] **滑点/手续费模型增强** — 按成交额阶梯费率(IB实际费率) + 成交量冲击模型，目前是固定比例
- [ ] **报告增强** — 月度收益热力图 + 滚动 Sharpe/Beta 曲线 + 按标的 PnL 归因
- [ ] **多时间框架** — 支持周线/月线/小时线，策略可跨周期参考

### 中期

- [ ] **Walk-Forward 参数优化** — 网格搜索 + 走步验证 + 参数稳定性热力图，避免过拟合
- [ ] **IBKR 实盘对接** — IBKR API 实时数据+下单，策略信号→实际订单桥接
- [ ] **保证金模型** — 做空保证金占用、Reg T / Portfolio Margin、margin call 模拟
- [ ] **多资产类别** — 期权 (covered call/protective put) + 期货 (到期换月)

### 远期

- [ ] **事件日历** — 财报日/FOMC/期权到期日，策略可在事件前后调整行为
- [ ] **因子研究框架** — 截面因子计算 + IC/IR 分析 + 因子衰减曲线
- [ ] **分布式回测** — 大规模参数扫描并行化 + 多策略组合回测
