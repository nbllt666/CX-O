# CX-O Gateway 网关服务

## 概述

CX-O Gateway 是系统的统一入口，提供 WebSocket 和 HTTP API 网关功能，负责请求路由、服务转发、连接管理。

## 入口文件

**文件**：`cx-o-gateway/main.py`

```python
app = create_app()
uvicorn.run(
    "main:app",
    host=config.gateway.host,
    port=config.gateway.port,
    reload=False,
    log_level=config.logging.level.lower()
)
```

## 架构

```
┌─────────────────────────────────────────────────────────────────┐
│                       CX-O Gateway                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                    FastAPI Application                   │   │
│  │                                                           │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐      │   │
│  │  │  HTTP API   │  │  WebSocket  │  │   Health    │      │   │
│  │  │  Endpoints  │  │  Endpoints  │  │   Checker   │      │   │
│  │  └─────────────┘  └─────────────┘  └─────────────┘      │   │
│  │           │              │                               │   │
│  │  ┌────────┴──────────────┴────────┐                    │   │
│  │  │      ConnectionManager          │                    │   │
│  │  │  - _connections: Dict           │                    │   │
│  │  │  - _handlers: Dict              │                    │   │
│  │  │  - _stats: Dict                 │                    │   │
│  │  └─────────────────────────────────┘                    │   │
│  │                      │                                  │   │
│  │  ┌───────────────────┼───────────────────┐              │   │
│  │  │                   │                   │              │   │
│  │  ▼                   ▼                   ▼              │   │
│  │ ChatHandler    MemoryHandler      AudioHandler           │   │
│  │ ToolsHandler   ACPHandler         MCPHandler            │   │
│  │ ConfigHandler  MetricsHandler     PluginHandler         │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## WebSocket 端点

### WS /ws
通用 WebSocket 端点，处理所有客户端消息。

### WS /ws/live
直播客户端专用端点，支持伪全双工通信。

## HTTP API 端点

### 健康检查
- `GET /health` - 返回服务健康状态

### 服务代理
- `GET /api/stats` - 获取网关统计
- `POST /api/{path}` - 代理请求到 CXHMS

### 音频接口
- `GET /api/audio/files` - 列出音频文件
- `POST /api/audio/upload` - 上传音频文件
- `GET /api/audio/files/{filename}` - 获取音频文件
- `DELETE /api/audio/files/{filename}` - 删除音频文件

### 配置接口
- `GET /api/config/audio` - 获取音频配置
- `POST /api/config/audio` - 更新音频配置
- `GET /api/config/services` - 获取服务配置
- `POST /api/config/services` - 更新服务配置

### TTS 接口
- `POST /api/tts/synthesize` - 非流式语音合成
- `POST /api/tts/synthesize-stream` - 流式语音合成

### ASR 接口
- `POST /api/asr/speech-to-text` - 语音转文字

### IndexTTS 接口
- `GET /api/index-tts/status` - IndexTTS 服务状态
- `POST /api/index-tts/synthesize` - IndexTTS 语音合成
- `POST /api/audio/generate-emotions` - 生成情感音频

### 控制服务代理
- `GET /control/{path}` - 代理到控制服务
- `POST /control/{path}` - 代理到控制服务

## 消息协议

### 消息类型

| 类型 | 说明 |
|------|------|
| REQUEST | 请求消息 |
| RESPONSE | 响应消息 |
| STREAM | 流式消息 |
| ERROR | 错误消息 |
| PING | 心跳请求 |
| PONG | 心跳响应 |

### 消息格式

**请求**：
```json
{
  "type": "request",
  "action": "chat.message",
  "request_id": "uuid-string",
  "data": {}
}
```

**响应**：
```json
{
  "type": "response",
  "action": "chat.message",
  "request_id": "uuid-string",
  "status": "success",
  "data": {}
}
```

**流式响应**：
```json
{
  "type": "stream",
  "action": "chat.stream",
  "request_id": "uuid-string",
  "chunk_index": 0,
  "data": {"content": "..."},
  "is_final": false
}
```

## Handler 模块

### Chat Handler

处理聊天消息，转发到 CXHMS 后端。

**Actions**：
- `chat.message` - 非流式聊天
- `chat.stream` - 流式聊天
- `chat.multimodal` - 多模态聊天

### Memory Handler

处理记忆相关操作。

**Actions**：
- `memory.list` - 获取记忆列表
- `memory.create` - 创建记忆
- `memory.get` - 获取记忆详情
- `memory.update` - 更新记忆
- `memory.delete` - 删除记忆
- `memory.search` - 搜索记忆

### Audio Handler

处理 ASR/TTS 音频操作。

**Actions**：
- `asr.recognize` - 语音识别
- `asr.recognize_base64` - base64 音频识别
- `asr.stream` - 实时音频流（带 VAD）
- `tts.synthesize` - 语音合成
- `tts.synthesize_stream` - 流式语音合成
- `tts.voices` - 获取声音列表

### Live Handler

处理直播客户端消息。

**功能**：
- 弹幕接收与处理
- TTS 播放状态通知
- 音频流处理（伪全双工）
- VAD 状态通知

### Tools Handler

处理工具调用。

**Actions**：
- `tools.list` - 列出可用工具
- `tools.call` - 调用工具
- `tools.register` - 注册工具

### ACP Handler

处理 Agent 通信协议。

**Actions**：
- `acp.connect` - 连接 Agent
- `acp.disconnect` - 断开连接
- `acp.connections` - 列出连接
- `acp.status` - 获取状态
- `acp.send` - 发送消息

### MCP Handler

处理 MCP 协议。

**Actions**：
- `mcp.connect` - 连接 MCP 服务器
- `mcp.disconnect` - 断开 MCP 服务器
- `mcp.tools` - 获取 MCP 工具
- `mcp.call` - 调用 MCP 工具
- `mcp.status` - 获取状态

### Config Handler

处理配置管理。

**Actions**：
- `config.get` - 获取配置
- `config.set` - 设置配置
- `config.reset` - 重置配置

### Metrics Handler

处理指标统计。

**Actions**：
- `metrics.get` - 获取指标
- `metrics.requests` - 获取请求指标
- `metrics.history` - 获取历史指标

### System Handler

处理系统操作。

**Actions**：
- `system.health` - 健康检查
- `system.status` - 系统状态
- `system.info` - 系统信息

## Service 模块

### CXHMSClient

与 CXHMS 后端通信的客户端封装。

```python
cxhms_client = CXHMSClient(
    url="ws://127.0.0.1:8000/ws",
    pool_size=5
)
await cxhms_client.connect()
response = await cxhms_client.request(action, data)
```

### ASRClient

语音识别客户端。

```python
asr_client = ASRClient(
    base_url="http://127.0.0.1:8001",
    timeout=120
)
result = await asr_client.recognize(audio_data, language)
```

### TTSClient

语音合成客户端。

```python
tts_client = TTSClient(
    base_url="http://127.0.0.1:8002",
    ref_audio_path="path/to/ref.wav",
    ref_text="参考文本",
    timeout=120
)
audio_bytes = await tts_client.synthesize(text, **kwargs)
```

### FirewallService

弹幕防火墙服务，提供三档决策（BLOCK/PASSIVE/REPLY）。

### VADProcessor

语音活动检测处理器，支持 WebRTC/Energy/Silero 模式。

### LiveClient

直播客户端处理器，处理伪全双工通信。

## 配置

**文件**：`cx-o-gateway/config.json`

```json
{
  "gateway": {
    "host": "0.0.0.0",
    "port": 8100,
    "cors": {
      "allow_origins": ["*"],
      "allow_methods": ["*"],
      "allow_headers": ["*"]
    }
  },
  "services": {
    "cxhms": {
      "url": "ws://127.0.0.1:8000/ws",
      "http_url": "http://127.0.0.1:8000",
      "timeout": 60
    },
    "asr": {
      "url": "http://127.0.0.1:8001",
      "timeout": 120
    },
    "tts": {
      "url": "http://127.0.0.1:8002",
      "timeout": 120
    }
  },
  "logging": {
    "level": "INFO"
  }
}
```

## 伪全双工通信

直播 WebSocket 端点 `/ws/live` 支持伪全双工通信流程：

```
客户端                              服务端
─────                              ─────
  │                                   │
  │──── tts_start ──────────────────►│ _is_tts_playing = True
  │                                   │
  │──── audio_stream ───────────────►│ VAD 检测
  │                                   │    ↓
  │                                   │ ASR 识别
  │                                   │    ↓
  │                                   │ LLM 判断打断
  │◄─── tts_interrupt ───────────────│    ↓ (需要打断)
  │◄─── interrupt_reply ─────────────│ 新回复内容
  │                                   │
  │──── tts_end ────────────────────►│ _is_tts_playing = False
```

## 统计数据

网关维护以下统计数据：
- `tts_count` - TTS 请求计数
- `asr_count` - ASR 请求计数
- `llm_count` - LLM 请求计数
- `client_count` - 当前连接客户端数
