# CX-O 智能语音对话系统

基于微服务架构的智能语音对话系统，集成语音识别（ASR）、大语言模型（LLM）和语音合成（TTS）能力。

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
   │  Backend    │ │    (ASR)   │    │    (TTS)    │
   │  Port 8000  │ │  Port 8001 │    │  Port 8002  │
   └─────────────┘ └─────────────┘    └─────────────┘
```

## 功能特性

- **语音对话**: 端到端语音交互，集成 ASR → LLM → TTS
- **智能记忆**: 长期记忆存储、语义搜索、自动归档
- **多模型支持**: Ollama 本地模型，可扩展支持其他 LLM
- **工具生态**: MCP 协议支持，内置多种工具
- **ACP 协议**: 局域网自动发现、点对点通信、群组协同
- **弹幕系统**: B站/RDF 弹幕接入，三档防火墙（block/passive/reply）
- **双向全双工**: 用户打断 Agent TTS、Agent 打断用户说话
- **VAD 语音检测**: WebRTC/Energy/Silero 多种模式

## 快速开始

### 环境要求

- Windows 10/11
- Python 3.10+
- Node.js 18+
- Miniconda3 (项目内置)

### 启动服务

```batch
# 一键启动所有服务
d:\CX-O\1-1.start-all.bat

# 停止所有服务
d:\CX-O\1-2.stop-all.bat
```

### 访问界面

- 管理控制台: http://127.0.0.1:5173

## 服务说明

| 服务 | 端口 | 协议 | 说明 |
|------|------|------|------|
| CX-O Gateway | 8100 | WebSocket | 前端网关，统一入口 |
| CXHMS Backend | 8000 | WebSocket | 后端核心服务 |
| SenseVoice ASR | 8001 | HTTP | 语音识别服务 |
| F5-TTS | 8002 | HTTP | 语音合成服务 |

## 项目结构

```
CX-O/
├── cx-o-gateway/          # WebSocket 网关服务
│   ├── main.py            # 入口文件
│   ├── config.json        # 配置文件
│   ├── gateway/           # 网关核心
│   ├── handlers/          # 消息处理器
│   └── requirements.txt
│
├── cx-o-frontend/         # 前端管理界面
│   ├── src/
│   │   ├── api/           # WebSocket 客户端
│   │   ├── components/    # UI 组件
│   │   ├── pages/         # 页面
│   │   └── store/         # 状态管理
│   └── package.json
│
├── CXHMS/                 # 后端核心服务
│   ├── backend/           # FastAPI 后端
│   │   ├── api/           # API 路由
│   │   ├── core/          # 核心模块
│   │   └── tests/         # 测试
│   ├── config/            # 配置文件
│   ├── docs/              # 文档
│   └── requirements.txt
│
├── SenseVoice/            # 语音识别服务
│   └── api.py
│
├── F5-TTS/                # 语音合成服务
│   ├── webapi.py
│   └── requirements.txt
│
├── CosyVoice/             # 备用语音合成
│
├── data/                  # 数据配置
│   ├── acp/               # ACP 配置
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
      "url": "ws://127.0.0.1:8000/ws"
    },
    "asr": {
      "url": "http://127.0.0.1:8001"
    },
    "tts": {
      "url": "http://127.0.0.1:8002"
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

memory:
  vector_backend: milvus_lite
```

## WebSocket 协议

### 消息格式

```json
{
  "action": "chat.message",
  "request_id": "uuid-string",
  "data": {
    "message": "你好"
  }
}
```

### 核心 Action

| 模块 | Action | 说明 |
|------|--------|------|
| 聊天 | chat.message | 发送消息 |
| 聊天 | chat.voice | 语音对话 |
| 记忆 | memory.save | 保存记忆 |
| 记忆 | memory.search | 搜索记忆 |
| 工具 | tools.list | 列出工具 |
| 工具 | tools.call | 调用工具 |
| 语音 | asr.recognize | 语音识别 |
| 语音 | tts.synthesize | 语音合成 |
| 语音 | asr_stream | 实时音频流（带 VAD） |
| 直播 | live.connect | 连接直播客户端 |
| 直播 | live.danmaku | 弹幕消息 |
| 防火墙 | firewall.decide | 弹幕决策 |

## v3 新增功能

### 双向全双工架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        双向全双工架构                                     │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  场景 1: 用户打断 Agent                                                 │
│  Agent TTS 播放中 ──▶ 用户说话 ──▶ ASR 识别 ──▶ LLM 判断               │
│                                              │                          │
│                              ┌───────────────┴───────────────┐          │
│                              ▼                               ▼          │
│                      需要打断用户              不需要打断                │
│                      停止 TTS                 继续播放                  │
│                      生成新回复                                          │
│                                                                         │
│  场景 2: Agent 打断用户                                                 │
│  用户说话中 ──▶ 实时 ASR 流 ──▶ LLM 实时判断                           │
│                                    │                                    │
│                    ┌───────────────┴───────────────┐                    │
│                    ▼                               ▼                    │
│            可以插话/用户说完              用户还在说                    │
│            打断用户音频                   继续监听                      │
│            开始 TTS 回复                                                │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
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

文件: `CXHMS/config/firewall.yaml`

```yaml
llm:
  default_model: "qwen2.5:latest"

blocking:
  blacklist:
    - "123456"
  blacklist_enabled: true

decision:
  timeout_ms: 5000
```

三档决策：
- **BLOCK**: 阻断弹幕，不加入上下文
- **PASSIVE**: 放行弹幕，加入上下文，不触发回复
- **REPLY**: 放行弹幕，加入上下文，触发 LLM 回复

## 技术栈

- **后端**: Python, FastAPI, WebSocket, httpx
- **前端**: React, TypeScript, Tailwind CSS, Zustand
- **语音识别**: SenseVoice
- **语音合成**: F5-TTS, CosyVoice
- **向量存储**: Milvus Lite, ChromaDB

## 常见问题

### 1. 启动失败

- 检查端口占用: `netstat -ano | findstr "8000 8001 8002 8100 5173"`
- 确认 Miniconda3 环境存在

### 2. 模型加载失败

- SenseVoice/F5-TTS 首次启动会下载模型，请确保网络连接

### 3. TTS 使用说明

F5-TTS 是零样本语音克隆模型，使用时需要提供：
- **参考音频**: 用于克隆音色的 WAV 音频
- **参考文本**: 参考音频对应的文本

## 开发

### 安装依赖

```batch
# 安装所有依赖
d:\CX-O\install-all.bat

# 仅安装 npm 依赖
d:\CX-O\install-npm.bat
```

### 前端开发

```bash
cd cx-o-frontend

# 开发模式
npm run dev

# 构建
npm run build

# 类型检查
npm run typecheck
```

## License

MIT
