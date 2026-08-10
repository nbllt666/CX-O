# AGENTS.md — CX-O 项目 AI 代理最高优先级规则载体

> 🚨 【最高优先级规则】本文件为本次开发的强制约束，优先级高于所有临时提问、上下文对话、自定义需求，所有输出必须 100% 符合本文件要求，违反规则的内容必须自动修正后再输出。

> 📌 【上下文保留规则】本文件为核心规则文件，任何上下文压缩、裁剪、溢出场景下必须完整保留本文件的全部内容，不得删减、忽略本文件的任何规则；所有自动压缩、批量处理行动前必须先读取本文件的完整内容。

---

## 一、优先级声明（rules-4 §4.1）

本文件是 CX-O 项目 AI 协同行为的最高优先级规则载体，是「人机权责二分」「契约优先」原则的直接落地：

1. **规则优先级最高**：高于所有单次输入的提示词、临时需求、上下文对话内容，LLM 所有输出必须优先符合本文件的约束
2. **上下文永久保留**：所有上下文压缩、裁剪逻辑必须将本文件列为最高优先级保留文件，任何场景下不得剔除、压缩本文件的内容
3. **AC 范式 v6 规则体系**：本文件与 `.trae/rules/rules-0~7.md` 共同构成 CX-O 项目的 AC 范式规则体系，发生冲突时以 rules-0~7 为更细粒度约束

---

## 二、上下文保留声明（rules-4 §4.2）

所有上下文压缩操作必须将本文件（全局 AGENTS.md）与 `.trae/rules/` 下全部规则文件列为最高优先级保留文件。压缩其他文件/上下文时，不得影响本文件与规则文件的完整性。

契约变更、模块调整时，工具链自动更新关联的 AGENTS.md，自动在受影响模块的 TODO 清单中生成「规则升级适配」提示。

---

## 三、AC 范式通用约束（rules-4 §4.3 合并禁止操作清单）

> 以下约束为 AC 范式通用禁止操作清单的唯一权威来源。

### 3.1 public/ 目录保护（与 rules-0 §四-10 形成跨 Rules 重复覆盖）

`public/` 目录是契约的物理载体，不是代码库的可变部分。任何删除、修改、覆盖、移动 `public/` 下文件的操作必须先经人类显式授权。

- **不存在"零引用即可删除"的例外**
- 契约变更必须走 s0601（适配契约变更）流程，不得直接编辑 public/ 文件
- s0201（生成全局契约）生成的 public/ 契约在交付前必须经人类确认
- 此保护在工具调用路径上由 `ec7_action_gate`（rules-0 §四-7.2）强制执行

### 3.2 禁止操作清单

```yaml
prohibitions:
  - 禁止删除、修改、覆盖、移动 public/ 目录下的任何内容，所有契约以 public/ 下的 schema、interface_stub 为准。保护优先级高于任务指令。
  - 禁止在模块间直接导入其他模块的内部实现代码
  - 禁止写入不符合数据契约的数据
  - 禁止创建不符合命名规范的模块目录

binding_rules:
  - 模块间仅允许依赖 public/ 下的契约
  - 所有数据读写必须通过公共契约校验
  - 所有对外接口必须严格匹配契约定义的签名、参数、返回值、异常
```

违反上述任何一条，代码产出在合规检查中直接标记为不合规，不得合流。

---

## 四、CX-O 项目专属约束

### 4.1 服务边界声明

CX-O 是**多服务架构**，以下服务目录是独立服务，**非 AC 模块**，仅通过 `public/` 契约通信：

| 服务 | 根级目录 | 技术栈 | 端口 |
|------|---------|--------|------|
| CX-O Frontend | `CX-O-Frontend/` | React 18 + TypeScript + Vite + Electron | 5173 |
| CX-O Server | `CX-O-SERVER/` | Python 3.10+ + FastAPI + WebSocket | 8000 |
| CX-O VoiceWorkStation | `CX-O-VoiceWorkStation/` | Python（可选） | 8200 |

