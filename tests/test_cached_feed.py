"""
CachedFeed 单元测试。

使用一个 MockFeed 模拟上游数据源，验证缓存逻辑:
- 首次 fetch → 调用上游 + 写缓存
- 重复 fetch → 读缓存，不调用上游
- 扩展范围 → 只获取缺失部分
- 清除缓存
"""

import shutil
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from engine.core.bar_data import Bar
from engine.data.cached_feed import CachedFeed
from engine.data.data_feed import DataFeed


# ── Mock 数据源 ──────────────────────────────────────────────

class MockFeed(DataFeed):
    """可追踪调用次数的 Mock 数据源。"""

    def __init__(self):
        self.call_count = 0
        self.call_log: list[tuple[str, str, str]] = []

    def fetch(self, symbol: str, start: str, end: str) -> list[Bar]:
        self.call_count += 1
        self.call_log.append((symbol, start, end))

        # 生成假数据: 每个工作日一根 bar
        bars = []
        dt = datetime.strptime(start, "%Y-%m-%d")
        end_dt = datetime.strptime(end, "%Y-%m-%d")
        price = 100.0
        while dt <= end_dt:
            if dt.weekday() < 5:  # 只有工作日
                bars.append(Bar(
                    symbol=symbol,
                    timestamp=dt,
                    open=price,
                    high=price + 1,
                    low=price - 1,
                    close=price + 0.5,
                    volume=1_000_000,
                ))
                price += 0.5
            from datetime import timedelta
            dt += timedelta(days=1)
        return bars


# ── Fixtures ──────────────────────────────────────────────────

@pytest.fixture
def cache_dir():
    d = tempfile.mkdtemp()
    yield Path(d)
    shutil.rmtree(d)


@pytest.fixture
def mock_feed():
    return MockFeed()


@pytest.fixture
def cached(mock_feed, cache_dir):
    return CachedFeed(mock_feed, cache_dir=cache_dir)


# ── Tests ─────────────────────────────────────────────────────

class TestCachedFeedBasic:
    """基本缓存功能。"""

    def test_first_fetch_downloads(self, cached, mock_feed):
        bars = cached.fetch("AAPL", "2023-01-01", "2023-01-31")
        assert mock_feed.call_count == 1
        assert len(bars) > 0
        assert all(b.symbol == "AAPL" for b in bars)

    def test_second_fetch_hits_cache(self, cached, mock_feed):
        cached.fetch("AAPL", "2023-01-01", "2023-01-31")
        assert mock_feed.call_count == 1

        bars2 = cached.fetch("AAPL", "2023-01-01", "2023-01-31")
        assert mock_feed.call_count == 1  # 没有再调用上游!
        assert len(bars2) > 0

    def test_subset_range_hits_cache(self, cached, mock_feed):
        """请求范围是缓存的子集 → 不需要下载。"""
        cached.fetch("AAPL", "2023-01-01", "2023-03-31")
        assert mock_feed.call_count == 1

        bars = cached.fetch("AAPL", "2023-02-01", "2023-02-28")
        assert mock_feed.call_count == 1  # 仍然只调用了一次
        assert all(
            datetime(2023, 2, 1) <= b.timestamp <= datetime(2023, 2, 28)
            for b in bars
        )

    def test_bars_sorted(self, cached):
        bars = cached.fetch("AAPL", "2023-01-01", "2023-06-30")
        timestamps = [b.timestamp for b in bars]
        assert timestamps == sorted(timestamps)


