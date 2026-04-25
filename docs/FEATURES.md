# 知识图谱集成功能

本文档详细介绍项目的知识图谱集成实现逻辑。

## 架构概览

该项目实现了一个**语义图数据库系统**，核心代码位于 `backend/core/graph/` 目录，采用 **SQLite + Weaviate** 的混合架构：

```
backend/core/graph/
├── __init__.py          # 主入口 GraphDatabase 类
├── config.py            # 配置管理
├── database.py          # SQLite 数据库连接
├── models.py            # 数据模型
├── nodes.py             # 节点 CRUD 操作
├── edges.py             # 边 CRUD 操作
├── traversal.py         # 图遍历算法
├── semantic_search.py   # 语义搜索
├── hybrid_query.py      # 混合查询（图+语义）
├── vectorizer.py        # 文本向量化
├── visualization.py     # 图可视化导出
└── monitoring.py        # 健康检查和监控
```

## 核心组件

### 1. 数据模型

系统定义了两个核心数据结构：

```python
@dataclass
class GraphNode:
    id: str                    # 节点唯一标识
    type: str                  # 节点类型
    properties: Dict[str, Any] # 属性字典
    text_content: str          # 文本内容（用于语义搜索）
    vector_id: str             # 向量索引ID
    created_at / updated_at    # 时间戳

@dataclass
class GraphEdge:
    id: str                    # 边唯一标识
    source_id: str             # 起始节点
    target_id: str             # 目标节点
    relation_type: str         # 关系类型
    properties: Dict[str, Any] # 属性字典
    text_content: str          # 文本内容
    vector_id: str             # 向量索引ID
```

### 2. 四类知识图谱

系统支持四种不同类型的知识图谱：

| 图谱类型 | 实体类型 | 关系类型 | 用途 |
|---------|---------|---------|------|
| **User Graph** | person, user, contact | knows, friend, family, colleague, enemy | 用户关系网络 |
| **Thing Graph** | object, item, product | owns, part_of, similar_to, located_at, made_of | 事物关系 |
| **Concept Graph** | concept, idea, topic | related_to, subtopic_of, opposite_of, implies | 概念知识 |
| **Event Graph** | event, activity, occurrence | caused, followed_by, concurrent_with, prevents | 事件关系 |

### 3. 数据库层

使用 **SQLite** 作为底层存储，表结构设计：

```sql
-- 节点表
CREATE TABLE nodes (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    properties TEXT NOT NULL DEFAULT '{}',
    text_content TEXT,
    vector_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- 边表
CREATE TABLE edges (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    properties TEXT NOT NULL DEFAULT '{}',
    text_content TEXT,
    vector_id TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (source_id) REFERENCES nodes(id),
    FOREIGN KEY (target_id) REFERENCES nodes(id)
);
```

### 4. 语义搜索

集成 **Weaviate** 向量数据库实现语义搜索：

```python
class SemanticSearch:
    def search(self, query: str, node_type: str, limit: int):
        # 1. 将查询文本向量化
        query_vector = self._vectorizer.encode(query)
        
        # 2. 在 Weaviate 中进行向量相似度搜索
        results = self._client.query.get("GraphNode", [...])
            .with_near_vector({"vector": query_vector.tolist()})
            .with_limit(limit)
            .do()
        
        # 3. 返回语义相似的节点
        return [SemanticSearchResult(node_id, score) ...]
```

支持**回退模式**：当 Weaviate 不可用时，使用本地关键词匹配。

### 5. 图遍历算法

实现了多种经典图算法：

| 算法 | 方法 | 功能 |
|-----|------|------|
| **BFS** | `bfs_traverse()` | 广度优先遍历 |
| **DFS** | `dfs_traverse()` | 深度优先遍历 |
| **Dijkstra** | `shortest_path()` | 最短路径查找 |
| **PageRank** | `pagerank()` | 节点重要性排序 |
| **LPA** | `_lpa_community_detection()` | 标签传播社区发现 |
| **Louvain** | `_louvain_community_detection()` | 模块度优化社区发现 |

### 6. 混合查询

结合**图结构**和**语义相似度**的混合查询：

```python
class HybridQueryManager:
    def semantic_path_discovery(self, start_id, end_id, semantic_weight=0.3):
        # 1. 找出所有路径
        all_paths = self.traversal.all_paths(start_id, end_id)
        
        # 2. 计算路径语义相似度
        semantic_score = self._calculate_path_semantic_score(path)
        
        # 3. 计算结构分数（路径越短越好）
        structural_score = 1.0 / (edge_count + 1)
        
        # 4. 综合评分
        combined_score = (1 - semantic_weight) * structural_score + semantic_weight * semantic_score
```

## 工具注册机制

系统为 AI 模型注册了 **56 个图工具**，供主模型、摘要模型和记忆管理 Agent 调用：

```python
def register_graph_tools():
    # 每类图谱 14 个工具，共 4 类图谱
    user_graph_tools = [
        user_graph_create_entity,      # 创建实体
        user_graph_create_relation,    # 创建关系
        user_graph_query_entities,     # 查询关联实体
        user_graph_find_paths,         # 查找路径
        user_graph_search_related_memories,  # 图增强记忆搜索
        user_graph_extract_entities,   # 提取实体
        user_graph_merge_entities,     # 合并实体
        user_graph_get_entity_summary, # 获取实体摘要
        user_graph_update_entity,      # 更新实体
        user_graph_delete_entity,      # 删除实体
        user_graph_update_relation,    # 更新关系
        user_graph_delete_relation,    # 删除关系
        user_graph_get_stats,          # 获取统计
        user_graph_export,             # 导出数据
    ]
    # thing_graph_tools, concept_graph_tools, event_graph_tools 类似...
```