**第三方独立仓库**（原位不动，不纳入 AC 模块管理）：
- `orpheus-tts/`、`cosyvoice/`、`CosyVoice-main/`、`so-vits-svc-4.1-Stable/`、`VoxCPM-main/`、`LLM_Live2D-master/`

### 4.2 目录策略

- **现有源码目录留根级不迁移**：CX-O-Frontend/SERVER/VoiceWorkStation 保持根级，不迁移至 `modules/`
- **`modules/` 为空容器**：预留给未来按 AC 规范（`模块N_xxx`）新增的后端模块，详见 [modules/README.md](./modules/README.md)
- **`public/` 为跨服务公共真相源**：三层契约（schema/interface_stub/config_template）由各服务共同遵守
- **`.trae/` 为 AC 资产区**：Rules/Skills/specs/documents/Pipeline，已 .gitignore 忽略（不入 git，本地 AC 资产）

### 4.3 契约映射表

| 契约层 | 源真理（真实契约源） | public/ 落点 | 当前状态 |
|--------|---------------------|--------------|----------|
| 数据契约 | `data/agents.json`、`CX-O-SERVER/server/protocol/message.py`、`server/core/*/models.py`、`CX-O-Frontend/src/api/clients/_types.ts` | `public/schema/` | 🟡 种子阶段，待 s0201 |
| 接口契约 | `CX-O-SERVER/server/api/routers/` 19 个 FastAPI router + WS Actions | `public/interface_stub/` | 🟡 种子阶段，待 s0201 |
| 配置契约 | `CX-O-SERVER/server/config.py` UnifiedConfig、`config/*.yaml`、`.env.example` | `public/config_template/` | 🟡 种子阶段，待 s0201 |

**M16 前端 API 客户端结构**（2026-07-01 重构后）：`CX-O-Frontend/src/api/clients/` 下 12 域 mixin + 2 共享文件（_common.ts + _types.ts），所有 DTO 在 `_types.ts`（17 接口）。

### 4.4 全局错误码要求

- 所有服务必须统一定义错误码，对应 `public/schema/error_codes.schema.json`
- 后端当前错误码散落在各 router 的 HTTPException 与 WS ErrorMessage 中，s0201 阶段需统一
- 调用方必须处理约定的异常，不得静默吞掉

### 4.5 日志规范

- 终端输出格式：`[timestamp] [INFO/ERROR] [elapsed]`
- API Key 仅存本地 `config.json`（模板隔离），禁止在日志/输出/异常信息中打印完整 api_key
- 如需展示仅允许脱敏（例如仅保留前 3 后 2）

### 4.6 合流要求

- 代码变更必须在 `.trae/documents/` 下有对应变更追踪文档（rules-6 §三：修复前必写）
- 文档命名必须符合 `YYYYMMDD_模块N_变更简述.md` 规范（rules-6 §二）
- 文档必须包含完整元数据（frontmatter）+ 四章节（问题分析/修复方案/实现步骤/预期效果）
- 合流前必须通过 GN-004 交付前审查

### 4.7 测试要求

- 后端：`python -m pytest`（CX-O-SERVER 下）
- 前端：`npm run test`（CX-O-Frontend 下，含 lint + test）
- 前端 UI 变更必须通过 s0402 前端三重测试闸门（单测→E2E→Mock 回归）
- 契约测试由 LLM 按 rules-3 §五自主执行，结果由 GN-004 审查验证

### 4.8 RADIX-Lite 迁移新模块（2026-07-19，spec migrate-cxhms-radix-acp-multimodal）

CX-O-SERVER 在 spec `migrate-cxhms-radix-acp-multimodal` 下从 CXHMS 迁移了 4 个核心模块 + ACP 升级，均位于 `CX-O-SERVER/server/core/` 下：

