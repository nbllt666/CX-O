# CX-O 网关文档

## 概述

CX-O v4 单体架构中，WebSocket 网关是统一入口，处理前端所有请求。

## 架构

```
前端 (5173) → WebSocket (8100) → Handlers → Services/Core
```

## WebSocket 连接

```javascript
const ws = new WebSocket("ws://127.0.0.1:8100");

ws.onopen = () => {
  console.log("Connected to CX-O Server");
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

## 直接调用服务

在单体架构中，Handlers 直接调用 Services，无需 HTTP：

```python
# handlers/audio.py
from server.services.asr import get_asr_service
from server.services.tts import get_tts_service

asr = get_asr_service()
tts = get_tts_service()

# 直接调用
result = await asr.recognize(audio_data)
audio = await tts.synthesize(text)
```

## 配置

`server/config.json`:

```json
{
  "server": {
    "host": "0.0.0.0",
    "port": 8100
  },
  "cors": {
    "enabled": true,
    "origins": ["*"]
  }
}
```

## 心跳

网关支持心跳检测：

```json
{"type": "ping", "timestamp": 1234567890}
```

## 错误处理

```json
{
  "type": "error",
  "request_id": "uuid-string",
  "action": "module.action",
  "code": "ERROR_CODE",
  "message": "错误描述"
}
```

## 性能优化

- 进程内直接调用，无网络开销
- 流式响应减少首字节延迟
- 连接池复用
