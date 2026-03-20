# quant-engine

Event-driven quantitative backtesting engine in Python. Built for strategy research, backtesting, and cross-validation with QuantConnect.

## Features

- **Event-driven architecture** — MarketEvent → SignalEvent → OrderEvent → FillEvent, loosely coupled
- **Look-ahead bias prevention** — BarData only exposes data up to the current bar
- **Realistic execution** — Orders fill on the next bar's open + slippage (no close-price cheating)
- **Pluggable fee models** — IB per-share (default), percentage-based, or zero-fee; easy to extend
- **11 built-in strategies** — SMA crossover, dual momentum, all-weather, MACD, RSI, Bollinger, Donchian, momentum rotation, leveraged regime, and more
- **Auto SPY benchmark** — Automatically fetches SPY data and computes Alpha, Beta, Sharpe, Sortino, etc.
- **QuantConnect export** — Translate strategies to QC's Python API using Claude LLM
- **Walk-forward optimization** — Grid search + rolling window validation to avoid overfitting
- **Full analytics** — Equity curve, drawdown, exposure, turnover, trade log, and report generation

## Quick Start

### Install dependencies

```bash
pip install numpy scipy yfinance matplotlib
```

### Run a strategy

```bash
python -m examples.run_sma              # SMA crossover on AAPL
python -m examples.run_dual_momentum    # Dual momentum (QQQ/SPY/IWM + SHY)
python -m examples.run_all_weather      # All-weather adaptive momentum (10 assets)
python -m examples.run_etf_momentum     # ETF momentum rotation
python -m examples.run_leveraged_regime # TQQQ/SQQQ regime switching
python -m examples.run_walk_forward     # Walk-forward parameter optimization
```

### Run tests

```bash
python -m pytest tests/ -x -q    # 194 tests
```

## Write Your Own Strategy

```python
from engine.strategy.base import BaseStrategy
from engine.indicators.trend import sma

class SmaCrossover(BaseStrategy):
    def __init__(self, symbol: str, fast: int = 10, slow: int = 30):
        super().__init__()
        self.symbol = symbol
        self.fast = fast
        self.slow = slow

    def on_bar(self) -> None:
        if not self.bar_data.has_enough_bars(self.symbol, self.slow):
            return

        closes = self.bar_data.history(self.symbol, "close", self.slow)
        fast_sma = sma(closes, self.fast)[-1]
        slow_sma = sma(closes, self.slow)[-1]

        pos = self.get_position(self.symbol)

        if fast_sma > slow_sma and pos == 0:
            qty = int(self.portfolio.equity * 0.98 / self.bar_data.current(self.symbol).close)
            self.buy(self.symbol, qty)
        elif fast_sma < slow_sma and pos > 0:
            self.sell(self.symbol, pos)
```

## Run a Backtest

```python
from engine.engine import BacktestEngine
from engine.data import CachedFeed, YFinanceFeed
from engine.execution.fee_model import PerShareFeeModel
from engine.analytics.metrics import print_report

engine = BacktestEngine(
    strategy=SmaCrossover(symbol="AAPL", fast=10, slow=30),
    data_feed=CachedFeed(YFinanceFeed()),
    symbols=["AAPL"],
    start="2020-01-01",
    end="2025-12-31",
    initial_cash=100_000.0,
    fee_model=PerShareFeeModel(),   # IB: $0.005/share, min $1, max 0.5%
    slippage_rate=0.0005,           # 0.05%
)
portfolio = engine.run()
print_report(portfolio, trade_log=engine.trade_log, engine=engine)
```

## Built-in Strategies

