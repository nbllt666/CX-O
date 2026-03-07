"""
检查 torchaudio 后端 - 忽略警告
"""
import warnings
warnings.filterwarnings('ignore')

import torchaudio
print(f"torchaudio 版本: {torchaudio.__version__}")

# 检查可用的后端
print("\n尝试加载音频...")
try:
    waveform, sample_rate = torchaudio.load("d:/CX-O/test_audio.wav")
    print(f"✅ 加载成功! shape={waveform.shape}, sample_rate={sample_rate}")
except Exception as e:
    print(f"❌ 加载失败: {e}")

# 尝试其他方法
print("\n尝试使用 scipy...")
try:
    from scipy.io import wavfile
    rate, data = wavfile.read("d:/CX-O/test_audio.wav")
    print(f"✅ scipy 加载成功! rate={rate}, data.shape={data.shape}")
except Exception as e:
    print(f"❌ scipy 加载失败: {e}")
