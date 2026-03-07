"""调试 SenseVoice ASR 音频处理"""
import torchaudio
from io import BytesIO

# 尝试加载测试音频
try:
    file_io = BytesIO()
    with open("d:/CX-O/test_audio.wav", "rb") as f:
        file_io.write(f.read())
    file_io.seek(0)
    
    print("尝试使用 torchaudio 加载...")
    data_or_path_or_list, audio_fs = torchaudio.load(file_io)
    print(f"加载成功! 采样率: {audio_fs}, 数据形状: {data_or_path_or_list.shape}")
except Exception as e:
    print(f"加载失败: {e}")
    import traceback
    traceback.print_exc()
