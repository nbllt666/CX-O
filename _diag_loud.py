"""响度诊断：对 WAV 测 peak/rms/dBFS，验证音量修复到位。"""
import sys
import numpy as np
import wave

PATH = sys.argv[1] if len(sys.argv) > 1 else r"C:\CX-O\.trae\test_reports\audio_sample_cosyvoice3_ws.wav"

with wave.open(PATH, "rb") as wf:
    sr = wf.getframerate()
    ch = wf.getnchannels()
    n = wf.getnframes()
    pcm = wf.readframes(n)
x = np.frombuffer(pcm, dtype="<i2").astype(np.float64)
if ch > 1:
    x = x.reshape(-1, ch).mean(axis=1)
dur = len(x) / sr
peak = abs(x).max()
rms = np.sqrt((x**2).mean())
peak_db = 20 * np.log10(peak / 32768) if peak > 0 else -999
rms_db = 20 * np.log10(rms / 32768) if rms > 0 else -999
clip = int((x >= 32766).sum() + (x <= -32766).sum())
print(f"{PATH}")
print(f"dur={dur:.2f}s peak={peak:.0f} ({peak_db:.1f}dBFS) rms={rms:.0f} ({rms_db:.1f}dBFS) clip={clip}")
print(f"  => peak正常(<1%,>40%满幅) rms正常(-30<dBFS<-10)" if 0.4 < peak/32768 < 1.0 and -30 < rms_db < -10 else "  => 响度仍需确认")