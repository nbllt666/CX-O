# CX-O API 文档

## 概述

CX-O 提供了完整的 RESTful API 和 WebSocket API，支持智能对话、记忆管理、知识图谱、Agent互联、工具调用等功能。

**基础信息：**
- 基础URL: `http://localhost:8000/api`
- 认证方式: 无需认证（开发环境）
- 响应格式: JSON
- API版本: v1.0.0

**健康检查：**
```http
GET /health
```

返回示例：
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "components": {
    "memory_manager": true,
    "context_manager": true,
    "acp_manager": true,
    "llm_client": true,
    "model_router": true
  }
}
```

---

## 目录

1. [聊天 API](#聊天-api)
2. [记忆管理 API](#记忆管理-api)
3. [上下文管理 API](#上下文管理-api)
4. [Agent 管理 API](#agent-管理-api)
5. [ACP 协议 API](#acp-协议-api)
6. [知识图谱 API](#知识图谱-api)
7. [工具管理 API](#工具管理-api)
8. [音频处理 API](#音频处理-api)
9. [配置管理 API](#配置管理-api)
10. [统计信息 API](#统计信息-api)
11. [WebSocket API](#websocket-api)

---

## 聊天 API

### 1. 非流式聊天

**POST** `/api/chat`

与指定 Agent 进行非流式对话。

**请求体：**
```json
{
  "message": "你好",
  "agent_id": "default",
  "stream": false,
  "images": []
}
```

**参数说明：**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| message | string | 是 | 用户消息内容 |
| agent_id | string | 否 | Agent ID，默认 "default" |
| stream | boolean | 否 | 是否流式响应，默认 false |
| images | array | 否 | Base64 编码的图片列表 |

**响应示例：**
```json
{
  "status": "success",
  "response": "你好！我是AI助手，有什么可以帮助你的吗？",
  "session_id": "agent-default",
  "tokens_used": 150
}
```

### 2. 流式聊天

**POST** `/api/chat/stream`

与指定 Agent 进行流式对话，支持实时返回响应。

**请求体：**
```json
{
  "message": "讲一个故事",
  "agent_id": "default",
  "stream": true
}
```

**响应格式：** Server-Sent Events (SSE)

**事件类型：**
- `session`: 会话信息
- `content`: 内容片段
- `thinking`: 思考过程
- `tool_call`: 工具调用
- `tool_result`: 工具结果
- `done`: 完成
- `error`: 错误

**响应示例：**
```
data: {"type": "session", "session_id": "agent-default"}

data: {"type": "content", "content": "很久很久以前..."}

