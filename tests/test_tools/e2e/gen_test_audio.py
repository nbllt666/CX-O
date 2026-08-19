"""生成多频段测试音频：模拟语音的频谱特征，让 ASR 能识别出多字符文本。

生成策略：三个不同频率的短脉冲（440Hz/880Hz/1320Hz），每个持续 200ms，
中间有 50ms 静音间隔，模拟"短句"的音节结构。
"""
import io
import wave
import numpy as np

SR = 16000
DUR_S = 1.0

def generate_speech_like_audio() -> bytes:
    """生成多频段脉冲音频，让 ASR 更容易识别为多字符文本。"""
    n = int(DUR_S * SR)
    t = np.linspace(0, DUR_S, n, endpoint=False, dtype=np.float32)
    
    # 三段不同频率的脉冲，模拟音节
    seg_len = n // 4
    wave = np.zeros(n, dtype=np.float32)
    
    # 第一段: 440Hz 200ms
    s1 = int(0.2 * SR)
    wave[:s1] = 0.4 * np.sin(2 * np.pi * 440 * t[:s1])
    
    # 第二段: 880Hz 200ms
    s2 = int(0.45 * SR)
    wave[s1:s2] = 0.4 * np.sin(2 * np.pi * 880 * t[s1:s2])
    
    # 第三段: 1320Hz 200ms
    s3 = int(0.7 * SR)
    wave[s2:s3] = 0.4 * np.sin(2 * np.pi * 1320 * t[s2:s3])
    
    # 第四段: 660Hz 剩余
    wave[s3:n] = 0.3 * np.sin(2 * np.pi * 660 * t[s3:n])
    
    pcm = (wave * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(pcm.tobytes())
    return buf.getvalue()


def generate_sine_wave() -> bytes:
    """原始 440Hz 纯正弦波（对比用）。"""
    n = int(DUR_S * SR)
    t = np.linspace(0, DUR_S, n, endpoint=False, dtype=np.float32)
    wave = 0.5 * np.sin(2 * np.pi * 440 * t)
    pcm = (wave * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(pcm.tobytes())
    return buf.getvalue()


if __name__ == "__main__":
    import base64
    speech_like = generate_speech_like_audio()
    sine = generate_sine_wave()
    print(f"speech_like audio: {len(speech_like)} bytes -> base64: {len(base64.b64encode(speech_like).decode())} chars")
    print(f"sine wave audio:   {len(sine)} bytes -> base64: {len(base64.b64encode(sine).decode())} chars")
    
    # 保存到文件供分析
    with open("test_speech.wav", "wb") as f:
        f.write(speech_like)
    print("saved: test_speech.wav")
    with open("test_sine.wav", "wb") as f:
        f.write(sine)
    print("saved: test_sine.wav")