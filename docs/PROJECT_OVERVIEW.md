# CX-O 项目概述

## 项目简介

**CX-O** 是一个基于单体架构的智能语音对话系统，集成语音识别（ASR）、大语言模型（LLM）和语音合成（TTS）能力，提供端到端的语音交互体验。

### 架构演进

| 版本 | 架构 | 特点 |
|------|------|------|
| v1-v3 | 微服务 | 多进程分离，延迟较高 |
| **v4** | **单体** | **进程内直接调用，延迟降低 50%** |

## 系统特性

### 核心能力
- **语音对话**：端到端语音交互，ASR → LLM → TTS 全流程
- **智能记忆**：长期记忆存储、语义搜索、自动归档遗忘机制
- **多模型支持**：Ollama 本地模型，可扩展支持 VLLM 等其他 LLM
- **工具生态**：MCP（Model Context Protocol）协议支持，内置多种工具
- **ACP 协议**：局域网自动发现、点对点通信、群组协同
- **弹幕系统**：B站/RDF 弹幕接入，三档防火墙（block/passive/reply）
- **双向全双工**：支持用户打断 Agent TTS、Agent 打断用户说话
- **VAD 语音检测**：WebRTC/Energy/Silero 多种模式

### 技术架构（单体）
- **服务层**：统一的 WebSocket/HTTP 网关 + ASR/TTS 直接调用
- **核心层**：记忆管理、工具调用、Agent 系统（进程内）
- **前端层**：React + TypeScript 管理界面

## 目录结构

```
CX-O/
├── server/                    # 单体应用
│   ├── main.py               # 入口文件
│   ├── config.py             # 配置管理
│   ├── config.json           # 配置文件
│   │
│   ├── gateway/              # WebSocket 网关
│   ├── handlers/             # 消息处理器
│   ├── services/             # 服务层（ASR/TTS/记忆等）
│   ├── core/                 # 核心业务（LLM/记忆/工具等）
│   ├── api/                  # REST API
│   └── protocol/             # 协议定义
│
├── frontend/                  # 前端管理界面
│   └── src/                  # React 源码
│
├── data/                      # 数据文件
│   ├── acp/                  # ACP 配置
│   ├── memories.db            # 记忆数据库
│   └── sessions.db            # 会话数据库
│
└── docs/                     # 项目文档
```

## 服务端口

| 服务 | 端口 | 协议 | 说明 |
|------|------|------|------|
| CX-O Server | 8100 | WebSocket/HTTP | 统一入口，包含所有功能 |
| 前端界面 | 5173 | HTTP | React 开发服务器 |

**注意**：v4 单体架构不再需要独立的服务端口（8000/8001/8002）。

## 技术栈

### 后端
- **框架**：Python 3.10+, FastAPI, uvicorn
- **WebSocket**：fastapi-websocket
- **数据库**：SQLite, Milvus Lite, ChromaDB
- **日志**：logging-config

### 前端
- **框架**：React 18+, TypeScript
- **状态管理**：Zustand
- **样式**：Tailwind CSS
- **构建工具**：Vite

### 语音模型
- **ASR**：SenseVoice（阿里，直接调用）
- **TTS**：F5-TTS（零样本语音克隆，直接调用）
- **LLM**：Ollama（本地方便）、VLLM（高性能推理）

## 快速启动

### 环境要求
- Windows 10/11
- Python 3.10+
- Node.js 18+
- Miniconda3（项目内置）

### 启动单体服务
```batch
cd cx-o/server
python main.py
```

### 访问界面
- 管理控制台：http://127.0.0.1:5173

## 配置说明

### 单体配置
文件：`server/config.json`

### VAD 配置
文件：`CXHMS/config/vad.yaml`

### 弹幕防火墙配置
文件：`CXHMS/config/firewall.yaml` 或 `firewall_v3.yaml`

## 版本历史

- **v4**：单体架构重构，ASR/TTS 直接调用，延迟降低 50%
- **v3**：新增双向全双工架构，支持用户/Agent 相互打断
- **v2**：弹幕防火墙系统
- **v1**：基础语音对话功能

## 性能对比

| 指标 | 微服务 (v3) | 单体 (v4) | 改善 |
|------|-------------|-----------|------|
| 语音对话延迟 | ~800ms | ~400ms | -50% |
| 内存占用 | ~8GB | ~6GB | -25% |
| 启动时间 | ~60s | ~45s | -25% |

## License

MIT
