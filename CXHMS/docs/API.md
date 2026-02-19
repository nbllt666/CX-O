# CXHMS API 文档

## 概述

CXHMS (CX-O History & Memory Service) 提供了一套完整的RESTful API，用于管理记忆、上下文、ACP互联、工具调用等功能。

**基础URL**: `http://localhost:8000`

**认证**: 当前版本暂未实现认证机制（生产环境请配置API密钥）

**响应格式**: 所有API返回JSON格式，包含`status`字段表示请求状态。

---

## 记忆管理 API

### 1. 列出记忆

**端点**: `GET /api/memories`

**参数**:
- `workspace_id` (string, 可选): 工作区ID，默认为"default"
- `memory_type` (string, 可选): 记忆类型（long_term, short_term, permanent）
- `limit` (integer, 可选): 返回数量限制，默认为20
- `offset` (integer, 可选): 偏移量，默认为0

**响应示例**:
```json
{
  "status": "success",
  "memories": [
    {
      "id": 1,
      "type": "long_term",
      "content": "用户喜欢编程",
      "importance": 3,
      "importance_score": 0.6,
      "time_score": 0.8,
      "relevance_score": 0.7,
      "final_score": 0.7,
      "tags": ["编程", "爱好"],
      "created_at": "2026-02-06T10:00:00"
    }
  ],
  "total": 1
}
```

### 2. 创建记忆

**端点**: `POST /api/memories`

**请求体**:
```json
{
  "content": "用户喜欢编程",
  "type": "long_term",
  "importance": 3,
  "tags": ["编程", "爱好"],
  "metadata": {},
  "permanent": false,
  "workspace_id": "default"
}
```

**响应示例**:
```json
{
  "status": "success",
  "memory_id": 1,
  "message": "记忆已创建"
}
```

### 3. 获取记忆详情

**端点**: `GET /api/memories/{memory_id}`

**响应示例**:
```json
{
  "status": "success",
  "memory": {
    "id": 1,
    "type": "long_term",
    "content": "用户喜欢编程",
    "importance": 3,
    "importance_score": 0.6,
    "tags": ["编程", "爱好"],
    "created_at": "2026-02-06T10:00:00"
  }
}
```

### 4. 更新记忆

**端点**: `PUT /api/memories/{memory_id}`

**请求体**:
```json
{
  "content": "用户喜欢Python编程",
  "importance": 4,
  "tags": ["Python", "编程"]
}
```

### 5. 删除记忆

**端点**: `DELETE /api/memories/{memory_id}`

### 6. 搜索记忆

**端点**: `POST /api/memories/search`

**请求体**:
```json
{
  "query": "编程",
  "memory_type": "long_term",
  "tags": ["Python"],
  "time_range": "last_week",
  "limit": 10,
  "include_deleted": false
}
```

### 7. 三维搜索

**端点**: `POST /api/memories/3d`

**请求体**:
```json
{
  "query": "编程",
  "memory_type": "long_term",
  "tags": [],
  "limit": 10,
  "weights": [0.35, 0.25, 0.4],
  "workspace_id": "default"
}
```

**响应示例**:
```json
{
  "status": "success",
  "memories": [...],
  "total": 5,
  "applied_weights": {
    "importance": 0.35,
    "time": 0.25,
    "relevance": 0.4
  }
}
```

### 8. 语义搜索（向量搜索）

**端点**: `POST /api/memories/semantic-search`

**请求体**:
```json
{
  "query": "用户的爱好是什么？",
  "limit": 10,
  "threshold": 0.7,
  "workspace_id": "default"
}
```

### 8. RAG搜索

**端点**: `POST /api/memories/rag`

**请求体**:
```json
{
  "query": "用户的爱好是什么？",
  "workspace_id": "default",
  "limit": 5
}
```

### 9. 记忆召回

**端点**: `POST /api/memories/recall`

**请求体**:
```json
{
  "memory_ids": [1, 2, 3],
  "reactivation_strength": 0.2
}
```

