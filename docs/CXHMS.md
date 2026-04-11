# CXHMS 核心服务文档

## 概述

在 v4 单体架构中，CXHMS 的核心功能已整合到 `server/core/` 目录，作为业务逻辑层。

## 核心模块

### LLM Client (`server/core/llm/`)

LLM 客户端封装，支持 Ollama 和 VLLM。

```python
from server.core.llm import get_llm_client

llm = get_llm_client()
response = await llm.chat(messages)
```

### Memory Manager (`server/core/memory/`)

记忆管理系统，负责记忆的 CRUD、向量搜索和衰减。

```python
from server.core.memory import get_memory_manager

memory = get_memory_manager()
memory.write_memory(content="今天很开心", memory_type="long_term")
results = memory.search_memories(query="心情")
```

### Context Manager (`server/core/context/`)

上下文管理器，处理会话和消息历史。

```python
from server.core.context import get_context_manager

context = get_context_manager()
messages = context.get_messages(session_id)
context.add_message(session_id, role="user", content="你好")
```

### Tool Registry (`server/core/tools/`)

工具注册表，管理所有可用工具。

```python
from server.core.tools import tool_registry

tools = tool_registry.list_tools()
result = await tool_registry.call_tool("calculator", {"expr": "1+1"})
```

### ACP Manager (`server/core/acp/`)

ACP 协议管理器，处理 Agent 发现和通信。

```python
from server.core.acp import get_acp_manager

acp = get_acp_manager()
agents = acp.discover_agents()
```

## 数据流

```
Handler → Core Module → Database/Vector Store
```

## 数据库

### SQLite

- `data/memories.db` - 记忆数据
- `data/sessions.db` - 会话数据
- `data/acp/` - ACP 数据

### 向量存储

支持 Milvus Lite、ChromaDB、Qdrant。

```python
memory.enable_vector_search(
    embedding_model=llm_client,
    vector_backend="milvus_lite",
    db_path="data/milvus.db"
)
```

## 工具系统

### 内置工具

- `calculator` - 数学计算
- `datetime` - 日期时间
- `random` - 随机数生成
- `json_format` - JSON 格式化

### 主模型工具

- 记忆工具（搜索、创建、更新）
- ACP 工具（发现、连接、发送）
- 提醒工具（设置、取消）
- 图工具（关系管理）

### MCP 工具

通过 MCP 协议扩展的工具。

## 配置

在 `server/config.json` 中配置：

```json
{
  "llm": {
    "provider": "ollama",
    "host": "http://localhost:11434",
    "model": "qwen3-vl:8b"
  },
  "memory": {
    "vector_enabled": true,
    "vector_backend": "milvus_lite"
  }
}
```

## 扩展

### 添加新工具

```python
from server.core.tools import tool_registry

@tool_registry.register
async def my_tool(param1: str) -> str:
    return f"Result: {param1}"
```

### 添加新的记忆类型

```python
memory.write_memory(
    content="内容",
    memory_type="custom_type",
    importance=3,
    tags=["tag1"]
)
```
