"""检查 torchaudio 后端"""
import torchaudio
print("Available backends:", torchaudio.list_available_backends())
print("Soundfile available:", torchaudio.backends.soundfile.available())
print("Sox available:", torchaudio.backends.sox.available())
print("SoxIO available:", torchaudio.backends.sox_io.available())

# 尝试直接读取
try:
    waveform, sample_rate = torchaudio.load("d:/CX-O/test_audio.wav")
    print(f"Loaded: waveform shape={waveform.shape}, sample_rate={sample_rate}")
except Exception as e:
    print(f"Error: {e}")
