# CX-O 网关文档

## 概述

CX-O Gateway 是系统的统一入口，处理前端所有请求，负责 WebSocket 通信、协议解析和服务协调。

**服务端口**: 8100

## 架构

```
前端 (5173) → WebSocket (8100) → Handlers → Services → CXHMS/SenseVoice/F5-TTS
```

## WebSocket 连接

```javascript
const ws = new WebSocket("ws://127.0.0.1:8100/ws");

ws.onopen = () => {
  console.log("Connected to CX-O Gateway");
};

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log("Received:", data);
};
```

## 消息格式

### 请求

```json
{
  "type": "request",
  "action": "module.action",
  "request_id": "uuid-string",
  "data": {}
}
```

### 响应

```json
{
  "type": "response",
  "request_id": "uuid-string",
  "action": "module.action",
  "status": "success",
  "data": {}
}
```

### 流式响应

```json
{
  "type": "stream",
  "request_id": "uuid-string",
  "action": "module.action",
  "chunk_index": 0,
  "data": {},
  "is_final": false
}
```

### 错误响应

```json
{
  "type": "error",
  "request_id": "uuid-string",
  "action": "module.action",
  "code": "ERROR_CODE",
  "message": "错误描述"
}
```

## Action 列表

### 聊天

| Action | 说明 | data |
|--------|------|------|
| chat.message | 发送消息 | `{messages, agent_id}` |
| chat.stream | 流式聊天 | `{text, agent_id}` |
| chat.multimodal | 多模态输入 | `{messages, audio}` |

### 记忆

| Action | 说明 | data |
|--------|------|------|
| memory.list | 列出记忆 | `{}` |
| memory.create | 创建记忆 | `{content, memory_type, tags}` |
| memory.search | 搜索记忆 | `{query}` |
| memory.update | 更新记忆 | `{id, content}` |
| memory.delete | 删除记忆 | `{id}` |

### 语音

| Action | 说明 | data |
|--------|------|------|
| asr.recognize | 语音识别 | `{audio: base64}` |
| asr.recognize_base64 | Base64 识别 | `{audio: base64, language}` |
| asr.stream | 实时 ASR 流 | `{audio: base64}` |
| tts.synthesize | 语音合成 | `{text, ref_audio, ref_text}` |
| tts.synthesize_stream | 流式 TTS | `{text, emotion_enabled}` |

### 工具

| Action | 说明 | data |
|--------|------|------|
| tools.list | 列出工具 | `{}` |
| tools.call | 调用工具 | `{tool_name, parameters}` |

### 系统

| Action | 说明 | data |
|--------|------|------|
| system.health | 健康检查 | `{}` |
| system.config | 获取配置 | `{}` |

### ACP

| Action | 说明 | data |
|--------|------|------|
| acp.discover | 发现 Agent | `{}` |
| acp.send | 发送消息 | `{target, message}` |

## 配置

`cx-o-gateway/config.json`:

```json
{
  "server": {
    "host": "0.0.0.0",
    "port": 8100
  },
  "services": {
    "cxhms": {
      "url": "http://127.0.0.1:8000"
    },
    "sensevoice": {
      "url": "http://127.0.0.1:8001"
    },
    "f5tts": {
      "url": "http://127.0.0.1:8002"
    }
  },
  "cors": {
    "enabled": true,
    "origins": ["*"]
  }
}
```

## 服务调用

Gateway 通过 HTTP 客户端调用后端服务：

```python
# handlers/audio.py
from services.asr_client import get_asr_client
from services.tts_client import get_tts_client

asr = get_asr_client()
tts = get_tts_client()

# 调用 ASR 服务
result = await asr.recognize(audio_data)

# 调用 TTS 服务
audio = await tts.synthesize(text)
```

## 心跳

Gateway 支持心跳检测：

```json
{"type": "ping", "timestamp": 1234567890}
```

## 性能优化

- HTTP 客户端连接复用
- 流式响应减少首字节延迟
- 并发请求处理