## API 路由

提供 RESTful API 接口：

| 端点 | 方法 | 功能 |
|-----|------|------|
| `/graph/nodes` | POST | 创建节点 |
| `/graph/nodes/{id}` | GET/PUT/DELETE | 节点 CRUD |
| `/graph/edges` | POST | 创建边 |
| `/graph/search/semantic` | POST | 语义搜索 |
| `/graph/search/hybrid` | POST | 混合搜索 |
| `/graph/traverse/bfs` | POST | BFS 遍历 |
| `/graph/traverse/shortest-path` | POST | 最短路径 |

## 架构示意图

```
┌─────────────────────────────────────────────────────────────┐
│                     GraphDatabase 主入口                      │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │ NodeManager │  │ EdgeManager │  │ TraversalManager    │  │
│  │   节点管理   │  │   边管理    │  │ 图遍历算法          │  │
│  └──────┬──────┘  └──────┬──────┘  └──────────┬──────────┘  │
│         │                │                    │              │
│         └────────────────┼────────────────────┘              │
│                          ▼                                   │
│  ┌───────────────────────────────────────────────────────┐   │
│  │              Database (SQLite)                         │   │
│  │  ┌─────────────┐        ┌─────────────┐               │   │
│  │  │ nodes 表    │        │ edges 表    │               │   │
│  │  └─────────────┘        └─────────────┘               │   │
│  └───────────────────────────────────────────────────────┘   │
│                          │                                   │
│                          ▼                                   │
│  ┌───────────────────────────────────────────────────────┐   │
│  │              SemanticSearch (Weaviate)                 │   │
│  │  ┌─────────────┐        ┌─────────────┐               │   │
│  │  │ 向量索引    │        │ 语义搜索    │               │   │
│  │  └─────────────┘        └─────────────┘               │   │
│  └───────────────────────────────────────────────────────┘   │
│                          │                                   │
│                          ▼                                   │
│  ┌───────────────────────────────────────────────────────┐   │
│  │              HybridQueryManager                        │   │
│  │         混合查询（图结构 + 语义相似度）                  │   │
│  └───────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

## 核心设计亮点

1. **轻量级架构**：使用 SQLite 替代 Neo4j，降低部署复杂度
2. **语义增强**：集成 Weaviate 向量数据库，支持语义搜索
3. **多图谱隔离**：四类图谱独立管理，支持不同领域的知识建模
4. **混合查询**：结合图结构和语义相似度，提供更智能的检索能力
5. **丰富的图算法**：内置 PageRank、社区发现等高级分析能力
6. **AI 工具集成**：为 LLM 提供 56 个图操作工具，实现知识图谱的智能管理

## 配置说明

### 环境变量

| 变量名 | 默认值 | 说明 |
|-------|-------|------|
| `GRAPH_DATABASE_PATH` | `data/graph.db` | SQLite 数据库路径 |
| `GRAPH_AUTO_CREATE` | `true` | 自动创建表结构 |
| `GRAPH_POOL_SIZE` | `10` | 连接池大小 |
| `GRAPH_TIMEOUT` | `30` | 超时时间（秒） |
| `WEAVIATE_URL` | `http://localhost:8080` | Weaviate 服务地址 |
| `WEAVIATE_API_KEY` | - | Weaviate API 密钥 |
| `WEAVIATE_VECTOR_DIM` | `384` | 向量维度 |
| `EMBEDDING_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | 向量化模型 |

### 配置类

```python
@dataclass
class GraphConfig:
    database_path: str = "data/graph.db"
    auto_create_schema: bool = True
    pool_size: int = 10
    timeout: int = 30
    weaviate: WeaviateConfig
    embedding: EmbeddingConfig
```

## 使用示例

### 初始化图数据库

```python
from backend.core.graph import GraphDatabase

graph = GraphDatabase()
graph.initialize()
```

### 创建节点和边

```python
from backend.core.graph.models import NodeCreate, EdgeCreate

# 创建节点
node = graph.nodes.create(NodeCreate(
    type="person",
    properties={"name": "张三", "age": 30},
    text_content="张三是一名软件工程师"
))

# 创建关系
edge = graph.edges.create(EdgeCreate(
    source_id=node1.id,
    target_id=node2.id,
    relation_type="knows",
    text_content="张三认识李四"
))
```

### 语义搜索

```python
results = graph.semantic.search(
    query="软件工程师",
    node_type="person",
    limit=10
)
```

### 混合查询

```python
paths = graph.hybrid.semantic_path_discovery(
    start_id="node1",
    end_id="node2",
    semantic_weight=0.3
)
```

### 图遍历

```python
# BFS 遍历
nodes = graph.traversal.bfs_traverse(start_id="node1", max_depth=3)

# 最短路径
path = graph.traversal.shortest_path(start_id="node1", end_id="node2")

