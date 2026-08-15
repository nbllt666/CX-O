"""IndexTTS-2.5 探针：验证克隆+情感能力矩阵。

用法:
    <indextts25-venv>/python probe_indextts25.py
"""
import base64, json, os, sys, time

sys.path.insert(0, r"C:\CX-O\third_party\index-tts-official")
from indextts.infer_v2_5 import IndexTTS2

MODEL_DIR = r"C:\CX-O\models\IndexTTS-2.5"
REF_WAV = r"C:\CX-O\CX-O-SERVER\data\ref_audio_assets\_upload_ref.wav"
OUT_DIR = r"C:\CX-O\docker\llm\probe_out"
os.makedirs(OUT_DIR, exist_ok=True)

results = []
def record(name, ok, detail):
    results.append({"name": name, "ok": ok, "detail": detail})
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")

import torchaudio, soundfile as sf, numpy as np

# 加载模型
t0 = time.monotonic()
tts = IndexTTS2(
    cfg_path=os.path.join(MODEL_DIR, "config.yaml"),
    model_dir=MODEL_DIR,
    use_bf16=True,
    device="cuda:1",
    use_qwen_emo=True,
)
print(f">> Model loaded in {time.monotonic()-t0:.1f}s")

# 1. 基本克隆（参考音频 + 文本）
t0 = time.monotonic()
result = tts.infer(
    spk_audio_prompt=REF_WAV,
    text="你好，这是一个测试语音克隆的样本。",
    output_path=None,
    lang="zh_CN",
    emo_audio_prompt=None,
    emo_alpha=1.0,
    emo_vector=None,
    use_emo_text=False,
    emo_text=None,
    use_random=False,
)
ok = result is not None and isinstance(result, tuple) and len(result[1]) > 0
sr, wav = result if ok else (0, np.array([]))
record("basic_clone", ok, f"sr={sr} len={len(wav)} dur={len(wav)/sr:.2f}s" if ok else "None")
if ok:
    sf.write(os.path.join(OUT_DIR, "indextts_basic_clone.wav"), wav.T if wav.ndim == 2 else wav, sr)

# 2. 情感文本控制（emo_text）
t0 = time.monotonic()
result = tts.infer(
    spk_audio_prompt=REF_WAV,
    text="我非常生气，这太让人愤怒了！",
    output_path=None,
    lang="zh_CN",
    emo_audio_prompt=None,
    emo_alpha=1.0,
    emo_vector=None,
    use_emo_text=True,
    emo_text="愤怒地大声说话",
    use_random=False,
)
ok = result is not None and isinstance(result, tuple) and len(result[1]) > 0
sr, wav = result if ok else (0, np.array([]))
record("emo_text_angry", ok, f"sr={sr} len={len(wav)} dur={len(wav)/sr:.2f}s" if ok else "None")
if ok:
    sf.write(os.path.join(OUT_DIR, "indextts_emo_angry.wav"), wav.T if wav.ndim == 2 else wav, sr)

# 3. 情感文本控制 - 悲伤
result = tts.infer(
    spk_audio_prompt=REF_WAV,
    text="这真是一个令人悲伤的消息。",
    output_path=None,
    lang="zh_CN",
    emo_audio_prompt=None,
    emo_alpha=1.0,
    emo_vector=None,
    use_emo_text=True,
    emo_text="悲伤地轻声诉说",
    use_random=False,
)
ok = result is not None and isinstance(result, tuple) and len(result[1]) > 0
sr, wav = result if ok else (0, np.array([]))
record("emo_text_sad", ok, f"sr={sr} len={len(wav)} dur={len(wav)/sr:.2f}s" if ok else "None")
if ok:
    sf.write(os.path.join(OUT_DIR, "indextts_emo_sad.wav"), wav.T if wav.ndim == 2 else wav, sr)

# 4. 情感向量控制
emo_vec = [0, 0, 0.65, 0, 0, 0, 0, 0]  # 愤怒维度
result = tts.infer(
    spk_audio_prompt=REF_WAV,
    text="测试情感向量控制愤怒程度。",
    output_path=None,
    lang="zh_CN",
    emo_audio_prompt=None,
    emo_alpha=1.0,
    emo_vector=emo_vec,
    use_emo_text=False,
    emo_text=None,
    use_random=False,
)
ok = result is not None and isinstance(result, tuple) and len(result[1]) > 0
sr, wav = result if ok else (0, np.array([]))
record("emo_vector_angry", ok, f"sr={sr} len={len(wav)} dur={len(wav)/sr:.2f}s" if ok else "None")
if ok:
    sf.write(os.path.join(OUT_DIR, "indextts_emo_vector.wav"), wav.T if wav.ndim == 2 else wav, sr)

# 汇总
passed = sum(1 for x in results if x["ok"])
print(f"\n=== PROBE SUMMARY ===\npassed={passed}/{len(results)}")
with open(os.path.join(OUT_DIR, "probe_indextts25_manifest.json"), "w", encoding="utf-8") as f:
    json.dump({"results": results}, f, ensure_ascii=False, indent=2)