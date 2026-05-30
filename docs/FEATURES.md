# CX-O 功能特性文档

本文档详细介绍 CX-O 项目的所有核心功能特性。

## 目录

- [一、核心智能](#一核心智能)
  - [1.1 智能记忆系统](#11-智能记忆系统)
  - [1.2 知识图谱集成](#12-知识图谱集成)
  - [1.3 多模型路由与 LLM 客户端](#13-多模型路由与-llm-客户端)
  - [1.4 对话上下文管理](#14-对话上下文管理)
  - [1.5 提示词构建与隐藏注入](#15-提示词构建与隐藏注入)
- [二、内容安全与交互控制](#二内容安全与交互控制)
  - [2.1 三档防火墙系统](#21-三档防火墙系统)
  - [2.2 全双工打断系统](#22-全双工打断系统)
  - [2.3 情感与音效解析引擎](#23-情感与音效解析引擎)
- [三、语音能力](#三语音能力)
  - [3.1 语音识别服务 (ASR)](#31-语音识别服务-asr)
  - [3.2 语音合成服务 (TTS)](#32-语音合成服务-tts)
  - [3.3 语音活动检测 (VAD)](#33-语音活动检测-vad)
  - [3.4 语音工作站](#34-语音工作站)
- [四、虚拟形象与直播](#四虚拟形象与直播)
  - [4.1 虚拟形象驱动系统](#41-虚拟形象驱动系统)
  - [4.2 直播舞台与 OBS 分层输出](#42-直播舞台与-obs-分层输出)
- [五、多智能体与扩展](#五多智能体与扩展)
  - [5.1 ACP 多智能体协作协议](#51-acp-多智能体协作协议)
  - [5.2 CXFC 插件联邦协议](#52-cxfc-插件联邦协议)
  - [5.3 插件系统](#53-插件系统)
  - [5.4 工具注册与调用系统](#54-工具注册与调用系统)
- [六、基础设施](#六基础设施)
  - [6.1 WebSocket 实时通信网关](#61-websocket-实时通信网关)
  - [6.2 闹钟/定时提醒系统](#62-闹钟定时提醒系统)
  - [6.3 会话持久化存储](#63-会话持久化存储)

---

# 一、核心智能

## 1.1 智能记忆系统

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

### 核心组件

#### MemoryManager - 记忆管理器

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
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    archived_at TIMESTAMP,
    is_deleted BOOLEAN DEFAULT FALSE,
    source VARCHAR(50),
    workspace_id VARCHAR(100),
    agent_id VARCHAR(100)                -- Agent ID (多租户隔离)
);
```

#### DecayCalculator - 记忆衰减计算器

模拟人类记忆遗忘曲线，采用**双阶段指数衰减模型**：

```
T(t) = α·e^(-λ₁·Δt) + (1-α)·e^(-λ₂·Δt)
```

| 重要性分数 | 衰减类型 | α值 | λ₁值 | λ₂值 | 180天保留率 |
|-----------|---------|-----|------|------|------------|
| ≥0.95 | zero (永久) | - | - | - | 100% |
| 0.85-0.99 | exponential | 0.2 | 0.01 | 0.001 | 95% |
| 0.70-0.84 | exponential | 0.35 | 0.08 | 0.015 | 80% |
| 0.50-0.69 | exponential | 0.6 | 0.25 | 0.04 | 50% |
| 0.30-0.49 | exponential | 0.75 | 0.45 | 0.08 | 25% |
| <0.30 | exponential | 0.9 | 0.8 | 0.15 | 5% |

**再激活加成机制**：再激活加成 = 基础分数 × (1 + 0.2 × 再激活次数) + 0.1，情感加成 = 0.05 × |情感强度|

#### HybridSearch - 混合搜索引擎

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

#### MemoryRouter - 记忆路由器

实现**场景感知**的智能记忆检索，支持 7 种场景配置：

| 场景 | 相关性权重 | 重要性权重 | 时间权重 |
|------|-----------|-----------|---------|
| task (任务型) | 0.50 | 0.30 | 0.20 |
| chat (闲聊/情感) | 0.35 | 0.45 | 0.20 |
| first_interaction (首次交互) | 0.40 | 0.30 | 0.30 |
| recall (记忆召回) | 0.50 | 0.25 | 0.25 |
| learning (学习) | 0.45 | 0.35 | 0.20 |
| problem_solving (问题解决) | 0.55 | 0.25 | 0.20 |
| creative (创造性) | 0.30 | 0.30 | 0.40 |

**三维评分模型**：最终分数 = 重要性分数 × 权重₁ + 时间分数 × 权重₂ + 相关性分数 × 权重₃

#### 其他组件

| 组件 | 说明 |
|------|------|
| **DeduplicationEngine** | 去重引擎，Jaccard 相似度 + 并查集算法检测重复组 |
| **EmbeddingFactory** | 嵌入模型工厂，支持 Ollama 和 SentenceTransformers |
| **VectorizationQueue** | 异步向量化队列，优先级队列 + 工作线程，避免阻塞主线程 |

### 记忆类型

| 类型 | 说明 | 衰减特性 |
|------|------|---------|
| **short_term** | 短期记忆 | 快速衰减，用于临时对话 |
| **long_term** | 长期记忆 | 正常衰减，持久化存储 |
| **permanent** | 永久记忆 | 不衰减，重要性固定为 1.0 |

### API 接口

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/memories` | POST | 写入记忆 |
| `/api/memories/search` | GET | 搜索记忆 |
| `/api/memories/{id}` | GET/PUT/DELETE | 记忆 CRUD |
| `/api/memories/hybrid-search` | POST | 混合搜索 |
| `/api/memories/statistics` | GET | 获取统计 |
| `/api/memories/{id}/recall` | POST | 召回记忆 |
| `/api/memories/batch` | POST | 批量操作 |

### 核心设计亮点

1. **认知科学融合**: 模拟艾宾浩斯遗忘曲线，实现双阶段指数衰减
2. **三维评分模型**: 重要性 + 时间 + 相关性，综合评估记忆价值
3. **场景感知路由**: 根据对话场景动态调整检索策略
4. **混合搜索**: 向量搜索 + 关键词搜索，兼顾语义理解和精确匹配
5. **多 Agent 隔离**: 支持多租户架构，每个 Agent 独立记忆空间
6. **异步向量化**: 非阻塞写入，优化性能
7. **智能去重**: 自动检测并管理相似记忆
8. **再激活机制**: 记忆召回时提升时间分数，模拟人类记忆强化

---

## 1.2 知识图谱集成

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

### 四类知识图谱

| 图谱类型 | 实体类型 | 关系类型 | 用途 |
|---------|---------|---------|------|
| **User Graph** | person, user, contact | knows, friend, family, colleague, enemy | 用户关系网络 |
| **Thing Graph** | object, item, product | owns, part_of, similar_to, located_at, made_of | 事物关系 |
| **Concept Graph** | concept, idea, topic | related_to, subtopic_of, opposite_of, implies | 概念知识 |
| **Event Graph** | event, activity, occurrence | caused, followed_by, concurrent_with, prevents | 事件关系 |

### 图遍历算法

| 算法 | 方法 | 功能 |
|-----|------|------|
| **BFS** | `bfs_traverse()` | 广度优先遍历 |
| **DFS** | `dfs_traverse()` | 深度优先遍历 |
| **Dijkstra** | `shortest_path()` | 最短路径查找 |
| **PageRank** | `pagerank()` | 节点重要性排序 |
| **LPA** | `_lpa_community_detection()` | 标签传播社区发现 |
| **Louvain** | `_louvain_community_detection()` | 模块度优化社区发现 |

### 工具注册机制

系统为 AI 模型注册了 **56 个图工具**（每类图谱 14 个），供主模型、摘要模型和记忆管理 Agent 调用：

```
每类图谱工具:
create_entity → create_relation → query_entities → find_paths
→ search_related_memories → extract_entities → merge_entities
→ get_entity_summary → update_entity → delete_entity
→ update_relation → delete_relation → get_stats → export
```

### 混合查询

结合**图结构**和**语义相似度**的混合查询：

```python
combined_score = (1 - semantic_weight) * structural_score + semantic_weight * semantic_score
```

### API 路由

| 端点 | 方法 | 功能 |
|-----|------|------|
| `/graph/nodes` | POST | 创建节点 |
| `/graph/nodes/{id}` | GET/PUT/DELETE | 节点 CRUD |
| `/graph/edges` | POST | 创建边 |
| `/graph/search/semantic` | POST | 语义搜索 |
| `/graph/search/hybrid` | POST | 混合搜索 |
| `/graph/traverse/bfs` | POST | BFS 遍历 |
| `/graph/traverse/shortest-path` | POST | 最短路径 |

### 核心设计亮点

1. **轻量级架构**: 使用 SQLite 替代 Neo4j，降低部署复杂度
2. **语义增强**: 集成 Weaviate 向量数据库，支持语义搜索
3. **多图谱隔离**: 四类图谱独立管理，支持不同领域的知识建模
4. **混合查询**: 结合图结构和语义相似度，提供更智能的检索能力
5. **丰富的图算法**: 内置 PageRank、社区发现等高级分析能力
6. **AI 工具集成**: 为 LLM 提供 56 个图操作工具，实现知识图谱的智能管理

---

## 1.3 多模型路由与 LLM 客户端

核心代码位于 `server/core/model_router.py` 和 `server/core/llm/`，实现多 LLM 模型的统一管理和路由分发。

### 架构概览

```
server/core/
├── model_router.py     # 模型路由器
└── llm/
    ├── client.py       # LLM 客户端基类 + Ollama/VLLM 实现
    └── tools.py        # 工具调用辅助
```

### 三种模型角色

| 角色 | 用途 | 说明 |
|------|------|------|
| **main** | 主模型 | 负责核心对话和决策 |
| **summary** | 摘要模型 | 负责上下文摘要和实体提取 |
| **memory** | 记忆模型 | 负责记忆管理和向量化 |

### 核心组件

#### ModelRouter - 模型路由器

```python
class ModelRouter:
    async def initialize(self)              # 初始化所有模型客户端
    async def warmup_models(self)           # 预热模型（加载到内存）
    def get_client(self, model_type)        # 获取指定类型的客户端
    async def check_all_status(self)        # 检查所有模型状态
    async def chat(self, model_type, messages, stream)  # 统一对话接口
    async def get_embedding(self, model_type, text)     # 获取文本向量
```

**模型跟随机制**：支持配置模型默认跟随，如 `summary` 跟随 `main`，避免重复加载。

#### LLMClient - 抽象客户端

```python
class LLMClient(ABC):
    async def chat(messages, stream, **kwargs) -> LLMResponse
    async def stream_chat(messages, **kwargs) -> AsyncGenerator
    async def get_embedding(text) -> List[float]

# 实现:
class OllamaClient(LLMClient)    # Ollama 后端
class VLLMClient(LLMClient)      # vLLM 后端
```

#### LLMTools - 工具调用辅助

负责格式化工具定义、解析 LLM 返回的工具调用、执行工具调用循环。

### 核心设计亮点

1. **多角色分离**: 主模型/摘要模型/记忆模型各司其职，优化资源分配
2. **模型预热**: 启动时自动预热模型，减少首次响应延迟
3. **状态检测**: 实时检测模型可用性和延迟
4. **模型跟随**: 支持配置模型默认跟随，灵活复用
5. **多后端支持**: 兼容 Ollama 和 vLLM 两种推理后端

---

## 1.4 对话上下文管理

核心代码位于 `server/core/context/`，负责管理对话会话和消息历史。

### 架构概览

```
server/core/context/
├── manager.py               # 上下文管理器 ContextManager
├── agent_context_manager.py # Agent 上下文管理器（单例）
└── summarizer.py            # 上下文摘要器
```

### 核心组件

#### ContextManager - 上下文管理器

```python
class ContextManager:
    def create_session(workspace_id, title, user_id) -> str   # 创建会话
    def get_session(session_id) -> Dict                       # 获取会话
    def add_message(session_id, role, content, content_type)  # 添加消息
    def get_messages(session_id, limit, offset) -> List[Dict] # 获取消息列表
    def add_mono_context(session_id, content, rounds)         # 添加 Mono 上下文
    def get_mono_context(session_id) -> List[Dict]            # 获取有效 Mono 上下文
    def clear_expired_mono(session_id) -> int                 # 清理过期 Mono 上下文
```

**数据表结构**：

```sql
-- 会话表
CREATE TABLE sessions (
    id VARCHAR(36) PRIMARY KEY,
    workspace_id VARCHAR(100) DEFAULT 'default',
    title VARCHAR(500),
    message_count INTEGER DEFAULT 0,
    summary TEXT,
    is_active BOOLEAN DEFAULT TRUE
);

-- 消息表
CREATE TABLE messages (
    id VARCHAR(36) PRIMARY KEY,
    session_id VARCHAR(36) NOT NULL,
    role VARCHAR(20) NOT NULL,
    content TEXT NOT NULL,
    content_type VARCHAR(20) DEFAULT 'text',
    is_deleted BOOLEAN DEFAULT FALSE
);
```

#### Mono 上下文机制

Mono 是一种**临时性上下文保持机制**，允许信息在指定轮次内保持在对话上下文中：

- 设置 `rounds` 参数控制保持轮次
- 自动过期清理，避免上下文膨胀
- 支持 Agent 通过工具调用注入 Mono 上下文

#### ContextSummarizer - 上下文摘要器

支持两种摘要模式：
- **LLM 摘要**: 调用摘要模型生成高质量摘要
- **规则摘要**: 基于规则的关键信息提取，作为降级方案

### 核心设计亮点

1. **Mono 上下文**: 灵活的临时上下文保持机制，支持按轮次过期
2. **自动过期清理**: 定期清理过期的 Mono 上下文，保持对话精简
3. **多工作空间隔离**: 通过 `workspace_id` 实现工作空间级别的会话隔离
4. **双模式摘要**: LLM 摘要 + 规则摘要，兼顾质量和可用性

---

## 1.5 提示词构建与隐藏注入

核心代码位于 `server/services/prompt_builder.py` 和 `server/services/hidden_prompt.py`。

### PromptBuilder - 提示词构建器

根据上下文和配置构建发送给 LLM 的提示词：

```python
class PromptBuilder:
    def set_system_prompt(prompt)                           # 设置系统提示词
    def build_messages(user_text, context, system_prompt)   # 构建消息列表
    def build_chat_prompt(user_text, context, agent_config) # 构建聊天提示词
```

支持：
- 系统提示词注入
- Agent 性格设定
- 情感/音效标记清理（发送给 LLM 前去除内部标记）

### HiddenPromptManager - 隐藏提示词管理器

管理需要注入到对话上下文中但对用户不可见的系统提示词：

```python
class HiddenPromptManager:
    def register_prompt(name, prompt)                    # 注册隐藏提示词
    def remove_prompt(name)                              # 移除隐藏提示词
    def build_system_prompt_extension() -> str           # 构建扩展内容
    def inject_into_context(context) -> list[dict]       # 注入到上下文中
```

**注入方式**：自动追加到已有的 system 消息末尾，或插入新的 system 消息，对用户完全透明。

### 核心设计亮点

1. **关注点分离**: 提示词构建与业务逻辑解耦
2. **隐藏注入**: 系统级指令对用户不可见，保持对话自然性
3. **标记清理**: 发送给 LLM 前自动去除情感/音效标记，避免干扰推理

---

# 二、内容安全与交互控制

## 2.1 三档防火墙系统

三档防火墙是一个**直播弹幕内容审核与决策系统**，核心代码位于 `backend/services/firewall.py` 和 `gateway/services/firewall.py`，采用**规则过滤 + LLM 智能决策**的混合架构。

### 三档决策模型

| 档位 | 决策类型 | 含义 | 处理方式 |
|------|----------|------|----------|
| **第一档** | `block` | 阻断 | 违规内容，直接拦截，不进入上下文 |
| **第二档** | `passive` | 放行 | 正常弹幕，通过但不主动回复 |
| **第三档** | `reply` | 回复 | 优质弹幕，值得互动回复 |

### 决策流程

```
弹幕数据 → 黑名单检查 → LLM 智能决策 → 返回决策结果
              ↓              ↓
           快速拦截      深度分析
```

**Step 1 - 黑名单快速过滤**：优先级最高，命中黑名单用户直接返回 block，置信度 1.0。

**Step 2 - LLM 智能决策**：构建决策 Prompt，调用 LLM 进行内容分析，解析 JSON 格式返回结果。

### V3 增强配置 - ASR 打断

```yaml
interrupt:
  enabled: true
  mode: "main_llm"  # 模式: main_llm | independent_llm

  main_llm:
    enabled: true
    prompt: |
      输出 "##[interrupt]##" 表示需要打断并回复用户。
      输出 "##[no_reply]##" 表示不需要回复。

  independent_llm:
    enabled: false
    model: "qwen2.5:1.5b"
    timeout_ms: 5000

  rules:
    auto_reply_on_interrupt: true
    priority_users:
      - guard_level: 3  # 舰艇总督
      - is_admin: true  # 房管
```

### 容错机制

| 场景 | 处理方式 |
|------|----------|
| LLM 不可用 | 默认放行 (`passive`)，避免误伤 |
| JSON 解析失败 | 记录警告，返回默认决策 |
| 异常捕获 | 记录错误日志，保证服务稳定 |

### 核心设计亮点

1. **双层防护**: 规则过滤（黑名单）+ 智能决策（LLM），兼顾效率与准确性
2. **三档分级**: 精细化处理不同类型的弹幕，避免一刀切
3. **上下文感知**: 结合会话历史进行决策，提升判断准确性
4. **容错优先**: LLM 不可用时默认放行，避免误伤正常用户
5. **V3 增强**: 支持 ASR 打断功能，两种模式灵活切换

---

## 2.2 全双工打断系统

核心代码位于 `server/services/interrupt_manager.py`、`asr_interrupt.py` 和 `agent_interrupt_user.py`，实现双向打断能力。

### 两种打断方向

| 打断方向 | 模块 | 说明 |
|---------|------|------|
| **用户打断 Agent** | `ASRInterruptModule` | 用户说话时打断 Agent 正在进行的 TTS 播放（伪全双工） |
| **Agent 打断用户** | `AgentInterruptUser` | Agent 在用户说话过程中判断是否插话（双向全双工） |

### 核心组件

```python
class InterruptManager:
    _instance = None  # 单例模式

    def set_asr_interrupt(asr_interrupt)      # 设置 ASR 打断模块
    def set_agent_interrupt(agent_interrupt)   # 设置 Agent 打断模块
    async def handle_interrupt(source, text)   # 统一打断处理
```

**ASR 打断流程**：
1. VAD 检测到用户开始说话
2. ASR 识别语音内容
3. LLM 判断是否需要打断当前回复
4. 若需打断，停止 TTS 播放并触发新回复

**Agent 打断流程**：
1. 用户正在说话
2. Agent 通过 LLM 判断是否需要插话
3. 支持冷却时间和最小语音时长限制
4. 避免频繁打断影响体验

### 核心设计亮点

1. **双向全双工**: 支持用户打断 Agent 和 Agent 打断用户两个方向
2. **LLM 智能判断**: 非简单规则判断，由 LLM 根据上下文决定是否打断
3. **冷却机制**: 防止频繁打断，保障交互体验
4. **统一管理**: InterruptManager 统一管理两种打断方向

---

## 2.3 情感与音效解析引擎

核心代码位于 `server/services/emotion_parser.py` 和 `server/services/effect_parser.py`。

### EmotionParser - 情感解析器

解析文本中的情感标记 `[emotion:name]`，支持 **15 种情感类型**：

| 情感 | 标记 | 情感 | 标记 |
|------|------|------|------|
| 开心 | `[emotion:happy]` | 悲伤 | `[emotion:sad]` |
| 愤怒 | `[emotion:angry]` | 惊讶 | `[emotion:surprised]` |
| 恐惧 | `[emotion:fear]` | 厌恶 | `[emotion:disgust]` |
| 中性 | `[emotion:neutral]` | 兴奋 | `[emotion:excited]` |
| 平静 | `[emotion:calm]` | 低语 | `[emotion:whisper]` |
| 呼喊 | `[emotion:shout]` | 大笑 | `[emotion:laugh]` |
| 哭泣 | `[emotion:cry]` | 叹气 | `[emotion:sigh]` |
| 咯笑 | `[emotion:giggle]` | | |

```python
def extract_emotions_with_text(text: str) -> list[dict]:
    # 将 "你好[emotion:happy]今天天气真好" 解析为:
    # [{"type": "text", "content": "你好"}, {"type": "emotion", "emotion": "happy"}, ...]
```

### EffectParser - 音效解析器

解析文本中的音效标记 `[effect:name]`，加载音效文件（wav/mp3/ogg/flac），将文本分割为文字段落和音效段落的混合序列。

### 前端标记适配器

`FrontendMarker` 和 `MarkerAdapter` 将内部情感/音效/动作标记转换为前端可识别的格式，提供情感强度映射和音效类型映射，驱动虚拟形象表情和 TTS 情感语音。

### 核心设计亮点

1. **统一标记语法**: `[emotion:name]` 和 `[effect:name]` 简洁直观
2. **15 种情感**: 覆盖常见情感表达，支持细粒度控制
3. **多端联动**: 情感标记同时驱动 TTS 语音情感和虚拟形象表情
4. **可扩展**: 支持自定义情感和音效类型

---

# 三、语音能力

## 3.1 语音识别服务 (ASR)

核心代码位于 `server/services/asr_service.py` 和 `server/services/sensevoice_streaming_client.py`。

### 双模式架构

| 模式 | 说明 | 适用场景 |
|------|------|---------|
| **embedded** | 直接加载 SenseVoice 模型推理 | 本地部署，低延迟 |
| **remote** | HTTP 调用远程 ASR 服务 | 分布式部署，GPU 集群 |

```python
class ASRService:
    def __init__(self, mode="remote", model_dir="", device="cuda", remote_url="http://127.0.0.1:8001")

    async def initialize(self)  # 初始化模型或连接
    async def transcribe(audio_data) -> str  # 识别音频
```

**自动降级**：embedded 模式加载失败时，自动降级为 remote 模式。

### SenseVoiceStreamingClient - 流式 ASR

支持增量识别的流式 ASR 客户端，适用于实时对话场景。

### 核心设计亮点

1. **双模式 + 自动降级**: embedded 失败自动切换 remote，保障可用性
2. **流式识别**: 支持增量 ASR，适配实时对话
3. **统一接口**: 上层代码无需关心底层模式

---

## 3.2 语音合成服务 (TTS)

核心代码位于 `server/services/tts_service.py`。

### 双模式架构

| 模式 | 说明 | 适用场景 |
|------|------|---------|
| **embedded** | 直接调用 F5-TTS 模型 | 本地部署 |
| **remote** | HTTP 调用远程 TTS 服务 | 分布式部署 |

### 核心能力

```python
class TTSService:
    def __init__(self, mode, model_dir, remote_url, ref_audio_path,
                 emotion_voices, effects_dir, voice_refs_dir,
                 use_triton, ...)
```

| 能力 | 说明 |
|------|------|
| **情感语音切换** | 根据情感标记自动切换参考音频 |
| **音效插入** | 在文本中插入音效（如 `[effect:bell]`） |
| **流式合成** | 按句分割，流式返回音频数据 |
| **Triton 推理加速** | 支持 Triton Inference Server 加速推理 |
| **按句分割** | 自动按标点分割长文本，逐句合成 |

### 核心设计亮点

1. **情感语音**: 根据情感标记自动选择对应参考音频
2. **音效混合**: 文本中可嵌入音效标记，TTS 自动插入音效
3. **流式输出**: 按句分割流式合成，降低首字延迟
4. **Triton 加速**: 支持 GPU 推理加速

---

## 3.3 语音活动检测 (VAD)

核心代码位于 `server/services/vad_processor.py`。

### 三种检测模式

| 模式 | 说明 | 特点 |
|------|------|------|
| **Energy** | 能量检测 | 最简单，基于音量阈值 |
| **WebRTC VAD** | WebRTC 语音检测 | 轻量高效，默认模式 |
| **Silero VAD** | Silero 神经网络检测 | 最准确，需 PyTorch |

```python
class VADProcessor:
    _instance = None  # 单例模式

    def set_config(config)              # 配置检测模式和参数
    def process_frame(audio_data)       # 处理音频帧
    def set_callbacks(on_start, on_end) # 设置语音开始/结束回调
```

**自动降级**：WebRTC/Silero 不可用时自动降级为 Energy 模式。

### 核心设计亮点

1. **三模式可选**: 从简单到精确，灵活选择
2. **自动降级**: 高级模式不可用时自动降级
3. **回调机制**: 语音开始/结束事件回调，驱动打断和口型同步

---

## 3.4 语音工作站

CX-O-VoiceWorkStation 是一个独立的语音工作站服务（端口 8200），提供完整的语音克隆工作流。

### 架构概览

```
CX-O-VoiceWorkStation/workstation/
├── main.py              # FastAPI 应用入口
├── config.py            # 全局配置
├── api/
│   ├── ref_audio.py     # 参考音频 API
│   ├── f5tts_finetune.py # F5-TTS 微调 API
│   ├── sovits_svc.py    # So-VITS-SVC API
│   ├── voxcpm.py        # VoxCPM API
│   └── workflow.py      # 工作流 API
├── services/
│   ├── cosyvoice_client.py       # CosyVoice 客户端
│   ├── index_tts_client.py       # IndexTTS 2 客户端
│   ├── index_tts_manager.py      # IndexTTS 服务管理器
│   ├── voxcpm_client.py          # VoxCPM 客户端
│   ├── f5tts_finetune.py         # F5-TTS 微调服务
│   ├── sovits_svc_trainer.py     # So-VITS-SVC 训练服务
│   ├── sovits_svc_infer.py       # So-VITS-SVC 推理服务
│   └── emotion_ref_generator.py  # 情感参考音频生成器
└── tools/
    └── generate_emotion_refs.py  # CLI 工具
```

### 五步工作流

```
① 参考音频生成 (VoxCPM)
    ↓
② 情感参考音频生成 (CosyVoice/IndexTTS)
    ↓
③ 训练数据准备 (So-VITS-SVC 预处理)
    ↓
④ 模型训练 (So-VITS-SVC)
    ↓
⑤ 推理 (So-VITS-SVC 语音转换)
```

### 多引擎支持

| 引擎 | 模式 | 说明 |
|------|------|------|
| **VoxCPM** | CLI 子进程 | 三种模式：Voice Design / Controllable Clone / Ultimate Clone |
| **CosyVoice** | HTTP API | 8 种情感 + 56 种过渡 = 64 个参考音频，Instruct2 模式 |
| **IndexTTS 2** | HTTP API | 8 种情感 × 5 级强度 = 40 组合，按需启停 |
| **F5-TTS** | CLI 子进程 | 微调训练，支持自定义训练参数 |
| **So-VITS-SVC** | CLI 子进程 | 完整流水线：预处理 → 训练 → 推理，支持变调和聚类模型 |

### IndexTTS 服务按需启停

```python
class IndexTTSManager:
    _instance = None  # 单例模式

    async def start()          # 按需启动服务进程
    async def stop()           # 停止服务
    async def ensure_running() # 确保运行中
    def reset_auto_stop_timer() # 重置自动停止计时器
```

空闲超时（默认 300s）后自动停止服务，节省 GPU 资源。

### API 端点

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/ref-audio/pregenerate` | POST | 预生成 64 个参考音频 |
| `/api/f5tts-finetune/train` | POST | 启动 F5-TTS 微调 |
| `/api/sovits-svc/preprocess` | POST | So-VITS-SVC 数据预处理 |
| `/api/sovits-svc/train` | POST | 启动 So-VITS-SVC 训练 |
| `/api/sovits-svc/infer` | POST | 执行语音转换推理 |
| `/api/voxcpm/generate` | POST | VoxCPM 音频生成 |
| `/api/workflow/status` | GET | 获取工作流状态 |
| `/api/workflow/step/{id}/execute` | POST | 执行指定步骤 |

### 核心设计亮点

1. **完整工作流**: 从参考音频到最终推理的端到端流水线
2. **多引擎互补**: VoxCPM/CosyVoice/IndexTTS/F5-TTS/So-VITS-SVC 各有专长
3. **按需启停**: IndexTTS 空闲自动关闭，节省 GPU 资源
4. **情感参考系统**: 8 情感 + 56 过渡 = 64 参考音频，覆盖丰富情感表达
5. **全局单例**: 关键服务均采用单例模式，统一管理

---

# 四、虚拟形象与直播

## 4.1 虚拟形象驱动系统

前端核心代码位于 `CX-O-Frontend/src/components/Avatar/`、`Live2D/` 和 `VRM/`，实现统一虚拟形象驱动系统，同时支持 **Live2D** 和 **VRM** 两种模型格式。

### 架构概览

```
CX-O-Frontend/src/components/
├── Avatar/
│   ├── AvatarDriver.ts       # 驱动抽象层 (IAvatarDriver 接口)
│   ├── AvatarManager.tsx     # 虚拟形象管理器 (全屏 Modal)
│   ├── AvatarPanel.tsx       # 聊天页面虚拟形象面板
│   ├── AvatarUploader.tsx    # 虚拟形象上传器
│   └── avatarManifest.ts     # Avatar 声明系统
├── Live2D/
│   ├── Live2DViewer.tsx      # Live2D 模型查看器
│   ├── Live2DPanel.tsx       # Live2D 侧面板
│   ├── Live2DStage.tsx       # Live2D 舞台 (声明式渲染)
│   ├── live2dEngine.ts       # Live2D 渲染引擎 (PIXI.js)
│   ├── Live2DLipSync.ts      # 口型同步
│   ├── Live2DExpression.ts   # 表情控制
│   ├── Live2DMotion.ts       # 动作触发
│   └── AudioAnalyzer.ts      # 音频分析器
└── VRM/
    ├── VRMViewer.tsx          # VRM 3D 模型查看器
    ├── VRMPanel.tsx           # VRM 侧面板
    ├── VRMEngine.ts           # VRM 渲染引擎 (Three.js)
    ├── VRMLipSync.ts          # 口型同步
    ├── VRMExpression.ts       # 表情控制
    ├── VRMAnimation.ts        # 动画系统
    ├── VRMMotionTrigger.ts    # 动作触发器
    ├── VRMTweakPanel.tsx      # 微调面板
    ├── AudioLipSync.ts        # 音频口型同步
    └── VowelAnalyzer.ts       # 元音分析器
```

### IAvatarDriver - 驱动抽象层

```typescript
interface IAvatarDriver {
    expressionMix(emotion: EmotionType, intensity: number): void
    parameterOverrides(params: Record<string, number>): void
    mouthOpen(value: number): void
    transform(transform: StageTransform): void
    watermark(visible: boolean): void
}

// 工厂函数
function createAvatarDriver(avatarType: 'live2d' | 'vrm', ...): IAvatarDriver
```

通过 `IAvatarDriver` 接口抽象，实现模型无关的驱动层，上层代码无需关心底层是 Live2D 还是 VRM。

### AvatarManifest - 声明系统

定义类型：`AvatarManifest`、`AvatarExpression`、`ExpressionLayer`、`ParameterOverride`、`ExpressionBinding` 等。

- 内置多个 Live2D 模型声明（yumi, ellen, bingtang, strawberryBunny 等）
- 自动发现表情和参数控制
- VRM BlendShape 预设映射
- VRM Humanoid 骨骼控制
- `resolveAvatarManifest()` 异步丰富声明 + 缓存机制

### 核心能力对比

| 能力 | Live2D | VRM |
|------|--------|-----|
| 渲染引擎 | PIXI.js + pixi-live2d-display | Three.js + @pixiv/three-vrm |
| 口型同步 | 元音权重平滑插值 → CoreModel 参数 | 元音权重 → BlendShape (Aa/Ih/Ou/Ee/Oh) |
| 表情控制 | EmotionType → 表情计时 + 权重过渡 | LLM_EMOTION_MAP → BlendShape 预设 |
| 动作触发 | 情绪动作映射 + 说话点头 | 预设动作 + 骨骼动画 |
| 音频分析 | Web Audio API AnalyserNode | 同左 + VowelAnalyzer 元音分析 |
| 模型格式 | Live2D Cubism 4 (.model.json/.zip) | VRM (.vrm) |

### 核心设计亮点

1. **统一驱动接口**: IAvatarDriver 抽象层，模型无关
2. **声明式管理**: AvatarManifest 声明系统，自动发现和配置
3. **双引擎支持**: Live2D 2D 模型 + VRM 3D 模型，灵活切换
4. **实时口型同步**: 音频分析驱动口型，支持元音权重平滑插值
5. **表情混合**: 多层表情叠加，平滑权重过渡
6. **鼠标视线追踪**: VRM 模型支持鼠标位置追踪

---

## 4.2 直播舞台与 OBS 分层输出

### LiveStage - 直播舞台

核心代码位于 `CX-O-Frontend/src/components/Live/LiveStage.tsx`，整合虚拟形象渲染、弹幕叠加、字幕显示：

```
┌──────────────────────────────────────────────┐
│               LiveStage (55%:45%)             │
│  ┌────────────────────┬───────────────────┐  │
│  │   虚拟形象区域      │   弹幕/字幕区域    │  │
│  │  (Live2D/VRM)      │  (DanmakuOverlay) │  │
│  │   + 表情驱动        │  (SubtitleDisplay)│  │
│  │   + 口型同步        │                   │  │
│  └────────────────────┴───────────────────┘  │
│              [拆分模式] [音频控制]              │
└──────────────────────────────────────────────┘
```

### DanmakuOverlay - 弹幕覆盖层

- CSS 动画弹幕（滚动/顶部/底部三种类型）
- 轨道分配算法
- 可配置速度/字号/透明度/位置

### SubtitleDisplay - 字幕显示

- 打字机效果（requestAnimationFrame）
- 可配置位置/字号/颜色/背景/速度
- 自动清除延迟，最大行数限制

### OBS 分层输出

为 OBS 提供分层浏览器源输出，将直播画面拆分为独立透明背景层：

| 层 | 组件 | 分辨率 | 说明 |
|----|------|--------|------|
| 虚拟形象层 | `AvatarSource.tsx` | 1920×1080 | 透明背景，Live2D/VRM 模型 |
| 弹幕层 | `DanmakuSource.tsx` | 1920×1080 | 透明背景，弹幕叠加 |
| 字幕层 | `SubtitleSource.tsx` | 1920×1080 | 透明背景，AI 回复字幕 |
| 音频控制层 | `AudioPanelOBS.tsx` | 自适应 | 透明背景，音频控制面板 |

### AudioPanel - 音频控制面板

- 麦克风输入（设备选择/增益/音量电平）
- 音频输出（TTS/输出音量）
- AEC 回声消除（自动/浏览器/AudioWorklet/手动）
- WebSocket TTS 同步播放
- 实时音量监控

### 核心设计亮点

1. **OBS 分层**: 虚拟形象/弹幕/字幕/音频独立透明层，灵活叠加
2. **弹幕轨道分配**: 智能轨道分配算法，避免弹幕重叠
3. **打字机字幕**: 流式 AI 回复以打字机效果逐字显示
4. **AEC 回声消除**: 多种回声消除模式，适配不同场景

---

# 五、多智能体与扩展

## 5.1 ACP 多智能体协作协议

核心代码位于 `server/core/acp/`，实现多智能体之间的通信协议。

### 架构概览

```
server/core/acp/
├── manager.py    # ACP 管理器
├── discover.py   # 局域网自动发现
└── group.py      # 群组管理
```

### 核心组件

#### ACPManager - Agent 通信管理器

```python
class ACPManager:
    # Agent 管理
    async def register_agent(agent: ACPAgentInfo)      # 注册 Agent
    async def update_agent_status(agent_id, status)    # 更新状态
    async def list_agents(online_only) -> List[Dict]   # 列出 Agent

    # 连接管理
    async def create_connection(connection)            # 创建连接
    async def list_connections(local_only) -> List[Dict]

    # 群组管理
    async def create_group(group: ACPGroupInfo)        # 创建群组
    async def add_group_member(group_id, member)       # 添加成员
    async def remove_group_member(group_id, agent_id)  # 移除成员

    # 消息管理
    async def send_message(message: ACPMessageInfo)    # 发送消息
    async def get_messages(target_id, limit) -> List[Dict]
```

#### ACPLanDiscovery - 局域网自动发现

基于 **UDP 广播**的局域网自动发现服务，支持：
- 自动广播本机 Agent 信息
- 发现局域网内其他 Agent
- 可配置广播端口、发现端口、广播地址和间隔

#### 数据模型

| 数据类 | 说明 |
|--------|------|
| `ACPAgentInfo` | Agent 信息（ID、名称、能力、状态） |
| `ACPConnectionInfo` | 连接信息（本地/远程 Agent、消息统计） |
| `ACPGroupInfo` | 群组信息（成员列表、最大成员数） |
| `ACPMessageInfo` | 消息信息（类型、发送方、接收方、内容） |

**数据持久化**：使用 YAML 文件存储 agents、connections、groups 数据。

### 核心设计亮点

1. **局域网自动发现**: UDP 广播自动发现局域网内 Agent
2. **能力声明**: Agent 可声明自身 capabilities，支持能力匹配
3. **群组通信**: 支持创建群组、群组广播消息
4. **YAML 持久化**: 轻量级数据持久化，便于查看和编辑

---

## 5.2 CXFC 插件联邦协议

核心代码位于 `server/core/cxfc/`，实现插件联邦协议，支持外部插件的自动发现、注册和技能匹配。

### 架构概览

```
server/core/cxfc/
├── manager.py        # CXFC 管理器
├── discovery.py      # 插件联邦局域网发现
├── skill_registry.py # 技能注册表
├── models.py         # 数据模型
└── storage.py        # SQLite 存储
```

### 核心组件

#### CXFCManager - 插件联邦管理器

```python
class CXFCManager:
    async def start()                              # 启动管理器
    async def _check_heartbeats_loop()             # 心跳检测循环
    async def _register_plugin_tools_and_skills()  # 注册插件工具和技能
    async def _fetch_tools(host, port) -> List[Dict]   # 获取插件工具列表
    async def _fetch_skills(host, port) -> List[Dict]  # 获取插件技能列表
```

**插件生命周期**：
1. 插件启动，暴露 HTTP API（`/health`、`/tools`、`/skills`）
2. CXFCManager 发现插件，检查存活状态
3. 获取工具和技能列表，注册到 ToolRegistry 和 SkillRegistry
4. 心跳检测，断线自动标记为 DISCONNECTED

#### SkillRegistry - 技能注册表

支持两种技能触发方式：
- **关键词匹配**: 用户消息包含特定关键词时触发
- **事件触发**: 系统事件（如新消息、新记忆）发生时触发

#### 数据模型

| 数据类 | 说明 |
|--------|------|
| `CXFCPluginInfo` | 插件信息（ID、名称、状态、工具、技能） |
| `SkillDefinition` | 技能定义（名称、触发关键词、触发事件、自动注入） |
| `PluginStatus` | 插件状态枚举（CONNECTED/DISCONNECTED/ERROR） |

### 核心设计亮点

1. **联邦协议**: 统一的插件接入协议，标准化工具和技能声明
2. **心跳检测**: 自动检测插件存活状态，断线自动标记
3. **技能匹配**: 关键词 + 事件双重触发机制
4. **工具同步**: 插件工具自动注册到 ToolRegistry，LLM 可直接调用

---

## 5.3 插件系统

核心代码位于 `server/core/plugins/`，提供完整的插件生命周期管理。

### 架构概览

```
server/core/plugins/
├── manager.py   # 插件管理器
├── context.py   # 插件上下文（系统 API 注入）
└── models.py    # 插件数据模型
```

### 核心组件

#### PluginManager - 插件管理器

```python
class PluginManager:
    def set_system_apis(memory_manager, context_manager, llm_client,
                        tool_registry, ws_manager)  # 注入系统 API
    def discover_plugins()         # 发现插件
    def load_plugin(plugin_id)     # 加载插件
    def enable_plugin(plugin_id)   # 启用插件
    def disable_plugin(plugin_id)  # 禁用插件
```

#### PluginContext - 插件上下文

为插件注入系统 API，插件可访问：

| API | 说明 |
|-----|------|
| `memory_manager` | 记忆管理器，读写搜索记忆 |
| `context_manager` | 上下文管理器，管理对话历史 |
| `llm_client` | LLM 客户端，调用大模型 |
| `tool_registry` | 工具注册表，注册自定义工具 |
| `ws_manager` | WebSocket 管理器，实时通信 |

#### 钩子(Hook)系统

| 钩子类型 | 触发时机 |
|---------|---------|
| `on_message` | 收到新消息 |
| `on_response` | 生成回复 |
| `on_memory_write` | 写入记忆 |
| `on_tool_call` | 调用工具 |
| `on_startup` | 插件启动 |
| `on_shutdown` | 插件关闭 |

### 核心设计亮点

1. **系统 API 注入**: 插件可访问记忆、上下文、LLM、工具、WebSocket 等核心能力
2. **钩子系统**: 6 种钩子类型，覆盖消息、回复、记忆、工具等关键事件
3. **异步任务追踪**: 自动追踪插件的异步任务，防止资源泄漏
4. **生命周期管理**: 完整的发现 → 加载 → 启用 → 禁用 → 卸载流程

---

## 5.4 工具注册与调用系统

核心代码位于 `server/core/tools/`，提供统一的工具注册、发现和调用机制。

### 架构概览

```
server/core/tools/
├── registry.py        # 工具注册表 (单例)
├── mcp.py             # MCP 协议管理器
├── builtin.py         # 内置工具
├── master_tools.py    # 主模型工具
├── assistant_tools.py # 助手工具
├── summary_tools.py   # 摘要模型工具
├── memory_tools.py    # 记忆管理工具
└── graph_tools.py     # 图数据库工具
```

### ToolRegistry - 工具注册表

```python
class ToolRegistry:
    _instance = None  # 单例模式

    def register(name, description, parameters, function, ...)  # 注册工具
    def get_tool(name) -> Tool                                   # 获取工具
    def list_tools(enabled_only, include_builtin) -> List[Tool]  # 列出工具
    def list_openai_functions(category) -> List[Dict]            # OpenAI 格式
    async def call_tool_async(name, arguments) -> Dict           # 异步调用
    def enable_tool(name) / disable_tool(name)                   # 启用/禁用
    def get_tool_stats() -> Dict                                 # 统计信息
```

### 工具分类

| 类别 | 工具示例 | 说明 |
|------|---------|------|
| **内置工具** | calculator, datetime, random, json_format | 基础能力 |
| **主模型工具** | write_long_term_memory, set_alarm, mono, call_assistant | 核心决策工具 |
| **摘要工具** | summarize_content, save_summary_memory | 上下文摘要 |
| **助手工具** | search_memories, delete_memory, merge_memories, export_memories | 记忆管理 |
| **图数据库工具** | 56 个图操作工具（四类图谱 × 14） | 知识图谱操作 |
| **MCP 工具** | 外部 MCP 服务器提供的工具 | 协议扩展 |
| **CXFC 工具** | 外部 CXFC 插件提供的工具 | 插件扩展 |

### MCPManager - MCP 协议管理器

支持连接外部 MCP (Model Context Protocol) 服务器，自动发现和注册 MCP 工具：

```python
class MCPManager:
    async def connect_server(name, config)   # 连接 MCP 服务器
    async def list_tools() -> List[Dict]     # 获取工具列表
    async def call_tool(name, arguments)     # 调用 MCP 工具
```

### 核心设计亮点

1. **统一注册表**: 所有工具（内置/MCP/CXFC/自定义）统一管理
2. **OpenAI 格式兼容**: 工具定义自动转换为 OpenAI Function Calling 格式
3. **按角色分类**: 不同模型角色使用不同工具集，精确控制
4. **MCP 协议支持**: 标准化外部工具接入
5. **调用统计**: 记录每个工具的调用次数和最后调用时间

---

# 六、基础设施

## 6.1 WebSocket 实时通信网关

核心代码位于 `server/core/websocket/manager.py` 和 `handlers.py`，是前后端实时通信的核心基础设施。

### 核心组件

#### WebSocketManager - 连接管理器

```python
class WebSocketManager:
    async def connect(websocket, client_id, metadata) -> WebSocketConnection
    async def disconnect(client_id)
    async def send_to_client(client_id, data)
    async def broadcast(data, channel)
    async def subscribe(client_id, channel)
    async def unsubscribe(client_id, channel)
```

#### WebSocketConnection - 连接封装

```python
class WebSocketConnection:
    websocket: WebSocket
    client_id: str
    subscriptions: Set[str]  # 订阅的频道

    async def send(data)
    async def receive() -> Dict
    def subscribe(channel)
    def unsubscribe(channel)
```

### 支持的通信模式

| 模式 | 说明 |
|------|------|
| **点对点** | 发送消息给指定客户端 |
| **广播** | 向所有连接广播消息 |
| **频道订阅** | 客户端订阅频道，接收频道消息 |
| **分组消息** | 按分组发送消息 |

### 核心设计亮点

1. **频道订阅/发布**: 灵活的频道机制，支持细粒度消息分发
2. **离线回调**: 客户端断线时触发回调，便于清理资源
3. **统计信息**: 记录 TTS/ASR/LLM 调用计数
4. **Action Handler**: 可注册消息动作处理器，扩展通信协议

---

## 6.2 闹钟/定时提醒系统

核心代码位于 `server/core/alarm/manager.py`，为 Agent 提供闹钟和定时提醒功能。

### 核心组件

```python
class AlarmManager:
    def create_alarm(agent_id, seconds, message) -> str  # 创建闹钟
    def get_alarm(alarm_id) -> Dict                      # 获取闹钟
    def get_alarms_by_agent(agent_id) -> List[Dict]      # 获取 Agent 闹钟
    def cancel_alarm(alarm_id) -> bool                   # 取消闹钟
    def restore_pending_alarms()                         # 恢复待触发闹钟
    def shutdown()                                       # 关闭管理器
```

### Alarm 数据模型

```python
@dataclass
class Alarm:
    id: str
    agent_id: str
    message: str
    trigger_time: datetime
    created_at: datetime
    status: str = "pending"          # pending / triggered / cancelled
    triggered_at: Optional[datetime] = None
```

### 实现机制

- **SQLite 持久化**: 闹钟数据存储在 SQLite 数据库，重启不丢失
- **threading.Timer**: 基于线程定时器实现精确触发
- **回调机制**: 闹钟触发时调用注册的回调函数
- **自动恢复**: 启动时自动恢复所有待触发闹钟，过期闹钟立即触发

### 核心设计亮点

1. **持久化存储**: SQLite 存储，重启后自动恢复
2. **精确触发**: 线程定时器精确触发回调
3. **自动恢复**: 启动时恢复待触发闹钟，过期闹钟立即触发
4. **安全关闭**: shutdown 时取消所有定时器，防止回调异常

---

## 6.3 会话持久化存储

核心代码位于 `server/core/session/`，提供持久化会话存储。

### 架构概览

```
server/core/session/
├── store.py      # 会话存储
├── models.py     # 数据模型
└── cleanup.py    # 自动清理
```

### 核心组件

#### SessionStore - 会话存储

```python
class SessionStore:
    def create_session(workspace_id, title) -> str      # 创建会话
    def get_session(session_id) -> Optional[Session]    # 获取会话
    def get_sessions(workspace_id, limit) -> List[Session]
    def update_session(session_id, **kwargs) -> bool
    def delete_session(session_id) -> bool
    def add_message(session_id, message) -> str         # 添加消息
    def get_messages(session_id, limit, offset) -> List[SessionMessage]
    def get_statistics(workspace_id) -> SessionStats
```

### 数据模型

| 模型 | 说明 |
|------|------|
| `Session` | 会话（ID、工作区、标题、消息数、摘要、活跃状态） |
| `SessionMessage` | 消息（ID、会话ID、角色、内容、内容类型、Token数） |
| `SessionStats` | 统计（总会话数、活跃会话数、总消息数、平均消息数） |

### 自动清理

`cleanup.py` 提供会话过期和自动清理功能，支持配置过期时间和清理间隔。

### 核心设计亮点

1. **SQLite 持久化**: 会话和消息持久化存储
2. **多工作空间隔离**: 通过 `workspace_id` 实现工作空间级别隔离
3. **自动清理**: 过期会话自动清理，避免数据膨胀
4. **统计信息**: 提供会话和消息的统计查询
