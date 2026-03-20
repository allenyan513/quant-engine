"""
QuantConnect 导出器 — 用 Claude 将 quant-engine 策略翻译为 QuantConnect Python 算法。

用法:
    exporter = QCExporter()
    qc_code = exporter.export(
        strategy_path="strategies/sma_crossover.py",
        start="2023-01-01",
        end="2025-12-31",
        initial_cash=100_000,
        strategy_kwargs={"symbol": "AAPL", "fast_period": 10, "slow_period": 30, "size": 100},
    )
"""

from __future__ import annotations

import os
from pathlib import Path

import anthropic


# ── QC 最新 API 参考 (PEP8 snake_case) ─────────────────────────────

QC_API_REFERENCE = """\
## QuantConnect Python API Reference (PEP8 snake_case — 2024+)

QuantConnect has migrated to PEP8 snake_case. ALL method/property names must use snake_case.
Enum values use UPPER_CASE. Class names remain CamelCase.

### Algorithm Structure
```python
from AlgorithmImports import *

class MyAlgorithm(QCAlgorithm):
    def initialize(self) -> None:
        self.set_start_date(2020, 1, 1)
        self.set_end_date(2024, 12, 31)
        self.set_cash(100000)
        self._symbol = self.add_equity("SPY", Resolution.DAILY).symbol
        self.set_warm_up(30, Resolution.DAILY)

    def on_data(self, data: Slice) -> None:
        if self.is_warming_up:
            return
        ...
```

### Key API Mappings
- Configuration: set_start_date(), set_end_date(), set_cash(), set_warm_up(), set_benchmark()
- Add securities: add_equity(ticker, Resolution.DAILY), add_crypto(), add_forex()
- Orders: market_order(sym, qty), limit_order(sym, qty, price), stop_market_order(), set_holdings(sym, pct), liquidate(sym)
- Portfolio: self.portfolio["SPY"].quantity, self.portfolio["SPY"].invested, self.portfolio.total_portfolio_value, self.portfolio.cash
- Securities: self.securities[sym].price, .open, .close, .high, .low, .volume
- History: self.history(symbol_obj, length, Resolution.DAILY) → pandas DataFrame, columns: "close", "open", "high", "low", "volume"
- Time: self.time (datetime)
- Logging: self.log(msg), self.debug(msg)
- Events: on_order_event(self, order_event), on_end_of_algorithm(self)

### Resolution Enum (UPPER_CASE)
Resolution.TICK, Resolution.SECOND, Resolution.MINUTE, Resolution.HOUR, Resolution.DAILY

### Fee Model
security.set_fee_model(ConstantFeeModel(0, "USD"))  # zero fees
# Or via initializer:
self.set_security_initializer(lambda sec: sec.set_fee_model(ConstantFeeModel(0, "USD")))

### Built-in Indicators (auto-updated by engine)
self.ema(sym, period, Resolution.DAILY)  → indicator.is_ready, indicator.current.value
self.sma(sym, period, Resolution.DAILY)
self.rsi(sym, period, MovingAverageType.WILDERS, Resolution.DAILY)
self.macd(sym, fast, slow, signal, MovingAverageType.EXPONENTIAL, Resolution.DAILY)
self.bb(sym, period, k, MovingAverageType.SIMPLE, Resolution.DAILY)
self.atr(sym, period, MovingAverageType.WILDERS, Resolution.DAILY)

### Scheduling
self.schedule.on(self.date_rules.every_day(sym), self.time_rules.after_market_open(sym, 30), self.rebalance)
"""

# ── quant-engine API 参考 ──────────────────────────────────────────

ENGINE_API_REFERENCE = """\
## quant-engine API Reference

### Strategy Base Class
```python
class BaseStrategy(ABC):
    def initialize(self) -> None: ...      # optional, called once at start
    def on_bar(self) -> None: ...          # called every bar — core logic
    def on_fill(self, fill: FillEvent): ...  # optional fill callback
```

### Data Access
- self.bar_data.history(symbol: str, field: str, length: int) → np.ndarray
  fields: "close", "open", "high", "low", "volume"
- self.bar_data.current(symbol: str) → Bar  (has .open, .high, .low, .close, .volume, .timestamp)
- self.bar_data.has_enough_bars(symbol: str, length: int) → bool

### Orders
- self.buy(symbol, quantity)        # market buy
- self.sell(symbol, quantity)       # market sell
- self.buy_limit(symbol, qty, price)
- self.sell_limit(symbol, qty, price)

### Position & Portfolio
- self.get_position(symbol) → int     # current position quantity
- self.portfolio.equity → float       # total portfolio value
- self.portfolio.cash → float

### Risk Management
- self.set_stop_loss(symbol, stop_price)
- self.set_take_profit(symbol, target_price)
- self.set_trailing_stop(symbol, trail_pct)
- self.cancel_stops(symbol)

### Indicators (standalone functions, operate on numpy arrays)
- from engine.indicators.trend import sma, ema, macd
- from engine.indicators.momentum import rsi
- from engine.indicators.volatility import atr, bollinger
Usage: closes = self.bar_data.history(sym, "close", 50); val = sma(closes, 20)[-1]
"""