### 10. 永久记忆管理

**列出永久记忆**: `GET /api/memories/permanent`

**创建永久记忆**: `POST /api/memories/permanent`

**删除永久记忆**: `DELETE /api/memories/permanent/{memory_id}`

### 11. 批量操作

**批量写入**: `POST /api/memories/batch/write`

**请求体**:
```json
{
  "memories": [
    {"content": "记忆1", "type": "long_term", "importance": 3},
    {"content": "记忆2", "type": "long_term", "importance": 4}
  ]
}
```

**批量更新**: `POST /api/memories/batch/update`

**请求体**:
```json
{
  "ids": [1, 2, 3],
  "data": {"tags": ["新标签"], "importance": 4},
  "agent_id": "default"
}
```

**批量删除**: `POST /api/memories/batch/delete`

**请求体**:
```json
{
  "ids": [1, 2, 3],
  "agent_id": "default"
}
```

**批量标签更新**: `POST /api/memories/batch/tags`

**请求体**:
```json
{
  "ids": [1, 2, 3],
  "tags": ["标签1", "标签2"],
  "operation": "add",
  "agent_id": "default"
}
```

**批量归档**: `POST /api/memories/batch/archive`

**批量恢复**: `POST /api/memories/batch/restore`

### 12. Agent记忆表管理

**获取Agent记忆表列表**: `GET /api/memories/agents`

**响应示例**:
```json
{
  "status": "success",
  "agents": [
    {"agent_id": "default", "table_name": "memories", "created_at": null},
    {"agent_id": "agent-001", "table_name": "memories_agent_001", "created_at": "2026-02-16T10:00:00"}
  ],
  "total": 2
}
```

### 13. 记忆统计

**获取记忆统计**: `GET /api/memories/stats`

**获取衰减统计**: `GET /api/memories/decay-stats`

---

## 上下文管理 API

### 1. 创建会话

**端点**: `POST /api/sessions`

**请求体**:
```json
{
  "workspace_id": "default",
  "title": "新对话",
  "user_id": "user123",
  "metadata": {}
}
```

**响应示例**:
```json
{
  "status": "success",
  "session_id": "uuid-string",
  "message": "会话已创建"
}
```

### 2. 获取会话列表

**端点**: `GET /api/sessions`

**参数**:
- `workspace_id` (string, 可选): 工作区ID
- `user_id` (string, 可选): 用户ID

### 3. 获取会话详情

**端点**: `GET /api/sessions/{session_id}`

### 4. 更新会话

**端点**: `PUT /api/sessions/{session_id}`

### 5. 删除会话

**端点**: `DELETE /api/sessions/{session_id}`

### 6. 添加消息

**端点**: `POST /api/sessions/{session_id}/messages`

**请求体**:
```json
{
  "role": "user",
  "content": "你好",
  "metadata": {}
}
```

### 7. 获取消息历史

**端点**: `GET /api/sessions/{session_id}/messages`

**参数**:
- `limit` (integer, 可选): 返回数量限制
- `offset` (integer, 可选): 偏移量

### 8. Mono上下文

**添加Mono上下文**: `POST /api/context/mono`

**获取Mono上下文**: `GET /api/context/mono`

**清理过期上下文**: `POST /api/context/mono/cleanup`

---

## ACP互联 API

### 1. 发现Agents

**端点**: `POST /api/acp/discover`

**请求体**:
```json
{
  "timeout": 5.0
}
```

**响应示例**:
```json
{
  "status": "success",
  "agents": [
    {
      "agent_id": "agent-1",
      "name": "Agent 1",
      "host": "192.168.1.100",
      "port": 8001,
      "status": "online"
    }
  ],
  "scanned_count": 1,
  "message": "发现 1 个Agents"
}
```

### 2. 注册Agent

**端点**: `POST /api/acp/agents`

**请求体**:
```json
{
  "agent_id": "agent-1",
  "name": "Agent 1",
  "host": "192.168.1.100",
  "port": 8001,
  "capabilities": ["chat", "tools"],
  "metadata": {}
}
```

