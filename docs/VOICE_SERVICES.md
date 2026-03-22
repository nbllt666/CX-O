# 语音服务文档

## 概述

CX-O 系统集成了两个语音服务：
- **SenseVoice**：语音识别（ASR）
- **F5-TTS**：语音合成（TTS）

## SenseVoice（ASR 服务）

### 概述

SenseVoice 是阿里开发的语音识别服务，提供多语言语音转文字功能，支持情感识别。

**端口**：8001

**位置**：`SenseVoice/api.py`

### 模型特性

- **SenseVoiceSmall**：轻量级模型
- 支持语言：中文、英文、粤语、日语、韩语等
- 支持语音情感识别（SER）
- ITN（逆文本正规化）处理

### API 端点

#### GET /

根端点，返回服务状态。

**响应**：
```json
{
  "message": "SenseVoice API",
  "status": "running",
  "model_available": true
}
```

#### GET /health

健康检查。

**响应**：
```json
{
  "status": "healthy",
  "model_loaded": true
}
```

#### POST /asr

语音识别。

**请求（JSON）**：
```json
{
  "audio": {
    "url": "http://example.com/audio.wav",
    "audio_base64": "base64编码的音频"
  },
  "language": "auto",
  "use_itn": true,
  "task": "rich"
}
```

**响应**：
```json
{
  "task_id": "uuid",
  "results": [
    {
      "text": "识别文字",
      "language": "zh",
      "emotion": "happy",
      "start": 0.0,
      "end": 2.5
    }
  ],
  "timestamp": "2024-01-15T10:00:00"
}
```

#### POST /batch

批量语音识别。

**请求**：
```json
{
  "audios": [
    {"audio_base64": "base64编码1"},
    {"audio_base64": "base64编码2"}
  ],
  "language": "auto"
}
```

### 音频格式要求

- 采样率：16kHz
- 格式：WAV/PCM
- 编码：16-bit

### 配置

**文件**：`SenseVoice/config.py`

```python
class ASRConfig:
    model_name: str = "SenseVoiceSmall"
    device: str = "cuda"  # cuda 或 cpu
    log_level: str = "INFO"
    workers: int = 4
```

## F5-TTS（TTS 服务）

### 概述

F5-TTS 是零样本语音克隆模型，可以通过参考音频和参考文本来合成具有相似音色的语音。

**端口**：8002

**位置**：`F5-TTS/webapi.py`

### 模型特性

- **零样本克隆**：无需额外训练
- **参考音频 + 参考文本** → 克隆音色
- 支持 F5-TTS 和 E2-TTS 两种模型
- 流式输出支持
- 交叉淡入淡出

### API 端点

#### GET /

根端点。

**响应**：
```json
{
  "message": "Welcome to F5-TTS Web API",
  "status": "running",
  "model_available": true
}
```

#### GET /health

健康检查。

**响应**：
```json
{
  "status": "healthy",
  "model_loaded": true
}
```

#### POST /tts/

语音合成。

**请求（Form Data）**：
| 参数 | 类型 | 描述 |
|------|------|------|
| ref_audio | File | 参考音频文件 |
| ref_text | string | 参考音频对应的文本 |
| gen_text | string | 要合成的文本 |
| tts_model | string | F5-TTS 或 E2-TTS |
| speed | float | 语速（默认 1.0） |
| cross_fade_duration | float | 交叉淡入淡出时长 |
| nfe_step | int | 推理步数 |
| cfg_strength | int | CFG 强度 |
| remove_silence | bool | 是否去静音 |

**响应**：音频文件流（WAV 格式）

#### POST /tts_stream/

流式语音合成。

**请求**：同 `/tts/`

**响应**：SSE 流式响应

### 使用示例

```python
import httpx
import base64

async def synthesize_speech():
    with open("ref_audio.wav", "rb") as f:
        ref_audio = base64.b64encode(f.read()).decode()

    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://127.0.0.1:8002/tts/",
            files={
                "ref_audio": open("reference.wav", "rb"),
            },
            data={
                "ref_text": "这是一段参考文本",
                "gen_text": "要合成的文本内容",
                "speed": 1.0
            }
        )

    return response.content
```

## CosyVoice（备用 TTS）

### 概述

CosyVoice 是备用的语音合成服务，支持情感语音合成。

**位置**：`CosyVoice/`

### 特性

- 多音色支持
- 情感控制
- 流式合成

## 音频处理流程

### 语音识别流程

```
用户音频（PCM 16kHz）
       │
       ▼
 Gateway ASR Client
       │
       ▼
 SenseVoice API (/asr)
       │
       ├──► 文本结果
       │
       └──► 情感标签（可选）
```

### 语音合成流程

```
LLM 生成的文本
       │
       ▼
 Gateway TTS Client
       │
       ├──► 加载参考音频
       │
       ▼
 F5-TTS API (/tts/)
       │
       ├──► 流式音频块
       │
       ▼
 交叉淡入淡出处理
       │
       ▼
 返回给客户端
```

## 情感 TTS

### IndexTTS

IndexTTS 是支持情感控制的 TTS 服务。

**位置**：`cx-o-gateway/services/index_tts_client.py`

**支持的情感**：
- happy（开心）
- sad（悲伤）
- angry（生气）
- surprised（惊讶）
- tender（温柔）
- fearful（害怕）
- disgusted（厌恶）
- neutral（中性）

### 情感生成

通过参考音频生成各情感的音频样本：

```json
{
  "ref_audio": "path/to/ref.wav",
  "ref_text": "参考文本",
  "emotions": [
    {"type": "happy", "intensity": 0.5},
    {"type": "sad", "intensity": 0.5}
  ]
}
```

## VAD（语音活动检测）

### 概述

VAD 用于检测用户是否在说话，用于打断和实时对话场景。

### 支持的模式

| 模式 | 描述 |
|------|------|
| webrtc | WebRTC VAD，默认模式 |
| energy | 能量检测，简单高效 |
| silero | Silero VAD，精度高 |

### 配置

**文件**：`CXHMS/config/vad.yaml`

```yaml
vad:
  mode: "webrtc"
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

### VAD 状态

| 状态 | 描述 |
|------|------|
| speech_start | 检测到语音开始 |
| speech_end | 检测到语音结束 |

## 全双工打断

### 打断流程

```
场景 1：用户打断 Agent TTS
━━━━━━━━━━━━━━━━━━━━━━━━━━━
Agent TTS 播放中 ──► 用户说话 ──► VAD 检测
                                    │
                    ┌───────────────┴───────────────┐
                    ▼                               ▼
              需要打断                        不需要打断
              停止 TTS                       继续播放
              生成新回复

场景 2：Agent 打断用户说话
━━━━━━━━━━━━━━━━━━━━━━━━━━━
用户说话中 ──► 实时 ASR 流 ──► LLM 实时判断
                                      │
                    ┌───────────────┴───────────────┐
                    ▼                               ▼
            可以插话                        用户还在说
            打断用户音频                     继续监听
            开始 TTS 回复
```

### 打断条件

- **用户打断 Agent**：
  - VAD 检测到语音开始
  - ASR 识别出文字
  - LLM 判断需要打断

- **Agent 打断用户**：
  - 实时 ASR 流识别中
  - LLM 判断可以插话
  - TTS 音频已准备好
