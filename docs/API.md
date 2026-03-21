# CX-O API 文档

## 概述

CX-O 是一个 AI 智能体系统，包含多个服务：

- **CXHMS 后端** (端口 8000) - 核心 AI 处理、记忆管理、Agent 系统
- **CX-O 网关** (端口 8100) - 统一的 WebSocket 和 HTTP API 网关
- **前端** (端口 5173) - React 管理界面

## 服务地址

| 服务       | 协议        | 地址                      |
| -------- | --------- | ----------------------- |
| CXHMS 后端 | HTTP      | `http://127.0.0.1:8000` |
| CXHMS 后端 | WebSocket | `ws://127.0.0.1:8000`   |
| CX-O 网关  | HTTP      | `http://127.0.0.1:8100` |
| CX-O 网关  | WebSocket | `ws://127.0.0.1:8100`   |

***

## 第一部分：CXHMS 后端 HTTP API

基础地址：`http://127.0.0.1:8000`

所有接口前缀为 `/api`

***

### 健康检查与管理

#### GET /health

健康检查接口。

**响应：**

```Python
{
  "status": "healthy",
  "components": {
    "memory": "healthy",
    "context": "healthy",
    "acp": "healthy"
  }
}
```

#### GET /api/admin/dashboard

获取仪表盘统计数据。

**请求头：**

```
X-API-Key: <admin-api-key>
```

**响应：**

```json
{
  "status": "success",
  "timestamp": "2024-01-15T10:30:00",
  "dashboard": {
    "memory": {
      "total_memories": 150,
      "long_term_count": 80,
      "short_term_count": 50,
      "permanent_count": 20
    },
    "context": {
      "total_sessions": 10,
      "total_messages": 500
    },
    "acp": {
      "total_agents": 3,
      "active_connections": 2
    }
  }
}
```

#### GET /api/admin/stats

获取系统统计信息。

**请求头：**

```
X-API-Key: <admin-api-key>
```

**响应：**

```json
{
  "status": "success",
  "statistics": {
    "memory": {
      "total_memories": 150,
      "by_type": {
        "long_term": 80,
        "short_term": 50,
        "permanent": 20
      }
    },
    "context": {
      "total_sessions": 10,
      "total_messages": 500
    },
    "tools": {
      "total_tools": 25,
      "enabled_tools": 20
    }
  }
}
```

#### GET /api/admin/health

获取详细健康信息（无需认证）。

**响应：**

```json
{
  "status": "healthy",
  "components": {
    "memory": "healthy",
    "context": "healthy",
    "acp": "healthy"
  }
}
```

#### GET /api/admin/config

获取系统配置。

**请求头：**

```
X-API-Key: <admin-api-key>
```

**响应：**

```json
{
  "status": "success",
  "config": {
    "llm": {
      "provider": "ollama",
      "model": "qwen2.5:14b"
    },
    "vector": {
      "enabled": true
    },
    "acp": {
      "enabled": true,
      "agent_name": "晨曦"
    },
    "system": {
      "debug": false
    }
  }
}
```

#### PUT /api/admin/config

更新系统配置。

**请求头：**

```
X-API-Key: <admin-api-key>
```

**请求：**

```json
{
  "llm": {
    "provider": "ollama",
    "model": "qwen2.5:14b"
  },
  "vector": {
    "enabled": true
  },
  "system": {
    "debug": false
  }
}
```

**响应：**

```json
{
  "status": "success",
  "message": "配置已更新"
}
```

#### GET /api/admin/logs

获取系统日志。

**请求头：**

```
X-API-Key: <admin-api-key>
```

**查询参数：**

- `level` (string, 默认: "INFO") - 日志级别
- `lines` (int, 默认: 50) - 行数

**响应：**

```json
{
  "status": "success",
  "logs": ["日志内容..."],
  "total": 3,
  "level": "INFO",
  "lines": 50
}
```

#### POST /api/admin/backup

触发备份。

**请求头：**

```
X-API-Key: <admin-api-key>
```

**响应：**

```json
{
  "status": "success",
  "path": "data/backups/backup_20240115_103000.zip",
  "message": "备份已创建: backup_20240115_103000.zip"
}
```

***

### 聊天模块

#### POST /api/chat

非流式聊天。

**请求：**

```json
{
  "message": "你好",
  "agent_id": "default",
  "stream": false
}
```

**响应：**

```json
{
  "status": "success",
  "response": "你好！有什么可以帮助你的吗？",
  "session_id": "agent-default",
  "tokens_used": 150
}
```

#### POST /api/chat/stream

流式聊天（SSE）。

**请求：**

```json
{
  "message": "你好",
  "agent_id": "default",
  "stream": true,
  "images": ["base64编码的图片数据"]
}
```

**响应（SSE）：**

```
data: {"type": "session", "session_id": "agent-default"}

data: {"type": "thinking", "content": "让我想想..."}

data: {"type": "content", "content": "你好"}

data: {"type": "tool_call", "tool_call": {"name": "calculator", "arguments": {}}}

data: {"type": "tool_result", "tool_name": "calculator", "result": {"result": 42}}

data: {"type": "done", "session_id": "agent-default"}
```

#### GET /api/chat/history/{session\_id}

获取聊天历史。

**响应：**

```json
{
  "status": "success",
  "session_id": "agent-default",
  "session": {
    "id": "agent-default",
    "title": "默认助手的对话",
    "created_at": "2024-01-15T10:00:00",
    "message_count": 10
  },
  "messages": [
    {
      "id": 1,
      "role": "user",
      "content": "你好",
      "created_at": "2024-01-15T10:00:00"
    },
    {
      "id": 2,
      "role": "assistant",
      "content": "你好！有什么可以帮助你的吗？",
      "created_at": "2024-01-15T10:00:05"
    }
  ]
}
```

#### POST /api/memory-agent/chat/stream

记忆 Agent 流式聊天。

**请求：**

```json
{
  "message": "搜索关于AI的记忆"
}
```

**响应（SSE）：**

```
data: {"type": "session", "session_id": "memory-agent-default"}

data: {"type": "content", "content": "找到了以下关于AI的记忆..."}

data: {"type": "done", "session_id": "memory-agent-default"}
```

***

### 记忆模块

#### GET /api/memories

获取记忆列表。

**查询参数：**

- `workspace_id` (string, 默认: "default")
- `type` (string, 可选) - long\_term/short\_term/permanent
- `memory_type` (string, 可选) - type 的别名
- `limit` (int, 默认: 20)
- `offset` (int, 默认: 0)
- `agent_id` (string, 默认: "default")

**响应：**

```json
{
  "status": "success",
  "memories": [
    {
      "id": 1,
      "content": "用户喜欢喝咖啡",
      "type": "long_term",
      "importance": 4,
      "tags": ["偏好", "饮食"],
      "created_at": "2024-01-15T10:00:00",
      "updated_at": "2024-01-15T10:00:00",
      "is_archived": false,
      "decay_score": 0.85
    }
  ],
  "total": 1
}
```

#### POST /api/memories

创建新记忆。

**请求：**

```json
{
  "content": "要记住的重要信息",
  "type": "long_term",
  "importance": 5,
  "tags": ["重要", "工作"],
  "metadata": {},
  "permanent": false,
  "workspace_id": "default"
}
```

**响应：**

```json
{
  "status": "success",
  "memory_id": 123,
  "message": "记忆创建成功"
}
```

#### GET /api/memories/{memory\_id}

获取指定记忆。

**响应：**

```json
{
  "status": "success",
  "memory": {
    "id": 1,
    "content": "用户喜欢喝咖啡",
    "type": "long_term",
    "importance": 4,
    "tags": ["偏好", "饮食"],
    "created_at": "2024-01-15T10:00:00",
    "updated_at": "2024-01-15T10:00:00",
    "metadata": {},
    "decay_score": 0.85
  }
}
```

#### PUT /api/memories/{memory\_id}

更新记忆。

**请求：**

```json
{
  "content": "更新后的内容",
  "importance": 4,
  "tags": ["已更新"]
}
```

**响应：**

```json
{
  "status": "success",
  "message": "记忆更新成功"
}
```

#### DELETE /api/memories/{memory\_id}

删除记忆。

**查询参数：**

- `soft_delete` (bool, 默认: false) - 是否软删除

**响应：**

```json
{
  "status": "success",
  "message": "记忆删除成功"
}
```

#### POST /api/memories/search

搜索记忆。

**请求：**

```json
{
  "query": "搜索关键词",
  "type": "long_term",
  "tags": ["标签1"],
  "limit": 10,
  "offset": 0,
  "workspace_id": "default",
  "agent_id": "default"
}
```

**响应：**

```json
{
  "status": "success",
  "memories": [
    {
      "id": 1,
      "content": "匹配的记忆内容",
      "type": "long_term",
      "importance": 4,
      "tags": ["标签1"],
      "score": 0.95
    }
  ],
  "total": 1
}
```

#### POST /api/memories/rag

RAG 搜索记忆。

**请求：**

```json
{
  "query": "用户对AI的看法",
  "workspace_id": "default",
  "limit": 5
}
```

**响应：**

```json
{
  "status": "success",
  "query": "用户对AI的看法",
  "results": [
    {
      "id": 1,
      "content": "用户认为AI很有用",
      "score": 0.92
    }
  ],
  "total": 1
}
```

#### GET /api/memories/stats

获取记忆统计。

**响应：**

```json
{
  "status": "success",
  "statistics": {
    "total_memories": 150,
    "by_type": {
      "long_term": 80,
      "short_term": 50,
      "permanent": 20
    },
    "by_importance": {
      "1": 10,
      "2": 20,
      "3": 50,
      "4": 40,
      "5": 30
    },
    "archived_count": 15,
    "deleted_count": 5
  }
}
```

#### POST /api/memories/permanent

创建永久记忆。

**请求：**

```json
{
  "content": "永久信息",
  "tags": ["永久"],
  "metadata": {},
  "emotion_score": 0.5,
  "source": "user"
}
```

**响应：**

```json
{
  "status": "success",
  "memory_id": 456,
  "message": "永久记忆创建成功"
}
```

#### GET /api/memories/permanent

获取永久记忆列表。

**查询参数：**

- `limit` (int, 默认: 20)
- `offset` (int, 默认: 0)
- `tags` (list, 可选)

**响应：**

```json
{
  "status": "success",
  "memories": [
    {
      "id": 1,
      "content": "永久记忆内容",
      "importance_score": 5,
      "tags": ["永久"],
      "created_at": "2024-01-15T10:00:00",
      "emotion_score": 0.5,
      "source": "user",
      "verified": true
    }
  ],
  "total": 1
}
```

#### GET /api/memories/permanent/{memory\_id}