class QCExporter:
    """用 Claude 将 quant-engine 策略翻译为 QuantConnect Python 算法。"""

    def __init__(self, model: str = "claude-sonnet-4-20250514", api_key: str | None = None):
        self.model = model
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise ValueError(
                "需要 Anthropic API key。请设置环境变量 ANTHROPIC_API_KEY 或传入 api_key 参数。\n"
                "  export ANTHROPIC_API_KEY=sk-ant-..."
            )
        self.client = anthropic.Anthropic(api_key=key)

    def export(
        self,
        strategy_path: str,
        start: str = "2023-01-01",
        end: str = "2025-12-31",
        initial_cash: float = 100_000.0,
        commission_rate: float | None = None,
        slippage_rate: float | None = None,
        output_path: str | None = None,
        strategy_kwargs: dict | None = None,
    ) -> str:
        """
        导出策略为 QC 代码。

        Args:
            strategy_path: 策略源码路径
            start/end: 回测日期范围
            initial_cash: 初始资金
            commission_rate: 手续费率 (None = 使用 QC 默认)
            slippage_rate: 滑点率 (None = 使用 QC 默认)
            output_path: 输出路径 (None = 不写文件)
            strategy_kwargs: 策略构造参数，如 {"symbol": "AAPL", "size": 100}

        Returns:
            生成的 QC Python 代码
        """
        # 读取策略源码
        source = Path(strategy_path).read_text(encoding="utf-8")

        # 构建 prompt
        prompt = self._build_prompt(
            source=source,
            strategy_path=strategy_path,
            start=start,
            end=end,
            initial_cash=initial_cash,
            commission_rate=commission_rate,
            slippage_rate=slippage_rate,
            strategy_kwargs=strategy_kwargs,
        )

        # 调用 Claude
        print(f"Translating {strategy_path} → QuantConnect...")
        response = self.client.messages.create(
            model=self.model,
            max_tokens=8192,
            messages=[{"role": "user", "content": prompt}],
        )

        # 提取代码
        qc_code = self._extract_code(response.content[0].text)

        if output_path:
            Path(output_path).write_text(qc_code, encoding="utf-8")
            print(f"Exported to {output_path}")

        return qc_code

    def _build_prompt(
        self,
        source: str,
        strategy_path: str,
        start: str,
        end: str,
        initial_cash: float,
        commission_rate: float | None,
        slippage_rate: float | None,
        strategy_kwargs: dict | None,
    ) -> str:
        """构建翻译 prompt。"""

        config_lines = [
            f"- Start date: {start}",
            f"- End date: {end}",
            f"- Initial cash: {initial_cash}",
        ]
        if commission_rate is not None:
            config_lines.append(f"- Commission rate: {commission_rate} (percentage-based)")
        if slippage_rate is not None:
            config_lines.append(f"- Slippage rate: {slippage_rate}")

        if strategy_kwargs:
            config_lines.append(f"- Strategy constructor arguments: {strategy_kwargs}")

        config_str = "\n".join(config_lines)

        return f"""\
You are an expert quant developer. Translate the following quant-engine strategy to a QuantConnect Python algorithm.

{ENGINE_API_REFERENCE}

{QC_API_REFERENCE}

## Backtest Configuration
{config_str}

## Source Strategy ({strategy_path})
```python
{source}
```

## Translation Rules

1. **Use the latest QC PEP8 snake_case API** — all method/property names must be snake_case, enum values UPPER_CASE.
2. **Preserve the exact same trading logic** — same signals, same conditions, same order sizing. Do NOT simplify or "improve" the strategy.
3. **Data access translation:**
   - `self.bar_data.history(sym, "close", N)` → `self.history(symbol_obj, N, Resolution.DAILY)["close"].values`
   - `self.bar_data.current(sym).close` → `self.securities[sym].close`
   - `self.bar_data.has_enough_bars(sym, N)` → check `len(history_df) >= N`
4. **Order translation:**
   - `self.buy(sym, qty)` → `self.market_order(sym, qty)`
   - `self.sell(sym, qty)` → `self.market_order(sym, -qty)`
   - `self.get_position(sym)` → `self.portfolio[sym].quantity`
   - `self.portfolio.equity` → `self.portfolio.total_portfolio_value`
   - `self.portfolio.cash` → `self.portfolio.cash`
5. **Indicators:** For simple indicators like SMA, you can either:
   - Use QC built-in indicators (preferred if straightforward), OR
   - Keep numpy-based calculation using self.history() data (when the original logic is complex or uses indicators in a non-standard way)
6. **Symbols:** In QC, store Symbol objects from add_equity() for use with history(). String tickers work for orders/portfolio.
7. **Commission model:** If commission_rate is provided, set up ConstantFeeModel accordingly. If None, use QC defaults.
8. **Constructor args:** If strategy_kwargs is provided, hardcode those values in initialize(). Otherwise, use the strategy's default values.
9. **Warmup:** Set appropriate set_warm_up() based on the longest lookback period used.
10. **Output a single, complete, self-contained .py file** that can be directly pasted into QuantConnect.

Output ONLY the Python code, wrapped in ```python ... ```. No explanation needed.
"""

    def _extract_code(self, response_text: str) -> str:
        """从 Claude 响应中提取代码块。"""
        # 尝试提取 ```python ... ``` 中的代码
        import re
        match = re.search(r"```python\s*\n(.*?)```", response_text, re.DOTALL)
        if match:
            return match.group(1).strip() + "\n"

        # 如果没有代码块标记，返回整个响应
        return response_text.strip() + "\n"