# PageRank 排序
important_nodes = graph.traversal.get_important_nodes(limit=10)
```

---

# 三档防火墙系统

本文档详细介绍项目的三档防火墙实现逻辑。

## 架构概览

三档防火墙是一个**直播弹幕内容审核与决策系统**，核心代码位于 `backend/services/firewall.py` 和 `gateway/services/firewall.py`，采用**规则过滤 + LLM 智能决策**的混合架构。

```
backend/services/firewall.py    # 后端防火墙服务
gateway/services/firewall.py    # 网关防火墙服务
config/firewall.yaml            # 基础配置
config/firewall_v3.yaml         # V3 增强配置（ASR 打断）
```

## 三档决策模型

系统将弹幕分为三个等级处理：

| 档位 | 决策类型 | 含义 | 处理方式 |
|------|----------|------|----------|
| **第一档** | `block` | 阻断 | 违规内容，直接拦截，不进入上下文 |
| **第二档** | `passive` | 放行 | 正常弹幕，通过但不主动回复 |
| **第三档** | `reply` | 回复 | 优质弹幕，值得互动回复 |

## 核心组件

### 1. 单例模式

```python
class FirewallService:
    _instance = None
    
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
```

确保全局只有一个防火墙实例，统一管理弹幕决策。

### 2. 依赖注入

| 组件 | 用途 |
|------|------|
| `_cxhms_client` | LLM 客户端，用于智能决策 |
| `_context_manager` | 上下文管理器，获取会话历史 |
| `_session_id` | 当前会话 ID |

### 3. 决策流程

```
弹幕数据 → 黑名单检查 → LLM 智能决策 → 返回决策结果
              ↓              ↓
           快速拦截      深度分析
```

## 决策逻辑详解

### Step 1: 黑名单快速过滤

```python
if self.blacklist_enabled and user_id in self.blacklist:
    return {
        "decision": "block",
        "confidence": 1.0,
        "reason": "用户在黑名单中",
        "added_to_context": False,
        "reply_triggered": False
    }
```

- 优先级最高，快速拦截黑名单用户
- 置信度固定为 1.0
- 不加入上下文，不触发回复

### Step 2: LLM 智能决策

```python
result = await self._cxhms_client.request("chat", {
    "messages": messages,
    "stream": False
}, timeout=10.0)
```

- 构建决策 Prompt
- 调用 LLM 进行内容分析
- 解析 JSON 格式返回结果

## 决策 Prompt 设计

系统通过精心设计的 Prompt 引导 LLM 进行判断：

### BLOCK (阻断) 触发条件

- 政治敏感内容
- 色情低俗内容
- 暴力血腥内容
- 垃圾广告
- 恶意刷屏
- 人身攻击

### PASSIVE (放行) 触发条件

- 普通问候
- 闲聊内容
- 简单表情

### REPLY (回复) 触发条件

- 有趣的提问
- 感谢支持
- 有意义的互动
- 需要回答的问题

### Prompt 模板

```python
def _build_decision_prompt(self, content: str, user: Dict, context: list = None) -> str:
    return f"""你是一个直播弹幕安全审查助手。请根据以下规则判断弹幕内容：

【弹幕内容】
{content}

【用户信息】
- 用户名: {user.get('username', '')}
- 勋章等级: {user.get('badge_level', 0)}
- 舰队等级: {user.get('guard_level', 0)}

【判断规则】
1. BLOCK (阻断): 违规内容...
2. PASSIVE (放行): 正常弹幕...
3. REPLY (回复): 优质弹幕...

请以 JSON 格式返回结果：
{{"decision": "block|passive|reply", "confidence": 0.0-1.0, "reason": "简要原因"}}
"""
```

## 返回结果结构

```python
{
    "decision": "block|passive|reply",  # 决策类型
    "confidence": 0.0-1.0,               # 置信度
    "reason": "原因",                    # 决策原因
    "added_to_context": bool,            # 是否加入上下文
    "reply_triggered": bool              # 是否触发回复
}
```

## 配置说明

### 基础配置 (firewall.yaml)

```yaml
llm:
  default_model: "qwen2.5:latest"
  
blocking:
  blacklist: ["123456", "789012"]  # 黑名单用户ID
  blacklist_enabled: true

decision:
  timeout_ms: 5000  # 决策超时
```

### V3 增强配置 (firewall_v3.yaml)

```yaml
interrupt:
  enabled: true
  mode: "main_llm"  # 模式: main_llm | independent_llm
  
  # 模式 A: 主 LLM（低延迟）
  main_llm:
    enabled: true
    prompt: |
      你是一个直播助手。当用户说话时，你需要判断是否需要打断当前正在进行的回复。
      输出 "##[interrupt]##" 表示需要打断并回复用户。
      输出 "##[no_reply]##" 表示不需要回复。
      
  # 模式 B: 独立 LLM（专用决策）
  independent_llm:
    enabled: false
    model: "qwen2.5:1.5b"
    endpoint: "http://localhost:11434"
    polling_interval_ms: 1000
    timeout_ms: 5000
    
  rules:
    auto_reply_on_interrupt: true
    priority_users:
      - guard_level: 3  # 舰艇总督
      - is_admin: true  # 房管
```

## 容错机制

| 场景 | 处理方式 |
|------|----------|
| LLM 不可用 | 默认放行 (`passive`)，避免误伤 |
| JSON 解析失败 | 记录警告，返回默认决策 |
| 异常捕获 | 记录错误日志，保证服务稳定 |

```python
except Exception as e:
    logger.error(f"LLM decision error: {e}")
    return {
        "decision": "passive",
        "confidence": 0.0,
        "reason": f"决策出错: {str(e)}",
        "added_to_context": True,
        "reply_triggered": False
    }
