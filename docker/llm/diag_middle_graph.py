"""基于真实形状的首 hop middle CUDA graph 加速器（stft/istft eager）。

真实形状（mel=10, causal_padding=3）：
  s_stft=[1,18,361], xc=[1,512,3] → up0 24 → up1 120（对应 upsample_rates=[8,5,3]）
middle 段（conv）可 graph；stft/istft（cuFFT）保持 eager。
"""
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

cp = h.conv_pre_look_right  # 4
U = torch.as_tensor(h.upsample_rates).prod().item()  # 8*5*3=120
UPS = h.conv_pre_look_right
STFT_HOP = h.istft_params["hop_len"]


def transform_source(s):
    """s (bs,1,T_src) -> (real, imag) s_stft, 复现 decode 的截断"""
    stft = torch.stft(s.squeeze(1), h.istft_params["n_fft"], STFT_HOP, h.istft_params["n_fft"],
                      window=h.stft_window, return_complex=True)
    real = stft.real[:, :, :-int(U * UPS)]
    imag = stft.imag[:, :, :-int(U * UPS)]
    return torch.cat([real, imag], dim=1)  # [1, n_fft*2, T]


def middle(xc, s_stft):
    """decode 中间段（conv，可 graph）：xc->mag/phase"""
    x = xc
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


def istft(mag, phase):
    real = mag * torch.cos(phase)
    img = mag * torch.sin(phase)
    return torch.istft(torch.complex(real, img), h.istft_params["n_fft"], STFT_HOP, h.istft_params["n_fft"],
                       window=h.stft_window)


def decode_split(mel_in, finalize=False):
    """完整 decode：stft(eager) -> conv_pre -> middle -> istft(eager)"""
    f0 = h.f0_predictor(mel_in, finalize=finalize)
    s = h.f0_upsamp(f0[:, None]).transpose(1, 2)
    s, _, _ = h.m_source(s)
    s = s.transpose(1, 2)
    s_stft = transform_source(s)
    if finalize:
        xc = h.conv_pre(mel_in)
    else:
        xc = h.conv_pre(mel_in[:, :, :-cp], mel_in[:, :, -cp:])
    mag, ph = middle(xc, s_stft)
    out = istft(mag, ph)
    out = out[:, :-int(U * STFT_HOP)]
    return out


# eager 参考（原 decode）
mel = torch.rand(1, 80, 10, device="cuda:0")
f0 = h.f0_predictor(mel, finalize=False)
s = h.f0_upsamp(f0[:, None]).transpose(1, 2)
s, _, _ = h.m_source(s)
s = s.transpose(1, 2)
ref = h.decode(x=mel[:, :, :-h.f0_predictor.condnet[0].causal_padding], s=s, finalize=False)

# decode_split eager 基准 + 参考
for _ in range(20):
    o = decode_split(mel)
torch.cuda.synchronize()
t0 = time.perf_counter()
for _ in range(50):
    o = decode_split(mel)
torch.cuda.synchronize()
print(f"decode_split eager: {(time.perf_counter()-t0)/50*1000:.1f}ms")

# 构造 middle 固定输入，捕获 graph
f0 = h.f0_predictor(mel, finalize=False)
s = h.f0_upsamp(f0[:, None]).transpose(1, 2)
s, _, _ = h.m_source(s)
s = s.transpose(1, 2)
s_stft_static = transform_source(s)
xc_static = h.conv_pre(mel[:, :, :-cp], mel[:, :, -cp:])
for _ in range(10):
    m, p = middle(xc_static, s_stft_static)
torch.cuda.synchronize()
g = torch.cuda.CUDAGraph()
with torch.cuda.graph(g):
    m_g, p_g = middle(xc_static, s_stft_static)
torch.cuda.synchronize()
print("middle graph capture OK")

# graph middle 基准
def decode_graph(mel_in):
    f0 = h.f0_predictor(mel_in, finalize=False)
    s = h.f0_upsamp(f0[:, None]).transpose(1, 2)
    s, _, _ = h.m_source(s)
    s = s.transpose(1, 2)
    s_stft = transform_source(s)
    xc = h.conv_pre(mel_in[:, :, :-cp], mel_in[:, :, -cp:])
    # 仅当形状匹配时用 graph，否则回退 eager middle
    if xc.shape == xc_static.shape and s_stft.shape == s_stft_static.shape:
        # copy 输入到 graph 静态缓冲（此处直接用静态张量，生产需 copy_）
        with torch.no_grad():
            xc_static.copy_(xc)
            s_stft_static.copy_(s_stft)
        g.replay()
        return istft(m_g, p_g)[:, :-int(U * STFT_HOP)]
    else:
        mag, ph = middle(xc, s_stft)
        return istft(mag, ph)[:, :-int(U * STFT_HOP)]

for _ in range(20):
    o = decode_graph(mel)
torch.cuda.synchronize()
t0 = time.perf_counter()
for _ in range(50):
    o = decode_graph(mel)
torch.cuda.synchronize()
print(f"decode_graph: {(time.perf_counter()-t0)/50*1000:.1f}ms")

# 正确性：decode_graph vs eager decode
torch.cuda.synchronize()
o = decode_graph(mel)
print(f"graph vs eager decode diff: {(ref - o).abs().max().item():.6f}")