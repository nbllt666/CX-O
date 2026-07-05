# public/schema/ — 数据契约（JSON Schema）

> 数据契约层，rules-3 §一定义。所有核心数据结构以 JSON Schema (draft-07+) 定义，字段描述无歧义。

## 当前状态：种子阶段 + s0601 部分补全

- s0601 (Spec A) 已补全 3 个 schema：`acp.schema.json` / `api_response.schema.json` / `message.schema.json`
- 其余 schema 仍为种子阶段，待 s0201 完整补全

## Schema 清单与源真理

| Schema 文件 | 源真理（真实契约源） | 优先级 | 状态 |
|-------------|---------------------|--------|------|
| `agent.schema.json` | `c:/CX-O/data/agents.json`（14 字段） | P0 | 🟡 种子 |
| `chat_message.schema.json` | `c:/CX-O/CX-O-SERVER/server/protocol/message.py` + 前端 _types.ts | P0 | 🟡 种子 |
| `memory.schema.json` | `c:/CX-O/CX-O-SERVER/server/core/memory/` + 前端 _types.ts | P1 | 🟡 种子 |
| `graph_entity.schema.json` | `c:/CX-O/CX-O-SERVER/server/core/graph/models.py` | P1 | 🟡 种子 |
| `tool.schema.json` | `c:/CX-O/CX-O-Frontend/src/api/clients/_types.ts` Tool 接口 | P1 | 🟡 种子 |
| `error_codes.schema.json` | 全局错误码（待定义） | P2 | 🟡 种子 |
| `acp.schema.json` | `c:/CX-O/CX-O-SERVER/server/models/acp.py` + `server/core/acp/manager.py`（5 Pydantic 模型） | P1 | ✅ s0601 补全 |
| `api_response.schema.json` | `c:/CX-O/CX-O-SERVER/server/api/response.py`（4 Pydantic 模型） | P1 | ✅ s0601 补全 |
| `message.schema.json` | `c:/CX-O/CX-O-SERVER/server/protocol/message.py`（7 Pydantic 模型 + 5 工厂） | P0 | ✅ s0601 补全 |

## 契约可验证性（rules-3 §五）

- **测试套件**：s0601 补全的 3 个 schema 已有对应测试（tests/test_models_acp.py / tests/test_api_response.py / tests/test_router_websocket.py）
- **合规 rubric**：s0601 补全的 3 个 schema 已在 `_contractVerifiability` 字段记录 rubric
- **self_test**：T15 全量回归 4900 passed 含 s0601 补全 schema 对应的所有测试

## 字段描述规范

- 所有字段必须包含 `type`、`description`（无歧义）、`required`（必填性）
- 错误码与异常契约统一定义于 `error_codes.schema.json`
- 所有数据读写通过 jsonschema 库自动校验，不符合契约的数据禁止入库