```

## 架构示意图

```
┌─────────────────────────────────────────────────────────────┐
│                    FirewallService                          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              弹幕数据输入                             │   │
│  │  { content, user: { uid, username, badge_level } }  │   │
│  └──────────────────────┬──────────────────────────────┘   │
│                         ▼                                   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │           黑名单快速过滤 (第一道防线)                 │   │
│  │  - 检查用户 ID 是否在黑名单                          │   │
│  │  - 命中则直接返回 block                              │   │
│  └──────────────────────┬──────────────────────────────┘   │
│                         ▼                                   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │           LLM 智能决策 (第二道防线)                   │   │
│  │  - 构建决策 Prompt                                   │   │
│  │  - 调用 CXHMS 客户端                                 │   │
│  │  - 解析 JSON 返回结果                                │   │
│  └──────────────────────┬──────────────────────────────┘   │
│                         ▼                                   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              决策结果输出                             │   │
│  │  { decision, confidence, reason, ... }              │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## 核心设计亮点

1. **双层防护**：规则过滤（黑名单）+ 智能决策（LLM），兼顾效率与准确性
2. **三档分级**：精细化处理不同类型的弹幕，避免一刀切
3. **上下文感知**：结合会话历史进行决策，提升判断准确性
4. **容错优先**：LLM 不可用时默认放行，避免误伤正常用户
5. **V3 增强**：支持 ASR 打断功能，两种模式灵活切换

## 使用示例

### 初始化防火墙

```python
from backend.services.firewall import FirewallService

firewall = FirewallService.get_instance()
firewall.load_config({
    "blocking": {
        "blacklist": ["123456", "789012"],
        "blacklist_enabled": True
    },
    "llm": {
        "default_model": "qwen2.5:latest"
    }
})
```

### 设置依赖

```python
firewall.set_cxhms_client(cxhms_client)
firewall.set_context_manager(context_manager, session_id="session_001")
```

### 弹幕决策

```python
result = await firewall.decide_danmaku({
    "content": "主播今天直播多久？",
    "user": {
        "uid": "12345678",
        "username": "测试用户",
        "badge_level": 20,
        "guard_level": 1
    }
})

# result:
# {
#     "decision": "reply",
#     "confidence": 0.9,
#     "reason": "用户提出了有意义的问题",
#     "added_to_context": True,
#     "reply_triggered": True
# }
```

---

# 智能记忆系统

本文档详细介绍项目的智能记忆系统实现逻辑。

## 架构概览

智能记忆系统是一个**模拟人类记忆机制的对话记忆管理解决方案**，核心代码位于 `backend/core/memory/` 目录，采用 **SQLite + Weaviate + LLM** 的混合架构：

```
backend/core/memory/
├── manager.py              # 核心管理器 MemoryManager
├── decay.py                # 记忆衰减计算器
├── hybrid_search.py        # 混合搜索引擎
├── router.py               # 记忆路由器（场景感知）
├── vector_store.py         # 向量存储基类
├── weaviate_store.py       # Weaviate 向量存储实现
├── embedding.py            # 嵌入模型工厂
├── deduplication.py        # 去重引擎
├── archiver.py             # 记忆归档器
├── conversation.py         # 对话记忆处理
├── async_manager.py        # 异步管理器
├── emotion.py              # 情感分析
└── vectorization_queue.py  # 向量化队列
```

## 核心组件

### 1. MemoryManager - 记忆管理器

采用**单例模式**设计，是整个系统的核心：

```python
class MemoryManager:
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls, db_path: str = "data/memories.db"):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
```

**主要职责**：

| 功能模块 | 说明 |
|---------|------|
| **记忆存储** | SQLite 数据库存储记忆元数据，支持多 Agent 隔离 |
| **向量同步** | 异步向量化队列，非阻塞写入 |
| **连接池** | 线程本地连接池，自动清理空闲连接 |
| **批量操作** | 支持批量写入、更新、删除、归档 |
| **审计日志** | 所有操作都有记录 |

**记忆数据结构**：

```sql
CREATE TABLE memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type VARCHAR(20) NOT NULL,           -- 记忆类型
    content TEXT NOT NULL,               -- 记忆内容
    vector_id VARCHAR(100),              -- 向量索引ID
    metadata TEXT,                       -- 元数据
    importance INTEGER DEFAULT 3,        -- 重要性等级 (1-5)
    importance_score FLOAT DEFAULT 0.6,  -- 重要性分数 (0-1)
    decay_type VARCHAR(20),              -- 衰减类型
    decay_params TEXT,                   -- 衰减参数
    reactivation_count INTEGER DEFAULT 0,-- 再激活次数
    emotion_score FLOAT DEFAULT 0.0,     -- 情感分数
    permanent BOOLEAN DEFAULT FALSE,     -- 是否永久记忆
    psychological_age FLOAT DEFAULT 1.0, -- 心理年龄
    tags TEXT,                           -- 标签列表
    created_at TIMESTAMP,                -- 创建时间
    updated_at TIMESTAMP,                -- 更新时间
    archived_at TIMESTAMP,               -- 归档时间
    is_deleted BOOLEAN DEFAULT FALSE,    -- 是否删除
    source VARCHAR(50),                  -- 来源
    workspace_id VARCHAR(100),           -- 工作区ID
    agent_id VARCHAR(100)                -- Agent ID (多租户隔离)
);
```

