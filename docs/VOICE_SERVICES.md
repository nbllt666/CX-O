# 语音服务文档

## 概述

CX-O 系统集成了语音识别（ASR）和语音合成（TTS）服务，通过 HTTP API 提供语音处理能力。

## ASR 服务（SenseVoice）

**服务端口**: 8001

### 功能

- 多语言语音识别（中文、英文、粤语、日语、韩语等）
- 实时流式识别
- 情感识别（SER）
- 事件检测（BGM、笑声、掌声等）

### API 调用示例

```python
import httpx

async def recognize(audio_data: bytes):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://127.0.0.1:8001/recognize",
            files={"audio": audio_data},
            data={"language": "auto"}
        )
        return response.json()
```

### WebSocket Action

| Action | 说明 |
|--------|------|
| asr.recognize | 语音识别 |
| asr.recognize_base64 | Base64 编码音频识别 |
| asr.stream | 实时 ASR 流 |

## TTS 服务（F5-TTS）

**服务端口**: 8002

### 功能

- 零样本语音克隆
- 实时流式合成
- 情感 TTS
- 音效插入

### API 调用示例

```python
import httpx

async def synthesize(text: str, ref_audio: str, ref_text: str):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://127.0.0.1:8002/synthesize",
            json={
                "text": text,
                "ref_audio": ref_audio,
                "ref_text": ref_text
            }
        )
        return response.content
```

### 情感 TTS

```python
text_with_emotion = "[emotion:happy]今天真开心！[/emotion][emotion:sad]不过有点难过。[/emotion]"
```

### 音效

```python
text_with_sound = "大家好。[sound:applause]欢迎来到直播间！"
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

## 备用语音服务（CosyVoice）

**服务端口**: 8090

CosyVoice 是备用的语音合成服务，提供额外的音色选择。

### 启动

```batch
cd CosyVoice
python webui.py
```

## 故障排除

### ASR 识别失败

1. 检查音频格式是否为 16kHz WAV
2. 检查服务是否正常运行
3. 查看日志中的错误信息

### TTS 合成失败

1. 确认参考音频文件存在
2. 检查参考文本是否与参考音频匹配
3. 验证 TTS 模型是否正确加载

### 模型加载失败

1. 确保有足够的 GPU 显存
2. 检查模型文件是否完整下载
3. 验证 CUDA 和 cuDNN 版本
