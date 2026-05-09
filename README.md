# CX-O&#x20;

CX-O 是一个基于单体应用架构的智能语音对话系统，集成语音识别 (ASR)、大语言模型 (LLM) 和语音合成 (TTS) 能力，支持双向全双工语音交互。

## 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                      CX-O Frontend                              │
│                   (React + TypeScript)                          │
│                      http://127.0.0.1:5173                       │
└──────────────────────────┬──────────────────────────────────────┘
                           │ WebSocket / HTTP
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                   CX-O Server (8100)                           │
│              单体应用，集成所有功能                               │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │  Gateway Layer: WebSocket、HTTP REST API                 │  │
│  ├─────────────────────────────────────────────────────────┤  │
│  │  Handlers Layer: 聊天、记忆、音频、工具、ACP、MCP         │  │
│  ├─────────────────────────────────────────────────────────┤  │
│  │  Services Layer: ASR、TTS、VAD、防火墙、打断管理          │  │
│  ├─────────────────────────────────────────────────────────┤  │
│  │  Core Layer: LLM、记忆、上下文、工具、ACP、图谱           │  │
│  └─────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

## 功能特性

### 核心功能

- **语音对话**：端到端语音交互，ASR → LLM → TTS 全流程
- **智能记忆**：长期记忆存储、语义搜索、自动遗忘衰减机制
- **多模型支持**：Ollama 本地模型，可扩展支持 VLLM 等其他 LLM
- **工具生态**：MCP (Model Context Protocol) 协议支持，内置多种工具
- **ACP 协议**：局域网自动发现、点对点通信、群组协同
- **弹幕系统**：B站/RDF 弹幕接入，三档防火墙 (block/passive/reply)
- **双向全双工**：支持用户打断 Agent TTS、Agent 打断用户说话
- **VAD 语音检测**：WebRTC/Energy/Silero 多种模式
- **情感 TTS**：支持多种情感音色的语音合成
- **知识图谱**：语义节点存储、关系管理、图遍历查询

### 高级特性

- **四类知识图谱**：用户图谱、事物图谱、概念图谱、事件图谱
- **三维评分模型**：重要性 + 时间 + 相关性综合评估
- **场景感知路由**：根据对话场景动态调整检索策略
- **混合搜索**：向量搜索 + 关键词搜索
- **多 Agent 隔离**：支持多租户架构，每个 Agent 独立记忆空间
- **直播模式**：虚拟形象 (Live2D/VRM)、弹幕叠加、字幕显示

## 快速开始

### 环境要求

- Windows 10/11 或 Linux
- Python 3.10+
- Node.js 18+
- CUDA 11.8+ (GPU 支持)
- Miniconda3

### 启动服务

#### Windows 一键启动

```batch
.\start-all.bat
```

#### 手动启动

1. **启动后端服务**

```batch
cd CX-O-SERVER
python server/main.py
```

1. **启动前端**

```batch
cd CX-O-Frontend
npm install
npm run dev
```

### 访问界面

- 前端界面: <http://127.0.0.1:5173>
- API 文档: <http://127.0.0.1:8100/docs>
- 健康检查: <http://127.0.0.1:8100/health>

## 服务端口

| 服务                | 端口   | 协议             | 说明          |
| ----------------- | ---- | -------------- | ----------- |
| CX-O Server       | 8100 | WebSocket/HTTP | 单体应用，集成所有功能 |
| CX-O Frontend     | 5173 | HTTP           | Web 前端      |
| Voice WorkStation | 8200 | HTTP           | 语音工作站 (可选)  |
| Weaviate          | 8090 | HTTP/gRPC      | 向量数据库 (可选)  |

## 项目结构

