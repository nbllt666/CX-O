# CXHMS (晨曦人格化记忆系统)

CXHMS (CX-O History & Memory Service) 是一个智能记忆管理平台，提供长期记忆存储、语义搜索、自动归档、多模型对话、ACP协议通信和工具调用功能。

## 核心特性

- **智能记忆系统**: 多向量存储后端（Milvus Lite/Chroma）、记忆衰减模型、三维评分、混合搜索
- **ACP 协议**: 局域网自动发现、点对点通信、群组协同
- **工具生态**: MCP 协议支持、内置工具（计算器、记忆管理、提醒等）、动态注册
- **对话系统**: 流式响应、RAG 检索增强、多 Agent 支持、多模态视觉
- **多模型支持**: 支持 Ollama 本地模型，可配置多个模型实例

## 快速开始

### 环境要求

- Python 3.10+
- Node.js 18+
- Ollama (推荐) 或其他 LLM 服务

### 安装启动

```bash
# 1. 安装后端依赖
pip install -r requirements.txt

# 2. 安装模型 (使用 Ollama)
ollama pull qwen3-vl:8b
ollama pull nomic-embed-text

# 3. 启动后端
python main.py

# 4. 安装并启动前端
cd frontend && npm install && npm run dev
```

**Windows 一键启动**: `.\1.1.启动前端(含控制服务)(Conda).bat`

### 服务地址

| 服务 | 地址 |
|------|------|
| API 文档 (Swagger) | http://localhost:8000/docs |
| API 文档 (ReDoc) | http://localhost:8000/redoc |
| 前端界面 | http://localhost:3000 |
| Gradio WebUI | http://localhost:7860 |

## 主要 API

| 端点 | 描述 |
|------|------|
| `POST /api/chat/stream` | 流式聊天 |
| `GET/POST /api/memories` | 记忆管理 |
| `POST /api/memories/search` | 记忆搜索 |
| `POST /api/memories/semantic-search` | 语义搜索 |
| `GET/POST /api/agents` | Agent 管理 |
| `GET/POST /api/tools` | 工具管理 |
| `POST /api/acp/discover` | Agent 发现 |

完整 API 文档: http://localhost:8000/docs

## 项目结构

```
CXHMS/
├── backend/           # Python 后端 (FastAPI)
│   ├── api/routers/   # API 路由
│   │   ├── agents.py  # Agent 管理
│   │   ├── chat.py    # 聊天接口
│   │   ├── memory.py  # 记忆管理
│   │   ├── tools.py   # 工具管理
│   │   └── acp.py     # ACP 协议
│   ├── core/          # 核心模块
│   │   ├── memory/    # 记忆系统
│   │   ├── llm/       # LLM 客户端
│   │   ├── tools/     # 工具系统
│   │   └── acp/       # ACP 协议
│   └── tests/         # 测试用例
├── frontend/          # React 前端
│   └── src/
│       ├── pages/     # 页面组件
│       ├── components/# UI 组件
│       └── store/     # 状态管理 (Zustand)
├── config/            # 配置文件
│   └── default.yaml   # 默认配置
└── docs/              # 文档
    ├── API.md         # API 文档
    ├── ARCHITECTURE.md# 架构文档
    └── TECHNICAL.md   # 技术文档
```

## 配置

主配置文件: `config/default.yaml`

```yaml
models:
  main:
    provider: ollama
    model: qwen3-vl:8b
  memory:
    provider: ollama
    model: qwen3-vl:8b

memory:
  vector_backend: milvus_lite
  decay_model: exponential

server:
  host: 0.0.0.0
  port: 8000
```

## 技术栈

**后端**: FastAPI, Pydantic, Milvus Lite, Ollama, SQLite  
**前端**: React, TypeScript, Vite, Tailwind CSS, Zustand

## 开发

### 后端开发

```bash
# 安装开发依赖
pip install -r requirements.txt

# 运行测试
cd backend && pytest tests/ -v

# 运行测试覆盖率
pytest tests/ --cov=backend --cov-report=term-missing

# 代码格式化
black backend/
isort backend/
```

### 前端开发

```bash
cd frontend

# 安装依赖
npm install

# 开发模式
npm run dev

# 构建生产版本
npm run build

# 运行测试
npm run test

# 代码格式化
npm run format

# 类型检查
npm run typecheck
```

## 文档

- [API 文档](docs/API.md)
- [架构文档](docs/ARCHITECTURE.md)
- [部署指南](docs/DEPLOYMENT.md)
- [技术文档](docs/TECHNICAL.md)

## 许可证

MIT License
