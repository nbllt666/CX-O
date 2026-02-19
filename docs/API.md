# CX-O API 文档

## 概述

CX-O 使用 WebSocket 协议进行前后端通信。所有消息采用 JSON 格式。

## 连接地址

```
ws://127.0.0.1:8100/ws
```

## 消息格式

### 请求消息

```json
{
  "type": "request",
  "request_id": "uuid-string",
  "action": "chat.message",
  "data": {
    "message": "你好"
  }
}
```

### 响应消息

```json
{
  "type": "response",
  "request_id": "uuid-string",
  "action": "chat.message",
  "status": "success",
  "data": {
    "reply": "你好！有什么可以帮助你的吗？"
  }
}
```

### 流式消息

```json
{
  "type": "stream",
  "request_id": "uuid-string",
  "action": "chat.stream",
  "chunk_index": 0,
  "data": {
    "content": "你好"
  },
  "is_final": false
}
```

### 错误消息

```json
{
  "type": "error",
  "request_id": "uuid-string",
  "action": "chat.message",
  "error": {
    "code": "INVALID_REQUEST",
    "message": "Missing message content"
  }
}
```

---

## 聊天模块 (chat.*)

### chat.message - 发送消息

发送文本消息到后端处理。

**请求：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| message | string | 是 | 消息内容 |
| session_id | string | 否 | 会话ID |

```json
{
  "action": "chat.message",
  "data": {
    "message": "你好，请介绍一下你自己",
    "session_id": "session-001"
  }
}
```

**响应：**

```json
{
  "type": "response",
  "action": "chat.message",
  "data": {
    "reply": "你好！我是...",
    "session_id": "session-001"
  }
}
```

### chat.stream - 流式对话

使用流式输出接收回复。

**请求：**

```json
{
  "action": "chat.stream",
  "data": {
    "message": "给我讲个故事"
  }
}
```

**流式响应：**

```json
{
  "type": "stream",
  "action": "chat.stream",
  "chunk_index": 0,
  "data": {
    "content": "从前"
  },
  "is_final": false
}
```

---

## 记忆模块 (memory.*)

### memory.list - 列出记忆

获取已存储的记忆列表。

**请求：**

```json
{
  "action": "memory.list",
  "data": {
    "limit": 10,
    "offset": 0
  }
}
```

**响应：**

```json
{
  "type": "response",
  "action": "memory.list",
  "data": {
    "items": [
      {
        "id": "mem-001",
        "content": "用户喜欢蓝色",
        "timestamp": 1700000000
      }
    ],
    "total": 1
  }
}
```

### memory.create - 创建记忆

保存新的记忆。

**请求：**

```json
{
  "action": "memory.create",
  "data": {
    "content": "用户喜欢听古典音乐",
    "metadata": {
      "source": "chat"
    }
  }
}
```

### memory.search - 搜索记忆

根据关键词搜索记忆。

**请求：**

```json
{
  "action": "memory.search",
  "data": {
    "query": "音乐",
    "limit": 5
  }
}
```

### memory.delete - 删除记忆

删除指定记忆。

**请求：**

```json
{
  "action": "memory.delete",
  "data": {
    "id": "mem-001"
  }
}
```

---

## 工具模块 (tools.*)

### tools.list - 列出可用工具

获取所有可用的工具列表。

**请求：**

```json
{
  "action": "tools.list",
  "data": {}
}
```

**响应：**

```json
{
  "type": "response",
  "action": "tools.list",
  "data": {
    "tools": [
      {
        "name": "web_search",
        "description": "搜索互联网",
        "parameters": {
          "query": "string"
        }
      }
    ]
  }
}
```

### tools.call - 调用工具

执行指定的工具。

**请求：**

```json
{
  "action": "tools.call",
  "data": {
    "name": "web_search",
    "parameters": {
      "query": "Python 教程"
    }
  }
}
```

---

## 音频模块

### asr.recognize - 语音识别

将音频数据识别为文本。

**请求：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| audio | string | 是 | Base64 编码的音频数据 |
| language | string | 否 | 语言代码 (auto/zh/en/yue/ja/ko) |

```json
{
  "action": "asr.recognize",
  "data": {
    "audio": "base64-encoded-audio-data",
    "language": "auto"
  }
}
```

**响应：**

```json
{
  "type": "response",
  "action": "asr.recognize",
  "data": {
    "text": "你好，这是语音识别结果",
    "language": "zh",
    "confidence": 0.95
  }
}
```

### tts.synthesize - 语音合成

将文本转换为语音。

> **重要说明**: F5-TTS 是零样本语音克隆模型，需要提供参考音频和对应的参考文本才能合成语音。参考音频用于克隆音色，参考文本是参考音频的转录内容。

