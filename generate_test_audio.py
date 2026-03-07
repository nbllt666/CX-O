"""
生成测试音频文件并测试 ASR
"""
import numpy as np
import wave
import base64

# 生成 1 秒 440Hz 正弦波 (标准测试音调)
sample_rate = 16000
duration = 1.0
t = np.linspace(0, duration, int(sample_rate * duration))
audio = np.sin(2 * np.pi * 440 * t).astype(np.float32)

# 保存为 WAV
with wave.open("d:/CX-O/test_audio.wav", 'wb') as wf:
    wf.setnchannels(1)
    wf.setsampwidth(2)
    wf.setframerate(sample_rate)
    wf.writeframes((audio * 32767).astype(np.int16).tobytes())

print(f"生成测试音频: d:/CX-O/test_audio.wav")
print(f"样本率: {sample_rate}, 时长: {duration}秒, 通道: 1")

# 读取并转为 base64
with open("d:/CX-O/test_audio.wav", "rb") as f:
    audio_b64 = base64.b64encode(f.read()).decode("utf-8")
    print(f"Base64 长度: {len(audio_b64)}")
