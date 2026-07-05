# public/interface_stub/ — 接口契约存根索引

> 接口契约层，rules-3 §二定义。所有对外接口以 Python .pyi 存根文件定义，零实现逻辑，仅声明签名（方法名、参数类型、返回值类型、抛出异常）。

## 当前状态：种子阶段 + s0601 部分补全

- s0601 (Spec A) 已补全 `websocket.pyi`（7 消息模型 + 18 个独立 Action 类镜像 + 4 WS 端点签名 + 5 工厂函数签名）
- 其余存根仍为种子阶段，待 s0201 完整补全

## 计划存根清单（19 个 FastAPI router + WS）

| 存根文件 | 源真理（router 文件） | 优先级 | 状态 |
|---------|---------------------|--------|------|
| `chat.pyi` | `c:/CX-O/CX-O-SERVER/server/api/routers/chat.py` | P0 | 🟡 种子已建 |
| `agents.pyi` | `c:/CX-O/CX-O-SERVER/server/api/routers/agents.py` | P0 | 🟡 种子已建 |
| `memory.pyi` | `c:/CX-O/CX-O-SERVER/server/api/routers/memory.py` | P0 | 🟡 种子已建 |
| `websocket.pyi` | `c:/CX-O/CX-O-SERVER/server/api/routers/websocket.py` + `server/protocol/` | P0 | ✅ s0601 补全 |
| `graph.pyi` | `c:/CX-O/CX-O-SERVER/server/api/routers/graph.py` | P1 | ⬜ 待 s0201 |
| `acp.pyi` | `c:/CX-O/CX-O-SERVER/server/api/routers/acp.py` | P1 | ⬜ 待 s0201 |
| `cxfc.pyi` | `c:/CX-O/CX-O-SERVER/server/api/routers/cxfc.py` | P1 | ⬜ 待 s0201 |
| `audio.pyi` | `c:/CX-O/CX-O-SERVER/server/api/routers/audio.py` | P1 | ⬜ 待 s0201 |
| `avatars.pyi` | `c:/CX-O/CX-O-SERVER/server/api/routers/avatars.py` | P1 | ⬜ 待 s0201 |
| `tools.pyi` | `c:/CX-O/CX-O-SERVER/server/api/routers/tools.py` | P1 | ⬜ 待 s0201 |
| `vector.pyi` | `c:/CX-O/CX-O-SERVER/server/api/routers/vector.py` | P1 | ⬜ 待 s0201 |
| `config.pyi` | `c:/CX-O/CX-O-SERVER/server/api/routers/config.py` | P2 | ⬜ 待 s0201 |
| `context.pyi` | `c:/CX-O/CX-O-SERVER/server/api/routers/context.py` | P2 | ⬜ 待 s0201 |
| `service.pyi` | `c:/CX-O/CX-O-SERVER/server/api/routers/service.py` | P2 | ⬜ 待 s0201 |
| `admin.pyi` | `c:/CX-O/CX-O-SERVER/server/api/routers/admin.py` | P2 | ⬜ 待 s0201 |
| `stats.pyi` | `c:/CX-O/CX-O-SERVER/server/api/routers/stats.py` | P2 | ⬜ 待 s0201 |
| `backup.pyi` | `c:/CX-O/CX-O-SERVER/server/api/routers/backup.py` | P2 | ⬜ 待 s0201 |
| `archive.pyi` | `c:/CX-O/CX-O-SERVER/server/api/routers/archive.py` | P2 | ⬜ 待 s0201 |
| `memory_chat.pyi` | `c:/CX-O/CX-O-SERVER/server/api/routers/memory_chat.py` | P2 | ⬜ 待 s0201 |

## 契约可验证性（rules-3 §五）

- **测试套件**：未闭合，待 s0201 生成完整存根后补接口契约签名匹配用例
- **合规 rubric**：未闭合，待 s0201 生成后补签名匹配判据
- **signature_match 校验**：模块实现必须严格匹配存根定义的签名，否则契约测试不通过

## 异常说明规范

- 接口契约必须包含异常说明（rules-3 §二）
- 调用方必须处理约定的异常
- 异常类型与错误码对应 `schema/error_codes.schema.json`
