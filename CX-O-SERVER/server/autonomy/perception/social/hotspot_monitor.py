"""社交热点监控器（HotspotMonitor）。

- 通过注入的 search_provider（如 P2 阶段的 free-search-mcp）按主题查询热点，
  provider 入参 query，返回 [{title, link, snippet}] 结构
- 无 search_provider 时优雅返回 []，不抛错
- fallback 作为备用 provider：search_provider 无结果或调用失败时触发
- provider / fallback 均支持同步与异步可调用对象
- 本模块无文件 IO，禁止相对路径
"""

from __future__ import annotations

import inspect
from typing import Any, Callable, Dict, List, Optional

from server.core.logging_config import get_contextual_logger

logger = get_contextual_logger(__name__)


async def _maybe_await(value: Any) -> Any:
    """若 value 是 awaitable 则等待后返回，否则原样返回（兼容 sync/async provider）。"""
    if inspect.isawaitable(value):
        return await value
    return value


class HotspotMonitor:
    """社交热点监控器：按主题列表查询热点结果，供规划器获取社交话题素材。"""

    def __init__(
        self,
        search_provider: Optional[Callable] = None,
        fallback: Optional[Callable] = None,
    ) -> None:
        """初始化监控器。

        Args:
            search_provider: 搜索 provider，入参 query 返回 [{title, link, snippet}]
            fallback: 备用 provider，search_provider 无结果或失败时调用
        """
        self.search_provider: Optional[Callable] = search_provider
        self.fallback: Optional[Callable] = fallback

    async def get_hotspots(self, topics: List[str], limit: int = 5) -> List[Dict]:
        """按主题列表查询热点，返回至多 limit 条结果。

        无 search_provider 时优雅返回 []；单主题失败记录日志并跳过，不阻断
        其余主题；搜索结果不足 limit 时触发 fallback 补足。
        """
        if not callable(self.search_provider):
            return []
        hotspots: List[Dict] = []
        for topic in topics:
            results: List[Dict] = []
            try:
                results = await _maybe_await(self.search_provider(topic)) or []
            except Exception as e:
                logger.warning("搜索热点失败 %s: %s", topic, e)
            if not results and callable(self.fallback):
                try:
                    results = await _maybe_await(self.fallback(topic)) or []
                except Exception as e:
                    logger.warning("回退搜索热点失败 %s: %s", topic, e)
            hotspots.extend(results)
            if len(hotspots) >= limit:
                break
        return hotspots[:limit]
