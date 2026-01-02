# SenseVoice API 文档

## 📖 概述

SenseVoice API 是一个基于 FastAPI 的语音识别服务，支持多语言语音识别、语音情感识别和音频事件检测。

- **模型**: iic/SenseVoiceSmall
- **框架**: FastAPI + PyTorch
- **特性**: 多输入方式、批量处理、异步执行

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 启动服务

```bash
# CPU 模式
export SENSEVOICE_DEVICE=cpu
python api.py

# GPU 模式
export SENSEVOICE_DEVICE=cuda:0
python api.py

# 自定义配置
export SENSEVOICE_HOST=0.0.0.0
export SENSEVOICE_PORT=8080
export SENSEVOICE_WORKERS=4
export SENSEVOICE_LOG_LEVEL=INFO
python api.py
```

### 3. 访问服务

- **API 文档**: http://localhost:50000/docs
- **健康检查**: http://localhost:50000/health
- **主页**: http://localhost:50000/

---

## 📡 API 端点

### 基础信息

#### GET /

返回服务主页。

**响应示例** (HTML):
```html
<!DOCTYPE html>
<html>
    <head>
        <meta charset=utf-8>
        <title>SenseVoice API</title>
    </head>
    <body>
        <h1>🎤 SenseVoice API Service</h1>
    </body>
</html>
```

---

#### GET /health

服务健康检查。

**响应参数**:

| 参数 | 类型 | 描述 |
|------|------|------|
| status | string | 服务状态: "healthy" / "unhealthy" |
| device | string | 设备信息 (如 "cuda:0", "cpu") |
| model_dir | string | 模型目录 |
| version | string | API 版本 |
| uptime_seconds | float | 服务运行时间(秒) |

**响应示例** (200 OK):
```json
{
    "status": "healthy",
    "device": "cuda:0",
    "model_dir": "iic/SenseVoiceSmall",
    "version": "1.0.0",
    "uptime_seconds": 123.456
}
```

---

#### GET /api/v1/languages

获取支持的语音列表。

**响应示例** (200 OK):
```json
{
    "languages": [
        {"code": "auto", "name": "Auto Detect"},
        {"code": "zh", "name": "Chinese (Mandarin)"},
        {"code": "en", "name": "English"},
        {"code": "yue", "name": "Cantonese"},
        {"code": "ja", "name": "Japanese"},
        {"code": "ko", "name": "Korean"},
        {"code": "nospeech", "name": "No Speech"}
    ]
}
```

---

#### GET /api/v1/tasks

获取支持的任务类型。

**响应示例** (200 OK):
```json
{
    "tasks": [
        {"code": "asr", "name": "Speech Recognition"},
        {"code": "rich", "name": "Rich Transcription (ASR + SER + AED)"}
    ]
}
```

---

### 语音识别

#### POST /api/v1/asr

**文件上传方式** - 将音频文件上传进行语音识别。

**请求参数** (multipart/form-data):

| 参数 | 类型 | 必填 | 描述 |
|------|------|------|------|
| file | File | ✅ | 音频文件 (wav, mp3, flac, m4a 等) |
| language | Form | ❌ | 语音: auto, zh, en, yue, ja, ko, nospeech (默认: auto) |
| use_itn | Form | ❌ | 是否使用文本规整化 (默认: true) |
| task | Form | ❌ | 任务类型: asr, rich (默认: rich) |

**请求示例**:
```bash
# curl
curl -X POST "http://localhost:50000/api/v1/asr" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@audio.mp3" \
  -F "language=auto" \
  -F "use_itn=true"
```

```python
# Python requests
import requests

url = "http://localhost:50000/api/v1/asr"
files = {"file": open("audio.mp3", "rb")}
data = {
    "language": "auto",
    "use_itn": "true"
}

response = requests.post(url, files=files, data=data)
print(response.json())
```

**响应参数**:

| 字段 | 类型 | 描述 |
|------|------|------|
| task_id | string | 任务 ID |
| results | array | 识别结果列表 |
| timestamp | string | 时间戳 |
| model_info | object | 模型信息 |

