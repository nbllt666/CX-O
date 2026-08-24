"""主动视觉视频叙事增强 —— 后端底座包。

本包承载「前端事件触发 → 回溯打包视频片段 → multipart 上传 → 后端落地」的后端底座，
当前仅实现 **路由 + 独立异步队列 + 临时文件清理** 三件事，不含任何视频理解消费逻辑。

- ``clip_queue``: `VisionClipQueue` 独立异步队列，提供可注入 ``consumer``，
  供下游 VideoUnderstanding / 会话理解模块接入真正的理解消费逻辑。
- ``video_understanding``: `VideoUnderstanding` 作为队列 consumer，把片段喂给
  MultimodalPipeline（video 模态）产出叙事性摘要 ``NarrativeSummary``。
- ``server.api.routers.vision``: `POST /api/vision/clip` 路由（见该模块 docstring）。

consumer 接入与临时文件清理责任边界见 ``clip_queue`` 模块 docstring。

**叙事记忆沉淀**：本包只负责「理解产出 NarrativeSummary」，**叙事记忆写入由下游
NarrativeVisionMemory（Task8）接入**，本包不实现记忆回写。
"""