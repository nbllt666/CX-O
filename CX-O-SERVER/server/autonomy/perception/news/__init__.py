"""新闻感知子包：RssFetcher 异步抓取 RSS 源并解析标题/链接/摘要。

数据源来自 AutonomyConfig.rss_sources；本子包不依赖第三方 RSS 解析库，
使用标准库 xml.etree.ElementTree 解析 <item>。
"""
