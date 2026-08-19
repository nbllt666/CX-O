"""monkey-patch CausalHiFTGenerator.decode 打印首 hop 中间各步形状，用于 CUDA graph 对齐。"""
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

# 复刻 server 补丁
import torch.nn.utils.parametrize as parametrize
for m in h.modules():
    try:
        if parametrize.is_parametrized(m, "weight"):
            parametrize.remove_parametrizations(m, "weight")
    except Exception:
        pass

print(f"upsample_rates={h.upsample_rates} conv_pre_look_right={h.conv_pre_look_right}")
for i, sd in enumerate(h.source_downs):
    print(f"source_downs[{i}]: kernel={sd.kernel_size} stride={sd.stride} padding={sd.padding}")
for i, sd in enumerate(h.source_resblocks):
    print(f"source_resblocks[{i}] ok")
print(f"num_upsamples={h.num_upsamples} num_kernels={h.num_kernels}")

# 打印 decode 各步形状（mel=10 首 hop）
orig_decode = h.decode
def patched_decode(self, x, s=torch.zeros(1,1,0), finalize=True):
    s_stft_real, s_stft_imag = self._stft(s.squeeze(1))
    print(f"  [decode] s_stft_real={list(s_stft_real.shape)} x_in={list(x.shape)} finalize={finalize}")
    if finalize is True:
        xc = self.conv_pre(x)
    else:
        xc = self.conv_pre(x[:, :, :-self.conv_pre_look_right], x[:, :, -self.conv_pre_look_right:])
        s_stft_real = s_stft_real[:, :, :-int(torch.tensor(self.upsample_rates).prod()) * self.conv_pre_look_right]
        s_stft_imag = s_stft_imag[:, :, :-int(torch.tensor(self.upsample_rates).prod()) * self.conv_pre_look_right]
    s_stft = torch.cat([s_stft_real, s_stft_imag], dim=1)
    print(f"  after conv_pre xc={list(xc.shape)} s_stft={list(s_stft.shape)}")
    x = xc
    for i in range(self.num_upsamples):
        x = torch.nn.functional.leaky_relu(x, self.lrelu_slope)
        x = self.ups[i](x)
        if i == self.num_upsamples - 1:
            x = self.reflection_pad(x)
        # fusion
        si = self.source_downs[i](s_stft)
        si_in = si
        si = self.source_resblocks[i](si)
        print(f"  up{i}: x={list(x.shape)} source_downs out={list(si_in.shape)} resblock out={list(si.shape)}")
        x = x + si
        xs = None
        for j in range(self.num_kernels):
            if xs is None:
                xs = self.resblocks[i * self.num_kernels + j](x)
            else:
                xs += self.resblocks[i * self.num_kernels + j](x)
        x = xs / self.num_kernels
    x = torch.nn.functional.leaky_relu(x)
    x = self.conv_post(x)
    magnitude = torch.exp(x[:, :self.istft_params["n_fft"] // 2 + 1, :])
    phase = torch.sin(x[:, self.istft_params["n_fft"] // 2 + 1:, :])
    x = self._istft(magnitude, phase)
    if finalize is False:
        x = x[:, :-int(torch.tensor(self.upsample_rates).prod()) * self.istft_params['hop_len']]
    x = torch.clamp(x, -self.audio_limit, self.audio_limit)
    return x
h.decode = patched_decode.__get__(h, type(h))

# mel=10（首 hop）
mel10 = torch.rand(1, 80, 10, device="cuda:0")
f0 = h.f0_predictor(mel10, finalize=False)
s = h.f0_upsamp(f0[:, None]).transpose(1, 2)
s, _, _ = h.m_source(s)
s = s.transpose(1, 2)
print("=== mel=10 decode ===")
out = h.decode(mel10[:, :, :-h.f0_predictor.condnet[0].causal_padding], s=s, finalize=False)
print(f"output={list(out.shape)} causal_padding={h.f0_predictor.condnet[0].causal_padding}")