**results 字段详情**:

| 字段 | 类型 | 描述 |
|------|------|------|
| key | string | 音频标识 |
| raw_text | string | 原始识别文本 |
| text | string | 处理后的文本 (带标点和 ITN) |
| clean_text | string | 清洗后的文本 (不含标签) |
| language | string | 识别出的语言 |
| emotion | string | 情感标签 |
| event | string | 事件标签 |

**响应示例** (200 OK):
```json
{
    "task_id": "550e8400-e29b-41d4-a716-446655440000",
    "results": [
        {
            "key": "audio_0",
            "raw_text": "<|zh|><|NEUTRAL|><|Speech|><|withitn|>你好世界",
            "text": "你好世界。",
            "clean_text": "你好世界",
            "language": "zh",
            "emotion": "NEUTRAL",
            "event": "Speech"
        }
    ],
    "timestamp": "2024-01-01T12:00:00.000Z",
    "model_info": {
        "model": "iic/SenseVoiceSmall",
        "device": "cuda:0"
    }
}
```

**错误响应** (400 Bad Request):
```json
{
    "detail": "Failed to process audio file"
}
```

---

#### POST /api/v1/asr/json

**JSON 方式** - 通过 URL 或 Base64 编码传输音频。

**请求参数** (application/json):

| 字段 | 类型 | 必填 | 描述 |
|------|------|------|------|
| audio | object | ✅ | 音频输入 |
| audio.url | string | ❌ | 音频 URL (与 audio_base64 二选一) |
| audio.audio_base64 | string | ❌ | Base64 编码的音频 (与 url 二选一) |
| language | string | ❌ | 语音: auto, zh, en, yue, ja, ko, nospeech (默认: auto) |
| use_itn | boolean | ❌ | 是否使用文本规整化 (默认: true) |
| task | string | ❌ | 任务类型: asr, rich (默认: rich) |

**请求示例 - URL 方式**:
```bash
curl -X POST "http://localhost:50000/api/v1/asr/json" \
  -H "Content-Type: application/json" \
  -d '{
    "audio": {
      "url": "https://example.com/audio.mp3"
    },
    "language": "auto",
    "use_itn": true
  }'
```

```python
import requests

url = "http://localhost:50000/api/v1/asr/json"
data = {
    "audio": {
        "url": "https://example.com/audio.mp3"
    },
    "language": "auto",
    "use_itn": True
}

response = requests.post(url, json=data)
print(response.json())
```

**请求示例 - Base64 方式**:
```bash
curl -X POST "http://localhost:50000/api/v1/asr/json" \
  -H "Content-Type: application/json" \
  -d '{
    "audio": {
      "audio_base64": "UklGRiQAAABXQVZFZm10..."
    },
    "language": "zh",
    "use_itn": true
  }'
```

```python
import base64
import requests

with open("audio.mp3", "rb") as f:
    audio_base64 = base64.b64encode(f.read()).decode()

url = "http://localhost:50000/api/v1/asr/json"
data = {
    "audio": {
        "audio_base64": audio_base64
    },
    "language": "zh",
    "use_itn": True
}

response = requests.post(url, json=data)
print(response.json())
```

**响应**: 同 `/api/v1/asr`

---

### 批量处理

#### POST /api/v1/batch

**批量语音识别** - 同时处理多个音频文件。

**请求参数** (multipart/form-data):

| 参数 | 类型 | 必填 | 描述 |
|------|------|------|------|
| files | List[File] | ✅ | 音频文件列表 (最多 50 个) |
| language | Form | ❌ | 语音: auto, zh, en, yue, ja, ko, nospeech (默认: auto) |
| use_itn | Form | ❌ | 是否使用文本规整化 (默认: true) |

**请求示例**:
```bash
curl -X POST "http://localhost:50000/api/v1/batch" \
  -H "Content-Type: multipart/form-data" \
  -F "files=@audio1.mp3" \
  -F "files=@audio2.mp3" \
  -F "files=@audio3.mp3" \
  -F "language=auto"
```