**请求：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| text | string | 是 | 要合成语音的文本 |
| ref_audio | string | 是 | Base64 编码的参考音频 (WAV 格式) |
| ref_text | string | 是 | 参考音频对应的文本转录 |
| model_type | string | 否 | 模型类型 (F5-TTS/E2-TTS) |
| speed | float | 否 | 语速 (默认 1.0) |

```json
{
  "action": "tts.synthesize",
  "data": {
    "text": "你好，欢迎使用语音合成服务",
    "ref_audio": "base64-encoded-ref-audio",
    "ref_text": "这是参考音频的文本内容，用于音色克隆"
  }
}
```

**响应：**

```json
{
  "type": "response",
  "action": "tts.synthesize",
  "data": {
    "audio_data": "base64-encoded-audio",
    "format": "wav"
  }
}
```

### tts.synthesize_stream - 流式语音合成

流式输出语音，支持双流式（同时返回文本和音频）。

> **重要说明**: 同样需要提供参考音频和参考文本。

**请求：**

```json
{
  "action": "tts.synthesize_stream",
  "data": {
    "text": "第一句话。第二句话。第三句话。",
    "ref_audio": "base64-encoded-ref-audio",
    "ref_text": "这是参考音频的文本内容"
  }
}
```

**流式响应：**

```json
{
  "type": "stream",
  "action": "tts.synthesize_stream",
  "chunk_index": 0,
  "data": {
    "text_segment": "第一句话。",
    "audio_data": "base64-encoded-audio-segment-1"
  },
  "is_final": false
}
```

```json
{
  "type": "stream",
  "action": "tts.synthesize_stream",
  "chunk_index": 1,
  "data": {
    "text_segment": "第二句话。",
    "audio_data": "base64-encoded-audio-segment-2"
  },
  "is_final": false
}
```

```json
{
  "type": "stream",
  "action": "tts.synthesize_stream",
  "chunk_index": 2,
  "data": {
    "text_segment": "第三句话。",
    "audio_data": "base64-encoded-audio-segment-3"
  },
  "is_final": true
}
```

---

## 系统模块 (system.*)

### system.health - 健康检查

检查各服务健康状态。

**请求：**

```json
{
  "action": "system.health",
  "data": {}
}
```

**响应：**

```json
{
  "type": "response",
  "action": "system.health",
  "data": {
    "gateway": "healthy",
    "cxhms": "healthy",
    "asr": "healthy",
    "tts": "healthy"
  }
}
```

### system.status - 系统状态

获取详细系统状态。

**请求：**

```json
{
  "action": "system.status",
  "data": {}
}
```

### system.info - 系统信息

获取系统信息。

**请求：**

```json
{
  "action": "system.info",
  "data": {}
}
```

---

## 配置模块 (config.*)

### config.get - 获取配置

获取当前配置。

**请求：**

```json
{
  "action": "config.get",
  "data": {}
}
```

### config.set - 设置配置

更新配置项。

**请求：**

```json
{
  "action": "config.set",
  "data": {
    "key": "tts.speed",
    "value": 1.2
  }
}
```

---

## 指标模块 (metrics.*)

### metrics.get - 获取指标

获取系统指标。

**请求：**

```json
{
  "action": "metrics.get",
  "data": {}
}
```

**响应：**

```json
{
  "type": "response",
  "action": "metrics.get",
  "data": {
    "connections": 5,
    "requests_total": 100,
    "requests_per_minute": 10,
    "uptime_seconds": 3600
  }
}
```

---

## 插件模块 (plugin.*)

### plugin.list - 列出插件

获取已注册的插件列表。

**请求：**

```json
{
  "action": "plugin.list",
  "data": {}
}
```

### plugin.register - 注册插件

注册新插件。

**请求：**

```json
{
  "action": "plugin.register",
  "data": {
    "name": "my_plugin",
    "version": "1.0.0",
    "capabilities": ["chat", "tools"]
  }
}
```

---

## 心跳机制

### Ping/Pong

客户端应定期发送心跳以保持连接。

**Ping：**

```json
{
  "type": "ping",
  "timestamp": 1700000000.123
}
```

**Pong：**

```json
{
  "type": "pong",
  "timestamp": 1700000000.123
}
```

---

## 错误代码

| 错误码 | 说明 |
|--------|------|
| INVALID_REQUEST | 请求格式错误 |
| MISSING_PARAMETER | 缺少必要参数 |
| SERVICE_UNAVAILABLE | 服务不可用 |
| ASR_ERROR | 语音识别错误 |
| TTS_ERROR | 语音合成错误 |
| CXHMS_ERROR | CXHMS 后端错误 |
| TIMEOUT | 请求超时 |
| INTERNAL_ERROR | 内部错误 |
