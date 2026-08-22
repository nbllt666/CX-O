"""RSS 新闻源抓取器（RssFetcher）。

- 异步逐个抓取配置的 RSS 源（httpx.AsyncClient），不引入第三方解析依赖，
  使用标准库 xml.etree.ElementTree 解析 <item> 的 title / link / description
- 单源失败不阻断其余源：记录日志并跳过；全部失败返回 []
- 解析容错：缺字段补空字符串；非 XML 响应抛 ET.ParseError 被跳过
- 结果结构：{title, link, summary, published?, source}，published 仅在有
  pubDate 时填充
- 本模块无文件 IO，禁止相对路径
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Dict, List

import httpx

from server.core.logging_config import get_contextual_logger

logger = get_contextual_logger(__name__)


def _find_text(element: ET.Element, tag: str) -> str:
    """取 element 下第一个匹配 tag 的子元素文本；缺失返回空字符串。

    先按精确 tag 查找；未命中时再按 ``{ns}tag`` 形式匹配，兼容带默认
    命名空间的 RSS 源。
    """
    node = element.find(tag)
    if node is not None:
        return (node.text or "").strip()
    for sub in element.iter(tag):
        return (sub.text or "").strip()
    return ""


class RssFetcher:
    """RSS 新闻源抓取器。

    构造接收 RSS 源 URL 列表、单请求超时（秒）与每源最多抓取条数。
    """

    def __init__(self, urls: List[str], timeout: float = 10.0, max_items: int = 10) -> None:
        """初始化抓取器。

        Args:
            urls: RSS 源 URL 列表
            timeout: 单请求超时秒数（默认 10.0）
            max_items: 每源最多解析的 <item> 条数（默认 10）
        """
        self.urls: List[str] = list(urls)
        self.timeout: float = timeout
        self.max_items: int = max_items

    async def fetch(self) -> List[Dict]:
        """逐个抓取全部 RSS 源并解析，返回汇总结果列表。

        单源失败记录日志并跳过，不阻断其余源；全部失败返回 []。
        """
        results: List[Dict] = []
        async with httpx.AsyncClient(
            timeout=self.timeout, follow_redirects=True, trust_env=False, proxy=None
        ) as client:
            for url in self.urls:
                try:
                    response = await client.get(url)
                    response.raise_for_status()
                    results.extend(self._parse(url, response.text))
                except Exception as e:
                    logger.warning("抓取 RSS 源失败 %s: %s", url, e)
        return results

    def _parse(self, source: str, xml_text: str) -> List[Dict]:
        """解析单个 RSS 源的 XML 文本，返回至多 max_items 条 <item>。

        非 XML 响应抛 ET.ParseError，由 fetch() 捕获后跳过该源。
        """
        root = ET.fromstring(xml_text)
        items: List[Dict] = []
        for item in root.iter("item"):
            title = _find_text(item, "title")
            link = _find_text(item, "link")
            description = _find_text(item, "description")
            pub_date = _find_text(item, "pubDate")
            entry: Dict = {
                "title": title,
                "link": link,
                "summary": description,
                "source": source,
            }
            if pub_date:
                entry["published"] = pub_date
            items.append(entry)
            if len(items) >= self.max_items:
                break
        return items
