# CX-O 微服务架构

基于 CXHMS + SenseVoice (ASR) + F5-TTS (TTS) 的语音对话微服务系统。

## 架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                        CX-O Frontend                            │
│                     (React + TypeScript)                        │
│                      http://127.0.0.1:5173                      │
└──────────────────────────┬──────────────────────────────────────┘
                           │ WebSocket
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                      CX-O Gateway                               │
│                   (WebSocket 网关服务)                           │
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

## 服务说明

| 服务 | 端口 | 协议 | 说明 |
|------|------|------|------|
| CX-O Gateway | 8100 | WebSocket | 前端网关，统一入口 |
| CXHMS Backend | 8000 | WebSocket | 后端核心服务 (Chat/Memory/Tools) |
| SenseVoice ASR | 8001 | HTTP | 语音识别服务 |
| F5-TTS | 8002 | HTTP | 语音合成服务 |
| CX-O Frontend | 5173 | HTTP | 管理控制台 |

## 快速开始

### 1. 安装依赖

```batch
# 安装所有依赖 (Python + npm)
d:\CX-O\install-all.bat

# 或仅安装 npm 依赖
d:\CX-O\install-npm.bat
```

### 2. 启动服务

```batch
d:\CX-O\start-all.bat
```

### 3. 访问管理界面

打开浏览器访问: http://127.0.0.1:5173

## 项目结构

```
CX-O/
├── cx-o-gateway/          # WebSocket 网关服务
│   ├── main.py           # 入口文件
│   ├── config.json       # 配置文件
│   ├── gateway/          # 网关核心
│   ├── services/         # 服务客户端
│   ├── handlers/         # 消息处理器
│   └── protocol/         # 协议定义
│
├── cx-o-frontend/        # 前端管理界面
│   ├── src/
│   │   ├── api/          # WebSocket 客户端
│   │   ├── components/   # 组件
│   │   ├── pages/        # 页面
│   │   └── stores/       # 状态管理
│   └── package.json
│
├── CXHMS/               # 后端核心服务 (不修改)
│   └── backend/
│
├── SenseVoice/          # 语音识别服务 (不修改)
│   └── api.py
│
├── F5-TTS/              # 语音合成服务
│   └── webapi.py
│
├── Miniconda3/          # 内置 Python 环境
│
├── start-all.bat        # 启动所有服务
├── stop-all.bat         # 停止所有服务
├── install-all.bat      # 安装所有依赖
├── install-npm.bat      # 安装 npm 依赖
├── requirements.txt     # Python 依赖列表
└── .gitignore          # Git 忽略规则
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

### 消息类型

| 类型 | 说明 |
|------|------|
| request | 请求消息 |
| response | 响应消息 |
| stream | 流式消息 |
| error | 错误消息 |
| ping | 心跳 |
| pong | 心跳响应 |

### 错误响应

```json
{
  "type": "error",
  "request_id": "uuid-string",
  "action": "chat.message",
  "code": "ERROR_CODE",
  "message": "错误描述"
}
```

## 功能模块

### 1. 聊天功能 (chat.*)

| Action | 说明 |
|--------|------|
| chat.message | 发送消息 |
| chat.voice | 语音对话 |
| chat.history | 获取历史 |
| chat.clear | 清除会话 |

### 2. 记忆功能 (memory.*)

| Action | 说明 |
|--------|------|
| memory.save | 保存记忆 |
| memory.search | 搜索记忆 |
| memory.list | 列出记忆 |
| memory.delete | 删除记忆 |

### 3. 工具功能 (tools.*)

| Action | 说明 |
|--------|------|
| tools.list | 列出工具 |
| tools.call | 调用工具 |
| tools.result | 工具结果 |

### 4. 音频功能 (audio.* / asr.* / tts.*)

| Action | 说明 |
|--------|------|
| asr.recognize | 语音识别 |
| tts.synthesize | 语音合成 |
| tts.synthesize_stream | 流式语音合成 |

### 5. 系统功能 (system.*)

| Action | 说明 |
|--------|------|
| system.health | 健康检查 |
| system.metrics | 系统指标 |
| system.config | 系统配置 |

## 配置说明

### Gateway 配置 (cx-o-gateway/config.json)

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
      "url": "http://127.0.0.1:8002",
      "ref_audio_path": "",
      "ref_text": ""
    }
  }
}
```

## 常见问题

### 1. 启动失败

- 检查端口是否被占用: `netstat -ano | findstr "8000 8001 8002 8100 5173"`
- 确认 Miniconda3 环境存在

### 2. 模型加载失败

- SenseVoice/F5-TTS 首次启动会下载模型，请确保网络连接
- 可手动下载模型到本地

### 3. TTS 语音合成使用说明

F5-TTS 是零样本语音克隆模型，使用时需要提供：
- **参考音频 (ref_audio)**: 用于克隆音色的音频文件 (WAV 格式)
- **参考文本 (ref_text)**: 参考音频对应的文本转录

使用方式：
1. 在前端测试页面上传参考音频并输入参考文本
2. 或在 `config.json` 中配置默认的 `ref_audio_path` 和 `ref_text`

### 4. 前端连接失败

- 确认 Gateway 服务已启动 (端口 8100)
- 检查浏览器控制台错误信息

## 技术栈

- **后端**: Python, FastAPI, WebSocket, httpx
- **前端**: React, TypeScript, Ant Design, Zustand
- **语音**: SenseVoice, F5-TTS
- **向量库**: ChromaDB, Milvus, Qdrant

## License

MIT
