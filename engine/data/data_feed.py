"""
数据源适配器 — 负责把外部数据转成 Bar 列表。
"""

from __future__ import annotations

import csv
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path

from engine.core.bar_data import Bar


class DataFeed(ABC):
    """数据源基类。"""

    @abstractmethod
    def fetch(self, symbol: str, start: str, end: str) -> list[Bar]:
        """获取历史数据，返回按时间升序排列的 Bar 列表。"""
        ...


class YFinanceFeed(DataFeed):
    """
    yfinance 数据源（日线）。

    weekdays_only: 只保留工作日数据（默认 True）。
    对于 BTC-USD 等 7x24 交易的品种，过滤掉周末数据以对齐其他标的。
    """

    def __init__(self, weekdays_only: bool = True) -> None:
        self.weekdays_only = weekdays_only

    def fetch(self, symbol: str, start: str, end: str) -> list[Bar]:
        try:
            import yfinance as yf
        except ImportError:
            raise ImportError("请安装 yfinance: pip install yfinance")

        ticker = yf.Ticker(symbol)
        df = ticker.history(start=start, end=end)

        if df.empty:
            raise ValueError(f"No data for {symbol} from {start} to {end}")

        bars: list[Bar] = []
        for ts, row in df.iterrows():
            dt = ts.to_pydatetime()
            # 过滤周末 (BTC-USD 等加密货币 7 天交易)
            if self.weekdays_only and dt.weekday() >= 5:
                continue
            bars.append(Bar(
                symbol=symbol,
                timestamp=dt,
                open=float(row["Open"]),
                high=float(row["High"]),
                low=float(row["Low"]),
                close=float(row["Close"]),
                volume=int(row["Volume"]),
            ))
        return bars


class CSVFeed(DataFeed):
    """
    CSV 数据源。

    期望列: Date,Open,High,Low,Close,Volume
    """

    def __init__(self, data_dir: str | Path = "data_cache") -> None:
        self.data_dir = Path(data_dir)

    def fetch(self, symbol: str, start: str, end: str) -> list[Bar]:
        filepath = self.data_dir / f"{symbol}.csv"
        if not filepath.exists():
            raise FileNotFoundError(f"CSV not found: {filepath}")

        start_dt = datetime.strptime(start, "%Y-%m-%d")
        end_dt = datetime.strptime(end, "%Y-%m-%d")

        bars: list[Bar] = []
        with open(filepath) as f:
            reader = csv.DictReader(f)
            for row in reader:
                dt = datetime.strptime(row["Date"], "%Y-%m-%d")
                if dt < start_dt or dt > end_dt:
                    continue
                bars.append(Bar(
                    symbol=symbol,
                    timestamp=dt,
                    open=float(row["Open"]),
                    high=float(row["High"]),
                    low=float(row["Low"]),
                    close=float(row["Close"]),
                    volume=int(row["Volume"]),
                ))
        bars.sort(key=lambda b: b.timestamp)
        return bars
