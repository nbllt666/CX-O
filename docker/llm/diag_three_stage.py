"""验证三段式 hift decode：stft(eager) → middle(CUDA graph) → istft(eager)。

可安全集成到生产的道路：
1. stft 段：eager（cuFFT，不可捕获，但快）
2. middle 段：CUDA graph 捕获（67ms→4ms）
3. istft 段：eager（cuFFT）
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
sg2 = h.m_source.l_sin_gen
for attr in ("rand_ini", "sine_waves", "uv"):
    buf = getattr(sg2, attr, None)
    if buf is not None and buf.device.type == "cpu":
        setattr(sg2, attr, buf.to("cuda:0"))

mel = torch.rand(1, 80, 10, device="cuda:0")
upsamp = int(torch.as_tensor(h.upsample_rates).prod())
cp_look = h.conv_pre_look_right


def compute_s_stft(s):
    stft = torch.stft(s.squeeze(1), h.istft_params["n_fft"], h.istft_params["hop_len"],
                      h.istft_params["n_fft"], window=h.stft_window, return_complex=True)
    return torch.cat([stft.real, stft.imag], dim=1)


def middle(x, s_stft):
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


def istft(magnitude, phase):
    real = magnitude * torch.cos(phase)
    img = magnitude * torch.sin(phase)
    return torch.istft(torch.complex(real, img), h.istft_params["n_fft"], h.istft_params["hop_len"],
                       h.istft_params["n_fft"], window=h.stft_window)


def decode_sections(mel_in, finalize=False):
    # 等价于 CausalHiFTGenerator.inference 的 decode 段
    f0 = h.f0_predictor(mel_in, finalize=finalize)
    s = h.f0_upsamp(f0[:, None]).transpose(1, 2)
    s, _, _ = h.m_source(s)
    s = s.transpose(1, 2)
    s_stft = compute_s_stft(s)
    if finalize:
        x = h.conv_pre(mel_in)
    else:
        x = h.conv_pre(mel_in[:, :, :-cp_look], mel_in[:, :, -cp_look:])
        s_stft = s_stft[:, :, :-upsamp * cp_look]
    mag, ph = middle(x, s_stft)
    out = istft(mag, ph)
    if not finalize:
        out = out[:, :-upsamp * h.istft_params["hop_len"]]
    return out


# eager 参考（原 hift.decode）
f0 = h.f0_predictor(mel, finalize=False)
s = h.f0_upsamp(f0[:, None]).transpose(1, 2)
s, _, _ = h.m_source(s)
s = s.transpose(1, 2)
ref = h.decode(x=mel[:, :, :-h.f0_predictor.condnet[0].causal_padding], s=s, finalize=False)

# 三段式 eager 基准 + 参考
for _ in range(20):
    o = decode_sections(mel)
torch.cuda.synchronize()
t0 = time.perf_counter()
for _ in range(50):
    o = decode_sections(mel)
torch.cuda.synchronize()
print(f"three-stage eager: {(time.perf_counter()-t0)/50*1000:.1f}ms")

# graph 加速 middle
x_pre = torch.zeros(0)
s_stft_pre = torch.zeros(0)
# 准备 middle 输入
f0 = h.f0_predictor(mel, finalize=False)
s = h.f0_upsamp(f0[:, None]).transpose(1, 2)
s, _, _ = h.m_source(s)
s = s.transpose(1, 2)
s_stft = compute_s_stft(s)[:, :, :-upsamp * cp_look]
x = h.conv_pre(mel[:, :, :-cp_look], mel[:, :, -cp_look:])

# 捕获 middle 的 CUDA graph
for _ in range(10):
    m, p = middle(x, s_stft)
torch.cuda.synchronize()
g = torch.cuda.CUDAGraph()
with torch.cuda.graph(g):
    m_g, p_g = middle(x, s_stft)
torch.cuda.synchronize()
print("middle graph capture OK")

# 三段式（graph middle）基准
def decode_graph(mel_in):
    f0 = h.f0_predictor(mel_in, finalize=False)
    s = h.f0_upsamp(f0[:, None]).transpose(1, 2)
    s, _, _ = h.m_source(s)
    s = s.transpose(1, 2)
    s_stft = compute_s_stft(s)[:, :, :-upsamp * cp_look]
    x = h.conv_pre(mel_in[:, :, :-cp_look], mel_in[:, :, -cp_look:])
    g.replay()
    return istft(m_g, p_g)

for _ in range(20):
    o = decode_graph(mel)
torch.cuda.synchronize()
t0 = time.perf_counter()
for _ in range(50):
    o = decode_graph(mel)
torch.cuda.synchronize()
print(f"three-stage graph-middle: {(time.perf_counter()-t0)/50*1000:.1f}ms")

# 正确性：graph-middle vs eager decode
torch.cuda.synchronize()
print(f"graph-middle vs eager diff: {(ref - o).abs().max().item():.6f}")