class TestCachedFeedExtend:
    """范围扩展: 只下载缺失部分。"""

    def test_extend_right(self, cached, mock_feed):
        cached.fetch("AAPL", "2023-01-01", "2023-06-30")
        assert mock_feed.call_count == 1

        cached.fetch("AAPL", "2023-01-01", "2023-12-31")
        assert mock_feed.call_count == 2
        # 只下载了 2023-07-01 ~ 2023-12-31
        _, start, end = mock_feed.call_log[-1]
        assert start == "2023-07-01"
        assert end == "2023-12-31"

    def test_extend_left(self, cached, mock_feed):
        cached.fetch("AAPL", "2023-06-01", "2023-12-31")
        assert mock_feed.call_count == 1

        cached.fetch("AAPL", "2023-01-01", "2023-12-31")
        assert mock_feed.call_count == 2
        _, start, end = mock_feed.call_log[-1]
        assert start == "2023-01-01"
        assert end == "2023-05-31"

    def test_extend_both_sides(self, cached, mock_feed):
        cached.fetch("AAPL", "2023-04-01", "2023-06-30")
        assert mock_feed.call_count == 1

        cached.fetch("AAPL", "2023-01-01", "2023-12-31")
        # 应该有 2 次额外调用 (左 + 右)，但 _fetch_missing 合并为一次调用
        # 实际上 _fetch_missing 分别调用左和右
        assert mock_feed.call_count == 3  # 1 + 左 + 右


class TestCachedFeedMultiSymbol:
    """多个 symbol 互不干扰。"""

    def test_different_symbols_separate_cache(self, cached, mock_feed):
        cached.fetch("AAPL", "2023-01-01", "2023-03-31")
        cached.fetch("GOOG", "2023-01-01", "2023-03-31")
        assert mock_feed.call_count == 2

        # 各自命中缓存
        cached.fetch("AAPL", "2023-01-01", "2023-03-31")
        cached.fetch("GOOG", "2023-01-01", "2023-03-31")
        assert mock_feed.call_count == 2  # 没有增加


class TestCachedFeedClearCache:
    """缓存清除。"""

    def test_clear_single(self, cached, mock_feed, cache_dir):
        cached.fetch("AAPL", "2023-01-01", "2023-03-31")
        cached.fetch("GOOG", "2023-01-01", "2023-03-31")

        cached.clear_cache("AAPL")
        assert not (cache_dir / "AAPL.csv").exists()
        assert not (cache_dir / "AAPL.meta.json").exists()
        assert (cache_dir / "GOOG.csv").exists()  # GOOG 不受影响

    def test_clear_all(self, cached, mock_feed, cache_dir):
        cached.fetch("AAPL", "2023-01-01", "2023-03-31")
        cached.fetch("GOOG", "2023-01-01", "2023-03-31")

        cached.clear_cache()
        assert not list(cache_dir.glob("*.csv"))
        assert not list(cache_dir.glob("*.meta.json"))

    def test_refetch_after_clear(self, cached, mock_feed):
        cached.fetch("AAPL", "2023-01-01", "2023-03-31")
        assert mock_feed.call_count == 1

        cached.clear_cache("AAPL")
        cached.fetch("AAPL", "2023-01-01", "2023-03-31")
        assert mock_feed.call_count == 2  # 必须重新下载


class TestCacheInfo:
    """缓存元数据查询。"""

    def test_no_cache(self, cached):
        assert cached.cache_info("AAPL") is None

    def test_has_cache(self, cached):
        cached.fetch("AAPL", "2023-01-01", "2023-06-30")
        info = cached.cache_info("AAPL")
        assert info is not None
        assert info["symbol"] == "AAPL"
        assert info["bars"] > 0
        assert "updated_at" in info


class TestCSVPersistence:
    """验证 CSV 文件内容正确可读。"""

    def test_csv_roundtrip(self, cached, cache_dir):
        bars1 = cached.fetch("AAPL", "2023-01-01", "2023-01-31")

        # 直接用 CSVFeed 读同一个缓存文件
        from engine.data.data_feed import CSVFeed
        csv_feed = CSVFeed(data_dir=cache_dir)
        bars2 = csv_feed.fetch("AAPL", "2023-01-01", "2023-01-31")

        assert len(bars1) == len(bars2)
        for b1, b2 in zip(bars1, bars2):
            assert b1.timestamp == b2.timestamp
            assert abs(b1.close - b2.close) < 0.01
