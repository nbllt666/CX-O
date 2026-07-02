# public/schema/ — 数据契约（JSON Schema）

> 数据契约层，rules-3 §一定义。所有核心数据结构以 JSON Schema (draft-07+) 定义，字段描述无歧义。

## 当前状态：种子阶段

本目录当前为种子阶段，schema 文件仅含源真理指针（`_sourceOfTruth` 字段指向真实契约源），不包含完整字段定义。完整 Schema 由后续 s0201 Skill 承接生成。

## Schema 清单与源真理

| Schema 文件 | 源真理（真实契约源） | 优先级 |
|-------------|---------------------|--------|
| `agent.schema.json` | `c:/CX-O/data/agents.json`（14 字段：id/name/description/system_prompt/model/temperature/max_tokens/use_memory/use_tools/memory_scene/decay_model/vision_enabled/is_default/created_at/updated_at） | P0 |
| `chat_message.schema.json` | `c:/CX-O/CX-O-SERVER/server/protocol/message.py`（6 消息类型：BaseMessage/RequestMessage/ResponseMessage/StreamMessage/ErrorMessage/Ping/Pong）+ `c:/CX-O/CX-O-Frontend/src/api/clients/_types.ts` ChatMessage 接口 | P0 |
| `memory.schema.json` | `c:/CX-O/CX-O-SERVER/server/core/memory/` 模型 + `c:/CX-O/CX-O-Frontend/src/api/clients/_types.ts` Memory 接口 | P1 |
| `graph_entity.schema.json` | `c:/CX-O/CX-O-SERVER/server/core/graph/models.py`（GraphNode/GraphEdge 等 9 个，dataclass）+ 前端 GraphEntity/GraphRelation 接口 | P1 |
| `tool.schema.json` | `c:/CX-O/CX-O-Frontend/src/api/clients/_types.ts` Tool 接口 + `c:/CX-O/CX-O-SERVER/server/core/tools/` | P1 |
| `error_codes.schema.json` | 全局错误码（待定义，当前为占位） | P2 |

## 契约可验证性（rules-3 §五）

- **测试套件**：未闭合，待 s0201 生成完整 Schema 后补数据契约校验用例
- **合规 rubric**：未闭合，待 s0201 生成后补字段覆盖判据
- **self_test**：未闭合，待 s0201 生成后由 LLM 自主运行测试套件

## 字段描述规范

- 所有字段必须包含 `type`、`description`（无歧义）、`required`（必填性）
- 错误码与异常契约统一定义于 `error_codes.schema.json`
- 所有数据读写通过 jsonschema 库自动校验，不符合契约的数据禁止入库
