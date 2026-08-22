"""CX-O-Autonomy 感知层（P1-T3）单元测试。

覆盖 RssFetcher / HotspotMonitor / ContextSensor 三个感知模块：

1. RssFetcher 用 mock httpx 响应解析 title/link/summary（含缺字段容错）
2. 单源失败跳过其余源（mock 一个抛错一个成功）
3. 全部失败返回 []
4. HotspotMonitor 无 provider 返回 []
5. 有 provider 时返回搜索结果（sync / async / fallback）
6. ContextSensor.is_user_online 有/无 provider
7. snapshot 形状含 is_user_online
8. weather 不可用返回 {"available": False}

运行：python -m pytest tests/test_autonomy_perception.py -q
"""
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from server.autonomy.perception.env.context_sensor import ContextSensor
from server.autonomy.perception.news.rss_fetcher import RssFetcher
from server.autonomy.perception.social.hotspot_monitor import HotspotMonitor

_RSS_PATCH_TARGET = "server.autonomy.perception.news.rss_fetcher.httpx.AsyncClient"

RSS_TWO_ITEMS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>测试源</title>
    <item>
      <title>标题一</title>
      <link>http://example.com/a1</link>
      <description>摘要一</description>
      <pubDate>Mon, 01 Jan 2024 00:00:00 GMT</pubDate>
    </item>
    <item>
      <title>标题二</title>
      <link>http://example.com/a2</link>
      <description>摘要二</description>
    </item>
  </channel>