获取永久记忆详情。

**响应：**

```json
{
  "status": "success",
  "memory": {
    "id": 1,
    "content": "永久记忆内容",
    "importance_score": 5,
    "tags": ["永久"],
    "created_at": "2024-01-15T10:00:00",
    "metadata": {},
    "emotion_score": 0.5,
    "source": "user",
    "verified": true
  }
}
```

#### PUT /api/memories/permanent/{memory\_id}

更新永久记忆。

**请求：**

```json
{
  "content": "更新后的永久记忆",
  "tags": ["更新"],
  "metadata": {}
}
```

**响应：**

```json
{
  "status": "success",
  "message": "永久记忆更新成功"
}
```

#### DELETE /api/memories/permanent/{memory\_id}

删除永久记忆。

**响应：**

```json
{
  "status": "success",
  "message": "永久记忆删除成功"
}
```

#### POST /api/memories/3d

3D 记忆搜索（重要性、时间、相关性）。

**请求：**

```json
{
  "query": "搜索关键词",
  "memory_type": "long_term",
  "tags": [],
  "limit": 10,
  "weights": [0.35, 0.25, 0.4],
  "workspace_id": "default"
}
```

**响应：**

```json
{
  "status": "success",
  "memories": [
    {
      "id": 1,
      "content": "匹配的记忆",
      "score": 0.88,
      "importance_score": 0.9,
      "time_score": 0.8,
      "relevance_score": 0.95
    }
  ],
  "total": 1,
  "applied_weights": {
    "importance": 0.35,
    "time": 0.25,
    "relevance": 0.4
  }
}
```

#### POST /api/memories/recall/{memory\_id}

带情感强度回忆记忆。

**请求：**

```json
{
  "emotion_intensity": 0.5
}
```

**响应：**

```json
{
  "status": "success",
  "memory": {
    "id": 1,
    "content": "回忆的记忆内容",
    "recall_count": 5,
    "last_recalled_at": "2024-01-15T10:30:00"
  },
  "message": "记忆召回成功"
}
```

#### POST /api/memories/semantic-search

使用向量相似度进行语义搜索。

**请求：**

```json
{
  "query": "我之前学到的关于 AI 的知识？",
  "limit": 10,
  "threshold": 0.7,
  "workspace_id": "default"
}
```

**响应：**

```json
{
  "status": "success",
  "query": "我之前学到的关于 AI 的知识？",
  "results": [
    {
      "id": 1,
      "content": "AI相关知识",
      "score": 0.92
    }
  ],
  "total": 1,
  "threshold": 0.7
}
```

#### GET /api/memories/vectors/status

获取向量数据库状态。

**响应：**

```json
{
  "status": "success",
  "data": {
    "enabled": true,
    "backend": "chroma",
    "vector_count": 150,
    "sqlite_count": 150,
    "healthy": true,
    "last_sync": "2024-01-15T10:00:00"
  }
}
```

#### GET /api/memories/type/{memory\_type}

按类型获取记忆。

**路径参数：**

- `memory_type` - long\_term/short\_term

**查询参数：**

- `limit` (int, 默认: 20)
- `workspace_id` (string, 默认: "default")
- `agent_id` (string, 默认: "default")

**响应：**

```json
{
  "status": "success",
  "memories": [
    {
      "id": 1,
      "content": "记忆内容",
      "type": "long_term"
    }
  ],
  "count": 1
}
```

#### GET /api/memories/search-by-tag

按标签搜索记忆。

**查询参数：**

- `tag` (string, 必需) - 标签名
- `limit` (int, 默认: 20)
- `workspace_id` (string, 默认: "default")
- `agent_id` (string, 默认: "default")

**响应：**

```json
{
  "status": "success",
  "memories": [
    {
      "id": 1,
      "content": "带标签的记忆",
      "tags": ["重要"]
    }
  ],
  "count": 1
}
```

#### POST /api/memories/sync-decay

同步记忆衰减值。

**响应：**

```json
{
  "status": "success",
  "result": {
    "updated_count": 50,
    "message": "衰减值已同步"
  }
}
```

#### GET /api/memories/decay-stats

获取衰减统计。

**响应：**

```json
{
  "status": "success",
  "statistics": {
    "total_memories": 150,
    "avg_decay_score": 0.75,
    "low_decay_count": 20,
    "high_decay_count": 130
  }
}
```

#### POST /api/memories/secondary/execute

执行辅助模型命令。

**请求：**

```json
{
  "command": "summarize",
  "target_id": "1",
  "target_type": "memory",
  "parameters": {},
  "context": {},
  "priority": 0
}
```

**响应：**

```json
{
  "status": "success",
  "result": {
    "command": "summarize",
    "output": "摘要结果"
  }
}
```

#### GET /api/memories/secondary/commands

获取可用的辅助命令。

**响应：**

```json
{
  "status": "success",
  "commands": [
    "summarize",
    "categorize",
    "extract_entities"
  ]
}
```

#### GET /api/memories/secondary/history

获取辅助模型执行历史。

**查询参数：**

- `limit` (int, 默认: 10)

**响应：**

```json
{
  "status": "success",
  "history": [
    {
      "command": "summarize",
      "executed_at": "2024-01-15T10:00:00",
      "status": "completed"
    }
  ]
}
```

#### GET /api/memories/agents

获取所有 Agent 记忆表。

**响应：**

```json
{
  "status": "success",
  "agents": [
    {
      "agent_id": "default",
      "table_name": "memories",
      "created_at": null
    },
    {
      "agent_id": "agent-001",
      "table_name": "memories_agent_001",
      "created_at": "2024-01-15T10:00:00"
    }
  ],
  "total": 2
}
```

#### POST /api/memories/batch/write

批量写入记忆。

**请求：**

```json
[
  {
    "content": "记忆1",
    "type": "long_term",
    "importance": 3
  },
  {
    "content": "记忆2",
    "type": "short_term",
    "importance": 2
  }
]
```

**响应：**

```json
{
  "status": "success",
  "result": {
    "success_count": 2,
    "failed_count": 0,
    "memory_ids": [1, 2]
  }
}
```

#### POST /api/memories/batch/update

批量更新记忆。

**请求：**

```json
{
  "ids": [1, 2, 3],
  "data": {
    "content": "更新后的内容",
    "tags": ["批量"],
    "importance": 5
  },
  "agent_id": "default"
}
```

**响应：**

```json
{
  "status": "success",
  "result": {
    "updated_count": 3,
    "failed_ids": []
  }
}
```

#### POST /api/memories/batch/delete

批量删除记忆。

**请求：**

```json
{
  "ids": [1, 2, 3],
  "agent_id": "default"
}
```

**响应：**

```json
{
  "status": "success",
  "result": {
    "deleted_count": 3,
    "failed_ids": []
  }
}
```

#### POST /api/memories/batch/tags

批量更新记忆标签。

**请求：**

```json
{
  "ids": [1, 2, 3],
  "tags": ["重要"],
  "operation": "add",
  "agent_id": "default"
}
```

**响应：**

```json
{
  "status": "success",
  "result": {
    "updated_count": 3,
    "operation": "add"
  }
}
```

#### POST /api/memories/batch/archive

批量归档记忆。

**请求：**

```json
{
  "ids": [1, 2, 3],
  "agent_id": "default"
}
```

**响应：**

```json
{
  "status": "success",
  "result": {
    "archived_count": 3
  }
}
```

#### POST /api/memories/batch/restore

批量恢复记忆。

**请求：**

```json
{
  "ids": [1, 2, 3],
  "agent_id": "default"
}
```

**响应：**

```json
{
  "status": "success",
  "result": {
    "restored_count": 3,
    "failed_count": 0
  }
}
```

#### POST /api/memories/batch/tag-by-query

按查询批量标记。

**请求：**

```json
{
  "query": "AI",
  "tags": ["AI相关"],
  "operation": "add",
  "agent_id": "default"
}
```

**响应：**

```json
{
  "status": "success",
  "result": {
    "updated_count": 10
  }
}
```

#### POST /api/memories/batch/delete-by-query

按查询批量删除。

**请求：**

```json
{
  "query": "测试",
  "agent_id": "default"
}
```

**响应：**

```json
{
  "status": "success",
  "result": {
    "deleted_count": 5
  }
}
```

#### POST /api/memories/batch/archive-by-query

按查询批量归档。

**请求：**

```json
{
  "query": "旧数据",
  "target_level": 1,
  "agent_id": "default"
}
```

**响应：**

```json
{
  "status": "success",
  "result": {
    "archived_count": 8
  }
}
```

***

### 归档模块

#### POST /api/archive/memory

归档记忆。

**请求：**

```json
{
  "memory_id": 1,
  "target_level": 1,
  "compress": true
}
```

**响应：**

```json
{
  "status": "success",
  "archive": {
    "id": 1,
    "memory_id": 1,
    "archive_level": 1,
    "compressed_content": "压缩后的内容",
    "created_at": "2024-01-15T10:00:00"
  },
  "message": "记忆已归档到级别 1"
}
```

#### POST /api/archive/merge

合并已归档记忆。

**请求：**

```json
{
  "memory_ids": [1, 2, 3],
  "strategy": "smart"
}
```

**响应：**

```json
{
  "status": "success",
  "result": {
    "success": true,
    "merged_memory_id": 10,
    "merged_from": [1, 2, 3],
    "merged_content": "合并后的内容",
    "message": "成功合并 3 条记忆"
  }
}
```

#### POST /api/archive/deduplicate

去重已归档记忆。

**请求：**

```json
{
  "memory_ids": [1, 2, 3],
  "threshold": 0.85
}
```

**响应：**

```json
{
  "status": "success",
  "duplicate_groups": [
    {
      "group_id": 1,
      "memory_ids": [1, 2],
      "similarity": 0.92,
      "merged": false
    }
  ],
  "total_groups": 1,
  "threshold": 0.85
}
```

#### GET /api/archive/duplicates

获取重复记忆。

**响应：**

```json
{
  "status": "success",
  "duplicate_groups": [
    {
      "group_id": 1,
      "memory_ids": [1, 2, 3],
      "similarity": 0.9,
      "merged": false
    }
  ],
  "total_groups": 1
}
```

#### POST /api/archive/of-archives

归档的归档。

**请求：**

```json
{
  "target_level": 4
}
```

**响应：**

```json
{
  "status": "success",
  "results": [
    {
      "archive_id": 1,
      "new_level": 4
    }
  ],
  "count": 1,
  "target_level": 4
}
```

#### GET /api/archive/stats

获取归档统计。

**响应：**

