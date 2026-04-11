# CX-O API 文档

## 概述

CX-O v4 单体架构提供统一的 REST API 和 WebSocket 接口。

## 基础信息

- **Base URL**: `http://127.0.0.1:8100`
- **WebSocket**: `ws://127.0.0.1:8100/ws`
- **Content-Type**: `application/json`

## REST API

### 健康检查

```
GET /health
```

响应：
```json
{
  "status": "healthy",
  "service": "CX-O Server",
  "version": "1.0.0",
  "architecture": "monolithic"
}
```

### 记忆管理

#### 创建记忆

```
POST /api/memory
```

请求：
```json
{
  "content": "今天学习了 Python 异步编程",
  "memory_type": "long_term",
  "tags": ["学习", "编程"],
  "importance": 3
}
```

响应：
```json
{
  "id": "mem_xxx",
  "content": "今天学习了 Python 异步编程",
  "memory_type": "long_term",
  "created_at": "2024-01-01T12:00:00Z"
}
```

#### 搜索记忆

```
POST /api/memory/search
```

请求：
```json
{
  "query": "Python 异步"
}
```

响应：
```json
{
  "results": [
    {
      "id": "mem_xxx",
      "content": "今天学习了 Python 异步编程",
      "relevance": 0.95
    }
  ]
}
```

#### 列出记忆

```
GET /api/memory
```

响应：
```json
{
  "memories": [
    {"id": "mem_xxx", "content": "...", "memory_type": "long_term"}
  ],
  "total": 100
}
```

#### 删除记忆

```
DELETE /api/memory/{id}
```

### 上下文管理

#### 获取上下文

```
GET /api/context/{session_id}
```

响应：
```json
{
  "session_id": "sess_xxx",
  "messages": [
    {"role": "user", "content": "你好"},
    {"role": "assistant", "content": "你好，有什么可以帮忙的？"}
  ]
}
```

#### 清空上下文

```
DELETE /api/context/{session_id}
```

### 工具

#### 列出工具

```
GET /api/tools
```

响应：
```json
{
  "tools": [
    {
      "name": "calculator",
      "description": "数学计算",
      "parameters": {"expr": "string"}
    }
  ]
}
```

#### 调用工具

```
POST /api/tools/call
```

请求：
```json
{
  "tool_name": "calculator",
  "parameters": {"expr": "1 + 2 * 3"}
}
```

响应：
```json
{
  "result": 7
}
```

### ACP 协议

#### 发现 Agent

```
GET /api/acp/agents
```

响应：
```json
{
  "agents": [
    {
      "agent_id": "agent_xxx",
      "name": "My Agent",
      "status": "online"
    }
  ]
}
```

#### 发送消息

```
POST /api/acp/send
```

请求：
```json
{
  "target_agent_id": "agent_xxx",
  "message": "你好"
}
```

### 备份

#### 创建备份

```
POST /api/backup
```

请求：
```json
{
  "source_path": "data/memories.db",
  "backup_name": "memories_backup"
}
```

响应：
```json
{
  "backup_path": "data/backups/memories_backup",
  "created_at": "2024-01-01T12:00:00Z"
}
```

#### 列出备份

```
GET /api/backup
```

响应：
```json
{
  "backups": [
    {
      "name": "memories_backup",
      "path": "data/backups/memories_backup",
      "size": 1024000,
      "created": "2024-01-01T12:00:00Z"
    }
  ]
}
```

#### 恢复备份

```
POST /api/backup/restore
```

请求：
```json
{
  "backup_path": "data/backups/memories_backup",
  "target_path": "data/memories.db"
}
```

## WebSocket API

### 连接

```javascript
const ws = new WebSocket("ws://127.0.0.1:8100/ws");

ws.onopen = () => {
  ws.send(JSON.stringify({
    type: "ping"
  }));
};
```

### 发送请求

```javascript
ws.send(JSON.stringify({
  action: "chat.message",
  request_id: "req_xxx",
  data: {
    messages: [{"role": "user", "content": "你好"}]
  }
}));
```

### 接收响应

```javascript
ws.onmessage = (event) => {
  const response = JSON.parse(event.data);

  if (response.type === "response") {
    console.log("Result:", response.data);
  } else if (response.type === "stream") {
    console.log("Chunk:", response.data);
  } else if (response.type === "error") {
    console.error("Error:", response.message);
  }
};
```

### Action 速查

| 模块 | Action | 说明 |
|------|--------|------|
| chat | chat.message | 发送聊天消息 |
| chat | chat.stream | 流式聊天 |
| memory | memory.list | 列出记忆 |
| memory | memory.create | 创建记忆 |
| memory | memory.search | 搜索记忆 |
| memory | memory.delete | 删除记忆 |
| tools | tools.list | 列出工具 |
| tools | tools.call | 调用工具 |
| asr | asr.recognize | 语音识别 |
| asr | asr.stream | 实时 ASR |
| tts | tts.synthesize | 语音合成 |
| tts | tts.synthesize_stream | 流式 TTS |
| acp | acp.discover | 发现 Agent |
| acp | acp.send | 发送消息 |
| system | system.health | 健康检查 |
| system | system.config | 获取配置 |

## 错误码

| 错误码 | 说明 |
|--------|------|
| AUTH_ERROR | 认证错误 |
| NOT_FOUND | 资源不存在 |
| VALIDATION_ERROR | 参数验证失败 |
| INTERNAL_ERROR | 内部错误 |
| SERVICE_UNAVAILABLE | 服务不可用 |
| RATE_LIMITED | 请求过于频繁 |

## 速率限制

- REST API: 100 请求/分钟
- WebSocket: 1000 消息/分钟

## 认证

当前版本未启用认证，请勿直接暴露到公网。