### 2. DecayCalculator - 记忆衰减计算器

模拟人类记忆遗忘曲线，采用**双阶段指数衰减模型**：

```
T(t) = α·e^(-λ₁·Δt) + (1-α)·e^(-λ₂·Δt)
```

**重要性分级衰减参数**：

| 重要性分数 | 衰减类型 | α值 | λ₁值 | λ₂值 | 180天保留率 |
|-----------|---------|-----|------|------|------------|
| ≥0.95 | zero (永久) | - | - | - | 100% |
| 0.85-0.99 | exponential | 0.2 | 0.01 | 0.001 | 95% |
| 0.70-0.84 | exponential | 0.35 | 0.08 | 0.015 | 80% |
| 0.50-0.69 | exponential | 0.6 | 0.25 | 0.04 | 50% |
| 0.30-0.49 | exponential | 0.75 | 0.45 | 0.08 | 25% |
| <0.30 | exponential | 0.9 | 0.8 | 0.15 | 5% |

**再激活加成机制**：

```python
def calculate_reactivation_score(self, base_score, reactivation_count, emotion_intensity):
    """
    再激活加成 = 基础分数 × (1 + 0.2 × 再激活次数) + 0.1
    情感加成 = 0.05 × |情感强度|
    """
    enhanced = base_score * (1.0 + 0.2 * reactivation_count) + 0.1
    emotion_bonus = 0.05 * abs(emotion_intensity)
    return min(enhanced + emotion_bonus, 1.0)
```

**备选模型 - 艾宾浩斯优化版**：

```
T(t) = 1 / (1 + (Δt/T₅₀)^k)
```

### 3. HybridSearch - 混合搜索引擎

结合**向量搜索**和**关键词搜索**的优势：

```python
@dataclass
class HybridSearchOptions:
    query: str
    vector_weight: float = 0.6      # 向量搜索权重
    keyword_weight: float = 0.4     # 关键词搜索权重
    min_score: float = 0.3          # 最低分数阈值
    use_vector: bool = True
    use_keyword: bool = True
```

**搜索流程**：

1. **向量搜索**: 使用嵌入模型将查询向量化，在 Weaviate 中检索相似向量
2. **关键词搜索**: SQLite LIKE 查询进行关键词匹配
3. **结果合并**: 按权重合并两种搜索结果
4. **分数过滤**: 过滤低于阈值的结果

```python
def _merge_results(self, vector_results, keyword_results, vector_weight, keyword_weight):
    merged_dict: Dict[int, SearchResult] = {}
    
    # 合并向量搜索结果
    for r in vector_results:
        merged_dict[r.memory_id] = SearchResult(
            score=r.score * vector_weight,
            source="vector"
        )
    
    # 合并关键词搜索结果
    for r in keyword_results:
        if r.memory_id in merged_dict:
            existing = merged_dict[r.memory_id]
            combined_score = existing.score * (1 - keyword_weight) + r.score * keyword_weight
            existing.score = combined_score
            existing.source = "hybrid"
        else:
            merged_dict[r.memory_id] = SearchResult(
                score=r.score * keyword_weight,
                source="keyword"
            )
    
    return list(merged_dict.values())
```

### 4. MemoryRouter - 记忆路由器

实现**场景感知**的智能记忆检索：

```python
SCENE_CONFIGS = {
    "task": {           # 任务型对话 - 侧重相关性
        "relevance_weight": 0.5,
        "importance_weight": 0.30,
        "time_weight": 0.20,
    },
    "chat": {           # 闲聊/情感对话 - 侧重重要性
        "relevance_weight": 0.35,
        "importance_weight": 0.45,
        "time_weight": 0.20,
    },
    "first_interaction": {  # 首次交互
        "relevance_weight": 0.40,
        "importance_weight": 0.30,
        "time_weight": 0.30,
    },
    "recall": {         # 记忆召回 - 侧重相关性
        "relevance_weight": 0.50,
        "importance_weight": 0.25,
        "time_weight": 0.25,
    },
    "learning": {       # 学习/知识获取
        "relevance_weight": 0.45,
        "importance_weight": 0.35,
        "time_weight": 0.20,
    },
    "problem_solving": {  # 问题解决
        "relevance_weight": 0.55,
        "importance_weight": 0.25,
        "time_weight": 0.20,
    },
    "creative": {       # 创造性对话
        "relevance_weight": 0.30,
        "importance_weight": 0.30,
        "time_weight": 0.40,
    },
}
```

**三维评分模型**：

```
最终分数 = 重要性分数 × 权重₁ + 时间分数 × 权重₂ + 相关性分数 × 权重₃
```

**路由流程**：

```python
async def route(self, query: str, session_id: str, scene_type: str, context: Dict):
    # 1. 场景识别，确定权重
    applied_weights = self._get_weights(scene_type)
    
    # 2. 混合搜索
    search_results = await self._search_memories(query, options)
    
    # 3. 三维评分
    scored_memories = self._score_memories(search_results, query, applied_weights, context)
    
    # 4. 过滤与排序
    filtered = self._apply_filters(scored_memories)
    final_memories = self._apply_scene_adjustment(filtered, scene_type, applied_weights)
    
    # 5. 返回结果
    return RoutingResult(
        memories=final_memories[:self.config.max_memories],
        total_score=total_score,
        source_counts=source_counts,
        applied_weights=applied_weights
    )
```