```python
import requests

url = "http://localhost:50000/api/v1/batch"
files = [
    ("files", ("audio1.mp3", open("audio1.mp3", "rb"), "audio/mpeg")),
    ("files", ("audio2.mp3", open("audio2.mp3", "rb"), "audio/mpeg")),
    ("files", ("audio3.mp3", open("audio3.mp3", "rb"), "audio/mpeg")),
]
data = {"language": "auto", "use_itn": "true"}

response = requests.post(url, files=files, data=data)
print(response.json())
```

**响应参数**:

| 字段 | 类型 | 描述 |
|------|------|------|
| task_id | string | 任务 ID |
| total_files | int | 总文件数 |
| successful | int | 成功处理数 |
| failed | int | 处理失败数 |
| results | array | 处理结果列表 |
| timestamp | string | 时间戳 |

**响应示例** (200 OK):
```json
{
    "task_id": "550e8400-e29b-41d4-a716-446655440000",
    "total_files": 3,
    "successful": 2,
    "failed": 1,
    "results": [
        {
            "key": "audio_0",
            "raw_text": "<|zh|><|NEUTRAL|><|Speech|><|withitn|>你好",
            "text": "你好。",
            "clean_text": "你好",
            "language": "zh",
            "emotion": "NEUTRAL",
            "event": "Speech"
        },
        {
            "key": "audio_1",
            "raw_text": "<|en|><|HAPPY|><|Speech|><|withitn|>Hello World",
            "text": "Hello world.",
            "clean_text": "Hello World",
            "language": "en",
            "emotion": "HAPPY",
            "event": "Speech"
        },
        {
            "key": "audio2.mp3",
            "error": "Failed to process audio file"
        }
    ],
    "timestamp": "2024-01-01T12:00:00.000Z"
}
```

---

## 🔧 配置选项

### 环境变量

| 环境变量 | 默认值 | 描述 |
|---------|--------|------|
| SENSEVOICE_DEVICE | cuda:0 | 运行设备 (cuda:0, cuda:1, cpu) |
| SENSEVOICE_HOST | 0.0.0.0 | 服务绑定地址 |
| SENSEVOICE_PORT | 50000 | 服务端口 |
| SENSEVOICE_WORKERS | 1 | 工作进程数 |
| SENSEVOICE_LOG_LEVEL | INFO | 日志级别 (DEBUG, INFO, WARNING, ERROR) |
| SENSEVOICE_MODEL_DIR | iic/SenseVoiceSmall | 模型目录 |
| SENSEVOICE_ENABLE_CORS | true | 启用 CORS |
| SENSEVOICE_MAX_CONCURRENT | 10 | 最大并发请求数 |
| SENSEVOICE_TIMEOUT | 300 | 请求超时时间(秒) |

### 示例

```bash
# 生产环境配置
export SENSEVOICE_DEVICE=cuda:0
export SENSEVOICE_PORT=8080
export SENSEVOICE_WORKERS=4
export SENSEVOICE_LOG_LEVEL=WARNING
export SENSEVOICE_TIMEOUT=300
python api.py
```

---

## 📊 响应代码

| 状态码 | 描述 |
|--------|------|
| 200 | 成功 |
| 400 | 请求参数错误 |
| 404 | 资源不存在 |
| 422 | 参数验证错误 |
| 500 | 服务器内部错误 |

---

## 🎯 使用场景示例

### 1. 实时语音识别 (Web 应用)

```python
import requests
import streamlit as st

st.title("语音识别 Demo")

audio_file = st.file_uploader("上传音频", type=['mp3', 'wav', 'm4a'])

if audio_file:
    st.audio(audio_file)
    
    if st.button("开始识别"):
        files = {"file": audio_file}
        data = {"language": "auto", "use_itn": "true"}
        
        with st.spinner("识别中..."):
            response = requests.post(
                "http://localhost:50000/api/v1/asr",
                files=files,
                data=data
            )
            
            if response.status_code == 200:
                result = response.json()
                st.success("识别结果:")
                st.write(result["results"][0]["text"])
            else:
                st.error("识别失败")
```