```json
{
  "status": "success",
  "statistics": {
    "total_archives": 50,
    "by_level": {
      "1": 20,
      "2": 15,
      "3": 10,
      "4": 5
    },
    "total_compressed_size": 10240
  }
}
```

#### GET /api/archive/levels

获取归档级别。

**响应：**

```json
{
  "status": "success",
  "archive_levels": {
    "1": {
      "level": 1,
      "name": "轻度归档",
      "description": "保留主要信息",
      "compression_ratio": 0.8,
      "max_age_days": 30
    },
    "2": {
      "level": 2,
      "name": "中度归档",
      "description": "压缩摘要",
      "compression_ratio": 0.5,
      "max_age_days": 90
    }
  }
}
```

#### POST /api/archive/threshold

设置归档阈值。

**请求：**

```json
{
  "threshold": 0.85
}
```

**响应：**

```json
{
  "status": "success",
  "threshold": 0.85,
  "message": "去重阈值已设置为 0.85"
}
```

#### GET /api/archive/threshold

获取归档阈值。

**响应：**

```json
{
  "status": "success",
  "threshold": 0.85
}
```

#### POST /api/archive/auto-process

运行自动归档进程。

**请求：**

```json
{
  "min_age_days": 30,
  "target_level": 1,
  "auto_merge": true
}
```

**响应：**

```json
{
  "status": "success",
  "results": {
    "archived": [
      {"memory_id": 1, "archive_id": 10, "level": 1}
    ],
    "merged": [
      {"group_id": 1, "merged_memory_id": 20, "memory_count": 3}
    ],
    "errors": []
  },
  "summary": {
    "archived_count": 1,
    "merged_count": 1,
    "error_count": 0
  }
}
```

***

### 上下文模块

#### GET /api/context/sessions

列出所有会话。

**查询参数：**

- `workspace_id` (string, 默认: "default")
- `limit` (int, 默认: 20)
- `active_only` (bool, 默认: true)

**响应：**

```json
{
  "status": "success",
  "sessions": [
    {
      "id": "session-001",
      "title": "聊天会话",
      "created_at": "2024-01-15T10:00:00",
      "updated_at": "2024-01-15T10:30:00",
      "message_count": 10,
      "is_active": true
    }
  ],
  "total": 1
}
```

#### POST /api/context/sessions

创建新会话。

**请求：**

```json
{
  "workspace_id": "default",
  "title": "新会话",
  "metadata": {}
}
```

**响应：**

```json
{
  "status": "success",
  "session_id": "session-002",
  "message": "会话创建成功"
}
```

#### GET /api/context/sessions/{session\_id}

获取指定会话。

**响应：**

```json
{
  "status": "success",
  "session": {
    "id": "session-001",
    "title": "聊天会话",
    "created_at": "2024-01-15T10:00:00",
    "updated_at": "2024-01-15T10:30:00",
    "message_count": 10,
    "metadata": {}
  }
}
```

#### DELETE /api/context/sessions/{session\_id}

删除会话。

**响应：**

```json
{
  "status": "success",
  "message": "会话删除成功"
}
```

#### DELETE /api/context/sessions/all

删除所有会话。

**响应：**

```json
{
  "status": "success",
  "message": "已删除 10 个会话",
  "deleted_count": 10
}
```

#### GET /api/context/messages/{session\_id}

获取会话消息。

**查询参数：**

- `limit` (int, 默认: 50)
- `offset` (int, 默认: 0)

**响应：**

```json
{
  "status": "success",
  "session_id": "session-001",
  "messages": [
    {
      "id": 1,
      "role": "user",
      "content": "你好",
      "created_at": "2024-01-15T10:00:00"
    },
    {
      "id": 2,
      "role": "assistant",
      "content": "你好！",
      "created_at": "2024-01-15T10:00:05"
    }
  ],
  "total": 2
}
```

#### POST /api/context/messages

添加消息到会话。

**请求：**

```json
{
  "session_id": "session-001",
  "role": "user",
  "content": "新消息",
  "content_type": "text",
  "metadata": {}
}
```

**响应：**

```json
{
  "status": "success",
  "message_id": 100,
  "message": "消息添加成功"
}
```

#### POST /api/context/summary

生成上下文摘要。

**请求：**

```json
{
  "session_id": "session-001",
  "max_points": 5,
  "save_as_memory": true
}
```

**响应：**

```json
{
  "status": "success",
  "conversation_id": "session-001",
  "summary_memory_id": 500,
  "key_points": [
    {"content": "讨论了AI技术", "importance": "high", "participants": ["user"]}
  ],
  "report": {
    "topic": "AI技术讨论",
    "participants": ["user", "assistant"],
    "message_count": 10,
    "main_discussion": "主要讨论了AI的发展和应用",
    "sentiment": "positive"
  }
}
```

#### GET /api/context/stats

获取上下文统计。

**响应：**

```json
{
  "status": "success",
  "statistics": {
    "total_sessions": 10,
    "total_messages": 500,
    "by_role": {
      "user": 250,
      "assistant": 250
    }
  }
}
```

***

### 记忆聊天模块

#### POST /api/memory-chat

记忆聊天（非流式）。

**请求：**

```json
{
  "message": "搜索关于AI的记忆",
  "session_id": "default"
}
```

**响应：**

```json
{
  "status": "success",
  "message": "找到了5条关于AI的记忆",
  "session_id": "default",
  "pending_command": null,
  "data": {
    "memories": [
      {"id": 1, "content": "AI相关知识"}
    ]
  }
}
```

#### GET /api/memory-chat/sessions/{session\_id}

获取记忆聊天会话。

**响应：**

```json
{
  "status": "success",
  "session_id": "default",
  "messages": [
    {"role": "user", "content": "搜索AI记忆"},
    {"role": "assistant", "content": "找到了5条记忆"}
  ],
  "has_pending_command": false,
  "pending_command": null
}
```

#### DELETE /api/memory-chat/sessions/{session\_id}

删除记忆聊天会话。

**响应：**

```json
{
  "status": "success",
  "message": "会话 default 已清除"
}
```

#### GET /api/memory-chat/commands

获取可用的记忆聊天命令。

**响应：**

```json
{
  "status": "success",
  "commands": {
    "search": "搜索记忆",
    "archive": "归档记忆",
    "merge": "合并记忆",
    "delete": "删除记忆",
    "stats": "查看统计"
  },
  "destructive_commands": ["delete", "merge"],
  "examples": [
    {"command": "搜索关于人工智能的记忆", "description": "搜索包含特定关键词的记忆"},
    {"command": "归档记忆 ID 123", "description": "将指定记忆归档"}
  ]
}
```

***

### 工具模块

#### GET /api/tools

列出所有工具。

**查询参数：**

- `category` (string, 可选)
- `include_builtin` (bool, 可选)
- `enabled_only` (bool, 默认: true)