data: {"type": "done", "session_id": "agent-default"}
```

### 3. 获取聊天历史

**GET** `/api/chat/history/{session_id}`

获取指定会话的聊天历史。

**路径参数：**
- `session_id`: 会话ID

**查询参数：**
- `limit`: 返回消息数量，默认 50

**响应示例：**
```json
{
  "status": "success",
  "session_id": "agent-default",
  "session": {
    "id": "agent-default",
    "title": "默认助手的对话",
    "created_at": "2024-01-01T00:00:00"
  },
  "messages": [
    {
      "id": 1,
      "role": "user",
      "content": "你好",
      "created_at": "2024-01-01T00:00:00"
    },
    {
      "id": 2,
      "role": "assistant",
      "content": "你好！有什么可以帮助你的吗？",
      "created_at": "2024-01-01T00:00:01"
    }
  ]
}
```

### 4. 记忆管理模型流式聊天

**POST** `/api/memory-agent/chat/stream`

与记忆管理 Agent 进行流式对话，专门用于记忆管理操作。

**请求体：**
```json
{
  "message": "帮我搜索关于咖啡的记忆"
}
```

**响应格式：** Server-Sent Events (SSE)

---

## 记忆管理 API

### 1. 列出记忆

**GET** `/api/memories`

获取记忆列表。

**查询参数：**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| workspace_id | string | 否 | 工作区ID，默认 "default" |
| type | string | 否 | 记忆类型：short_term/long_term/permanent |
| limit | integer | 否 | 返回数量，默认 20 |
| offset | integer | 否 | 偏移量，默认 0 |
| agent_id | string | 否 | Agent ID，默认 "default" |

**响应示例：**
```json
{
  "status": "success",
  "memories": [
    {
      "id": 1,
      "content": "用户喜欢喝咖啡",
      "type": "long_term",
      "importance": 4,
      "tags": ["preference", "coffee"],
      "created_at": "2024-01-01T00:00:00",
      "emotion_score": 0.3
    }
  ],
  "total": 1
}
```

### 2. 创建记忆

**POST** `/api/memories`

创建新的记忆。

**请求体：**
```json
{
  "content": "用户喜欢喝咖啡，特别是拿铁",
  "type": "long_term",
  "importance": 4,
  "tags": ["preference", "coffee"],
  "metadata": {},
  "permanent": false,
  "workspace_id": "default"
}
```

**响应示例：**
```json
{
  "status": "success",
  "memory_id": 123,
  "message": "记忆创建成功"
}
```

### 3. 获取单条记忆

**GET** `/api/memories/{memory_id}`

获取指定记忆详情。

**响应示例：**
```json
{
  "status": "success",
  "memory": {
    "id": 123,
    "content": "用户喜欢喝咖啡，特别是拿铁",
    "type": "long_term",
    "importance": 4,
    "tags": ["preference", "coffee"],
    "created_at": "2024-01-01T00:00:00",
    "updated_at": "2024-01-01T00:00:00"
  }
}
```

### 4. 更新记忆

**PUT** `/api/memories/{memory_id}`

更新指定记忆。

**请求体：**
```json
{
  "content": "用户喜欢喝咖啡，特别是拿铁和美式",
  "importance": 5,
  "tags": ["preference", "coffee", "updated"]
}
```

### 5. 删除记忆

**DELETE** `/api/memories/{memory_id}`

删除指定记忆。

**查询参数：**
- `soft_delete`: 是否软删除，默认 false

### 6. 搜索记忆

**POST** `/api/memories/search`

搜索记忆。

**请求体：**
```json
{
  "query": "咖啡",
  "type": "long_term",
  "tags": ["preference"],
  "limit": 10,
  "workspace_id": "default"
}
```

### 7. RAG 搜索

**POST** `/api/memories/rag`

使用 RAG（检索增强生成）搜索记忆。

**查询参数：**
- `query`: 搜索查询
- `workspace_id`: 工作区ID，默认 "default"
- `limit`: 返回数量，默认 5

### 8. 语义搜索

**POST** `/api/memories/semantic-search`

基于向量相似度的语义搜索。

**请求体：**
```json
{
  "query": "用户喜欢什么饮料",
  "limit": 10,
  "threshold": 0.7,
  "workspace_id": "default"
}
```

### 9. 三维评分搜索

**POST** `/api/memories/3d`

使用三维评分模型搜索记忆（重要性 + 时间 + 相关性）。

**请求体：**
```json
{
  "query": "咖啡",
  "memory_type": "long_term",
  "tags": [],
  "limit": 10,
  "weights": [0.35, 0.25, 0.4],
  "workspace_id": "default"
}
```

### 10. 召回记忆

**POST** `/api/memories/recall/{memory_id}`

召回记忆，提升记忆时间分数。

**查询参数：**
- `emotion_intensity`: 情感强度，默认 0.0

### 11. 批量操作

#### 批量写入
**POST** `/api/memories/batch/write`

**请求体：**
```json
[
  {
    "content": "记忆1",
    "type": "long_term",
    "importance": 3
  },
  {
    "content": "记忆2",
    "type": "long_term",
    "importance": 4
  }
]
```

#### 批量更新
**POST** `/api/memories/batch/update`

**请求体：**
```json
{
  "ids": [1, 2, 3],
  "data": {
    "tags": ["batch_updated"]
  },
  "agent_id": "default"
}
```

#### 批量删除
**POST** `/api/memories/batch/delete`

**请求体：**
```json
{
  "ids": [1, 2, 3],
  "agent_id": "default"
}
```

**查询参数：**
- `soft_delete`: 是否软删除，默认 false

#### 批量归档
**POST** `/api/memories/batch/archive`

#### 批量恢复
**POST** `/api/memories/batch/restore`

### 12. 永久记忆

#### 创建永久记忆
**POST** `/api/memories/permanent`

**请求体：**
```json
{
  "content": "用户的生日是1月1日",
  "tags": ["birthday", "important"],
  "metadata": {},
  "emotion_score": 0.8,
  "source": "user"
}
```

#### 获取永久记忆列表
**GET** `/api/memories/permanent`

#### 获取单条永久记忆
**GET** `/api/memories/permanent/{memory_id}`

#### 更新永久记忆
**PUT** `/api/memories/permanent/{memory_id}`

#### 删除永久记忆
**DELETE** `/api/memories/permanent/{memory_id}`

### 13. 记忆统计

**GET** `/api/memories/stats`

获取记忆统计信息。

**查询参数：**
- `workspace_id`: 工作区ID，默认 "default"

**响应示例：**
```json
{
  "status": "success",
  "statistics": {
    "total_memories": 100,
    "by_type": {
      "short_term": 20,
      "long_term": 75,
      "permanent": 5
    },
    "by_importance": {
      "1": 10,
      "2": 20,
      "3": 40,
      "4": 20,
      "5": 10
    }
  }
}
```

### 14. 获取 Agent 记忆表列表

**GET** `/api/memories/agents`

获取所有 Agent 的记忆表列表。

### 15. 向量数据库状态

**GET** `/api/memories/vectors/status`

获取向量数据库状态信息。

---

## 上下文管理 API

### 1. 列出会话

**GET** `/api/context/sessions`

获取会话列表。

**查询参数：**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| workspace_id | string | 否 | 工作区ID，默认 "default" |
| limit | integer | 否 | 返回数量，默认 20 |
| active_only | boolean | 否 | 仅活跃会话，默认 true |

### 2. 创建会话

**POST** `/api/context/sessions`

**请求体：**
```json
{
  "workspace_id": "default",
  "title": "新对话",
  "metadata": {}
}
```

### 3. 获取会话

**GET** `/api/context/sessions/{session_id}`

### 4. 删除会话

**DELETE** `/api/context/sessions/{session_id}`

### 5. 清空所有会话

**DELETE** `/api/context/sessions/all`

### 6. 获取消息列表

**GET** `/api/context/messages/{session_id}`

**查询参数：**
- `limit`: 返回数量，默认 50
- `offset`: 偏移量，默认 0

### 7. 添加消息

**POST** `/api/context/messages`

**请求体：**
```json
{
  "session_id": "session-123",
  "role": "user",
  "content": "你好",
  "content_type": "text",
  "metadata": {}
}
```

### 8. 生成摘要

**POST** `/api/context/summary`

使用摘要模型生成对话摘要和报告。

**查询参数：**
- `session_id`: 会话ID
- `max_points`: 最大要点数，默认 5
- `save_as_memory`: 是否保存为记忆，默认 true

**响应示例：**
```json
{
  "status": "success",
  "conversation_id": "session-123",
  "summary_memory_id": 456,
  "key_points": [
    {
      "content": "讨论了咖啡偏好",
      "importance": "high",
      "participants": ["user"]
    }
  ],
  "report": {
    "topic": "咖啡偏好讨论",
    "participants": ["user", "assistant"],
    "message_count": 10,
    "main_discussion": "用户表达了对咖啡的偏好...",
    "sentiment": "positive"
  }
}
```

### 9. 获取统计信息

**GET** `/api/context/stats`

---

## Agent 管理 API

### 1. 获取所有 Agent

**GET** `/api/agents`

获取系统中所有 Agent 的配置列表。

**响应示例：**
```json
{
  "status": "success",
  "agents": [
    {
      "id": "default",
      "name": "默认助手",
      "description": "通用AI助手",
      "model": "main",
      "temperature": 0.7,
      "max_tokens": 131072,
      "use_memory": true,
      "use_tools": true,
      "is_default": true
    }
  ],
  "total": 1
}
```

### 2. 创建 Agent

**POST** `/api/agents`

**请求体：**
```json
{
  "name": "专业助手",
  "description": "专业的技术助手",
  "system_prompt": "你是一个专业的技术助手...",
  "model": "main",
  "temperature": 0.7,
  "max_tokens": 4096,
  "use_memory": true,
  "use_tools": true,
  "memory_scene": "chat",
  "vision_enabled": false
}
```

### 3. 获取单个 Agent

**GET** `/api/agents/{agent_id}`

### 4. 更新 Agent

**PUT** `/api/agents/{agent_id}`

**请求体：**
```json
{
  "name": "更新后的名称",
  "temperature": 0.8,
  "use_memory": false
}
```

### 5. 删除 Agent

**DELETE** `/api/agents/{agent_id}`

### 6. 克隆 Agent

**POST** `/api/agents/{agent_id}/clone`

### 7. 获取 Agent 统计

**GET** `/api/agents/{agent_id}/stats`

### 8. 获取 Agent 上下文

**GET** `/api/agents/{agent_id}/context`

**查询参数：**
- `limit`: 返回消息数量，默认 20

### 9. 清空 Agent 上下文

**DELETE** `/api/agents/{agent_id}/context`

---

## ACP 协议 API

ACP (Agent Communication Protocol) 用于 Agent 之间的互联和通信。

### 1. 发现 Agents

**POST** `/api/acp/discover`

发现网络中的其他 Agents。

**请求体：**
```json
{
  "timeout": 5.0
}
```

### 2. 列出 Agents

**GET** `/api/acp/agents`

**查询参数：**
- `online_only`: 仅在线 Agents，默认 false

### 3. 注册 Agent

**POST** `/api/acp/agents`

**请求体：**
```json
{
  "name": "My Agent",
  "description": "自定义 Agent",
  "capabilities": ["chat", "tools"],
  "host": "127.0.0.1",
  "port": 8080
}
```

### 4. 更新 Agent

**PATCH** `/api/acp/agents/{agent_id}`

### 5. 删除 Agent

**DELETE** `/api/acp/agents/{agent_id}`

### 6. 连接到 Agent

**POST** `/api/acp/connect`

**请求体：**
```json
{
  "agent_id": "remote-agent-123",
  "host": "192.168.1.100",
  "port": 8080
}
```

### 7. 断开连接

**DELETE** `/api/acp/connect/{connection_id}`

### 8. 列出连接

**GET** `/api/acp/connections`

**查询参数：**
- `local_only`: 仅本地连接，默认 true

### 9. 创建群组

**POST** `/api/acp/groups`

**请求体：**
```json
{
  "name": "开发团队",
  "description": "开发团队群组",
  "max_members": 50
}
```

### 10. 列出群组

**GET** `/api/acp/groups`

### 11. 加入群组

**POST** `/api/acp/groups/{group_id}/join`

### 12. 退出群组

**POST** `/api/acp/groups/{group_id}/leave`

### 13. 发送消息

**POST** `/api/acp/send`

**请求体：**
```json
{
  "to_agent_id": "agent-456",
  "content": {
    "text": "你好"
  },
  "msg_type": "chat"
}
```

### 14. 发送群组消息

**POST** `/api/acp/send/group`

**请求体：**
```json
{
  "group_id": "group-123",
  "content": {
    "text": "大家好"
  }
}
```

### 15. 获取消息

**GET** `/api/acp/messages`

**查询参数：**
- `agent_id`: Agent ID
- `group_id`: 群组 ID
- `limit`: 返回数量，默认 50

### 16. 获取 ACP 统计

**GET** `/api/acp/stats`

---

## 知识图谱 API

### 节点操作

#### 1. 创建节点

**POST** `/api/graph/nodes`

**请求体：**
```json
{
  "type": "person",
  "properties": {
    "name": "张三",
    "age": 30
  },
  "text_content": "张三是一名软件工程师"
}
```

#### 2. 获取节点

**GET** `/api/graph/nodes/{node_id}`

#### 3. 更新节点

**PUT** `/api/graph/nodes/{node_id}`

#### 4. 删除节点

**DELETE** `/api/graph/nodes/{node_id}`

**查询参数：**
- `cascade`: 是否级联删除关联边，默认 true

#### 5. 批量创建节点

**POST** `/api/graph/nodes/batch`

#### 6. 搜索节点

**GET** `/api/graph/nodes/search`

**查询参数：**
- `node_type`: 节点类型
- `limit`: 返回数量，默认 100
- `offset`: 偏移量，默认 0

#### 7. 获取邻居节点

**GET** `/api/graph/nodes/{node_id}/neighbors`

**查询参数：**
- `max_depth`: 最大深度，默认 1
- `direction`: 方向 (outgoing/incoming/both)，默认 both

### 边操作

#### 8. 创建边

**POST** `/api/graph/edges`

**请求体：**
```json
{
  "source_id": "node-1",
  "target_id": "node-2",
  "relation_type": "knows",
  "properties": {
    "since": "2020"
  },
  "text_content": "张三认识李四"
}
```

#### 9. 获取边

**GET** `/api/graph/edges/{edge_id}`

#### 10. 更新边

**PUT** `/api/graph/edges/{edge_id}`

#### 11. 删除边

**DELETE** `/api/graph/edges/{edge_id}`

#### 12. 搜索边

**GET** `/api/graph/edges/search`

### 图遍历

#### 13. BFS 遍历

**POST** `/api/graph/traverse/bfs`

**请求体：**
```json
{
  "start_id": "node-1",
  "max_depth": 3,
  "node_type_filter": "person"
}
```

#### 14. DFS 遍历

**POST** `/api/graph/traverse/dfs`

#### 15. 最短路径

**GET** `/api/graph/paths/shortest`

**查询参数：**
- `start_id`: 起始节点ID
- `end_id`: 目标节点ID
- `max_length`: 最大路径长度，默认 10

### 语义搜索

#### 16. 语义搜索

**POST** `/api/graph/semantic/search`

**请求体：**
```json
{
  "query": "软件工程师",
  "node_type": "person",
  "limit": 10
}
```

#### 17. 混合搜索

**POST** `/api/graph/semantic/hybrid`

**请求体：**
```json
{
  "query": "工程师",
  "node_type": "person",
  "properties_filter": {
    "age": {"$gt": 25}
  },
  "limit": 10
}
```

#### 18. 语义邻居

**GET** `/api/graph/semantic/neighbors/{node_id}`

**查询参数：**
- `limit`: 返回数量，默认 10
- `depth`: 深度，默认 1

### 图算法

#### 19. PageRank

**GET** `/api/graph/algorithm/pagerank`

**查询参数：**
- `damping`: 阻尼系数，默认 0.85
- `max_iterations`: 最大迭代次数，默认 100

#### 20. 重要节点

**GET** `/api/graph/algorithm/important-nodes`

**查询参数：**
- `limit`: 返回数量，默认 10

#### 21. 社区发现

**GET** `/api/graph/algorithm/communities`

**查询参数：**
- `method`: 算法 (lpa/louvain)，默认 lpa

### 其他

#### 22. 健康检查

**GET** `/api/graph/health`

#### 23. 性能指标

**GET** `/api/graph/metrics`

#### 24. 图统计

**GET** `/api/graph/stats`

#### 25. 导出 JSON

**GET** `/api/graph/export/json`

#### 26. 导出 GraphML

**GET** `/api/graph/export/graphml`

#### 27. 导出 DOT

**GET** `/api/graph/export/dot`

#### 28. 获取配置

**GET** `/api/graph/config`

---

## 工具管理 API

### 1. 列出工具

**GET** `/api/tools`

**查询参数：**
- `enabled_only`: 仅启用的工具，默认 true
- `include_builtin`: 包含内置工具，默认 false
- `category`: 按类别过滤

**响应示例：**
```json
{
  "status": "success",
  "tools": {
    "calculator": {
      "name": "calculator",
      "description": "数学计算工具",
      "type": "builtin",
      "status": "active",
      "category": "builtin"
    }
  },
  "statistics": {
    "total_tools": 10,
    "enabled_tools": 8,
    "disabled_tools": 2
  }
}
```

### 2. 注册工具

**POST** `/api/tools`

**请求体：**
```json
{
  "name": "my_tool",
  "description": "自定义工具",
  "parameters": {
    "type": "object",
    "properties": {
      "input": {
        "type": "string",
        "description": "输入参数"
      }
    },
    "required": ["input"]
  },
  "enabled": true,
  "category": "custom",
  "tags": ["utility"]
}
```

### 3. 获取工具

**GET** `/api/tools/{name}`

### 4. 更新工具

**PATCH** `/api/tools/{name}`

**请求体：**
```json
{
  "enabled": false,
  "description": "更新后的描述"
}
```

### 5. 删除工具

**DELETE** `/api/tools/{name}`

### 6. 调用工具

**POST** `/api/tools/call`

**请求体：**
```json
{
  "name": "calculator",
  "arguments": {
    "expression": "2 + 2"
  }
}
```

**响应示例：**
```json
{
  "success": true,
  "result": 4,
  "execution_time": 0.001
}
```

### 7. 测试工具

**POST** `/api/tools/{name}/test`

**请求体：**
```json
{
  "arguments": {
    "expression": "10 * 5"
  }
}
```

### 8. 获取 OpenAI 格式工具列表

**GET** `/api/tools/openai`

**查询参数：**
- `enabled_only`: 仅启用的工具，默认 true

### 9. 导出工具

**POST** `/api/tools/export`

### 10. 导入工具

**POST** `/api/tools/import`

**请求体：**
```json
[
  {
    "name": "tool1",
    "description": "工具1",
    "parameters": {}
  }
]
```

### 11. 获取工具统计

**GET** `/api/tools/stats`

### MCP (Model Context Protocol) 工具

#### 12. 列出 MCP 服务器

**GET** `/api/tools/mcp/servers`

#### 13. 添加 MCP 服务器

**POST** `/api/tools/mcp/servers`

**请求体：**
```json
{
  "name": "filesystem",
  "command": "mcp-filesystem",
  "args": ["/path/to/dir"],
  "env": {}
}
```

#### 14. 删除 MCP 服务器

**DELETE** `/api/tools/mcp/servers/{name}`

#### 15. 启动 MCP 服务器

**POST** `/api/tools/mcp/servers/start`

**请求体：**
```json
{
  "name": "filesystem"
}
```

#### 16. 停止 MCP 服务器

**POST** `/api/tools/mcp/servers/stop`

#### 17. 检查 MCP 服务器健康状态

**GET** `/api/tools/mcp/servers/{name}/health`

#### 18. 获取 MCP 服务器工具列表

**GET** `/api/tools/mcp/servers/{name}/tools`

#### 19. 调用 MCP 工具

**POST** `/api/tools/mcp/call`

**请求体：**
```json
{
  "server_name": "filesystem",
  "tool_name": "read_file",
  "arguments": {
    "path": "/path/to/file"
  }
}
```

#### 20. 同步 MCP 工具

**POST** `/api/tools/mcp/sync`

---

## 音频处理 API

### 1. 获取音频配置

**GET** `/api/audio/config`

### 2. 获取音频文件列表

**GET** `/api/audio/files`

**响应示例：**
```json
{
  "files": [
    {
      "name": "reference.wav",
      "size": 1024000,
      "modified": "2024-01-01T00:00:00"
    }
  ]
}
```

### 3. 上传音频文件

**POST** `/api/audio/upload`

**请求格式：** multipart/form-data

**字段：**
- `file`: 音频文件

### 4. 获取音频文件

**GET** `/api/audio/files/{filename}`

### 5. 删除音频文件

**DELETE** `/api/audio/files/{filename}`

### TTS (文本转语音)

#### 6. TTS 合成

**POST** `/api/tts/synthesize`

**请求体：**
```json
{
  "text": "你好，这是一段测试文本",
  "speed": 1.0,
  "cross_fade_duration": 0.15,
  "ref_audio": "reference.wav",
  "ref_text": "参考音频文本"
}
```

**响应示例：**
```json
{
  "status": "success",
  "audio_data": "base64编码的音频数据",
  "format": "wav"
}
```

#### 7. TTS 流式合成

**POST** `/api/tts/synthesize-stream`

**请求体：**
```json
{
  "text": "这是一段长文本...",
  "speed": 1.0
}
```

**响应格式：** Server-Sent Events (SSE)

### ASR (语音识别)

#### 8. ASR 语音识别

**POST** `/api/asr/speech-to-text`

**请求格式：** multipart/form-data 或 JSON

**字段：**
- `file`: 音频文件（multipart/form-data）
- `audio`: Base64 编码的音频数据（JSON）
- `language`: 语言，默认 "auto"

**响应示例：**
```json
{
  "status": "success",
  "text": "识别出的文本内容",
  "language": "zh"
}
```

---

## 配置管理 API

### 1. 获取统一配置

**GET** `/api/config`

**响应示例：**
```json
{
  "status": "success",
  "config": {
    "audio": {
      "ref_audio_path": "",
      "ref_text": "",
      "speed": 1.0
    },
    "vector": {
      "backend": "weaviate",
      "vector_size": 384
    },
    "llm": {
      "provider": "ollama",
      "model": "qwen2.5:latest",
      "host": "http://localhost:11434"
    },
    "system": {
      "debug": false,
      "log_level": "INFO"
    }
  }
}
```

### 2. 更新统一配置

**PUT** `/api/config`

**请求体：**
```json
{
  "section": "audio",
  "data": {
    "speed": 1.2,
    "emotion_enabled": true
  }
}
```

### 3. 获取音频配置

**GET** `/api/config/audio`

### 4. 更新音频配置

**POST** `/api/config/audio`

### 5. 获取服务配置

**GET** `/api/config/services`

### 6. 更新服务配置

**POST** `/api/config/services`

### 7. 更新 LLM 配置

**POST** `/api/config/llm`

### 8. 获取弹幕配置

**GET** `/api/danmaku/config`

### 9. 获取防火墙配置

**GET** `/api/firewall/config`

### 10. 获取 VAD 配置

**GET** `/api/vad/config`

### 11. 获取 SenseVoice Streaming 配置

**GET** `/api/config/sensevoice-streaming`

### 12. 更新 SenseVoice Streaming 配置

**POST** `/api/config/sensevoice-streaming`

### 13. 获取 Adaptive Polling 配置

**GET** `/api/config/adaptive-polling`

### 14. 更新 Adaptive Polling 配置

**POST** `/api/config/adaptive-polling`

---

## 统计信息 API

### 1. 获取系统统计

**GET** `/api/stats`

**响应示例：**
```json
{
  "status": "success",
  "data": {
    "total_memories": 100,
    "total_sessions": 10,
    "total_agents": 3,
    "archived_memories": 5
  }
}
```

---

## WebSocket API

WebSocket API 提供实时双向通信能力。

### 1. Agent WebSocket 端点

**WebSocket** `/api/ws/{agent_id}`

**路径参数：**
- `agent_id`: Agent ID

**查询参数：**
- `timeout`: 离线超时时间（秒），默认 60

**使用示例：**
```javascript
const ws = new WebSocket('ws://localhost:8000/api/ws/default?timeout=60');