| 模块 | 路径 | 功能 | 契约 |
|------|------|------|------|
| template_engine | `server/core/template_engine/` | Jinja2 模板引擎，7 方法（_parse_frontmatter / create_template / get_template / update_template / delete_template / list_templates / render_template），auto_init 创建 default.j2 + distillation.j2 预设 | `public/interface_stub/template_engine.pyi` |
| multimodal | `server/core/multimodal/` | 多模态管线，4 workers（text / character_card / image / vllm_native），vLLM provider 场景下视频/音频走原生 API，非 vLLM 走降级路径 | `public/interface_stub/multimodal_pipeline.pyi` |
| distillation | `server/core/distillation/` | 蒸馏服务，9 状态机（S_INIT → S_PREREAD → S_QUESTION → S_REFLECT → S_CROSSVALIDATE → S_EXTRACT → S_STORAGE_DECISION → S_FINALIZE / S_REJECT）+ 9 API 端点（4 单次 + 5 批量）+ OBS-6 方案 C LLM 评估重构（QUALITY_ESTIMATE_PROMPT + _llm_estimate_quality_score + _estimate_quality_score LLM 优先+启发式回退基础分 0.6→0.4 + 3 配置项 quality_llm_enabled / quality_llm_model / quality_llm_timeout_seconds） | `public/interface_stub/distillation_service.pyi` |
| decision | `server/core/decision/` | 管理 Agent 决策核心，6 决策点（D1_LOCATION / D2_METADATA / D3_ASK_USER / D4_REDISTILL / D5_CROSS_VALIDATE / D6_REJECT）+ write_with_decision / get_rejected_content / cleanup_expired_rejected_content | `public/interface_stub/decision_core.pyi` |
| acp（升级） | `server/core/acp/manager.py` | ACP v3.1.0 per-agent 隔离升级（per-agent Weaviate collection + per-agent SQLite graph + 端口更新修复） | `public/interface_stub/agent_tools_v2.pyi` |

**配置节扩展**（`server/config.py`）：4 新配置类（DistillationConfig / MultimodalPipelineConfig / RadixConfig / DecisionCoreConfig），auto_fill 默认值，越界回退。

**API 路由扩展**（`server/api/routers/` + `server/api/app.py` 注册）：
- `multimodal.py` — 多模态预处理 API
- `distillation.py` — 蒸馏 9 路由聚合（4 单次 + 5 批量）
- `decision.py` — 6 决策点 API
- `acp.py` — 升级后 per-agent 隔离 + `/acp/receive` 端点

**测试体系**（`tests/test_tools/e2e/`）：5 E2E 测试（test_distillation_e2e / test_decision_e2e / test_multimodal_vllm_native_e2e / test_acp_per_agent_isolation_e2e / test_asr_llm_tts_latency），`run_e2e_tests.py` ALL PASSED 8/8（2026-07-19 19:21:50，WS P95=599.54ms / HTTP P95=294.76ms < 800ms）。

**变更追踪文档**（`.trae/documents/`）：6 个迁移文档（20260718_模块7/8/9/10 + 20260718_模块0_ACP隔离升级 + 20260719_模块0_ASRLLMTTS延迟验证）+ OBS-6 方案 C 重构文档（20260719_模块9_质量评分LLM评估重构）+ D5.6 复合根因修复文档（20260719_模块0_CXFC路由注入修复）。

### 4.9 聊天管线与提示词工程收敛（2026-08-09）

> 深度测试与架构/提示词优化阶段对聊天链路做了「去重 + 单入口」收敛，新增/整并以下核心模块。**新增模块一律以其为唯一真相源，禁止在别处复制实现。**

