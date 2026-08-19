"""重试 hift-only CUDA graph 捕获（阻塞点已全部修复后）。"""
import time
import sys

import torch

sys.path.insert(0, "/workspace/cosyvoice-official")
sys.path.insert(0, "/workspace/cosyvoice-official/third_party/Matcha-TTS")
from hyperpyyaml import load_hyperpyyaml

md = "/workspace/models/Fun-CosyVoice3-0.5B-2512"
cfg = load_hyperpyyaml(
    open(md + "/cosyvoice3.yaml"),
    overrides={"llm": None, "flow": None, "qwen_pretrain_path": md + "/CosyVoice-BlankEN"},
)
h = cfg["hift"].to("cuda:0").eval()
h.stft_window = h.stft_window.to("cuda:0")
# 模拟 server 补丁：f0 保持 fp32 + weight_norm 移除 + SineGen2 缓冲 GPU
import torch.nn.utils.parametrize as parametrize
for m in h.modules():
    try:
        if parametrize.is_parametrized(m, "weight"):
            parametrize.remove_parametrizations(m, "weight")
    except Exception:
        pass
sg2 = h.m_source.l_sin_gen
for attr in ("rand_ini", "sine_waves", "uv"):
    buf = getattr(sg2, attr, None)
    if buf is not None and buf.device.type == "cpu":
        setattr(sg2, attr, buf.to("cuda:0"))

mel = torch.rand(1, 80, 10, device="cuda:0")
for _ in range(30):
    h.inference(speech_feat=mel, finalize=False)
torch.cuda.synchronize()

# hift-only CUDA graph 捕获
try:
    g = torch.cuda.CUDAGraph()
    with torch.cuda.graph(g):
        out_graph = h.inference(speech_feat=mel, finalize=False)[0].clone()
    torch.cuda.synchronize()
    print("hift-only capture OK")
    # eager 基准
    t0 = time.perf_counter()
    for _ in range(50):
        h.inference(speech_feat=mel, finalize=False)
    torch.cuda.synchronize()
    print(f"eager hift: {(time.perf_counter()-t0)/50*1000:.1f}ms")
    # graph 基准
    t0 = time.perf_counter()
    for _ in range(50):
        g.replay()
    torch.cuda.synchronize()
    print(f"graph hift: {(time.perf_counter()-t0)/50*1000:.1f}ms")
    # 正确性
    eager_out = h.inference(speech_feat=mel, finalize=False)[0].clone()
    torch.cuda.synchronize()
    print(f"graph vs eager diff: {(eager_out - out_graph).abs().max().item():.6f}")
except Exception as e:
    import traceback
    print(f"hift-only capture FAILED: {e}")
    traceback.print_exc()
