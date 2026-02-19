# CXHMS 项目完整功能与实现逻辑报告

## 项目概述

CXHMS (晨曦人格化记忆系统) 是一个基于 FastAPI 的智能记忆管理平台，提供完整的记忆存储、语义搜索、对话系统、ACP 协议通信和工具调用功能。

### 技术栈

**后端技术**
- 框架: Python 3.10+ / FastAPI + Uvicorn
- 数据验证: Pydantic v2
- 数据库: SQLite + SQLAlchemy
- HTTP 客户端: httpx 异步支持
- 测试框架: pytest + pytest-asyncio

**前端技术**
- 框架: React 18 + TypeScript
- 构建工具: Vite 6
- 状态管理: Zustand + React Query
- 样式: Tailwind CSS
- 测试: Vitest + jsdom

**AI 与向量**
- LLM 集成: Ollama、OpenAI、Anthropic 兼容接口
- 向量数据库: Milvus Lite、Qdrant、Weaviate
- 工具协议: MCP (Model Context Protocol)

---

## 一、核心架构设计

### 1.1 应用启动流程

```
main.py → 初始化日志 → 加载配置 → 启动 Uvicorn → FastAPI 应用
```

**FastAPI 应用初始化顺序** ([app.py](file:///d:/CXHMS/backend/api/app.py))：

1. **ModelRouter** - 模型路由器 (最先初始化)
2. **MemoryManager** - 记忆管理器
3. **ContextManager** - 上下文管理器
4. **ACPManager** - ACP 管理器
5. **LLMClient** - LLM 客户端
6. **SecondaryModelRouter** - 副模型路由器
7. **MCPManager** - MCP 管理器
8. **DecayBatchProcessor** - 批量衰减处理器
9. **向量搜索功能** - 向量数据库连接

### 1.2 全局依赖注入

系统提供以下依赖注入函数：

```python
get_memory_manager()      # 记忆管理器
get_context_manager()     # 上下文管理器
get_acp_manager()         # ACP 管理器
get_llm_client()          # LLM 客户端
get_secondary_router()    # 副模型路由器
get_mcp_manager()         # MCP 管理器
get_model_router()        # 模型路由器
```

---

## 二、API 路由系统

### 2.1 路由文件总览

| 文件 | 路径 | 主要功能 | 核心方法 |
|------|------|---------|---------|
| [chat.py](file:///d:/CXHMS/backend/api/routers/chat.py) | `/api/chat` | 聊天对话、流式响应 | send_message, stream_chat |
| [memory.py](file:///d:/CXHMS/backend/api/routers/memory.py) | `/api/memories` | 记忆 CRUD、搜索、RAG | get_memories, search, semantic_search |
| [context.py](file:///d:/CXHMS/backend/api/routers/context.py) | `/api/context` | 会话管理、消息历史 | create_session, add_message |
| [tools.py](file:///d:/CXHMS/backend/api/routers/tools.py) | `/api/tools` | 工具注册、MCP 管理 | list_tools, call_tool |
| [acp.py](file:///d:/CXHMS/backend/api/routers/acp.py) | `/api/acp` | ACP 协议、Agent 发现 | discover_agents, send_message |
| [agents.py](file:///d:/CXHMS/backend/api/routers/agents.py) | `/api/agents` | Agent 配置管理 | get_agents, create_agent |
| [archive.py](file:///d:/CXHMS/backend/api/routers/archive.py) | `/api/archive` | 归档管理、去重合并 | archive, merge, detect_duplicates |
| [memory_chat.py](file:///d:/CXHMS/backend/api/routers/memory_chat.py) | `/api/memory-chat` | 记忆管理对话引擎 | chat, search_memories |
| [admin.py](file:///d:/CXHMS/backend/api/routers/admin.py) | `/api/admin` | 管理员功能 | system_info, clear_cache |
| [service.py](file:///d:/CXHMS/backend/api/routers/service.py) | `/api/service` | 服务状态管理 | start_service, stop_service |

### 2.2 聊天路由详细实现 ([chat.py](file:///d:/CXHMS/backend/api/routers/chat.py))

**非流式聊天流程**：

```
用户消息 → POST /api/chat
    ↓
获取 Agent 配置 (系统提示词、模型)
    ↓
获取/创建会话 (ContextManager)
    ↓
添加用户消息到上下文
    ↓
检索相关记忆 (MemoryRouter)
    ↓
构建消息列表:
  1. 系统提示词
  2. 记忆上下文 (如果启用)
  3. 历史消息
  4. 用户消息
    ↓
调用 LLM (流式/非流式)
    ↓
保存助手响应到上下文
    ↓
返回结果
```

**核心方法实现**：

```python
@router.post("")
async def send_message(request: ChatRequest):
    # 1. 获取 Agent 配置
    agent = await get_agent_by_id(request.agent_id)
    
    # 2. 获取或创建会话
    session = await context_manager.get_or_create_session(
        session_id=request.session_id,
        workspace_id=request.workspace_id
    )
    
    # 3. 添加用户消息
    await context_manager.add_message(
        session_id=session.id,
        role="user",
        content=request.message
    )
    
    # 4. 检索相关记忆
    memory_context = ""
    if agent.use_memory:
        memories = await memory_router.route(
            query=request.message,
            scene=agent.memory_scene,
            limit=5
        )
        memory_context = format_memories(memories)
    
    # 5. 构建消息
    messages = build_messages(
        system_prompt=agent.system_prompt,
        memory_context=memory_context,
        history=await context_manager.get_messages(session.id),
        user_message=request.message
    )
    
    # 6. 调用 LLM
    response = await llm_client.chat(
        model=agent.model,
        messages=messages,
        temperature=agent.temperature
    )
    
    # 7. 保存响应
    await context_manager.add_message(
        session_id=session.id,
        role="assistant",
        content=response.content
    )
    
    return {"response": response.content, "session_id": session.id}
```

### 2.3 记忆路由详细实现 ([memory.py](file:///d:/CXHMS/backend/api/routers/memory.py))

**核心方法**：

```python
@router.get("")
async def get_memories(
    workspace_id: str,
    memory_type: MemoryType = None,
    tags: List[str] = None,
    page: int = 1,
    page_size: int = 20
) -> PaginatedMemories:
    """获取记忆列表"""
    return await memory_manager.list_memories(
        workspace_id=workspace_id,
        type=memory_type,
        tags=tags,
        page=page,
        page_size=page_size
    )

@router.post("")
async def create_memory(request: CreateMemoryRequest) -> Memory:
    """创建新记忆"""
    return await memory_manager.write_memory(
        content=request.content,
        memory_type=request.type,
        importance=request.importance,
        tags=request.tags,
        metadata=request.metadata,
        permanent=request.permanent,
        emotion_score=request.emotion_score
    )

@router.post("/search")
async def search_memories(request: SearchRequest) -> List[Memory]:
    """混合搜索记忆"""
    return await memory_manager.hybrid_search(
        query=request.query,
        memory_type=request.type,
        tags=request.tags,
        limit=request.limit
    )

@router.post("/semantic-search")
async def semantic_search(request: SemanticSearchRequest) -> List[Memory]:
    """语义搜索"""
    return await memory_manager.vector_search(
        query=request.query,
        limit=request.limit
    )
```

---

## 三、记忆管理系统 (Memory System)

### 3.1 核心类：MemoryManager

**文件位置**: [backend/core/memory/manager.py](file:///d:/CXHMS/backend/core/memory/manager.py)

**数据库架构设计**：

```sql
-- 记忆主表
CREATE TABLE memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type VARCHAR(20) NOT NULL,           -- long_term/short_term/permanent
    content TEXT NOT NULL,
    vector_id VARCHAR(100),              -- 向量数据库 ID
    metadata TEXT,                       -- JSON 元数据
    importance INTEGER DEFAULT 3,        -- 1-5 重要性等级
    importance_score FLOAT DEFAULT 0.6,  -- 重要性分数
    decay_type VARCHAR(20) DEFAULT 'exponential',
    decay_params TEXT,
    reactivation_count INTEGER DEFAULT 0,
    emotion_score FLOAT DEFAULT 0.0,
    permanent BOOLEAN DEFAULT FALSE,
    psychological_age FLOAT DEFAULT 1.0,
    tags TEXT,                           -- JSON 标签列表
    workspace_id VARCHAR(100),
    source VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    archived_at TIMESTAMP,
    is_deleted BOOLEAN DEFAULT FALSE
);

-- 审计日志表
CREATE TABLE audit_logs (
    id INTEGER PRIMARY KEY,
    action VARCHAR(50),
    memory_id INTEGER,
    details TEXT,
    timestamp TIMESTAMP
);

-- 永久记忆表
CREATE TABLE permanent_memories (
    id INTEGER PRIMARY KEY,
    memory_id INTEGER,
    content TEXT,
    importance_score FLOAT,
    embedding BLOB
);
```

**核心方法详解**：

| 方法名 | 功能描述 | 实现逻辑 |
|-------|---------|---------|
| `write_memory()` | 创建新记忆 | 1. 生成向量嵌入 2. 插入数据库 3. 同步到向量库 4. 记录审计日志 |
| `get_memory()` | 获取单条记忆 | 1. 查询数据库 2. 检查软删除 3. 返回结果 |
| `search_memories()` | 搜索记忆 | 1. 构建查询条件 2. 执行筛选 3. 返回分页结果 |
| `update_memory()` | 更新记忆 | 1. 检查存在性 2. 更新字段 3. 重新生成向量 4. 记录变更 |
| `delete_memory()` | 删除记忆 | 1. 软删除标记 2. 从向量库移除 3. 记录审计 |
| `hybrid_search()` | 混合搜索 | 1. 向量相似度搜索 2. 关键词匹配 3. 分数融合 4. 排序返回 |
| `search_memories_3d()` | 3D 评分搜索 | 1. 获取向量得分 2. 计算时间衰减 3. 计算相关性 4. 加权融合 |
| `batch_write_memories()` | 批量写入 | 1. 批量生成向量 2. 事务插入 3. 批量同步 |
| `sync_decay_values()` | 同步衰减值 | 1. 批量计算新分数 2. 更新数据库 3. 记录统计 |

### 3.2 记忆衰减系统 (Decay System)

**文件位置**: [backend/core/memory/decay.py](file:///d:/CXHMS/backend/core/memory/decay.py)

**衰减模型设计**：

```python
# 双阶段指数衰减函数
T(t) = α·e^(-λ₁·Δt) + (1-α)·e^(-λ₂·Δt)

# 艾宾浩斯遗忘曲线优化版
T(t) = 1 / (1 + (Δt/T₅₀)^k)

# 180天保留率计算
retention_rate = importance_score × exp(-decay_rate × days)
```

**重要性等级与衰减参数**：

| 等级 | 分数范围 | 衰减类型 | 180天保留率 | 应用场景 |
|-----|---------|---------|------------|---------|
| 1.0 | 1.0 | zero | 100% | 核心身份信息 |
| 0.92 | 0.85-0.99 | exponential | 95% | 重要偏好设置 |
| 0.77 | 0.70-0.84 | exponential | 80% | 近期重要事件 |
| 0.60 | 0.50-0.69 | exponential | 50% | 一般性知识 |
| 0.40 | 0.30-0.49 | exponential | 25% | 临时信息 |
| 0.15 | 0.0-0.29 | exponential | 5% | 边缘信息 |

**综合评分公式**：

```python
final_score = importance_score × 0.35 + time_score × 0.25 + relevance_score × 0.4
```

**time_score 计算 - 双阶段指数衰减（默认）**：

```python
def calculate_time_score(created_at, decay_type):
    days_elapsed = (now - created_at).days
    
    if decay_type == "zero":
        return 1.0
    
    # 双阶段指数衰减（默认模型）
    # T(t) = α·e^(-λ₁·Δt) + (1-α)·e^(-λ₂·Δt)
    alpha = 0.6      # 近期记忆权重
    lambda1 = 0.25   # 快速衰减系数
    lambda2 = 0.04   # 慢速衰减系数
    
    decay_factor = (
        alpha * math.exp(-lambda1 * days_elapsed) +
        (1 - alpha) * math.exp(-lambda2 * days_elapsed)
    )
    
    return importance * decay_factor
```

**time_score 计算 - 艾宾浩斯优化版（实验性）**：

```python
# 艾宾浩斯遗忘曲线优化版（实验性功能）
# 可通过配置 memory.decay_model: "ebbinghaus" 启用
# T(t) = 1 / (1 + (Δt/T₅₀)^k)

def calculate_ebbinghaus_time_score(created_at, decay_params):
    days_elapsed = (now - created_at).days
    
    t50 = decay_params.get("t50", 30.0)  # 半衰期（天）
    k = decay_params.get("k", 2.0)       # 曲线陡峭度
    
    decay_factor = 1.0 / (1.0 + (days_elapsed / t50) ** k)
    
    return importance * decay_factor
```

**衰减模型切换配置**：

```yaml
memory:
  # 衰减模型选择
  # exponential - 双阶段指数衰减（默认，推荐）
  # ebbinghaus  - 艾宾浩斯遗忘曲线（实验性）
  decay_model: exponential
  
  # 艾宾浩斯模型参数（仅当 decay_model 为 ebbinghaus 时生效）
  ebbinghaus_params:
    t50: 30.0  # 半衰期（天）
    k: 2.0     # 曲线陡峭度
```

### 3.3 记忆路由器 (Memory Router)

**文件位置**: [backend/core/memory/router.py](file:///d:/CXHMS/backend/core/memory/router.py)

**场景感知配置**：

```python
class MemoryRouter:
    SCENE_CONFIGS = {
        "task": {
            "importance_weight": 0.30,
            "time_weight": 0.20,
            "relevance_weight": 0.50
        },
        "chat": {
            "importance_weight": 0.45,
            "time_weight": 0.20,
            "relevance_weight": 0.35
        },
        "first_interaction": {
            "importance_weight": 0.30,
            "time_weight": 0.30,
            "relevance_weight": 0.40
        },
        "recall": {
            "importance_weight": 0.25,
            "time_weight": 0.25,
            "relevance_weight": 0.50
        },
        "learning": {
            "importance_weight": 0.35,
            "time_weight": 0.20,
            "relevance_weight": 0.45
        },
        "problem_solving": {
            "importance_weight": 0.25,
            "time_weight": 0.20,
            "relevance_weight": 0.55
        },
        "creative": {
            "importance_weight": 0.30,
            "time_weight": 0.40,
            "relevance_weight": 0.30
        }
    }
    
    async def route(
        self,
        query: str,
        scene: str = "chat",
        limit: int = 5
    ) -> List[Memory]:
        """根据场景路由到不同的记忆检索策略"""
        config = self.SCENE_CONFIGS.get(scene, self.SCENE_CONFIGS["chat"])
        
        # 3D 评分搜索
        memories = await self.memory_manager.search_memories_3d(
            query=query,
            importance_weight=config["importance_weight"],
            time_weight=config["time_weight"],
            relevance_weight=config["relevance_weight"],
            limit=limit
        )
        
        return memories
```

### 3.4 归档管理系统 (Archive System)

**文件位置**: [backend/core/memory/archiver.py](file:///d:/CXHMS/backend/core/memory/archiver.py)

**归档层级定义**：

```python
ARCHIVE_LEVELS = {
    1: {
        "name": "存档",
        "compression_rate": 0.30,
        "max_retention_days": 90,
        "description": "轻度压缩，保留详细信息"
    },
    2: {
        "name": "归档",
        "compression_rate": 0.20,
        "max_retention_days": 180,
        "description": "中度压缩，保留关键信息"
    },
    3: {
        "name": "深度归档",
        "compression_rate": 0.10,
        "max_retention_days": 365,
        "description": "高度压缩，仅保留摘要"
    },
    4: {
        "name": "封存",
        "compression_rate": 0.05,
        "max_retention_days": 730,
        "description": "极压缩，仅保留核心信息"
    }
}

class Archiver:
    async def archive_memory(
        self,
        memory_id: int,
        level: int = 1
    ) -> ArchiveResult:
        """归档单条记忆"""
        memory = await self.memory_manager.get_memory(memory_id)
        
        # 计算新的存储策略
        archive_config = ARCHIVE_LEVELS[level]
        
        # 压缩内容
        compressed_content = self._compress_content(
            memory.content,
            archive_config["compression_rate"]
        )
        
        # 更新记忆状态
        await self.memory_manager.update_memory(
            memory_id,
            archived=True,
            archive_level=level,
            compressed_content=compressed_content,
            archived_at=datetime.now()
        )
        
        # 从向量库移除原始内容
        await self.vector_store.delete(memory.vector_id)
        
        return ArchiveResult(
            memory_id=memory_id,
            level=level,
            original_size=len(memory.content),
            compressed_size=len(compressed_content)
        )
    
    async def merge_duplicate_memories(
        self,
        memory_ids: List[int]
    ) -> MergeResult:
        """合并重复记忆"""
        memories = await self.memory_manager.get_memories(memory_ids)
        
        # 合并内容
        merged_content = self._merge_contents(memories)
        
        # 保留最高重要性
        max_importance = max(m.importance for m in memories)
        
        # 合并标签
        all_tags = set()
        for m in memories:
            all_tags.update(m.tags)
        
        # 删除原记忆
        for m in memories:
            await self.memory_manager.delete_memory(m.id)
        
        # 创建新记忆
        new_memory = await self.memory_manager.write_memory(
            content=merged_content,
            importance=max_importance,
            tags=list(all_tags),
            memory_type=MemoryType.LONG_TERM
        )
        
        return MergeResult(
            original_count=len(memories),
            new_memory_id=new_memory.id
        )
```

### 3.5 向量存储系统 (Vector Store)

**文件位置**: [backend/core/memory/vector_store.py](file:///d:/CXHMS/backend/core/memory/vector_store.py)

**支持的向量后端**：

```python
class VectorStore(ABC):
    """向量存储抽象基类"""
    
    @abstractmethod
    async def upsert(self, id: str, vector: List[float], metadata: Dict):
        """插入或更新向量"""
        pass
    
    @abstractmethod
    async def search(
        self,
        query_vector: List[float],
        limit: int = 10,
        filters: Dict = None
    ) -> List[SearchResult]:
        """相似度搜索"""
        pass
    
    @abstractmethod
    async def delete(self, id: str):
        """删除向量"""
        pass
    
    @abstractmethod
    async def count(self) -> int:
        """获取向量数量"""
        pass


# Milvus Lite 实现
class MilvusLiteStore(VectorStore):
    def __init__(self, db_path: str, vector_size: int = 768):
        self.collection = Collection("cxhms_memories")
    
    async def search(
        self,
        query_vector: List[float],
        limit: int = 10,
        filters: Dict = None
    ) -> List[SearchResult]:
        search_params = {
            "metric_type": "COSINE",
            "params": {"nprobe": 10}
        }
        
        results = self.collection.search(
            data=[query_vector],
            anns_field="vector",
            param=search_params,
            limit=limit,
            expr=filter_expr
        )
        
        return [SearchResult(**r) for r in results]


# Weaviate 实现
class WeaviateStore(VectorStore):
    def __init__(self, host: str, port: int, embedded: bool = False):
        self.client = weaviate.Client(
            url=f"http://{host}:{port}",
            embedded_snapshot_path="./weaviate"
        ) if embedded else weaviate.Client(url=f"http://{host}:{port}")
    
    async def search(
        self,
        query_vector: List[float],
        limit: int = 10,
        filters: Dict = None
    ) -> List[SearchResult]:
        return (
            self.client.query
            .get("CXHMSMemory", ["content", "metadata", "importance"])
            .with_near_vector({
                "vector": query_vector,
                "certainty": 0.7
            })
            .with_limit(limit)
            .do()
        )
```

### 3.6 混合搜索实现 (Hybrid Search)

**文件位置**: [backend/core/memory/hybrid_search.py](file:///d:/CXHMS/backend/core/memory/hybrid_search.py)

```python
class HybridSearch:
    def __init__(
        self,
        vector_store: VectorStore,
        text_search: TextSearch,
        reranker: Reranker = None
    ):
        self.vector_store = vector_store
        self.text_search = text_search
        self.reranker = reranker
    
    async def search(
        self,
        query: str,
        vector_weight: float = 0.7,
        text_weight: float = 0.3,
        limit: int = 10
    ) -> List[HybridResult]:
        # 1. 生成查询向量
        query_vector = await self.get_embedding(query)
        
        # 2. 向量搜索
        vector_results = await self.vector_store.search(
            query_vector=query_vector,
            limit=limit * 2
        )
        
        # 3. 关键词搜索
        text_results = await self.text_search.search(
            query=query,
            limit=limit * 2
        )
        
        # 4. 分数融合
        combined_results = self._fuse_scores(
            vector_results,
            text_results,
            vector_weight,
            text_weight
        )
        
        # 5. 重排序
        if self.reranker:
            combined_results = await self.reranker.rerank(
                query=query,
                results=combined_results,
                top_k=limit
            )
        
        return combined_results[:limit]
    
    def _fuse_scores(
        self,
        vector_results: List[SearchResult],
        text_results: List[SearchResult],
        vector_weight: float,
        text_weight: float
    ) -> List[HybridResult]:
        # 使用 RRF (Reciprocal Rank Fusion) 融合
        fused = {}
        
        for rank, result in enumerate(vector_results):
            fused[result.id] = {
                "id": result.id,
                "vector_score": result.score,
                "text_score": 0,
                "vector_rank": rank + 1,
                "text_rank": float('inf'),
                "metadata": result.metadata
            }
        
        for rank, result in enumerate(text_results):
            if result.id in fused:
                fused[result.id]["text_score"] = result.score
                fused[result.id]["text_rank"] = rank + 1
            else:
                fused[result.id] = {
                    "id": result.id,
                    "vector_score": 0,
                    "text_score": result.score,
                    "vector_rank": float('inf'),
                    "text_rank": rank + 1,
                    "metadata": result.metadata
                }
        
        # 计算 RRF 融合分数
        for result in fused.values():
            vector_rrf = 1.0 / (result["vector_rank"] + 60)
            text_rrf = 1.0 / (result["text_rank"] + 60)
            result["fused_score"] = (
                vector_weight * vector_rrf + 
                text_weight * text_rrf
            )
        
        # 归一化
        max_score = max(r["fused_score"] for r in fused.values())
        for result in fused.values():
            result["fused_score"] /= max_score
        
        return sorted(
            fused.values(),
            key=lambda x: x["fused_score"],
            reverse=True
        )
```

---

## 四、聊天对话系统

### 4.1 聊天流程详细设计

**文件位置**: [backend/api/routers/chat.py](file:///d:/CXHMS/backend/api/routers/chat.py)

**核心流程**：

```python
class ChatService:
    def __init__(
        self,
        memory_manager: MemoryManager,
        context_manager: ContextManager,
        model_router: ModelRouter,
        tool_registry: ToolRegistry
    ):
        self.memory = memory_manager
        self.context = context_manager
        self.model_router = model_router
        self.tools = tool_registry
    
    async def chat(
        self,
        agent_id: str,
        message: str,
        session_id: str = None,
        stream: bool = False
    ) -> ChatResponse:
        # 1. 获取 Agent 配置
        agent = await self._get_agent(agent_id)
        
        # 2. 管理会话
        session = await self.context.get_or_create_session(
            session_id=session_id,
            workspace_id=agent.workspace_id
        )
        
        # 3. 构建上下文
        context = await self._build_context(
            agent=agent,
            session=session,
            message=message
        )
        
        # 4. 工具调用准备
        if agent.use_tools:
            available_tools = self.tools.list_enabled()
            tool_definitions = self.tools.list_openai_functions()
        else:
            tool_definitions = []
        
        # 5. 调用 LLM
        llm_response = await self.model_router.chat(
            model_type=agent.model,
            messages=context.messages,
            tools=tool_definitions,
            stream=stream
        )
        
        # 6. 处理工具调用
        if llm_response.tool_calls:
            tool_results = await self._execute_tool_calls(
                llm_response.tool_calls
            )
            # 继续对话流程
            context.messages.extend(tool_results)
            llm_response = await self.model_router.chat(
                model_type=agent.model,
                messages=context.messages
            )
        
        # 7. 保存到上下文
        await self.context.add_message(
            session_id=session.id,
            role="assistant",
            content=llm_response.content
        )
        
        # 8. 可选：保存重要内容到记忆
        if self._should_memorize(llm_response.content):
            await self._memorize_response(
                message=message,
                response=llm_response.content,
                agent=agent
            )
        
        return ChatResponse(
            content=llm_response.content,
            session_id=session.id,
            usage=llm_response.usage
        )
    
    async def _build_context(
        self,
        agent: Agent,
        session: Session,
        message: str
    ) -> BuildContext:
        messages = []
        
        # 1. 系统提示词
        messages.append({
            "role": "system",
            "content": agent.system_prompt
        })
        
        # 2. 记忆上下文
        if agent.use_memory:
            memories = await self.memory.router.route(
                query=message,
                scene=agent.memory_scene,
                limit=5
            )
            memory_context = self._format_memories(memories)
            messages.append({
                "role": "system",
                "content": f"相关记忆:\n{memory_context}"
            })
        
        # 3. 历史消息
        history = await self.context.get_messages(
            session_id=session.id,
            limit=10
        )
        messages.extend([
            {"role": m.role, "content": m.content}
            for m in history
        ])
        
        # 4. 当前用户消息
        messages.append({"role": "user", "content": message})
        
        return BuildContext(messages=messages)
```

### 4.2 Agent 配置管理

**文件位置**: [backend/api/routers/agents.py](file:///d:/CXHMS/backend/api/routers/agents.py)

**Agent 数据模型**：

```python
class AgentConfig(BaseModel):
    id: str = Field(..., description="Agent 唯一标识")
    name: str = Field(..., description="显示名称")
    system_prompt: str = Field(..., description="系统提示词")
    model: str = Field(default="main", description="使用的模型")
    temperature: float = Field(default=0.7, ge=0, le=2.0)
    max_tokens: int = Field(default=4096, ge=1, le=65536)
    use_memory: bool = Field(default=True)
    use_tools: bool = Field(default=True)
    memory_scene: str = Field(default="chat")
    workspace_id: str
    created_at: datetime
    updated_at: datetime


# 默认 Agent 配置示例
DEFAULT_CHAT_AGENT = AgentConfig(
    id="default_chat",
    name="默认助手",
    system_prompt="""你是一个智能助手,帮助用户解答问题和进行对话。
请保持友好、专业、有帮助的回答风格。
如果用户询问个人信息,请基于已存储的记忆来回答。
不要编造信息,如果不知道则坦诚告知。""",
    model="main",
    temperature=0.7,
    use_memory=True,
    use_tools=True,
    memory_scene="chat"
)

CREATIVE_AGENT = AgentConfig(
    id="creative",
    name="创意助手",
    system_prompt="""你是一个创意写作助手。
帮助用户进行创意写作、头脑风暴、故事创作等任务。
保持开放、鼓励、富有想象力的风格。""",
    model="main",
    temperature=0.9,
    use_memory=True,
    use_tools=False,
    memory_scene="creative"
)

TASK_AGENT = AgentConfig(
    id="task",
    name="任务助手",
    system_prompt="""你是一个任务管理助手。
帮助用户管理任务、制定计划、追踪进度。
请结构化地组织信息和任务。""",
    model="main",
    temperature=0.5,
    use_memory=True,
    use_tools=True,
    memory_scene="task"
)
```

### 4.3 流式响应实现

```python
from fastapi.responses import StreamingResponse
from sse_starlette.sse import EventSourceResponse


@router.post("/stream")
async def stream_chat(request: ChatRequest):
    """流式聊天响应"""
    
    async def generate_response():
        try:
            # 初始化
            agent = await get_agent(request.agent_id)
            session = await context_manager.get_or_create_session(...)
            
            # 构建上下文
            messages = await build_messages(...)
            
            # 流式调用
            async for chunk in llm_client.stream_chat(
                model=agent.model,
                messages=messages
            ):
                yield {
                    "event": "message",
                    "data": json.dumps({"chunk": chunk})
                }
            
            # 完成事件
            yield {"event": "done", "data": json.dumps({"status": "complete"})}
            
        except Exception as e:
            yield {
                "event": "error",
                "data": json.dumps({"error": str(e)})
            }
    
    return StreamingResponse(
        generate_response(),
        media_type="text/event-stream"
    )
```

---

## 五、ACP 协议实现 (Agent Communication Protocol)

### 5.1 ACP 核心概念

ACP (Agent Communication Protocol) 是一个用于多 Agent 通信的协议，支持：

- **局域网发现**: 自动发现同一网络中的其他 Agent
- **点对点通信**: Agent 之间直接消息传递
- **群组通信**: 创建群组，多个 Agent 协同工作
- **记忆共享**: 跨 Agent 记忆检索和共享

### 5.2 ACP 数据模型

**文件位置**: [backend/models/acp.py](file:///d:/CXHMS/backend/models/acp.py)

```python
from enum import Enum
from pydantic import BaseModel
from typing import List, Dict, Optional
from datetime import datetime


class MessageType(Enum):
    CHAT = "chat"                    # 聊天消息
    MEMORY_REQUEST = "memory_request"    # 记忆请求
    MEMORY_RESPONSE = "memory_response" # 记忆响应
    TOOL_CALL = "tool_call"          # 工具调用
    TOOL_RESULT = "tool_result"      # 工具结果
    BROADCAST = "broadcast"          # 广播消息
    GROUP_MESSAGE = "group_message"  # 群组消息
    SYNC = "sync"                    # 同步消息
    CONTROL = "control"              # 控制消息


class ACPAgentInfo(BaseModel):
    """Agent 信息"""
    agent_id: str
    name: str
    host: str
    port: int
    status: str = "online"
    capabilities: List[str] = []
    version: str = "1.0.0"
    last_seen: datetime
    metadata: Dict = {}


class ACPConnectionInfo(BaseModel):
    """连接信息"""
    id: str
    local_agent_id: str
    remote_agent_id: str
    remote_host: str
    remote_port: int
    status: str = "disconnected"
    created_at: datetime


class ACPGroupInfo(BaseModel):
    """群组信息"""
    id: str
    name: str
    owner_agent_id: str
    members: List[str] = []
    max_members: int = 10
    is_active: bool = True
    created_at: datetime


class ACPMessageInfo(BaseModel):
    """消息信息"""
    id: str
    msg_type: MessageType
    from_agent_id: str
    to_agent_id: str
    content: Dict
    timestamp: datetime
    requires_response: bool = False
    correlation_id: str = None
```

### 5.3 ACP 管理器实现

**文件位置**: [backend/core/acp/manager.py](file:///d:/CXHMS/backend/core/acp/manager.py)

```python
import asyncio
import httpx
from typing import Dict, List, Optional
from datetime import datetime


class ACPManager:
    def __init__(self, config: ACPConfig):
        self.config = config
        self.local_agent_id = config.agent_id
        self.local_agent_name = config.name
        
        # Agent 连接池
        self.connections: Dict[str, ACPConnectionInfo] = {}
        
        # 已发现的 Agent
        self.discovered_agents: Dict[str, ACPAgentInfo] = {}
        
        # 群组管理
        self.groups: Dict[str, ACPGroupInfo] = {}
        
        # 消息处理回调
        self.message_handlers: Dict[MessageType, List[callable]] = {}
        
        # HTTP 客户端
        self.http_client = httpx.AsyncClient(timeout=30.0)
    
    async def send_message(
        self,
        to_agent_id: str,
        msg_type: MessageType,
        content: Dict,
        requires_response: bool = False
    ) -> ACPMessageInfo:
        """发送消息到远程 Agent"""
        
        connection = self.connections.get(to_agent_id)
        if not connection:
            raise ACPError(f"No connection to agent: {to_agent_id}")
        
        message = ACPMessageInfo(
            id=self._generate_message_id(),
            msg_type=msg_type,
            from_agent_id=self.local_agent_id,
            to_agent_id=to_agent_id,
            content=content,
            timestamp=datetime.now(),
            requires_response=requires_response
        )
        
        try:
            response = await self.http_client.post(
                f"http://{connection.remote_host}:{connection.remote_port}/acp/receive",
                json=message.dict()
            )
            response.raise_for_status()
            
            return message
            
        except Exception as e:
            await self._handle_send_error(message, e)
            raise
    
    async def broadcast(
        self,
        msg_type: MessageType,
        content: Dict,
        exclude: List[str] = None
    ) -> List[ACPMessageInfo]:
        """广播消息到所有已连接的 Agent"""
        exclude = exclude or []
        results = []
        
        tasks = [
            self.send_message(agent_id, msg_type, content)
            for agent_id in self.connections.keys()
            if agent_id not in exclude
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        return [r for r in results if not isinstance(r, Exception)]
    
    async def request_memory(
        self,
        target_agent_id: str,
        query: str,
        memory_type: str = None,
        limit: int = 5
    ) -> List[Dict]:
        """请求远程 Agent 的记忆"""
        message = ACPMessageInfo(
            id=self._generate_message_id(),
            msg_type=MessageType.MEMORY_REQUEST,
            from_agent_id=self.local_agent_id,
            to_agent_id=target_agent_id,
            content={
                "query": query,
                "memory_type": memory_type,
                "limit": limit
            },
            requires_response=True,
            correlation_id=self._generate_correlation_id()
        )
        
        response = await self.send_message(
            to_agent_id=target_agent_id,
            msg_type=MessageType.MEMORY_REQUEST,
            content=message.content
        )
        
        # 等待响应
        response_message = await self._wait_for_response(
            correlation_id=message.correlation_id,
            timeout=30.0
        )
        
        return response_message.content.get("memories", [])
    
    # === 群组管理 ===
    
    async def create_group(
        self,
        name: str,
        max_members: int = 10
    ) -> ACPGroupInfo:
        """创建群组"""
        group = ACPGroupInfo(
            id=self._generate_group_id(),
            name=name,
            owner_agent_id=self.local_agent_id,
            max_members=max_members,
            members=[self.local_agent_id],
            created_at=datetime.now()
        )
        
        self.groups[group.id] = group
        return group
    
    async def join_group(self, group_id: str) -> bool:
        """加入群组"""
        group = self.groups.get(group_id)
        if not group:
            raise ACPError(f"Group not found: {group_id}")
        
        if len(group.members) >= group.max_members:
            raise ACPError("Group is full")
        
        if self.local_agent_id in group.members:
            raise ACPError("Already in group")
        
        group.members.append(self.local_agent_id)
        return True
    
    async def broadcast_to_group(
        self,
        group_id: str,
        msg_type: MessageType,
        content: Dict
    ) -> List[ACPMessageInfo]:
        """向群组广播消息"""
        group = self.groups.get(group_id)
        if not group:
            raise ACPError(f"Group not found: {group_id}")
        
        # 排除自己
        members = [m for m in group.members if m != self.local_agent_id]
        
        return await self.broadcast(
            msg_type=msg_type,
            content=content,
            exclude=members
        )
```

### 5.4 局域网发现机制

**文件位置**: [backend/core/acp/discover.py](file:///d:/CXHMS/backend/core/acp/discover.py)

```python
import asyncio
import socket
from typing import List, Optional
from datetime import datetime


class ACPLanDiscovery:
    """ACP 局域网发现服务"""
    
    DISCOVERY_PORT = 9999
    BROADCAST_PORT = 9998
    BROADCAST_ADDRESS = "255.255.255.255"
    
    def __init__(
        self,
        agent_id: str,
        agent_name: str,
        host: str,
        port: int,
        capabilities: List[str]
    ):
        self.agent_id = agent_id
        self.agent_name = agent_name
        self.host = host
        self.port = port
        self.capabilities = capabilities
        
        self.discovery_socket = None
        self.broadcast_socket = None
        self.running = False
        
        # 已发现的 Agent
        self.agents: Dict[str, ACPAgentInfo] = {}
        
        # 发现回调
        self.on_agent_discovered: callable = None
        self.on_agent_lost: callable = None
    
    async def start(self):
        """启动发现服务"""
        self.running = True
        
        # 创建 UDP 套接字
        self.discovery_socket = socket.socket(
            socket.AF_INET,
            socket.SOCK_DGRAM,
            socket.IPPROTO_UDP
        )
        self.discovery_socket.setsockopt(
            socket.SOL_SOCKET,
            socket.SO_BROADCAST,
            1
        )
        
        # 启动监听任务
        asyncio.create_task(self._listen_for_discovery())
        
        # 启动定期广播任务
        asyncio.create_task(self._periodic_broadcast())
        
        # 启动定期扫描任务
        asyncio.create_task(self._periodic_scan())
    
    async def _listen_for_discovery(self):
        """监听发现消息"""
        while self.running:
            try:
                data, addr = self.discovery_socket.recvfrom(1024)
                message = json.loads(data.decode())
                
                if message["type"] == "discovery_request":
                    await self._handle_discovery_request(addr)
                elif message["type"] == "discovery_response":
                    await self._handle_discovery_response(message, addr)
                    
            except Exception as e:
                if self.running:
                    logging.error(f"Discovery listen error: {e}")
    
    async def _periodic_broadcast(self):
        """定期广播自己的存在"""
        while self.running:
            try:
                message = {
                    "type": "discovery_response",
                    "agent_id": self.agent_id,
                    "agent_name": self.agent_name,
                    "host": self.host,
                    "port": self.port,
                    "capabilities": self.capabilities,
                    "timestamp": datetime.now().isoformat()
                }
                
                self.discovery_socket.sendto(
                    json.dumps(message).encode(),
                    (self.BROADCAST_ADDRESS, self.DISCOVERY_PORT)
                )
                
                await asyncio.sleep(30)  # 每 30 秒广播一次
                
            except Exception as e:
                logging.error(f"Broadcast error: {e}")
    
    async def _periodic_scan(self):
        """定期扫描网络中的 Agent"""
        while self.running:
            try:
                # 发送发现请求
                request = {
                    "type": "discovery_request",
                    "sender_id": self.agent_id,
                    "timestamp": datetime.now().isoformat()
                }
                
                self.discovery_socket.sendto(
                    json.dumps(request).encode(),
                    (self.BROADCAST_ADDRESS, self.DISCOVERY_PORT)
                )
                
                await asyncio.sleep(60)  # 每 60 秒扫描一次
                
            except Exception as e:
                logging.error(f"Scan error: {e}")
    
    async def _handle_discovery_request(self, addr):
        """处理发现请求"""
        # 发送响应
        response = {
            "type": "discovery_response",
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "host": self.host,
            "port": self.port,
            "capabilities": self.capabilities,
            "timestamp": datetime.now().isoformat()
        }
        
        self.discovery_socket.sendto(
            json.dumps(response).encode(),
            addr
        )
    
    async def _handle_discovery_response(self, message, addr):
        """处理发现响应"""
        agent_info = ACPAgentInfo(
            agent_id=message["agent_id"],
            name=message["agent_name"],
            host=message["host"],
            port=message["port"],
            capabilities=message.get("capabilities", []),
            last_seen=datetime.now()
        )
        
        self.agents[agent_info.agent_id] = agent_info
        
        if self.on_agent_discovered:
            self.on_agent_discovered(agent_info)
    
    def stop(self):
        """停止发现服务"""
        self.running = False
        if self.discovery_socket:
            self.discovery_socket.close()
    
    def get_agents(self) -> List[ACPAgentInfo]:
        """获取所有已发现的 Agent"""
        return list(self.agents.values())
```

---

## 六、上下文管理系统

### 6.1 ContextManager 实现

**文件位置**: [backend/core/context/manager.py](file:///d:/CXHMS/backend/core/context/manager.py)

**数据库架构**：

```sql
-- 会话表
CREATE TABLE sessions (
    id VARCHAR(36) PRIMARY KEY,
    workspace_id VARCHAR(100),
    title VARCHAR(500),
    user_id VARCHAR(100),
    message_count INTEGER DEFAULT 0,
    summary TEXT,
    metadata TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 消息表
CREATE TABLE messages (
    id VARCHAR(36) PRIMARY KEY,
    session_id VARCHAR(36) REFERENCES sessions(id),
    role VARCHAR(20) NOT NULL,        -- system/user/assistant/mono_context
    content TEXT NOT NULL,
    content_type VARCHAR(20) DEFAULT 'text',  -- text/mono_context
    metadata TEXT,
    tokens INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Mono 上下文表 (持久化关键信息)
CREATE TABLE mono_contexts (
    id VARCHAR(36) PRIMARY KEY,
    session_id VARCHAR(36) REFERENCES sessions(id),
    key VARCHAR(100) NOT NULL,
    value TEXT NOT NULL,
    description TEXT,
    expires_at TIMESTAMP,
    rounds_remaining INTEGER DEFAULT -1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**核心方法实现**：

```python
class ContextManager:
    def __init__(self, database_path: str):
        self.db = Database(database_path)
    
    async def create_session(
        self,
        workspace_id: str,
        title: str = None,
        user_id: str = None
    ) -> Session:
        """创建新会话"""
        session_id = str(uuid.uuid4())
        
        await self.db.execute(
            """INSERT INTO sessions 
               (id, workspace_id, title, user_id) 
               VALUES (?, ?, ?, ?)""",
            [session_id, workspace_id, title or "新对话", user_id]
        )
        
        return Session(
            id=session_id,
            workspace_id=workspace_id,
            title=title,
            message_count=0,
            is_active=True
        )
    
    async def get_or_create_session(
        self,
        session_id: str = None,
        workspace_id: str = None
    ) -> Session:
        """获取或创建会话"""
        if session_id:
            session = await self.get_session(session_id)
            if session:
                return session
        
        return await self.create_session(workspace_id=workspace_id)
    
    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        content_type: str = "text",
        metadata: Dict = None
    ) -> Message:
        """添加消息"""
        message_id = str(uuid.uuid4())
        tokens = self._count_tokens(content)
        
        await self.db.execute(
            """INSERT INTO messages 
               (id, session_id, role, content, content_type, metadata, tokens) 
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [
                message_id,
                session_id,
                role,
                content,
                content_type,
                json.dumps(metadata or {}),
                tokens
            ]
        )
        
        # 更新会话消息计数
        await self.db.execute(
            """UPDATE sessions SET message_count = message_count + 1,
               updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
            [session_id]
        )
        
        return Message(
            id=message_id,
            session_id=session_id,
            role=role,
            content=content,
            content_type=content_type,
            tokens=tokens
        )
    
    async def get_messages(
        self,
        session_id: str,
        limit: int = 20,
        offset: int = 0
    ) -> List[Message]:
        """获取消息历史"""
        rows = await self.db.execute(
            """SELECT * FROM messages 
               WHERE session_id = ? AND is_deleted = 0
               ORDER BY created_at ASC
               LIMIT ? OFFSET ?""",
            [session_id, limit, offset]
        )
        
        return [Message(**row) for row in rows]
    
    async def get_sessions(
        self,
        workspace_id: str,
        active_only: bool = True
    ) -> List[Session]:
        """获取会话列表"""
        query = "SELECT * FROM sessions WHERE workspace_id = ?"
        params = [workspace_id]
        
        if active_only:
            query += " AND is_active = 1"
        
        query += " ORDER BY updated_at DESC"
        
        rows = await self.db.execute(query, params)
        return [Session(**row) for row in rows]
    
    # === Mono 上下文管理 ===
    
    async def add_mono_context(
        self,
        session_id: str,
        key: str,
        value: str,
        description: str = None,
        expires_at: datetime = None,
        rounds: int = -1
    ) -> MonoContext:
        """添加 Mono 上下文 (持久化关键信息)"""
        context_id = str(uuid.uuid4())
        
        await self.db.execute(
            """INSERT INTO mono_contexts 
               (id, session_id, key, value, description, expires_at, rounds_remaining) 
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [
                context_id,
                session_id,
                key,
                value,
                description,
                expires_at,
                rounds
            ]
        )
        
        return MonoContext(
            id=context_id,
            session_id=session_id,
            key=key,
            value=value,
            description=description,
            expires_at=expires_at,
            rounds_remaining=rounds
        )
    
    async def get_mono_context(
        self,
        session_id: str,
        key: str = None
    ) -> List[MonoContext]:
        """获取 Mono 上下文"""
        query = "SELECT * FROM mono_contexts WHERE session_id = ?"
        params = [session_id]
        
        if key:
            query += " AND key = ?"
            params.append(key)
        
        # 过滤过期
        query += " AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)"
        query += " AND (rounds_remaining < 0 OR rounds_remaining > 0)"
        
        rows = await self.db.execute(query, params)
        return [MonoContext(**row) for row in rows]
    
    async def decrement_mono_rounds(self, session_id: str):
        """减少 Mono 上下文轮次计数"""
        await self.db.execute(
            """UPDATE mono_contexts 
               SET rounds_remaining = rounds_remaining - 1
               WHERE session_id = ? AND rounds_remaining > 0""",
            [session_id]
        )
        
        # 清理已过期的
        await self.clear_expired_mono(session_id)
    
    async def clear_expired_mono(self, session_id: str):
        """清理过期的 Mono 上下文"""
        await self.db.execute(
            """DELETE FROM mono_contexts 
               WHERE session_id = ? 
               AND (expires_at IS NOT NULL AND expires_at <= CURRENT_TIMESTAMP)
               OR (rounds_remaining IS NOT NULL AND rounds_remaining <= 0)""",
            [session_id]
        )
```

### 6.2 上下文摘要生成

**文件位置**: [backend/core/context/summarizer.py](file:///d:/CXHMS/backend/core/context/summarizer.py)

```python
class ContextSummarizer:
    """上下文摘要生成器"""
    
    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client
        self.max_context_length = 4000
    
    async def summarize(
        self,
        messages: List[Message],
        summary_prompt: str = None
    ) -> str:
        """生成对话摘要"""
        if not messages:
            return ""
        
        if self._count_tokens(messages) < self.max_context_length:
            return ""
        
        prompt = summary_prompt or self.default_prompt
        
        context_text = self._format_messages(messages)
        
        response = await self.llm.chat(
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"请总结以下对话的要点:\n\n{context_text}"}
            ],
            max_tokens=500
        )
        
        return response.content
    
    async def generate_session_title(
        self,
        messages: List[Message]
    ) -> str:
        """生成会话标题"""
        if not messages:
            return "新对话"
        
        first_user_msg = next(
            (m for m in messages if m.role == "user"),
            None
        )
        
        if first_user_msg and len(first_user_msg.content) < 50:
            return first_user_msg.content[:50]
        
        # 使用 LLM 生成标题
        prompt = """根据以下对话开头,为这个对话生成一个简短(不超过20个字)的标题。
只返回标题,不要任何其他内容。"""
        
        response = await self.llm.chat(
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": messages[0].content if messages else "新对话"}
            ],
            max_tokens=20
        )
        
        return response.content.strip('" \n')
    
    def _format_messages(self, messages: List[Message]) -> str:
        """格式化消息列表"""
        return "\n".join([
            f"[{m.role}]: {m.content}"
            for m in messages[-20:]  # 只取最近 20 条
        ])
    
    def _count_tokens(self, messages: List[Message]) -> int:
        """估算 token 数量"""
        return sum(len(m.content) // 4 for m in messages)
```

---

## 七、LLM 客户端系统

### 7.1 LLM 客户端抽象

**文件位置**: [backend/core/llm/client.py](file:///d:/CXHMS/backend/core/llm/client.py)

```python
from abc import ABC, abstractmethod
from typing import List, AsyncIterator, Dict, Optional


class LLMResponse(BaseModel):
    """LLM 响应"""
    content: str
    model: str
    usage: Dict[str, int]  # prompt_tokens, completion_tokens, total_tokens
    finish_reason: str


class LLMClient(ABC):
    """LLM 客户端抽象基类"""
    
    @property
    @abstractmethod
    def model_name(self) -> str:
        """获取模型名称"""
        pass
    
    @abstractmethod
    async def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tools: List[Dict] = None
    ) -> LLMResponse:
        """发送聊天请求"""
        pass
    
    @abstractmethod
    async def stream_chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tools: List[Dict] = None
    ) -> AsyncIterator[str]:
        """流式聊天请求"""
        pass
    
    @abstractmethod
    async def is_available(self) -> bool:
        """检查模型是否可用"""
        pass
    
    @abstractmethod
    async def get_embedding(self, text: str) -> List[float]:
        """获取文本嵌入向量"""
        pass
```

### 7.2 Ollama 客户端实现

```python
class OllamaClient(LLMClient):
    """Ollama LLM 客户端"""
    
    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "llama3.2:3b",
        timeout: int = 60
    ):
        self.base_url = base_url
        self.model = model
        self.timeout = timeout
    
    @property
    def model_name(self) -> str:
        return self.model
    
    async def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tools: List[Dict] = None
    ) -> LLMResponse:
        """发送聊天请求到 Ollama"""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            # 构建请求
            request_body = {
                "model": self.model,
                "messages": messages,
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens
                },
                "stream": False
            }
            
            if tools:
                request_body["tools"] = tools
            
            # 发送请求
            response = await client.post(
                f"{self.base_url}/api/chat",
                json=request_body
            )
            response.raise_for_status()
            
            result = response.json()
            
            return LLMResponse(
                content=result["message"]["content"],
                model=self.model,
                usage={
                    "prompt_tokens": result.get("prompt_eval_count", 0),
                    "completion_tokens": result.get("eval_count", 0),
                    "total_tokens": sum([
                        result.get("prompt_eval_count", 0),
                        result.get("eval_count", 0)
                    ])
                },
                finish_reason=result.get("done_reason", "stop")
            )
    
    async def stream_chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tools: List[Dict] = None
    ) -> AsyncIterator[str]:
        """流式聊天请求"""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            request_body = {
                "model": self.model,
                "messages": messages,
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens
                },
                "stream": True
            }
            
            if tools:
                request_body["tools"] = tools
            
            async with client.stream(
                "POST",
                f"{self.base_url}/api/chat",
                json=request_body
            ) as response:
                async for line in response.aiter_lines():
                    if line:
                        chunk = json.loads(line)
                        if "message" in chunk:
                            yield chunk["message"]["content"]
                        
                        if chunk.get("done", False):
                            break
    
    async def get_embedding(self, text: str) -> List[float]:
        """获取文本嵌入"""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/api/embeddings",
                json={
                    "model": self.model,
                    "prompt": text
                }
            )
            response.raise_for_status()
            
            result = response.json()
            return result["embedding"]
    
    async def is_available(self) -> bool:
        """检查 Ollama 是否可用"""
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                response.raise_for_status()
                return True
        except:
            return False
```

### 7.3 vLLM / OpenAI 兼容客户端

```python
class VLLMClient(LLMClient):
    """vLLM / OpenAI 兼容 API 客户端"""
    
    def __init__(
        self,
        base_url: str,
        model: str = None,
        api_key: str = None,
        timeout: int = 60
    ):
        self.base_url = base_url
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
    
    @property
    def model_name(self) -> str:
        return self.model
    
    def _get_headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers
    
    async def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tools: List[Dict] = None
    ) -> LLMResponse:
        """发送聊天请求"""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            request_body = {
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": False
            }
            
            if tools:
                request_body["tools"] = tools
            
            response = await client.post(
                f"{self.base_url}/v1/chat/completions",
                headers=self._get_headers(),
                json=request_body
            )
            response.raise_for_status()
            
            result = response.json()
            choice = result["choices"][0]
            
            return LLMResponse(
                content=choice["message"]["content"],
                model=self.model,
                usage={
                    "prompt_tokens": result["usage"]["prompt_tokens"],
                    "completion_tokens": result["usage"]["completion_tokens"],
                    "total_tokens": result["usage"]["total_tokens"]
                },
                finish_reason=choice.get("finish_reason", "stop")
            )
    
    async def stream_chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tools: List[Dict] = None
    ) -> AsyncIterator[str]:
        """流式聊天请求"""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            request_body = {
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": True
            }
            
            if tools:
                request_body["tools"] = tools
            
            async with client.stream(
                "POST",
                f"{self.base_url}/v1/chat/completions",
                headers=self._get_headers(),
                json=request_body
            ) as response:
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        chunk = line[6:]
                        if chunk != "[DONE]":
                            data = json.loads(chunk)
                            if "choices" in data:
                                delta = data["choices"][0].get("delta", {})
                                if "content" in delta:
                                    yield delta["content"]
    
    async def get_embedding(self, text: str) -> List[float]:
        """获取文本嵌入 (需要 /v1/embeddings 端点)"""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/v1/embeddings",
                headers=self._get_headers(),
                json={
                    "model": self.model,
                    "input": text
                }
            )
            response.raise_for_status()
            
            result = response.json()
            return result["data"][0]["embedding"]
    
    async def is_available(self) -> bool:
        """检查 vLLM 是否可用"""
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(f"{self.base_url}/v1/models")
                response.raise_for_status()
                return True
        except:
            return False
```

### 7.4 模型路由器

**文件位置**: [backend/core/model_router.py](file:///d:/CXHMS/backend/core/model_router.py)

```python
class ModelRouter:
    """模型路由器 - 管理多个 LLM 模型"""
    
    def __init__(self, config: List[ModelConfig]):
        self.clients: Dict[str, LLMClient] = {}
        self.configs: Dict[str, ModelConfig] = {}
        
        # 初始化所有模型客户端
        for model_config in config:
            self.clients[model_config.type] = self._create_client(
                model_config
            )
            self.configs[model_config.type] = model_config
    
    def _create_client(self, config: ModelConfig) -> LLMClient:
        """根据配置创建客户端"""
        if config.provider == "ollama":
            return OllamaClient(
                base_url=config.host,
                model=config.model,
                timeout=config.timeout or 60
            )
        elif config.provider == "openai":
            return VLLMClient(
                base_url=config.host,
                model=config.model,
                api_key=config.apiKey,
                timeout=config.timeout or 60
            )
        elif config.provider == "anthropic":
            return AnthropicClient(
                api_key=config.apiKey,
                model=config.model,
                timeout=config.timeout or 60
            )
        else:
            raise ValueError(f"Unknown provider: {config.provider}")
    
    async def initialize(self):
        """初始化所有模型"""
        for model_type, client in self.clients.items():
            if client.config.enabled:
                available = await client.is_available()
                if not available:
                    logging.warning(f"Model {model_type} is not available")
    
    def get_client(self, model_type: str) -> LLMClient:
        """获取模型客户端"""
        if model_type in self.clients:
            return self.clients[model_type]
        
        # 如果是具体模型名,创建临时客户端
        if model_type.startswith("ollama/"):
            model_name = model_type.split("/")[1]
            return OllamaClient(model=model_name)
        
        # 默认使用 main
        return self.clients.get("main")
    
    def get_config(self, model_type: str) -> ModelConfig:
        """获取模型配置"""
        return self.configs.get(model_type)
    
    async def chat(
        self,
        model_type: str,
        messages: List[Dict[str, str]],
        temperature: float = None,
        max_tokens: int = None,
        tools: List[Dict] = None,
        stream: bool = False
    ) -> LLMResponse:
        """发送聊天请求"""
        client = self.get_client(model_type)
        config = self.get_config(model_type)
        
        # 使用配置的默认值
        temperature = temperature or config.temperature if config else 0.7
        max_tokens = max_tokens or config.max_tokens if config else 4096
        
        if stream:
            return client.stream_chat(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                tools=tools
            )
        else:
            return await client.chat(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                tools=tools
            )
    
    async def get_embedding(
        self,
        model_type: str,
        text: str
    ) -> List[float]:
        """获取嵌入向量"""
        client = self.get_client(model_type)
        return await client.get_embedding(text)
```

---

## 八、工具系统

### 8.1 工具注册表

**文件位置**: [backend/core/tools/registry.py](file:///d:/CXHMS/backend/core/tools/registry.py)

```python
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Any
import json


@dataclass
class Tool:
    """工具定义"""
    name: str
    description: str
    parameters: Dict  # JSON Schema 格式
    function: Callable
    enabled: bool = True
    version: str = "1.0.0"
    category: str = "general"
    tags: List[str] = field(default_factory=list)
    examples: List[str] = field(default_factory=list)
    call_count: int = 0
    last_called: str = None


class ToolRegistry:
    """工具注册表"""
    
    def __init__(self):
        self.tools: Dict[str, Tool] = {}
    
    def register(
        self,
        name: str = None,
        description: str = None,
        category: str = "general"
    ):
        """装饰器注册工具"""
        def decorator(func):
            tool_name = name or func.__name__
            
            # 从函数签名构建参数
            parameters = self._build_parameters(func)
            
            tool = Tool(
                name=tool_name,
                description=description or func.__doc__ or "",
                parameters=parameters,
                function=func,
                category=category
            )
            
            self.tools[tool_name] = tool
            return func
        
        return decorator
    
    def get_tool(self, name: str) -> Tool:
        """获取工具"""
        return self.tools.get(name)
    
    def list_tools(self, enabled_only: bool = True) -> List[Tool]:
        """列出所有工具"""
        tools = list(self.tools.values())
        if enabled_only:
            tools = [t for t in tools if t.enabled]
        return tools
    
    def call_tool(self, name: str, arguments: Dict) -> Any:
        """调用工具"""
        tool = self.get_tool(name)
        if not tool:
            raise ToolError(f"Tool not found: {name}")
        
        if not tool.enabled:
            raise ToolError(f"Tool is disabled: {name}")
        
        # 调用工具函数
        try:
            result = tool.function(**arguments)
            
            # 更新调用统计
            tool.call_count += 1
            tool.last_called = datetime.now().isoformat()
            
            return result
            
        except Exception as e:
            raise ToolError(f"Tool execution failed: {e}")
    
    def enable_tool(self, name: str):
        """启用工具"""
        tool = self.get_tool(name)
        if tool:
            tool.enabled = True
    
    def disable_tool(self, name: str):
        """禁用工具"""
        tool = self.get_tool(name)
        if tool:
            tool.enabled = False
    
    def delete_tool(self, name: str):
        """删除工具"""
        if name in self.tools:
            del self.tools[name]
    
    def list_openai_functions(self) -> List[Dict]:
        """获取 OpenAI 格式的工具定义"""
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters
                }
            }
            for tool in self.list_tools()
        ]
    
    def _build_parameters(self, func: Callable) -> Dict:
        """从函数签名构建参数定义"""
        import inspect
        
        sig = inspect.signature(func)
        parameters = {
            "type": "object",
            "properties": {},
            "required": []
        }
        
        for name, param in sig.parameters.items():
            param_info = {
                "type": "string",
                "description": ""
            }
            
            # 处理类型注解
            if param.annotation != inspect.Parameter.empty:
                param_info["type"] = self._python_type_to_json(
                    param.annotation
                )
            
            # 处理默认值
            if param.default != inspect.Parameter.empty:
                param_info["default"] = param.default
            
            parameters["properties"][name] = param_info
            
            # 必填参数
            if param.default == inspect.Parameter.empty:
                parameters["required"].append(name)
        
        return parameters
    
    def _python_type_to_json(self, python_type) -> str:
        """Python 类型转 JSON Schema 类型"""
        type_map = {
            str: "string",
            int: "integer",
            float: "number",
            bool: "boolean",
            list: "array",
            dict: "object"
        }
        
        return type_map.get(python_type, "string")
```

### 8.2 内置工具示例

```python
# 注册内置工具
@registry.register(
    name="calculator",
    description="执行数学计算。支持基本运算: 加减乘除、幂运算、括号等。",
    category="utility"
)
def calculator(expression: str) -> str:
    """计算数学表达式
    
    Args:
        expression: 数学表达式,例如 "2 + 3 * 4" 或 "(2 + 3) * 4"
    
    Returns:
        计算结果
    """
    try:
        # 安全计算 (限制运算符)
        allowed_chars = set("0123456789+-*/(). ")
        if not all(c in allowed_chars for c in expression):
            raise ValueError("Invalid characters in expression")
        
        result = eval(expression)
        return str(result)
    except Exception as e:
        return f"计算错误: {e}"


@registry.register(
    name="datetime",
    description="获取当前日期时间信息",
    category="utility"
)
def get_datetime(format: str = "%Y-%m-%d %H:%M:%S") -> str:
    """获取当前日期时间
    
    Args:
        format: 输出格式,默认为 "YYYY-MM-DD HH:mm:ss"
    
    Returns:
        格式化的时间字符串
    """
    from datetime import datetime
    return datetime.now().strftime(format)


@registry.register(
    name="search_memory",
    description="搜索用户记忆库中的相关信息",
    category="memory"
)
async def search_memory(
    query: str,
    memory_type: str = None,
    limit: int = 5
) -> str:
    """搜索记忆
    
    Args:
        query: 搜索查询
        memory_type: 记忆类型 (long_term/short_term/permanent)
        limit: 返回结果数量
    
    Returns:
        搜索结果
    """
    memories = await memory_manager.hybrid_search(
        query=query,
        memory_type=memory_type,
        limit=limit
    )
    
    if not memories:
        return "未找到相关记忆"
    
    results = [
        f"[重要度:{m.importance}] {m.content[:200]}"
        for m in memories
    ]
    
    return "\n---\n".join(results)
```

### 8.3 MCP 管理器

**文件位置**: [backend/core/tools/mcp.py](file:///d:/CXHMS/backend/core/tools/mcp.py)

```python
class MCPManager:
    """MCP (Model Context Protocol) 管理器"""
    
    def __init__(
        self,
        registry: ToolRegistry,
        mcp_config: MCPConfig
    ):
        self.registry = registry
        self.config = mcp_config
        
        # MCP 服务器进程
        self.servers: Dict[str, subprocess.Popen] = {}
        
        # 服务器工具缓存
        self.server_tools: Dict[str, List[Tool]] = {}
    
    async def start_server(
        self,
        server_id: str,
        command: List[str],
        env: Dict = None
    ) -> bool:
        """启动 MCP 服务器"""
        try:
            # 启动进程
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env={**os.environ, **(env or {})}
            )
            
            self.servers[server_id] = process
            
            # 等待并获取工具列表
            await asyncio.sleep(2)
            tools = await self._discover_server_tools(server_id)
            self.server_tools[server_id] = tools
            
            # 同步到注册表
            for tool in tools:
                wrapped_tool = self._wrap_mcp_tool(tool, server_id)
                self.registry.register(wrapped_tool)
            
            return True
            
        except Exception as e:
            logging.error(f"Failed to start MCP server: {e}")
            return False
    
    async def stop_server(self, server_id: str):
        """停止 MCP 服务器"""
        if server_id in self.servers:
            self.servers[server_id].terminate()
            del self.servers[server_id]
            
            # 从注册表移除工具
            if server_id in self.server_tools:
                for tool in self.server_tools[server_id]:
                    self.registry.delete_tool(tool.name)
                del self.server_tools[server_id]
    
    async def call_mcp_tool(
        self,
        server_id: str,
        tool_name: str,
        arguments: Dict
    ) -> Any:
        """调用 MCP 工具"""
        # 使用 JSON-RPC 调用 MCP 服务器
        request = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments
            }
        }
        
        # 发送到服务器
        server = self.servers.get(server_id)
        if not server:
            raise MCPError(f"Server not found: {server_id}")
        
        # 读取响应
        # ... 实现细节
    
    def _wrap_mcp_tool(
        self,
        mcp_tool: MCPTool,
        server_id: str
    ) -> Tool:
        """包装 MCP 工具为本地工具"""
        
        async def wrapped_tool(**kwargs):
            return await self.call_mcp_tool(
                server_id=server_id,
                tool_name=mcp_tool.name,
                arguments=kwargs
            )
        
        return Tool(
            name=f"mcp_{server_id}_{mcp_tool.name}",
            description=mcp_tool.description,
            parameters=mcp_tool.inputSchema,
            function=wrapped_tool,
            enabled=True,
            category="mcp"
        )
```

---

## 九、异常处理体系

### 9.1 自定义异常

**文件位置**: [backend/core/exceptions.py](file:///d:/CXHMS/backend/core/exceptions.py)

```python
from fastapi import HTTPException
from typing import Optional


class CXHMSException(Exception):
    """CXHMS 基础异常"""
    
    def __init__(
        self,
        message: str,
        code: str = None,
        details: Dict = None
    ):
        self.message = message
        self.code = code or "CXHMS_ERROR"
        self.details = details or {}
        super().__init__(self.message)


class DatabaseError(CXHMSException):
    """数据库操作异常"""
    
    def __init__(
        self,
        message: str,
        operation: str = None,
        table: str = None
    ):
        super().__init__(
            message=message,
            code="DATABASE_ERROR",
            details={"operation": operation, "table": table}
        )


class ValidationError(CXHMSException):
    """数据验证异常"""
    
    def __init__(
        self,
        message: str,
        field: str = None,
        value: str = None
    ):
        super().__init__(
            message=message,
            code="VALIDATION_ERROR",
            details={"field": field, "value": value}
        )


class ACPError(CXHMSException):
    """ACP 相关异常"""
    
    def __init__(
        self,
        message: str,
        agent_id: str = None,
        operation: str = None
    ):
        super().__init__(
            message=message,
            code="ACP_ERROR",
            details={"agent_id": agent_id, "operation": operation}
        )


class MemoryError(CXHMSException):
    """记忆管理异常"""
    
    def __init__(
        self,
        message: str,
        memory_id: int = None,
        operation: str = None
    ):
        super().__init__(
            message=message,
            code="MEMORY_ERROR",
            details={"memory_id": memory_id, "operation": operation}
        )


class VectorStoreError(CXHMSException):
    """向量存储异常"""
    
    def __init__(
        self,
        message: str,
        backend: str = None,
        operation: str = None
    ):
        super().__init__(
            message=message,
            code="VECTOR_STORE_ERROR",
            details={"backend": backend, "operation": operation}
        )


class LLMError(CXHMSException):
    """LLM 调用异常"""
    
    def __init__(
        self,
        message: str,
        model: str = None,
        provider: str = None
    ):
        super().__init__(
            message=message,
            code="LLM_ERROR",
            details={"model": model, "provider": provider}
        )


class ToolError(CXHMSException):
    """工具调用异常"""
    
    def __init__(
        self,
        message: str,
        tool_name: str = None,
        arguments: Dict = None
    ):
        super().__init__(
            message=message,
            code="TOOL_ERROR",
            details={"tool_name": tool_name, "arguments": arguments}
        )
```

---

## 十、前端实现

### 10.1 API 客户端

**文件位置**: [frontend/src/api/client.ts](file:///d:/CXHMS/frontend/src/api/client.ts)

```typescript
import axios, { AxiosInstance } from 'axios';


class APIClient {
  private client: AxiosInstance;
  
  constructor() {
    this.client = axios.create({
      baseURL: '/api',
      timeout: 30000,
      headers: {
        'Content-Type': 'application/json'
      }
    });
    
    // 请求拦截器
    this.client.interceptors.request.use(
      (config) => {
        // 添加认证信息
        const token = localStorage.getItem('auth_token');
        if (token) {
          config.headers.Authorization = `Bearer ${token}`;
        }
        return config;
      },
      (error) => Promise.reject(error)
    );
    
    // 响应拦截器
    this.client.interceptors.response.use(
      (response) => response.data,
      (error) => {
        console.error('API Error:', error.response?.data || error.message);
        return Promise.reject(error);
      }
    );
  }
  
  // === 服务管理 ===
  async startService(): Promise<void> {
    return this.client.post('/service/start');
  }
  
  async stopService(): Promise<void> {
    return this.client.post('/service/stop');
  }
  
  async restartService(): Promise<void> {
    return this.client.post('/service/restart');
  }
  
  async getServiceLogs(lines: number = 100): Promise<string[]> {
    return this.client.get('/service/logs', { params: { lines } });
  }
  
  // === 记忆管理 ===
  async getMemories(params: {
    workspace_id: string;
    type?: string;
    tags?: string[];
    page?: number;
    page_size?: number;
  }): Promise<PaginatedMemories> {
    return this.client.get('/memories', { params });
  }
  
  async createMemory(data: CreateMemoryRequest): Promise<Memory> {
    return this.client.post('/memories', data);
  }
  
  async searchMemories(query: string, limit?: number): Promise<Memory[]> {
    return this.client.post('/memories/search', { query, limit });
  }
  
  async semanticSearch(query: string, limit?: number): Promise<Memory[]> {
    return this.client.post('/memories/semantic-search', { query, limit });
  }
  
  async updateMemory(id: number, data: UpdateMemoryRequest): Promise<Memory> {
    return this.client.put(`/memories/${id}`, data);
  }
  
  async deleteMemory(id: number): Promise<void> {
    return this.client.delete(`/memories/${id}`);
  }
  
  // === 归档管理 ===
  async archiveMemory(id: number, level?: number): Promise<ArchiveResult> {
    return this.client.post(`/archive/${id}`, { level });
  }
  
  async mergeMemories(ids: number[]): Promise<MergeResult> {
    return this.client.post('/archive/merge', { ids });
  }
  
  async detectDuplicates(memoryId: number): Promise<number[]> {
    return this.client.post(`/archive/detect-duplicates`, { memory_id: memoryId });
  }
  
  async runAutoArchive(): Promise<AutoArchiveResult> {
    return this.client.post('/archive/auto-archive');
  }
  
  // === 聊天功能 ===
  async sendMessage(data: ChatRequest): Promise<ChatResponse> {
    return this.client.post('/chat', data);
  }
  
  async *sendMessageStream(data: ChatRequest): AsyncGenerator<string> {
    const response = await this.client.post(
      '/chat/stream',
      data,
      { responseType: 'stream' }
    );
    
    const reader = response.data.getReader();
    const decoder = new TextDecoder();
    
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      
      const chunk = decoder.decode(value);
      const lines = chunk.split('\n');
      
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const data = JSON.parse(line.slice(6));
            if (data.chunk) yield data.chunk;
            if (data.done) return;
          } catch {
            // 忽略解析错误
          }
        }
      }
    }
  }
  
  // === ACP 功能 ===
  async getAcpAgents(): Promise<ACPAgent[]> {
    return this.client.get('/acp/agents');
  }
  
  async getAcpGroups(): Promise<ACPGroup[]> {
    return this.client.get('/acp/groups');
  }
  
  async createAcpGroup(name: string, maxMembers?: number): Promise<ACPGroup> {
    return this.client.post('/acp/groups', { name, max_members: maxMembers });
  }
  
  async sendAcpMessage(agentId: string, content: any): Promise<void> {
    return this.client.post(`/acp/send/${agentId}`, { content });
  }
  
  // === Agent 管理 ===
  async getAgents(): Promise<Agent[]> {
    return this.client.get('/agents');
  }
  
  async createAgent(data: CreateAgentRequest): Promise<Agent> {
    return this.client.post('/agents', data);
  }
  
  async updateAgent(id: string, data: UpdateAgentRequest): Promise<Agent> {
    return this.client.put(`/agents/${id}`, data);
  }
  
  async deleteAgent(id: string): Promise<void> {
    return this.client.delete(`/agents/${id}`);
  }
  
  async cloneAgent(id: string, name?: string): Promise<Agent> {
    return this.client.post(`/agents/${id}/clone`, { name });
  }
  
  // === 工具管理 ===
  async getTools(): Promise<Tool[]> {
    return this.client.get('/tools');
  }
  
  async testTool(name: string, args?: any): Promise<ToolResult> {
    return this.client.post(`/tools/${name}/test`, { args });
  }
  
  async enableTool(name: string): Promise<void> {
    return this.client.post(`/tools/${name}/enable`);
  }
  
  async disableTool(name: string): Promise<void> {
    return this.client.post(`/tools/${name}/disable`);
  }
}


export const apiClient = new APIClient();
```

### 10.2 状态管理 (Zustand)

**文件位置**: [frontend/src/store/chatStore.ts](file:///d:/CXHMS/frontend/src/store/chatStore.ts)

```typescript
import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';


interface Agent {
  id: string;
  name: string;
  system_prompt: string;
  model: string;
  temperature: number;
  use_memory: boolean;
  use_tools: boolean;
  memory_scene: string;
}


interface Message {
  id: string;
  role: 'system' | 'user' | 'assistant';
  content: string;
  timestamp: string;
}


interface Session {
  id: string;
  title: string;
  message_count: number;
  created_at: string;
  updated_at: string;
}


interface ChatState {
  // Agent 管理
  agents: Agent[];
  currentAgentId: string | null;
  
  // 会话管理
  sessions: Session[];
  currentSessionId: string | null;
  currentMessages: Message[];
  
  // UI 状态
  isChatExpanded: boolean;
  isTyping: boolean;
  
  // Actions
  loadAgents: () => Promise<void>;
  selectAgent: (agentId: string) => Promise<void>;
  loadSessions: () => Promise<void>;
  createSession: () => Promise<string>;
  selectSession: (sessionId: string) => Promise<void>;
  sendMessage: (content: string) => Promise<void>;
  clearMessages: () => void;
  toggleChat: () => void;
}


export const useChatStore = create<ChatState>()(
  persist(
    (set, get) => ({
      // 初始状态
      agents: [],
      currentAgentId: null,
      sessions: [],
      currentSessionId: null,
      currentMessages: [],
      isChatExpanded: true,
      isTyping: false,
      
      // 实现方法
      async loadAgents() {
        try {
          const agents = await apiClient.getAgents();
          set({ agents });
          
          // 选择第一个 Agent
          if (agents.length > 0 && !get().currentAgentId) {
            set({ currentAgentId: agents[0].id });
          }
        } catch (error) {
          console.error('Failed to load agents:', error);
        }
      },
      
      async selectAgent(agentId: string) {
        set({ currentAgentId: agentId });
      },
      
      async loadSessions() {
        try {
          const sessions = await apiClient.getSessions();
          set({ sessions });
        } catch (error) {
          console.error('Failed to load sessions:', error);
        }
      },
      
      async createSession() {
        try {
          const session = await apiClient.createSession();
          set((state) => ({
            sessions: [session, ...state.sessions],
            currentSessionId: session.id,
            currentMessages: []
          }));
          return session.id;
        } catch (error) {
          console.error('Failed to create session:', error);
          throw error;
        }
      },
      
      async selectSession(sessionId: string) {
        try {
          const messages = await apiClient.getMessages(sessionId);
          set({
            currentSessionId: sessionId,
            currentMessages: messages
          });
        } catch (error) {
          console.error('Failed to load messages:', error);
        }
      },
      
      async sendMessage(content: string) {
        const state = get();
        
        if (!state.currentSessionId) {
          await get().createSession();
        }
        
        const sessionId = state.currentSessionId!;
        const agentId = state.currentAgentId!;
        
        // 添加用户消息
        const userMessage: Message = {
          id: crypto.randomUUID(),
          role: 'user',
          content,
          timestamp: new Date().toISOString()
        };
        
        set((state) => ({
          currentMessages: [...state.currentMessages, userMessage],
          isTyping: true
        }));
        
        try {
          // 发送消息并流式接收
          const response = await apiClient.sendMessage({
            agent_id: agentId,
            session_id: sessionId,
            message: content
          });
          
          // 添加助手消息
          const assistantMessage: Message = {
            id: crypto.randomUUID(),
            role: 'assistant',
            content: response.response,
            timestamp: new Date().toISOString()
          };
          
          set((state) => ({
            currentMessages: [...state.currentMessages, assistantMessage],
            isTyping: false
          }));
          
        } catch (error) {
          console.error('Failed to send message:', error);
          set({ isTyping: false });
          
          // 添加错误消息
          const errorMessage: Message = {
            id: crypto.randomUUID(),
            role: 'assistant',
            content: '抱歉,发生了错误,请稍后重试。',
            timestamp: new Date().toISOString()
          };
          
          set((state) => ({
            currentMessages: [...state.currentMessages, errorMessage]
          }));
        }
      },
      
      clearMessages() {
        set({ currentMessages: [] });
      },
      
      toggleChat() {
        set((state) => ({ isChatExpanded: !state.isChatExpanded }));
      }
    }),
    {
      name: 'cxhms-chat-storage',
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({
        currentAgentId: state.currentAgentId,
        currentSessionId: state.currentSessionId,
        isChatExpanded: state.isChatExpanded
      })
    }
  )
);
```

---

## 十一、测试配置

### 11.1 前端测试 (Vitest)

**文件位置**: [frontend/vitest.config.ts](file:///d:/CXHMS/frontend/vitest.config.ts)

```typescript
import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';


export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json', 'html'],
      exclude: [
        'node_modules/',
        'src/test/',
        '**/*.d.ts',
        '**/*.test.ts',
        '**/*.test.tsx'
      ]
    },
    include: ['src/**/*.test.{ts,tsx}']
  }
});
```

### 11.2 后端测试 (pytest)

**文件位置**: [pytest.ini](file:///d:/CXHMS/pytest.ini)

```ini
[pytest]
testpaths = backend/tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts = -v --tb=short --strict-markers
markers =
    unit: Unit tests
    integration: Integration tests
    api: API tests
    slow: Slow running tests
filterwarnings =
    ignore::DeprecationWarning
    ignore::PendingDeprecationWarning
```

### 11.3 测试用例示例

```python
# backend/tests/test_api/test_chat.py


import pytest
from fastapi.testclient import TestClient
from backend.api.app import app


@pytest.fixture
def client():
    """创建测试客户端"""
    return TestClient(app)


@pytest.fixture
def mock_memory_manager():
    """模拟记忆管理器"""
    manager = MagicMock()
    manager.hybrid_search = AsyncMock(return_value=[])
    return manager


@pytest.fixture
def mock_context_manager():
    """模拟上下文管理器"""
    manager = MagicMock()
    manager.get_or_create_session = AsyncMock(return_value=Session(id="test-session"))
    manager.add_message = AsyncMock(return_value=Message(id="test-msg"))
    manager.get_messages = AsyncMock(return_value=[])
    return manager


@pytest.mark.api
class TestChatAPI:
    """聊天 API 测试类"""
    
    def test_send_message_success(self, client, mock_context_manager, mock_memory_manager):
        """测试发送消息成功"""
        # 模拟依赖
        app.dependency_overrides[get_context_manager] = lambda: mock_context_manager
        app.dependency_overrides[get_memory_manager] = lambda: mock_memory_manager
        
        response = client.post(
            "/api/chat",
            json={
                "agent_id": "default",
                "message": "你好",
                "session_id": None
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "response" in data
        assert "session_id" in data
        
        # 清理覆盖
        app.dependency_overrides.clear()
    
    def test_send_message_with_memory(self, client, mock_context_manager, mock_memory_manager):
        """测试带记忆检索的消息"""
        # 设置模拟返回
        mock_memory_manager.hybrid_search = AsyncMock(return_value=[
            Memory(
                id=1,
                content="用户喜欢编程",
                importance=4
            )
        ])
        
        app.dependency_overrides[get_memory_manager] = lambda: mock_memory_manager
        
        response = client.post(
            "/api/chat",
            json={
                "agent_id": "default",
                "message": "我最近在做什么?",
                "session_id": "test-session"
            }
        )
        
        assert response.status_code == 200
        mock_memory_manager.hybrid_search.assert_called_once()
        
        app.dependency_overrides.clear()
    
    def test_stream_chat(self, client, mock_context_manager):
        """测试流式聊天"""
        app.dependency_overrides[get_context_manager] = lambda: mock_context_manager
        
        with client.post(
            "/api/chat/stream",
            json={
                "agent_id": "default",
                "message": "讲个笑话"
            },
            stream=True
        ) as response:
            assert response.status_code == 200
            
            chunks = []
            for line in response.iter_lines():
                if line:
                    data = json.loads(line.decode('utf-8'))
                    if data.get('chunk'):
                        chunks.append(data['chunk'])
            
            # 验证收到流式数据
            assert len(chunks) > 0
        
        app.dependency_overrides.clear()


# frontend/src/store/chatStore.test.ts


import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useChatStore } from './chatStore';


describe('ChatStore', () => {
  beforeEach(() => {
    // 重置状态
    useChatStore.setState({
      agents: [],
      currentAgentId: null,
      sessions: [],
      currentSessionId: null,
      currentMessages: [],
      isChatExpanded: true,
      isTyping: false
    });
    
    // 模拟 API
    vi.mock('../api/client', () => ({
      apiClient: {
        getAgents: vi.fn().mockResolvedValue([
          { id: '1', name: 'Agent 1', system_prompt: 'Hello' }
        ]),
        getSessions: vi.fn().mockResolvedValue([]),
        createSession: vi.fn().mockResolvedValue({ id: 'session-1' }),
        getMessages: vi.fn().mockResolvedValue([]),
        sendMessage: vi.fn().mockResolvedValue({
          response: 'Hello!'
        })
      }
    }));
  });
  
  describe('loadAgents', () => {
    it('should load agents and select first one', async () => {
      const { result } = renderHook(() => useChatStore());
      
      await act(async () => {
        await result.current.loadAgents();
      });
      
      expect(result.current.agents).toHaveLength(1);
      expect(result.current.currentAgentId).toBe('1');
    });
  });
  
  describe('sendMessage', () => {
    it('should add user message and assistant response', async () => {
      const { result } = renderHook(() => useChatStore());
      
      // 先加载 agent
      await act(async () => {
        await result.current.loadAgents();
      });
      
      // 发送消息
      await act(async () => {
        await result.current.sendMessage('Hello');
      });
      
      expect(result.current.currentMessages).toHaveLength(2);
      expect(result.current.currentMessages[0].role).toBe('user');
      expect(result.current.currentMessages[1].role).toBe('assistant');
    });
  });
});
```

---

## 十二、核心业务流程图

### 12.1 消息处理完整流程

```
┌─────────────────────────────────────────────────────────────────┐
│                        用户发送消息                              │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  1. 获取 Agent 配置 (系统提示词、模型、温度等)                      │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  2. 会话管理                                                     │
│     - 如果有 session_id: 获取已有会话                            │
│     - 如果没有: 创建新会话                                        │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  3. 添加用户消息到上下文                                          │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  4. 记忆检索 (如果启用)                                          │
│     - MemoryRouter.route() → 根据场景配置路由                     │
│     - HybridSearch → 向量搜索 + 关键词搜索                        │
│     - DecayCalculator → 计算时间衰减分数                         │
│     - 综合评分排序                                               │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  5. 构建消息列表                                                │
│     ┌──────────────────────────────────────────────────────┐   │
│     │ [System] 你是一个智能助手...                            │   │
│     │ [System] 相关记忆:                                     │   │
│     │ - 记忆1 (重要性: 4, 相关度: 0.85)                       │   │
│     │ - 记忆2 (重要性: 3, 相关度: 0.72)                       │   │
│     │ [User] 你好,请帮我...                                   │   │
│     └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  6. 调用 LLM                                                    │
│     - 选择模型 (main/summary/memory)                            │
│     - ModelRouter.chat()                                        │
│     - 传递工具定义 (如果启用工具)                                 │
└─────────────────────────────────────────────────────────────────┘
                              ↓
           ┌────────────────┴────────────────┐
           ↓                                 ↓
    ┌─────────────┐                 ┌─────────────┐
    │  普通响应    │                 │ 工具调用请求 │
    └─────────────┘                 └─────────────┘
           ↓                                 ↓
    ┌─────────────┐                 ┌─────────────┐
    │ 保存到上下文 │                 │ 执行工具调用 │
    │ 返回给用户  │                 │ 收集结果     │
    └─────────────┘                 └─────────────┘
           ↓                                 ↓
           └────────────────┬────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  7. 可选: 保存重要内容到记忆                                      │
│     - 评估内容重要性                                             │
│     - 生成向量嵌入                                               │
│     - 写入记忆库                                                 │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  8. 返回响应                                                    │
└─────────────────────────────────────────────────────────────────┘
```

### 12.2 记忆检索评分流程

```
┌─────────────────────────────────────────────────────────────────┐
│                        检索请求                                  │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  1. 生成查询向量                                                 │
│     - LLMClient.get_embedding(query)                            │
└─────────────────────────────────────────────────────────────────┘
                              ↓
           ┌────────────────┴────────────────┐
           ↓                                 ↓
    ┌─────────────┐                 ┌─────────────┐
    │ 向量搜索     │                 │ 关键词搜索   │
    │ (余弦相似度) │                 │ (BM25/TF-IDF)│
    └─────────────┘                 └─────────────┘
           ↓                                 ↓
           └────────────────┬────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  2. 分数融合 (RRF)                                              │
│     score = w1 * vector_rank + w2 * text_rank                   │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  3. 3D 评分 (场景感知)                                          │
│                                                              │
│     final = importance_w * importance_score                    │
│           + time_w * time_score                               │
│           + relevance_w * relevance_score                      │
│                                                              │
│     场景配置示例:                                                │
│     - chat: importance=0.45, time=0.20, relevance=0.35         │
│     - task: importance=0.30, time=0.20, relevance=0.50        │
│     - creative: importance=0.30, time=0.40, relevance=0.30    │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  4. 过滤低分记忆 (阈值: 0.3)                                     │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  5. 返回排序后的记忆列表 (Top-K)                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 12.3 ACP 消息流程

```
┌─────────────────────────────────────────────────────────────────┐
│                      Agent A 发送消息                            │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  1. 消息序列化                                                   │
│     - ACPMessageInfo → JSON                                     │
│     - 添加时间戳、相关性 ID                                       │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  2. 路由选择                                                     │
│     - 如果是直接消息: 发送到目标 Agent                           │
│     - 如果是广播: 发送到所有已连接 Agent                         │
│     - 如果是群组消息: 发送到群组成员                              │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  3. HTTP POST 发送                                              │
│     POST http://target:port/acp/receive                         │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  4. Agent B 接收消息                                            │
│     - 验证消息格式                                               │
│     - 查找消息处理器                                             │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  5. 消息处理                                                     │
│     - chat: 添加到对话上下文                                     │
│     - memory_request: 执行搜索,返回结果                          │
│     - tool_call: 执行工具,返回结果                               │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  6. 发送响应 (如果需要)                                          │
│     - 创建响应消息                                               │
│     - HTTP POST 返回                                            │
└─────────────────────────────────────────────────────────────────┘
```

---

## 十三、功能总结

### 13.1 核心功能列表

| 功能模块 | 功能项 | 状态 | 说明 |
|---------|-------|------|------|
| **记忆管理** | 记忆 CRUD | ✅ | 支持创建、读取、更新、删除 |
| | 语义搜索 | ✅ | 基于向量的相似度搜索 |
| | 混合搜索 | ✅ | 向量 + 关键词融合搜索 |
| | 记忆衰减 | ✅ | 艾宾浩斯遗忘曲线模型 |
| | 归档管理 | ✅ | 智能去重、层级压缩 |
| | 情感分析 | ✅ | 记忆情感标记 |
| **对话系统** | 聊天对话 | ✅ | 支持流式/非流式 |
| | Agent 配置 | ✅ | 灵活的系统提示词 |
| | 上下文管理 | ✅ | 会话历史、Mono 上下文 |
| | 记忆增强 | ✅ | RAG 检索增强生成 |
| **ACP 协议** | Agent 发现 | ✅ | 局域网自动发现 |
| | 点对点通信 | ✅ | 直接消息传递 |
| | 群组通信 | ✅ | 多 Agent 协同 |
| | 记忆共享 | ✅ | 跨 Agent 记忆访问 |
| **工具系统** | 内置工具 | ✅ | 计算器、搜索等 |
| | MCP 集成 | ✅ | Model Context Protocol |
| | 工具注册 | ✅ | 动态注册自定义工具 |
| **LLM 集成** | Ollama | ✅ | 本地 LLM 支持 |
| | OpenAI | ✅ | OpenAI 兼容 API |
| | Anthropic | ✅ | Claude 兼容 |
| | 向量生成 | ✅ | 文本嵌入 |
| **前端界面** | 聊天界面 | ✅ | React 实现 |
| | 记忆管理 | ✅ | CRUD 界面 |
| | 归档管理 | ✅ | 可视化界面 |
| | Agent 配置 | ✅ | 配置编辑器 |
| | 工具管理 | ✅ | 工具列表、测试 |

### 13.2 技术亮点

1. **多层次记忆系统**
   - 短期/长期/永久记忆分类
   - 重要性动态评分
   - 场景感知路由

2. **智能衰减机制**
   - 艾宾浩斯遗忘曲线
   - 可配置的衰减参数
   - 自动重新激活

3. **灵活的 ACP 协议**
   - 局域网自动发现
   - 群组协同工作
   - 跨 Agent 记忆共享

4. **强大的工具生态**
   - MCP 协议支持
   - 内置工具库
   - 动态工具注册

5. **完善的前端体验**
   - React 18 + TypeScript
   - Zustand 状态管理
   - 响应式设计

### 13.3 项目结构优势

- **模块化设计**: 各功能模块独立,便于扩展
- **清晰的分层**: API → Core → Storage
- **完善的测试**: 30+ 测试用例覆盖核心功能
- **类型安全**: TypeScript + Pydantic 双重保障
- **配置灵活**: YAML 配置文件支持多环境

---

## 报告生成时间

2026-02-08

## 版本

CXHMS v1.0.0

## 作者

CXHMS Development Team