| 模块 | 路径 | 职责 | 关键符号 |
|------|------|------|----------|
| 提示词组装 | `server/prompt_builder.py` | 收敛 handler/chat、api/routers/chat、anythingllm 三份聊天消息组装为**单一入口**；实时语音瘦身、hidden_prompt 注入、history 透传、多模态、CXFC 技能注入 | `build_messages` |
| 聊天助手 | `server/chat_helpers.py` | 跨 HTTP 路由与 WS 处理器共享的 Agent 解析、LLM 客户端选择、工具收集唯一规范实现 | `get_agent_config` / `get_llm_client_for_agent` / `get_tools_for_agent` |
| 聊天流式管线 | `server/core/chat/stream.py` | 流式聊天状态机 + 工具调用循环（`MAX_TOOL_ROUNDS=5` 截断、工具仅首轮注入、工具后二次生成不带工具），供 ACP 自动回复复用 | `ChatStreamState` / `generate_chat_stream` |
| 打断判定收敛 | `server/services/interrupt_llm.py` | 打断模块公共基类 `InterruptModuleBase`（会话/上下文/独立模型配置 + `_call_main_llm` 主模型判定 + `_invoke_callback` 回调分发），`asr_interrupt.ASRInterruptModule` 与 `agent_interrupt_user.AgentInterruptUser` 继承复用；底层统一「HTTP 调用 + JSON 解析 + 关键词兜底 + 超时降级」的 Ollama 判定 `call_ollama_decision` | `InterruptModuleBase` / `call_ollama_decision` |
| 连接池化 | `server/core/utils.py` | 共享 keep-alive HTTP 客户端，被 Ollama/TRTLLM 客户端、嵌入客户端、模型路由健康检查复用，消除逐请求建连 | `get_shared_http_client` |

**消费方约束**：所有聊天入口（HTTP `/chat`、WS chat handler、ACP 自动回复）必须经 `prompt_builder.build_messages` 组装消息、经 `chat_helpers.get_tools_for_agent` 收集工具；流式管线统一走 `core/chat/stream.py`。新增聊天相关实现不得绕过上述单入口。

---

## 五、关键文件路径速查

| 功能 | 路径 |
|------|------|
| AC 范式规则 | `.trae/rules/rules-0~7.md` |
| AC 范式 Skills | `.trae/skills/` |
| 变更追踪文档 | `.trae/documents/` |
| spec 三件套 | `.trae/specs/` |
| 连续性锚点 | `current-note.md` |
| 三层契约 | `public/` |
| 模块容器 | `modules/` |
| 后端入口 | `CX-O-SERVER/server/main.py` |
| 前端入口 | `CX-O-Frontend/src/main.tsx` |
| 后端配置 | `CX-O-SERVER/server/config.py`、`config/` |
| 前端 API 客户端 | `CX-O-Frontend/src/api/clients/` |
| 前端类型 | `CX-O-Frontend/src/api/clients/_types.ts` |
| WS 协议 | `CX-O-SERVER/server/protocol/message.py`、`actions.py` |
| 提示词组装单入口 | `CX-O-SERVER/server/prompt_builder.py` |
| 聊天助手单入口 | `CX-O-SERVER/server/chat_helpers.py` |
| 聊天流式管线 | `CX-O-SERVER/server/core/chat/stream.py` |
| 打断判定收敛 | `CX-O-SERVER/server/services/interrupt_llm.py` |
| 共享 HTTP 连接池 | `CX-O-SERVER/server/core/utils.py` |

---

## 六、参考文档

- [README.md](./README.md) — 用户向入口锚点
- [public/README.md](./public/README.md) — 三层契约保护规则
- [modules/README.md](./modules/README.md) — 模块容器说明
- [current-note.md](./current-note.md) — 连续性交接锚点
- `.trae/rules/rules-0.md` — AC 范式核心行为规则
- `.trae/rules/rules-2.md` — 目录架构与命名规范
- `.trae/rules/rules-3.md` — 三层契约定义
- `.trae/rules/rules-4.md` — AGENTS.md 模板与上下文保留
- `.trae/rules/rules-5.md` — 锚点与双文档体系
- `.trae/rules/rules-6.md` — 变更追踪闸门
- `.trae/rules/rules-7.md` — Subagent 调度与续接
