"""AI service — Claude API for strategy code generation and auto-fix."""

from __future__ import annotations

import re
from typing import AsyncIterator

import anthropic

SYSTEM_PROMPT = """\
You are a quantitative trading strategy code generator. You generate Python strategy code for a backtesting engine.

## Rules
1. Always output a SINGLE Python class that inherits from `BaseStrategy`.
2. The class MUST implement `on_bar(self) -> None`.
3. The class `__init__` must accept the parameters the user describes and call `super().__init__()`.
4. Output ONLY the Python code block — no explanation, no markdown fences, just pure Python code.
5. Always include necessary imports at the top of the code.

## Available API

```python
from engine.strategy.base import BaseStrategy
from engine.indicators.trend import sma, ema, macd  # sma(arr, n), ema(arr, n), macd(arr, fast, slow, signal) -> MACDResult(.macd_line, .signal_line, .histogram)
from engine.indicators.momentum import rsi  # rsi(arr, n)
from engine.indicators.volatility import atr, bollinger  # atr(high, low, close, n), bollinger(arr, n, num_std) -> BollingerResult(.upper, .middle, .lower)
from engine.indicators.breakout import donchian  # donchian(high, low, n) -> DonchianResult(.upper, .lower, .middle)

class MyStrategy(BaseStrategy):
    def __init__(self, symbols: list[str], **params):
        super().__init__()
        self.symbols = symbols  # will be set from UI params
        # store other params

    def on_bar(self) -> None:
        for symbol in self.symbols:
            # Data access
            if not self.bar_data.has_enough_bars(symbol, period):
                return
            closes = self.bar_data.history(symbol, "close", period)  # -> np.ndarray
            highs = self.bar_data.history(symbol, "high", period)
            lows = self.bar_data.history(symbol, "low", period)
            bar = self.bar_data.current(symbol)  # -> Bar (.open/.high/.low/.close/.volume/.timestamp)

            # Position
            pos = self.get_position(symbol)   # -> int (number of shares, 0 if flat)
            equity = self.portfolio.equity     # -> float
            cash = self.portfolio.cash         # -> float

            # Orders
            self.buy(symbol, quantity)              # market buy
            self.sell(symbol, quantity)              # market sell
            self.buy_limit(symbol, quantity, price)  # limit buy
            self.sell_limit(symbol, quantity, price)  # limit sell

            # Risk management
            self.set_stop_loss(symbol, stop_price)
            self.set_take_profit(symbol, target_price)
            self.set_trailing_stop(symbol, trail_pct=0.05)
            self.cancel_stops(symbol)
```

## Important notes
- The strategy `__init__` MUST accept `symbols: list[str]` as the first parameter (the UI will pass it).
- Use `self.symbols` to iterate over all symbols (support multi-symbol).
- Orders execute on the NEXT bar at open price + slippage.
- `bar_data.history()` returns a numpy array. Indicators return numpy arrays.
- When using indicators, always check `has_enough_bars()` first.
- For position sizing, use `int(equity * fraction / price)` pattern.
- All indicators return np.ndarray where first N-1 values are NaN — always use `[-1]` to get the latest value.
"""

FIX_PROMPT = """\
The strategy code below produced an error during backtesting. Fix the code and return ONLY the corrected Python code (no explanation, no markdown fences).

## Error
{error}

## Code
{code}

## Available API (same as before)
The strategy must inherit BaseStrategy, implement on_bar(), and __init__ must accept symbols: list[str] as first param.
Fix the error while preserving the strategy logic. Common issues:
- Import errors: make sure all imports are correct
- Index errors: check array bounds with has_enough_bars()
- Type errors: quantity must be int, prices must be float
- Attribute errors: use the correct API methods
"""

TITLE_PROMPT = """\
Generate a short title (max 6 Chinese characters or 20 English chars) for a trading strategy described as:
"{description}"
Output ONLY the title, nothing else."""


def _extract_code(text: str) -> str:
    """Extract Python code from LLM response, stripping markdown fences if present."""
    # Try to extract from ```python ... ``` blocks
    match = re.search(r"```python\s*\n(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    match = re.search(r"```\s*\n(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    # Assume the whole response is code
    return text.strip()


class AIService:
    def __init__(self) -> None:
        self.client = anthropic.Anthropic()
        self.model = "claude-sonnet-4-20250514"

    async def generate_strategy(
        self,
        messages: list[dict[str, str]],
    ) -> AsyncIterator[str]:
        """
        Generate/modify strategy code via multi-turn conversation.
        Yields partial text chunks for streaming.

        messages: [{"role": "user"|"assistant", "content": "..."}]
        """
        import anthropic as _anthropic

        async_client = _anthropic.AsyncAnthropic()

        async with async_client.messages.stream(
            model=self.model,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=messages,
        ) as stream:
            async for text in stream.text_stream:
                yield text

    async def generate_strategy_sync(
        self,
        messages: list[dict[str, str]],
    ) -> str:
        """Non-streaming version — returns full response text."""
        import anthropic as _anthropic

        async_client = _anthropic.AsyncAnthropic()

        response = await async_client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=messages,
        )
        raw = response.content[0].text
        return _extract_code(raw)

    async def fix_code(self, code: str, error: str) -> str:
        """Auto-fix strategy code that produced an error."""
        import anthropic as _anthropic

        async_client = _anthropic.AsyncAnthropic()

        response = await async_client.messages.create(
            model=self.model,
            max_tokens=4096,
            messages=[{
                "role": "user",
                "content": FIX_PROMPT.format(error=error, code=code),
            }],
        )
        raw = response.content[0].text
        return _extract_code(raw)

    async def generate_title(self, description: str) -> str:
        """Generate a short title for the strategy."""
        import anthropic as _anthropic

        async_client = _anthropic.AsyncAnthropic()

        response = await async_client.messages.create(
            model=self.model,
            max_tokens=50,
            messages=[{
                "role": "user",
                "content": TITLE_PROMPT.format(description=description),
            }],
        )
        return response.content[0].text.strip().strip('"').strip("'")

    def extract_code(self, text: str) -> str:
        return _extract_code(text)
