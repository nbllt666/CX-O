"""验证 hift decode 中间 conv 段 CUDA graph 捕获（stft/istft 保持 eager）。"""
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


def middle(mel_in, s_stft_in):
    """decode 中间段（stft 之后、istft 之前）：conv_pre → ups → resblocks → conv_post → mag/phase"""
    x = mel_in[:, :, :-h.f0_predictor.condnet[0].causal_padding]
    x = h.conv_pre(x[:, :, :-h.conv_pre_look_right], x[:, :, -h.conv_pre_look_right:])
    s_stft = s_stft_in
    for i in range(h.num_upsamples):
        x = torch.nn.functional.leaky_relu(x, h.lrelu_slope)
        x = h.ups[i](x)
        if i == h.num_upsamples - 1:
            x = h.reflection_pad(x)
        si = h.source_downs[i](s_stft)
        si = h.source_resblocks[i](si)
        x = x + si
        xs = None
        for j in range(h.num_kernels):
            r = h.resblocks[i * h.num_kernels + j](x)
            xs = r if xs is None else xs + r
        x = xs / h.num_kernels
    x = torch.nn.functional.leaky_relu(x)
    x = h.conv_post(x)
    magnitude = torch.exp(x[:, :h.istft_params["n_fft"] // 2 + 1, :])
    phase = torch.sin(x[:, h.istft_params["n_fft"] // 2 + 1:, :])
    return magnitude, phase


def full(mel_in):
    """完整 decode（含 stft/istft）"""
    f0 = h.f0_predictor(mel_in, finalize=False)
    s = h.f0_upsamp(f0[:, None]).transpose(1, 2)
    s, _, _ = h.m_source(s)
    s = s.transpose(1, 2)
    return h.decode(x=mel_in[:, :, :-h.f0_predictor.condnet[0].causal_padding], s=s, finalize=False)


# 计算 eager s_stft（stft 段保持 eager）
f0 = h.f0_predictor(mel, finalize=False)
s = h.f0_upsamp(f0[:, None]).transpose(1, 2)
s, _, _ = h.m_source(s)
s = s.transpose(1, 2)
s_stft = torch.cat([
    torch.stft(s.squeeze(1), h.istft_params["n_fft"], h.istft_params["hop_len"], h.istft_params["n_fft"], window=h.stft_window, return_complex=True).real,
    torch.stft(s.squeeze(1), h.istft_params["n_fft"], h.istft_params["hop_len"], h.istft_params["n_fft"], window=h.stft_window, return_complex=True).imag,
], dim=1)
# 与 decode 内一致的截断
s_stft = s_stft[:, :, :-int(torch.as_tensor(h.upsample_rates).prod() * h.conv_pre_look_right)]

# eager middle 基准 + 参考
for _ in range(20):
    m1, p1 = middle(mel, s_stft)
torch.cuda.synchronize()
t0 = time.perf_counter()
for _ in range(50):
    m1, p1 = middle(mel, s_stft)
torch.cuda.synchronize()
print(f"eager middle: {(time.perf_counter()-t0)/50*1000:.1f}ms")

# CUDA graph 捕获 middle
try:
    g = torch.cuda.CUDAGraph()
    with torch.cuda.graph(g):
        m_g, p_g = middle(mel, s_stft)
    torch.cuda.synchronize()
    print("middle capture OK")
    t0 = time.perf_counter()
    for _ in range(50):
        g.replay()
    torch.cuda.synchronize()
    print(f"graph middle: {(time.perf_counter()-t0)/50*1000:.1f}ms")
    # 正确性
    em1, ep1 = middle(mel, s_stft)
    torch.cuda.synchronize()
    print(f"graph vs eager mag diff: {(em1 - m_g).abs().max().item():.6f}")
    print(f"graph vs eager phase diff: {(ep1 - p_g).abs().max().item():.6f}")
except Exception as e:
    import traceback
    print(f"middle capture FAILED: {e}")
    traceback.print_exc()
