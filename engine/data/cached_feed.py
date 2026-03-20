"""
数据缓存层 — 装饰器模式，包装任意 DataFeed，避免重复下载。

缓存策略:
- 每个 symbol 一个 CSV 文件 + 一个 .meta.json 元数据文件
- 请求 fetch(symbol, start, end) 时:
  1. 检查本地缓存是否已覆盖 [start, end]
  2. 若完全覆盖 → 直接读本地，零网络请求
  3. 若部分覆盖 → 只下载缺失的日期范围，合并后更新缓存
  4. 若无缓存 → 全量下载并保存
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta
from pathlib import Path

from engine.core.bar_data import Bar
from engine.data.data_feed import DataFeed


class CachedFeed(DataFeed):
    """
    带本地缓存的数据源包装器。

    用法:
        inner = YFinanceFeed()
        feed = CachedFeed(inner)               # 默认缓存到 data_cache/
        feed = CachedFeed(inner, "my_cache")    # 自定义缓存目录
        bars = feed.fetch("AAPL", "2023-01-01", "2024-01-01")  # 首次下载并缓存
        bars = feed.fetch("AAPL", "2023-01-01", "2024-01-01")  # 直接读缓存，零网络
    """

    DATE_FMT = "%Y-%m-%d"

    def __init__(self, inner: DataFeed, cache_dir: str | Path = "data_cache") -> None:
        self.inner = inner
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    # ── public API ──────────────────────────────────────────────

    def fetch(self, symbol: str, start: str, end: str) -> list[Bar]:
        start_dt = datetime.strptime(start, self.DATE_FMT)
        end_dt = datetime.strptime(end, self.DATE_FMT)

        meta = self._read_meta(symbol)
        cached_bars = self._read_csv(symbol) if meta else []

        if meta and self._covers(meta, start_dt, end_dt):
            # 完全命中缓存
            print(f"  [cache] {symbol}: hit ✓ ({start} ~ {end})")
            return self._filter(cached_bars, start_dt, end_dt)

        # 需要从上游获取缺失部分
        new_bars = self._fetch_missing(symbol, start_dt, end_dt, meta, cached_bars)

        # 合并 & 去重 & 排序
        merged = self._merge(cached_bars, new_bars)

        # 写回缓存 (存储请求的日期范围，而非实际 bar 日期)
        self._write_csv(symbol, merged)
        self._write_meta(symbol, merged, start_dt, end_dt, meta)

        print(f"  [cache] {symbol}: updated ({len(new_bars)} new bars downloaded)")
        return self._filter(merged, start_dt, end_dt)

    def clear_cache(self, symbol: str | None = None) -> None:
        """清除缓存。symbol=None 清除全部。"""
        if symbol:
            for suffix in (".csv", ".meta.json"):
                p = self.cache_dir / f"{symbol}{suffix}"
                p.unlink(missing_ok=True)
        else:
            for p in self.cache_dir.glob("*.csv"):
                p.unlink()
            for p in self.cache_dir.glob("*.meta.json"):
                p.unlink()

    def cache_info(self, symbol: str) -> dict | None:
        """查看某个 symbol 的缓存信息。"""
        return self._read_meta(symbol)

    # ── 缓存判断逻辑 ──────────────────────────────────────────

    @staticmethod
    def _covers(meta: dict, start_dt: datetime, end_dt: datetime) -> bool:
        cached_start = datetime.strptime(meta["start"], CachedFeed.DATE_FMT)
        cached_end = datetime.strptime(meta["end"], CachedFeed.DATE_FMT)
        return cached_start <= start_dt and cached_end >= end_dt

    def _fetch_missing(
        self,
        symbol: str,
        start_dt: datetime,
        end_dt: datetime,
        meta: dict | None,
        cached_bars: list[Bar],
    ) -> list[Bar]:
        """只下载缓存未覆盖的日期范围。"""
        if not meta:
            # 无缓存，全量下载
            return self.inner.fetch(
                symbol,
                start_dt.strftime(self.DATE_FMT),
                end_dt.strftime(self.DATE_FMT),
            )

        cached_start = datetime.strptime(meta["start"], self.DATE_FMT)
        cached_end = datetime.strptime(meta["end"], self.DATE_FMT)

        new_bars: list[Bar] = []

        # 左侧缺失: 请求的 start 早于缓存的 start
        if start_dt < cached_start:
            left_end = cached_start - timedelta(days=1)
            try:
                left_bars = self.inner.fetch(
                    symbol,
                    start_dt.strftime(self.DATE_FMT),
                    left_end.strftime(self.DATE_FMT),
                )
                new_bars.extend(left_bars)
            except ValueError:
                pass  # 可能该范围无数据

        # 右侧缺失: 请求的 end 晚于缓存的 end
        if end_dt > cached_end:
            right_start = cached_end + timedelta(days=1)
            try:
                right_bars = self.inner.fetch(
                    symbol,
                    right_start.strftime(self.DATE_FMT),
                    end_dt.strftime(self.DATE_FMT),
                )
                new_bars.extend(right_bars)
            except ValueError:
                pass  # 可能该范围无数据

        return new_bars

    # ── 合并 & 过滤 ──────────────────────────────────────────

    @staticmethod
    def _merge(existing: list[Bar], new: list[Bar]) -> list[Bar]:
        """按 timestamp 去重合并，保留最新的数据。同时统一去掉时区信息。"""
        bar_map: dict[str, Bar] = {}
        for bar in existing:
            # 统一为 naive datetime
            naive_bar = Bar(
                symbol=bar.symbol,
                timestamp=bar.timestamp.replace(tzinfo=None),
                open=bar.open, high=bar.high,
                low=bar.low, close=bar.close,
                volume=bar.volume,
            )
            key = f"{bar.symbol}_{naive_bar.timestamp.strftime('%Y-%m-%d')}"
            bar_map[key] = naive_bar
        for bar in new:
            naive_bar = Bar(
                symbol=bar.symbol,
                timestamp=bar.timestamp.replace(tzinfo=None),
                open=bar.open, high=bar.high,
                low=bar.low, close=bar.close,
                volume=bar.volume,
            )
            key = f"{bar.symbol}_{naive_bar.timestamp.strftime('%Y-%m-%d')}"
            bar_map[key] = naive_bar  # 新数据覆盖旧数据
        merged = sorted(bar_map.values(), key=lambda b: b.timestamp)
        return merged

    @staticmethod
    def _filter(bars: list[Bar], start_dt: datetime, end_dt: datetime) -> list[Bar]:
        return [
            b for b in bars
            if start_dt <= b.timestamp.replace(tzinfo=None) <= end_dt
        ]

    # ── CSV 读写 ──────────────────────────────────────────────

    def _csv_path(self, symbol: str) -> Path:
        return self.cache_dir / f"{symbol}.csv"

    def _meta_path(self, symbol: str) -> Path:
        return self.cache_dir / f"{symbol}.meta.json"

    def _read_csv(self, symbol: str) -> list[Bar]:
        path = self._csv_path(symbol)
        if not path.exists():
            return []

        bars: list[Bar] = []
        with open(path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                bars.append(Bar(
                    symbol=symbol,
                    timestamp=datetime.strptime(row["Date"], self.DATE_FMT),
                    open=float(row["Open"]),
                    high=float(row["High"]),
                    low=float(row["Low"]),
                    close=float(row["Close"]),
                    volume=int(row["Volume"]),
                ))
        bars.sort(key=lambda b: b.timestamp)
        return bars

    def _write_csv(self, symbol: str, bars: list[Bar]) -> None:
        path = self._csv_path(symbol)
        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Date", "Open", "High", "Low", "Close", "Volume"])
            for bar in bars:
                writer.writerow([
                    bar.timestamp.strftime(self.DATE_FMT),
                    f"{bar.open:.4f}",
                    f"{bar.high:.4f}",
                    f"{bar.low:.4f}",
                    f"{bar.close:.4f}",
                    bar.volume,
                ])

    def _read_meta(self, symbol: str) -> dict | None:
        path = self._meta_path(symbol)
        if not path.exists():
            return None
        with open(path) as f:
            return json.load(f)

    def _write_meta(
        self,
        symbol: str,
        bars: list[Bar],
        req_start: datetime,
        req_end: datetime,
        old_meta: dict | None,
    ) -> None:
        if not bars:
            return
        # 取请求范围与旧缓存范围的并集
        start = req_start
        end = req_end
        if old_meta:
            old_start = datetime.strptime(old_meta["start"], self.DATE_FMT)
            old_end = datetime.strptime(old_meta["end"], self.DATE_FMT)
            start = min(start, old_start)
            end = max(end, old_end)

        meta = {
            "symbol": symbol,
            "start": start.strftime(self.DATE_FMT),
            "end": end.strftime(self.DATE_FMT),
            "bars": len(bars),
            "updated_at": datetime.now().isoformat(),
        }
        path = self._meta_path(symbol)
        with open(path, "w") as f:
            json.dump(meta, f, indent=2)