### 3. 获取Agent列表

**端点**: `GET /api/acp/agents`

### 4. 获取Agent详情

**端点**: `GET /api/acp/agents/{agent_id}`

### 5. 更新Agent

**端点**: `PUT /api/acp/agents/{agent_id}`

### 6. 删除Agent

**端点**: `DELETE /api/acp/agents/{agent_id}`

### 7. 连接管理

**列出连接**: `GET /api/acp/connections`

**创建连接**: `POST /api/acp/connections`

**删除连接**: `DELETE /api/acp/connections/{connection_id}`

### 8. 群组管理

**创建群组**: `POST /api/acp/groups`

**请求体**:
```json
{
  "name": "开发组",
  "description": "开发团队群组",
  "max_members": 50
}
```

**获取群组列表**: `GET /api/acp/groups`

**获取群组详情**: `GET /api/acp/groups/{group_id}`

**加入群组**: `POST /api/acp/groups/join`

**退出群组**: `POST /api/acp/groups/leave`

**删除群组**: `DELETE /api/acp/groups/{group_id}`

### 9. 消息传递

**发送点对点消息**: `POST /api/acp/messages/p2p`

**请求体**:
```json
{
  "to_agent_id": "agent-2",
  "content": {
    "text": "你好"
  },
  "msg_type": "chat"
}
```

**发送群组消息**: `POST /api/acp/messages/group`

**获取消息列表**: `GET /api/acp/messages`

---

## 工具管理 API

### 1. 列出工具

**端点**: `GET /api/tools`

**参数**:
- `enabled_only` (boolean, 可选): 是否只返回启用的工具，默认为true