**响应：**

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
    "total_tools": 25,
    "enabled_tools": 20
  }
}
```

#### POST /api/tools

创建新工具。

**请求：**

```json
{
  "name": "my_tool",
  "description": "自定义工具",
  "parameters": {
    "type": "object",
    "properties": {
      "input": {"type": "string"}
    }
  },
  "type": "native",
  "icon": "tool-icon",
  "config": {},
  "enabled": true,
  "category": "custom"
}
```

**响应：**

```json
{
  "status": "success",
  "message": "工具 my_tool 注册成功"
}
```

#### GET /api/tools/stats

获取工具统计。

**响应：**

```json
{
  "status": "success",
  "statistics": {
    "total_tools": 25,
    "enabled_tools": 20,
    "active_tools": 20,
    "disabled_tools": 5,
    "mcp_tools": 10,
    "native_tools": 15,
    "total_calls": 1000,
    "by_category": {
      "builtin": 5,
      "mcp": 10,
      "custom": 10
    },
    "top_tools": [
      {"name": "calculator", "calls": 500}
    ]
  }
}
```

#### POST /api/tools/call

调用工具。

**请求：**

```json
{
  "name": "calculator",
  "arguments": {
    "expression": "1 + 1"
  }
}
```

**响应：**

```json
{
  "success": true,
  "result": 2,
  "execution_time_ms": 5
}
```

#### POST /api/tools/{name}/test

测试工具。

**请求：**

```json
{
  "arguments": {
    "expression": "2 + 2"
  }
}
```

**响应：**

```json
{
  "status": "success",
  "tool_name": "calculator",
  "arguments": {"expression": "2 + 2"},
  "result": 4,
  "message": "工具 calculator 测试成功"
}
```

#### GET /api/tools/openai

获取 OpenAI 格式的工具列表。

**响应：**

```json
{
  "status": "success",
  "functions": [
    {
      "type": "function",
      "function": {
        "name": "calculator",
        "description": "数学计算工具",
        "parameters": {
          "type": "object",
          "properties": {
            "expression": {"type": "string"}
          }
        }
      }
    }
  ]
}
```

#### POST /api/tools/export

导出工具。

**响应：**

```json
{
  "status": "success",
  "tools": [
    {"name": "calculator", "description": "..."}
  ],
  "total": 25
}
```

#### POST /api/tools/import

导入工具。

**请求：**

```json
[
  {
    "name": "imported_tool",
    "description": "导入的工具",
    "parameters": {}
  }
]
```

**响应：**

```json
{
  "status": "success",
  "message": "成功导入 1 个工具",
  "count": 1
}
```

#### GET /api/tools/mcp/servers

列出 MCP 服务器。

**响应：**

```json
{
  "status": "success",
  "servers": [
    {
      "name": "filesystem",
      "status": "running",
      "tools_count": 5,
      "connected_at": "2024-01-15T10:00:00"
    }
  ],
  "statistics": {
    "total_servers": 1,
    "running_servers": 1
  }
}
```

#### POST /api/tools/mcp/servers

添加 MCP 服务器。

**请求：**

```json
{
  "name": "filesystem",
  "command": "mcp-filesystem",
  "args": ["/path/to/files"],
  "env": {}
}
```

**响应：**

```json
{
  "status": "success",
  "server": {
    "name": "filesystem",
    "status": "connecting"
  },
  "message": "MCP服务器 filesystem 已添加"
}
```

#### DELETE /api/tools/mcp/servers/{name}

删除 MCP 服务器。

**响应：**

```json
{
  "status": "success",
  "message": "MCP服务器 filesystem 已删除"
}
```

#### POST /api/tools/mcp/servers/start

启动 MCP 服务器。

**请求：**

```json
{
  "name": "filesystem"
}
```

**响应：**

```json
{
  "status": "success",
  "message": "MCP服务器 filesystem 已启动"
}
```

#### POST /api/tools/mcp/servers/stop

停止 MCP 服务器。

**请求：**

```json
{
  "name": "filesystem"
}
```

**响应：**

```json
{
  "status": "success",
  "message": "MCP服务器 filesystem 已停止"
}
```

#### GET /api/tools/mcp/servers/{name}/health

获取 MCP 服务器健康状态。

**响应：**

```json
{
  "status": "success",
  "server": "filesystem",
  "healthy": true
}
```

#### GET /api/tools/mcp/servers/{name}/tools

获取 MCP 服务器工具列表。

**响应：**

```json
{
  "status": "success",
  "server": "filesystem",
  "tools": [
    {"name": "read_file", "description": "读取文件"},
    {"name": "write_file", "description": "写入文件"}
  ]
}
```

#### POST /api/tools/mcp/call

调用 MCP 工具。

**请求：**

```json
{
  "server_name": "filesystem",
  "tool_name": "read_file",
  "arguments": {
    "path": "/path/to/file.txt"
  }
}
```

**响应：**

```json
{
  "status": "success",
  "result": {
    "content": "文件内容..."
  }
}
```

#### POST /api/tools/mcp/sync

同步 MCP 工具。

**响应：**

```json
{
  "status": "success",
  "message": "同步了 5 个MCP工具",
  "count": 5
}
```

#### GET /api/tools/plugins

获取插件工具。

**响应：**

```json
{
  "status": "success",
  "plugins": {
    "weather_plugin": {
      "name": "weather_plugin",
      "description": "天气插件"
    }
  },
  "total": 1
}
```

#### GET /api/tools/{name}

获取指定工具。

**响应：**

```json
{
  "status": "success",
  "tool": {
    "name": "calculator",
    "description": "数学计算工具",
    "parameters": {
      "type": "object",
      "properties": {
        "expression": {"type": "string", "description": "数学表达式"}
      }
    },
    "enabled": true,
    "category": "builtin"
  }
}
```

#### DELETE /api/tools/{name}

删除工具。

**响应：**

```json
{
  "status": "success",
  "message": "工具 my_tool 已删除"
}
```

***

### Agent 模块

#### GET /api/agents

列出所有 Agent。

**响应：**

```json
{
  "status": "success",
  "agents": [
    {
      "id": "default",
      "name": "默认助手",
      "description": "通用AI助手",
      "model": "main",
      "is_default": true
    }
  ],
  "total": 1
}
```

#### POST /api/agents

创建新 Agent。

**请求：**

```json
{
  "name": "我的助手",
  "description": "一个 AI 助手",
  "system_prompt": "你是一个有帮助的助手",
  "model": "main",
  "temperature": 0.7,
  "max_tokens": 4096,
  "use_memory": true,
  "use_tools": true,
  "vision_enabled": false,
  "memory_scene": "chat"
}
```

**响应：**

```json
{
  "status": "success",
  "agent": {
    "id": "agent-abc123",
    "name": "我的助手",
    "description": "一个 AI 助手",
    "model": "main",
    "temperature": 0.7,
    "max_tokens": 4096,
    "use_memory": true,
    "use_tools": true,
    "vision_enabled": false,
    "memory_scene": "chat",
    "is_default": false,
    "created_at": "2024-01-15T10:00:00"
  },
  "message": "Agent 创建成功"
}
```

#### GET /api/agents/{agent\_id}

获取指定 Agent。

**响应：**

```json
{
  "status": "success",
  "agent": {
    "id": "default",
    "name": "默认助手",
    "description": "通用AI助手",
    "system_prompt": "你是一个有帮助的AI助手。",
    "model": "main",
    "temperature": 0.7,
    "max_tokens": 131072,
    "use_memory": true,
    "use_tools": true,
    "vision_enabled": false,
    "memory_scene": "chat",
    "is_default": true
  }
}
```

#### PUT /api/agents/{agent\_id}

更新 Agent。

**请求：**

```json
{
  "name": "更新后的助手",
  "temperature": 0.8
}
```

**响应：**

```json
{
  "status": "success",
  "agent": {
    "id": "agent-abc123",
    "name": "更新后的助手",
    "temperature": 0.8
  },
  "message": "Agent 更新成功"
}
```

#### DELETE /api/agents/{agent\_id}

删除 Agent。

**响应：**

```json
{
  "status": "success",
  "message": "Agent 'agent-abc123' 已删除"
}
```

#### POST /api/agents/{agent\_id}/clone

克隆 Agent。

**响应：**

```json
{
  "status": "success",
  "agent": {
    "id": "agent-def456",
    "name": "默认助手 (副本)",
    "is_default": false
  },
  "message": "Agent 克隆成功"
}
```

#### GET /api/agents/{agent\_id}/stats

获取 Agent 统计。

**响应：**

```json
{
  "status": "success",
  "agent_id": "default",
  "session_count": 5,
  "total_messages": 100
}
```

#### GET /api/agents/{agent\_id}/context

获取 Agent 上下文。

**响应：**

```json
{
  "status": "success",
  "agent_id": "default",
  "has_context": true,
  "session_id": "agent-default",
  "last_active": "2024-01-15T10:30:00",
  "created_at": "2024-01-15T10:00:00",
  "updated_at": "2024-01-15T10:30:00",
  "total_messages": 50,
  "role_counts": {
    "user": 25,
    "assistant": 25
  },
  "recent_messages": [
    {"role": "user", "content": "你好"}
  ]
}
```

#### DELETE /api/agents/{agent\_id}/context

删除 Agent 上下文。

**响应：**

```json
{
  "status": "success",
  "message": "Agent 'default' 的上下文已清空"
}
```

***

### ACP 模块（Agent 通信协议）

#### POST /api/acp/discover

发现 ACP Agent。

**请求：**

```json
{
  "timeout": 5.0
}
```

**响应：**

```json
{
  "status": "success",
  "agents": [
    {
      "agent_id": "remote-agent-001",
      "name": "远程Agent",
      "host": "192.168.1.100",
      "port": 10000
    }
  ],
  "scanned_count": 1,
  "message": "发现 1 个Agents"
}
```

#### GET /api/acp/agents

列出 ACP Agent。

**查询参数：**

- `online_only` (bool, 默认: false)

**响应：**

```json
{
  "status": "success",
  "agents": [
    {
      "agent_id": "local-agent",
      "name": "晨曦",
      "status": "online",
      "last_seen": "2024-01-15T10:30:00"
    }
  ],
  "total": 1
}
```

#### POST /api/acp/connect

连接到 ACP Agent。

**请求：**

```json
{
  "agent_id": "remote-agent-001",
  "host": "192.168.1.100",
  "port": 10000
}
```

**响应：**

```json
{
  "status": "success",
  "connection": {
    "id": "conn-001",
    "local_agent_id": "local-agent",
    "remote_agent_id": "remote-agent-001",
    "remote_agent_name": "远程Agent",
    "host": "192.168.1.100",
    "port": 10000,
    "status": "connecting",
    "connected_at": "2024-01-15T10:00:00"
  },
  "message": "连接请求已发送"
}
```

#### DELETE /api/acp/connect/{connection\_id}

断开 ACP Agent 连接。

**响应：**

```json
{
  "status": "success",
  "message": "连接已断开"
}
```

#### GET /api/acp/connections

列出 ACP 连接。

**响应：**

```json
{
  "status": "success",
  "connections": [
    {
      "id": "conn-001",
      "remote_agent_id": "remote-agent-001",
      "status": "connected"
    }
  ],
  "total": 1
}
```

#### POST /api/acp/groups

创建 ACP 组。

**请求：**

```json
{
  "name": "开发组",
  "description": "开发团队",
  "max_members": 50
}
```

**响应：**

```json
{
  "status": "success",
  "group": {
    "id": "group-001",
    "name": "开发组",
    "description": "开发团队",
    "creator_id": "local-agent",
    "members": ["local-agent"],
    "created_at": "2024-01-15T10:00:00"
  },
  "message": "群组创建成功"
}
```

#### GET /api/acp/groups

列出 ACP 组。

**响应：**

```json
{
  "status": "success",
  "groups": [
    {
      "id": "group-001",
      "name": "开发组",
      "member_count": 3
    }
  ],
  "total": 1
}
```

#### POST /api/acp/groups/{group\_id}/join

加入 ACP 组。

**响应：**

```json
{
  "status": "success",
  "message": "已加入群组"
}
```

#### POST /api/acp/groups/{group\_id}/leave

离开 ACP 组。

**响应：**

```json
{
  "status": "success",
  "message": "已退出群组"
}
```

#### POST /api/acp/send

发送消息给 ACP Agent。

**请求：**

```json
{
  "to_agent_id": "remote-agent-001",
  "content": {"text": "你好"},
  "msg_type": "chat"
}
```

**响应：**

```json
{
  "status": "success",
  "message_id": "msg-001",
  "message": "消息已发送"
}
```

#### POST /api/acp/send/group

发送消息给 ACP 组。

**请求：**

```json
{
  "group_id": "group-001",
  "content": {"text": "大家好"}
}
```

**响应：**

```json
{
  "status": "success",
  "message_id": "msg-002",
  "message": "群消息已发送"
}
```

#### GET /api/acp/messages

获取 ACP 消息。

**查询参数：**

- `agent_id` (string, 可选)
- `group_id` (string, 可选)
- `limit` (int, 默认: 50)

**响应：**

```json
{
  "status": "success",
  "messages": [
    {
      "id": "msg-001",
      "from_agent_id": "remote-agent-001",
      "content": {"text": "你好"},
      "timestamp": "2024-01-15T10:00:00"
    }
  ],
  "total": 1
}
```

#### GET /api/acp/stats

获取 ACP 统计。

**响应：**

```json
{
  "status": "success",
  "statistics": {
    "total_agents": 5,
    "online_agents": 3,
    "total_connections": 2,
    "total_groups": 1,
    "messages_sent": 100,
    "messages_received": 95
  }
}
```

***

### 备份模块

#### GET /api/backups

列出所有备份。

**响应：**

```json
[
  {
    "id": "backup-001",
    "backup_type": "full",
    "status": "completed",
    "created_at": "2024-01-15T10:00:00",
    "completed_at": "2024-01-15T10:05:00",
    "description": "完整备份",
    "total_size": 10485760,
    "compressed_size": 5242880,
    "file_count": 100
  }
]
```

#### POST /api/backups

创建备份。

**请求：**

```json
{
  "backup_type": "full",
  "description": "手动备份"
}
```

**响应：**

```json
{
  "id": "backup-002",
  "backup_type": "full",
  "status": "in_progress",
  "created_at": "2024-01-15T11:00:00",
  "description": "手动备份",
  "total_size": 0,
  "compressed_size": 0,
  "file_count": 0
}
```

#### GET /api/backups/{backup\_id}

获取备份详情。

**响应：**

```json
{
  "id": "backup-001",
  "backup_type": "full",
  "status": "completed",
  "created_at": "2024-01-15T10:00:00",
  "completed_at": "2024-01-15T10:05:00",
  "description": "完整备份",
  "total_size": 10485760,
  "compressed_size": 5242880,
  "file_count": 100
}
```

#### POST /api/backups/{backup\_id}/restore

恢复备份。

**响应：**

```json
{
  "success": true,
  "restored_files": 100,
  "failed_files": 0,
  "error_message": null
}
```

#### DELETE /api/backups/{backup\_id}

删除备份。

**响应：**

```json
{
  "status": "success",
  "message": "备份 backup-001 已删除"
}
```

#### GET /api/backups/stats

获取备份统计。

**响应：**

```json
{
  "total_backups": 5,
  "full_backups": 3,
  "incremental_backups": 2,
  "total_size": 52428800,
  "oldest_backup": "2024-01-01T00:00:00",
  "latest_backup": "2024-01-15T10:00:00"
}
```

#### POST /api/backups/import

导入备份（multipart/form-data）。

**请求：**

- `file`: 备份文件（.zip）

**响应：**

```json
{
  "status": "success",
  "backup": {
    "id": "backup-imported",
    "backup_type": "full",
    "status": "completed"
  }
}
```

#### GET /api/backups/{backup\_id}/export

导出备份文件。

**响应：**
文件下载（application/zip）

***

### 服务模块

#### GET /api/service/status

获取服务状态。

**响应：**

```json
{
  "running": true,
  "pid": 12345,
  "port": 8000,
  "uptime": 3600.5,
  "using_conda": true
}
```

#### POST /api/service/start

启动服务。

**请求：**

```json
{
  "host": "0.0.0.0",
  "port": 8000,
  "log_level": "INFO",
  "reload": false,
  "use_conda": true
}
```

**响应：**

```json
{
  "status": "success",
  "message": "Service started",
  "pid": 12345,
  "port": 8000,
  "using_conda": true
}
```

#### POST /api/service/stop

停止服务。

**响应：**

```json
{
  "status": "success",
  "message": "Service stopped"
}
```

#### POST /api/service/restart

重启服务。

**请求：**

```json
{
  "host": "0.0.0.0",
  "port": 8000,
  "log_level": "INFO",
  "reload": false,
  "use_conda": true
}
```

**响应：**

```json
{
  "status": "success",
  "message": "Service started",
  "pid": 12346,
  "port": 8000,
  "using_conda": true
}
```

#### GET /api/service/logs

获取服务日志。

**查询参数：**

- `lines` (int, 默认: 100)

**响应：**

```json
{
  "status": "success",
  "logs": "2024-01-15 10:00:00 - INFO - Service started\n..."
}
```

#### GET /api/service/config

获取服务配置。

**响应：**

```json
{
  "status": "success",
  "config": {
    "host": "0.0.0.0",
    "port": 8000,
    "log_level": "INFO",
    "debug": false,
    "conda_available": true,
    "models": {
      "main": {"model": "qwen2.5:14b", "provider": "ollama"},
      "summary": {"model": "qwen2.5:7b", "provider": "ollama"},
      "memory": {"model": "qwen2.5:14b", "provider": "ollama"}
    },
    "vector": {
      "backend": "chroma",
      "vector_size": 768
    }
  }
}
```

#### POST /api/service/config

更新服务配置。

**请求：**

```json
{
  "vector": {
    "backend": "milvus_lite"
  }
}
```

**响应：**

```json
{
  "status": "success",
  "message": "Configuration updated, restart to apply changes"
}
```

#### GET /api/service/environment

获取环境信息。

**响应：**

```json
{
  "status": "success",
  "environment": {
    "conda_available": true,
    "conda_python_path": "D:/CX-O/miniconda3/python.exe",
    "conda_activate_script": "D:/CX-O/miniconda3/Scripts/activate.bat",
    "system_python": "C:/Python311/python.exe",
    "platform": "win32"
  }
}
```

#### GET /api/service/startup-command

获取启动命令。

**查询参数：**

- `use_conda` (bool, 默认: true)

**响应：**

```json
{
  "status": "success",
  "command": "D:/CX-O/miniconda3/python.exe",
  "args": ["-m", "uvicorn", "backend.api.app:app", "--host", "0.0.0.0", "--port", "8000"],
  "use_conda": true,
  "conda_available": true,
  "project_root": "D:/CX-O/CXHMS"
}
```

#### GET /api/service/models

获取可用模型列表。

**响应：**

```json
{
  "status": "success",
  "providers": [
    {"id": "main", "name": "qwen2.5:14b", "provider": "ollama", "host": "http://localhost:11434", "enabled": true},
    {"id": "summary", "name": "qwen2.5:7b", "provider": "ollama", "host": "http://localhost:11434", "enabled": true},
    {"id": "memory", "name": "qwen2.5:14b", "provider": "ollama", "host": "http://localhost:11434", "enabled": true}
  ],
  "ollama_models": [
    {"name": "qwen2.5:14b", "size": 9000000000, "modified_at": "2024-01-15T00:00:00"},
    {"name": "qwen2.5:7b", "size": 4500000000, "modified_at": "2024-01-15T00:00:00"}
  ]
}
```

***

## 第二部分：CX-O 网关 HTTP API

基础地址：`http://127.0.0.1:8100`

