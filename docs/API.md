# CX-O API 文档

## 概述

CX-O 系统提供两套 API：
1. **CXHMS REST API** (端口 8000)：核心 AI 服务接口
2. **Gateway WebSocket API** (端口 8100)：前端统一入口

---

## CXHMS REST API

**基础 URL**: `http://127.0.0.1:8000`

**API 文档**: `http://127.0.0.1:8000/docs`

### 基础信息

- **Content-Type**: `application/json`
- **认证**: 当前版本未启用认证

---

## 记忆管理 API

### 1. 列出记忆

```
GET /api/memories
```

**参数**:
- `workspace_id` (string, 可选): 工作区ID，默认 "default"
- `memory_type` (string, 可选): 记忆类型（long_term, short_term, permanent）
- `limit` (integer, 可选): 返回数量，默认 20
- `offset` (integer, 可选): 偏移量，默认 0

**响应**:
```json
{
  "status": "success",
  "memories": [
    {
      "id": 1,
      "type": "long_term",
      "content": "用户喜欢编程",
      "importance": 3,
      "tags": ["编程"],
      "created_at": "2026-02-06T10:00:00"
    }
  ],
  "total": 1
}
```

### 2. 创建记忆

```
POST /api/memories
```

**请求体**:
```json
{
  "content": "用户喜欢编程",
  "type": "long_term",
  "importance": 3,
  "tags": ["编程"],
  "workspace_id": "default"
}
```

### 3. 获取记忆详情

```
GET /api/memories/{memory_id}
```

### 4. 更新记忆

```
PUT /api/memories/{memory_id}
```

**请求体**:
```json
{
  "content": "用户喜欢Python编程",
  "importance": 4,
  "tags": ["Python", "编程"]
}
```

### 5. 删除记忆

```
DELETE /api/memories/{memory_id}
```

### 6. 搜索记忆

```
POST /api/memories/search
```

**请求体**:
```json
{
  "query": "编程",
  "memory_type": "long_term",
  "limit": 10
}
```

### 7. 语义搜索

```
POST /api/memories/semantic-search
```

**请求体**:
```json
{
  "query": "用户的爱好是什么？",
  "limit": 10,
  "threshold": 0.7
}
```

### 8. 三维搜索

```
POST /api/memories/3d
```

**请求体**:
```json
{
  "query": "编程",
  "limit": 10,
  "weights": [0.35, 0.25, 0.4]
}
```

### 9. RAG 搜索

```
POST /api/memories/rag
```

**请求体**:
```json
{
  "query": "用户的爱好是什么？",
  "workspace_id": "default",
  "limit": 5
}
```

### 10. 记忆召回

```
POST /api/memories/recall
```

**请求体**:
```json
{
  "memory_ids": [1, 2, 3],
  "reactivation_strength": 0.2
}
```

### 11. 批量操作

**批量写入**: `POST /api/memories/batch/write`

**批量更新**: `POST /api/memories/batch/update`

**批量删除**: `POST /api/memories/batch/delete`

### 12. 永久记忆

**列出**: `GET /api/memories/permanent`

**创建**: `POST /api/memories/permanent`

**删除**: `DELETE /api/memories/permanent/{memory_id}`

---

## 上下文管理 API

### 1. 创建会话

```
POST /api/sessions
```

**请求体**:
```json
{
  "workspace_id": "default",
  "title": "新对话",
  "user_id": "user123"
}
```

### 2. 获取会话列表

```
GET /api/sessions
```

### 3. 获取会话详情

```
GET /api/sessions/{session_id}
```

### 4. 删除会话

```
DELETE /api/sessions/{session_id}
```

### 5. 添加消息

```
POST /api/sessions/{session_id}/messages
```

**请求体**:
```json
{
  "role": "user",
  "content": "你好"
}
```

### 6. 获取消息历史

```
GET /api/sessions/{session_id}/messages
```

---

## 聊天 API

### 1. 发送消息

```
POST /api/chat
```

**请求体**:
```json
{
  "message": "你好",
  "agent_id": "default",
  "stream": false
}
```

**参数说明**:
- `message` (string, 必需): 用户消息
- `agent_id` (string, 可选): Agent ID，默认 "default"
- `stream` (boolean, 可选): 是否流式响应，默认 true
- `images` (array, 可选): base64 编码的图片列表

**响应**:
```json
{
  "status": "success",
  "response": "你好！有什么可以帮忙的？",
  "session_id": "agent-default",
  "tokens_used": 150
}
```

### 2. 流式聊天

```
POST /api/chat/stream
```

**响应**: Server-Sent Events (SSE) 流

**事件类型**:
- `session`: 会话信息
- `thinking`: 思考过程
- `content`: 内容片段
- `tool_call`: 工具调用
- `tool_result`: 工具执行结果
- `done`: 完成
- `error`: 错误

### 3. 获取聊天历史

```
GET /api/chat/history/{session_id}
```

---

## ACP 互联 API

### 1. 发现 Agents

```
POST /api/acp/discover
```

**请求体**:
```json
{
  "timeout": 5.0
}
```

### 2. 注册 Agent

```
POST /api/acp/agents
```

**请求体**:
```json
{
  "agent_id": "agent-1",
  "name": "Agent 1",
  "host": "192.168.1.100",
  "port": 8001,
  "capabilities": ["chat", "tools"]
}
```

### 3. 获取 Agent 列表

```
GET /api/acp/agents
```

### 4. 发送点对点消息

```
POST /api/acp/messages/p2p
```

**请求体**:
```json
{
  "to_agent_id": "agent-2",
  "content": {"text": "你好"}
}
```

### 5. 群组管理

