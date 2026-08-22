"""CX-O-Autonomy 感知层子包。

承载自主系统对环境的感知能力，按信息域划分为三个子包：

- news/    新闻感知（RssFetcher）：异步抓取配置的 RSS 源并解析标题/链接/摘要
- social/  社交感知（HotspotMonitor）：通过注入的搜索 provider 获取社交热点
- env/     环境感知（ContextSensor）：本地时间 / 用户在线 / 天气 快照

感知层产出统一供规划器作为行动决策的上下文输入（P1 后续任务）。
"""