</rss>
"""

RSS_THREE_ITEMS = RSS_TWO_ITEMS.replace(
    "</channel>",
    """  <item>
      <title>标题三</title>
      <link>http://example.com/a3</link>
      <description>摘要三</description>
    </item>
  </channel>""",
)


def _make_response(text: str, status_code: int = 200) -> MagicMock:
    """构造最小 mock httpx.Response（含 status_code / text / raise_for_status）。"""
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    resp.raise_for_status.return_value = None
    return resp


def _mock_client(*, get_result: MagicMock = None, side_effect=None) -> AsyncMock:
    """构造支持 async with 的 mock httpx.AsyncClient，替换其 get 行为。"""
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.__aexit__.return_value = None
    if get_result is not None:
        client.get.return_value = get_result
    if side_effect is not None:
        client.get.side_effect = side_effect
    return client


# ================================================================ RssFetcher
class TestRssFetcher:
    @pytest.mark.asyncio
    async def test_fetch_parses_items(self):
        """① 用 mock httpx 响应解析 title/link/summary；缺字段容错。"""
        client = _mock_client(get_result=_make_response(RSS_TWO_ITEMS))
        with patch(_RSS_PATCH_TARGET, return_value=client):
            fetcher = RssFetcher(urls=["http://example.com/rss"])
            items = await fetcher.fetch()
        assert len(items) == 2
        assert items[0]["title"] == "标题一"
        assert items[0]["link"] == "http://example.com/a1"
        assert items[0]["summary"] == "摘要一"
        assert items[0]["source"] == "http://example.com/rss"
        # 有 pubDate → 填充 published
        assert "published" in items[0]
        # 第二项缺 pubDate → 不含 published
        assert items[1]["title"] == "标题二"
        assert "published" not in items[1]

    @pytest.mark.asyncio
    async def test_single_source_failure_skipped(self):
        """② 单源失败（抛 ConnectError）跳过，其余源正常解析。"""
        client = _mock_client(
            side_effect=[httpx.ConnectError("boom"), _make_response(RSS_TWO_ITEMS)]
        )
        with patch(_RSS_PATCH_TARGET, return_value=client):
            fetcher = RssFetcher(urls=["http://example.com/fail", "http://example.com/ok"])
            items = await fetcher.fetch()
        assert len(items) == 2
        assert all(item["source"] == "http://example.com/ok" for item in items)

    @pytest.mark.asyncio
    async def test_all_failures_return_empty(self):
        """③ 全部源失败返回 []。"""
        client = _mock_client(side_effect=httpx.ConnectError("boom"))
        with patch(_RSS_PATCH_TARGET, return_value=client):
            fetcher = RssFetcher(urls=["http://example.com/a", "http://example.com/b"])
            items = await fetcher.fetch()
        assert items == []

    @pytest.mark.asyncio
    async def test_non_xml_response_skipped(self):
        """非 XML 响应（解析抛错）被跳过，返回 []。"""
        client = _mock_client(get_result=_make_response("<html>not rss</html>"))
        with patch(_RSS_PATCH_TARGET, return_value=client):
            fetcher = RssFetcher(urls=["http://example.com/bad"])
            items = await fetcher.fetch()
        assert items == []

    @pytest.mark.asyncio
    async def test_max_items_limited(self):
        """每源只解析前 max_items 条。"""
        client = _mock_client(get_result=_make_response(RSS_THREE_ITEMS))
        with patch(_RSS_PATCH_TARGET, return_value=client):
            fetcher = RssFetcher(urls=["http://example.com/rss"], max_items=2)
            items = await fetcher.fetch()
        assert len(items) == 2
        assert items[0]["title"] == "标题一"
        assert items[1]["title"] == "标题二"


# ================================================================ HotspotMonitor
class TestHotspotMonitor:
    @pytest.mark.asyncio
    async def test_no_provider_returns_empty(self):
        """④ 无 provider 时优雅返回 []，不抛错。"""
        monitor = HotspotMonitor()
        assert await monitor.get_hotspots(["AI"]) == []

    @pytest.mark.asyncio
    async def test_with_provider_returns_search_results(self):
        """⑤ 有 provider 时返回搜索结果（async provider）。"""

        async def fake_provider(query: str):
            return [{"title": f"{query}-标题", "link": f"http://x/{query}", "snippet": "摘要"}]

        monitor = HotspotMonitor(search_provider=fake_provider)
        hotspots = await monitor.get_hotspots(["AI", "游戏"], limit=3)
        assert len(hotspots) == 2
        assert hotspots[0] == {"title": "AI-标题", "link": "http://x/AI", "snippet": "摘要"}
        assert hotspots[1]["title"] == "游戏-标题"

    @pytest.mark.asyncio
    async def test_sync_provider_supported(self):
        """同步 provider 亦可工作。"""

        def fake_provider(query: str):
            return [{"title": query, "link": "", "snippet": ""}]

        monitor = HotspotMonitor(search_provider=fake_provider)
        hotspots = await monitor.get_hotspots(["话题"], limit=5)
        assert hotspots[0]["title"] == "话题"

    @pytest.mark.asyncio
    async def test_fallback_used_when_provider_empty(self):
        """provider 无结果时触发 fallback 补足。"""

        async def empty_provider(query: str):
            return []

        async def fallback_provider(query: str):
            return [{"title": f"fallback-{query}", "link": "", "snippet": ""}]

        monitor = HotspotMonitor(search_provider=empty_provider, fallback=fallback_provider)
        hotspots = await monitor.get_hotspots(["t"], limit=5)
        assert hotspots[0]["title"] == "fallback-t"


# ================================================================ ContextSensor
class TestContextSensor:
    def test_is_user_online_no_provider(self):
        """⑥ 无 provider 时 is_user_online 返回 False。"""
        assert ContextSensor().is_user_online() is False

    def test_is_user_online_with_provider(self):
        """⑥ 有 provider 时按 provider 返回值判定。"""
        assert ContextSensor(user_online_provider=lambda: True).is_user_online() is True
        assert ContextSensor(user_online_provider=lambda: False).is_user_online() is False

    def test_snapshot_shape_contains_is_user_online(self):
        """⑦ snapshot 形状包含 is_user_online 等 5 个键。"""
        sensor = ContextSensor(user_online_provider=lambda: True)
        snap = sensor.snapshot()
        assert set(snap.keys()) == {"now_iso", "weekday", "hour", "is_user_online", "weather"}
        assert snap["is_user_online"] is True
        assert isinstance(snap["now_iso"], str)
        assert isinstance(snap["weekday"], int)
        assert isinstance(snap["hour"], int)

    def test_weather_unavailable_returns_available_false(self):
        """⑧ 无 weather provider 时返回 {"available": False}。"""
        assert ContextSensor().get_weather("上海") == {"available": False}

    def test_weather_with_provider(self):
        """有 weather provider 时返回其查询结果。"""
        sensor = ContextSensor(
            weather_provider=lambda loc: {"available": True, "temp": 25, "location": loc}
        )
        weather = sensor.get_weather("上海")
        assert weather["available"] is True
        assert weather["location"] == "上海"

    def test_now_is_aware_with_offset(self):
        """now() 返回含时区偏移的 aware datetime。"""
        sensor = ContextSensor(timezone_offset_hours=8)
        now = sensor.now()
        assert now.utcoffset() is not None
        assert now.utcoffset().total_seconds() == 8 * 3600