***

### 健康与统计

#### GET /health

网关健康检查。

**响应：**

```json
{
  "status": "healthy",
  "services": {
    "cxhms": "healthy",
    "asr": "healthy",
    "tts": "healthy"
  }
}
```

#### GET /api/stats

获取网关统计。

**响应：**

```json
{
  "tts_count": 100,
  "asr_count": 150,
  "llm_count": 200,
  "client_count": 5
}
```

***

### 音频文件

#### GET /api/audio/files

列出音频文件。

**响应：**

```json
{
  "status": "success",
  "files": [
    {
      "name": "reference.wav",
      "size": 1048576,
      "created_at": "2024-01-15T10:00:00"
    }
  ]
}
```

#### POST /api/audio/upload

上传音频文件（multipart/form-data）。

**请求：**

- `file`: 音频文件

**响应：**

```json
{
  "status": "success",
  "filename": "uploaded.wav",
  "message": "文件上传成功"
}
```

#### GET /api/audio/files/{filename}

获取指定音频文件。

**响应：**
音频文件流

#### DELETE /api/audio/files/{filename}

删除音频文件。

**响应：**

```json
{
  "status": "success",
  "message": "文件已删除"
}
```

***

### 音频配置

#### GET /api/config/audio

获取音频配置。

**响应：**

```json
{
  "status": "success",
  "config": {
    "ref_audio_path": "path/to/ref.wav",
    "ref_text": "参考文本",
    "speed": 1.0,
    "cross_fade_duration": 0.15,
    "emotion_enabled": true,
    "effects_enabled": true,
    "emotion_voices": {
      "happy": "path/to/happy.wav",
      "sad": "path/to/sad.wav"
    }
  }
}
```

#### POST /api/config/audio

更新音频配置。

**请求：**

```json
{
  "ref_audio_path": "path/to/new_ref.wav",
  "speed": 1.2
}
```

**响应：**

```json
{
  "status": "success",
  "message": "音频配置已更新"
}
```

#### GET /api/audio/emotions/list

获取情感配置列表。

**响应：**

```json
{
  "status": "success",
  "emotions": ["happy", "sad", "angry", "neutral", "surprised"]
}
```

***

### 服务配置

#### GET /api/config/services

获取服务配置。

**响应：**

```json
{
  "status": "success",
  "config": {
    "cxhms": {
      "url": "ws://127.0.0.1:8000/api/ws",
      "http_url": "http://127.0.0.1:8000",
      "timeout": 60
    },
    "asr": {
      "url": "http://127.0.0.1:8001",
      "timeout": 120
    },
    "tts": {
      "url": "http://127.0.0.1:8002",
      "timeout": 120
    },
    "index_tts": {
      "url": "http://127.0.0.1:8004",
      "enabled": true,
      "timeout": 180
    }
  }
}
```

#### POST /api/config/services

更新服务配置。

**请求：**

```json
{
  "asr": {
    "url": "http://192.168.1.100:8001"
  }
}
```

**响应：**

```json
{
  "status": "success",
  "message": "服务配置已更新"
}
```

***

### TTS（语音合成）

#### POST /api/tts/synthesize

合成语音（非流式）。

**请求：**

```json
{
  "text": "你好，你好吗？",
  "ref_audio": "base64编码的音频",
  "ref_text": "参考文本",
  "speed": 1.0
}
```

**响应：**

```json
{
  "status": "success",
  "audio_data": "base64编码的wav",
  "format": "wav"
}
```

#### POST /api/tts/synthesize-stream

合成语音（流式，SSE）。

**请求：**

```json
{
  "text": "你好，你好吗？",
  "ref_audio": "base64编码的音频",
  "ref_text": "参考文本",
  "speed": 1.0,
  "emotion_enabled": false,
  "effects_enabled": false
}
```

**响应（SSE）：**

```
data: {"type": "chunk", "text_segment": "你好，", "audio_data": "base64...", "chunk_index": 0, "is_final": false}

data: {"type": "chunk", "text_segment": "你好吗？", "audio_data": "base64...", "chunk_index": 1, "is_final": true}
```

***

### ASR（语音识别）

#### POST /api/asr/speech-to-text

语音转文字。

**请求（multipart/form-data）：**

- `file`: 音频文件
- `language`: 语言代码（默认: "auto"）

**请求（JSON）：**

```json
{
  "audio": "base64编码的音频",
  "language": "auto"
}
```

**响应：**

```json
{
  "status": "success",
  "text": "识别的文字",
  "language": "zh"
}
```

***

### IndexTTS（情感语音合成）

#### GET /api/index-tts/status

获取 IndexTTS 服务状态。

**响应：**

```json
{
  "status": "success",
  "available": true,
  "models_loaded": true
}
```

#### POST /api/index-tts/synthesize

使用 IndexTTS 合成。

**请求：**

```json
{
  "text": "带情感的问候",
  "ref_audio": "path/to/ref.wav",
  "emotion": "happy",
  "emotion_intensity": 0.5,
  "speed": 1.0,
  "pitch": 0.0
}
```

**响应：**

```json
{
  "status": "success",
  "audio_data": "base64编码的wav",
  "format": "wav"
}
```

#### POST /api/audio/generate-emotions

从参考音频生成情感音频。

**请求：**

```json
{
  "ref_audio": "path/to/ref.wav",
  "ref_text": "参考文本",
  "emotions": [
    {"type": "happy", "intensity": 0.5},
    {"type": "sad", "intensity": 0.5}
  ]
}
```

