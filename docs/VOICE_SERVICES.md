# 语音服务文档

## 概述

CX-O v4 单体架构集成了语音识别（ASR）和语音合成（TTS）服务，直接在进程内调用模型，无需网络通信开销。

## ASR 服务（SenseVoice）

### 功能

- 多语言语音识别（中文、英文、粤语、日语、韩语等）
- 实时流式识别
- 情感识别（SER）
- 事件检测（BGM、笑声、掌声等）

### 直接调用示例

```python
from server.services.asr import get_asr_service

asr_service = get_asr_service()

# 单次识别
result = await asr_service.recognize(audio_data, language="auto")
print(result["text"])

# 流式识别
async for chunk in asr_service.recognize_stream(audio_chunks, language="auto"):
    print(chunk["text"], end="", flush=True)
```

### 配置

```json
{
  "asr": {
    "model_dir": "SenseVoice",
    "device": "cuda",
    "enabled": true,
    "language": "auto",
    "use_itn": true
  }
}
```

### WebSocket Action

| Action | 说明 |
|--------|------|
| asr.recognize | 语音识别 |
| asr.recognize_base64 | Base64 编码音频识别 |

## TTS 服务（F5-TTS）

### 功能

- 零样本语音克隆
- 实时流式合成
- 情感 TTS
- 音效插入

### 直接调用示例

```python
from server.services.tts import get_tts_service

tts_service = get_tts_service()

# 单次合成
audio_bytes = await tts_service.synthesize(
    text="你好，世界！",
    ref_audio_path="data/voice_refs/default.wav",
    ref_text="你好，我是语音助手。"
)

# 流式合成
async for chunk in tts_service.synthesize_stream(text):
    if chunk["audio_data"]:
        send_audio(chunk["audio_data"])
```

### 情感 TTS

```python
text_with_emotion = "[emotion:happy]今天真开心！[/emotion][emotion:sad]不过有点难过。[/emotion]"

async for chunk in tts_service.synthesize_stream_with_emotions(text_with_emotion):
    if chunk["audio_data"]:
        send_audio(chunk["audio_data"])
```

### 音效

```python
text_with_sound = "大家好。[sound:applause]欢迎来到直播间！"

async for chunk in tts_service.synthesize_stream_with_emotions(text_with_sound):
    if chunk["audio_data"]:
        send_audio(chunk["audio_data"])
```

### 配置

```json
{
  "tts": {
    "model_dir": "F5-TTS",
    "device": "cuda",
    "enabled": true,
    "ref_audio": "data/voice_refs/default.wav",
    "ref_text": "你好，我是语音助手。",
    "speed": 1.0
  }
}
```

### WebSocket Action

| Action | 说明 |
|--------|------|
| tts.synthesize | 语音合成 |
| tts.synthesize_stream | 流式语音合成 |
| emotions.list | 获取支持的情感列表 |
| emotions.parse | 解析情感文本 |
| effects.list | 获取可用的音效列表 |
| effects.parse | 解析音效文本 |

## VAD（语音活动检测）

### 功能

- WebRTC VAD
- Energy VAD
- Silero VAD

### 配置

```yaml
vad:
  mode: "webrtc"
  sample_rate: 16000
  frame_duration_ms: 30
  silence_threshold_ms: 500
  speech_threshold_ms: 300
```

## 全双工打断

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

## 性能优化

### 单体架构优势

| 指标 | 微服务 | 单体 | 改善 |
|------|--------|------|------|
| ASR 延迟 | ~100ms | ~50ms | -50% |
| TTS 延迟 | ~300ms | ~150ms | -50% |
| 总体延迟 | ~800ms | ~400ms | -50% |

### 优化策略

1. **进程内调用**：消除 HTTP/网络开销
2. **模型缓存**：模型只加载一次
3. **流式处理**：边识别边返回，减少首字节延迟
4. **批量推理**：多个请求合并处理

## 故障排除

### ASR 识别失败

1. 检查音频格式是否为 16kHz WAV
2. 检查 `config.json` 中 ASR 配置
3. 查看日志中的错误信息

### TTS 合成失败

1. 确认参考音频文件存在
2. 检查参考文本是否与参考音频匹配
3. 验证 TTS 模型是否正确加载

### 模型加载失败

1. 确保有足够的 GPU 显存
2. 检查模型文件是否完整下载
3. 验证 CUDA 和 cuDNN 版本