### 5. VectorStore - 向量存储

提供向量检索能力，支持 **Weaviate** 后端：

```python
class VectorStoreBase:
    async def add_memory_vector(memory_id, content, embedding, metadata)
    async def search_similar(query_embedding, limit, memory_type, min_score)
    async def delete_by_memory_id(memory_id)
    async def get_vector_by_id(memory_id)
    async def check_exists(memory_id)
    async def sync_with_sqlite(sqlite_manager, last_sync_time)
    def get_collection_info()
    def clear_collection()
    def close()
```

**工厂模式创建**：

```python
def create_vector_store(backend: str = "weaviate", **kwargs) -> VectorStoreBase:
    if backend == "weaviate":
        return WeaviateVectorStore(embedded=False, **kwargs)
    elif backend == "weaviate_embedded":
        return WeaviateVectorStore(embedded=True, **kwargs)
```

### 6. DeduplicationEngine - 去重引擎

检测并管理相似记忆：

```python
class DeduplicationEngine:
    def __init__(self, memory_manager, threshold: float = 0.85):
        self.threshold = threshold  # 相似度阈值
        self._similarity_cache: Dict[str, float] = {}
        self._duplicate_groups: Dict[str, DuplicateGroup] = {}
    
    async def check_similarity(memory_id_1, memory_id_2)
    async def find_similar_memories(memory_id, threshold, limit)
    async def detect_duplicates_batch(memory_ids, threshold)
```

**Jaccard 相似度计算**：

```python
def _calculate_text_similarity(self, text1: str, text2: str) -> float:
    set1 = set(text1.lower().split())
    set2 = set(text2.lower().split())
    
    intersection = len(set1 & set2)
    union = len(set1 | set2)
    
    return intersection / union if union > 0 else 0.0
```

**并查集算法检测重复组**：

```python
def _find_connected_components(self, graph: Dict[int, Set[int]]) -> List[Set[int]]:
    visited = set()
    components = []
    
    def dfs(node, component):
        visited.add(node)
        component.add(node)
        for neighbor in graph.get(node, set()):
            if neighbor not in visited:
                dfs(neighbor, component)
    
    for node in graph:
        if node not in visited:
            component = set()
            dfs(node, component)
            components.append(component)
    
    return components
```

### 7. EmbeddingModel - 嵌入模型

支持多种嵌入模型：

| 提供者 | 模型示例 | 维度 |
|-------|---------|------|
| Ollama | nomic-embed-text | 768 |
| SentenceTransformers | paraphrase-multilingual-MiniLM-L12-v2 | 384 |

**工厂模式**：

```python
class EmbeddingFactory:
    _models: dict = {}
    _lock = threading.Lock()
    
    @classmethod
    def create(cls, provider: str = "ollama", **kwargs) -> EmbeddingModel:
        key = f"{provider}:{kwargs.get('model', 'default')}"
        
        with cls._lock:
            if key in cls._models:
                return cls._models[key]
            
            if provider == "ollama":
                model = OllamaEmbedding(**kwargs)
            elif provider == "sentence-transformers":
                model = SentenceTransformersEmbedding(**kwargs)
            
            cls._models[key] = model
            return model
```

## 核心工作流程

### 记忆写入流程

```
用户输入 → MemoryManager.write_memory()
    │
    ├─→ 1. 写入 SQLite (同步)
    │       - 存储元数据
    │       - 记录审计日志
    │
    ├─→ 2. 向量化队列 (异步)
    │       - EmbeddingModel.get_embedding()
    │       - VectorStore.add_memory_vector()
    │
    └─→ 3. 图数据库同步 (可选)
            - 实体提取
            - 关系创建
```

**代码实现**：

```python
def write_memory(self, content, memory_type, importance, tags, metadata, permanent, emotion_score, workspace_id, agent_id):
    # 1. 确保 Agent 表存在
    self._ensure_agent_table(agent_id)
    
    # 2. 写入 SQLite
    cursor.execute(f"INSERT INTO {table_name} (...) VALUES (...)")
    memory_id = cursor.lastrowid
    
    # 3. 记录审计日志
    cursor.execute("INSERT INTO audit_logs (...) VALUES (...)")
    
    # 4. 异步向量化
    self._sync_vector_for_memory(memory_id, content, vector_metadata)
    
    # 5. 图数据库同步 (可选)
    if self._graph_enabled:
        self._sync_to_graph(memory_id, content, tags, metadata)
    
    return memory_id
```

### 记忆检索流程

```
查询请求 → MemoryRouter.route()
    │
    ├─→ 1. 场景识别，确定权重
    │
    ├─→ 2. HybridSearch.search()
    │       ├─→ 向量搜索
    │       └─→ 关键词搜索
    │
    ├─→ 3. 三维评分
    │       - DecayCalculator.calculate_importance_score()
    │       - DecayCalculator.calculate_time_score()
    │       - 相关性分数 (来自搜索)
    │
    ├─→ 4. 过滤与排序
    │       - 硬规则过滤
    │       - 场景调整
    │
    └─→ 5. 返回 RoutingResult
```

### 记忆召回流程

