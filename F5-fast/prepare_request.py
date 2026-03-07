import json
import struct
import wave
import base64

def load_wav(path):
    with wave.open(path, "rb") as wf:
        sample_rate = wf.getframerate()
        n_channels = wf.getnchannels()
        n_frames = wf.getnframes()
        audio_bytes = wf.readframes(n_frames)
        import numpy as np
        audio = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        if n_channels > 1:
            audio = audio.reshape(-1, n_channels).mean(axis=1)
        return audio, sample_rate

ref_audio, ref_sr = load_wav("test.wav")
print(f"Audio shape: {ref_audio.shape}, sr: {ref_sr}")

audio_data = ref_audio.reshape(1, -1).astype('<f4')
audio_bytes = audio_data.tobytes()
audio_b64 = base64.b64encode(audio_bytes).decode('utf-8')

audio_len_bytes = struct.pack('<i', ref_audio.shape[0])
audio_len_b64 = base64.b64encode(audio_len_bytes).decode('utf-8')

ref_text = "欢迎所有新进直播间的朋友们"
target_text = "大家好，这是一个语音合成测试。"

request = {
    "id": "1",
    "inputs": [
        {
            "name": "reference_wav",
            "datatype": "FP32",
            "shape": [1, len(ref_audio)],
            "content": audio_b64
        },
        {
            "name": "reference_wav_len",
            "datatype": "INT32",
            "shape": [1, 1],
            "content": audio_len_b64
        },
        {
            "name": "reference_text",
            "datatype": "BYTES",
            "shape": [1, 1],
            "content": base64.b64encode(ref_text.encode('utf-8')).decode('utf-8')
        },
        {
            "name": "target_text",
            "datatype": "BYTES",
            "shape": [1, 1],
            "content": base64.b64encode(target_text.encode('utf-8')).decode('utf-8')
        }
    ],
    "outputs": [{"name": "waveform"}]
}

with open("request.json", "w") as f:
    json.dump(request, f)

print("Request saved to request.json")
print(f"Audio length: {len(ref_audio)} samples")