**创建群组**: `POST /api/acp/groups`

**加入群组**: `POST /api/acp/groups/join`

**退出群组**: `POST /api/acp/groups/leave`

---

## 工具管理 API

### 1. 列出工具

```
GET /api/tools
```

**响应**:
```json
{
  "status": "success",
  "tools": [
    {
      "name": "search_web",
      "description": "搜索网络",
      "parameters": {
        "type": "object",
        "properties": {
          "query": {"type": "string"}
        }
      }
    }
  ]
}
```

### 2. 调用工具

```
POST /api/tools/call
```

**请求体**:
```json
{
  "name": "calculator",
  "arguments": {"expr": "1 + 2"}
}
```

### 3. 获取 OpenAI 格式工具列表

```
GET /api/tools/openai
```

---

## MCP 工具管理 API

### 1. 列出 MCP 服务器

```
GET /api/tools/mcp/servers
```

### 2. 添加 MCP 服务器

```
POST /api/tools/mcp/servers
```

**请求体**:
```json
{
  "name": "filesystem",
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path"]
}
```

### 3. 启动 MCP 服务器

```
POST /api/tools/mcp/servers/start
```

### 4. 调用 MCP 工具

```
POST /api/tools/mcp/call
```

**请求体**:
```json
{
  "server_name": "filesystem",
  "tool_name": "read_file",
  "arguments": {"path": "/path/to/file"}
}
```

---

## Agent 管理 API

### 1. 获取 Agent 列表

```
GET /api/agents
```

### 2. 创建 Agent

```
POST /api/agents
```

### 3. 获取 Agent 详情

```
GET /api/agents/{agent_id}
```

### 4. 更新 Agent

```
PUT /api/agents/{agent_id}
```

### 5. 删除 Agent

```
DELETE /api/agents/{agent_id}
```

### 6. 克隆 Agent

```
POST /api/agents/{agent_id}/clone
```

---

## 管理员 API

### 1. 健康检查

```
GET /api/admin/health
```

**响应**:
```json
{
  "status": "success",
  "health": {
    "database": "ok",
    "vector_store": "ok",
    "llm": "ok"
  }
}
```

### 2. 系统统计

```
GET /api/admin/stats
```

---

## Gateway WebSocket API

**WebSocket URL**: `ws://127.0.0.1:8100/ws`

### 连接

```javascript
const ws = new WebSocket("ws://127.0.0.1:8100/ws");

ws.onopen = () => {
  console.log("Connected to CX-O Gateway");
};
```

### 消息格式

**请求**:
```json
{
  "type": "request",
  "action": "module.action",
  "request_id": "uuid-string",
  "data": {}
}
```

**响应**:
```json
{
  "type": "response",
  "request_id": "uuid-string",
  "action": "module.action",
  "status": "success",
  "data": {}
}
```

### Action 速查

#### 聊天

| Action | 说明 | data |
|--------|------|------|
| chat.message | 发送消息 | `{messages, agent_id}` |
| chat.stream | 流式聊天 | `{text, agent_id}` |

#### 记忆

| Action | 说明 | data |
|--------|------|------|
| memory.list | 列出记忆 | `{}` |
| memory.create | 创建记忆 | `{content, memory_type, tags}` |
| memory.search | 搜索记忆 | `{query}` |
| memory.delete | 删除记忆 | `{id}` |

#### 工具

| Action | 说明 | data |
|--------|------|------|
| tools.list | 列出工具 | `{}` |
| tools.call | 调用工具 | `{tool_name, parameters}` |

#### 语音

| Action | 说明 | data |
|--------|------|------|
| asr.recognize | 语音识别 | `{audio: base64}` |
| asr.stream | 实时 ASR 流 | `{audio: base64}` |
| tts.synthesize | 语音合成 | `{text, ref_audio, ref_text}` |
| tts.synthesize_stream | 流式 TTS | `{text, emotion_enabled}` |

#### 系统

| Action | 说明 | data |
|--------|------|------|
| system.health | 健康检查 | `{}` |
| system.config | 获取配置 | `{}` |

#### ACP

| Action | 说明 | data |
|--------|------|------|
| acp.discover | 发现 Agent | `{}` |
| acp.send | 发送消息 | `{target, message}` |

---

## 错误码

| 错误码 | 说明 |
|--------|------|
| AUTH_ERROR | 认证错误 |
| NOT_FOUND | 资源不存在 |
| VALIDATION_ERROR | 参数验证失败 |
| INTERNAL_ERROR | 内部错误 |
| SERVICE_UNAVAILABLE | 服务不可用 |
| RATE_LIMITED | 请求过于频繁 |

---

## 示例代码

### Python 示例

```python
import httpx

async def create_memory():
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://127.0.0.1:8000/api/memories",
            json={
                "content": "用户喜欢编程",
                "type": "long_term",
                "importance": 3
            }
        )
        return response.json()

result = await create_memory()
print(result)
```

### JavaScript WebSocket 示例

```javascript
const ws = new WebSocket("ws://127.0.0.1:8100/ws");

ws.onopen = () => {
  ws.send(JSON.stringify({
    type: "request",
    action: "chat.message",
    request_id: "req_001",
    data: {
      messages: [{"role": "user", "content": "你好"}]
    }
  }));
};

ws.onmessage = (event) => {
  const response = JSON.parse(event.data);
  console.log("Received:", response);
};
```

### cURL 示例

```bash
# 创建记忆
curl -X POST http://127.0.0.1:8000/api/memories \
  -H "Content-Type: application/json" \
  -d '{"content": "测试记忆", "type": "long_term", "importance": 3}'

# 健康检查
curl http://127.0.0.1:8000/api/admin/health
```