ws.onopen = () => {
  console.log('WebSocket 已连接');
};

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log('收到消息:', data);
};

ws.send(JSON.stringify({
  type: 'chat',
  message: '你好'
}));
```

### 2. 通用 WebSocket 端点

**WebSocket** `/api/ws`

**查询参数：**
- `client_id`: 客户端ID（可选）
- `token`: 认证令牌（可选）

### 3. 聊天专用 WebSocket 端点

**WebSocket** `/api/ws/chat`

**查询参数：**
- `session_id`: 会话ID（可选）
- `agent_id`: Agent ID（可选，默认 default）

### 4. 直播专用 WebSocket 端点

**WebSocket** `/api/ws/live`

用于直播场景的实时通信，支持弹幕、音频流、TTS 同步等功能。

**查询参数：**
- `session_id`: 会话ID（可选）

**特性：**
- 支持二进制帧传输（音频数据，Opus/PCM 格式）
- 自动订阅到 "live" 频道接收广播消息
- 使用 `LiveClientHandler` 处理所有直播特有消息
- 支持 TTS 多客户端同步广播

**使用示例：**
```javascript
const ws = new WebSocket('ws://localhost:8000/api/ws/live');

ws.onopen = () => {
  ws.send(JSON.stringify({ type: 'init', data: { session_id: 'live-001' } }));
};

