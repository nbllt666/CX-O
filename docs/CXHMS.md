# CXHMS 后端服务

## 概述

CXHMS (CX-O History & Memory Service) 是系统的核心后端服务，提供 Agent 管理、记忆管理、上下文管理、工具调用和 ACP 协议通信等功能。

## 入口文件

**文件**：`CXHMS/backend/api/app.py`

## 核心组件

### 1. 记忆管理系统 (MemoryManager)

**位置**：`backend/core/memory/manager.py`

**职责**：
- 记忆 CRUD 操作
- 向量搜索（语义搜索）
- 混合搜索（向量+关键词）
- 三维评分（重要性、时间、相关性）
- 记忆衰减计算
- 记忆召回与重激活
- 批量操作支持

**数据模型**：
```python
class Memory:
    id: int
    type: str  # long_term, short_term, permanent
    content: str
    importance: int  # 1-5
    importance_score: float
    decay_type: str
    reactivation_count: int
    emotion_score: float
    tags: List[str]
    created_at: datetime
```

**存储架构**：
- **SQLite**：结构化数据存储
- **向量存储**：Milvus Lite / ChromaDB / Qdrant / Weaviate

### 2. 上下文管理系统 (ContextManager)

**位置**：`backend/core/context/manager.py`

**职责**：
- 会话管理
- 消息历史存储
- Mono 上下文（临时上下文）
- 上下文摘要生成

**特性**：
- LRU 缓存（100 条上限）
- 过期自动清理
- 工作区隔离

### 3. 工具系统 (Tools System)

**位置**：
- `backend/core/tools/registry.py`
- `backend/core/tools/mcp.py`

**职责**：
- 工具注册与发现
- MCP 服务器管理
- 工具调用执行
- OpenAI Functions 兼容

**MCP 服务器管理**：
- 进程生命周期管理
- HTTP 端点通信
- 工具自动同步
- 健康检查

### 4. ACP 互联系统 (ACPManager)

**位置**：`backend/core/acp/manager.py`

**职责**：
- Agent 发现（UDP 广播）
- 连接管理
- 群组管理
- 消息传递

**通信协议**：
- **发现**：UDP 广播（端口 9998/9999）
- **连接**：HTTP/REST API
- **消息**：异步消息队列

### 5. LLM 客户端 (LLMClient)

**位置**：`backend/core/llm/client.py`

**支持的提供商**：
- **Ollama**：本地模型
- **VLLM**：高性能推理

**特性**：
- 同步/流式对话
- 错误分类处理
- 请求验证
- 超时控制
- 多模态支持（图片输入）
- 工具调用支持

### 6. 模型路由器 (ModelRouter)

**位置**：`backend/core/model_router.py`

**职责**：
- 管理多个 LLM 模型客户端
- 按用途路由请求（main/summary/memory）
- 模型配置热加载
- 健康检查和故障转移

**预配置模型用途**：
- `main`：主对话模型（128k 上下文）
- `summary`：摘要生成模型
- `memory`：记忆处理模型

### 7. 副模型路由器 (SecondaryModelRouter)

**位置**：`backend/core/memory/secondary_router.py`

**职责**：
- 处理辅助任务（摘要、分类等）
- 与主模型协同工作

## API 路由

### Chat 模块
- `POST /api/chat` - 非流式聊天
- `POST /api/chat/stream` - 流式聊天（SSE）
- `GET /api/chat/history/{session_id}` - 获取聊天历史

### Memory 模块
- `GET /api/memories` - 获取记忆列表
- `POST /api/memories` - 创建记忆
- `GET /api/memories/{memory_id}` - 获取记忆详情
- `PUT /api/memories/{memory_id}` - 更新记忆
- `DELETE /api/memories/{memory_id}` - 删除记忆
- `POST /api/memories/search` - 搜索记忆
- `POST /api/memories/rag` - RAG 搜索
- `POST /api/memories/3d` - 3D 记忆搜索
- `POST /api/memories/semantic-search` - 语义搜索
- `POST /api/memories/permanent` - 创建永久记忆
- `POST /api/memories/batch/write` - 批量写入
- `POST /api/memories/batch/delete` - 批量删除