```python
def recall_memory(self, memory_id: int, emotion_intensity: float = 0.0):
    # 1. 获取记忆
    memory = self.get_memory(memory_id)
    
    # 2. 计算旧时间分数
    old_time_score = decay_calculator.calculate_time_score(memory, apply_reactivation=False)
    
    # 3. 计算加成
    reactivation_bonus = 0.1 + 0.2 * reactivation_count
    emotion_bonus = 0.05 * abs(emotion_intensity)
    new_time_score = min(old_time_score + reactivation_bonus + emotion_bonus, 1.0)
    
    # 4. 更新记忆
    cursor.execute("""
        UPDATE memories
        SET reactivation_count = ?, emotion_score = ?, updated_at = ?
        WHERE id = ?
    """, (new_reactivation_count, new_emotion_score, datetime.now(), memory_id))
    
    # 5. 返回更新后的记忆
    return self.get_memory(memory_id)
```

## 关键特性

### 1. 多 Agent 隔离

每个 Agent 拥有独立的记忆表，通过 `agent_id` 区分：

```python
def _get_table_name(self, agent_id: str = "default") -> str:
    if agent_id == "default":
        return "memories"
    safe_agent_id = re.sub(r"[^a-zA-Z0-9_]", "_", agent_id)
    return f"memories_{safe_agent_id}"

def _ensure_agent_table(self, agent_id: str):
    table_name = self._get_table_name(agent_id)
    cursor.execute(f"CREATE TABLE IF NOT EXISTS {table_name} (...)")
    cursor.execute("INSERT OR REPLACE INTO agent_memory_tables (agent_id, table_name) VALUES (?, ?)")
```

### 2. 异步向量化队列

避免阻塞主线程：

```python
class VectorizationQueue:
    def __init__(self, max_workers=2, batch_size=5):
        self.queue = PriorityQueue()
        self.workers = []
        
    def add_task(self, memory_id, content, priority=5):
        task_id = str(uuid.uuid4())
        self.queue.put((priority, task_id, memory_id, content))
        return task_id
    
    def set_callbacks(self, on_complete, on_error):
        self.on_complete = on_complete
        self.on_error = on_error
```

### 3. 连接池管理

自动清理空闲连接，优化性能：

```python
def _get_connection(self):
    thread_id = threading.get_ident()
    
    with self._lock:
        if thread_id in self._connection_pool:
            conn_info = self._connection_pool[thread_id]
            conn = conn_info["connection"]
            conn.execute("SELECT 1")  # 健康检查
            conn_info["last_used"] = time.time()
            conn_info["use_count"] += 1
            return conn
    
    # 创建新连接
    conn = sqlite3.connect(str(self.db_path), timeout=20.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA cache_size=-64000")
    
    self._connection_pool[thread_id] = {
        "connection": conn,
        "last_used": time.time(),
        "use_count": 0
    }
    return conn

def _cleanup_idle_connections(self):
    idle_threshold = time.time() - 300  # 5分钟空闲
    for tid, conn_info in list(self._connection_pool.items()):
        if conn_info["last_used"] < idle_threshold:
            conn_info["connection"].close()
            del self._connection_pool[tid]
```

### 4. 审计日志

所有操作都有记录：

```python
cursor.execute("""
    INSERT INTO audit_logs (operation, memory_id, session_id, operator, details)
    VALUES (?, ?, ?, ?, ?)
""", ("create", memory_id, session_id, "system", json_dumps({...})))
```

### 5. 记忆类型

系统支持三种记忆类型：

| 类型 | 说明 | 衰减特性 |
|------|------|---------|
| **short_term** | 短期记忆 | 快速衰减，用于临时对话 |
| **long_term** | 长期记忆 | 正常衰减，持久化存储 |
| **permanent** | 永久记忆 | 不衰减，重要性固定为 1.0 |

## API 接口