**响应：**

```json
{
  "status": "success",
  "generated": [
    {"emotion": "happy", "audio_path": "path/to/happy.wav"},
    {"emotion": "sad", "audio_path": "path/to/sad.wav"}
  ]
}
```

***

### 配置接口

#### GET /api/config/vad

获取 VAD（语音活动检测）配置。

**响应：**

```json
{
  "config": {
    "vad": {
      "mode": "webrtc",
      "sample_rate": 16000,
      "frame_duration_ms": 30,
      "silence_threshold_ms": 500,
      "speech_threshold_ms": 300
    },
    "audio_stream": {
      "asr_interval_ms": 500
    },
    "agent_interrupt": {
      "enabled": true,
      "interrupt_threshold_ms": 500,
      "min_speech_duration_ms": 1000,
      "interrupt_cooldown_ms": 3000
    }
  }
}
```

#### POST /api/config/vad

更新 VAD 配置。

**请求：**

```json
{
  "vad": {
    "mode": "silero"
  }
}
```

**响应：**

```json
{
  "status": "success",
  "message": "VAD配置已更新"
}
```

#### GET /api/config/danmaku

获取弹幕配置。

**响应：**

```json
{
  "status": "success",
  "config": {
    "enabled": true,
    "max_length": 100,
    "filter_words": []
  }
}
```

#### POST /api/config/danmaku

更新弹幕配置。

**请求：**

```json
{
  "enabled": true,
  "max_length": 200
}
```

**响应：**

```json
{
  "status": "success",
  "message": "弹幕配置已更新"
}
```

#### GET /api/config/firewall

获取防火墙配置。

**响应：**

```json
{
  "status": "success",
  "config": {
    "enabled": true,
    "block_patterns": ["广告", "刷屏"],
    "max_frequency": 10
  }
}
```

#### POST /api/config/firewall

更新防火墙配置。

**请求：**

```json
{
  "enabled": true,
  "block_patterns": ["广告"]
}
```

**响应：**

```json
{
  "status": "success",
  "message": "防火墙配置已更新"
}
```

#### GET /api/config/firewall\_v3

获取 v3 防火墙配置（打断设置）。

**响应：**

```json
{
  "config": {
    "interrupt": {
      "enabled": true,
      "mode": "main_llm",
      "main_llm": {
        "enabled": true,
        "prompt": "判断是否需要打断..."
      },
      "independent_llm": {
        "enabled": false,
        "model": "qwen2.5:1.5b"
      }
    }
  }
}
```

#### POST /api/config/firewall\_v3

更新 v3 防火墙配置。

**请求：**

```json
{
  "interrupt": {
    "enabled": true,
    "mode": "independent_llm"
  }
}
```

**响应：**

```json
{
  "status": "success",
  "message": "防火墙v3配置已更新"
}
```

***

### 直播客户端

#### GET /api/live/status

获取直播客户端状态。

**响应：**

```json
{
  "status": "success",
  "clients": [
    {
      "client_id": "client-001",
      "client_type": "web",
      "room_id": "12345678",
      "connected_at": "2024-01-15T10:00:00"
    }
  ],
  "total": 1
}
```

#### POST /api/live/connect

连接直播客户端。

**请求：**

```json
{
  "client_type": "web",
  "room_id": "12345678",
  "supported_markers": ["live2d", "emotion"],
  "marker_config": {}
}
```

**响应：**

```json
{
  "status": "success",
  "client_id": "client-002",
  "message": "客户端已连接"
}
```

#### DELETE /api/live/disconnect/{client\_id}

断开直播客户端连接。

**响应：**

```json
{
  "status": "success",
  "message": "客户端已断开"
}
```

***

## 第三部分：CXHMS WebSocket API

地址：`ws://127.0.0.1:8000`

### WebSocket 端点

#### WS /api/ws

通用 WebSocket 端点。

**Query 参数：**

- `client_id` (string, 可选) - 客户端ID
- `token` (string, 可选) - 认证令牌

#### WS /api/ws/{agent\_id}

Agent 专用 WebSocket 端点（推荐使用）。

**Path 参数：**

- `agent_id` - Agent ID

**Query 参数：**

- `timeout` (int, 默认: 60) - 离线超时时间（秒）

#### WS /api/ws/chat

聊天专用 WebSocket 端点。

**Query 参数：**

- `session_id` (string, 可选) - 会话ID
- `agent_id` (string, 默认: "default") - Agent ID

### 消息格式

#### 请求

```json
{
  "action": "module.action",
  "request_id": "uuid字符串",
  "data": {}
}
```

#### 响应

```json
{
  "type": "response",
  "request_id": "uuid字符串",
  "action": "module.action",
  "status": "success",
  "data": {}
}
```

#### 错误响应

```json
{
  "type": "error",
  "request_id": "uuid字符串",
  "action": "module.action",
  "code": "错误码",
  "message": "错误描述"
}
```

#### 流式响应

```json
{
  "type": "stream",
  "request_id": "uuid字符串",
  "chunk_index": 0,
  "action": "module.action",
  "data": {
    "content": "文本内容",
    "done": false
  },
  "is_final": false
}
```

***

## 第四部分：CX-O 网关 WebSocket API

地址：`ws://127.0.0.1:8100`

### WebSocket 端点

#### WS /ws

通用 WebSocket 端点（用于音频处理、聊天等）。

#### WS /ws/live

直播客户端专用端点（支持伪全双工通信）。

### 消息格式

#### chat.message

发送文本消息（非流式）。

**请求：**

```json
{
  "action": "chat.message",
  "request_id": "xxx",
  "data": {
    "message": "你好",
    "agent_id": "default"
  }
}
```

**响应：**

```json
{
  "type": "response",
  "request_id": "xxx",
  "action": "chat.message",
  "status": "success",
  "data": {
    "content": "你好！有什么可以帮助你的吗？"
  }
}
```

#### chat.stream

发送消息并接收流式响应。

**请求：**

```json
{
  "action": "chat.stream",
  "request_id": "xxx",
  "data": {
    "text": "你好",
    "agent_id": "default"
  }
}
```

**响应（流式）：**

```json
{
  "type": "stream",
  "request_id": "xxx",
  "chunk_index": 0,
  "data": {
    "content": "你好"
  },
  "is_final": false
}
```

#### chat.multimodal

发送多模态消息。

**请求：**

```json
{
  "action": "chat.multimodal",
  "request_id": "xxx",
  "data": {
    "message": "这张图片是什么？",
    "agent_id": "default",
    "images": ["base64编码的图片"]
  }
}
```

***

### 记忆动作

#### memory.list

获取记忆列表。

**请求：**

```json
{
  "action": "memory.list",
  "request_id": "xxx",
  "data": {
    "limit": 20,
    "type": "long_term"
  }
}
```

**响应：**

```json
{
  "type": "response",
  "request_id": "xxx",
  "action": "memory.list",
  "status": "success",
  "data": {
    "memories": [
      {"id": 1, "content": "记忆内容"}
    ]
  }
}
```

#### memory.create

创建记忆。

**请求：**

```json
{
  "action": "memory.create",
  "request_id": "xxx",
  "data": {
    "content": "新记忆",
    "type": "long_term",
    "importance": 3
  }
}
```

**响应：**

```json
{
  "type": "response",
  "request_id": "xxx",
  "action": "memory.create",
  "status": "success",
  "data": {
    "memory_id": 123
  }
}
```

#### memory.delete

删除记忆。

**请求：**

```json
{
  "action": "memory.delete",
  "request_id": "xxx",
  "data": {
    "memory_id": 123
  }
}
```

**响应：**

```json
{
  "type": "response",
  "request_id": "xxx",
  "action": "memory.delete",
  "status": "success",
  "data": {}
}
```

#### memory.search

搜索记忆。

**请求：**

```json
{
  "action": "memory.search",
  "request_id": "xxx",
  "data": {
    "query": "关键词",
    "limit": 10
  }
}
```

**响应：**

```json
{
  "type": "response",
  "request_id": "xxx",
  "action": "memory.search",
  "status": "success",
  "data": {
    "memories": [
      {"id": 1, "content": "匹配的记忆", "score": 0.95}
    ]
  }
}
```

#### memory.get

获取指定记忆。

**请求：**

```json
{
  "action": "memory.get",
  "request_id": "xxx",
  "data": {
    "memory_id": 123
  }
}
```

**响应：**

```json
{
  "type": "response",
  "request_id": "xxx",
  "action": "memory.get",
  "status": "success",
  "data": {
    "memory": {
      "id": 123,
      "content": "记忆内容",
      "type": "long_term"
    }
  }
}
```

#### memory.update

更新记忆。

**请求：**

```json
{
  "action": "memory.update",
  "request_id": "xxx",
  "data": {
    "memory_id": 123,
    "content": "更新后的内容"
  }
}
```

**响应：**

```json
{
  "type": "response",
  "request_id": "xxx",
  "action": "memory.update",
  "status": "success",
  "data": {}
}
```

***

### 工具动作

#### tools.list

列出可用工具。

**请求：**

```json
{
  "action": "tools.list",
  "request_id": "xxx",
  "data": {}
}
```

**响应：**

```json
{
  "type": "response",
  "request_id": "xxx",
  "action": "tools.list",
  "status": "success",
  "data": {
    "tools": [
      {"name": "calculator", "description": "数学计算"}
    ]
  }
}
```

#### tools.call

调用工具。

**请求：**

```json
{
  "action": "tools.call",
  "request_id": "xxx",
  "data": {
    "tool_name": "calculator",
    "arguments": {
      "expression": "1 + 1"
    }
  }
}
```

**响应：**

```json
{
  "type": "response",
  "request_id": "xxx",
  "action": "tools.call",
  "status": "success",
  "data": {
    "result": 2
  }
}
```

#### tools.register

注册新工具。

**请求：**

```json
{
  "action": "tools.register",
  "request_id": "xxx",
  "data": {
    "name": "my_tool",
    "description": "自定义工具",
    "parameters": {
      "type": "object",
      "properties": {
        "input": {"type": "string"}
      }
    }
  }
}
```

**响应：**

```json
{
  "type": "response",
  "request_id": "xxx",
  "action": "tools.register",
  "status": "success",
  "data": {}
}
```

***

### 插件动作

#### plugin.register

注册插件。

**请求：**

```json
{
  "action": "plugin.register",
  "request_id": "xxx",
  "data": {
    "name": "weather_plugin",
    "version": "1.0.0",
    "tools": [
      {"name": "get_weather", "description": "获取天气"}
    ]
  }
}
```

**响应：**

```json
{
  "type": "response",
  "request_id": "xxx",
  "action": "plugin.register",
  "status": "success",
  "data": {}
}
```

