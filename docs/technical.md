# CX-O 技术文档

> CX-O 是一套面向二次元爱好者的 AI 人格化陪伴系统。本文档从工程视角**完整**描述系统的所有特性、实现逻辑与系统架构，含关键参数、类名与数据流，供开发与维护者阅读。

---

## 目录

- [1. 系统概述](#1-系统概述)
- [2. 系统架构](#2-系统架构)
- [3. 后端服务（CX-O-SERVER）](#3-后端服务cx-o-server)
- [4. 实时语音对话（双流式）](#4-实时语音对话双流式)
- [5. 记忆系统](#5-记忆系统)
- [6. 知识图谱](#6-知识图谱)
- [7. 上下文管理](#7-上下文管理)
- [8. 多 Agent 协作（ACP）](#8-多-agent-协作acp)
- [9. 工具系统](#9-工具系统)
- [10. 插件系统（CXFC）](#10-插件系统cxfc)
- [11. 蒸馏服务与角色卡](#11-蒸馏服务与角色卡)
- [12. 多模态管线与决策核心](#12-多模态管线与决策核心)
- [13. 提醒与任务调度](#13-提醒与任务调度)
- [14. 前端（CX-O-Frontend）](#14-前端cx-o-frontend)
- [15. 语音工作站（CX-O-VoiceWorkStation）](#15-语音工作站cx-o-voiceworkstation)
- [16. Docker 推理服务](#16-docker-推理服务)
- [17. 配置系统](#17-配置系统)
- [附录：目录速览](#附录目录速览)

---

## 1. 系统概述

CX-O 将虚拟形象、实时语音对话、记忆管理、直播推流、声音克隆、AI 作曲等能力整合进一个桌面应用。系统由一条"**ASR 识别 → LLM 推理 → TTS 合成**"的实时语音主链路，和一个承载人设、记忆、工具、协作的"**智能体（Agent）运行时**"构成。

**核心能力一览**

| 能力 | 简述 |
|------|------|
| 实时语音对话 | 全双工（双流式），边听边说，双向互相插话，首包 <300ms |
| 虚拟形象 | Live2D / VRM 双引擎，表情、动作、口型、风场、眼球追踪 |
| 记忆系统 | 三层记忆 + 向量检索 + 知识图谱 + 自动衰减 + 记忆蒸馏 |
| 多 Agent 协作 | 多人格独立管理，ACP 协议互相通信 |
| 直播推流 | OBS 四源拆分（形象/弹幕/字幕/音频），弹幕实时互动 |
| 声音克隆与训练 | VoxCPM 音色设计 + CosyVoice 情感参考 + So-VITS-SVC 训练推理 |
| AI 作曲与歌声 | 歌谱编辑 + MusicXML 导入 + 声库选择 + 歌声合成 |
| 桌面宠物 | 透明悬浮窗、鼠标穿透、右键菜单 |

---

## 2. 系统架构

### 2.1 整体组件

```
┌─────────────────────────────────────────────────────────────────────┐
│                           CX-O 桌面端                                │
│  ┌────────────────┐   ┌──────────────────────────────┐              │
│  │ CX-O-Frontend  │   │ APP-Frontend（Electron 宠物） │              │
│  │ Web 前端(5173) │   └──────────────────────────────┘              │
│  └───────┬────────┘                                                │
│          │ HTTP / WebSocket                                         │
├──────────┼──────────────────────────────────────────────────────────┤
│  ┌───────┴──────────────────────────────────────────────────────┐  │
│  │              CX-O-SERVER（FastAPI，端口 8000）                 │  │
│  │   Gateway(WS) + Backend(REST) + ASR + TTS 单体服务            │  │
│  └───────┬───────────────┬────────────────────────┬─────────────┘  │
│          │               │                        │                │
│  ┌───────┴──────┐  ┌─────┴──────┐  ┌──────────────┴───────────┐   │
│  │  Docker 推理  │  │ CX-O-Voice │  │  第三方引擎/服务           │   │
│  │  asr/llm/tts │  │ WorkStation│  │  Ollama / vLLM / Weaviate│   │
│  └──────────────┘  │ (8200)     │  │  CosyVoice / Orpheus ... │   │
│                    └────────────┘  └──────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.2 组件清单

| 组件 | 技术 | 端口 | 职责 |
|------|------|------|------|
| CX-O-SERVER | Python / FastAPI / uvicorn | 8000 | 统一后端：Gateway(WS) + REST + ASR + TTS 单体 |
| CX-O-Frontend | React / TypeScript / Vite | 5173 | Web 管理界面、聊天、直播、录音作曲 |
| APP-Frontend | Electron | — | 桌面宠物（透明悬浮窗） |
| CX-O-VoiceWorkStation | Python / FastAPI | 8200 | 参考音频生成、SVC 训练/推理、AI 作曲 |
| asr-sensevoice | Docker / FunASR+SenseVoice | 8005 | 语音识别服务 |
| f5-tts-triton | Docker / Triton+TRT-LLM | 8000/8001/8002 | F5-TTS 合成（Triton 加速） |
| llm | Docker / vLLM 或 TRT-LLM | 8080 | 对话大模型推理 |
| orpheus-tts | Docker / vLLM+SNAC | 5060 | Orpheus 多语言 TTS |
| Ollama / vLLM | 外部 | 11434/... | 对话与嵌入模型 |
| Weaviate | 外部 | 8080 | 向量数据库（可选） |

### 2.3 数据流

**实时语音主链路**（详见第 4 章）：

```
麦克风 → VAD 语音活动检测 → ASR Partial/Final 结果
        → LLM Speculative Prefill → TextSmoother 平滑切句
        → TTS 流式合成 → 音频流回前端 → 播放 + 口型/表情驱动
                            ↑__ 双向打断（Agent↔用户）
```

**聊天（文本）链路**：

```
用户消息 → 上下文管理器装配 → 主模型 LLM 推理（可调用工具）
        → 工具调用循环 → 结果写回会话 → 流式返回前端
```

---

## 3. 后端服务（CX-O-SERVER）

### 3.1 入口与生命周期（`server/main.py`）

`main.py` 是统一入口，通过 `lifespan` 协程在启动/关闭时按依赖顺序初始化所有核心服务：

1. 配置加载（`config.py`，Pydantic 模型）
2. 模型路由器（`core/model_router.py`）
3. 记忆管理器（同步 + 异步）
4. 上下文管理器
5. ACP 多 Agent 管理器
6. LLM 客户端
7. 蒸馏服务
8. 副模型路由器（记忆决策用）
9. MCP 管理器、工具注册（内置 / 主模型 / 摘要 / 记忆管理 / 任务 / 图）
10. 向量搜索（Weaviate）初始化与同步
11. 提醒管理器、WebSocket 离线保存
12. 批量衰减处理器、任务调度器
13. CXFC 插件管理器与自动发现
14. ASR / TTS 服务（embedded / remote 模式，含降级回退）
15. 预热：共享 HTTP 客户端、Orpheus TTS、LLM / Embedding 推理

### 3.2 双网关（REST + WebSocket）

- **REST**（`server/api/app.py` + `routers/`）：`/api/v1/...` 路由，覆盖 agents、chat、memory、graph、tools、config、stats、backup、archive、anythingllm、distillation、multimodal、vector、service、acp、cxfc、admin、audio、avatars、live 等。
- **Gateway / WebSocket**（`server/gateway/server.py`）：`/ws` 与 `/ws/live` 两条通道，接收 `action` 驱动的 JSON 消息，按 `ACTION_HANDLERS` 映射到对应 handler（chat / memory / tools / plugin / context / acp / mcp / config / metrics / system / audio / danmaku / events）。

### 3.3 WebSocket 消息协议（`server/protocol/`）

消息以 `action` 字段区分类型，`actions.py` 定义全部 action 常量与 handler 映射。消息结构为 `{action, request_id, data}`，服务端通过 `{action, request_id, ok, data}` 异步回发结果。

| 域 | Action 示例 | 处理者 |
|----|-------------|--------|
| 聊天 | `chat.message` / `chat.stream` / `chat.multimodal` | chat |
| 记忆 | `memory.list/create/delete/search/get/update` | memory |
| 工具 | `tools.list/call/register` | tools |
| 插件 | `plugin.register/heartbeat/list/unregister` | plugin |
| 上下文 | `context.get/append/clear/set` | context |
| ACP | `acp.connect/disconnect/connections/status` | acp |
| MCP | `mcp.connect/disconnect/tools/call/status` | mcp |
| 配置 | `config.get/set/reset` | config |
| 指标 | `metrics.get/requests/history` | metrics |
| 系统 | `system.health/status/info` | system |
| 语音 | `voice.dual_stream` / `voice.partial` / `voice.tts_chunk` / `voice.prefill_started` | audio |
| 弹幕 | `danmaku.list/add/clear` | danmaku |
| 事件 | `events.subscribe/unsubscribe` | events |

### 3.4 核心工具链（`core/`）

按领域分目录：`acp`、`alarm`、`chat`、`context`、`cxfc`、`decision`、`distillation`、`document`、`graph`、`llm`、`memory`、`multimodal`、`plugins`、`session`、`tasks`、`template_engine`、`tools`、`websocket`。

---

## 4. 实时语音对话（双流式）

> 系统最核心的实时链路，位于 `server/handlers/audio.py`（AudioProcessor）与 `server/services/`。

### 4.1 双流式设计思想

- **单工（对讲机）**：听完再说，有天然停顿。
- **双流式（全双工）**：ASR、LLM、TTS 三条流并行执行；用户与 AI 可互相打断，像真人打电话。
- **关键点**：事件由 **ASR 的 Partial（中间）结果**驱动，而非等用户说完；VAD 只做兜底。

### 4.2 边听边说（Listen-while-Speak）

- ASR 一边识别一边把 **Partial 中间结果**实时推给前端显示字幕（`voice.partial`）。
- LLM 在用户说话途中就**开始推理**（投机预填充）。
- TTS **边收边合成边播放**，不等整句（`voice.tts_chunk` 流式推送音频块）。

### 4.3 投机预填充（Speculative Prefill）

- 用户说出 **2 个字**（`_trigger_char_threshold=2`）即触发 LLM 推理，不必等 VAD `on_end`。
- 省去等待 VAD 判定"说完"的约 **500ms 静默判定**，显著降低端到端延迟。
- 后端推送 `voice.prefill_started` 通知前端。

### 4.4 双向打断（Bidirectional Interrupt）

**用户打断 AI**（`asr_interrupt.py` / `audio.py`）：
- VAD 检测到 `speech_start`（用户开口）→ 立即 `_interrupt_pipeline()` 取消正在运行的 LLM+TTS 流水线，停止 TTS 播放。
- 触发 `asyncio.CancelledError`，处理器将**当前用户已说文本累积到 pending**，供下一轮合并，不丢内容。

**AI 打断用户**（`agent_interrupt_user.py`，类 `AgentInterruptUser`）：
- 在用户说话过程中（`on_asr_partial_result`），AI 判断是否插话。
- **三态判定**：`INTERRUPT`（可插话）/ `CONTINUE`（用户还在组织语言，等）/ `IGNORE`（自言自语，无需回应）。
- **两种模式**：
  - `main_llm`：用主模型生成插入的回复内容（含情感/标点）。
  - `independent_llm`：用独立小模型只输出三态标记（不占用主 LLM 槽位），回复内容由主流水线生成。
- 判定为 `INTERRUPT` 时：停掉当前 TTS，直接播放一句简短插话（`interrupt_and_reply`）。

### 4.5 首包延迟优化（<300ms 的落地手段）

`_run_pipeline` 是 LLM → TextSmoother → TTS 的流水线，每一环都是 async generator，形成**管道并行**：

1. **Prompt 精简**：`build_messages(is_realtime_voice=True)` 跳过 MemoryRouter / HybridSearch / 重型隐藏提示词，仅保留核心 System Prompt + 最近 2 轮对话，省去约 **1500 token Prefill（100-200ms）**。
2. **回复长度限制**：实时语音回复应为短口语（2~3 句），`max_tokens=min(agent_max, 150)`，阻断 LLM 进入长文总结模式导致 TTS 排队。
3. **TextSmoother 平滑缓冲**：`smooth(llm_stream, window_ms=30, char_threshold=2)`，以 30ms 滑动窗口把 1~2 字的碎片 token 聚合为 3~5 字词组，用约 40ms 延迟换取音质（远小于 300ms 预算）。C4 优化：`window_ms 40→30`、`char_threshold 3→2`。
4. **TTS 细粒度流式合成**：`synthesize_stream_fine` 接受 token 流，**4 字即切片送合成**，不必等整句，首包音频压缩数百 ms。
5. **流式推送**：`synthesize_stream_fine` 产出第一个音频块即通过 `voice.tts_chunk(is_final=False)` 推给前端，不等整句。

### 4.6 ASR 服务（`asr_service.py`）

- 引擎：SenseVoice，支持情感 / 事件 / 语种检测。
- 模式：`embedded`（本地模型）与 `remote`（HTTP/WS 远程服务）两种，可降级回退。
- **嵌入式**：加载本地模型，在单独线程池中执行推理。
- **远程**：HTTP 请求远程识别接口；流式优先走 WS（`ws://127.0.0.1:8005/ws/asr/stream`）。
- 识别结果附带 `language`、`emotion`、`event`（BGM/掌声/笑声/哭声/咳嗽/呼吸等）。
- 流式分片参数：`chunk_size=1600`、`hop_size=800`、`look_back=8000`。

### 4.7 TTS 服务（`tts_service.py`）

- 模式：`embedded` / `remote` / `triton` / `orpheus`。
- **双引擎**：
  - **F5-TTS**（默认，Triton 加速，支持参考音频克隆，`model_type=F5-TTS`）。
  - **Orpheus**（基于 vLLM 的多语言 TTS，不支持参考音频，用预设音色）。
- 流式合成：`synthesize_stream_fine` 直接对接 token 流，边收边切边合成，每个 `text_segment` 对应一个 TTS chunk；`cross_fade_duration=0.15` 平滑过渡。
- 情感语音：`emotion_enabled`，不同情绪用不同参考音色（`emotion_refs_dir`）。
- 音效标签：`effects_enabled`，文本中插入标签触发音效。
- 过渡词：`transition_enabled`，在开播前插入过渡词（`transition_text="嗯，"`），衔接自然。

### 4.8 VAD 语音活动检测（`vad_processor.py`）

- 三种模式：`ENERGY`（能量阈值）/ `WEBRTC`（轻量高效，默认）/ `SILERO`（神经网络，最准确）。
- 双流式下 VAD 仅作兜底，不阻塞 ASR Partial 驱动的主流程。
- `min_silence_duration_ms=150` 判定句尾，加速兜底修正约 350ms。

### 4.9 弹幕防火墙（`firewall.py`）与自适应轮询

- **防火墙**：三档过滤不当弹幕/内容，保障直播与对话安全。
- **自适应轮询**（`adaptive_polling.py`）：动态调整轮询间隔（`min_interval_ms=50 ~ max_interval_ms=2000`），兼顾实时性与负载。

### 4.10 实时性能预算

代码注释中标注的实测目标：vLLM 推理约 **90 tokens/s**、TTFT 约 **80ms**、Prompt Tokens < 500 锁死 80ms TTFT。优化演进目标：C4 `P50<600ms` → `P50<400ms`。各环节延迟预算：

| 环节 | 手段 | 预算 |
|------|------|------|
| Prefill | 精简 Prompt（省 ~1500 token） | 100-200ms |
| 推理 | vLLM 流式 + 短回复限长 | TTFT ~80ms |
| 平滑 | TextSmoother 30ms 窗口 | ~40ms |
| 合成/传输 | TTS 4 字切片 + 流式推送 | 首包 <300ms 总预算 |

---

## 5. 记忆系统

> 位于 `server/core/memory/`，是系统的"长期记忆"核心。**本节给出具体实现逻辑**：存储结构、写入/读取/检索流程、衰减公式与决策路由。

### 5.1 架构与存储

**顶层模型**：`MemoryManager`（单例，`__init__`/`__new__`）+ `AsyncMemoryManager`（异步包装）。

`MemoryManager` 是一个单例，原 2998 行按功能域拆分为 **9 个 mixin**：

| Mixin | 职责 |
|-------|------|
| `_MemoryDBMixin` | DB 基础设施：连接池、表 schema、agent 表隔离、清理关闭 |
| `_GraphIntegrationMixin` | 知识图谱集成 |
| `_VectorIntegrationMixin` | 向量存储集成与向量搜索 |
| `_MemoryCRUDMixin` | 核心 CRUD（写/读/搜索/改/删/恢复）+ async 包装 |
| `_PermanentMemoryMixin` | 永久记忆操作 |
| `_AdvancedSearchMixin` | 3D 搜索、召回、衰减统计、记忆上下文 |
| `_BatchOperationsMixin` | 批量操作 |
| `_QueryHelpersMixin` | 查询辅助 |
| `_DecisionMixin` | DecisionCore 集成（rejected_content 表 + write_with_decision） |

**SQLite 存储**（`data/memories.db`）：默认 `memories` 表 schema——

```
memories(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  type VARCHAR(20) NOT NULL,          -- long_term / short_term / permanent
  content TEXT NOT NULL,
  vector_id VARCHAR(100),             -- 关联向量库对象
  metadata TEXT,                      -- JSON
  importance INTEGER DEFAULT 3,       -- 1-5 等级
  importance_score FLOAT DEFAULT 0.6, -- 0-1 连续分
  decay_type VARCHAR(20) DEFAULT 'exponential',  -- exponential/ebbinghaus/zero
  decay_params TEXT,                  -- JSON
  reactivation_count INTEGER DEFAULT 0,
  emotion_score FLOAT DEFAULT 0.0,
  permanent BOOLEAN DEFAULT FALSE,
  psychological_age FLOAT DEFAULT 1.0,
  tags TEXT,                          -- JSON 数组
  created_at / updated_at / archived_at TIMESTAMP,
  is_deleted BOOLEAN DEFAULT FALSE,   -- 软删除
  source VARCHAR(50) DEFAULT 'user',
  workspace_id VARCHAR(100) DEFAULT 'default',
  agent_id VARCHAR(100) DEFAULT 'default'
)
```

**Agent 记忆隔离**：非 default 的 Agent 有专属表 `memories_{safe_agent_id}`（`_get_table_name` + `_ensure_agent_table`），避免跨 Agent 记忆串扰。另配 `audit_logs` 表记录每次写/删/召回操作。

### 5.2 写入流程

**直接写入** `write_memory(content, memory_type, importance, ...)`：
1. `_ensure_agent_table(agent_id)` 确保表存在。
2. INSERT 记忆行：`importance_score = 0.6（非永久）或 1.0（永久）`；`decay_type = "zero"（永久）或 "exponential"`。
3. 写 `audit_logs`（operation=create）并 commit。
4. **向量同步**（`_sync_vector_for_memory`）：失败仅告警，不影响主操作。
5. **图同步**（`_sync_to_graph`，`_graph_enabled` 时）：失败仅告警。

**决策写入** `write_with_decision(content, decision, metadata)`（与 DecisionCore 联动）：
- 按 `decision.location` 分派：
  - `memories` → `write_memory`（long_term，importance=3）
  - `permanent_memories` → `write_permanent_memory`
  - `rejected` → 写入 `rejected_content` 表（D6_REJECT 落地）
- `rejected_content` 表记录：`quality_score`、`reject_reason`、`decision_point`、`rubric_snapshot`、`llm_reasoning`、`llm_confidence`、`expires_at`（retention_days 默认 30）。
- `cleanup_expired_rejected_content` 按 `expires_at` 标记 `is_purged`。

**异步包装**：`write_memory_async` 等通过 `asyncio.to_thread` 包装同步 sqlite 调用，避免阻塞对话主线程。

### 5.3 读取与检索流程

**记忆路由** `MemoryRouter`（`router.py`）——`route(query, scene_type, ...)` 的流程：

```
最近交互记忆（session tag 召回，最多 100）
  + 检索结果（hybrid 向量+关键词，或 SQL LIKE）
→ _score_memories 三维打分 → _apply_filters 过滤
→ _apply_scene_adjustment 场景调整 → 取 config.max_memories 条
```

- **三维打分**：`final_score = importance·w₁ + time·w₂ + relevance·w₃`。
- **场景感知权重**：按 `scene_type` 切换权重（`_get_weights`）——

| 场景 | importance | time | relevance |
|------|-----------|------|-----------|
| task（任务） | 0.30 | 0.20 | 0.50 |
| chat（闲聊/情感） | 0.45 | 0.20 | 0.35 |
| first_interaction（首次） | 0.30 | 0.30 | 0.40 |
| recall（召回） | 0.25 | 0.25 | 0.50 |
| learning（学习） | 0.35 | 0.20 | 0.45 |
| problem_solving（问题解决） | 0.25 | 0.20 | 0.55 |
| creative（创造） | 0.30 | 0.40 | 0.30 |

- **过滤规则**：永久记忆始终保留；`score >= high_priority_threshold(0.8)` 或 `>= min_score_threshold` 保留；显式提及的记忆保留。
- **混合检索**（`hybrid_search.py`）：`vector_weight=0.6`、`keyword_weight=0.4`、`min_score=0.2`。

**3D 检索** `search_memories_3d`（`advanced_mixin`）：默认权重 `(0.35, 0.25, 0.4)`，对每条记忆并行计算 importance / time / relevance，永久记忆 +0.15 加成，按 `final_score` 排序。

### 5.4 衰减机制（核心公式）

`DecayCalculator`（`decay.py`）采用**实时计算**模式（时间分不预存库，读取时现算）。

**双阶段指数衰减**（默认）：

```
T(t) = α·e^(-λ₁·Δt) + (1-α)·e^(-λ₂·Δt)
衰减后分数 = importance × T(t)
```

**艾宾浩斯优化版**（备选，`decay_type="ebbinghaus"`）：

```
T(t) = 1 / (1 + (Δt/T₅₀)^k)      # T₅₀=30, k=2
```

**永久记忆**：`decay_type="zero"` 或 `importance ≥ 0.95` 或 `permanent=True` → 恒为 1.0，不衰减。

**重要性分层**（`IMPORTANCE_LEVELS`，α/λ₁/λ₂ 随重要度递增衰减速度）：

| 重要度区间 | 等级分 | α | λ₁ | λ₂ | 180天保留率 |
|-----------|-------|-----|------|------|-----------|
| ≥0.95 | 1.00 | — | — | — | 1.00（永久） |
| 0.85–0.99 | 0.92 | 0.2 | 0.01 | 0.001 | 0.95 |
| 0.70–0.84 | 0.77 | 0.35 | 0.08 | 0.015 | 0.80 |
| 0.50–0.69 | 0.60 | 0.6 | 0.25 | 0.04 | 0.50 |
| 0.30–0.49 | 0.40 | 0.75 | 0.45 | 0.08 | 0.25 |
| <0.30 | 0.15 | 0.9 | 0.80 | 0.15 | 0.05 |

**再激活加成**（`recall_memory` / `calculate_reactivation_score`）：

```
新时间分 = min(旧时间分 × (1 + 0.2×再激活次数) + 0.1 + 0.05×|情绪强度|, 1.0)
```

召回时同时更新 `reactivation_count + 1`、`emotion_score`（取均值），并写 audit_logs（operation=recall）。

**网络效应**（`calculate_network_effect`）：`增强 = min(0.1×√关联活跃记忆数, 0.3)`。

**相关性维度**（`calculate_relevance_score`）：语义相似 60% + 上下文关联 30% + 关键词匹配 10%。

**整数↔分数换算**：`importance_to_score`（5→0.95、4→0.77、3→0.60、2→0.40、1→0.15）与 `score_to_importance` 互为逆。

### 5.5 向量检索

- 后端：`weaviate` 或 `weaviate_embedded`（Milvus Lite / Chroma / Qdrant 已弃用，启动时告警）。
- 嵌入：Ollama（默认 `nomic-embed-text`）或 vLLM Embedding 模型，维度 `vector_size=768`。
- 启动时 SQLite ↔ 向量库全量/增量同步，保证一致性。
- 写入/删除时同步增删向量，失败不阻塞主操作。

### 5.6 记忆蒸馏（`core/distillation/`）

超长上下文智能切分 + 多轮蒸馏对话 + 角色卡 Agent 自动创建，把海量内容提炼成可检索的记忆。

---

## 6. 知识图谱

> 位于 `server/core/graph/`，用图结构组织实体与关系，支持语义检索。

- **存储**：SQLite（`data/graph.db`，`database.py`）+ 可选 Weaviate（`graph_store.py`）。
- **节点/边**（`nodes.py` / `edges.py`）：实体与关系建模。
- **查询**：
  - `semantic_query` / `semantic_search`：语义检索。
  - `hybrid_query`：混合查询（关键词 + 向量 + 图遍历）。
  - `traversal`：图遍历。
- **向量化**（`vectorizer.py`）：实体/关系文本向量化。
- **可视化**（`visualization.py`）：前端图可视化数据接口。
- **按需创建**：图数据库 lazy 初始化，首次调用工具时才创建实例。
- **配置**（`GraphConfigSection`）：`enabled`、`auto_create_schema`、Weaviate（`vector_dim=384`、`ef_construction=128`、`max_connections=16`）、Embedding（`all-MiniLM-L6-v2`、`batch_size=32`）。

---

## 7. 上下文管理

> 位于 `server/core/context/`。

- **上下文管理器**（`manager.py`）：维护会话消息历史，装配进入 LLM 的上下文。
- **摘要器**（`summarizer.py`）：上下文超长时自动摘要压缩，控制 token 预算。
- **Agent 上下文管理器**（`agent_context_manager.py`）：管理每个 Agent 的独立上下文。
- **会话存储**（`core/session/`）：会话持久化。
- **限额**（`ContextLimitsConfig`）：`max_messages=500`、`window_size=50`、`summary_threshold=100`、`summarizer_max_topics=15`、`summarizer_max_key_points=15`。

---

## 8. 多 Agent 协作（ACP）

> 位于 `server/core/acp/`，ACP（Agent Collaboration Protocol）让不同 AI 伙伴互相通信协作。

- **管理器**（`manager.py`）：注册 Agent、维护连接、路由消息。
- **发现**（`discover.py`）：UDP 广播发现其他 Agent 实例（`discovery_port=9999`、`broadcast_port=9998`）。
- **分组**（`group.py`）：Agent 分组协作（`port=10001`、`max_members=50`）。
- **配置**：`agent_id=cxo-agent-001`、`connection.port=10000`、`heartbeat_interval=10`。
- 前端 `AcpPage` 提供连接管理界面。

---

## 9. 工具系统

> 位于 `server/core/tools/`，为 LLM 提供可调用能力。

- **注册中心**（`registry.py`）：统一注册、启停、统计工具。
- **工具集**：
  - `builtin`：内置基础工具。
  - `master_tools`：主模型工具（记忆、上下文、ACP 等）。
  - `summary_tools`：摘要模型工具。
  - `assistant_tools`：记忆管理模型工具。
  - `task_tools`：任务辅助。
  - `graph_tools`：知识图谱工具。
  - `mcp`：通过 MCP（Model Control Protocol）接入外部工具。
- **工具调用循环**：LLM 推理 → 识别工具调用 → 执行 → 结果回填 → 继续推理，直至无工具调用或达上限。

---

## 10. 插件系统（CXFC）

> 位于 `server/core/cxfc/`，CXFC 是 CX-O 的插件/技能协议。

- **发现**（`discovery.py`）：UDP 广播自动发现本地插件（`discovery_port=9996`、`broadcast_port=9997`）。
- **管理器**（`manager.py`）：插件生命周期、心跳检测（`heartbeat_timeout=30`、`check_interval=10`）。
- **技能注册表**（`skill_registry.py`）：维护所有可用技能。
- **存储**（`storage.py`）：插件数据持久化（`data/cxfc_plugins.db`）。
- 插件通过标准端点（`/tools`、`/skills`、`/call`）暴露能力，主服务按 host:port 直连抓取。
- 语音工作站启动时向主服务注册并保持心跳。

---

## 11. 蒸馏服务与角色卡

> 位于 `server/core/distillation/`。

- **蒸馏服务**（`distillation_service.py`）：多模态源（text / character_card / image / video / audio / conversation_log）→ 蒸馏对话 → 提炼记忆 / 创建 Agent。
  - 配置：`max_turns=4`（1-6）、`session_timeout_seconds=1800`、`quality_llm_enabled`（LLM 质量评估，失败回退启发式基础分 0.4）。
- **角色卡解析**（`character_card_parser.py`）：解析 SillyTavern 角色卡（PNG tEXt chunk 或 JSON，兼容 V1/V2/V3 及非标准字段）。
- **批量路由**（`api/batch_routes.py`）：解析角色卡、从角色卡启动蒸馏、终结并创建角色卡 Agent。
- 前端 `CharacterCardModal`：从酒馆角色卡直接创建 Agent，无需经过蒸馏状态机。

---

## 12. 多模态管线与决策核心

### 12.1 多模态管线（`core/multimodal/multimodal_pipeline.py`）

- 支持 5 种模态：`text` / `character_card` / `image` / `video` / `audio`。
- `worker_pool_size=4`、`task_timeout_seconds=120`。
- OCR：`paddleocr`（`ocr_language=ch`）；vision 不可用时降级为纯 OCR（`vision_degraded_fallback`）。
- CX-O 扩展：video/audio 走 vLLM 原生解码（仅当 LLM provider=vllm 时启用）。
- 用于聊天中的多模态输入处理与蒸馏数据源。

### 12.2 决策核心（`core/decision/decision_core.py`）

基于规则 + 模型的决策判断，覆盖 6 个决策点（rubric）：

| 决策点 | 含义 | 关键阈值 |
|--------|------|---------|
| D1_LOCATION | 记忆存放位置 | — |
| D2_METADATA | 记忆元数据 | — |
| D3_ASK_USER | 是否追问用户 | `ask_user_confidence_threshold=0.4` |
| D4_REDISTILL | 是否再次蒸馏 | `max_redistill_turns=2` |
| D5_CROSS_VALIDATE | 跨源验证 | 数据源列表 |
| D6_REJECT | 质量拒绝 | `quality_reject_threshold=0.3` |

- **永久记忆**：重要性 ≥ `importance_threshold_permanent=0.7`。
- 置信度极低时回退 system_prompt（`system_prompt_fallback_enabled`）。
- 拒绝内容保留 `rejected_content_retention_days=30` 天，审计日志落盘 `data/distillation_logs/`。

---

## 13. 提醒与任务调度

- **提醒管理器**（`core/alarm/manager.py`）：定时提醒，触发时通过 WebSocket 推送给 Agent/前端。
- **任务调度**（`core/tasks/`）：`TaskScheduler` 每 60s 扫描执行任务。

---

## 14. 前端（CX-O-Frontend）

> React + TypeScript + Vite，路由见 `src/App.tsx`。

### 14.1 页面路由

| 路径 | 功能 |
|------|------|
| `/chat` | 聊天（含双流式语音） |
| `/dashboard` | 仪表盘 |
| `/memories` | 记忆管理 |
| `/archive` | 归档 |
| `/agents` | Agent 管理（新建人设、配置参数） |
| `/acp` | ACP 多 Agent 协作 |
| `/plugins`、`/tools` | 插件 / 工具 |
| `/audio-workstation` | 录音作曲 |
| `/settings` | 设置 |
| `/memory-agent`、`/vector-data` | 记忆 Agent / 向量数据 |
| `/live`、`/live/split/*` | 直播（OBS 四源：avatar/danmaku/subtitle/audio） |
| `/pet` | 桌面宠物 |

### 14.2 语音管线（`src/hooks/`）

- `useAudioStream`：双流式语音会话（init / audio / end），管理音频采集与播放。
- `useMicrophone`：麦克风采集。
- `useAudioAnalyzer`：音频能量分析（驱动口型/表情）。
- `useWebSocket` / `useLiveWebSocket` / `ws/transport`：连接管理。

### 14.3 虚拟形象

- **Live2D**（`components/Live2D/`）：`live2dEngine` 加载 `.model3.json`，表情、口型（`Live2DLipSync`）、动作（`Live2DMotion`）、音频分析。
- **VRM**（`components/VRM/`）：`VRMEngine` 加载 `.vrm`，表情、口型、动作触发、风场（`VRMWindField`）、眼球/元音分析（`VowelAnalyzer`）。
- 统一由 `AvatarDriver` 抽象层驱动，模型无关。

### 14.4 UI 与动画

- 扁平化设计 + Apple Liquid Glass 玻璃拟态效果（`lib/glass/`，WebGL shader）。
- 二次元视觉元素（`components/anime/`）：花瓣、星轨、粒子、光晕等动效。
- 动画系统（`lib/motion/`）：GSAP 时间线、弹簧、贝塞尔曲线、橡皮筋滚动。
- 响应式（`lib/responsive/`）：断点、移动端降级。
- 主题（`lib/theme/`）：亮暗主题、跨淡入淡出。

---

## 15. 语音工作站（CX-O-VoiceWorkStation）

> Python / FastAPI，端口 8200，提供声音克隆与训练、AI 作曲能力。

### 15.1 参考音频生成

- `ref_audio` / `voxcpm`：VoxCPM 音色设计。
- `emotion_ref_generator`：CosyVoice 情感参考音频生成（8 情感 + 56 过渡 = 64 参考音频）。

### 15.2 SVC 训练与推理

- `sovits_svc_trainer` / `sovits_svc_infer`：So-VITS-SVC 训练与推理。
- `dataset_builder`：数据集构建。
- 训练在子进程中运行，服务关闭时自动停止并释放 GPU。

### 15.3 AI 作曲与歌声合成

- `music/`：歌谱（score）、自动编排（arranger）、多轨伴奏（accompaniment）、混音（mixer）、MusicXML 导入。
- `song_pipeline` / `singing_engine`：歌声合成。
- 支持 VoxCPM / Orpheus / 参考音频等多种音源。

### 15.4 CXFC 集成

- 启动时注册为 CXFC 插件并保持心跳，通过 `/tools`、`/skills`、`/call` 暴露能力给主服务。

---

## 16. Docker 推理服务

`docker-compose.yml` 编排 GPU 推理服务，构成语音/LLM 推理层：

| 服务 | 说明 |
|------|------|
| `asr-sensevoice` | FunASR + SenseVoice 语音识别，端口 8005 |
| `f5-tts-triton` | F5-TTS Triton + TRT-LLM 加速，端口 8000/8001/8002 |
| `llm` | 对话大模型（vLLM + GGUF 或 TRT-LLM），端口 8080 |
| `orpheus-tts` | Orpheus 多语言 TTS（vLLM 后端 + SNAC Bridge），端口 5060 |

- 均支持 GPU 资源预留、健康检查、自动重启。
- 另有 `docker-compose.weaviate*.yml` 用于 Weaviate 向量库部署。

---

## 17. 配置系统

> `server/config.py`，Pydantic 模型，从 `config.json` 读取，支持 `CXO_` 前缀环境变量覆盖；`get_settings()` 为类级单例，`reset()` 即重建。

### 17.1 加载优先级

```
config.json 文件配置  →  deep_merge  →  环境变量（CXO_ 前缀）  →  RADIX auto_fill
```

- 环境变量映射：如 `CXO_LLM_PROVIDER` → `llm.provider`、`CXO_ASR_MODE` → `asr.mode`、`CXO_MEMORY_VECTOR_BACKEND` → `memory.vector_backend`。
- 相对路径经 `_resolve_data_path` 归一化为项目根绝对路径，消除运行时工作目录依赖。

### 17.2 主要配置段与默认值

| 配置段 | 关键默认值 |
|--------|-----------|
| `system` | host `0.0.0.0`、port `8000`、workers `1` |
| `llm` | provider `ollama`、host `http://localhost:11434`、model `qwen3:latest`、temp `0.7`、max_tokens `32768` |
| `models` | main / summary(max_tokens 131072) / memory(max_tokens 131072)，defaults 指向 main |
| `asr` | mode `remote`、model `SenseVoiceSmall`、device `cuda`、ws_url `:8005/ws/asr/stream` |
| `tts` | mode `remote`、model `F5TTS_v1_Base`、remote_url `:5000`、cross_fade `0.15`、emotion/effects 开 |
| `tts.orpheus` | url `:5060`、model `canopylabs/orpheus-multilingual-research-release`、voice `长乐`、sample_rate `24000` |
| `memory` | vector_backend `weaviate`、embedding `nomic-embed-text`、permanent_threshold `0.95`、dedup `0.85`、短期7天/长期365天 |
| `database` | `data/cxo.db`、`memories.db`、`sessions.db`；`sqlite+aiosqlite` |
| `graph` | `data/graph.db`、weaviate url `:8080`、embedding `all-MiniLM-L6-v2` |
| `acp` | agent_id `cxo-agent-001`、discovery `9999/9998`、group port `10001` |
| `cxfc` | heartbeat `30`、discovery `9996/9997`、storage `data/cxfc_plugins.db` |
| `limits.memory` | max_memories `30`、注入 `20`、去重相似 `0.5`、chat_history `50` |
| `limits.context` | max_messages `500`、window `50`、summary_threshold `100` |
| `limits.firewall` | max_msg_len `10000`、5 msg/s、100 msg/min、重复 `3`/30s |
| `limits.frontend` | 上传 `500MB`、聊天图片 `20`、温度上限 `5`、语速上限 `3` |
| `distillation` | port `8000`、max_turns `4`、session_timeout `1800`、quality_llm 开 |
| `multimodal_pipeline` | worker_pool `4`、OCR `paddleocr`、vllm_native 开 |
| `decision_core` | permanent `0.7`、quality_reject `0.3`、ask_user `0.4`、max_redistill `2` |

---

## 附录：目录速览

```
CX-O/
├── CX-O-Frontend/          # 前端桌面应用（React + Electron）
├── CX-O-SERVER/            # 后端服务（FastAPI + WebSocket 单体）
│   └── server/
│       ├── api/            # REST 路由
│       ├── gateway/        # WebSocket 网关
│       ├── handlers/       # WS 消息处理器（chat/audio/tools/...）
│       ├── services/       # 语音服务（asr/tts/vad/interrupt/...）
│       ├── core/           # 领域核心（memory/graph/tools/acp/...）
│       ├── protocol/       # 消息协议（action）
│       └── storage/        # 数据库连接与迁移
├── CX-O-VoiceWorkStation/  # 语音工作站（声音克隆/训练/作曲）
├── docker/                 # 推理服务 Dockerfile
├── docs/                   # 项目文档
├── models/                 # 本地模型
├── config/                 # 全局配置
└── public/                 # 公共契约资源
```