### 2. 批量处理 (离线任务)

```python
import os
import requests
from pathlib import Path

def batch_recognize(audio_dir, output_file):
    audio_files = list(Path(audio_dir).glob("*.wav"))
    
    files = []
    for audio_file in audio_files:
        files.append(
            ("files", (audio_file.name, open(audio_file, "rb"), "audio/wav"))
        )
    
    data = {"language": "auto", "use_itn": "true"}
    
    response = requests.post(
        "http://localhost:50000/api/v1/batch",
        files=files,
        data=data
    )
    
    if response.status_code == 200:
        result = response.json()
        
        # 保存结果
        import json
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        
        print(f"处理完成: {result['successful']}/{result['total_files']}")
    else:
        print(f"请求失败: {response.status_code}")

# 使用
batch_recognize("/path/to/audio", "results.json")
```

### 3. API 集成 (JavaScript)

```javascript
// 浏览器环境
async function recognizeAudio(file) {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('language', 'auto');
    formData.append('use_itn', 'true');

    const response = await fetch('http://localhost:50000/api/v1/asr', {
        method: 'POST',
        body: formData
    });

    if (!response.ok) {
        throw new Error('识别失败');
    }

    return await response.json();
}

// Node.js 环境
const fetch = require('node-fetch');
const FormData = require('form-data');
const fs = require('fs');

async function recognizeAudio(filePath) {
    const formData = new FormData();
    formData.append('file', fs.createReadStream(filePath));

    const response = await fetch('http://localhost:50000/api/v1/asr', {
        method: 'POST',
        body: formData
    });

    return await response.json();
}
```

---

## 🐳 Docker 部署

### Dockerfile

```dockerfile
FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 50000

ENV SENSEVOICE_DEVICE=cuda:0

CMD ["python", "api.py"]
```

### 构建和运行

```bash
# 构建镜像
docker build -t sensevoice-api .

# 运行 (GPU)
docker run --gpus all -p 50000:50000 sensevoice-api

# 运行 (CPU)
docker run -e SENSEVOICE_DEVICE=cpu -p 50000:50000 sensevoice-api
```

### Docker Compose

```yaml
version: '3.8'

services:
  sensevoice-api:
    build: .
    ports:
      - "50000:50000"
    environment:
      - SENSEVOICE_DEVICE=cuda:0
      - SENSEVOICE_WORKERS=4
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
```

---

## ⚠️ 注意事项

1. **音频格式**: 支持 wav, mp3, flac, m4a, ogg 等常见格式
2. **音频采样率**: 自动转换到 16kHz
3. **音频长度**: 建议单文件不超过 30 秒，长音频会自动分段
4. **模型加载**: 首次启动需要下载模型 (约 200MB)
5. **GPU 内存**: 约需 2GB GPU 内存
6. **并发限制**: 默认支持 10 个并发请求

---

## 📝 日志查看

```bash
# 实时日志
tail -f nohup.out

# 或使用系统日志
journalctl -u sensevoice -f
```

---

## 🤝 常见问题

### Q1: 如何提高识别准确率?
- 使用高质量的音频 (16kHz 采样率)
- 尽量减少背景噪音
- 说话时保持适中的语速和音量

### Q2: 支持哪些语言?
支持 6 种语言的自动检测和识别:
- 中文 (zh)
- 英文 (en)
- 粤语 (yue)
- 日语 (ja)
- 韩语 (ko)
- 无语音 (nospeech)

### Q3: 如何处理长音频?
系统会自动使用 VAD (语音活动检测) 对长音频进行分段处理，每段最多 30 秒。

### Q4: 响应时间过长怎么办?
- 使用 GPU 加速
- 减少音频文件大小
- 降低并发请求数量
- 调整 `merge_vad` 参数

---

## 📞 技术支持

- **项目地址**: https://github.com/FunAudioLLM/SenseVoice
- **文档**: 查看 `/docs` 获取交互式 API 文档
- **问题反馈**: GitHub Issues

---

**最后更新**: 2024年1月
