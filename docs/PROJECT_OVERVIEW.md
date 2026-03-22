# CX-O 项目概述

## 项目简介

**CX-O** 是一个基于微服务架构的智能语音对话系统，集成语音识别（ASR）、大语言模型（LLM）和语音合成（TTS）能力，提供端到端的语音交互体验。

## 系统特性

### 核心能力
- **语音对话**：端到端语音交互，集成 ASR → LLM → TTS 全流程
- **智能记忆**：长期记忆存储、语义搜索、自动归档遗忘机制
- **多模型支持**：Ollama 本地模型，可扩展支持 VLLM 等其他 LLM
- **工具生态**：MCP（Model Context Protocol）协议支持，内置多种工具
- **ACP 协议**：局域网自动发现、点对点通信、群组协同
- **弹幕系统**：B站/RDF 弹幕接入，三档防火墙（block/passive/reply）
- **双向全双工**：支持用户打断 Agent TTS、Agent 打断用户说话
- **VAD 语音检测**：WebRTC/Energy/Silero 多种模式

### 技术架构
- **网关层**：统一的 WebSocket/HTTP 网关（cx-o-gateway）
- **核心层**：CXHMS 后端服务（记忆管理、工具调用、Agent 系统）
- **语音层**：SenseVoice（ASR）、F5-TTS/CosyVoice（ TTS）
- **前端层**：React + TypeScript 管理界面

## 目录结构

```
CX-O/
├── cx-o-gateway/          # WebSocket 网关服务
│   ├── gateway/           # 网关核心
│   ├── handlers/          # 消息处理器
│   ├── protocol/          # 协议定义
│   ├── services/          # 服务客户端
│   └── main.py            # 入口文件
│
├── cx-o-frontend/         # 前端管理界面
│   └── src/               # React 源码
│
├── CXHMS/                 # 后端核心服务
│   ├── backend/           # FastAPI 后端
│   │   ├── api/           # API 路由
│   │   ├── core/          # 核心模块（LLM、记忆、工具等）
│   │   └── tests/         # 测试
│   └── config/            # 配置文件
│
├── SenseVoice/            # 语音识别服务（ASR）
│   └── api.py
│
├── F5-TTS/                # 语音合成服务（TTS）
│   └── webapi.py
│
├── CosyVoice/             # 备用语音合成
│
├── data/                  # 数据配置
│   ├── acp/               # ACP 配置
│   └── agents.json        # Agent 配置
│
└── docs/                  # 项目文档
```

## 服务端口

| 服务 | 端口 | 协议 | 说明 |
|------|------|------|------|
| CX-O Gateway | 8100 | WebSocket/HTTP | 前端网关，统一入口 |
| CXHMS Backend | 8000 | WebSocket/HTTP | 后端核心服务 |
| SenseVoice ASR | 8001 | HTTP | 语音识别服务 |
| F5-TTS | 8002 | HTTP | 语音合成服务 |
| 前端界面 | 5173 | HTTP | React 开发服务器 |

## 技术栈

### 后端
- **框架**：Python 3.10+, FastAPI, uvicorn
- **WebSocket**：fastapi-websocket
- **HTTP 客户端**：httpx
- **数据库**：SQLite, Milvus Lite, ChromaDB
- **日志**：logging-config

### 前端
- **框架**：React 18+, TypeScript
- **状态管理**：Zustand
- **样式**：Tailwind CSS
- **构建工具**：Vite

### 语音模型
- **ASR**：SenseVoice（阿里）
- **TTS**：F5-TTS（零样本语音克隆）、CosyVoice（支持情感）
- **LLM**：Ollama（本地方便）、VLLM（高性能推理）

## 快速启动

### 环境要求
- Windows 10/11
- Python 3.10+
- Node.js 18+
- Miniconda3（项目内置）

### 启动所有服务
```batch
d:\CX-O\1-1.start-all.bat
```

### 访问界面
- 管理控制台：http://127.0.0.1:5173

## 配置说明

### Gateway 配置
文件：`cx-o-gateway/config.json`

### CXHMS 配置
文件：`CXHMS/config/default.yaml`

### VAD 配置
文件：`CXHMS/config/vad.yaml`

### 弹幕防火墙配置
文件：`CXHMS/config/firewall.yaml` 或 `firewall_v3.yaml`

## 版本历史

- **v3**：新增双向全双工架构，支持用户/Agent 相互打断
- **v2**：弹幕防火墙系统
- **v1**：基础语音对话功能

## License

MIT
