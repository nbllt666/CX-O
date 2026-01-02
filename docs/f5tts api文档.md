# F5-TTS API 文档

## 概述

F5-TTS 是一个基于深度学习的文本转语音（Text-to-Speech）API，支持 F5-TTS 和 E2-TTS 两种模型。

## 安装依赖

```bash
pip install soundfile torch tqdm cached_path
```

## 快速开始

```python
from api import F5TTS

f5tts = F5TTS()

wav, sr, spect = f5tts.infer(
    ref_file="reference.wav",
    ref_text="这是参考文本",
    gen_text="这是要生成的文本",
    file_wave="output.wav"
)
```

## F5TTS 类

### 初始化

```python
f5tts = F5TTS(
    model_type="F5-TTS",
    ckpt_file="",
    vocab_file="",
    ode_method="euler",
    use_ema=True,
    local_path=None,
    device=None
)
```

#### 参数说明

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `model_type` | str | `"F5-TTS"` | 模型类型，可选 `"F5-TTS"` 或 `"E2-TTS"` |
| `ckpt_file` | str | `""` | 模型检查点文件路径，为空时自动下载默认模型 |
| `vocab_file` | str | `""` | 词汇表文件路径 |
| `ode_method` | str | `"euler"` | ODE 求解方法，可选 `"euler"`、`"rk4"` 等 |
| `use_ema` | bool | `True` | 是否使用 EMA 模型 |
| `local_path` | str | `None` | 本地模型路径（用于 vocoder） |
| `device` | str | `None` | 运行设备，`"cuda"`、`"mps"` 或 `"cpu"`，为 None 时自动选择 |

#### 返回值

初始化成功后返回 `F5TTS` 实例。

---

### infer 方法

核心方法，用于生成语音。

```python
wav, sr, spect = f5tts.infer(
    ref_file,
    ref_text,
    gen_text,
    show_info=print,
    progress=tqdm,
    target_rms=0.1,
    cross_fade_duration=0.15,
    sway_sampling_coef=-1,
    cfg_strength=2,
    nfe_step=32,
    speed=1.0,
    fix_duration=None,
    remove_silence=False,
    file_wave=None,
    file_spect=None,
    seed=-1
)
```

#### 参数说明

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `ref_file` | str | 必填 | 参考音频文件路径（.wav 格式） |
| `ref_text` | str | 必填 | 参考音频对应的文本内容 |
| `gen_text` | str | 必填 | 要生成的语音文本 |
| `show_info` | Callable | `print` | 信息显示函数 |
| `progress` | Callable | `tqdm` | 进度条函数 |
| `target_rms` | float | `0.1` | 目标 RMS（均方根）值，控制音量 |
| `cross_fade_duration` | float | `0.15` | 交叉淡入淡出时长（秒） |
| `sway_sampling_coef` | float | `-1` | 摆动采样系数，-1 为自动 |
| `cfg_strength` | float | `2` | Classifier-Free Guidance 强度 |
| `nfe_step` | int | `32` | 噪声前向扩散步数，越高越慢但质量越好 |
| `speed` | float | `1.0` | 生成语音速度，1.0 为正常 |
| `fix_duration` | float | `None` | 固定生成时长（秒），为 None 时自动计算 |
| `remove_silence` | bool | `False` | 是否移除生成音频中的静音部分 |
| `file_wave` | str | `None` | 输出音频文件路径 |
| `file_spect` | str | `None` | 输出频谱图文件路径 |
| `seed` | int | `-1` | 随机种子，-1 为随机生成 |

#### 返回值

| 返回值 | 类型 | 说明 |
|--------|------|------|
| `wav` | numpy.ndarray | 生成的音频数据，浮点数类型，范围 [-1, 1] |
| `sr` | int | 采样率，始终为 `24000` |
| `spect` | numpy.ndarray | 生成的频谱数据，形状为 `(n_mel_channels, time_steps)` |

#### 使用示例

```python
from api import F5TTS
import numpy as np

f5tts = F5TTS()

wav, sr, spect = f5tts.infer(
    ref_file="ref_audio.wav",
    ref_text="这是一段参考语音的文字内容",
    gen_text="这是一段要生成的语音文本内容",
    file_wave="output.wav",
    remove_silence=True,
    seed=42
)

print(f"音频形状: {wav.shape}")
print(f"采样率: {sr}")
print(f"频谱形状: {spect.shape}")
print(f"使用的种子: {f5tts.seed}")
```

---

### export_wav 方法

导出音频文件。

```python
f5tts.export_wav(wav, file_wave, remove_silence=False)
```

#### 参数说明

| 参数 | 类型 | 说明 |
|------|------|------|
| `wav` | numpy.ndarray | 音频数据 |
| `file_wave` | str | 输出文件路径 |
| `remove_silence` | bool | 是否移除静音 |

---

### export_spectrogram 方法

导出频谱图。

```python
f5tts.export_spectrogram(spect, file_spect)
```

#### 参数说明

| 参数 | 类型 | 说明 |
|------|------|------|
| `spect` | numpy.ndarray | 频谱数据 |
| `file_spect` | str | 输出图片路径 |

---

## 实例属性

| 属性 | 类型 | 说明 |
|------|------|------|
| `final_wave` | numpy.ndarray | 最后生成的音频数据 |
| `target_sample_rate` | int | 目标采样率，始终为 `24000` |
| `n_mel_channels` | int | 梅尔频道数，始终为 `100` |
| `hop_length` | int | 跳跃长度，始终为 `256` |
| `target_rms` | float | 目标 RMS 值 |
| `seed` | int | 最后使用的随机种子 |
| `device` | str | 运行设备 |
| `vocos` | nn.Module | Vocoder 模型 |
| `ema_model` | nn.Module | 主扩散模型 |

---

## 高级用法

### 使用自定义模型

```python
from api import F5TTS

f5tts = F5TTS(
    model_type="E2-TTS",
    ckpt_file="./models/e2tts_model.safetensors",
    vocab_file="./models/vocab.txt",
    use_ema=True
)
```

### 批量生成

```python
from api import F5TTS

f5tts = F5TTS()

texts = [
    "第一段文本",
    "第二段文本",
    "第三段文本"
]

for i, text in enumerate(texts):
    wav, sr, spect = f5tts.infer(
        ref_file="reference.wav",
        ref_text="参考文本",
        gen_text=text,
        file_wave=f"output_{i}.wav",
        seed=i + 1  # 使用不同种子
    )
```

### 控制生成速度

```python
wav, sr, spect = f5tts.infer(
    ref_file="ref.wav",
    ref_text="参考文本",
    gen_text="要生成的文本",
    speed=1.5,  # 1.5倍速度
    nfe_step=64  # 增加步数以提高质量
)
```

---

## 错误处理

```python
from api import F5TTS

try:
    f5tts = F5TTS()
    
    wav, sr, spect = f5tts.infer(
        ref_file="reference.wav",
        ref_text="参考文本",
        gen_text="生成文本"
    )
    
except ValueError as e:
    print(f"参数错误: {e}")
except Exception as e:
    print(f"运行时错误: {e}")
```

---

## 模型配置

### F5-TTS 默认配置

```python
model_cfg = dict(
    dim=1024,      # 维度
    depth=22,      # 深度
    heads=16,      # 注意力头数
    ff_mult=2,     # 前馈网络倍数
    text_dim=512,  # 文本维度
    conv_layers=4  # 卷积层数
)
```

### E2-TTS 默认配置

```python
model_cfg = dict(
    dim=1024,   # 维度
    depth=24,   # 深度
    heads=16,   # 注意力头数
    ff_mult=4   # 前馈网络倍数
)
```