#### plugin.heartbeat

发送插件心跳。

**请求：**

```json
{
  "action": "plugin.heartbeat",
  "request_id": "xxx",
  "data": {
    "name": "weather_plugin"
  }
}
```

**响应：**

```json
{
  "type": "response",
  "request_id": "xxx",
  "action": "plugin.heartbeat",
  "status": "success",
  "data": {}
}
```

#### plugin.list

列出插件。

**请求：**

```json
{
  "action": "plugin.list",
  "request_id": "xxx",
  "data": {}
}
```

**响应：**

```json
{
  "type": "response",
  "request_id": "xxx",
  "action": "plugin.list",
  "status": "success",
  "data": {
    "plugins": [
      {"name": "weather_plugin", "status": "active"}
    ]
  }
}
```

#### plugin.unregister

注销插件。

**请求：**

```json
{
  "action": "plugin.unregister",
  "request_id": "xxx",
  "data": {
    "name": "weather_plugin"
  }
}
```

**响应：**

```Java
{
  "type": "response",
  "request_id": "xxx",
  "action": "plugin.unregister",
  "status": "success",
  "data": {}
}
```

***

### 上下文动作

#### context.get

获取上下文。

**请求：**

```json
{
  "action": "context.get",
  "request_id": "xxx",
  "data": {
    "session_id": "session-001"
  }
}
```

**响应：**

```json
{
  "type": "response",
  "request_id": "xxx",
  "action": "context.get",
  "status": "success",
  "data": {
    "messages": [
      {"role": "user", "content": "你好"}
    ]
  }
}
```

#### context.append

追加上下文。

**请求：**

```json
{
  "action": "context.append",
  "request_id": "xxx",
  "data": {
    "session_id": "session-001",
    "role": "user",
    "content": "新消息"
  }
}
```

**响应：**

```json
{
  "type": "response",
  "request_id": "xxx",
  "action": "context.append",
  "status": "success",
  "data": {}
}
```

#### context.clear

清空上下文。

**请求：**

```json
{
  "action": "context.clear",
  "request_id": "xxx",
  "data": {
    "session_id": "session-001"
  }
}
```

**响应：**

```json
{
  "type": "response",
  "request_id": "xxx",
  "action": "context.clear",
  "status": "success",
  "data": {}
}
```

#### context.set

设置上下文。

**请求：**

```json
{
  "action": "context.set",
  "request_id": "xxx",
  "data": {
    "session_id": "session-001",
    "messages": [
      {"role": "user", "content": "重置后的消息"}
    ]
  }
}
```

**响应：**

```json
{
  "type": "response",
  "request_id": "xxx",
  "action": "context.set",
  "status": "success",
  "data": {}
}
```

***

### ACP 动作

#### acp.connect

连接到 ACP Agent。

**请求：**

```json
{
  "action": "acp.connect",
  "request_id": "xxx",
  "data": {
    "agent_id": "remote-agent",
    "host": "192.168.1.100",
    "port": 10000
  }
}
```

**响应：**

```json
{
  "type": "response",
  "request_id": "xxx",
  "action": "acp.connect",
  "status": "success",
  "data": {
    "connection_id": "conn-001"
  }
}
```

#### acp.disconnect

断开 ACP Agent 连接。

**请求：**

```json
{
  "action": "acp.disconnect",
  "request_id": "xxx",
  "data": {
    "connection_id": "conn-001"
  }
}
```

**响应：**

```json
{
  "type": "response",
  "request_id": "xxx",
  "action": "acp.disconnect",
  "status": "success",
  "data": {}
}
```

#### acp.connections

列出连接。

**请求：**

```json
{
  "action": "acp.connections",
  "request_id": "xxx",
  "data": {}
}
```

**响应：**

```json
{
  "type": "response",
  "request_id": "xxx",
  "action": "acp.connections",
  "status": "success",
  "data": {
    "connections": [
      {"id": "conn-001", "remote_agent_id": "remote-agent"}
    ]
  }
}
```

#### acp.status

获取 ACP 状态。

**请求：**

```json
{
  "action": "acp.status",
  "request_id": "xxx",
  "data": {}
}
```

**响应：**

```json
{
  "type": "response",
  "request_id": "xxx",
  "action": "acp.status",
  "status": "success",
  "data": {
    "total_agents": 5,
    "active_connections": 2
  }
}
```

***

### MCP 动作

#### mcp.connect

连接到 MCP 服务器。

**请求：**

```json
{
  "action": "mcp.connect",
  "request_id": "xxx",
  "data": {
    "name": "filesystem",
    "command": "mcp-filesystem",
    "args": ["/path"]
  }
}
```

**响应：**

```json
{
  "type": "response",
  "request_id": "xxx",
  "action": "mcp.connect",
  "status": "success",
  "data": {}
}
```

#### mcp.disconnect

断开 MCP 服务器连接。

**请求：**

```json
{
  "action": "mcp.disconnect",
  "request_id": "xxx",
  "data": {
    "name": "filesystem"
  }
}
```

**响应：**

```json
{
  "type": "response",
  "request_id": "xxx",
  "action": "mcp.disconnect",
  "status": "success",
  "data": {}
}
```

#### mcp.tools

获取 MCP 工具。

**请求：**

```json
{
  "action": "mcp.tools",
  "request_id": "xxx",
  "data": {
    "server_name": "filesystem"
  }
}
```

**响应：**

```json
{
  "type": "response",
  "request_id": "xxx",
  "action": "mcp.tools",
  "status": "success",
  "data": {
    "tools": [
      {"name": "read_file", "description": "读取文件"}
    ]
  }
}
```

#### mcp.call

调用 MCP 工具。

**请求：**

```json
{
  "action": "mcp.call",
  "request_id": "xxx",
  "data": {
    "server_name": "filesystem",
    "tool_name": "read_file",
    "arguments": {
      "path": "/path/to/file"
    }
  }
}
```

**响应：**

```json
{
  "type": "response",
  "request_id": "xxx",
  "action": "mcp.call",
  "status": "success",
  "data": {
    "result": "文件内容..."
  }
}
```

#### mcp.status

获取 MCP 状态。

**请求：**

```json
{
  "action": "mcp.status",
  "request_id": "xxx",
  "data": {}
}
```

**响应：**

```json
{
  "type": "response",
  "request_id": "xxx",
  "action": "mcp.status",
  "status": "success",
  "data": {
    "servers": [
      {"name": "filesystem", "status": "running"}
    ]
  }
}
```

***

### 配置动作

#### config.get

获取配置。

**请求：**

```json
{
  "action": "config.get",
  "request_id": "xxx",
  "data": {
    "key": "audio"
  }
}
```

**响应：**

```json
{
  "type": "response",
  "request_id": "xxx",
  "action": "config.get",
  "status": "success",
  "data": {
    "config": {
      "speed": 1.0
    }
  }
}
```

#### config.set

设置配置。

**请求：**

```json
{
  "action": "config.set",
  "request_id": "xxx",
  "data": {
    "key": "audio.speed",
    "value": 1.2
  }
}
```

**响应：**

```json
{
  "type": "response",
  "request_id": "xxx",
  "action": "config.set",
  "status": "success",
  "data": {}
}
```

#### config.reset

重置配置。

**请求：**

```json
{
  "action": "config.reset",
  "request_id": "xxx",
  "data": {}
}
```

**响应：**

```json
{
  "type": "response",
  "request_id": "xxx",
  "action": "config.reset",
  "status": "success",
  "data": {}
}
```

***

### 指标动作

#### metrics.get

获取指标。

**请求：**

```json
{
  "action": "metrics.get",
  "request_id": "xxx",
  "data": {}
}
```

**响应：**

```json
{
  "type": "response",
  "request_id": "xxx",
  "action": "metrics.get",
  "status": "success",
  "data": {
    "requests_total": 1000,
    "requests_success": 990,
    "requests_failed": 10
  }
}
```

#### metrics.requests

获取请求指标。

**请求：**

```json
{
  "action": "metrics.requests",
  "request_id": "xxx",
  "data": {}
}
```

**响应：**

```json
{
  "type": "response",
  "request_id": "xxx",
  "action": "metrics.requests",
  "status": "success",
  "data": {
    "by_action": {
      "chat.stream": 500,
      "memory.search": 200
    }
  }
}
```

#### metrics.history

获取指标历史。

**请求：**

```json
{
  "action": "metrics.history",
  "request_id": "xxx",
  "data": {
    "duration": "1h"
  }
}
```

**响应：**

```json
{
  "type": "response",
  "request_id": "xxx",
  "action": "metrics.history",
  "status": "success",
  "data": {
    "history": [
      {"timestamp": "2024-01-15T10:00:00", "requests": 100}
    ]
  }
}
```

***

### 系统动作

#### system.health

获取系统健康状态。

**请求：**

```json
{
  "action": "system.health",
  "request_id": "xxx",
  "data": {}
}
```

**响应：**

```json
{
  "type": "response",
  "request_id": "xxx",
  "action": "system.health",
  "status": "success",
  "data": {
    "status": "healthy",
    "components": {
      "memory": "healthy",
      "context": "healthy"
    }
  }
}
```

#### system.status

获取系统状态。

**请求：**

```json
{
  "action": "system.status",
  "request_id": "xxx",
  "data": {}
}
```

**响应：**

```json
{
  "type": "response",
  "request_id": "xxx",
  "action": "system.status",
  "status": "success",
  "data": {
    "uptime": 3600,
    "version": "1.0.0",
    "connections": 5
  }
}
```

#### system.info

获取系统信息。

**请求：**

```json
{
  "action": "system.info",
  "request_id": "xxx",
  "data": {}
}
```

**响应：**

```json
{
  "type": "response",
  "request_id": "xxx",
  "action": "system.info",
  "status": "success",
  "data": {
    "version": "1.0.0",
    "python_version": "3.11.0",
    "platform": "Windows"
  }
}
```

***

### ASR 动作

#### asr.recognize

识别语音。

**请求：**

```json
{
  "action": "asr.recognize",
  "request_id": "xxx",
  "data": {
    "audio": "base64编码的pcm",
    "language": "auto"
  }
}
```

**响应：**

```json
{
  "type": "response",
  "request_id": "xxx",
  "action": "asr.recognize",
  "status": "success",
  "data": {
    "text": "识别的文字",
    "language": "zh"
  }
}
```

#### asr.recognize\_base64

识别语音（base64 编码）。

**请求：**

```json
{
  "action": "asr.recognize_base64",
  "request_id": "xxx",
  "data": {
    "audio": "base64编码的音频",
    "language": "auto"
  }
}
```

**响应：**

