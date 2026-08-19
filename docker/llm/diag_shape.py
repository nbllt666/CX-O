"""定位 hift decode 各段形状，用于 CUDA graph 加速器集成。"""
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

NUM_UPS = h.num_upsamples
UPS = h.upsample_rates  # [8,8]
with torch.no_grad():
    for mel_len in (10, 146):
        mel = torch.rand(1, 80, mel_len, device="cuda:0")
        f0 = h.f0_predictor(mel, finalize=False)
        s = h.f0_upsamp(f0[:, None]).transpose(1, 2)  # bs,n,t
        s, _, _ = h.m_source(s)
        s = s.transpose(1, 2)
        print(f"\n=== mel_len={mel_len} ===")
        print(f"s.shape={list(s.shape)}")
        real, imag = h._stft(s.squeeze(1))
        print(f"s_stft_real={list(real.shape)} imag={list(imag.shape)} n_fft={h.istft_params['n_fft']} hop={h.istft_params['hop_len']}")
        cp = h.conv_pre_look_right
        n_channels = h.istft_params["n_fft"]  # s_stft channels = n_fft+2
        x = h.conv_pre(mel[:, :, :-cp], mel[:, :, -cp:])
        print(f"after conv_pre x={list(x.shape)}")
        rs = real[:, :, :-int(torch.tensor(UPS).prod()) * cp]
        ims = imag[:, :, :-int(torch.tensor(UPS).prod()) * cp]
        print(f"stft real truncated={list(rs.shape)}")
        s_stft = torch.cat([rs, ims], dim=1)
        # 逐 up 阶段融合形状
        for i in range(NUM_UPS):
            x = torch.nn.functional.leaky_relu(x, h.lrelu_slope)
            x = h.ups[i](x)
            if i == NUM_UPS - 1:
                x = h.reflection_pad(x)
            si = h.source_downs[i](s_stft)
            print(f"up{i}: x={list(x.shape)} si={list(si.shape)} stride_s_down={h.source_downs[i].stride if hasattr(h.source_downs[i],'stride') else h.source_downs[i].stride}")
            # source_resblocks
            si = h.source_resblocks[i](si)
            x = x + si
            xs = None
            for j in range(h.num_kernels):
                r = h.resblocks[i * h.num_kernels + j](x)
                xs = r if xs is None else xs + r
            x = xs / h.num_kernels