**响应示例**:
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
          "query": {
            "type": "string",
            "description": "搜索关键词"
          }
        }
      },
      "enabled": true,
      "category": "web",
      "tags": ["search"]
    }
  ],
  "statistics": {
    "total_tools": 10,
    "enabled_tools": 8,
    "disabled_tools": 2
  }
}
```

### 2. 注册工具

**端点**: `POST /api/tools`

**请求体**:
```json
{
  "name": "search_web",
  "description": "搜索网络",
  "parameters": {
    "type": "object",
    "properties": {
      "query": {
        "type": "string",
        "description": "搜索关键词"
      }
    }
  },
  "enabled": true,
  "version": "1.0.0",
  "category": "web",
  "tags": ["search"],
  "examples": ["搜索Python教程"]
}
```

### 3. 获取工具详情

**端点**: `GET /api/tools/{name}`

### 4. 删除工具

**端点**: `DELETE /api/tools/{name}`

### 5. 调用工具

**端点**: `POST /api/tools/call`

**请求体**:
```json
{
  "name": "search_web",
  "arguments": {
    "query": "Python教程"
  }
}
```

**响应示例**:
```json
{
  "success": true,
  "result": {
    "results": [...]
  },
  "call_count": 5,
  "last_called": "2026-02-06T10:00:00"
}
```

### 6. 获取OpenAI格式工具列表

**端点**: `GET /api/tools/openai`

**响应示例**:
```json
{
  "status": "success",
  "functions": [
    {
      "name": "search_web",
      "description": "搜索网络",
      "parameters": {
        "type": "object",
        "properties": {
          "query": {
            "type": "string",
            "description": "搜索关键词"
          }
        }
      }
    }
  ]
}
```

### 7. 工具统计

**端点**: `GET /api/tools/stats`

### 8. 工具导入/导出

**导出工具**: `POST /api/tools/export`

**导入工具**: `POST /api/tools/import`

---

## MCP工具管理 API

### 1. 列出MCP服务器

**端点**: `GET /api/tools/mcp/servers`

**响应示例**:
```json
{
  "status": "success",
  "servers": [
    {
      "name": "filesystem",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/files"],
      "env": {},
      "status": "connected",
      "tools": [
        {
          "name": "read_file",
          "description": "读取文件"
        }
      ],
      "last_check": "2026-02-06T10:00:00"
    }
  ],
  "statistics": {
    "total_servers": 1,
    "connected_servers": 1,
    "disconnected_servers": 0,
    "error_servers": 0
  }
}
```

### 2. 添加MCP服务器

**端点**: `POST /api/tools/mcp/servers`

**请求体**:
```json
{
  "name": "filesystem",
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/files"],
  "env": {}
}
```

### 3. 移除MCP服务器

**端点**: `DELETE /api/tools/mcp/servers/{name}`

### 4. 启动MCP服务器

**端点**: `POST /api/tools/mcp/servers/start`

**请求体**:
```json
{
  "name": "filesystem"
}
```

### 5. 停止MCP服务器

**端点**: `POST /api/tools/mcp/servers/stop`

**请求体**:
```json
{
  "name": "filesystem"
}
```

### 6. 检查MCP服务器健康状态

**端点**: `GET /api/tools/mcp/servers/{name}/health`

**响应示例**:
```json
{
  "status": "success",
  "health": {
    "name": "filesystem",
    "status": "connected",
    "last_check": "2026-02-06T10:00:00",
    "error": null
  }
}
```

### 7. 获取MCP服务器工具

**端点**: `GET /api/tools/mcp/servers/{name}/tools`

### 8. 调用MCP工具

**端点**: `POST /api/tools/mcp/call`

**请求体**:
```json
{
  "server_name": "filesystem",
  "tool_name": "read_file",
  "arguments": {
    "path": "/path/to/file.txt"
  }
}
```

### 9. 同步MCP工具

**端点**: `POST /api/tools/mcp/sync`

**参数**:
- `name` (string): 服务器名称

---

## 聊天 API

### 1. 发送消息

**端点**: `POST /api/chat`

**请求体**:
```json
{
  "message": "你好",
  "agent_id": "default",
  "stream": false,
  "images": null
}
```

**参数说明**:
- `message` (string, 必需): 用户消息
- `agent_id` (string, 可选): Agent ID，默认为 "default"
- `stream` (boolean, 可选): 是否流式响应，默认为 true
- `images` (array, 可选): base64编码的图片列表（多模态支持）

**响应示例**:
```json
{
  "status": "success",
  "response": "你好！有什么我可以帮助你的吗？",
  "session_id": "agent-default",
  "tokens_used": 150
}
```

### 2. 流式聊天

**端点**: `POST /api/chat/stream`

**请求体**: 同`POST /api/chat`

**响应**: Server-Sent Events (SSE) 流

**事件类型**:
- `session`: 会话信息
- `thinking`: 思考过程（如模型支持）
- `content`: 内容片段
- `tool_call`: 工具调用
- `tool_start`: 工具开始执行
- `tool_result`: 工具执行结果
- `done`: 完成
- `error`: 错误

### 3. 获取聊天历史

**端点**: `GET /api/chat/history/{session_id}`

**参数**:
- `limit` (integer, 可选): 返回消息数量限制，默认50

**响应示例**:
```json
{
  "status": "success",
  "session_id": "agent-default",
  "session": {
    "id": "agent-default",
    "title": "默认助手的对话",
    "message_count": 10
  },
  "messages": [
    {"role": "user", "content": "你好"},
    {"role": "assistant", "content": "你好！有什么我可以帮助你的吗？"}
  ]
}
```

### 4. 记忆管理模型聊天

**端点**: `POST /api/memory-agent/chat/stream`

**请求体**:
```json
{
  "message": "帮我搜索关于编程的记忆"
}
```

**说明**: 专门用于记忆管理的流式聊天接口，使用 memory-agent 配置，支持16个记忆管理工具。

---

## Agent 管理 API

### 1. 获取Agent列表

**端点**: `GET /api/agents`

**响应示例**:
```json
[
  {
    "id": "default",
    "name": "默认助手",
    "description": "通用AI助手",
    "system_prompt": "你是一个有帮助的AI助手...",
    "model": "main",
    "temperature": 0.7,
    "max_tokens": 131072,
    "use_memory": true,
    "use_tools": true,
    "memory_scene": "chat",
    "is_default": true
  },
  {
    "id": "memory-agent",
    "name": "记忆管理助手",
    "description": "专业的记忆管理助手",
    "model": "memory",
    "temperature": 0.3,
    "max_tokens": 131072,
    "use_memory": false,
    "use_tools": true
  }
]
```

### 2. 创建Agent

**端点**: `POST /api/agents`

**请求体**:
```json
{
  "name": "自定义助手",
  "description": "我的自定义助手",
  "system_prompt": "你是一个专业的编程助手...",
  "model": "main",
  "temperature": 0.7,
  "max_tokens": 4096,
  "use_memory": true,
  "use_tools": true,
  "memory_scene": "chat",
  "vision_enabled": false
}
```

### 3. 获取Agent详情

**端点**: `GET /api/agents/{agent_id}`

### 4. 更新Agent

**端点**: `PUT /api/agents/{agent_id}`

### 5. 删除Agent

**端点**: `DELETE /api/agents/{agent_id}`

### 6. 克隆Agent

**端点**: `POST /api/agents/{agent_id}/clone`

### 7. 获取Agent统计

**端点**: `GET /api/agents/{agent_id}/stats`

**响应示例**:
```json
{
  "agent_id": "default",
  "session_count": 5,
  "total_messages": 120
}
```

### 8. 获取Agent上下文

**端点**: `GET /api/agents/{agent_id}/context`

**参数**:
- `limit` (integer, 可选): 返回消息数量限制，默认20

### 9. 清空Agent上下文

**端点**: `DELETE /api/agents/{agent_id}/context`

---

## 管理员 API

### 1. 系统健康检查

**端点**: `GET /api/admin/health`

**响应示例**:
```json
{
  "status": "success",
  "health": {
    "database": "ok",
    "vector_store": "ok",
    "llm": "ok",
    "acp": "ok"
  }
}
```

### 2. 系统统计

**端点**: `GET /api/admin/stats`

**响应示例**:
```json
{
  "status": "success",
  "stats": {
    "total_memories": 100,
    "total_sessions": 50,
    "total_agents": 5,
    "total_tools": 10,
    "uptime": 3600
  }
}
```

### 3. 日志查询

**端点**: `GET /api/admin/logs`

**参数**:
- `level` (string, 可选): 日志级别（DEBUG, INFO, WARNING, ERROR）
- `limit` (integer, 可选): 返回数量限制

### 4. 备份数据

**端点**: `POST /api/admin/backup`

### 5. 恢复数据

**端点**: `POST /api/admin/restore`

---

## 错误码说明

| 错误码 | 说明 |
|--------|------|
| 200 | 请求成功 |
| 400 | 请求参数错误 |
| 404 | 资源不存在 |
| 500 | 服务器内部错误 |
| 503 | 服务不可用 |

---

## 注意事项

1. **认证**: 当前版本未实现认证，生产环境请配置API密钥
2. **CORS**: 默认允许所有来源，生产环境请限制CORS来源
3. **速率限制**: 当前未实现速率限制，建议生产环境配置
4. **数据持久化**: 使用SQLite数据库，生产环境建议使用PostgreSQL
5. **向量搜索**: 支持Milvus Lite和Qdrant，根据配置选择

---

## 示例代码

### Python示例

```python
import httpx

async def create_memory():
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:8000/api/memories",
            json={
                "content": "用户喜欢编程",
                "type": "long_term",
                "importance": 3,
                "tags": ["编程", "爱好"]
            }
        )
        return response.json()

result = await create_memory()
print(result)
```

### JavaScript示例

```javascript
async function createMemory() {
  const response = await fetch('http://localhost:8000/api/memories', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      content: '用户喜欢编程',
      type: 'long_term',
      importance: 3,
      tags: ['编程', '爱好']
    })
  });
  return await response.json();
}

createMemory().then(result => console.log(result));
```