```json
{
  "type": "response",
  "request_id": "xxx",
  "action": "asr.recognize_base64",
  "status": "success",
  "data": {
    "text": "识别的文字",
    "language": "zh"
  }
}
```

#### asr.stream

实时音频流（带 VAD 检测）。

**请求：**

```json
{
  "action": "asr_stream",
  "request_id": "xxx",
  "data": {
    "audio": "base64编码的pcm",
    "reset": false
  }
}
```

**VAD 状态响应：**

```json
{
  "type": "vad_status",
  "data": {
    "status": "speech_start",
    "speech_duration_ms": 1500
  }
}
```

**VAD 帧响应：**

```json
{
  "type": "vad_frame",
  "data": {
    "is_speaking": true,
    "speech_probability": 0.85,
    "speech_duration_ms": 500
  }
}
```

**ASR 结果响应：**

```json
{
  "type": "response",
  "action": "asr_stream_result",
  "data": {
    "text": "识别的文字",
    "is_final": false
  }
}
```

**Agent 打断用户响应：**

```json
{
  "type": "agent_interrupt_user",
  "data": {
    "should_reply": true,
    "reply_content": "让我来回答..."
  }
}
```

***

### TTS 动作

#### tts.synthesize

合成语音（非流式）。

**请求：**

```json
{
  "action": "tts.synthesize",
  "request_id": "xxx",
  "data": {
    "text": "你好",
    "ref_audio": "base64编码的音频",
    "ref_text": "参考文本"
  }
}
```

**响应：**

```json
{
  "type": "response",
  "request_id": "xxx",
  "action": "tts.synthesize",
  "status": "success",
  "data": {
    "audio_data": "base64编码的音频",
    "format": "wav"
  }
}
```

#### tts.synthesize\_stream

合成语音（流式）。

**请求：**

```json
{
  "action": "tts.synthesize_stream",
  "request_id": "xxx",
  "data": {
    "text": "带情感的问候",
    "emotion_enabled": true,
    "effects_enabled": true
  }
}
```

**流式响应：**

```json
{
  "type": "stream",
  "request_id": "xxx",
  "chunk_index": 0,
  "data": {
    "text_segment": "你好",
    "audio_data": "base64编码的音频",
    "emotion": "happy",
    "is_effect": false,
    "is_final": false
  },
  "is_final": false
}
```

#### tts.voices

获取可用的 TTS 声音列表。

**请求：**

```json
{
  "action": "tts.voices",
  "request_id": "xxx",
  "data": {}
}
```

**响应：**

```json
{
  "type": "response",
  "request_id": "xxx",
  "action": "tts.voices",
  "status": "success",
  "data": {
    "voices": [
      {"id": "default", "name": "默认声音"}
    ]
  }
}
```

***

### 情感动作

#### emotions.list

列出可用情感。

**请求：**

```json
{
  "action": "emotions.list",
  "request_id": "xxx",
  "data": {}
}
```

**响应：**

```json
{
  "type": "response",
  "request_id": "xxx",
  "action": "emotions.list",
  "status": "success",
  "data": {
    "emotions": ["happy", "sad", "angry", "neutral", "surprised"]
  }
}
```

#### emotions.parse

从文本解析情感。

**请求：**

```json
{
  "action": "emotions.parse",
  "request_id": "xxx",
  "data": {
    "text": "今天真是太开心了！"
  }
}
```

**响应：**

```json
{
  "type": "response",
  "request_id": "xxx",
  "action": "emotions.parse",
  "status": "success",
  "data": {
    "segments": [
      {"text": "今天真是太开心了！", "emotion": "happy"}
    ]
  }
}
```

***

### 音效动作

#### effects.list

列出可用音效。

**请求：**

```json
{
  "action": "effects.list",
  "request_id": "xxx",
  "data": {}
}
```

**响应：**

```json
{
  "type": "response",
  "request_id": "xxx",
  "action": "effects.list",
  "status": "success",
  "data": {
    "effects": ["typing", "notification", "click"]
  }
}
```

#### effects.parse

从文本解析音效。

**请求：**

```json
{
  "action": "effects.parse",
  "request_id": "xxx",
  "data": {
    "text": "[typing]你好[/typing]"
  }
}
```

**响应：**

```json
{
  "type": "response",
  "request_id": "xxx",
  "action": "effects.parse",
  "status": "success",
  "data": {
    "segments": [
      {"type": "effect", "effect_name": "typing", "is_effect": true}
    ]
  }
}
```

***

### 弹幕动作

#### danmaku.list

获取弹幕列表。

**请求：**

```json
{
  "action": "danmaku.list",
  "request_id": "xxx",
  "data": {
    "limit": 50
  }
}
```

**响应：**

```json
{
  "type": "response",
  "request_id": "xxx",
  "action": "danmaku.list",
  "status": "success",
  "data": {
    "danmaku": [
      {"content": "弹幕内容", "user": {"uid": "123"}}
    ]
  }
}
```

#### danmaku.add

添加弹幕。

**请求：**

```json
{
  "action": "danmaku.add",
  "request_id": "xxx",
  "data": {
    "content": "新弹幕",
    "user": {
      "uid": "123",
      "username": "用户"
    }
  }
}
```

**响应：**

```json
{
  "type": "response",
  "request_id": "xxx",
  "action": "danmaku.add",
  "status": "success",
  "data": {}
}
```

#### danmaku.clear

清空弹幕。

**请求：**

```json
{
  "action": "danmaku.clear",
  "request_id": "xxx",
  "data": {}
}
```

**响应：**

```json
{
  "type": "response",
  "request_id": "xxx",
  "action": "danmaku.clear",
  "status": "success",
  "data": {}
}
```

***

### 直播 WebSocket 端点

地址：`ws://127.0.0.1:8100/ws/live`

直播客户端专用的 WebSocket 端点，支持伪全双工通信（TTS 播放时可接收音频并打断）。

#### 连接消息

**客户端 → 服务端**

```json
{
  "type": "connect",
  "data": {
    "client_type": "web",
    "room_id": "12345678",
    "supported_markers": ["live2d", "emotion"],
    "marker_config": {}
  }
}
```

**服务端 → 客户端**

```json
{
  "type": "ack",
  "client_id": "uuid-string",
  "status": "connected"
}
```

#### 弹幕消息

**客户端 → 服务端**

```json
{
  "type": "danmaku",
  "data": {
    "content": "弹幕内容",
    "user": {
      "uid": "12345",
      "username": "用户名",
      "badge_level": 10,
      "guard_level": 1
    }
  }
}
```

**服务端 → 客户端**

```json
{
  "type": "danmaku_result",
  "data": {
    "original_content": "弹幕内容",
    "decision": "passive",
    "added_to_context": true,
    "reply_triggered": false,
    "user": {
      "uid": "12345",
      "username": "用户名"
    }
  }
}
```

#### TTS 播放状态通知（伪全双工支持）

**客户端 → 服务端：TTS 开始播放**

```json
{
  "type": "tts_start",
  "data": {
    "request_id": "tts-request-uuid"
  }
}
```

**客户端 → 服务端：TTS 播放结束**

```json
{
  "type": "tts_end"
}
```

#### 音频流消息（伪全双工支持）

**客户端 → 服务端**

```json
{
  "type": "audio_stream",
  "data": {
    "audio": "base64编码的PCM音频数据",
    "reset": false
  }
}
```

#### VAD 状态响应

**服务端 → 客户端**

```json
{
  "type": "vad_status",
  "data": {
    "status": "speech_start",
    "speech_duration_ms": 1500
  }
}
```

`status` 可能的值：

- `speech_start` - 检测到用户开始说话
- `speech_end` - 检测到用户停止说话

#### ASR 识别结果响应

**服务端 → 客户端**

```json
{
  "type": "asr_result",
  "data": {
    "text": "识别的文字",
    "language": "zh",
    "is_final": false
  }
}
```

#### TTS 打断响应

**服务端 → 客户端**

```json
{
  "type": "tts_interrupt",
  "data": {
    "reason": "user_speech_detected",
    "asr_text": "用户说的话"
  }
}
```

`reason` 可能的值：

- `user_speech` - 用户说话触发打断
- `user_speech_detected` - 检测到用户语音

#### 打断后的新回复

**服务端 → 客户端**

```json
{
  "type": "interrupt_reply",
  "data": {
    "content": "新的回复内容"
  }
}
```

#### 文本消息（CXHMS 回复）

**服务端 → 客户端**

```json
{
  "type": "text",
  "data": {
    "content": "回复的文本内容",
    "chunk_index": 0,
    "is_final": false
  }
}
```

#### 前端标记消息

**服务端 → 客户端**

```json
{
  "type": "frontend_marker",
  "data": {
    "marker_type": "emotion",
    "marker_content": {
      "action": "happy",
      "duration": 2.0,
      "params": {}
    },
    "split_index": 0
  }
}
```

#### 伪全双工工作流程

```
┌─────────────────────────────────────────────────────────────────┐
│                    伪全双工通信流程                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  客户端                              服务端                      │
│  ──────                              ──────                      │
│    │                                   │                         │
│    │──── tts_start ──────────────────►│ _is_tts_playing = True  │
│    │                                   │                         │
│    │──── audio_stream ───────────────►│ VAD 检测                │
│    │                                   │    ↓                    │
│    │                                   │ ASR 识别                │
│    │                                   │    ↓                    │
│    │                                   │ LLM 判断打断            │
│    │◄─── tts_interrupt ───────────────│    ↓ (需要打断)         │
│    │◄─── interrupt_reply ─────────────│ 新回复内容              │
│    │                                   │                         │
│    │──── tts_end ────────────────────►│ _is_tts_playing = False │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

#### 二进制音频帧

客户端也可以直接发送二进制音频数据（PCM 格式）：

```
WebSocket Binary Frame: <PCM audio bytes>
```

服务端会自动识别并处理为音频帧。

***

## 错误码

| 错误码                  | 说明       |
| -------------------- | -------- |
| INVALID\_REQUEST     | 无效的请求格式  |
| MISSING\_PARAMETER   | 缺少必要参数   |
| SERVICE\_UNAVAILABLE | 服务不可用    |
| ASR\_ERROR           | 语音识别错误   |
| TTS\_ERROR           | 语音合成错误   |
| LLM\_ERROR           | LLM 调用错误 |
| TIMEOUT              | 请求超时     |
| NOT\_FOUND           | 资源未找到    |
| UNAUTHORIZED         | 未授权访问    |
| INTERNAL\_ERROR      | 内部服务器错误  |

***

## 认证

部分接口需要认证。在 Authorization 头中包含 token：

```
Authorization: Bearer <token>
```

Token 存储在 localStorage 中，键名为 `cxhms-token`。