提供 RESTful API：

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/memories` | POST | 写入记忆 |
| `/api/memories/search` | GET | 搜索记忆 |
| `/api/memories/{id}` | GET | 获取单条记忆 |
| `/api/memories/{id}` | PUT | 更新记忆 |
| `/api/memories/{id}` | DELETE | 删除记忆 |
| `/api/memories/hybrid-search` | POST | 混合搜索 |
| `/api/memories/statistics` | GET | 获取统计 |
| `/api/memories/{id}/recall` | POST | 召回记忆 |
| `/api/memories/batch` | POST | 批量操作 |

## 架构示意图

```
┌─────────────────────────────────────────────────────────────────────┐
│                        智能记忆系统架构                               │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────────────────┐ │
│  │ API Layer   │───▶│ MemoryRouter │───▶│ HybridSearch           │ │
│  │ (memory.py) │    │ (路由决策)    │    │ (混合搜索引擎)          │ │
│  └─────────────┘    └─────────────┘    └─────────────────────────┘ │
│         │                  │                      │                │
│         ▼                  ▼                      ▼                │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                    MemoryManager (核心管理器)                 │   │
│  │  ┌───────────┐ ┌──────────────┐ ┌────────────────────────┐  │   │
│  │  │ SQLite DB │ │ VectorStore  │ │ DecayCalculator        │  │   │
│  │  │ (元数据)   │ │ (Weaviate)   │ │ (衰减计算器)            │  │   │
│  │  └───────────┘ └──────────────┘ └────────────────────────┘  │   │
│  └─────────────────────────────────────────────────────────────┘   │
│         │                  │                                        │
│         ▼                  ▼                                        │
│  ┌──────────────┐  ┌──────────────────┐                            │
│  │ Deduplication│  │ EmbeddingModel   │                            │
│  │ (去重引擎)    │  │ (嵌入模型)        │                            │
│  └──────────────┘  └──────────────────┘                            │
└─────────────────────────────────────────────────────────────────────┘
```

## 核心设计亮点

1. **认知科学融合**: 模拟艾宾浩斯遗忘曲线，实现双阶段指数衰减
2. **三维评分模型**: 重要性 + 时间 + 相关性，综合评估记忆价值
3. **场景感知路由**: 根据对话场景动态调整检索策略
4. **混合搜索**: 向量搜索 + 关键词搜索，兼顾语义理解和精确匹配
5. **多 Agent 隔离**: 支持多租户架构，每个 Agent 独立记忆空间
6. **异步向量化**: 非阻塞写入，优化性能
7. **智能去重**: 自动检测并管理相似记忆
8. **再激活机制**: 记忆召回时提升时间分数，模拟人类记忆强化

## 配置说明

### 环境变量

| 变量名 | 默认值 | 说明 |
|-------|-------|------|
| `MEMORY_DB_PATH` | `data/memories.db` | SQLite 数据库路径 |
| `VECTOR_BACKEND` | `weaviate` | 向量存储后端 |
| `WEAVIATE_HOST` | `localhost` | Weaviate 服务地址 |
| `WEAVIATE_PORT` | `8080` | Weaviate HTTP 端口 |
| `WEAVIATE_GRPC_PORT` | `50051` | Weaviate gRPC 端口 |
| `EMBEDDING_PROVIDER` | `ollama` | 嵌入模型提供者 |
| `EMBEDDING_MODEL` | `nomic-embed-text` | 嵌入模型名称 |

### 路由配置

```python
@dataclass
class RoutingConfig:
    importance_weight: float = 0.35
    time_weight: float = 0.25
    relevance_weight: float = 0.4
    hard_rules_enabled: bool = True
    scene_awareness_enabled: bool = True
    max_memories: int = 10
    min_score_threshold: float = 0.3
    high_priority_threshold: float = 0.8
```

## 使用示例

### 初始化记忆管理器

```python
from backend.core.memory.manager import MemoryManager
from backend.core.memory.embedding import EmbeddingFactory
from backend.core.memory.vector_store import create_vector_store

# 创建记忆管理器
memory_manager = MemoryManager(db_path="data/memories.db")

# 创建嵌入模型
embedding_model = EmbeddingFactory.create(
    provider="ollama",
    host="http://localhost:11434",
    model="nomic-embed-text"
)

# 启用向量搜索
memory_manager.enable_vector_search(
    embedding_model=embedding_model,
    vector_backend="weaviate",
    weaviate_host="localhost",
    weaviate_port=8080
)
```

### 写入记忆

```python
memory_id = memory_manager.write_memory(
    content="用户喜欢喝咖啡，特别是拿铁",
    memory_type="long_term",
    importance=4,
    tags=["preference", "coffee"],
    metadata={"source": "chat"},
    permanent=False,
    emotion_score=0.3,
    workspace_id="default",
    agent_id="assistant_001"
)
```

### 搜索记忆

```python
# 关键词搜索
results = memory_manager.search_memories(
    query="咖啡",
    memory_type="long_term",
    tags=["preference"],
    limit=10
)

# 混合搜索
results = await memory_manager.hybrid_search(
    query="用户喜欢什么饮料",
    memory_type="long_term",
    limit=10
)
```

### 记忆路由

```python
from backend.core.memory.router import MemoryRouter, RoutingConfig

router = MemoryRouter(
    memory_manager=memory_manager,
    vector_store=vector_store,
    embedding_model=embedding_model,
    config=RoutingConfig()
)

result = await router.route(
    query="用户喜欢什么",
    session_id="session_001",
    scene_type="chat",
    context={"user_id": "123"}
)

for memory in result.memories:
    print(f"内容: {memory['content']}")
    print(f"分数: {memory['final_score']}")
    print(f"来源: {memory['source']}")
```

### 召回记忆

```python
memory = memory_manager.recall_memory(
    memory_id=123,
    emotion_intensity=0.5
)

print(f"再激活次数: {memory['reactivation_count']}")
print(f"时间分数: {memory['reactivation_details']['new_time_score']}")
```

### 批量操作

```python
# 批量写入
results = memory_manager.batch_write_memories([
    {"content": "记忆1", "type": "long_term", "importance": 3},
    {"content": "记忆2", "type": "long_term", "importance": 4},
])

# 批量更新
results = memory_manager.batch_update_memories([
    {"memory_id": 1, "content": "更新内容1"},
    {"memory_id": 2, "tags": ["new_tag"]},
])

# 批量删除
results = memory_manager.batch_delete_memories(
    memory_ids=[1, 2, 3],
    soft_delete=True
)
```

### 获取统计信息

```python
# 基础统计
stats = memory_manager.get_statistics(workspace_id="default")

# 衰减统计
decay_stats = memory_manager.get_decay_statistics(workspace_id="default")

# 记忆时间线
timeline = memory_manager.get_memory_timeline(workspace_id="default", days=30)
```
