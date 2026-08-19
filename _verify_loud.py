"""直连 cosyvoice（列表 ref 格式 = 真实 provider 路径）验证响度归一化。"""
import base64
import numpy as np
import requests

SR = 24000


def main():
    ref_b64 = base64.b64encode(open(r"C:\CX-O\CX-O-SERVER\data\ref_audio_assets\ref_8df9787c96124a5f.wav", "rb").read()).decode()
    body = {
        "input": "今天天气真不错，我们一起出去散步吧，你觉得怎么样呢",
        "ref_audio": ["data:audio/wav;base64," + ref_b64],
        "ref_text": ["参考音频转写文本。"],
        "stream": True, "response_format": "wav", "speed": 1.0,
    }
    r = requests.post("http://127.0.0.1:8094/v1/audio/speech", json=body, timeout=120,
                      proxies={"http": None, "https": None}, stream=True)
    r.raise_for_status()
    skip = 44
    allpcm = b""
    for ch in r.iter_content(chunk_size=8192):
        if skip > 0:
            cut = min(skip, len(ch)); ch = ch[cut:]; skip -= cut
            if not ch: continue
        allpcm += ch
    x = np.frombuffer(allpcm, dtype="<i2").astype(np.float64)
    peak = abs(x).max()
    rms = np.sqrt((x**2).mean())
    clip = int((x >= 32766).sum() + (x <= -32766).sum())
    peak_db = 20*np.log10(peak/32768)
    rms_db = 20*np.log10(rms/32768)
    print(f"samples={len(x)} dur={len(x)/SR:.2f}s")
    print(f"peak={peak:.0f} ({peak_db:.1f}dBFS) rms={rms:.0f} ({rms_db:.1f}dBFS) clip={clip}")
    ok = peak > 0.3*32768 and peak < 32768 and clip == 0
    print("=> 响度正常" if ok else "=> 仍需调整")


if __name__ == "__main__":
    main()