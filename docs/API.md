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
12. [CXFC 插件联邦 API](#cxfc-插件联邦-api)
13. [记忆归档 API](#记忆归档-api)
14. [向量数据库 API](#向量数据库-api)
15. [管理员 API](#管理员-api)
16. [Avatar 模型管理 API](#avatar-模型管理-api)
17. [备份管理 API](#备份管理-api)
18. [服务管理 API](#服务管理-api)
19. [记忆对话 API](#记忆对话-api)

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

### WebSocket Action 列表

WebSocket 消息中可通过 `action` 字段指定操作类型，以下是完整的 Action 列表：

#### 监控指标 Actions

| Action | 说明 |
|--------|------|
| metrics.get | 获取当前监控指标 |
| metrics.requests | 获取请求统计 |
| metrics.history | 获取历史监控数据 |

**请求示例：**
```json
{
  "type": "action",
  "action": "metrics.get"
}
```

**响应示例：**
```json
{
  "type": "action_result",
  "action": "metrics.get",
  "data": {
    "cpu_usage": 45.2,
    "memory_usage": 62.1,
    "active_connections": 5
  }
}
```

#### 插件管理 Actions

| Action | 说明 |
|--------|------|
| plugin.register | 注册插件 |
| plugin.heartbeat | 插件心跳上报 |
| plugin.list | 列出已注册插件 |
| plugin.unregister | 注销插件 |

**请求示例：**
```json
{
  "type": "action",
  "action": "plugin.register",
  "data": {
    "name": "my-plugin",
    "port": 9001,
    "skills": ["skill1", "skill2"]
  }
}
```

#### 系统管理 Actions

| Action | 说明 |
|--------|------|
| system.health | 系统健康检查 |
| system.status | 获取系统状态 |
| system.info | 获取系统信息 |

**请求示例：**
```json
{
  "type": "action",
  "action": "system.health"
}
```

**响应示例：**
```json
{
  "type": "action_result",
  "action": "system.health",
  "data": {
    "status": "healthy",
    "uptime": 86400,
    "version": "1.0.0"
  }
}
```

#### MCP 协议 Actions

| Action | 说明 |
|--------|------|
| mcp.connect | 连接 MCP 服务器 |
| mcp.disconnect | 断开 MCP 服务器 |
| mcp.tools | 获取 MCP 工具列表 |
| mcp.call | 调用 MCP 工具 |
| mcp.status | 获取 MCP 状态 |

**请求示例：**
```json
{
  "type": "action",
  "action": "mcp.call",
  "data": {
    "server_name": "filesystem",
    "tool_name": "read_file",
    "arguments": {"path": "/tmp/test.txt"}
  }
}
```

#### 情感/特效 Actions

| Action | 说明 |
|--------|------|
| emotions.list | 列出可用情感 |
| emotions.parse | 解析文本情感 |
| effects.list | 列出可用特效 |
| effects.parse | 解析特效参数 |

**请求示例：**
```json
{
  "type": "action",
  "action": "emotions.parse",
  "data": {
    "text": "今天真是太开心了！"
  }
}
```

**响应示例：**
```json
{
  "type": "action_result",
  "action": "emotions.parse",
  "data": {
    "emotion": "happy",
    "intensity": 0.85,
    "suggested_effects": ["sparkle", "bounce"]
  }
}
```

---

## CXFC 插件联邦 API

CXFC (CX-O Federation Connector) 插件联邦协议，用于插件的注册、发现、连接和生命周期管理。

源文件：`server/api/routers/cxfc.py`，路由前缀 `/api`

### 1. 注册插件

**POST** `/api/cxfc/register`

注册插件到 CXFC 联邦。

**请求体：** `CXFCRegisterRequest`
```json
{
  "name": "my-plugin",
  "description": "我的自定义插件",
  "host": "127.0.0.1",
  "port": 9001,
  "skills": ["skill1", "skill2"],
  "version": "1.0.0"
}
```

**响应示例：**
```json
{
  "status": "success",
  "plugin_id": "plugin-abc123",
  "message": "插件注册成功"
}
```

### 2. 插件心跳上报

**POST** `/api/cxfc/heartbeat`

插件定期上报心跳以维持在线状态。

**请求体：** `CXFCHeartbeatRequest`
```json
{
  "plugin_id": "plugin-abc123",
  "port": 9001
}
```

**响应示例：**
```json
{
  "status": "success",
  "message": "心跳已更新"
}
```

### 3. 推送事件

**POST** `/api/cxfc/event/push`

推送事件到 CXFC 管理器。

**请求体：** `CXFCEvent`
```json
{
  "event_type": "data_update",
  "source": "plugin-abc123",
  "data": {
    "key": "value"
  }
}
```

**响应示例：**
```json
{
  "status": "success",
  "message": "事件已推送"
}
```

### 4. 发现已注册插件

**GET** `/api/cxfc/discover`

发现已注册插件列表。

**查询参数：**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| scan | boolean | 否 | 设为 true 时同时扫描网络中的插件，默认 false |

**响应示例：**
```json
{
  "status": "success",
  "plugins": [
    {
      "plugin_id": "plugin-abc123",
      "name": "my-plugin",
      "host": "127.0.0.1",
      "port": 9001,
      "status": "online",
      "skills": ["skill1", "skill2"]
    }
  ]
}
```

### 5. 获取 CXFC Skills 列表

**GET** `/api/cxfc/skills`

获取所有已注册的 CXFC Skills 列表。

**响应示例：**
```json
{
  "status": "success",
  "skills": [
    {
      "name": "skill1",
      "description": "技能描述",
      "plugin_id": "plugin-abc123"
    }
  ]
}
```

### 6. 主动连接到指定插件

**POST** `/api/cxfc/connect`

主动连接到指定插件。

**请求体：** `CXFCConnectRequest`
```json
{
  "host": "192.168.1.100",
  "port": 9001
}
```

**响应示例：**
```json
{
  "status": "success",
  "plugin_id": "plugin-xyz789",
  "message": "连接成功"
}
```

### 7. 断开并移除指定插件

**DELETE** `/api/cxfc/plugins/{plugin_id}`

断开并移除指定插件。

**路径参数：**
- `plugin_id`: 插件ID

**响应示例：**
```json
{
  "status": "success",
  "message": "插件已断开并移除"
}
```

### 8. 列出所有已注册插件

**GET** `/api/cxfc/plugins`

列出所有已注册插件。

**响应示例：**
```json
{
  "status": "success",
  "plugins": [
    {
      "plugin_id": "plugin-abc123",
      "name": "my-plugin",
      "host": "127.0.0.1",
      "port": 9001,
      "status": "online",
      "last_heartbeat": "2024-01-01T00:00:00"
    }
  ],
  "total": 1
}
```

### 9. 刷新指定插件

**POST** `/api/cxfc/plugins/{plugin_id}/refresh`

刷新指定插件的连接状态和 Skill 信息。

**路径参数：**
- `plugin_id`: 插件ID

**响应示例：**
```json
{
  "status": "success",
  "plugin_id": "plugin-abc123",
  "message": "插件信息已刷新",
  "skills": ["skill1", "skill2"]
}
```

---

## 记忆归档 API

提供记忆的归档、合并、去重等高级管理功能。

源文件：`server/api/routers/archive.py`，路由前缀 `/api`

### 1. 归档单个记忆

**POST** `/api/archive/memory`

归档单个记忆到指定层级。

**请求体：**
```json
{
  "memory_id": 123,
  "target_level": 2,
  "compress": true
}
```

**参数说明：**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| memory_id | integer | 是 | 要归档的记忆ID |
| target_level | integer | 是 | 目标归档层级 |
| compress | boolean | 否 | 是否压缩，默认 true |

**响应示例：**
```json
{
  "status": "success",
  "message": "记忆已归档",
  "archive_id": 456,
  "target_level": 2
}
```

### 2. 合并重复记忆

**POST** `/api/archive/merge`

合并重复记忆为一条。

**请求体：**
```json
{
  "memory_ids": [1, 2, 3],
  "strategy": "smart"
}
```

**参数说明：**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| memory_ids | array | 是 | 要合并的记忆ID列表，至少2个 |
| strategy | string | 否 | 合并策略：smart（智能合并）/ simple（简单合并），默认 smart |

**响应示例：**
```json
{
  "status": "success",
  "message": "记忆已合并",
  "merged_memory_id": 999,
  "source_count": 3
}
```

### 3. 检测重复记忆

**POST** `/api/archive/deduplicate`

检测重复记忆，返回相似记忆组。

**请求体：**
```json
{
  "memory_ids": [1, 2, 3, 4, 5],
  "threshold": 0.85
}
```

**参数说明：**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| memory_ids | array | 否 | 指定检测范围，为空则检测全部 |
| threshold | float | 否 | 相似度阈值，默认使用全局阈值 |

**响应示例：**
```json
{
  "status": "success",
  "duplicate_groups": [
    {
      "group_id": 1,
      "memory_ids": [1, 3],
      "similarity": 0.92
    }
  ],
  "total_groups": 1
}
```

### 4. 获取去重组列表

**GET** `/api/archive/duplicates`

获取所有去重组列表。

**响应示例：**
```json
{
  "status": "success",
  "groups": [
    {
      "group_id": 1,
      "memory_ids": [1, 3],
      "similarity": 0.92,
      "suggested_action": "merge"
    }
  ]
}
```

### 5. 归档的归档（二次压缩）

**POST** `/api/archive/of-archives`

对已归档的记忆进行二次压缩。

**请求体：**
```json
{
  "target_level": 4
}
```

**参数说明：**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| target_level | integer | 否 | 目标层级，默认 4 |

**响应示例：**
```json
{
  "status": "success",
  "message": "二次归档完成",
  "archived_count": 15,
  "target_level": 4
}
```

### 6. 获取归档统计信息

**GET** `/api/archive/stats`

获取归档统计信息。

**响应示例：**
```json
{
  "status": "success",
  "statistics": {
    "total_archived": 50,
    "by_level": {
      "1": 10,
      "2": 20,
      "3": 15,
      "4": 5
    },
    "total_merged": 8,
    "space_saved": "35%"
  }
}
```

### 7. 获取归档层级定义

**GET** `/api/archive/levels`

获取归档层级定义。

**响应示例：**
```json
{
  "status": "success",
  "levels": [
    {
      "level": 1,
      "name": "轻度归档",
      "compression_ratio": 0.8,
      "max_retention_days": 90
    },
    {
      "level": 2,
      "name": "中度归档",
      "compression_ratio": 0.6,
      "max_retention_days": 180
    },
    {
      "level": 3,
      "name": "深度归档",
      "compression_ratio": 0.4,
      "max_retention_days": 365
    },
    {
      "level": 4,
      "name": "极限压缩",
      "compression_ratio": 0.2,
      "max_retention_days": null
    }
  ]
}
```

### 8. 设置去重相似度阈值

**POST** `/api/archive/threshold`

设置去重相似度阈值。

**请求体：**
```json
{
  "threshold": 0.85
}
```

**参数说明：**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| threshold | float | 是 | 相似度阈值，范围 0.5~1.0 |

**响应示例：**
```json
{
  "status": "success",
  "threshold": 0.85,
  "message": "阈值已更新"
}
```

### 9. 获取当前去重相似度阈值

**GET** `/api/archive/threshold`

获取当前去重相似度阈值。

**响应示例：**
```json
{
  "status": "success",
  "threshold": 0.85
}
```

### 10. 自动归档处理

**POST** `/api/archive/auto-process`

自动归档处理：归档旧记忆并合并重复项。

**查询参数：**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| min_age_days | integer | 否 | 最小记忆天数，默认 30 |
| target_level | integer | 否 | 目标归档层级，默认 2 |
| auto_merge | boolean | 否 | 是否自动合并重复项，默认 false |

**响应示例：**
```json
{
  "status": "success",
  "archived_count": 25,
  "merged_count": 5,
  "target_level": 2,
  "message": "自动归档处理完成"
}
```

---

## 向量数据库 API

提供向量数据库的配置、状态查询、数据管理和搜索功能。

源文件：`server/api/routers/vector.py`，路由前缀 `/api`

### 1. 获取向量数据库配置

**GET** `/api/vector/config`

获取向量数据库配置信息。

**响应示例：**
```json
{
  "status": "success",
  "config": {
    "backend": "weaviate",
    "vector_size": 384,
    "host": "http://localhost:8080",
    "collection_name": "cxo_memories"
  }
}
```

### 2. 获取向量数据库运行状态

**GET** `/api/vector/status`

获取向量数据库运行状态。

**响应示例：**
```json
{
  "status": "success",
  "running": true,
  "backend": "weaviate",
  "connected": true,
  "collections": 1
}
```

### 3. 向量数据库健康检查

**GET** `/api/vector/health`

向量数据库健康检查。

**响应示例：**
```json
{
  "status": "healthy",
  "backend": "weaviate",
  "response_time_ms": 12
}
```

### 4. 列出向量数据

**GET** `/api/vector/vectors`

列出向量数据。

**查询参数：**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| limit | integer | 否 | 返回数量，默认 20 |
| offset | integer | 否 | 偏移量，默认 0 |
| memory_type | string | 否 | 按记忆类型过滤 |

**响应示例：**
```json
{
  "status": "success",
  "vectors": [
    {
      "memory_id": 1,
      "memory_type": "long_term",
      "vector_size": 384,
      "created_at": "2024-01-01T00:00:00"
    }
  ],
  "total": 100
}
```

### 5. 获取指定记忆的向量数据详情

**GET** `/api/vector/vectors/{memory_id}`

获取指定记忆的向量数据详情。

**路径参数：**
- `memory_id`: 记忆ID

**响应示例：**
```json
{
  "status": "success",
  "memory_id": 1,
  "memory_type": "long_term",
  "vector_size": 384,
  "content_preview": "用户喜欢喝咖啡...",
  "created_at": "2024-01-01T00:00:00"
}
```

### 6. 删除指定记忆的向量数据

**DELETE** `/api/vector/vectors/{memory_id}`

删除指定记忆的向量数据。

**路径参数：**
- `memory_id`: 记忆ID

**响应示例：**
```json
{
  "status": "success",
  "message": "向量数据已删除"
}
```

### 7. 同步向量数据库

**POST** `/api/vector/sync`

同步向量数据库与 SQLite（增量同步）。

**响应示例：**
```json
{
  "status": "success",
  "synced_count": 15,
  "message": "增量同步完成"
}
```

### 8. 重建全部向量数据

**POST** `/api/vector/rebuild`

重建全部向量数据（清空后全量同步）。

**响应示例：**
```json
{
  "status": "success",
  "rebuilt_count": 100,
  "message": "全量重建完成"
}
```

### 9. 向量相似度搜索

**POST** `/api/vector/search`

基于向量相似度的语义搜索。

**查询参数：**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| query | string | 是 | 搜索查询文本 |
| limit | integer | 否 | 返回数量，默认 10 |
| min_score | float | 否 | 最低相似度分数，默认 0.5 |
| memory_type | string | 否 | 按记忆类型过滤 |

**响应示例：**
```json
{
  "status": "success",
  "results": [
    {
      "memory_id": 1,
      "content": "用户喜欢喝咖啡",
      "score": 0.92,
      "memory_type": "long_term"
    }
  ],
  "total": 1
}
```

### 10. 获取向量数据库统计

**GET** `/api/vector/stats`

获取向量数据库统计信息。

**响应示例：**
```json
{
  "status": "success",
  "statistics": {
    "total_vectors": 100,
    "by_type": {
      "short_term": 20,
      "long_term": 75,
      "permanent": 5
    },
    "index_size_mb": 12.5,
    "backend": "weaviate"
  }
}
```

---

## 管理员 API

管理员专用 API，需要 `X-API-Key` Header 认证。

源文件：`server/api/routers/admin.py`，路由前缀 `/api`

**认证方式：** 所有端点（除 `/health` 外）需要在请求头中携带 `X-API-Key`。

```
X-API-Key: your-admin-api-key
```

### 1. 获取管理仪表盘数据

**GET** `/api/admin/dashboard`

获取管理仪表盘数据。

**请求头：**
- `X-API-Key`: 管理员密钥（必填）

**响应示例：**
```json
{
  "status": "success",
  "dashboard": {
    "system": {
      "uptime": 86400,
      "cpu_usage": 45.2,
      "memory_usage": 62.1
    },
    "memories": {
      "total": 100,
      "archived": 5
    },
    "agents": {
      "total": 3,
      "active": 2
    },
    "recent_activity": [
      {
        "type": "memory_created",
        "timestamp": "2024-01-01T00:00:00"
      }
    ]
  }
}
```

### 2. 获取管理员统计

**GET** `/api/admin/stats`

获取管理员统计信息。

**请求头：**
- `X-API-Key`: 管理员密钥（必填）

**响应示例：**
```json
{
  "status": "success",
  "statistics": {
    "total_requests": 10000,
    "total_errors": 50,
    "avg_response_time_ms": 120,
    "active_users": 5
  }
}
```

### 3. 管理员健康检查

**GET** `/api/admin/health`

管理员健康检查（无需认证）。

**响应示例：**
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "components": {
    "database": true,
    "vector_db": true,
    "llm": true
  }
}
```

### 4. 获取系统配置

**GET** `/api/admin/config`

获取系统配置。

**请求头：**
- `X-API-Key`: 管理员密钥（必填）

**响应示例：**
```json
{
  "status": "success",
  "config": {
    "system": {
      "debug": false,
      "log_level": "INFO"
    },
    "llm": {
      "provider": "ollama",
      "model": "qwen2.5:latest"
    },
    "vector": {
      "backend": "weaviate"
    }
  }
}
```

### 5. 更新系统配置

**PUT** `/api/admin/config`

更新系统配置。

**请求头：**
- `X-API-Key`: 管理员密钥（必填）

**请求体：**
```json
{
  "section": "system",
  "data": {
    "debug": true,
    "log_level": "DEBUG"
  }
}
```

**响应示例：**
```json
{
  "status": "success",
  "message": "配置已更新"
}
```

### 6. 获取系统日志

**GET** `/api/admin/logs`

获取系统日志。

**请求头：**
- `X-API-Key`: 管理员密钥（必填）

**查询参数：**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| level | string | 否 | 日志级别过滤（DEBUG/INFO/WARNING/ERROR） |
| lines | integer | 否 | 返回行数，默认 100 |

**响应示例：**
```json
{
  "status": "success",
  "logs": [
    {
      "timestamp": "2024-01-01T00:00:00",
      "level": "INFO",
      "message": "系统启动完成"
    }
  ]
}
```

### 7. 创建数据备份

**POST** `/api/admin/backup`

创建数据备份。

**请求头：**
- `X-API-Key`: 管理员密钥（必填）

**响应示例：**
```json
{
  "status": "success",
  "backup_id": "backup-20240101",
  "message": "备份创建成功"
}
```

---

## Avatar 模型管理 API

提供 VRM/Live2D 虚拟形象模型的上传、下载和管理功能。

源文件：`server/api/routers/avatars.py`，路由前缀 `/api`

### 1. 获取模型列表

**GET** `/api/avatars`

获取所有已上传的 VRM/Live2D 模型列表。

**查询参数：**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| type | string | 否 | 模型类型过滤：vrm / live2d |

**响应示例：**
```json
{
  "status": "success",
  "avatars": [
    {
      "avatar_id": "avatar-001",
      "name": "默认角色",
      "avatar_type": "vrm",
      "file_size": 5242880,
      "created_at": "2024-01-01T00:00:00"
    }
  ],
  "total": 1
}
```

### 2. 上传模型文件

**POST** `/api/avatars/upload`

上传 VRM 或 Live2D 模型文件。

**请求格式：** multipart/form-data

**字段：**
| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| file | file | 是 | 模型文件，限制 50MB |
| name | string | 是 | 模型名称 |
| avatar_type | string | 是 | 模型类型：vrm / live2d |

**响应示例：**
```json
{
  "status": "success",
  "avatar_id": "avatar-002",
  "name": "新角色",
  "avatar_type": "vrm",
  "message": "模型上传成功"
}
```

### 3. 获取单个模型元数据

**GET** `/api/avatars/{avatar_id}`

获取单个模型的元数据。

**路径参数：**
- `avatar_id`: 模型ID

**查询参数：**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| avatar_type | string | 否 | 模型类型：vrm / live2d |

**响应示例：**
```json
{
  "status": "success",
  "avatar": {
    "avatar_id": "avatar-001",
    "name": "默认角色",
    "avatar_type": "vrm",
    "file_size": 5242880,
    "metadata": {},
    "created_at": "2024-01-01T00:00:00",
    "updated_at": "2024-01-01T00:00:00"
  }
}
```

### 4. 下载模型文件

**GET** `/api/avatars/{avatar_id}/file`

下载模型文件。

**路径参数：**
- `avatar_id`: 模型ID

**查询参数：**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| avatar_type | string | 否 | 模型类型：vrm / live2d |

**响应：** 模型文件二进制流

### 5. 更新模型元数据

**PUT** `/api/avatars/{avatar_id}`

更新模型元数据。

**路径参数：**
- `avatar_id`: 模型ID

**查询参数：**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| avatar_type | string | 否 | 模型类型：vrm / live2d |

**请求体：**
```json
{
  "name": "更新后的名称",
  "metadata": {
    "description": "角色描述"
  }
}
```

**响应示例：**
```json
{
  "status": "success",
  "message": "模型元数据已更新"
}
```

### 6. 删除模型

**DELETE** `/api/avatars/{avatar_id}`

删除模型及其文件。

**路径参数：**
- `avatar_id`: 模型ID

**查询参数：**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| avatar_type | string | 否 | 模型类型：vrm / live2d |

**响应示例：**
```json
{
  "status": "success",
  "message": "模型已删除"
}
```

---

## 备份管理 API

提供数据备份的创建、恢复、导入导出等功能。

源文件：`server/api/routers/backup.py`，路由前缀 `/api`

### 1. 获取备份列表

**GET** `/api/backups`

获取所有备份列表。

**响应示例：**
```json
{
  "status": "success",
  "backups": [
    {
      "backup_id": "backup-001",
      "backup_type": "full",
      "description": "每日全量备份",
      "size_mb": 128.5,
      "created_at": "2024-01-01T00:00:00"
    }
  ],
  "total": 1
}
```

### 2. 创建新备份

**POST** `/api/backups`

创建新备份。

**请求体：**
```json
{
  "backup_type": "full",
  "description": "手动全量备份"
}
```

**参数说明：**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| backup_type | string | 是 | 备份类型：full / incremental / differential |
| description | string | 否 | 备份描述 |

**响应示例：**
```json
{
  "status": "success",
  "backup_id": "backup-002",
  "backup_type": "full",
  "message": "备份创建成功"
}
```

### 3. 获取备份详情

**GET** `/api/backups/{backup_id}`

获取备份详情。

**路径参数：**
- `backup_id`: 备份ID

**响应示例：**
```json
{
  "status": "success",
  "backup": {
    "backup_id": "backup-001",
    "backup_type": "full",
    "description": "每日全量备份",
    "size_mb": 128.5,
    "file_count": 15,
    "created_at": "2024-01-01T00:00:00"
  }
}
```

### 4. 恢复指定备份

**POST** `/api/backups/{backup_id}/restore`

恢复指定备份。

**路径参数：**
- `backup_id`: 备份ID

**响应示例：**
```json
{
  "status": "success",
  "backup_id": "backup-001",
  "message": "备份恢复成功"
}
```

### 5. 删除指定备份

**DELETE** `/api/backups/{backup_id}`

删除指定备份。

**路径参数：**
- `backup_id`: 备份ID

**响应示例：**
```json
{
  "status": "success",
  "message": "备份已删除"
}
```

### 6. 获取备份统计

**GET** `/api/backups/stats`

获取备份统计信息。

**响应示例：**
```json
{
  "status": "success",
  "statistics": {
    "total_backups": 5,
    "total_size_mb": 640.0,
    "by_type": {
      "full": 2,
      "incremental": 2,
      "differential": 1
    },
    "latest_backup": "2024-01-01T00:00:00"
  }
}
```

### 7. 导入备份文件

**POST** `/api/backups/import`

导入备份文件。

**请求格式：** multipart/form-data

**字段：**
- `file`: 备份文件（zip 格式）

**响应示例：**
```json
{
  "status": "success",
  "backup_id": "backup-imported-001",
  "message": "备份导入成功"
}
```

### 8. 导出备份文件

**GET** `/api/backups/{backup_id}/export`

导出备份文件。

**路径参数：**
- `backup_id`: 备份ID

**响应：** 备份文件二进制流（zip 格式）

---

## 服务管理 API

提供后端服务的运行状态查询、启停控制和配置管理功能。

源文件：`server/api/routers/service.py`，路由前缀 `/api`

### 1. 获取服务运行状态

**GET** `/api/service/status`

获取后端服务运行状态。

**响应示例：**
```json
{
  "status": "success",
  "service": {
    "running": true,
    "pid": 12345,
    "port": 8000,
    "uptime_seconds": 86400,
    "uptime_formatted": "1 day, 0:00:00"
  }
}
```

### 2. 启动后端服务

**POST** `/api/service/start`

启动后端服务。

**响应示例：**
```json
{
  "status": "success",
  "message": "服务启动成功",
  "pid": 12345
}
```

### 3. 停止后端服务

**POST** `/api/service/stop`

停止后端服务。

**响应示例：**
```json
{
  "status": "success",
  "message": "服务已停止"
}
```

### 4. 重启后端服务

**POST** `/api/service/restart`

重启后端服务。

**响应示例：**
```json
{
  "status": "success",
  "message": "服务重启成功",
  "pid": 12346
}
```

### 5. 获取服务日志

**GET** `/api/service/logs`

获取服务日志。

**查询参数：**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| lines | integer | 否 | 返回行数，默认 100 |

**响应示例：**
```json
{
  "status": "success",
  "logs": [
    "[INFO] 2024-01-01 00:00:00 - 服务启动完成",
    "[INFO] 2024-01-01 00:00:01 - 数据库连接成功"
  ]
}
```

### 6. 获取服务配置

**GET** `/api/service/config`

获取当前服务配置。

**响应示例：**
```json
{
  "status": "success",
  "config": {
    "host": "0.0.0.0",
    "port": 8000,
    "workers": 1,
    "log_level": "INFO"
  }
}
```

### 7. 更新服务配置

**PUT** `/api/service/config`

更新服务配置（需重启生效）。

**请求体：**
```json
{
  "log_level": "DEBUG",
  "workers": 2
}
```

**响应示例：**
```json
{
  "status": "success",
  "message": "配置已更新，需重启服务生效"
}
```

### 8. 更新服务配置（POST）

**POST** `/api/service/config`

更新服务配置（同 PUT，需重启生效）。

**请求体：** 同 PUT `/api/service/config`

### 9. 获取运行环境信息

**GET** `/api/service/environment`

获取运行环境信息。

**响应示例：**
```json
{
  "status": "success",
  "environment": {
    "python_version": "3.11.0",
    "os": "Linux",
    "cpu_count": 8,
    "memory_total_gb": 16.0,
    "cuda_available": true
  }
}
```

### 10. 获取启动命令信息

**GET** `/api/service/startup-command`

获取启动命令信息。

**响应示例：**
```json
{
  "status": "success",
  "command": "python -m uvicorn server.main:app --host 0.0.0.0 --port 8000",
  "working_directory": "/app"
}
```

### 11. 获取可用模型列表

**GET** `/api/service/models`

获取可用模型列表。

**响应示例：**
```json
{
  "status": "success",
  "models": [
    {
      "name": "qwen2.5:latest",
      "provider": "ollama",
      "size": "4.7GB",
      "status": "available"
    }
  ]
}
```

### 12. 获取单体架构网关配置

**GET** `/api/config/gateway`

获取单体架构网关配置。

**响应示例：**
```json
{
  "status": "success",
  "gateway": {
    "mode": "monolithic",
    "port": 8000,
    "routes": {
      "api": "/api",
      "ws": "/api/ws"
    }
  }
}
```

---

## 记忆对话 API

与记忆管理模型进行自然语言对话，支持通过自然语言指令管理记忆。

### 1. 记忆管理对话

**POST** `/api/memory-chat`

与记忆管理模型自然语言对话。

**请求体：**
```json
{
  "message": "帮我搜索关于咖啡的记忆",
  "session_id": "optional-session-id"
}
```

**参数说明：**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| message | string | 是 | 用户消息内容 |
| session_id | string | 否 | 会话ID，不提供则创建新会话 |

**响应示例：**
```json
{
  "status": "success",
  "response": "找到了2条关于咖啡的记忆：1. 用户喜欢喝咖啡... 2. 用户偏好拿铁...",
  "session_id": "memory-chat-abc123"
}
```

### 2. 获取对话会话历史

**GET** `/api/memory-chat/sessions/{session_id}`

获取对话会话历史。

**路径参数：**
- `session_id`: 会话ID

**响应示例：**
```json
{
  "status": "success",
  "session_id": "memory-chat-abc123",
  "messages": [
    {
      "role": "user",
      "content": "帮我搜索关于咖啡的记忆",
      "created_at": "2024-01-01T00:00:00"
    },
    {
      "role": "assistant",
      "content": "找到了2条关于咖啡的记忆...",
      "created_at": "2024-01-01T00:00:01"
    }
  ]
}
```

### 3. 清除指定对话会话

**DELETE** `/api/memory-chat/sessions/{session_id}`

清除指定对话会话。

**路径参数：**
- `session_id`: 会话ID

**响应示例：**
```json
{
  "status": "success",
  "message": "会话已清除"
}
```

### 4. 列出可用记忆管理命令

**GET** `/api/memory-chat/commands`

列出可用的记忆管理命令。

**响应示例：**
```json
{
  "status": "success",
  "commands": [
    {
      "name": "search",
      "description": "搜索记忆",
      "usage": "搜索 [关键词]"
    },
    {
      "name": "archive",
      "description": "归档记忆",
      "usage": "归档 [记忆ID]"
    },
    {
      "name": "merge",
      "description": "合并重复记忆",
      "usage": "合并 [记忆ID1] [记忆ID2]"
    }
  ]
}
```

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