```
CX-O/
├── CX-O-Frontend/              # 前端服务 (React + TypeScript)
│   ├── src/
│   │   ├── api/               # API 客户端
│   │   ├── components/        # React 组件
│   │   │   ├── Avatar/        # 虚拟形象组件
│   │   │   ├── Live/          # 直播组件
│   │   │   ├── Live2D/        # Live2D 组件
│   │   │   ├── VRM/           # VRM 组件
│   │   │   ├── layout/        # 布局组件
│   │   │   └── ui/            # UI 组件
│   │   ├── hooks/             # React Hooks
│   │   ├── i18n/              # 国际化
│   │   ├── pages/             # 页面组件
│   │   ├── store/             # 状态管理 (Zustand)
│   │   └── styles/            # 样式文件
│   ├── public/                # 静态资源
│   └── package.json           # 前端依赖配置
│
├── CX-O-SERVER/                # 后端服务 (Python + FastAPI)
│   ├── server/
│   │   ├── api/               # API 路由
│   │   │   ├── routers/       # REST API 路由
│   │   │   └── middleware/    # 中间件
│   │   ├── core/              # 核心模块
│   │   │   ├── acp/           # ACP 协议
│   │   │   ├── alarm/         # 闹钟系统
│   │   │   ├── asr/           # ASR 服务
│   │   │   ├── context/       # 上下文管理
│   │   │   ├── graph/         # 知识图谱
│   │   │   ├── llm/           # LLM 客户端
│   │   │   ├── memory/        # 记忆系统
│   │   │   ├── plugins/       # 插件系统
│   │   │   ├── session/       # 会话管理
│   │   │   ├── tools/         # 工具系统
│   │   │   ├── tts/           # TTS 服务
│   │   │   └── websocket/     # WebSocket 管理
│   │   ├── gateway/           # 网关模块
│   │   ├── handlers/          # 消息处理器
│   │   ├── protocol/          # 协议定义
│   │   ├── services/          # 业务服务
│   │   └── storage/           # 存储层
│   ├── f5_tts/                # F5-TTS 模型
│   ├── sensevoice/            # SenseVoice 模型
│   └── pyproject.toml         # Python 项目配置
│
├── CX-O-VoiceWorkStation/      # 语音工作站 (可选)
│   ├── workstation/
│   │   ├── api/               # API 接口
│   │   ├── services/          # 服务层
│   │   └── tools/             # 工具集
│   └── pyproject.toml         # Python 项目配置
│
├── cosyvoice/                  # CosyVoice 语音合成 (可选)
│   ├── cosyvoice/             # 核心模块
│   ├── runtime/               # 运行时
│   └── examples/              # 示例代码
│
├── f5-fast/                    # F5-TTS 快速推理 (可选)
│   ├── inference_service/     # 推理服务
│   ├── gateway/               # 网关
│   └── model_repo/            # 模型仓库
│
├── weaviate-embeddings/        # Weaviate 向量嵌入服务 (可选)
│   ├── server.py              # 服务入口
│   └── Dockerfile             # Docker 配置
│
├── config/                     # 配置文件
│   ├── default.yaml           # 主配置
│   ├── settings.py            # 配置加载
│   ├── danmaku.yaml           # 弹幕配置
│   ├── firewall.yaml          # 防火墙配置
│   ├── firewall_v3.yaml       # 防火墙 V3 配置
│   ├── vad.yaml               # VAD 配置
│   └── hidden_prompt.yaml     # 隐藏提示词配置
│
├── data/                       # 数据目录
│   ├── acp/                   # ACP 数据
│   ├── agents.json            # Agent 配置
│   └── memories.db            # 记忆数据库
│
├── docs/                       # 项目文档
│   ├── API.md                 # API 文档
│   └── FEATURES.md            # 功能特性文档
│
├── main.py                     # 旧版入口 (已废弃)
├── start-all.bat              # Windows 一键启动脚本
├── docker-compose.weaviate.yml # Weaviate Docker 配置
└── requirements.txt           # Python 依赖
```

## 核心模块详解

### 1. 智能记忆系统

基于认知科学的记忆管理解决方案：

- **双阶段指数衰减模型**：模拟艾宾浩斯遗忘曲线
- **三维评分**：重要性 + 时间 + 相关性
- **场景感知路由**：根据对话场景动态调整检索策略
- **混合搜索**：向量搜索 + 关键词搜索
- **多 Agent 隔离**：每个 Agent 独立记忆空间