ws.onmessage = (event) => {
  if (event.data instanceof ArrayBuffer) {
    // 二进制音频帧
    return;
  }
  const data = JSON.parse(event.data);
  switch (data.type) {
    case 'danmaku':
      // 处理弹幕
      break;
    case 'tts_sync':
      // TTS 播放开始同步信号
      break;
    case 'tts_tick':
      // TTS 播放进度 tick（每100ms）
      break;
    case 'tts_end':
      // TTS 播放结束
      break;
  }
};

// 发送麦克风音频（二进制）
navigator.mediaDevices.getUserMedia({ audio: true }).then(stream => {
  const recorder = new MediaRecorder(stream);
  recorder.ondataavailable = (e) => { ws.send(e.data); };
  recorder.start(100);
});
```

**直播端点完整消息类型：**

| 类型 | 说明 | 方向 |
|------|------|------|
| init | 初始化连接 | 客户端 → 服务端 |
| danmaku | 弹幕消息 | 双向 |
| text | 文本消息 | 客户端 → 服务端 |
| gift | 礼物通知 | 双向 |
| enter | 用户进入通知 | 双向 |
| interrupt | 中断请求 | 客户端 → 服务端 |
| stop_tts | 停止 TTS | 客户端 → 服务端 |
| audio | 音频数据（二进制） | 客户端 → 服务端 |
| vad_status | 语音活动状态 | 服务端 → 客户端 |
| asr_result | ASR 识别结果 | 服务端 → 客户端 |
| stream/response | AI 回复内容 | 服务端 → 客户端 |
| tts_sync | TTS 播放同步信号 | 服务端 → 客户端（广播） |
| tts_tick | TTS 播放进度 tick | 服务端 → 客户端（广播，100ms间隔） |
| tts_end | TTS 播放结束 | 服务端 → 客户端（广播） |

### 直播前端路由结构

```
/live                    → 整合模式主页（虚拟形象+弹幕+字幕）
/live/split              → 拆分模式导航页（各 OBS 源 URL 说明）
/live/split/avatar       → 纯虚拟形象源（透明背景，1920×1080）
/live/split/danmaku      → 纯弹幕层源（透明背景，1920×1080）
/live/split/subtitle     → 纯字幕层源（透明背景，1920×1080）
/live/split/audio        → 音频控制面板（含 AEC、同步状态、音量控制）
```

### 消息格式

#### 客户端发送消息

```json
{
  "type": "chat",
  "message": "你好",
  "session_id": "session-123",
  "agent_id": "default"
}
```

#### 服务端推送消息

```json
{
  "type": "response",
  "content": "你好！有什么可以帮助你的吗？",
  "session_id": "session-123"
}
```

### 消息类型

| 类型 | 说明 | 方向 |
|------|------|------|
| chat | 聊天消息 | 客户端 → 服务端 |
| response | 响应消息 | 服务端 → 客户端 |
| stream | 流式响应 | 服务端 → 客户端 |
| tool_call | 工具调用 | 服务端 → 客户端 |
| tool_result | 工具结果 | 服务端 → 客户端 |
| error | 错误消息 | 服务端 → 客户端 |
| ping | 心跳检测 | 双向 |
| pong | 心跳响应 | 双向 |

---

## 错误处理

### 错误响应格式

```json
{
  "detail": "错误描述信息"
}
```

### 常见错误码

| 状态码 | 说明 |
|--------|------|
| 400 | 请求参数错误 |
| 404 | 资源不存在 |
| 500 | 服务器内部错误 |
| 503 | 服务不可用 |

---

## 速率限制

当前版本暂无速率限制。

---

## 版本控制

API 版本通过 URL 前缀控制，当前版本为 v1。

---

## 最佳实践

### 1. 使用流式响应

对于长时间运行的操作（如聊天、TTS合成），建议使用流式响应以获得更好的用户体验。

### 2. 合理使用记忆

- 重要信息使用永久记忆
- 一般信息使用长期记忆
- 临时信息使用短期记忆

### 3. Agent 配置

根据使用场景选择合适的 Agent：
- 通用对话：使用默认 Agent
- 记忆管理：使用 memory-agent
- 特定任务：创建自定义 Agent

### 4. 错误处理

始终检查响应状态，妥善处理错误情况。

### 5. WebSocket 连接

- 实现心跳机制保持连接
- 处理断线重连逻辑
- 合理设置超时时间

---

## 更新日志

### v1.0.0 (2024-01-01)
- 初始版本发布
- 支持完整的 REST API
- 支持 WebSocket 实时通信
- 集成记忆管理、知识图谱、ACP 协议等核心功能

---

## 联系方式

如有问题或建议，请通过以下方式联系：
- GitHub Issues: [项目地址]
- 文档: [文档地址]
