# CX-O 智能语音对话系统

基于微服务架构的智能语音对话系统，集成语音识别（ASR）、大语言模型（LLM）和语音合成（TTS）能力，支持双向全双工语音交互。

## 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                      CX-O Frontend                               │
│                   (React + TypeScript)                          │
│                      http://127.0.0.1:5173                      │
└──────────────────────────┬──────────────────────────────────────┘
                           │ WebSocket
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                      CX-O Gateway                               │
│                   (WebSocket 网关服务)                          │
│                      ws://127.0.0.1:8100                        │
└───────────┬─────────────┬───────────────────┬───────────────────┘
            │             │                   │
            ▼             ▼                   ▼
   ┌─────────────┐ ┌─────────────┐    ┌─────────────┐
   │   CXHMS     │ │  SenseVoice │    │   F5-TTS    │
   │  Backend    │ │    (ASR)    │    │    (TTS)    │
   │  Port 8000  │ │  Port 8001 │    │  Port 8002  │
   └─────────────┘ └─────────────┘    └─────────────┘
```

## 功能特性

- **语音对话**: 端到端语音交互，集成 ASR → LLM → TTS
- **智能记忆**: 长期记忆存储、语义搜索、自动遗忘衰减机制
- **多模型支持**: Ollama 本地模型，可扩展支持 VLLM 等其他 LLM
- **工具生态**: MCP 协议支持，内置多种工具
- **ACP 协议**: 局域网自动发现、点对点通信、群组协同
- **弹幕系统**: B站/RDF 弹幕接入，三档防火墙（block/passive/reply）
- **双向全双工**: 支持用户打断 Agent TTS、Agent 打断用户说话
- **VAD 语音检测**: WebRTC/Energy/Silero 多种模式
- **情感 TTS**: 支持多种情感音色的语音合成

## 快速开始

### 环境要求

- Windows 10/11
- Python 3.10+
- Node.js 18+
- Miniconda3 (项目内置)

### 启动服务

```batch
d:\CX-O\1-1.start-all.bat
```

### 访问界面

- 管理控制台: http://127.0.0.1:5173

## 服务端口

| 服务 | 端口 | 协议 | 说明 |
|------|------|------|------|
| CX-O Gateway | 8100 | WebSocket | 前端网关，统一入口 |
| CXHMS Backend | 8000 | WebSocket/HTTP | 后端核心服务 |
| SenseVoice ASR | 8001 | HTTP | 语音识别服务 |
| F5-TTS | 8002 | HTTP | 语音合成服务 |
| Index-TTS | 8004 | HTTP | 情感语音合成（可选） |

## 项目结构

```
CX-O/
├── cx-o-gateway/          # WebSocket 网关服务
│   ├── gateway/           # 网关核心（连接管理、健康检查）
│   ├── handlers/          # 消息处理器
│   │   ├── chat.py        # 聊天消息处理
│   │   ├── memory.py      # 记忆管理
│   │   ├── audio.py       # 音频处理（ASR/TTS）
│   │   ├── live.py        # 直播客户端处理
│   │   ├── acp.py         # ACP 协议通信
│   │   └── mcp.py         # MCP 服务器管理
│   ├── services/          # 服务客户端
│   │   ├── cxhms_client.py    # CXHMS 后端通信
│   │   ├── asr_client.py      # 语音识别客户端
│   │   ├── tts_client.py      # F5-TTS 客户端
│   │   ├── index_tts_client.py # Index-TTS 客户端
│   │   ├── emotion_parser.py  # 情感解析
│   │   ├── effect_parser.py   # 音效解析
│   │   ├── vad_processor.py   # VAD 语音检测
│   │   ├── firewall.py        # 弹幕防火墙
│   │   └── interrupt_manager.py # 打断管理
│   ├── protocol/          # 协议定义
│   ├── main.py            # 入口文件
│   ├── config.json        # 配置文件
│   └── requirements.txt
│
├── cx-o-frontend/         # 前端管理界面
│   └── src/
│       ├── api/           # WebSocket 客户端
│       ├── components/    # UI 组件
│       ├── pages/         # 页面
│       └── store/         # 状态管理 (Zustand)
│
├── CXHMS/                 # 后端核心服务
│   ├── backend/           # FastAPI 后端
│   │   ├── api/          # API 路由
│   │   │   ├── routers/  # 路由模块
│   │   │   ├── app.py     # FastAPI 应用
│   │   │   └── exceptions.py
│   │   ├── core/         # 核心模块
│   │   │   ├── memory/   # 记忆系统
│   │   │   ├── llm/      # LLM 客户端
│   │   │   ├── tools/    # 工具系统
│   │   │   ├── acp/      # ACP 协议
│   │   │   ├── model_router.py  # 模型路由器
│   │   │   └── context/  # 上下文管理
│   │   └── tests/        # 测试用例
│   ├── config/            # 配置文件
│   │   ├── default.yaml  # 默认配置
│   │   ├── vad.yaml      # VAD 配置
│   │   ├── firewall.yaml  # 弹幕防火墙
│   │   └── hidden_prompt.yaml
│   └── docs/              # 文档
│
├── SenseVoice/            # 语音识别服务（ASR）
│   └── api.py
│
├── F5-TTS/                # 语音合成服务（TTS）
│   ├── webapi.py
│   └── requirements.txt
│
├── CosyVoice/             # 备用语音合成
│
├── data/                  # 数据配置
│   ├── acp/               # ACP 配置
│   │   ├── agents.yaml   # Agent 定义
│   │   ├── connections.yaml
│   │   └── groups.yaml
│   └── agents.json
│
└── docs/                  # 项目文档
```

## 配置说明

### Gateway 配置

文件: `cx-o-gateway/config.json`

```json
{
  "gateway": {
    "host": "0.0.0.0",
    "port": 8100
  },
  "services": {
    "cxhms": {
      "url": "ws://127.0.0.1:8000/api/ws"
    },
    "asr": {
      "url": "http://127.0.0.1:8001"
    },
    "tts": {
      "url": "http://127.0.0.1:8002"
    },
    "index_tts": {
      "url": "http://127.0.0.1:8004",
      "enabled": true
    }
  }
}
```

### CXHMS 配置

文件: `CXHMS/config/default.yaml`

```yaml
models:
  main:
    provider: ollama
    model: qwen3-vl:8b
  summary:
    provider: ollama
    model: qwen3-vl:8b
  memory:
    provider: ollama
    model: qwen3-vl:8b

