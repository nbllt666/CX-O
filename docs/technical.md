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
- [14. 前端（APP-Frontend）](#14-前端app-frontend)
- [15. 语音工作站（CX-O-VoiceWorkStation）](#15-语音工作站cx-o-voiceworkstation)
- [16. Docker 推理服务](#16-docker-推理服务)
- [17. 配置系统](#17-配置系统)
- [18. 主动视觉与电脑控制](#18-主动视觉与电脑控制)
- [19. 自我进化服务（CXO-Tuner）](#19-自我进化服务cxo-tuner)
- [20. CX-O-Autonomy 自主系统](#20-cx-o-autonomy-自主系统)
- [21. 梦境引擎（Dream）](#21-梦境引擎dream)
- [22. 生理信号接入（Physio）](#22-生理信号接入physio)
- [23. 管理面（CX-A）与哨兵集群（多机互备）](#23-管理面cx-a与哨兵集群多机互备)
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
| 声音克隆与训练 | VoxCPM 音色设计与情感参考 + So-VITS-SVC 训练推理 |
| AI 作曲与歌声 | 歌谱编辑 + MusicXML 导入 + 声库选择 + 歌声合成 |
| 桌面宠物 | 透明悬浮窗、鼠标穿透、右键菜单 |
| 自我进化 | 可选独立服务，对话反馈驱动自动微调，越用越懂你 |

---

## 2. 系统架构

### 2.1 整体组件

```
┌─────────────────────────────────────────────────────────────────────┐
│                           CX-O 桌面端                                │
│  ┌──────────────────────────────────────────────┐                   │
│  │            APP-Frontend（统一前端）           │                   │
│  │  管理界面 · 聊天 · 直播 · 录音作曲 · 桌宠     │                   │
│  │  浏览器模式 :3100 / Electron 桌面模式         │                   │
│  └───────────────────────┬──────────────────────┘                   │
│                          │ HTTP / WebSocket                         │
├──────────────────────────┼──────────────────────────────────────────┤
│  ┌───────────────────────┴──────────────────────────────────────┐  │
│  │              CX-O-SERVER（FastAPI，端口 8000）                 │  │
│  │   Gateway(WS) + Backend(REST) + ASR + TTS 单体服务            │  │
│  └───────┬───────────────┬────────────────────────┬─────────────┘  │
│          │               │                        │                │
│  ┌───────┴──────┐  ┌─────┴──────┐  ┌──────────────┴───────────┐   │
│  │  Docker 推理  │  │ CX-O-Voice │  │  第三方引擎/服务           │   │
│  │  asr/llm/tts │  │ WorkStation│  │  Ollama / vLLM / Weaviate│   │
│  └──────────────┘  │ (8200)     │  │  CosyVoice3 / Qwen3-TTS  │   │
│                    └────────────┘  └──────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.2 组件清单

| 组件 | 技术 | 端口 | 职责 |
|------|------|------|------|
| CX-O-SERVER | Python / FastAPI / uvicorn | 8000 | 统一后端：Gateway(WS) + REST + ASR + TTS 单体 |
| APP-Frontend | React / TypeScript / Vite / Electron | 3100（浏览器）/ Electron | 统一前端：管理界面、聊天、直播、录音作曲、桌面宠物 |
| CX-O-VoiceWorkStation | Python / FastAPI | 8200 | 数据集生成、SVC 训练/推理、AI 作曲 |
| asr-sensevoice | Docker / FunASR+SenseVoice | 8005 | 语音识别服务 |
| cosyvoice-tts | 独立 conda 服务 | 8094 | CosyVoice3 主引擎（克隆与情感合成） |
| voicedesign-tts | vLLM-Omni | 8091 | 无参考音频的音频设计 |
| qwen3-tts-base | vLLM-Omni | 8093 | TTS 降级兜底 |
| llm | Docker / vLLM 或 TRT-LLM | 8080 | 对话大模型推理 |
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
15. 预热：共享 HTTP 客户端、CosyVoice3 TTS、LLM / Embedding 推理

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

**打断判定收敛与智能化**（2026-08 演进）：

- **判定收敛**：打断模块收敛到公共基类 `InterruptModuleBase`（`interrupt_llm.py`），`asr_interrupt.ASRInterruptModule` 与 `agent_interrupt_user.AgentInterruptUser` 继承复用；底层统一「HTTP 调用 + JSON 解析 + 关键词兜底 + 超时降级」的 Ollama 判定 `call_ollama_decision`。
- **提问意图硬闸门（Feature A）**：LLM 判 `INTERRUPT` 后经确定性闸门 `_has_question_or_request`（提问词 + 祈使请求词）二次确认，无意图特征降级 `IGNORE`，消除情绪独白误打断（`question_intent_required` 开关，默认 true）。
- **固定搭配剔除**：`_NON_QUESTION_PHRASES`（14 项）先剔除「含疑问字但实为陈述 / 客套 / 填充」的固定搭配再作子串匹配，避免误判。
- **最终完整请求回复触发（Feature B）**：ASR `is_final`（真实「用户说完」信号）且累计文本通过意图闸门、本 utterance 未打断时，主动触发一次回复（`reply_on_final_question` 开关，默认 true），解决短句提问说完后无回复。
- **打断 / 回复标签解耦**：`on_asr_partial_result` 返回 `should_interrupt`（仅真打断）/ `should_reply`（仅需回复）/ `reply_content` 三字段独立语义；Feature B 走 `should_reply` 路径，经 `DualStreamSession.ensure_reply()` 启动主管线产出真实回复（不 cancel、不置打断标记、不发 interrupted）；空打断（无插话内容）不摧毁在途主管线。
- **停顿续接确认**：`REPLY_CONFIRM_S=0.5` 窗口确认用户确已说完再兜底启动回复，长句内部停顿不会被腰斩。
- **忽略传导**：`REALTIME_VOICE_PROMPT_PADDING` 注入「回应边界（忽略规则）」，主 LLM 对情绪 / 自言自语等非对话输入可选择不回应，对明确提问 / 请求务必回答。
- **VAD 兜底分层开关**：`speech_end_fallback`（默认 false）——true 时 LLM 打断标记 `_agent_interrupt_triggered` 抑制 VAD `speech_end` 兜底（避免双路 TTS 并发）。
- **统计与热更新端点**：`replies_triggered` / `interrupts_triggered` 独立统计；受保护端点 `GET /api/stats/interrupt` 读统计、`POST /api/stats/interrupt/enable` 热更新 `enabled` / `speech_end_fallback`。

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

- 模式：`remote`（统一走 TTS Provider，`qwen3_tts_provider.py`），`get_tts_service()` 单例统一 REST/gateway/main 链路。
- **多运行时路由**：配置段 `qwen3_tts.runtime` 枚举 `voicedesign / cosyvoice / qwen3_base`，当前主 runtime 为 `cosyvoice`（CosyVoice3）。Provider 自动路由——带参考音频（带 refs）走 `cosyvoice`（失败降级 `qwen3_base`）；无参考音频走 `voicedesign`（失败降级 `qwen3_base`）。
- **CosyVoice3 主引擎**：`Fun-CosyVoice3-0.5B-2512`，`docker/llm/cosyvoice_server.py` + `start-cosyvoice.ps1`（独立 conda 环境），OpenAI 兼容 `/v1/audio/speech`，地址 `http://127.0.0.1:8094`，承接克隆与情感合成，支持流式合成 + CUDA graph 加速。
- **VoiceDesign / Qwen3-TTS Base 备用**：`Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign`（8091，无 refs 音频设计）、`Qwen/Qwen3-TTS-12Hz-1.7B-Base`（8093，降级兜底），基于 vLLM-Omni。
- 流式合成：`synthesize_stream_fine` 直接对接 token 流，边收边切边合成，每个 `text_segment` 对应一个 TTS chunk；`cross_fade_duration=0.15` 平滑过渡。
- 情感指令：`emotion_instruction_enabled`，由 LLM 生成自然语言指令（`tts_instruction`，与 `reply_text` 分离），经 `emotion_instruction_service.py` 解析与中性回退；`[emotion:*]` 标签仅作迁移边界兼容输入。
- 参考音频资产：统一 `ref_audio_store.py` 管理（`source=prompt` 按提示词生成 / `source=file` 外部文件双来源），当前资产默认使用、合成请求可覆盖。
- 音效标签：`effects_enabled`，文本中插入标签触发音效。
- 过渡词：`transition_enabled`，在开播前插入过渡词（`transition_text="嗯，"`），衔接自然。

### 4.8 VAD 语音活动检测（`vad_processor.py`）

- 三种模式：`ENERGY`（能量阈值）/ `WEBRTC`（轻量高效，默认）/ `SILERO`（神经网络，最准确）。
- 双流式下 VAD 仅作兜底，不阻塞 ASR Partial 驱动的主流程。
- `min_silence_duration_ms=150` 判定句尾，加速兜底修正约 350ms。

### 4.9 弹幕防火墙（`firewall.py`）

- **防火墙**：三档过滤不当弹幕/内容，保障直播与对话安全。

### 4.10 实时性能预算与实测基线

代码注释中标注的实测目标：vLLM 推理约 **90 tokens/s**、TTFT 约 **80ms**、Prompt Tokens < 500 锁死 80ms TTFT。优化演进目标：C4 `P50<600ms` → `P50<400ms`。各环节延迟预算：

| 环节 | 手段 | 预算 |
|------|------|------|
| Prefill | 精简 Prompt（省 ~1500 token） | 100-200ms |
| 推理 | vLLM 流式 + 短回复限长 | TTFT ~80ms |
| 平滑 | TextSmoother 30ms 窗口 | ~40ms |
| 合成/传输 | TTS 4 字切片 + 流式推送 | 首包 <300ms 总预算 |

**全链路 WS 实测基线（2026-08-18 最终报告）**：

| 环节 | 实测值 | 说明 |
|------|--------|------|
| ASR 触发（T2/T3） | ~280-330ms | Partial 阈值 0.15s |
| LLM TTFT（预热后） | 50-92ms | 语音前缀预热 + prefix cache 命中 |
| TTS 首块（WS 实测） | 245-270ms | flow-steps=1 + CUDA graph |
| hift decode 中间段 | ~4ms | CUDA graph（67ms→4ms） |
| 全链路 T5 P50 | 449-610ms | 多数轮 <600ms |
| 全链路 T5 P95 | 637-762ms | 6 轮 10/10 全 <800ms |
| RTF（CosyVoice3 克隆） | 0.13-0.15 | 独立测量，<1 达标 |

> 全链路硬性验收：P95<800ms 且连续 6 轮（每轮 10 次）全部 <800ms（spec `optimize-ws-full-link-sub-800ms`）。由此前的 P50~1300ms / P95~1785ms 优化为 P50 469-699ms / P95 637-762ms（改善 46-64%）。

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
  type VARCHAR(20) NOT NULL,          -- long_term / short_term / permanent / dream
  content TEXT NOT NULL,
  vector_id VARCHAR(100),             -- 关联向量库对象
  metadata TEXT,                      -- JSON
  importance INTEGER DEFAULT 3,       -- 1-5 等级
  importance_score FLOAT DEFAULT 0.6, -- 0-1 连续分
  decay_type VARCHAR(20) DEFAULT 'exponential',  -- exponential/ebbinghaus/zero/dream
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
- **Agent 上下文管理器**（`agent_context_manager.py`）：管理每个 Agent 的独立上下文。
- **会话存储**（`core/session/`）：会话持久化。
- **限额**（`ContextLimitsConfig`）：`max_messages=500`、`window_size=50`、`summary_threshold=100`。

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
- **管理器**（`manager.py`）：插件生命周期、心跳检测（`heartbeat_timeout=30`、`check_interval=10`），并支持三种传输（`transport`）：
  - `direct`（默认）：插件自带 HTTP(S) 服务，主服务按 host:port 直连抓取 `/tools`、`/skills`、`/call`。
  - `relay`（前端转接）：后端不直连，把调用投递到 APP 前端通道并等待回报；覆盖"前端作中转代理转发外部插件"与"前端自身承载工具后回报"两义，统一一种传输。`call_tool` relay 分支返回 `RELAY_UNREACHABLE` / `RELAY_TIMEOUT`。
  - `embedded`（后端嵌入式）：工具以 Python Callable 直接登记进后端 `ToolRegistry`，进程内执行，不走网络、无 host/port；handler 缺失返回 `EMBEDDED_HANDLER_MISSING`。
- **技能注册表**（`skill_registry.py`）：维护所有可用技能。
- **存储**（`storage.py`）：插件数据持久化（`data/cxfc_plugins.db`，含 `transport` 列）。
- **后端新增路径**：`POST /cxfc/relay/register`、`GET /cxfc/relay/targets`、`POST /cxfc/relay/result`、`POST /cxfc/embedded`（`server/api/routers/cxfc.py`）。
- 语音工作站启动时向主服务注册并保持心跳。

### 10.1 内嵌 embedded 插件范式（进程内注册）

`embedded` 是 CXFC 的进程内传输范式：工具以 Python `Callable` 直接登记进后端 `ToolRegistry`，
无 HTTP 服务、无 host/port、不走网络。生产装配入口为 `CXFCManager.register_embedded_plugin()`：

- 签名：`register_embedded_plugin(plugin_id, name, tools, handlers, skills, capabilities)`；
- `plugin_id` 归一为 `embedded_{plugin_id}`，`transport=PluginTransport.EMBEDDED`；
- `handlers` 保存到 `_embedded_handlers`，与 `tools` 一并经 `_register_catalog` 写入
  `ToolRegistry`（category=`cxfc`），LLM 工具分发可直接进程内执行；
- 引用示例：`server/autonomy/main.py` 的 `setup_autonomy()`——以 `embedded_cxo-autonomy`
  注册 9 个 `autonomy_*` 工具 + 真实 handler（`get_handlers()`）；`dream.enabled` 时
  额外并入 `dream_get_status / dream_trigger / dream_list` 工具 + `"dream"` 能力（见 §21）；
- `call_tool` embedded 分支缺 handler 时返回稳定错误码 `EMBEDDED_HANDLER_MISSING`。

### 10.2 relay WS 推送通道

`relay` 的"后端 → 前端通道"投递由 WebSocketManager 承载（P2-T2 生产装配）：

- `CXFCManager._build_relay_ws_dispatcher()` 构造基于 `self._ws_manager.broadcast` 的投递回调，
  广播消息 `{type: "cxfc_relay_call", plugin_id, tool, arguments, request_id, token}`；
- `enable_relay_ws_dispatch()` 在 `server/main.py` `_init_cxfc` 装配处调用，装配后已注册及后续
  relay 插件自动获得真实 WS dispatcher；未装配时保持"显式 `register_relay_dispatcher`"语义
  （单测可注入替身）；
- 无活跃连接 / 广播异常 → 返回 `False` → `call_tool` 保持 `RELAY_UNREACHABLE`；
  投递后无人回报 → `RELAY_TIMEOUT`；全程不发起 host:port 直连，与 direct 路径隔离；
- 前端侧：`useWebSocket.ts` 消息路由 `cxfc_relay_call` 分支 → `src/hooks/ws/cxfcRelay.ts`
  `handleCxfcRelayCall()` 执行工具并回报 `POST /api/cxfc/relay/result {request_id, plugin_id, success, result/error}`。

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

## 14. 前端（APP-Frontend）

> React + TypeScript + Vite + Electron，管理界面路由见 `src/pages/management/routes.tsx`（HashRouter 管理窗）。
> 支持两种形态：浏览器模式（`npm run dev:browser`，端口 3100）与 Electron 桌面模式（`npm run dev`）。

### 14.1 管理界面路由

| 路径 | 功能 |
|------|------|
| `/chat` | 聊天（含 Markdown / 工具调用 / 提醒通知） |
| `/dashboard` | 仪表盘 |
| `/memories` | 记忆管理（批量操作 / 卡片·列表视图） |
| `/archive` | 归档 |
| `/agents` | Agent 管理（新建人设、配置参数） |
| `/acp` | ACP 多 Agent 协作 |
| `/plugins`、`/tools` | 插件 / 工具 |
| `/audio-workstation` | 录音作曲（五线谱 / 作曲 / SVC / VoxCPM / 数据集） |
| `/settings` | 设置 |
| `/memory-agent`、`/vector` | 记忆 Agent / 向量数据 |
| `/dream` | 梦境日志（含生理信号区块，见 §21/§22） |
| `/live-console`、`/live-overlay` | 直播控制台 / 直播分屏 |
| `/avatar-source`、`/danmaku-source`、`/subtitle-source`、`/audio-source` | OBS 四类浏览器源 |
| `/pet`、`/danmaku` | 桌面宠物 / 弹幕独立窗 |

### 14.2 语音管线（`src/hooks/`）

- `useAudioStream`：双流式语音会话（init / audio / end），管理音频采集与播放。
- `useMicrophone`：麦克风采集。
- `useAudioAnalyzer`：音频能量分析（驱动口型/表情）。
- `useWebSocket` / `useLiveWebSocket` / `ws/transport`：连接管理。

### 14.3 虚拟形象

- **Live2D**：`live2dEngine` 加载 `.model3.json`，表情、口型（`Live2DLipSync`）、动作（`Live2DMotion`）、音频分析；`live2dDriver` 统一接入（Live2D 无骨骼）。
- **VRM**（`src/avatar/vrm/`）：`vrmEngine` 加载 `.vrm`，渲染循环按 **L0 物理 → L1 程序化 → L2 LLM 指令 → L3 平滑** 四层组织：
  - **L0 物理**：`VRMSpringBone` 弹簧骨物理（兼容 three-vrm 3.x 的 `_joints` 字段）、`VRMWindField` 风场 + `triggerInteractionWind` 交互风力（峰值保持 + 0.95 逐帧衰减 + reset 清零）。
  - **L1 程序化待机**：`vrmAnimation` 呼吸 / 眨眼 / 摇摆 / 微表情（呼吸仅胸腔深度方向）；持续低帧（<30 & 2s）经 `vrmPerformanceMonitor` 触发 `setEnabled(false)` 关闭程序化待机 + `springBoneEveryOtherFrame` 降级，>50 & 2s 自动恢复（防抖动）。
  - **L2 LLM 指令**：`tagParser` 解析 `[emotion:]/[blend:]/[bone:]/[wind:]/[pose:]/[action:]/[sleep:]` → `applyTags` 分发；`[action:]` 经 `vrmActionController` 的 `AnimationMixer` 交叉淡入模型内嵌动画片段，无内嵌片段回退程序化动作。
  - **L3 平滑**：`vrmBlendShapeInterpolator` 对 `[blend:]` 权重做 Target/Current 分离 + Lerp 插值 + `fadeOutUnusedExpressions`，消除瞬时写入的抽搐感。
  - **骨骼控制白名单**：`boneControlCatalog`（`DEFAULT_BONE_CONTROLS` 26 骨 + `isControlledBone` / `getBoneRange`）——`setBoneRotations` 过滤白名单外骨骼、受控骨骼按各轴 `rotationRange` 限幅，防生成不存在骨骼或极端旋转；白名单真相源在 `manifest.ts`。
  - **骨骼动作保持时长**：`[bone:]` 第 6 参 `holdMs`（默认 3000ms）到期自动平滑归中，`holdMs=0` 保持不归中（`boneHoldTimers` 逐帧递减）。
  - **视线策略**：`vrmLookAtStrategy` — `MouseFollowStrategy`（桌宠鼠标跟随）/ `LiveCameraStrategy`（直播含读弹幕态 + Perlin 游离），`sceneMode` 由 `PetAvatar` / `LiveOverlayPage` 传入。
  - **表情键容错**：`vrmExpression` 大小写不敏感解析，兼容任意第三方 VRM。
  - **模型自选**：默认打包 `CX-OPEN.vrm`（不开源模型不打包），设置页经 Electron 系统对话框 / 浏览器 file input 选本地 `.vrm`，`vrmModelSource` 解析 + blob revoke。
- **音画同步**：`labelTimeline` 把标签序列与「含标签原文」建字符偏移 ↔ 触发点映射；`useWebSocket.onTextProgress` 每收一个流式 TTS chunk（`text_segment` 锚点）累加上游标，`PetChat.advanceTimeline` 随朗读逐步触发当前段标签，`flushRemaining` 收尾兜底——不再整句收尾一次性触发。
- **avatar 标签驱动（与语音解耦）**：`config/hidden_prompt.yaml` 的 `avatar_prompts` 承载「方括号视觉标签（形象表现）+ `<tts_instruction>`（语音情感）」双轨指引；`prompt_builder` 向主模型注入，管理端 ChatPage `stripAvatarTags` 剥离标签正文。
- 统一由 `AvatarDriver` 抽象层（`vrmDriver` / `live2dDriver`）驱动，模型无关。`VRMDriver` 暴露到 `window.__cxoDriver` 便于运行时调试。

### 14.4 UI 与动画

- 扁平化设计 + Apple Liquid Glass 玻璃拟态效果（`lib/glass/`，WebGL shader）。
- 二次元视觉元素（`components/anime/`）：花瓣、星轨、粒子、光晕等动效。
- 动画系统（`lib/motion/`）：GSAP 时间线、弹簧、贝塞尔曲线、橡皮筋滚动。
- 响应式（`lib/responsive/`）：断点、移动端降级。
- 主题（`lib/theme/`）：亮暗主题、跨淡入淡出。

---

## 15. 语音工作站（CX-O-VoiceWorkStation）

> Python / FastAPI，端口 8200，提供声音克隆与训练、AI 作曲能力。

### 15.1 数据集生成

- `voxcpm` / `batch-dataset`：基于 VoxCPM 的批量 SVC 训练数据集生成（单条参考音频生成已随 Qwen3 TTS 迁移移除）。

### 15.2 SVC 训练与推理

- `sovits_svc_trainer` / `sovits_svc_infer`：So-VITS-SVC 训练与推理。
- `dataset_builder`：数据集构建。
- 训练在子进程中运行，服务关闭时自动停止并释放 GPU。

### 15.3 AI 作曲与歌声合成

- `music/`：歌谱（score）、自动编排（arranger）、多轨伴奏（accompaniment）、混音（mixer）、MusicXML 导入。
- `song_pipeline` / `singing_engine`：歌声合成。
- 支持 VoxCPM / 参考音频 / 歌声合成引擎等多种音源。

### 15.4 CXFC 集成

- 启动时注册为 CXFC 插件并保持心跳，通过 `/tools`、`/skills`、`/call` 暴露能力给主服务。

---

## 16. Docker 推理服务

`docker-compose.yml` 编排 GPU 推理服务，构成语音/LLM 推理层：

| 服务 | 说明 |
|------|------|
| `asr-sensevoice` | FunASR + SenseVoice 语音识别，端口 8005 |
| `llm` | 对话大模型（vLLM + GGUF 或 TRT-LLM），端口 8080 |

> Docker Compose 现仅编排 ASR 与 LLM 推理服务；TTS 语音合成走独立服务（CosyVoice3 8094 / VoiceDesign 8091 / Qwen3-TTS Base 8093，见 §4.7），不在此编排内。

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
| `tts` | mode `remote`、cross_fade `0.15`、emotion/effects 开 |
| `qwen3_tts` | runtime `cosyvoice`（枚举 voicedesign/cosyvoice/qwen3_base）；cosyvoice `http://127.0.0.1:8094` / `Fun-CosyVoice3-0.5B-2512`；voicedesign `8091` / `Qwen3-TTS-12Hz-1.7B-VoiceDesign`；qwen3_base `8093` / `Qwen3-TTS-12Hz-1.7B-Base` |
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

### 17.3 配置热更新

部分配置节保存后**无需重启后端**即时生效（`server/config_hot_reload.py`）：

- `ModelRouter.reload_clients()` 按当前配置重建 main / summary / memory 三个 LLM 客户端，provider / model / host 变更即时生效；`apply_section()` 分发到对应运行时组件；`broadcast_config_changed()` 经 WebSocket 广播给前端。
- `update_unified_config` 保存后按节返回 `applied` / `requires_restart`。可热更新节：`llm` / `audio` / `live` / `system`；需重启节：`vector`。
- 前端 `configEvents.ts`（事件总线）+ `useConfigReload.ts`（WS 订阅）+ `ConfigToast.tsx`（通知）挂载于管理界面，收到 `config_changed` 事件后刷新 limits 并即时刷新 LLM / 向量区块；需重启节以 toast 提示。

---

## 18. 主动视觉与电脑控制

### 18.1 主动视觉（Active Vision）

桌宠 / 管理界面可采集屏幕或摄像头画面，周期性把帧经 `/api/chat/stream` 随聊天请求上行给 LLM，让 AI「看见」屏幕内容并据此回应。

- **采集状态**：`captureStore` 维护 `screenActive` / `cameraActive`（会话内采集开关）与 `frameMode` / `frameIntervalSec`（节奏偏好，持久化）。
- **总开关**：持久化 `visionEnabled`（默认 false）一键关闭画面上行；关闭时定时抽帧与手动点发均不发送（`useFrameSender` 注入闸门）。
- **帧节流**：`frameThrottle` 控制发送频率，避免高频上行占用带宽与算力。
- 依赖具备视觉能力的多模态 LLM 才能理解画面。
- **视频叙事管线**：事件驱动回溯打包的片段经 `POST /api/vision/clip` 入独立异步队列（`server/core/vision/clip_queue.py`），由 `VideoUnderstanding` 消费、`NarrativeVisionMemory` 沉淀为 `source='vision'` 记忆。
- **护栏（单进程边界）**：路由侧小时限流（`_RATE_WINDOW`）与同类事件冷却（`_COOLDOWN_STAMP`）为**进程内内存态**，与整条视觉链路（`vision_clip_queue` 内存队列、消费者）及整服务单进程架构一致。服务以单 worker 运行（`server.main:main` / `api_server.py` 均不传 `workers`）；**勿用 `uvicorn --workers N` 多进程启动**，否则限流放大 N 倍、冷却失效、片段分散各进程互不消费。

### 18.2 电脑控制（CXFC Computer Control）

桌宠（Electron）以 CXFC 插件形式向后端注册本机控制能力，让 AI 能操作你的电脑——需在悬浮窗显式授权。

- **能力**：屏幕控制、键盘控制、运行指令三个工具，经 CXFC 注册为技能由 LLM 调用。
- **安全**：
  - HTTPS 自签名证书 + 首次指纹信任（TLS）；
  - 注册时签发令牌，后端转发 `/call` 时携带 `Authorization` + 唯一 `request_id` 防重放；
  - 运行指令保留结构化参数 / 超时 / 进程树回收 / 输出截断 / 脱敏护栏。
- **授权**：悬浮窗「授权控制」按钮——永久授权、主动撤销（撤销即关闭）、重启恢复。
- **启动设置**：桌宠自启动、管理员权限启动（Windows UAC）。
- 浏览器模式降级不可用（不调用 Electron 专属 API）。
- 契约：`public/schema/computer_control_plugin.schema.json`、`computer_control_error_codes.json`、`public/interface_stub/computer_control.pyi`。

---

## 19. 自我进化服务（CXO-Tuner）

> 位于 `CXO-Tuner/`，可选独立服务，提供"自我进化"能力——LLM 从自然对话中自动回收反馈、自动评判、自动微调，让 AI 越用越懂用户偏好。默认端口 **8300**。

> 说明：本节为工程视角的能力范围说明。该服务**可选**，默认随 docker-compose 主配置不启用（`profiles: ["tuner"]`），不启动时对主系统零侵入。

### 19.1 独立服务定位

- 独立 FastAPI 应用（`tuner/main.py` 应用工厂 + lifespan 初始化），端口 `8300`，与 CX-O-SERVER 主服务解耦，可按需启停。
- 通过 `CXO-Tuner/start-cxo-tuner.ps1` 启动脚本单独拉起。
- 配置：`tuner/config.py` 对齐 `public/schema/cxo_tuner_config.schema.json`，`load_config()` 从 `CXO_TUNER_CONFIG`（JSON 环境变量）读取并自动补齐缺失字段（auto_fill）。
- 集成：进化产物作为 LoRA adapter 供主系统 vLLM **动态 LoRA** 加载（`vllm_url` / `vllm_lora_enabled` 契约打通）；前端"进化实验室"连接其 API 做数据集 / 训练任务 / 进度可视化。

### 19.2 架构四层模块

| 层 | 模块 | 职责 |
|----|------|------|
| 数据采集 | `core/collector/`（`dataset.py` + `cleaner.py`） | 回收对话、清洗、按角色卡锚点切分数据集，校验 `min_dataset_size` 阈值 |
| 评判 / 偏好 | `core/judge/`（`judge_engine.py` + `dpo_builder.py`） | judge 模型打分 + 基于收集数据构造 DPO 偏好对（`anchor_ratio` 控制锚点占比） |
| 训练 | `core/trainer/`（`qlora_trainer.py` / `train_job.py` / `anchors.py` / `store.py`） | QLoRA + vLLM LoRA 兼容适配，`apply_resource_caps()` 依 config 设置 `CUDA_VISIBLE_DEVICES` 与显存上限；任务状态与 adapter 落盘 |
| Adapter 管理 | `core/adapter_store/store.py` | 管理训练产物 adapter |

### 19.3 关键机制

- **自动数据回收**（无人工标注）：对话数据自动回收并沉淀为 **DPO 偏好对**，彻底移除对人类显式反馈标注的依赖。
- **自动评判（judge）**：judge 模型对回放打分，为偏好构造提供好坏依据。
- **在线 DPO 探索**：跟随互动节奏边用边学，在线采集-优化闭环；`dpo_builder` 依 `anchor_ratio` 平衡锚点样本与真实交互数据。
- **闲时调度**：`scheduler` 以 `idle_start` / `idle_end` 窗口在空闲期自动触发训练，避免抢占对话主链路。
- **QLoRA 微调 + vLLM LoRA**：训练产物为 LoRA adapter，主系统 vLLM 动态加载，训练完成实时可用。
- **资源占位控制**：`CUDA_VISIBLE_DEVICES` 空值默认 CPU，注入 GPU 编号即 GPU 加速；`max_memory_fraction` 兜底防 OOM。

### 19.4 部署

```text
# 仅启用 tuner profile 时才会启动 cxo-tuner 容器
docker compose --profile tuner up
```

- 对应 `docker-compose.yml` 服务 `cxo-tuner`，`profiles: ["tuner"]`，GPU `count:1` reservation；
- 数据 / 模型 / 角色卡目录卷挂载；`CXO_TUNER_PORT` 控制端口；
- 默认 `docker compose up -d` 不含 cxo-tuner（可选性校验通过），不启用时主系统零受影响。

---

## 20. CX-O-Autonomy 自主系统

> 位于 `server/autonomy/`，CX-O-Autonomy 是 CX-O 的"自主生命"能力：Agent 在用户离开期间
> 自主感知、动机、规划、行动、审计与反思，沉淀经历并写日记，用户回来后经聊天召回。
> 以 **embedded CXFC 插件**（`plugin_id=embedded_cxo-autonomy`）装配进主服务进程（spec
> `add-cxo-autonomy-embedded`），`config.autonomy.enabled=false` 时整体跳过装配，零影响。

### 20.1 架构五层

| 层 | 模块 | 职责 |
|----|------|------|
| 感知 | `perception/`（`rss_fetcher` / `hotspot_monitor` / `context_sensor`） | RSS 新闻、社交热点、环境感知 |
| 动机 | `core/motivation/state.py`（`MotivationState`） | 四维动机驱动 |
| 规划 | `core/planner/action_planner.py`（`ActionPlanner`） | LLM 规划 + 记忆注入 + 动作白名单 |
| 行动 | `action/`（`memory_actions` / `poster` / `streamer`） | 记忆写入、发帖、半自动直播 |
| 反思 | `reflection/`（`diary/generator` / `feedback/evaluator` / `consolidator`） | 每日日记、反馈评估、经历整合 |

调度：`core/scheduler/circadian.py`（`CircadianScheduler`，wake/sleep/golden/diary/quiet_windows）。
主循环：`core/loop/autonomy_engine.py`（`AutonomyEngine`，感知→动机→规划→行动→审计→反思，
节拍 `loop_interval_minutes`）。

### 20.2 动机引擎与规划器

- **动机**：`MotivationState` 维护四维动机（curiosity / social_need / creative_drive / fatigue），
  随活动/休息动态更新，驱动自主行为的选择。
- **规划器**：`ActionPlanner` 以主模型 LLM（`model_router.get_client("main")`）按人设 persona 规划
  下一步动作；记忆注入 provider 检索最近相关记忆供规划上下文；`permissions.allowed_actions` /
  `blocked_actions` 白名单约束动作空间（9 项动作枚举：sleep/wait/read_news/search/write_memory/
  write_post/start_live/stop_live/write_diary）。

### 20.3 预算、审计与安全

- **预算** `safety/budget/token_ledger.py`（`TokenLedger`）：日 token 上限 / 日 LLM 调用上限 /
  成本告警阈值 / 超支模式（`overspend_mode`：sleep / low_cost），状态持久化于
  `server/autonomy/data/token_ledger.json`。
- **审计** `safety/audit.py`（`AuditStore`）：每次行动写审计日志（`audit_logs.jsonl`），
  供前端行为回放与用户追溯。
- **安全**：`safety/gate/content_gate.py`（`ContentGate`，对接防火墙，内容闸门）；
  `safety/ratelimit/limiter.py`（`RateLimiter`，发帖限速 `post_rate_per_hour`）；
  `safety/killswitch.py`（`KillSwitch`，紧急停止持久化）。
- **离开模式**：`safety.leave_mode_authorize=True` 时用户离开直接授权自主行动，无需逐次确认；
  `user_online_sleep` 控制用户在线时是否休眠。

### 20.4 行动能力与外部依赖

- **发帖** `action/social/poster.py`：平台白名单 → LLM 生成 → 内容闸门 → 限速 → 经电脑控制
  浏览器自动化发布（`_build_computer_control` 从已注册插件识别电脑控制插件并构造调用器）；
  电脑控制插件未注册时返回 prepared 未执行态。
- **直播** `action/live/streamer.py`：半自动直播——生成脚本 → 确认门 → OBS 开播 → 下播写回忆。
- **日记与整合** `reflection/diary/generator.py`（第一人称日记写 permanent 记忆）、
  `reflection/consolidator.py`（经历整合，注入真实蒸馏服务 provider）。
- **搜索**：`search.mcp_server_name="free-search-mcp"`——`_build_mcp_search_provider` 从
  ToolRegistry 定位 category=mcp 且工具名含 "search" 的工具（free-search-mcp 的 web_search）
  调用并归一化为 `[{title, link, snippet}]`；不可用/无结果时 `HotspotMonitor` 降级 RSS。
  **free-search-mcp 已落地（2026-08-22）**：克隆至 `third_party/free-search-mcp`（venv 安装
  0.9.2），`cxo_search_adapter.py` 把标准 MCP 服务包装为 CX-O 简化 HTTP 协议（GET /health+/tools、
  POST /call，直接调 `search_mcp.aggregator.aggregate_search`），注册于 `CX-O-SERVER/config.json`
  `mcp_servers`（端口 8720），主服务启动时经 `start_configured_servers` 自动拉起；真实多引擎搜索
  全链路已运行时验证通过。

### 20.5 装配、REST 与前端控制页

- **装配**：`server/main.py` 在 `cxfc_manager` 就绪后 `_init_autonomy()` → `setup_autonomy(services)`
  （`server/autonomy/main.py`），注册 embedded 插件、注入路由单例并 `engine.start()`；任何异常被
  捕获隔离，不影响主服务启动。
- **REST** `server/api/routers/autonomy.py`（挂载 `/api`）：
  `GET /autonomy/status`（未启用返回 `{"status":"disabled"}` 不抛错）、
  `POST /autonomy/control`（enable/disable/pause/resume/emergency_stop）、
  `GET /autonomy/audit`（分页）、`GET|PUT /autonomy/config`（深度合并 + model_validate 校验，
  非法字段/枚举/时间格式返回 422）。
- **前端控制页**：管理窗路由 `/autonomy` → `AutonomyPage`（"Agent 生活"）：状态徽章（
  running/paused/sleeping/budget_limited/error/disabled）、四维动机进度条、日预算用量、
  控制区（启用/禁用/暂停/恢复/紧急停止/自动启动）、行为回放（审计列表分页加载）。
  前端降级口径：后端离线全页错误态；未启用展示"未启用"徽章；config/audit 独立容错。

> 自主生命的「睡眠窗口」由梦境引擎承接（§21），其入睡 / 唤醒依据来自生理信号接入（§22）。

---

## 21. 梦境引擎（Dream）

> 位于 `server/autonomy/dream/`（engine / collector / generator / filter / buffer / consolidator /
> purge / config），梦境引擎是 CX-O-Autonomy「自主生命」的睡眠态能力：Agent 在睡眠窗口内把
> 日内经历经「采集 → 生成 → 过滤 → 整合 → 清理」管线固化为梦境记忆，用户可经前端梦境日志
> 查看、确认或拒绝。以 embedded cxo-autonomy 插件装配（`dream.enabled=false` 默认，未启用
> 零装配零影响）。

### 21.1 架构与组件

| 组件 | 模块 | 职责 |
|------|------|------|
| 引擎 | `engine/` | 梦境引擎主流程（DreamEngine） |
| 采集 | `collector/` | 收集日内经历 / 记忆素材 |
| 生成 | `generator/` | LLM 生成梦境内容 |
| 过滤 | `filter/` | 梦境内容过滤（安全红线） |
| 缓冲 | `buffer/` | 梦境生成 / 呈现缓冲 |
| 整合 | `consolidator/` | 梦境记忆整合沉淀 |
| 清理 | `purge/` | 过期梦境清理（PurgeJob） |
| 配置 | `config` | `server/autonomy/data/dream_config.json` |

装配：`server/autonomy/main.py` `setup_autonomy()`——`dream.enabled` 时追加
`dream_get_status` / `dream_trigger` / `dream_list` 工具 + `"dream"` 能力（见 §10.1）。

### 21.2 记忆侧集成

- `_DreamMixin` 为 `MemoryManager` 第 10 个 Mixin（`server/core/memory/mixins/dream_mixin.py`），
  提供梦境记忆 CRUD + 会话回滚。
- 新增 `decay_type='dream'`：pending / surfaced λ=0.8、confirmed λ=0.25；`type='dream'`
  记忆枚举（见 §5.1 memories 表 schema 注释）。
- `MemoryRouter` 默认排除梦境记忆，仅 `dream_recall` / 触发词放行 confirmed 梦境。
- `D7_DREAM_FILTER` 登记进 `DecisionCore.DECISION_POINTS`（仅枚举登记，不参与决策路由）。

### 21.3 REST 与 WS

- **REST** `/api/dream/*`：`status` / `trigger` / `list` / `confirm` / `reject` /
  session 回滚 / `purge` / `config`。
- **WS** `DreamActions`：`dream.session_started` / `dream.session_completed` / `dream.surface` /
  `dream.confirm` / `dream.reject` / `dream.purged`。

### 21.4 前端

- 管理窗路由 `/dream` → DreamPage「梦境日志」（含生理信号区块，见 §22）；
  聊天页展示 `dream.surface` 气泡。

### 21.5 安全红线

1. `is_ground_truth` 恒为 `false`（梦境非真实经历，不污染事实记忆）。
2. `permanent=FALSE` 断言（梦境禁止永久化）。
3. `dream_session_id` 强制（每次梦境会话唯一标识）。
4. `decay_type='dream'` + PurgeJob（按梦境衰减策略清理过期梦境）。
5. `purge_dream_session` 会话回滚（清理动作可回退）。

### 21.6 配置

- `dream.enabled=false` 默认（`server/autonomy/data/dream_config.json`）；未启用时跳过
  工具 / 能力装配与 REST / WS 挂载，对主系统零影响。

---

## 22. 生理信号接入（Physio）

> 位于 `server/autonomy/dream/physio/`（`estimator` / `store` / `runtime`）+ `sleep_sensor.py`
> （S1-S9 融合状态机 AWAKE / DROWSY / ASLEEP / AWAY），为梦境引擎提供入睡 / 唤醒依据。
> 默认关闭（`dream.physio.enabled=false`），physio 缺席对现有链路零回归。

### 22.1 采集链路（前端 Electron 主进程）

- 采集走 Electron 主进程 **noble**（`APP-Frontend/electron/ble/ble_collector.ts`），
  BLE IPC 5 通道；HR 上送 `POST /api/physio/hr`。

### 22.2 后端组件

- `HeartRateSleepEstimator`（`estimator`）：滑动窗口 / `base_hr` 自学习 / `hr_sleep_confidence`
  睡眠置信度估计。
- `store` / `runtime`：生理数据存储与运行时管理。
- `SleepSensor` 融合状态机（S1-S9）：
  - 权重：S9 心率=0.40（顶级）、S4 显式睡眠语=1.0（短路）、S3 / S5 / S8 无源 weight 0。
- DreamEngine 入睡触发升级：窗口内 ASLEEP 确认 + S4 窗口外提前触发；physio 缺席零回归。

### 22.3 REST

- `/api/physio/*`：`hr` / `state` / `status` / `sleep` / `devices` / `forget` / `config` / `clear`。

### 22.4 隐私 R6

1. 原始 HR 不落盘、不入记忆 / LLM。
2. 默认关闭（`dream.physio.enabled=false`），需显式开启。
3. 配对授权、一键清除。

### 22.5 已知未闭合

- noble 真机验证（无硬件）。
- S2 / S3 / S5 / S8 无源待接线。

---

## 23. 管理面（CX-A）与哨兵集群（多机互备）

> 位于 `server/core/admin/`（管理面）+ `server/core/cluster/`（哨兵集群）+
> `server/api/routers/{admin,cluster}.py` + `server/protocol/actions.py`。
> 两者默认关闭（`admin.enabled=false` / `cluster.enabled=false`，空 `cluster_secret` 视为集群不启用），
> 关闭时零侵入，不影响单机运行。

### 23.1 角色与关系

- **CX-O 节点**：单个运行在某机器上的实例（持久化 `data/cluster/node_identity.json` 的 `node_id`）。
- **哨兵集群**：多个 CX-O 组成的对等互备网络，互为灵魂备份。
- **CX-A**：站在其上的管理 Agent，经管理接口纵向管单节点 / 整个集群（经 `ClusterAdminBridge`）。

### 23.2 管理面（Part A，`server/core/admin/`）

- `auth.py`：多级 token（readonly / operator / superadmin）+ `request_id` 防重放（TTL）+ 限流；审计落 `data/admin_audit.jsonl`（对齐 `AuditStore`）。
- `manifest.py`：`GET /api/admin/manifest` 运行时动态自描述（能力 / 动作 / agents / models / **cluster 块**：node_id/role/epoch/peers）。
- `control_plane.py`：`POST /api/admin/control` 统一分发到 autonomy / voice / live / config / agent / tuner / instance / **cluster** 域；`request_id` 幂等、未知动作 400。
- `batch.py`：`POST /api/admin/batch` sequential / parallel 编排。
- `registry.py`：CX-A 多实例注册 / 心跳 / 发现。
- `cluster_bridge.py`：把哨兵集群能力暴露给管理面；只读直接聚合，写操作需 superadmin + 审计；集群未启用统一返回 `{"status":"cluster_disabled"}`。

### 23.3 哨兵集群（Part B，`server/core/cluster/`）

- `identity.py`：`node_id` 首次生成后持久化不变（接管时靠它识别"这是谁的副本"）。
- `discovery.py`：默认种子列表主动握手 + `cluster_secret` HMAC 信任校验；UDP 广播可选。
- `transport.py`：节点间 TLS/HTTPS + 共享密钥 + `request_id`/`seq` 防重放 + 失败入待发队列（`data/cluster/pending/`）。
- `heartbeat.py`：每 `peer_heartbeat_interval_sec` 向每个 peer 发心跳；超时 + 连续 miss → suspect → **多数派确认** → dead（对齐 CXFC 心跳范式）。
- `replicator.py` + `units.py`：**增量事件流 + 定期快照双轨制**；`vector` **不跨机同步**（接收端本地重建）；按单调 `seq` 幂等重放、`last_applied_seq` 断线补传；异步推送不阻塞主链路。
- `failover.py`：接管流程 candidate → 仲裁 → **继承遗产**（B 保持自身 identity、记录 `inherited_from`，不改 node_id）→ active；仲裁失败恢复 standby 且**不消耗 epoch**（仅在成功后递增）。
- `consensus.py`：epoch 防双主 + 多数派 + **见证节点（tiebreaker）**；`state_version` 过旧抛 `ClusterDirtyTakeoverError`（严格红线：宁缺毋滥）。

### 23.4 关键决策（已冻结）

| 决策 | 落地 |
|------|------|
| 接管后身份 | B 保持自身身份、继承 A 记忆为遗产（`inherited_from`） |
| 2 节点脑裂 | 无法形成多数派时由见证节点（tiebreaker）仲裁；无见证则拒绝升级并告警 |
| 脏接管 | 数据不完整 / 过旧拒绝接管，严格红线 |
| 一致性 | 异步最终一致，守护主链路 <300ms；接管时接受丢失最近少量变更 |
| 传输安全 | 灵魂数据只在受信节点间经 TLS 流动，绝不经第三方 / 云端 |

### 23.5 生命周期与前端

- `main.py` lifespan：先 `_init_cluster()` 后 `_init_admin()`（`ClusterAdminBridge` 依赖 `SentinelCluster`）；关闭逆序（`replicator.flush` → `heartbeat.stop` 主动下线）；任一异常被捕获隔离，绝不影响主服务启动。
- WS：`protocol/actions.py` 新增 `admin.*` / `cluster.*` action；集群事件经 `/ws` events 域广播（`cluster.node_joined` / `failover_*` / `sync_lag_alert` / `split_brain_risk`）。
- 前端：`src/lib/backendFailover.ts` + `src/hooks/useBackendFailover.ts`——主后端断连时自动探测候选对等（cluster peers + 局域网发现 + 本地缓存），优先选 `role=active` 的健康节点，`setBackendUrl`+`setWsUrl` 后重载当前窗；带冷却（`SWITCH_COOLDOWN_MS`）防 A/B 震荡。挂载于 `App.tsx` 根部，覆盖桌宠 / 管理界面 / 弹幕窗。

### 23.6 已知未闭合

- 真机双机集群联调（心跳 / 同步 / 接管当前为 mock 单测覆盖）。
- 备份单元数据源为骨架级适配（session / graph / autonomy 真实增量需强化）。
- 管理面对外需显式配置 TLS（默认仅本机 `bind=127.0.0.1`）。

---

## 附录：目录速览

```
CX-O/
├── APP-Frontend/           # 前端（浏览器 :3100 / Electron 桌宠）
├── CX-O-SERVER/            # 后端服务（FastAPI + WebSocket 单体）
│   └── server/
│       ├── api/            # REST 路由
│       ├── gateway/        # WebSocket 网关
│       ├── handlers/       # WS 消息处理器（chat/audio/tools/...）
│       ├── services/       # 语音服务（asr/tts/vad/interrupt/...）
│       ├── core/           # 领域核心（memory/graph/tools/acp/admin/cluster/...）
│       │   ├── admin/      # 管理面（auth/manifest/control_plane/batch/registry/cluster_bridge）
│       │   └── cluster/    # 哨兵集群（identity/discovery/transport/heartbeat/replicator/failover/consensus/manager）
│       ├── protocol/       # 消息协议（action）
├── CX-O-VoiceWorkStation/  # 语音工作站（声音克隆/训练/作曲）
├── docker/                 # 推理服务 Dockerfile
├── docs/                   # 项目文档
├── models/                 # 本地模型
├── config/                 # 全局配置
└── public/                 # 公共契约资源
```