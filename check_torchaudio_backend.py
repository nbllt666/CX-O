"""
检查 torchaudio 后端
"""
import torchaudio
print(f"torchaudio 版本: {torchaudio.__version__}")

# 尝试 soundfile 后端
try:
    torchaudio.set_audio_backend("soundfile")
    print("soundfile 后端可用")
except Exception as e:
    print(f"soundfile 后端不可用: {e}")

# 尝试 sox 后端  
try:
    torchaudio.set_audio_backend("sox")
    print("sox 后端可用")
except Exception as e:
    print(f"sox 后端不可用: {e}")

# 尝试直接加载
try:
    waveform, sample_rate = torchaudio.load("d:/CX-O/test_audio.wav")
    print(f"加载成功! shape={waveform.shape}, sample_rate={sample_rate}")
except Exception as e:
    print(f"加载失败: {e}")
