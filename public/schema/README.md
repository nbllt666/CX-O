# public/schema/ — 数据契约（JSON Schema）

> 数据契约层，rules-3 §一定义。所有核心数据结构以 JSON Schema (draft-07+) 定义，字段描述无歧义。

## 当前状态：种子阶段 + s0601 部分补全

- s0601 (Spec A) 已补全 3 个 schema：`acp.schema.json` / `api_response.schema.json` / `message.schema.json`
- 其余 schema 仍为种子阶段，待 s0201 完整补全

## Schema 清单与源真理

| Schema 文件 | 源真理（真实契约源） | 优先级 | 状态 |
|-------------|---------------------|--------|------|
| `agent.schema.json` | `c:/CX-O/data/agents.json`（14 字段） | P0 | 🟡 种子 |
| `chat_message.schema.json` | `c:/CX-O/CX-O-SERVER/server/protocol/message.py` + 前端 APP-Frontend/src/api/types.ts | P0 | 🟡 种子 |
| `memory.schema.json` | `c:/CX-O/CX-O-SERVER/server/core/memory/` + 前端 APP-Frontend/src/api/types.ts | P1 | 🟡 种子 |
| `graph_entity.schema.json` | `c:/CX-O/CX-O-SERVER/server/core/graph/models.py` | P1 | 🟡 种子 |
| `tool.schema.json` | `c:/CX-O/APP-Frontend/src/api/types.ts` Tool 接口 | P1 | 🟡 种子 |
| `error_codes.schema.json` | 全局错误码（待定义） | P2 | 🟡 种子 |
| `acp.schema.json` | `c:/CX-O/CX-O-SERVER/server/models/acp.py` + `server/core/acp/manager.py`（5 Pydantic 模型） | P1 | ✅ s0601 补全 |
| `api_response.schema.json` | `c:/CX-O/CX-O-SERVER/server/api/response.py`（4 Pydantic 模型） | P1 | ✅ s0601 补全 |
| `message.schema.json` | `c:/CX-O/CX-O-SERVER/server/protocol/message.py`（7 Pydantic 模型 + 5 工厂） | P0 | ✅ s0601 补全 |
| `computer_control_plugin.schema.json` | 电脑控制插件数据契约（spec `add-computer-control-cxfc` 冻结决策） | P1 | ✅ s0201 补全（迁移自 contracts/plugin.json） |
| `computer_control_error_codes.json` | 电脑控制插件统一错误码枚举（spec `add-computer-control-cxfc` 冻结决策） | P1 | ✅ s0201 补全（迁移自 contracts/error_codes.json） |
| `speech_synthesis_request.schema.json` | 统一 Qwen3 TTS 合成请求（spec `unify-qwen3-tts-migration` Task 1 冻结决策） | P0 | ✅ s0201 补全 |
| `speech_synthesis_response.schema.json` | 统一 Qwen3 TTS 非流式响应（spec `unify-qwen3-tts-migration` Task 1 冻结决策） | P0 | ✅ s0201 补全 |
| `speech_audio_chunk.schema.json` | 统一 Qwen3 TTS 流式音频块（spec `unify-qwen3-tts-migration` Task 1 冻结决策） | P0 | ✅ s0201 补全 |
| `ref_audio_asset.schema.json` | 统一参考音频资产（双来源 prompt/file，spec `unify-qwen3-tts-migration` Task 1 冻结决策） | P0 | ✅ s0201 补全 |
| `emotion_instruction.schema.json` | LLM 自然语言情感指令（spec `unify-qwen3-tts-migration` Task 1 冻结决策） | P0 | ✅ s0201 补全 |
| `qwen3_tts_error_codes.json` | 统一 Qwen3 TTS 错误码枚举（spec `unify-qwen3-tts-migration` Task 1 冻结决策） | P0 | ✅ s0201 补全 |

### Qwen3 TTS 数据契约清单（spec `unify-qwen3-tts-migration`）

> 统一 Qwen3 TTS 三层契约的数据层，对应 Task 1 冻结。源真理为 spec `unify-qwen3-tts-migration` 冻结决策与 Qwen3-TTS/vLLM-Omni 官方协议（能力矩阵见 Task 0 基线盘点）。

| Schema 文件 | 职责 | 关键约束 |
|------------|------|---------|
| `speech_synthesis_request.schema.json` | 归一合成请求（普通/流式/WS/工作站） | text 必填；refs 引用资产 ID，禁止本地路径；输出采样率 const 24000 |
| `speech_synthesis_response.schema.json` | 非流式响应 | audio base64 + runtime 标识（vllm/official_qwen3） |
| `speech_audio_chunk.schema.json` | 流式音频块 | 恰一个 start/一个 final，顺序稳定 |
| `ref_audio_asset.schema.json` | 参考音频资产（source=prompt/file） | 稳定 ID、checksum 去重、输入采样率 [8000,48000] |
| `emotion_instruction.schema.json` | LLM 自然语言情感指令 | 与 reply_text 分离；失败回退中性；禁止 [emotion:*]/Orpheus XML |
| `qwen3_tts_error_codes.json` | 统一错误码 | 9 码含 http_status；LEGACY_ENGINE_REMOVED 标记旧引擎移除 |

## 契约可验证性（rules-3 §五）

- **测试套件**：s0601 补全的 3 个 schema 已有对应测试（tests/test_models_acp.py / tests/test_api_response.py / tests/test_router_websocket.py）
- **合规 rubric**：s0601 补全的 3 个 schema 已在 `_contractVerifiability` 字段记录 rubric
- **self_test**：T15 全量回归 4900 passed 含 s0601 补全 schema 对应的所有测试

## 字段描述规范

- 所有字段必须包含 `type`、`description`（无歧义）、`required`（必填性）
- 错误码与异常契约统一定义于 `error_codes.schema.json`
- 所有数据读写通过 jsonschema 库自动校验，不符合契约的数据禁止入库