memory:
  vector_backend: milvus_lite
  vector_enabled: true
  decay_enabled: true
```

## WebSocket 协议

### 消息格式

```json
{
  "type": "request",
  "action": "chat.message",
  "request_id": "uuid-string",
  "data": {}
}
```

### 核心 Action

| 模块 | Action | 说明 |
|------|--------|------|
| 聊天 | chat.message | 发送消息 |
| 聊天 | chat.stream | 流式聊天 |
| 记忆 | memory.list | 列出记忆 |
| 记忆 | memory.create | 创建记忆 |
| 记忆 | memory.search | 搜索记忆 |
| 工具 | tools.list | 列出工具 |
| 工具 | tools.call | 调用工具 |
| 语音 | asr.recognize | 语音识别 |
| 语音 | tts.synthesize | 语音合成 |
| 语音 | asr.stream | 实时音频流（带 VAD） |
| 直播 | live.connect | 连接直播客户端 |
| 直播 | live.danmaku | 弹幕消息 |
| ACP | acp.connect | 连接 Agent |
| ACP | acp.send | 发送消息 |

## v3 双向全双工架构

### 用户打断 Agent

```
Agent TTS 播放中 ──▶ 用户说话 ──▶ VAD 检测 ──▶ ASR 识别 ──▶ LLM 判断
                                            │
                        ┌───────────────────┴───────────────────┐
                        ▼                                       ▼
                需要打断：停止 TTS                       不需要打断：继续播放
                生成新回复，开始新 TTS
```

### Agent 打断用户

```
用户说话中 ──▶ 实时 ASR 流 ──▶ LLM 实时判断
                              │
            ┌─────────────────┴─────────────────┐
            ▼                                   ▼
    可以插话：打断用户音频              用户还在说：继续监听
    开始 TTS 回复
```

### VAD 配置

文件: `CXHMS/config/vad.yaml`

```yaml
vad:
  mode: "webrtc"           # energy | webrtc | silero
  sample_rate: 16000
  frame_duration_ms: 30
  silence_threshold_ms: 500
  speech_threshold_ms: 300

audio_stream:
  asr_interval_ms: 500

agent_interrupt:
  enabled: true
  interrupt_threshold_ms: 500
  min_speech_duration_ms: 1000
  interrupt_cooldown_ms: 3000
```

### 弹幕防火墙

三档决策：
- **BLOCK**: 阻断弹幕，不加入上下文
- **PASSIVE**: 放行弹幕，加入上下文，不触发回复
- **REPLY**: 放行弹幕，加入上下文，触发 LLM 回复

## 技术栈

- **网关**: Python, FastAPI, WebSocket, uvicorn
- **后端**: Python, FastAPI, Pydantic, SQLite, Milvus Lite
- **前端**: React, TypeScript, Tailwind CSS, Zustand
- **语音识别**: SenseVoice（阿里）
- **语音合成**: F5-TTS（零样本克隆）, Index-TTS（情感TTS）, CosyVoice
- **LLM**: Ollama, VLLM
- **协议**: MCP（Model Context Protocol）, ACP

## 常见问题

### 1. 启动失败

```batch
netstat -ano | findstr "8000 8001 8002 8100 5173"
```

### 2. 模型加载失败

SenseVoice/F5-TTS 首次启动会下载模型，请确保网络连接。

### 3. TTS 使用说明

F5-TTS 是零样本语音克隆模型，使用时需要提供：
- **参考音频**: 用于克隆音色的 WAV 音频
- **参考文本**: 参考音频对应的文本

Index-TTS 支持情感 TTS，提供多种情感音色。

## 开发

### 安装依赖

```batch
d:\CX-O\install-all.bat
```

### 前端开发

```bash
cd cx-o-frontend
npm run dev
npm run build
npm run typecheck
```

### 后端开发

```bash
cd CXHMS/backend
pip install -r requirements.txt
pytest tests/ -v
```

## 文档

- [架构文档](docs/ARCHITECTURE.md)
- [Gateway 文档](docs/GATEWAY.md)
- [CXHMS 文档](docs/CXHMS.md)
- [API 文档](docs/API.md)
- [部署指南](docs/DEPLOYMENT.md)

## License

MIT
