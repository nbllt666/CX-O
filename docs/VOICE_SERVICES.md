# CX-O 语音服务文档

本文档详细描述 CX-O 系统中语音相关服务的架构、配置与使用方式，涵盖 ASR 语音识别、TTS 语音合成、VAD 语音活动检测、全双工打断、情感解析、音效解析、语音工作站及前端音频控制等模块。

---

## 目录

- [1. ASR 语音识别](#1-asr-语音识别)
- [2. TTS 语音合成](#2-tts-语音合成)
- [3. VAD 语音活动检测](#3-vad-语音活动检测)
- [4. 全双工打断](#4-全双工打断)
- [5. 情感解析](#5-情感解析)
- [6. 音效解析](#6-音效解析)
- [7. 语音工作站](#7-语音工作站)
- [8. 前端音频控制](#8-前端音频控制)
- [9. 配置参考](#9-配置参考)
- [10. Orpheus TTS 流式情感语音合成](#10-orpheus-tts-流式情感语音合成)

---

## 1. ASR 语音识别

### 1.1 概述

ASR（Automatic Speech Recognition）服务负责将音频数据转换为文本，支持情感和语音事件检测。系统提供 **embedded** 和 **remote** 两种运行模式，并在 embedded 模式初始化失败时自动降级为 remote 模式。

**核心代码：**
- [asr_service.py](../CX-O-SERVER/server/services/asr_service.py) — 统一 ASR 服务
- [sensevoice_streaming_client.py](../CX-O-SERVER/server/services/sensevoice_streaming_client.py) — 流式 ASR 客户端

### 1.2 运行模式

| 模式 | 说明 | 模型 |
|------|------|------|
| `embedded` | 本地直接调用 SenseVoice 模型推理，无需外部服务 | SenseVoiceSmall |
| `remote` | 通过 HTTP 调用远程 ASR 服务 | 远程服务 |

**自动降级机制：** 当 `embedded` 模式加载模型失败时，系统自动切换到 `remote` 模式，确保服务可用性。降级过程会在日志中记录警告信息。

### 1.3 识别接口

`ASRService` 提供三种识别入口：

```python
from server.services.asr_service import get_asr_service

asr = get_asr_service()

# 方式一：原始字节数据识别
result = await asr.recognize(audio_bytes, language="auto", use_itn=True)

# 方式二：Base64 编码音频识别
result = await asr.recognize_base64(audio_base64, language="auto", use_itn=True)

# 方式三：文件路径识别
result = await asr.recognize_file("/path/to/audio.wav", language="auto", use_itn=True)
```

**返回结构：**

```json
{
  "text": "识别的文本内容",
  "language": "zh",
  "emotion": "HAPPY",
  "event": "Speech"
}
```

**参数说明：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `language` | `str` | `"auto"` | 语言选择，支持 `auto`/`zh`/`en`/`ja`/`ko` 等 |
| `use_itn` | `bool` | `True` | 是否启用逆文本正则化（数字、日期等格式化） |

**检测的情感标签：** `HAPPY`、`SAD`、`ANGRY`、`NEUTRAL`、`FEARFUL`、`DISGUSTED`、`SURPRISED`

**检测的语音事件标签：** `BGM`、`Speech`、`Applause`、`Laughter`、`Cry`、`Sneeze`、`Breath`、`Cough`、`Sing`、`Speech_Noise`

### 1.4 流式 ASR

`SenseVoiceStreamingClient` 支持增量式流式识别，适用于实时语音交互场景。

```python
from server.services.sensevoice_streaming_client import SenseVoiceStreamingClient

client = SenseVoiceStreamingClient(base_url="http://127.0.0.1:8001")

# 流式识别（异步生成器）
async for result in client.recognize_stream(
    audio_chunks=audio_generator,
    language="auto",
    chunk_size=1600,
    hop_size=800,
    look_back=8000
):
    print(result["text"], result["is_final"])

# 单块识别
result = await client.recognize_chunk(
    audio_data=chunk_bytes,
    language="auto",
    offset=0,
    is_final=False
)
```

**流式参数说明：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `chunk_size` | `int` | `1600` | 每次发送的音频块大小（字节） |
| `hop_size` | `int` | `800` | 滑动窗口步长（字节） |
| `look_back` | `int` | `8000` | 回看窗口大小，提供上下文信息 |
| `offset` | `int` | `0` | 当前音频偏移量 |

**流式返回结构：**

```json
{
  "text": "增量识别文本",
  "is_final": false,
  "offset": 800
}
```

### 1.5 音频预处理

ASR 服务内部对输入音频进行自动预处理：

1. 读取音频数据并转换为 `float32` 格式
2. 多声道音频取均值转为单声道
3. 重采样至 16kHz（`TARGET_FS = 16000`）
4. 若 `scipy` 处理失败，回退到 `torchaudio` 处理

### 1.6 配置项

```json
{
  "asr": {
    "mode": "remote",
    "model_dir": "SenseVoiceSmall",
    "device": "cuda",
    "remote_url": "http://127.0.0.1:8001",
    "language": "auto"
  }
}
```

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `mode` | `str` | `"remote"` | 运行模式：`embedded` 或 `remote` |
| `model_dir` | `str` | `"SenseVoiceSmall"` | embedded 模式下的模型目录 |
| `device` | `str` | `"cuda"` | 推理设备：`cuda` 或 `cpu` |
| `remote_url` | `str` | `"http://127.0.0.1:8001"` | remote 模式的服务地址 |
| `language` | `str` | `"auto"` | 默认识别语言 |

**环境变量覆盖：**

| 环境变量 | 对应配置 |
|----------|----------|
| `CXO_ASR_MODE` | `asr.mode` |
| `CXO_ASR_MODEL_DIR` | `asr.model_dir` |
| `CXO_ASR_DEVICE` | `asr.device` |
| `CXO_ASR_REMOTE_URL` | `asr.remote_url` |

---

## 2. TTS 语音合成

### 2.1 概述

TTS（Text-to-Speech）服务负责将文本转换为语音，支持情感语音切换、音效插入、流式合成和 Triton 推理加速。

**核心代码：** [tts_service.py](../CX-O-SERVER/server/services/tts_service.py)

### 2.2 运行模式

| 模式 | 说明 | 模型 |
|------|------|------|
| `embedded` | 本地直接调用 F5-TTS 模型推理 | F5-TTS |
| `remote` | 通过 HTTP 调用远程 TTS 服务 | 远程 F5-TTS 服务 |
| `triton` | 通过 Triton Inference Server 推理加速 | Triton + F5-TTS |
| `orpheus` | 通过 Orpheus TTS Bridge 调用 vLLM 推理 | Orpheus (vLLM + SNAC) |

### 2.3 合成接口

#### 基础合成

```python
from server.services.tts_service import get_tts_service

tts = get_tts_service()

# 基础合成（返回完整音频字节）
audio_data = await tts.synthesize(
    text="你好，世界！",
    ref_audio_path="data/voice_refs/default/ref.wav",
    ref_text="这是参考音频的文本内容。",
    speed=1.0,
    cross_fade_duration=0.15
)
```

**参数说明：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `text` | `str` | 必填 | 待合成文本 |
| `ref_audio_path` | `str` | 配置默认值 | 参考音频文件路径 |
| `ref_text` | `str` | 配置默认值 | 参考音频对应的文本 |
| `ref_audio` | `str` | 无 | Base64 编码的参考音频（优先级高于路径） |
| `speed` | `float` | `1.0` | 语速倍率 |
| `cross_fade_duration` | `float` | `0.15` | 交叉淡入淡出时长（秒） |
| `nfe_step` | `int` | `32` | 推理步数 |
| `cfg_strength` | `int` | `2` | CFG 引导强度 |
| `seed` | `int` | `-1` | 随机种子（-1 为随机） |
| `remove_silence` | `bool` | `False` | 是否移除静音段 |

#### 流式合成

流式合成将文本按句分割，逐句合成并返回，适用于实时对话场景。

```python
async for chunk in tts.synthesize_stream(
    text="你好！今天天气真好。你想聊些什么呢？",
    ref_audio_path="data/voice_refs/default/ref.wav",
    ref_text="这是参考音频的文本内容。",
    on_chunk=lambda text, audio: print(f"收到: {text}")
):
    if chunk["audio_data"]:
        # 播放 chunk["audio_data"]
        pass
    if chunk["is_final"]:
        break
```

**流式返回结构：**

```json
{
  "text_segment": "你好！",
  "audio_data": "<wav bytes>",
  "chunk_index": 0,
  "is_final": false
}
```

#### 情感语音合成

根据文本中的 `[emotion:name]` 标记自动切换参考音频，实现情感语音变化。

```python
audio_data = await tts.synthesize_with_emotions(
    text="[emotion:happy]太好了！[emotion:calm]让我想想。[emotion:excited]出发吧！"
)
```

#### 流式情感语音合成

结合情感切换与流式输出，同时支持音效标记。

```python
async for chunk in tts.synthesize_stream_with_emotions(
    text="[emotion:happy]欢迎来到直播间！[effect:applause][emotion:calm]今天我们来聊聊...",
    on_chunk=lambda text, audio: play_audio(audio)
):
    if chunk.get("is_effect"):
        print(f"音效: {chunk['effect_name']}")
    else:
        print(f"文本: {chunk['text_segment']}, 情感: {chunk.get('emotion')}")
```

**流式情感返回结构：**

```json
{
  "text_segment": "欢迎来到直播间！",
  "audio_data": "<wav bytes>",
  "chunk_index": 0,
  "is_final": false,
  "emotion": "happy",
  "is_effect": false
}
```

### 2.4 文本分句策略

`split_text_by_sentences` 函数负责将长文本按句分割，用于流式合成：

- 按 `。！？.!?` 等标点分句
- 单句最大长度 200 字符，超出则合并到前一句
- 保留标点符号在句末

### 2.5 参考音频解析

TTS 服务支持多种方式指定参考音频，按优先级排列：

1. **请求参数 `ref_audio`**：Base64 编码的音频数据
2. **请求参数 `ref_audio_path`**：音频文件绝对路径
3. **配置文件 `ref_audio_path`**：默认参考音频路径
4. **情感参考音频**：根据情感标记从 `emotion_refs_dir` 加载

参考音频路径解析逻辑：
- 绝对路径直接使用
- 相对路径先尝试当前工作目录
- 再尝试 `voice_refs_dir` 目录

### 2.6 音频拼接

多段音频合成后，`_concatenate_audio` 方法自动拼接：

- 所有段为 WAV 格式时：解析 WAV 头，提取 PCM 数据拼接，重新生成 WAV 头
- 非 WAV 格式：直接字节拼接

### 2.7 配置项

```json
{
  "tts": {
    "mode": "remote",
    "model_dir": "F5TTS_v1_Base",
    "device": "cuda",
    "remote_url": "http://127.0.0.1:5000",
    "ref_audio_path": "",
    "ref_text": "",
    "speed": 1.0,
    "cross_fade_duration": 0.15,
    "emotion_enabled": true,
    "effects_enabled": true,
    "emotion_refs_dir": "data/voice_refs/emotions",
    "transitions_dir": "data/voice_refs/transitions",
    "transition_enabled": true,
    "transition_text": "嗯，"
  }
}
```

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `mode` | `str` | `"remote"` | 运行模式：`embedded`/`remote`/`triton` |
| `model_dir` | `str` | `"F5TTS_v1_Base"` | embedded 模式的模型目录 |
| `device` | `str` | `"cuda"` | 推理设备 |
| `remote_url` | `str` | `"http://127.0.0.1:5000"` | remote 模式的服务地址 |
| `ref_audio_path` | `str` | `""` | 默认参考音频路径 |
| `ref_text` | `str` | `""` | 默认参考音频对应文本 |
| `speed` | `float` | `1.0` | 默认语速 |
| `cross_fade_duration` | `float` | `0.15` | 默认交叉淡入淡出时长 |
| `emotion_enabled` | `bool` | `True` | 是否启用情感语音 |
| `effects_enabled` | `bool` | `True` | 是否启用音效 |
| `emotion_refs_dir` | `str` | `"data/voice_refs/emotions"` | 情感参考音频目录 |
| `transitions_dir` | `str` | `"data/voice_refs/transitions"` | 音效文件目录 |
| `transition_enabled` | `bool` | `True` | 是否启用过渡音效 |
| `transition_text` | `str` | `"嗯，"` | 过渡文本 |

**环境变量覆盖：**

| 环境变量 | 对应配置 |
|----------|----------|
| `CXO_TTS_MODE` | `tts.mode` |
| `CXO_TTS_MODEL_DIR` | `tts.model_dir` |
| `CXO_TTS_DEVICE` | `tts.device` |
| `CXO_TTS_REMOTE_URL` | `tts.remote_url` |

---

## 3. VAD 语音活动检测

### 3.1 概述

VAD（Voice Activity Detection）模块负责检测用户是否正在说话，为打断机制和流式 ASR 提供语音状态判断。

**核心代码：** [vad_processor.py](../CX-O-SERVER/server/services/vad_processor.py)

### 3.2 检测模式

| 模式 | 枚举值 | 说明 | 依赖 |
|------|--------|------|------|
| Energy | `VADMode.ENERGY` | 基于音频能量阈值检测 | 无外部依赖 |
| WebRTC | `VADMode.WEBRTC` | WebRTC VAD 算法，鲁棒性好 | `webrtcvad` |
| Silero | `VADMode.SILERO` | Silero 神经网络 VAD，精度最高 | `torch` |

**自动降级机制：** WebRTC 和 Silero 模式初始化失败时自动降级为 Energy 模式。

### 3.3 VADProcessor 使用

```python
from server.services.vad_processor import get_vad_processor

vad = get_vad_processor()

# 配置
vad.set_config({
    "mode": "webrtc",
    "sample_rate": 16000,
    "frame_duration_ms": 30,
    "energy_threshold": 500,
    "silence_threshold_ms": 500,
    "speech_threshold_ms": 300
})

# 设置回调
vad.set_callbacks(
    on_speech_start=lambda: print("用户开始说话"),
    on_speech_end=lambda: print("用户停止说话")
)

# 处理音频帧
result = vad.process_audio(audio_frame_bytes)
```

**返回结构：**

```json
{
  "is_speaking": true,
  "speech_probability": 0.85,
  "state_changed": true,
  "speech_duration_ms": 1200.5,
  "silence_duration_ms": 0
}
```

**配置参数说明：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `mode` | `str` | `"webrtc"` | VAD 模式：`energy`/`webrtc`/`silero` |
| `sample_rate` | `int` | `16000` | 采样率 |
| `frame_duration_ms` | `int` | `30` | 帧时长（毫秒） |
| `energy_threshold` | `int` | `500` | Energy 模式的能量阈值 |
| `silence_threshold_ms` | `int` | `500` | 静音判定阈值（毫秒） |
| `speech_threshold_ms` | `int` | `300` | 语音起始判定阈值（毫秒） |

### 3.4 回调机制

VADProcessor 支持两个回调函数：

- **`on_speech_start`**：检测到用户开始说话时触发
- **`on_speech_end`**：检测到用户停止说话（静音超过 `silence_threshold_ms`）时触发

### 3.5 AudioStreamProcessor

`AudioStreamProcessor` 是 VAD 与流式 ASR 的集成处理器，协调 VAD 检测、ASR 识别和打断判断：

```python
from server.services.vad_processor import get_audio_stream_processor

processor = get_audio_stream_processor()
processor.set_config({"vad": {"mode": "webrtc"}})
processor.set_asr_client(streaming_client)
processor.set_agent_interrupt(agent_interrupt_module)

# 处理音频块
result = await processor.process_audio_chunk(audio_bytes)
# result 包含 vad、asr、interrupt 三个字段
```

### 3.6 各模式检测原理

#### Energy 模式

计算音频帧的 RMS 能量值，与阈值比较：

```python
energy = sum(sample ** 2 for sample in samples) / len(samples)
is_speech = energy > energy_threshold
```

#### WebRTC VAD 模式

使用 WebRTC VAD 算法，基于信号统计特征判断，对帧大小有严格要求（需为 10/20/30ms 对应的采样数）。

#### Silero VAD 模式

使用 Silero 预训练神经网络模型，输出语音概率值（0~1），阈值为 0.5：

```python
speech_prob = model(audio_tensor, sample_rate)
is_speech = speech_prob > 0.5
```

---

## 4. 全双工打断

### 4.1 概述

CX-O 实现了双向全双工打断机制，支持用户打断 Agent 和 Agent 打断用户两种场景。打断判断由 LLM 完成，确保语义层面的准确判断。

**核心代码：**
- [interrupt_manager.py](../CX-O-SERVER/server/services/interrupt_manager.py) — 打断管理器
- [asr_interrupt.py](../CX-O-SERVER/server/services/asr_interrupt.py) — 用户打断 Agent
- [agent_interrupt_user.py](../CX-O-SERVER/server/services/agent_interrupt_user.py) — Agent 打断用户

### 4.2 用户打断 Agent

当 Agent 正在播放 TTS 时，用户可以通过语音打断。

**流程：**

```
用户语音 → VAD 检测 → ASR 识别 → LLM 判断 → 停止 TTS
```

**ASRInterruptModule** 提供两种判断模式：

| 模式 | 说明 |
|------|------|
| `main_llm` | 使用主 LLM 判断，将 ASR 文本作为用户消息发送，根据 LLM 响应中的标记判断 |
| `independent_llm` | 使用独立 LLM（如 qwen2.5:1.5b）判断，降低主 LLM 负载 |

**LLM 判断标记：**

| 标记 | 含义 | 动作 |
|------|------|------|
| `##[INTERRUPT]##` | 用户明确提问或需要互动 | 停止 TTS，开始处理用户请求 |
| `##[IGNORE]##` | 用户自言自语或情绪表达 | 忽略，继续播放 TTS |
| `##[CONTINUE]##` | 用户还在组织语言 | 继续等待，不中断 |

**使用示例：**

```python
from server.services.asr_interrupt import get_asr_interrupt_module

interrupt = get_asr_interrupt_module()
interrupt.set_config({
    "interrupt": {
        "mode": "main_llm",
        "enabled": True,
        "independent_llm": {
            "enabled": False,
            "model": "qwen2.5:1.5b",
            "endpoint": "http://localhost:11434"
        }
    }
})

# 设置 TTS 播放状态
interrupt.set_tts_playing(True)

# ASR 结果到达时检查打断
decision, should_interrupt = await interrupt.on_asr_result("你好，等一下", is_final=False)
# decision: "INTERRUPT" / "IGNORE" / "CONTINUE"
# should_interrupt: True / False
```

### 4.3 Agent 打断用户

Agent 可以在用户说话过程中判断是否需要插话回复。

**流程：**

```
用户语音 → ASR 部分识别 → LLM 判断是否插话 → 停止用户录音 → Agent 开始 TTS
```

**AgentInterruptUser** 关键参数：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `enabled` | `True` | 是否启用 Agent 打断 |
| `interrupt_threshold_ms` | `500` | 打断判定阈值（毫秒） |
| `min_speech_duration_ms` | `1000` | 最短语音时长，低于此值不判断打断 |
| `interrupt_cooldown_ms` | `3000` | 打断冷却时间，防止频繁插话 |

**使用示例：**

```python
from server.services.agent_interrupt_user import get_agent_interrupt_module

agent_interrupt = get_agent_interrupt_module()
agent_interrupt.set_config({
    "agent_interrupt": {
        "enabled": True,
        "interrupt_threshold_ms": 500,
        "min_speech_duration_ms": 1000,
        "interrupt_cooldown_ms": 3000
    }
})

# 设置回调
agent_interrupt.set_callbacks(
    interrupt_user_callback=lambda: stop_user_recording(),
    start_tts_callback=lambda text: start_tts(text)
)

# ASR 部分结果到达时
result = await agent_interrupt.on_asr_partial_result("那个问题怎么解决？", is_final=False)
# result: {"should_interrupt": True, "should_reply": True, "reply_content": "..."}
```

### 4.4 InterruptManager

`InterruptManager` 是打断机制的统一入口，管理 ASR 打断和 Agent 打断两个子模块：

```python
from server.services.interrupt_manager import get_interrupt_manager

manager = get_interrupt_manager()
manager.set_asr_interrupt(asr_interrupt_module)
manager.set_agent_interrupt(agent_interrupt_module)
manager.set_interrupt_callback(lambda source, text: handle_interrupt(source, text))

# 触发打断
await manager.handle_interrupt(source="user", text="等一下")
```

### 4.5 双流式语音模式

除了传统的半双工模式外，系统支持 `voice.dual_stream` 双流式语音交互模式：

**与半双工模式的区别**：

| 特性 | 半双工模式 | 双流式模式 |
|------|-----------|-----------|
| 音频发送 | VAD 静默后才发送 | 边说边推，不等 VAD 判定 |
| ASR 识别 | 静默后整段识别 | 实时增量识别 |
| TTS 合成 | 完整回复后合成 | LLM 生成即合成（流式） |
| 打断方式 | ASR 结果后 LLM 判断 | 实时 VAD + ASR 判断 |

**WebSocket Actions**：

| Action | 方向 | 说明 |
|--------|------|------|
| `voice.dual_stream` | 客户端 → 服务端 | 发送音频数据（双流式） |
| `voice.partial` | 服务端 → 客户端 | ASR 部分识别结果 |
| `voice.tts_chunk` | 服务端 → 客户端 | TTS 音频块推送 |
| `voice.prefill_started` | 服务端 → 客户端 | TTS 预填充开始通知 |

**前端使用**：

```typescript
const { startDualStream, stopDualStream } = useAudioStream({
  wsSend: (data) => websocket.send(JSON.stringify(data)),
  onASRResult: (result) => console.log(result.text),
  onTTSChunk: (chunk) => playAudio(chunk),
  config: { sampleRate: 16000, channelCount: 1 },
});
```

---

## 5. 情感解析

### 5.1 概述

情感解析器负责解析文本中的情感标记 `[emotion:name]`，为 TTS 提供情感切换信息。

**核心代码：** [emotion_parser.py](../CX-O-SERVER/server/services/emotion_parser.py)

### 5.2 支持的情感

系统支持 15 种情感：

| 情感 | 标记 | 说明 |
|------|------|------|
| happy | `[emotion:happy]` | 开心 |
| sad | `[emotion:sad]` | 悲伤 |
| angry | `[emotion:angry]` | 愤怒 |
| surprised | `[emotion:surprised]` | 惊讶 |
| fear | `[emotion:fear]` | 恐惧 |
| disgust | `[emotion:disgust]` | 厌恶 |
| neutral | `[emotion:neutral]` | 中性 |
| excited | `[emotion:excited]` | 兴奋 |
| calm | `[emotion:calm]` | 平静 |
| whisper | `[emotion:whisper]` | 低语 |
| shout | `[emotion:shout]` | 呼喊 |
| laugh | `[emotion:laugh]` | 大笑 |
| cry | `[emotion:cry]` | 哭泣 |
| sigh | `[emotion:sigh]` | 叹气 |
| giggle | `[emotion:giggle]` | 咯咯笑 |

### 5.3 标记格式

```
[emotion:情感名称]
```

标记不区分大小写，解析后统一转为小写。未识别的情感标记将作为普通文本保留。

### 5.4 API

```python
from server.services.emotion_parser import (
    extract_emotions_with_text,
    parse_text_with_emotions,
    strip_emotion_tags,
    get_emotion_at_position,
    get_supported_emotions
)

# 获取支持的情感列表
emotions = get_supported_emotions()

# 提取情感与文本段落
segments = extract_emotions_with_text("[emotion:happy]你好！[emotion:calm]让我想想。")
# 返回:
# [
#   {"type": "emotion", "emotion": "happy"},
#   {"type": "text", "content": "你好！"},
#   {"type": "emotion", "emotion": "calm"},
#   {"type": "text", "content": "让我想想。"}
# ]

# 去除情感标记
clean_text = strip_emotion_tags("[emotion:happy]你好！")
# 返回: "你好！"

# 获取指定位置的情感
emotion = get_emotion_at_position("[emotion:happy]你好！", 5)
# 返回: "happy"
```

---

## 6. 音效解析

### 6.1 概述

音效解析器负责解析文本中的音效标记 `[effect:name]`，并加载对应的音效文件。

**核心代码：** [effect_parser.py](../CX-O-SERVER/server/services/effect_parser.py)

### 6.2 标记格式

```
[effect:音效名称]
```

### 6.3 支持的音效格式

| 格式 | 扩展名 |
|------|--------|
| WAV | `.wav` |
| MP3 | `.mp3` |
| OGG | `.ogg` |
| FLAC | `.flac` |

音效文件按优先级顺序查找：`.wav` → `.mp3` → `.ogg` → `.flac`

### 6.4 API

```python
from server.services.effect_parser import EffectParser

parser = EffectParser(effects_dir="data/voice_refs/transitions")

# 解析文本中的音效标记
segments = parser.parse_text_with_effects("欢迎！[effect:applause]让我们开始吧。")
# 返回:
# [
#   {"type": "text", "content": "欢迎！"},
#   {"type": "effect", "name": "applause", "data": <bytes>},
#   {"type": "text", "content": "让我们开始吧。"}
# ]

# 获取可用音效列表
effects = parser.get_available_effects()
# 返回: ["applause", "notification", "click", ...]

# 清除缓存
parser.clear_cache()
```

### 6.5 音效加载机制

- 音效文件从 `effects_dir` 目录加载
- 加载后缓存在内存中，避免重复 I/O
- 音效文件不存在时返回 `None`，并在日志中记录警告

---

## 7. 语音工作站

### 7.1 概述

CX-O-VoiceWorkStation 是独立的语音训练与推理服务，提供从参考音频生成到模型训练的完整工作流。

**核心代码：** [CX-O-VoiceWorkStation](../CX-O-VoiceWorkStation/)

**服务端口：** 8200

### 7.2 五步工作流

| 步骤 | ID | 名称 | 说明 |
|------|----|------|------|
| 1 | `ref_audio` | 参考音频生成 | 使用 VoxCPM 生成参考音频 |
| 2 | `emotion_refs` | 情感参考音频生成 | 基于 CosyVoice 生成多情感参考音频 |
| 3 | `train_prep` | 训练数据准备 | So-VITS-SVC 数据预处理 |
| 4 | `training` | 模型训练 | So-VITS-SVC 模型训练 |
| 5 | `inference` | 推理 | So-VITS-SVC 语音转换推理 |

**工作流 API：**

```bash
# 获取工作流状态
GET http://localhost:8200/api/workflow/status

# 执行指定步骤
POST http://localhost:8200/api/workflow/step/{step_id}/execute

# 获取步骤输出
GET http://localhost:8200/api/workflow/step/{step_id}/output

# 重置工作流
POST http://localhost:8200/api/workflow/reset
```

**执行步骤示例：**

```bash
# 步骤1：生成参考音频
curl -X POST http://localhost:8200/api/workflow/step/ref_audio/execute \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "design",
    "text": "大家好，欢迎来到我的直播间！",
    "control": "温柔、亲切的女性声音"
  }'

# 步骤2：生成情感参考音频
curl -X POST http://localhost:8200/api/workflow/step/emotion_refs/execute \
  -H "Content-Type: application/json" \
  -d '{
    "base_audio_path": "data/voice_refs/voxcpm/output.wav",
    "sample_text": "这是参考音频样本。",
    "transition_text": "嗯，",
    "pack_zip": true
  }'

# 步骤5：推理
curl -X POST http://localhost:8200/api/workflow/step/inference/execute \
  -H "Content-Type: application/json" \
  -d '{
    "audio_path": "input.wav",
    "model_path": "data/models/sovits_svc/model.pth",
    "speaker_id": 0,
    "transpose": 0
  }'
```

### 7.3 多引擎支持

| 引擎 | 用途 | API 路径 |
|------|------|----------|
| VoxCPM | 参考音频生成（设计/可控克隆/终极克隆） | `/api/voxcpm` |
| CosyVoice | 情感参考音频生成 | 内部调用 |
| IndexTTS | 情感 TTS 推理 | 按需启停 |
| F5-TTS | 微调训练 | `/api/f5tts-finetune` |
| So-VITS-SVC | 语音转换训练与推理 | `/api/sovits-svc` |

### 7.4 IndexTTS 按需启停

IndexTTS 服务采用按需启停策略，节省 GPU 资源：

- **按需启动：** 首次请求时自动启动，启动超时 180 秒
- **自动关闭：** 空闲 300 秒后自动关闭
- **状态监控：** 通过 `/health` 端点检测服务健康状态

```python
from workstation.services.index_tts_manager import get_indextts_manager

manager = get_indextts_manager(
    base_url="http://127.0.0.1:8004",
    start_command="python -m index_tts.app --port 8004 --host 0.0.0.0",
    working_dir="IndexTTS",
    auto_stop_delay=300,
    startup_timeout=180
)

# 确保服务运行
await manager.ensure_running()

# 获取状态
status = await manager.get_status()
# {"status": "running", "url": "http://127.0.0.1:8004", "healthy": true, "pid": 12345}

# 手动停止
await manager.stop()
```

**服务状态流转：**

```
STOPPED → STARTING → RUNNING → STOPPING → STOPPED
                                    ↓
                                  ERROR
```

### 7.5 VoxCPM 参考音频生成

VoxCPM 支持三种生成模式：

| 模式 | 说明 | 输入 |
|------|------|------|
| `design` | 文本设计语音 | text, control |
| `controllable_clone` | 可控语音克隆 | text, control, reference_audio |
| `ultimate_clone` | 终极语音克隆 | text, prompt_audio, prompt_text |

### 7.6 工作站配置

```json
{
  "server": {
    "host": "0.0.0.0",
    "port": 8200,
    "log_level": "INFO",
    "debug": true
  },
  "cosyvoice": {
    "url": "http://127.0.0.1:50000",
    "model": "CosyVoice2-0.5B",
    "default_mode": "instruct2",
    "timeout": 120.0,
    "default_spk_id": "中文女"
  },
  "index_tts": {
    "url": "http://127.0.0.1:8004",
    "enabled": true,
    "timeout": 180.0,
    "start_command": "",
    "working_dir": "IndexTTS",
    "auto_stop_delay": 300,
    "startup_timeout": 180
  },
  "f5tts_finetune": {
    "enabled": true,
    "base_model": "F5TTS_v1_Base",
    "output_dir": "data/models/f5tts",
    "training_data_dir": "data/training/f5tts"
  },
  "sovits_svc": {
    "enabled": true,
    "output_dir": "data/models/sovits_svc",
    "training_data_dir": "data/training/sovits_svc",
    "so_vits_svc_dir": "so-vits-svc-4.1-Stable",
    "python_path": "python"
  },
  "voxcpm": {
    "model_path": "openbmb/VoxCPM2",
    "device": "auto",
    "enable_denoiser": true,
    "cfg_value": 2.0,
    "inference_timesteps": 10,
    "zipenhancer_model_path": "iic/speech_zipenhancer_ans_multiloss_16k_base",
    "working_dir": "VoxCPM-main"
  },
  "output": {
    "voice_refs_dir": "CX-O-SERVER/data/voice_refs"
  }
}
```

---

## 8. 前端音频控制

### 8.1 概述

前端音频控制模块负责麦克风输入、音频输出、回声消除、音频分析和口型同步等功能。

**核心代码：**
- [AudioPanel.tsx](../CX-O-Frontend/src/pages/live/AudioPanel.tsx) — 音频控制面板
- [useAudioAnalyzer.ts](../CX-O-Frontend/src/hooks/useAudioAnalyzer.ts) — 音频分析 Hook
- [useAudioStream.ts](../CX-O-Frontend/src/hooks/useAudioStream.ts) — 音频流 Hook
- [AudioAnalyzer.ts](../CX-O-Frontend/src/components/Live2D/AudioAnalyzer.ts) — Live2D 音频分析器
- [Live2DLipSync.ts](../CX-O-Frontend/src/components/Live2D/Live2DLipSync.ts) — Live2D 口型同步
- [VRMLipSync.ts](../CX-O-Frontend/src/components/VRM/VRMLipSync.ts) — VRM 口型同步
- [AudioLipSync.ts](../CX-O-Frontend/src/components/VRM/AudioLipSync.ts) — VRM 音频口型同步

### 8.2 AudioPanel 音频控制面板

`AudioPanel` 组件提供完整的音频控制界面，包含以下功能：

#### 麦克风输入

- 设备枚举与选择
- 麦克风增益调节（0%~300%）
- 实时音量电平显示
- 音频录制并通过 WebSocket 发送

#### 音频输出

- TTS 音量控制（0%~200%）
- 输出音量控制（0%~200%）
- TTS 同步播放状态显示

#### AEC 回声消除

支持四种回声消除模式：

| 模式 | 说明 |
|------|------|
| `auto` | 自动选择最佳模式 |
| `browser` | 浏览器原生 AEC（`echoCancellation: true`） |
| `worklet` | AudioWorklet 自定义 AEC |
| `manual` | 手动音量平衡 |

**AEC 自动选择流程：**

1. 优先尝试浏览器原生 AEC
2. 检测 `echoCancellation` 设置是否生效
3. 若原生 AEC 不可用，尝试 AudioWorklet
4. 最终回退到手动模式

#### WebSocket 同步

AudioPanel 通过 WebSocket 与服务端同步 TTS 播放状态：

- **`onTTSSync`**：接收 TTS 播放同步数据（playback_id, text, server_ts）
- **`onTTSTick`**：接收 TTS 播放进度对齐
- **`onTTSEnd`**：TTS 播放结束通知

### 8.3 useAudioStream 音频流 Hook

`useAudioStream` Hook 封装了麦克风音频采集与 WebSocket 发送逻辑：

```typescript
import { useAudioStream } from '@/hooks/useAudioStream';

const { isStreaming, isSpeaking, startStreaming, stopStreaming, resetStream } = useAudioStream({
  wsSend: (data) => websocket.send(JSON.stringify(data)),
  onVADStatus: (status, duration) => console.log(status, duration),
  onASRResult: (result) => console.log(result.text),
  config: {
    sampleRate: 16000,
    channelCount: 1,
    echoCancellation: true,
    noiseSuppression: true,
    autoGainControl: true,
  },
  chunkInterval: 100,
});
```

**音频处理流程：**

1. `getUserMedia` 获取麦克风音频流
2. `AudioContext` + `ScriptProcessor` 采集 PCM 数据
3. Float32 → Int16 格式转换
4. 按 `chunkInterval`（默认 100ms）间隔打包
5. Base64 编码后通过 WebSocket 发送 `asr_stream` 动作

### 8.4 useAudioAnalyzer 音频分析 Hook

`useAudioAnalyzer` Hook 基于 Web Audio API 实现实时频率分析，为口型同步提供元音权重数据：

```typescript
import { useAudioAnalyzer } from '@/hooks/useAudioAnalyzer';

const { volume, voiceBandVolume, vowelWeights, volumeRef, vowelWeightsRef } = useAudioAnalyzer({
  audioElement: audioRef.current,
  isPlaying: true,
  fftSize: 256,
  smoothingTimeConstant: 0.8,
  normalizationFactor: 100,
});
```

**元音权重计算：**

通过频率分段求和计算五个元音的权重：

| 元音 | 频率段（FFT bin） |
|------|-------------------|
| a | 2-8 |
| i | 15-25 |
| u | 5-12 |
| e | 10-20 |
| o | 3-10 |

权重归一化后输出 0~1 的值，当总体音量低于阈值（0.05）时所有权重归零。

**性能优化：**

- 状态更新节流：每 100ms 更新一次 React 状态
- 提供 `volumeRef` 和 `vowelWeightsRef` 用于动画帧内直接读取，避免 React 重渲染

### 8.5 AudioAnalyzer（Live2D）

`AudioAnalyzer` 类为 Live2D 模型提供音频分析：

```typescript
import { audioAnalyzer } from '@/components/Live2D/AudioAnalyzer';

audioAnalyzer.connect(audioElement, (volume) => {
  // volume: 0~1 归一化音量
  live2dModel.setMouthOpen(volume);
});

audioAnalyzer.disconnect();
```

### 8.6 Live2DLipSync 口型同步

`Live2DLipSync` 将元音权重映射到 Live2D 模型的口型参数：

```typescript
import { Live2DLipSync } from '@/components/Live2D/Live2DLipSync';

const lipSync = new Live2DLipSync();
lipSync.bindModel(live2dModel);
lipSync.setSmoothing(0.3);

// 每帧更新
lipSync.updateWeights({ a: 0.8, i: 0.2, u: 0.1, e: 0.3, o: 0.5 });
lipSync.update(deltaTime);
```

**Live2D 参数映射：**

| 元音权重 | Live2D 参数 |
|----------|-------------|
| a | `ParamMouthA` |
| i | `ParamMouthI` |
| u | `ParamMouthU` |
| e | `ParamMouthE` |
| o | `ParamMouthO` |

**平滑插值：** 使用指数移动平均（EMA）进行平滑，`smoothingFactor` 控制插值速度。

### 8.7 VRMLipSync 口型同步

`VRMLipSync` 将元音权重映射到 VRM 模型的 BlendShape：

```typescript
import { VRMLipSync } from '@/components/VRM/VRMLipSync';

const lipSync = new VRMLipSync();
lipSync.bindVRM(vrmModel);
lipSync.setSmoothing(0.3);

lipSync.updateWeights({ a: 0.8, i: 0.2, u: 0.1, e: 0.3, o: 0.5 });
lipSync.update(deltaTime);
```

**VRM BlendShape 映射：**

| 元音权重 | VRM Expression Preset |
|----------|-----------------------|
| a | `VRMExpressionPresetName.Aa` |
| i | `VRMExpressionPresetName.Ih` |
| u | `VRMExpressionPresetName.Ou` |
| e | `VRMExpressionPresetName.Ee` |
| o | `VRMExpressionPresetName.Oh` |

### 8.8 VRMAudioLipSync

`VRMAudioLipSync` 是基于音频分析的简化口型同步，直接从音频元素提取音量驱动口型：

```typescript
import { createVRMLipSync } from '@/components/VRM/AudioLipSync';

const lipSync = createVRMLipSync();
lipSync.bindVRM(vrmModel);
lipSync.start(audioElement);

lipSync.stop();
lipSync.setExpression(VRMExpressionPresetName.Happy, 0.5);
lipSync.resetAllExpressions();
```

**口型映射策略：**

| BlendShape | 权重系数 |
|------------|----------|
| Aa | `volume * 0.8` |
| Ou | `volume * 0.3` |
| Ih | `volume * 0.2` |

---

## 9. 配置参考

### 9.1 完整语音配置示例

```json
{
  "asr": {
    "mode": "remote",
    "model_dir": "SenseVoiceSmall",
    "device": "cuda",
    "remote_url": "http://127.0.0.1:8001",
    "language": "auto"
  },
  "tts": {
    "mode": "remote",
    "model_dir": "F5TTS_v1_Base",
    "device": "cuda",
    "remote_url": "http://127.0.0.1:5000",
    "ref_audio_path": "data/voice_refs/default/ref.wav",
    "ref_text": "大家好，欢迎来到我的直播间！",
    "speed": 1.0,
    "cross_fade_duration": 0.15,
    "emotion_enabled": true,
    "effects_enabled": true,
    "emotion_refs_dir": "data/voice_refs/emotions",
    "transitions_dir": "data/voice_refs/transitions",
    "transition_enabled": true,
    "transition_text": "嗯，"
  },
  "services": {
    "asr": {
      "url": "http://127.0.0.1:8001",
      "timeout": 30
    },
    "tts": {
      "url": "http://127.0.0.1:5000",
      "timeout": 120,
      "ref_audio_path": "data/voice_refs/default/ref.wav",
      "ref_text": "大家好，欢迎来到我的直播间！",
      "model_type": "F5-TTS",
      "speed": 1.0,
      "cross_fade_duration": 0.15,
      "emotion_enabled": true,
      "effects_enabled": true,
      "emotion_voices": {
        "happy": {
          "ref_audio": "data/voice_refs/emotions/happy/ref.wav",
          "ref_text": "太好了！"
        },
        "sad": {
          "ref_audio": "data/voice_refs/emotions/sad/ref.wav",
          "ref_text": "唉..."
        }
      }
    },
    "index_tts": {
      "url": "http://127.0.0.1:8004",
      "timeout": 180,
      "enabled": true,
      "auto_stop_delay": 300,
      "start_command": "python -m index_tts.app --port 8004 --host 0.0.0.0",
      "working_dir": "index-tts"
    },
    "sensevoice_streaming": {
      "chunk_size": 1600,
      "hop_size": 800,
      "look_back": 8000
    },
    "orpheus": {
      "url": "http://127.0.0.1:5060",
      "model": "canopylabs/orpheus-multilingual-research-release",
      "voice": "tara",
      "timeout": 60,
      "flashinfer_enabled": true,
      "sample_rate": 24000
    }
  },
  "voice_workstation": {
    "url": "http://127.0.0.1:8200",
    "enabled": true
  }
}
```

### 9.2 情感参考音频目录结构

```
data/voice_refs/
├── default/
│   ├── ref.wav              # 默认参考音频
│   └── ref.txt              # 默认参考文本
├── emotions/
│   ├── emotion_mapping.json # 情感→音频映射（可选）
│   ├── happy/
│   │   ├── ref.wav
│   │   └── ref.txt
│   ├── sad/
│   │   ├── ref.wav
│   │   └── ref.txt
│   └── ...
└── transitions/
    ├── applause.wav
    ├── notification.wav
    └── ...
```

**emotion_mapping.json 格式：**

```json
{
  "happy": {
    "ref_audio": "data/voice_refs/emotions/happy/ref.wav",
    "ref_text": "太好了！"
  },
  "sad": {
    "ref_audio": "data/voice_refs/emotions/sad/ref.wav",
    "ref_text": "唉..."
  }
}
```

若 `emotion_mapping.json` 不存在，系统自动扫描 `emotions/` 下的子目录，以目录名作为情感名，查找 `ref.wav`/`ref.mp3`/`ref.flac` 和 `ref.txt`。

### 9.3 环境变量汇总

| 环境变量 | 对应配置路径 |
|----------|-------------|
| `CXO_ASR_MODE` | `asr.mode` |
| `CXO_ASR_MODEL_DIR` | `asr.model_dir` |
| `CXO_ASR_DEVICE` | `asr.device` |
| `CXO_ASR_REMOTE_URL` | `asr.remote_url` |
| `CXO_TTS_MODE` | `tts.mode` |
| `CXO_TTS_MODEL_DIR` | `tts.model_dir` |
| `CXO_TTS_DEVICE` | `tts.device` |
| `CXO_TTS_REMOTE_URL` | `tts.remote_url` |
| `CXO_ASR_URL` | `services.asr.url` |
| `CXO_TTS_URL` | `services.tts.url` |
| `CXO_INDEX_TTS_URL` | `services.index_tts.url` |
| `CXO_TTS_ORPHEUS_URL` | `tts.orpheus.url` |

---

## 10. Orpheus TTS 流式情感语音合成

### 10.1 概述

Orpheus TTS 是基于 vLLM + SNAC 解码的流式情感语音合成引擎，提供 OpenAI 兼容的 TTS API，支持 13 种语音和情感标签。

**核心代码：** [api_server.py](../orpheus-tts/api_server.py)

**服务端口：** 5060（Bridge），8000（vLLM 后端）

### 10.2 架构

```
客户端 → FastAPI Bridge (:5060) → vLLM (:8000) → SNAC 解码 → 24kHz WAV
```

**核心组件**：

| 组件 | 说明 |
|------|------|
| `VLLMClient` | 异步 vLLM 客户端，调用 `/v1/completions`，保留 custom tokens |
| `SnacTokenParser` | 流式解析 `<custom_token_N>` 格式的 SNAC 码 |
| `SnacDecoder` | 7 层量化码本解码，每帧 7 码 → 480 样本 (20ms @ 24kHz) |

### 10.3 API 端点

| 端点 | 方法 | 功能 |
|------|------|------|
| `/` | GET | 服务信息 |
| `/health` | GET | 健康检查（vLLM + SNAC 均就绪返回 200） |
| `/v1/models` | GET | OpenAI 兼容模型列表 |
| `/v1/audio/speech` | POST | OpenAI 兼容 TTS 端点，支持流式/非流式 |

### 10.4 语音合成请求

```bash
curl -X POST http://localhost:5060/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{
    "model": "canopylabs/orpheus-multilingual-research-release",
    "input": "你好，世界！",
    "voice": "tara",
    "response_format": "wav",
    "stream": true
  }'
```

**参数说明：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `model` | `str` | 必填 | 模型名称 |
| `input` | `str` | 必填 | 待合成文本 |
| `voice` | `str` | `"tara"` | 语音名称 |
| `response_format` | `str` | `"wav"` | 输出格式：wav / mp3 / pcm / opus |
| `stream` | `bool` | `False` | 是否流式输出 |

### 10.5 支持的语音

| 语音 | 语音 | 语音 |
|------|------|------|
| tara | leah | leo |
| dan | mia | jess |
| lily | zoe | zac |
| river | charlotte | james |
| matthew | | |

### 10.6 情感标签

在文本中嵌入情感标签控制语音情感表达：

| 标签 | 说明 |
|------|------|
| `<laugh>` | 笑声 |
| `<giggle>` | 咯咯笑 |
| `<sigh>` | 叹气 |
| `<cough>` | 咳嗽 |
| `<yawn>` | 打哈欠 |
| `<gasp>` | 倒吸气 |
| `<groan>` | 呻吟 |

**使用示例：**

```python
text = "今天真是太开心了 <laugh> 让我告诉你为什么"
```

### 10.7 性能指标

| 指标 | 值 |
|------|-----|
| 流式首包延迟 | < 300ms（目标） |
| RTF | 0.08-0.15（RTX 3080） |
| 采样率 | 24kHz |
| 生成速度 | 约为音频时长的 7-10 倍 |
| 批量大小 | 5 帧 = 100ms |

### 10.8 配置项

```json
{
  "tts": {
    "orpheus": {
      "url": "http://127.0.0.1:5060",
      "model": "canopylabs/orpheus-multilingual-research-release",
      "voice": "tara",
      "timeout": 60,
      "flashinfer_enabled": true,
      "sample_rate": 24000
    }
  }
}
```

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `url` | `str` | `"http://127.0.0.1:5060"` | Orpheus TTS Bridge 地址 |
| `model` | `str` | `"canopylabs/orpheus-multilingual-research-release"` | 模型名称 |
| `voice` | `str` | `"tara"` | 默认语音 |
| `timeout` | `int` | `60` | 请求超时（秒） |
| `flashinfer_enabled` | `bool` | `True` | 是否启用 FlashInfer 加速 |
| `sample_rate` | `int` | `24000` | 输出采样率 |

### 10.9 Docker 部署

```bash
cd orpheus-tts
docker-compose up -d
```

Docker Compose 启动两个服务：
- `vllm`：vLLM 推理引擎（端口 8000，GPU 0）
- `orpheus-bridge`：FastAPI Bridge（端口 5060，CPU）