### Context 模块
- `GET /api/context/sessions` - 列出会话
- `POST /api/context/sessions` - 创建会话
- `GET /api/context/messages/{session_id}` - 获取消息
- `POST /api/context/messages` - 添加消息
- `POST /api/context/summary` - 生成摘要

### Tools 模块
- `GET /api/tools` - 列出工具
- `POST /api/tools` - 注册工具
- `POST /api/tools/call` - 调用工具
- `GET /api/tools/mcp/servers` - MCP 服务器列表
- `POST /api/tools/mcp/servers` - 添加 MCP 服务器

### ACP 模块
- `POST /api/acp/discover` - 发现 Agent
- `POST /api/acp/connect` - 连接 Agent
- `POST /api/acp/groups` - 创建群组
- `POST /api/acp/send` - 发送消息

### Agent 模块
- `GET /api/agents` - 列出 Agent
- `POST /api/agents` - 创建 Agent
- `GET /api/agents/{agent_id}` - 获取 Agent
- `PUT /api/agents/{agent_id}` - 更新 Agent
- `DELETE /api/agents/{agent_id}` - 删除 Agent
- `POST /api/agents/{agent_id}/clone` - 克隆 Agent

### Archive 模块
- `POST /api/archive/memory` - 归档记忆
- `POST /api/archive/merge` - 合并归档
- `POST /api/archive/deduplicate` - 去重

### Backup 模块
- `GET /api/backups` - 列出备份
- `POST /api/backups` - 创建备份
- `POST /api/backups/{backup_id}/restore` - 恢复备份

### Admin 模块
- `GET /api/admin/dashboard` - 仪表盘统计
- `GET /api/admin/stats` - 系统统计
- `GET /api/admin/health` - 健康检查
- `GET /api/admin/config` - 获取配置
- `PUT /api/admin/config` - 更新配置

### Service 模块
- `GET /api/service/status` - 服务状态
- `POST /api/service/start` - 启动服务
- `POST /api/service/stop` - 停止服务
- `POST /api/service/restart` - 重启服务
- `GET /api/service/models` - 可用模型列表

## 配置

**文件**：`CXHMS/config/default.yaml`

```yaml
server:
  host: 0.0.0.0
  port: 8000

models:
  main:
    provider: ollama
    host: http://localhost:11434
    model: qwen3-vl:8b
    temperature: 0.7
    max_tokens: 0
  summary:
    provider: ollama
    model: qwen3-vl:8b
  memory:
    provider: ollama
    model: qwen3-vl:8b

memory:
  enabled: true
  vector_enabled: true
  vector_backend: milvus_lite
  decay_enabled: true
  decay_rate: 0.1

context:
  max_context_length: 4000
  context_window: 10

tools:
  enabled: true
  mcp_enabled: false

acp:
  enabled: true
  discovery_enabled: true
  discovery_port: 9999
```

## 启动流程

```
1. 初始化模型路由器 (ModelRouter)
2. 初始化记忆管理器 (MemoryManager)
3. 初始化异步记忆管理器 (AsyncMemoryManager)
4. 初始化上下文管理器 (ContextManager)
5. 初始化 ACP 管理器 (ACPManager)
6. 初始化 LLM 客户端
7. 初始化副模型路由器 (SecondaryModelRouter)
8. 初始化 MCP 管理器 (MCPManager)
9. 注册内置工具
10. 注册主模型工具
11. 注册摘要模型工具
12. 启用向量搜索
13. 启动衰减批处理器
14. 启动提醒管理器
```

## 错误处理

### 错误分类

1. **LLMError**：LLM 调用错误
   - LLMConnectionError：连接错误
   - LLMTimeoutError：超时错误
   - LLMRateLimitError：速率限制

2. **MCPError**：MCP 服务器错误
   - MCPConnectionError：连接错误
   - MCPTimeoutError：超时错误

3. **MemoryError**：记忆操作错误
4. **ContextError**：上下文操作错误

### 错误响应格式

```json
{
  "status": "error",
  "error": "错误描述",
  "error_details": {
    "status_code": 500,
    "exception": "详细异常信息"
  }
}
```

## 插件系统

CXHMS 支持插件扩展：
- 工具插件
- 存储后端插件
- LLM 提供商插件

**位置**：`backend/core/plugins/manager.py`