| Strategy | Description |
|---|---|
| `BuyAndHold` | Baseline — buy on first bar, hold forever |
| `SmaCrossover` | Golden cross / death cross (SMA) |
| `DualMomentum` | Relative + absolute momentum, monthly rebalance |
| `AllWeatherMomentum` | 10-asset risk-adjusted momentum, inverse-vol weighting, top-4 holdings |
| `MACDCrossover` | MACD signal line crossover |
| `RSIReversion` | RSI mean reversion |
| `BollingerReversion` | Bollinger Bands mean reversion |
| `DonchianBreakout` | Donchian channel breakout |
| `MomentumRotation` | Momentum rotation across assets |
| `ETFMomentumRotation` | ETF sector momentum rotation |
| `LeveragedRegime` | TQQQ/SQQQ regime switching (SMA + VIX) |

## Fee Models

```python
from engine.execution.fee_model import PerShareFeeModel, PercentageFeeModel, ZeroFeeModel

PerShareFeeModel(per_share=0.005, min_fee=1.0, max_pct=0.005)  # IB Fixed (default)
PercentageFeeModel(rate=0.001)                                   # 0.1% per trade
ZeroFeeModel()                                                   # No fees
```

## Indicators

All indicators are pure functions: `np.ndarray` in, `np.ndarray` out.

```python
from engine.indicators.trend import sma, ema, macd
from engine.indicators.momentum import rsi
from engine.indicators.volatility import atr, bollinger

sma(closes, 20)                    # Simple moving average
ema(closes, 20)                    # Exponential moving average
macd(closes, 12, 26, 9)           # MACD (returns .macd_line, .signal_line, .histogram)
rsi(closes, 14)                    # RSI (Wilder smoothing)
atr(highs, lows, closes, 14)      # Average True Range
bollinger(closes, 20, 2.0)        # Bollinger Bands (returns .upper, .middle, .lower)
```

## Analytics

Auto-computed metrics (vs SPY benchmark):

| Metric | Description |
|---|---|
| Total Return / CAGR | Cumulative and annualized return |
| Max Drawdown | Largest peak-to-trough decline |
| Sharpe Ratio | Risk-adjusted return |
| Sortino Ratio | Downside-risk-adjusted return |
| Calmar Ratio | CAGR / Max Drawdown |
| PSR | Probabilistic Sharpe Ratio |
| Alpha / Beta | vs SPY |
| Information Ratio | Active return / Tracking error |
| Treynor Ratio | Return per unit of systematic risk |

## QuantConnect Export

Translate any strategy to QuantConnect's Python API using Claude:

```python
from engine.export.quantconnect import QCExporter

exporter = QCExporter()  # requires ANTHROPIC_API_KEY
qc_code = exporter.export(
    strategy_path="strategies/sma_crossover.py",
    start="2023-01-01", end="2025-12-31",
    strategy_kwargs={"symbol": "AAPL", "size": 100},
    output_path="qc_sma.py",
)
```

## Project Structure

```
engine/                     Core engine framework
├── core/                   Bar, BarData, Events
├── data/                   DataFeed, YFinanceFeed, CachedFeed
├── execution/              SimulatedBroker, FeeModel
├── portfolio/              Position, Portfolio
├── strategy/               BaseStrategy
├── indicators/             SMA, EMA, MACD, RSI, ATR, Bollinger, Donchian
├── risk/                   PositionSizer, StopManager
├── analytics/              Metrics, Charts, Reports
├── optimize/               Walk-forward optimization
├── export/                 QuantConnect export + reconciliation
└── engine.py               BacktestEngine (main event loop)

strategies/                 11 built-in strategy implementations
examples/                   Runnable example scripts
tests/                      194 pytest tests
data_cache/                 Local CSV data cache
```

## Design Decisions

- **Next-bar execution** — Orders submitted this bar fill on the next bar's open + slippage
- **Market orders fill at open** — Not close, to avoid unrealistic fill assumptions
- **Data caching** — CachedFeed decorator: local CSV + meta.json, smart incremental updates
- **Strategy-engine decoupling** — Strategies interact only through `bar_data` / `portfolio` / `buy()` / `sell()`
- **LLM-based QC export** — More robust than AST-based code translation for complex strategies

## License

MIT