详见：[docs/FEATURES.md](docs/FEATURES.md#智能记忆系统)

### 2. 知识图谱系统

语义图数据库系统：

- **四类图谱**：用户图谱、事物图谱、概念图谱、事件图谱
- **混合架构**：SQLite + Weaviate
- **图算法**：BFS、DFS、Dijkstra、PageRank、社区发现
- **语义搜索**：基于向量的语义检索
- **56 个图工具**：为 LLM 提供图操作能力

详见：[docs/FEATURES.md](docs/FEATURES.md#知识图谱集成功能)

### 3. 三档防火墙系统

直播弹幕内容审核与决策系统：

- **第一档 (block)**：违规内容，直接拦截
- **第二档 (passive)**：正常弹幕，通过但不回复
- **第三档 (reply)**：优质弹幕，值得互动回复
- **双层防护**：规则过滤 + LLM 智能决策

详见：[docs/FEATURES.md](docs/FEATURES.md#三档防火墙系统)

### 4. 直播模式

支持虚拟主播直播场景：

- **虚拟形象**：Live2D / VRM 支持
- **弹幕系统**：B站/RDF 弹幕接入
- **字幕显示**：实时字幕叠加
- **音频控制**：AEC 回声消除、音量控制
- **拆分模式**：OBS 多源支持

## 技术栈

### 后端

- **框架**: Python 3.10+, FastAPI, uvicorn, WebSocket
- **AI 服务**: SenseVoice (ASR), F5-TTS (TTS), CosyVoice (可选)
- **LLM**: Ollama, VLLM
- **数据库**: SQLite, Milvus Lite, ChromaDB, Weaviate
- **协议**: MCP (Model Context Protocol), ACP

### 前端

- **框架**: React 18+, TypeScript, Vite
- **UI**: Tailwind CSS, Framer Motion, Lucide Icons
- **状态管理**: Zustand
- **路由**: React Router v6
- **国际化**: i18next
- **虚拟形象**: @pixiv/three-vrm, pixi-live2d-display
- **图表**: Recharts, React Force Graph

## 配置说明

### 主配置文件 (config/default.yaml)

```yaml
server:
  host: 0.0.0.0
  port: 8100
  debug: true

models:
  main:
    provider: ollama
    host: http://localhost:11434
    model: qwen3-vl:8b
    temperature: 0.7

memory:
  enabled: true
  vector_backend: weaviate
  graph_enabled: true

tts:
  mode: remote          # embedded | remote
  engine: f5-tts
  emotion_enabled: true

asr:
  mode: remote          # embedded | remote
  model_dir: SenseVoiceSmall

live:
  enabled: true
  mode: "integrated"
```

### 环境变量

| 变量名                  | 默认值                | 说明               |
| -------------------- | ------------------ | ---------------- |
| `MEMORY_DB_PATH`     | `data/memories.db` | 记忆数据库路径          |
| `VECTOR_BACKEND`     | `weaviate`         | 向量存储后端           |
| `WEAVIATE_HOST`      | `localhost`        | Weaviate 服务地址    |
| `WEAVIATE_PORT`      | `8090`             | Weaviate HTTP 端口 |
| `EMBEDDING_PROVIDER` | `ollama`           | 嵌入模型提供者          |

## API 文档

完整的 API 文档请参考：[docs/API.md](docs/API.md)

### 主要 API 端点

- **聊天**: `POST /api/chat`, `POST /api/chat/stream`
- **记忆管理**: `GET/POST/PUT/DELETE /api/memories`
- **Agent 管理**: `GET/POST/PUT/DELETE /api/agents`
- **知识图谱**: `GET/POST/PUT/DELETE /api/graph/nodes`, `/api/graph/edges`
- **工具管理**: `GET/POST /api/tools`
- **ACP 协议**: `POST /api/acp/discover`, `/api/acp/send`
- **WebSocket**: `ws://localhost:8100/api/ws/{agent_id}`

## 开发指南

### 前端开发

```bash
cd CX-O-Frontend
npm install
npm run dev          # 开发模式
npm run build        # 生产构建
npm run test         # 运行测试
npm run lint         # 代码检查
```

### 后端开发

```bash
cd CX-O-SERVER
pip install -e .
python server/main.py
```

### 代码规范

- **Python**: Black, isort, mypy
- **TypeScript**: ESLint, Prettier
- **提交规范**: Conventional Commits

## 部署

### Docker 部署

```bash
docker-compose up -d
```

### 生产环境

1. 构建前端：`cd CX-O-Frontend && npm run build`
2. 配置 Nginx 反向代理
3. 使用 Gunicorn/Uvicorn 运行后端
4. 配置 HTTPS 证书

## 常见问题

### 1. 后端无法启动

检查端口 8100 是否被占用，或修改 `config/default.yaml` 中的端口配置。

### 2. 前端无法连接后端

检查后端是否正常运行，或在前端连接设置中修改后端 URL。

### 3. ASR/TTS 服务不可用

确保 SenseVoice 和 F5-TTS 模型已正确安装，或使用远程服务模式。

### 4. 向量数据库连接失败

确保 Weaviate 服务已启动，或使用本地向量存储 (ChromaDB/Milvus Lite)。

## 贡献指南

欢迎提交 Issue 和 Pull Request！

1. Fork 本仓库
2. 创建特性分支：`git checkout -b feature/your-feature`
3. 提交更改：`git commit -m 'Add some feature'`
4. 推送分支：`git push origin feature/your-feature`
5. 提交 Pull Request

## 许可证

MIT License

## 联系方式

如有问题或建议，请通过 GitHub Issues 联系。
