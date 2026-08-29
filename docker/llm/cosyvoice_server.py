"""CosyVoice3-0.5B OpenAI 兼容服务层（Task 1 交付物：CosyVoice3 主运行时）。

将官方 CosyVoice3-0.5B（cosyvoice.cli.cosyvoice.CosyVoice2/CosyVoice3，按 model_dir 推断）封装为 OpenAI 兼容的
/v1/audio/speech 接口，供后端 Qwen3TTSProvider 以 HTTP 方式调用。

请求形态（OpenAI 兼容 + 扩展）:
    POST /v1/audio/speech
    {
        "model": "Fun-CosyVoice3-0.5B-2512",
        "input": "要合成的文本",
        "voice": "参考音频资产（可选，与 ref_audio 二选一）",
        "ref_audio": "参考音频 data URL（可选，零样本克隆）",
        "ref_text": "参考音频转写（可选，提升克隆质量）",
        "instructions": "情感/风格指令文本（instruct2 路径）",
        "response_format": "wav",
        "stream": false,
        "speed": 1.0
    }

响应: audio/wav（CosyVoice 原生 22050Hz -> 重采样统一输出 24kHz）

运行时模式:
- 携带 ref_audio（有参考音频）:
    * 有 instructions -> inference_instruct2（克隆 + 情感指令）
    * 无 instructions  -> inference_zero_shot（零样本克隆）
- 无 ref_audio（有 voice 资产名）: 走 assets 目录的参考音频，同上两条路径
- 无任何参考音频: 返回 422（CosyVoice 无 refs 需 SFT 预训练音色，本服务不承载 SFT）

CosyVoice3 关键适配（Task 8 变更）:
- prompt_text 须含 <|endofprompt|>（token 151646），服务层自动补全
  "You are a helpful assistant.<|endofprompt|>" 前缀，否则前端断言报错。
- CUDA graph patch 对 CosyVoice3LM 生效：sos/task_id 嵌入取自 speech_embedding。
- 预热用 1s 正弦波 ref（speech_tokenizer_v3 对静音提取 token 过短会导致 flow Conv 失败）。

Speaker 嵌入缓存（极端优化项）:
- 参考音频内容哈希命名（spk_{sha1[:16]}），经 add_zero_shot_spk 注册到
  frontend.spk2info 缓存（zero_shot_spk_id=spk_{hash}），重复 ref 跳过
  campplus + speech_tokenizer_v3 特征重提取。

运行:
    <cosyvoice-venv>/python cosyvoice_server.py --model_dir C:\\CX-O\\models\\Fun-CosyVoice3-0.5B-2512 \\
        --host 127.0.0.1 --port 8094 --device cuda:0 --bf16 --stream-hop-len 10
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import io
import os
import re
import sys
import threading
import time
import wave

import numpy as np

from fastapi import Request
from fastapi.responses import JSONResponse, Response, StreamingResponse


def _decode_data_url(data_url: str) -> bytes:
    """解码 data:audio/...;base64,XXXX 为原始字节。"""
    if data_url.startswith("data:"):
        m = re.match(r"data:[^,]*;base64,(.*)", data_url, re.S)
        if m:
            return base64.b64decode(m.group(1))
    return base64.b64decode(data_url)


# 统一合成链路输出采样率（speech_synthesis_response.schema.json const 24000）
SYNTH_SAMPLE_RATE = 24000
# CosyVoice2 原生输出采样率
COSYVOICE_NATIVE_SAMPLE_RATE = 22050


def _resample_linear(samples: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    """对 float32 单声道数组做线性插值重采样（src_rate -> dst_rate）。"""
    if src_rate == dst_rate or samples.size == 0:
        return samples
    n = samples.size
    out_len = max(1, int(round(n * dst_rate / src_rate)))
    pos = np.linspace(0.0, float(n - 1), num=out_len)
    j = np.floor(pos).astype(np.int64)
    frac = pos - j
    j = np.clip(j, 0, n - 1)
    k = np.clip(j + 1, 0, n - 1)
    return samples[j] * (1.0 - frac) + samples[k] * frac


def _encode_wav(sr: int, wav: np.ndarray, volume: float = 1.0) -> bytes:
    """将 float32/(samples,) 单声道归一化为 int16 并用标准库 wave 写 WAV（统一 24kHz）。"""
    wav = np.asarray(wav, dtype=np.float32).reshape(-1)
    if sr != SYNTH_SAMPLE_RATE:
        wav = _resample_linear(wav, int(sr), SYNTH_SAMPLE_RATE)
        sr = SYNTH_SAMPLE_RATE
    # 非流式整段：峰值归一化（全局视角，响度充足且无削波）+ 音量倍率
    wav = _normalize_loudness(wav, mode="peak", volume=volume)
    wav16 = (wav * 32767.0).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(int(sr))
        wf.writeframes(wav16.tobytes())
    return buf.getvalue()


def _make_wav_header(sr: int, data_size: int) -> bytes:
    """构造 44 字节 WAV 头（PCM16 单声道）。流式时 data_size 未知传 0xFFFFFFFF。"""
    import struct

    block_align = 2
    byte_rate = int(sr) * block_align
    # 流式未知大小标记（0xFFFFFFFF）时 RIFF size 直接用原值，避免 36+ 溢出 32 位无符号
    riff_size = data_size if data_size == 0xFFFFFFFF else 36 + data_size
    return struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", riff_size, b"WAVE",
        b"fmt ", 16, 1, 1, int(sr), byte_rate, block_align, 16,
        b"data", data_size,
    )


_TTS_TARGET_PEAK = 0.85     # 非流式（整段）峰值归一化目标：85%满幅≈-1.4dBFS，响度充足留安全余量
_TTS_FIXED_GAIN = 45.0      # 流式固定增益：CosyVoice3 原生 peak≈0.01~0.02，×45后≈0.45~0.90（块间稳定无呼吸效应）
_TTS_ABS_LIMIT = 0.98       # 绝对硬上限（clamp 到 ±0.98，绝不允许 int16 满幅削波）
_TTS_SILENCE_PEAK = 0.0001  # 流式静音判定阈值（低于此值不放大，防底噪抬升）


def _normalize_loudness(t: np.ndarray, target: float = _TTS_TARGET_PEAK, *, mode: str = "peak", volume: float = 1.0) -> np.ndarray:
    """响度归一化，双模式 + 音量倍率：

    - mode="peak"（非流式整段）：按全局峰值归一化到 target×volume，整段视角最准确。
    - mode="fixed"（流式逐块）：统一乘 FIXED_GAIN×volume，块间增益一致无"呼吸效应"。

    volume∈(0, 2]：LLM 音量标签（volume=0.5 → 轻声，目标电平减半；volume=1.5 → 洪亮）。
    任何模式最终都会硬 clamp 到 ±_TTS_ABS_LIMIT，杜绝 int16 满幅削波。
    """
    if t is None or t.size == 0:
        return t
    volume = float(volume)
    if volume <= 0:
        volume = 1.0
    if mode == "fixed":
        # 流式：仅对完全静音块跳过，避免底噪；非静音块统一增益，保证块间听感连续
        peak = float(np.abs(t).max())
        if peak < _TTS_SILENCE_PEAK:
            return t
        t = t * (_TTS_FIXED_GAIN * volume)
    else:
        # 非流式：整段峰值归一化（一次全量，能看到全局 peak，最准）
        peak = float(np.abs(t).max())
        if peak < _TTS_SILENCE_PEAK:
            return t
        gain = (target * volume) / peak
        t = t * gain
    t = np.clip(t, -_TTS_ABS_LIMIT, _TTS_ABS_LIMIT)
    return t


async def _stream_wav_pcm(gen, native_sr: int, volume: float = 1.0):
    """流式响应体：先发 44 字节 WAV 头（24k/16bit/mono），再逐段发 PCM16。

    CosyVoice 原生 22050Hz -> 重采样统一输出 24kHz；后端 Provider 流式读取时跳过
    前 44 字节 WAV 头，将后续 PCM 作为音频块（与 _synthesize_stream_once 的 skip 逻辑对齐）。

    async generator：sync generator 在 Windows/uvicorn 下首个 send 有线程池+缓冲延迟
    （实测 headers 首包 8.4s），async 迭代直接在事件循环中执行，首包即时下发。
    """
    _t0 = time.monotonic()
    _first = True
    yield _make_wav_header(SYNTH_SAMPLE_RATE, 0xFFFFFFFF)
    for out in gen:
        speech = out["tts_speech"]
        t = speech.detach().cpu().numpy()
        if t.ndim == 2:
            t = t.mean(axis=0)
        t = np.asarray(t, dtype=np.float32).reshape(-1)
        if _first:
            print(f"[CosyVoice] first audio at {time.monotonic()-_t0:.2f}s len={t.size/SYNTH_SAMPLE_RATE:.2f}s")
            _first = False
        if t.size == 0:
            continue
        if native_sr != SYNTH_SAMPLE_RATE:
            t = _resample_linear(t, int(native_sr), SYNTH_SAMPLE_RATE)
        t = _normalize_loudness(t, mode="fixed", volume=volume)
        yield (t * 32767.0).astype(np.int16).tobytes()
        # 让事件循环有机会切换（async generator 内不阻塞，防止 CPU 密集段长时间占用循环）
        await asyncio.sleep(0)


async def _stream_wav_pcm_keepalive(gen, native_sr: int, volume: float = 1.0):
    """流式响应包装：_stream_wav_pcm + GPU 保活信号复位。

    speech handler 在请求开始对 _active_count 计数 +1（暂停保活 GEMM 与请求
    竞争），流式响应在后台逐块生成，此处 finally 保证流式结束（含客户端断开/
    异常）后计数 -1；计数归零（count==0）即恢复保活——并发流式下每请求只减
    自己的份额，不会提前恢复。详见 .trae/documents/20260817_模块0_GPU保活增强消除降频.md
    """
    try:
        async for chunk in _stream_wav_pcm(gen, native_sr, volume=volume):
            yield chunk
    finally:
        # 流式结束（含断开/异常）：请求计数 -1，归零后恢复保活
        _active_count -= 1


def _load_wav_bytes(raw: bytes, target_sr: int = 16000):
    """从原始字节加载音频并重采样到 target_sr（CosyVoice prompt 需 16k）。

    用 soundfile 库读取（避免 torchaudio 2.11 对某些 wav 默认走 torchcodec backend 的兼容问题）。
    """
    import io as _io

    import soundfile as _sf

    buf = _io.BytesIO(raw)
    speech, sample_rate = _sf.read(buf, dtype="float32")  # (samples,) or (samples, channels)
    if speech.ndim > 1:
        speech = speech.mean(axis=1)
    speech = speech.reshape(1, -1)  # (1, samples)
    if sample_rate != target_sr:
        import torch
        import torchaudio

        assert sample_rate >= target_sr, (
            "wav sample rate {} must be greater than {}".format(sample_rate, target_sr)
        )
        speech = torchaudio.transforms.Resample(orig_freq=sample_rate, new_freq=target_sr)(
            torch.from_numpy(speech)
        )
    else:
        import torch

        speech = torch.from_numpy(speech)
    return speech


def _synth_chunks(gen):
    """把 CosyVoice 推理 generator 的 tts_speech 逐段聚合为 (sr, np.float32 一维数组)。"""
    sr = None
    parts = []
    for out in gen:
        speech = out["tts_speech"]  # (1, samples) 或 (channels, samples) tensor
        t = speech.detach().cpu().numpy()
        if t.ndim == 2:
            t = t.mean(axis=0)
        t = np.asarray(t, dtype=np.float32).reshape(-1)
        parts.append(t)
        if sr is None:
            sr = int(cosyvoice.sample_rate)
    if not parts:
        return sr, np.zeros(0, dtype=np.float32)
    return sr, np.concatenate(parts)


def _patch_load_wav() -> None:
    """用 soundfile 库实现替换 CosyVoice 的 load_wav（绕过 torchaudio 2.11 的 torchcodec DLL 依赖）。

    torchaudio 2.11 在 Windows 上 soundfile backend 不可用且 torchcodec DLL 加载失败，
    故用 soundfile 库读取（纯 Python，无 DLL 依赖），并将 file_utils 与 cli.frontend 两处引用统一替换。
    须在 AutoModel 构造（frontend 初始化）前调用。
    """
    import cosyvoice.cli.frontend as _frontend
    import cosyvoice.utils.file_utils as _file_utils

    def _load_wav_soundfile(wav, target_sr, min_sr=16000):
        import io as _io

        import soundfile as _sf
        import torch

        # 输入已是 tensor（CosyVoice 内部第二次调用 load_wav 时传入的是上次返回值）
        if isinstance(wav, torch.Tensor):
            return wav
        if isinstance(wav, (str, os.PathLike)):
            speech, sample_rate = _sf.read(str(wav), dtype="float32")
        else:
            speech, sample_rate = _sf.read(_io.BytesIO(wav.read()), dtype="float32")
        if speech.ndim > 1:
            speech = speech.mean(axis=1)
        speech = speech.reshape(1, -1)
        if sample_rate != target_sr:
            assert sample_rate >= min_sr, (
                "wav sample rate {} must be greater than {}".format(sample_rate, target_sr)
            )
            import torchaudio

            speech = torchaudio.transforms.Resample(orig_freq=sample_rate, new_freq=target_sr)(
                torch.from_numpy(speech)
            )
        else:
            speech = torch.from_numpy(speech)
        return speech

    _file_utils.load_wav = _load_wav_soundfile
    _frontend.load_wav = _load_wav_soundfile


def _patch_campplus_gpu(cv) -> None:
    """将 campplus ONNX 会话重建为 GPU provider（原代码硬编码 CPUExecutionProvider）。

    在 AutoModel 构造完成后调用；失败时回退 CPU 不影响功能。
    """
    try:
        import onnxruntime as _ort
        import torch as _torch

        if _torch.cuda.is_available():
            _opts = _ort.SessionOptions()
            _opts.graph_optimization_level = _ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            _opts.intra_op_num_threads = 1
            model_dir = getattr(cv, "model_dir", None)
            if not model_dir:
                return
            cv.frontend.campplus_session = _ort.InferenceSession(
                os.path.join(model_dir, "campplus.onnx"),
                sess_options=_opts,
                providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
            )
            print("[Patch] campplus ONNX -> CUDAExecutionProvider")
    except Exception as exc:
        print(f"[WARN] campplus GPU patch failed (fallback CPU): {exc}")


def _patch_flow_steps(cv, steps: int) -> bool:
    """将 cv.model.flow.decoder 的 ODE 求解步数覆盖为指定值。

    token2wav 首 hop 的 flow matching 推理步数（默认 10 步）是 TTFT 主要成本之一。
    5 步可将首个 flow 推理时间减半（质量略降）。通过 monkey-patch decoder.forward 实现。
    """
    try:
        decoder = cv.model.flow.decoder
        original = decoder.forward
        steps = max(1, int(steps))

        def _patched_forward(self, mu, mask, n_timesteps, temperature=1.0, spks=None, cond=None, **kwargs):
            if int(n_timesteps) == 10:
                n_timesteps = steps
            return original(mu, mask, n_timesteps, temperature=temperature, spks=spks, cond=cond, **kwargs)

        import types as _t
        decoder.forward = _t.MethodType(_patched_forward, decoder)
        print(f"[Patch] flow decoder n_timesteps -> {steps}")
        return True
    except Exception as exc:
        print(f"[WARN] flow steps patch failed (keep default 10): {exc}")
        return False


def _patch_llm_cudagraph(cv) -> bool:
    """将 cv.model.llm_job 替换为 CUDA graph + StaticCache 加速路径。

    在 AutoModel 构造完成后、预热前调用。失败时静默回退原始 llm_job 实现。
    返回 True 表示集成成功，False 表示回退。
    """
    try:
        import threading as _threading
        import types as _types

        import torch as _torch
        from transformers import StaticCache as _StaticCache

        from cosyvoice.llm.llm import Qwen2LM as _Qwen2LM
        from cosyvoice.llm.llm import CosyVoice3LM as _CosyVoice3LM

        llm = cv.model.llm
        if not isinstance(llm, _Qwen2LM):
            print("[WARN] LLM CUDA graph patch: not Qwen2LM, skipping")
            return False
        if not _torch.cuda.is_available():
            print("[WARN] LLM CUDA graph patch: CUDA not available, skipping")
            return False

        # CosyVoice3LM 与 Qwen2LM 的 sos/task_id 嵌入来源不同（speech_embedding vs llm_embedding）
        _is_cv3 = isinstance(llm, _CosyVoice3LM)

        device = cv.model.device
        config = llm.llm.model.config
        hidden_size = config.hidden_size
        max_cache_len = 512

        # 0. 用全向量化 GPU 采样替换 nucleus_sampling（消除 Python 循环逐元素 GPU 标量访问）
        #    原实现每个 token 做 ≤top_k 次 sorted_value[i] 标量读取（每次 GPU->CPU 同步），
        #    是 LLM 逐 token ~22ms 的主因；向量化后仅 1 次 .item() 同步。
        def _fast_nucleus(weighted_scores, top_p=0.8, top_k=25):
            probs = weighted_scores.softmax(dim=0)
            sorted_value, sorted_idx = probs.sort(descending=True, stable=True)
            cumsum_before = _torch.cumsum(sorted_value, dim=0) - sorted_value
            idx_arange = _torch.arange(sorted_idx.numel(), device=weighted_scores.device)
            # 原语义：累计概率（不含当前项）< top_p 且计数 < top_k；至少保留 top-1
            mask = ((idx_arange < top_k) & (cumsum_before < top_p)) | (idx_arange == 0)
            selected = sorted_idx[mask]
            p = sorted_value[mask]
            return int(selected[p.multinomial(1, replacement=True)].item())

        def _fast_ras(weighted_scores, decoded_tokens, sampling, top_p=0.8, top_k=25, win_size=10, tau_r=0.1):
            top_ids = _fast_nucleus(weighted_scores, top_p=top_p, top_k=top_k)
            rep_num = (_torch.tensor(decoded_tokens[-win_size:], device=weighted_scores.device) == top_ids).sum().item()
            if rep_num >= win_size * tau_r:
                weighted_scores[top_ids] = -float('inf')
                top_ids = int(weighted_scores.softmax(dim=0).multinomial(1, replacement=True).item())
            return top_ids

        def _fast_sampling_ids(self, weighted_scores, decoded_tokens, sampling, ignore_eos=True):
            if ignore_eos:
                weighted_scores[self.speech_token_size] = -float('inf')
            return self.sampling(weighted_scores, decoded_tokens, sampling)

        llm.sampling = _fast_ras
        llm.sampling_ids = _types.MethodType(_fast_sampling_ids, llm)
        print("[Patch] LLM sampling -> vectorized GPU (fast nucleus/ras)")

        # 1. StaticCache（固定长度 512，与验证脚本一致）
        cache = _StaticCache(config, max_batch_size=1, max_cache_len=max_cache_len,
                             device=device, dtype=_torch.bfloat16)

        # 2. 固定输入 buffer
        inp_buf = _torch.zeros((1, 1, hidden_size), dtype=_torch.bfloat16, device=device)
        cache_pos_buf = _torch.zeros((1,), dtype=_torch.long, device=device)

        # 3. 捕获 CUDA graph（3 次 warmup + 1 次 capture，与验证脚本一致）
        graph = _torch.cuda.CUDAGraph()
        s = _torch.cuda.Stream()
        s.wait_stream(_torch.cuda.current_stream())
        with _torch.cuda.stream(s):
            for _ in range(3):
                with _torch.inference_mode(), _torch.cuda.amp.autocast(True):
                    llm.llm.model(
                        inputs_embeds=inp_buf, cache_position=cache_pos_buf,
                        past_key_values=cache, use_cache=True, output_hidden_states=True,
                    )
        _torch.cuda.current_stream().wait_stream(s)
        with _torch.cuda.graph(graph):
            with _torch.inference_mode(), _torch.cuda.amp.autocast(True):
                _out = llm.llm.model(
                    inputs_embeds=inp_buf, cache_position=cache_pos_buf,
                    past_key_values=cache, use_cache=True, output_hidden_states=True,
                )
        hidden_buf = _out.hidden_states[-1]  # graph 输出 buffer: (1, 1, 896)
        _torch.cuda.synchronize()

        # 4. 存储 extras
        cv.model.__cudagraph_extra = {
            'cache': cache,
            'inp_buf': inp_buf,
            'cache_pos_buf': cache_pos_buf,
            'graph': graph,
            'hidden_buf': hidden_buf,
            'max_cache_len': max_cache_len,
            'lock': _threading.Lock(),
        }

        # 5. 替换 llm_job（保存原始引用，失败时回退）
        _original_llm_job = cv.model.llm_job

        def _patched_llm_job(self, text, prompt_text, llm_prompt_speech_token, llm_embedding, uuid):
            """CUDA graph + StaticCache 加速的 llm_job；异常/溢出时回退原始实现。"""
            appended_before = len(self.tts_speech_token_dict.get(uuid, []))
            try:
                extra = self.__cudagraph_extra
                _llm = self.llm
                _device = self.device

                # ---- 构建 lm_input（与 Qwen2LM.inference 一致） ----
                text_combined = _torch.concat([prompt_text, text], dim=1)
                text_emb = _llm.llm.model.model.embed_tokens(text_combined.to(_device))
                if _is_cv3:
                    # CosyVoice3LM：sos/task_id 嵌入取自 speech_embedding（无 llm_embedding）
                    sos_emb = _llm.speech_embedding.weight[_llm.sos].reshape(1, 1, -1)
                    task_id_emb = _llm.speech_embedding.weight[_llm.task_id].reshape(1, 1, -1)
                else:
                    sos_emb = _llm.llm_embedding.weight[_llm.sos].reshape(1, 1, -1)
                    task_id_emb = _llm.llm_embedding.weight[_llm.task_id].reshape(1, 1, -1)
                if llm_prompt_speech_token.shape[1] != 0:
                    prompt_speech_token_emb = _llm.speech_embedding(llm_prompt_speech_token.to(_device))
                else:
                    prompt_speech_token_emb = _torch.zeros(
                        1, 0, _llm.llm_input_size, dtype=text_emb.dtype, device=_device,
                    )
                lm_input = _torch.concat([sos_emb, text_emb, task_id_emb, prompt_speech_token_emb], dim=1)

                # ---- 计算 min/max length（与 Qwen2LM.inference 一致） ----
                tts_text_len = int(text.shape[1])
                min_len = tts_text_len * 2
                max_len = tts_text_len * 20

                # ---- 缓存容量保护：最小 token 数放不下则回退 ----
                # eager fallback 与 graph replay 共享同一 LLM/StaticCache，须与 graph 路径
                # 同锁（extra['lock']）串行，防止与其他请求跨线程并发 forward。
                _prefill_len = lm_input.shape[1]
                if _prefill_len + min_len > extra['max_cache_len']:
                    print("[WARN] LLM CUDA graph: prefill too long, fallback original")
                    with extra['lock']:
                        return _original_llm_job(text, prompt_text, llm_prompt_speech_token, llm_embedding, uuid)

                _cache = extra['cache']
                _inp_buf = extra['inp_buf']
                _cache_pos_buf = extra['cache_pos_buf']
                _graph = extra['graph']
                _hidden_buf = extra['hidden_buf']

                # ---- StaticCache prefill + 解码循环（在 llm_context stream 上，与 token2wav 并发） ----
                out_tokens = []
                pos = _prefill_len
                cur_silent_token_num, max_silent_token_num = 0, 5
                _t_dec_start = time.monotonic()

                with extra['lock'], self.llm_context, _torch.inference_mode(), _torch.cuda.amp.autocast(True):
                    # prefill（eager，长度可变）
                    _cache_position = _torch.arange(0, _prefill_len, device=_device)
                    _out_prefill = _llm.llm.model(
                        inputs_embeds=lm_input, cache_position=_cache_position,
                        past_key_values=_cache, use_cache=True, output_hidden_states=True,
                    )
                    _t_prefill_done = time.monotonic()
                    # 第一个 token 从 prefill 输出采样（与原版 inference 的 i=0 步一致，避免 zero 输入偏差）
                    prefill_hidden = _out_prefill.hidden_states[-1][:, -1].float()
                    logp0 = _llm.llm_decoder(prefill_hidden).log_softmax(dim=-1)
                    first_top = _llm.sampling_ids(logp0.squeeze(dim=0), out_tokens, 25, ignore_eos=True)
                    if first_top in _llm.stop_token_ids:
                        self.llm_end_dict[uuid] = True
                        return
                    out_tokens.append(first_top)
                    _inp_buf.copy_(_llm.speech_embedding.weight[first_top].reshape(1, 1, -1).to(_torch.bfloat16))
                    if first_top in self.silent_tokens:
                        cur_silent_token_num += 1
                    if cur_silent_token_num <= max_silent_token_num:
                        self.tts_speech_token_dict[uuid].append(first_top)

                    # decode（graph replay + 采样 + 新 token 写入，从 position P 起）
                    for i in range(1, max_len):
                        if pos >= extra['max_cache_len']:
                            break  # 缓存越界保护
                        _cache_pos_buf.copy_(_torch.tensor([pos], device=_device))
                        _graph.replay()
                        hidden = _hidden_buf[:, -1].float()  # (1, 896)
                        logp = _llm.llm_decoder(hidden).log_softmax(dim=-1)
                        top_ids = _llm.sampling_ids(
                            logp.squeeze(dim=0), out_tokens, 25,
                            ignore_eos=True if i < min_len else False,
                        )
                        if top_ids in _llm.stop_token_ids:
                            break
                        out_tokens.append(top_ids)
                        _inp_buf.copy_(_llm.speech_embedding.weight[top_ids].reshape(1, 1, -1).to(_torch.bfloat16))
                        pos += 1
                        # 静音 token 过滤（仅影响 tts_speech_token_dict，不影响输入推进）
                        if top_ids in self.silent_tokens:
                            cur_silent_token_num += 1
                            if cur_silent_token_num > max_silent_token_num:
                                continue
                        else:
                            cur_silent_token_num = 0
                        self.tts_speech_token_dict[uuid].append(top_ids)

                _t_decode_done = time.monotonic()
                self.llm_end_dict[uuid] = True
                print(f"[Patch] llm_job: prefill={( _t_prefill_done - _t_dec_start)*1000:.0f}ms "
                      f"decode={(_t_decode_done - _t_prefill_done)*1000:.0f}ms tokens={len(out_tokens)} "
                      f"rate={len(out_tokens)/max((_t_decode_done - _t_prefill_done), 1e-6):.0f}/s")

            except Exception as exc:
                appended = len(self.tts_speech_token_dict.get(uuid, [])) - appended_before
                if appended == 0:
                    # 未产出 token，可安全回退原始实现（eager 同样持 extra['lock']，
                    # 防止与其他请求的 graph replay / eager forward 跨线程并发）
                    print(f"[WARN] LLM CUDA graph decode failed (fallback original): {exc}")
                    with extra['lock']:
                        return _original_llm_job(text, prompt_text, llm_prompt_speech_token, llm_embedding, uuid)
                # 已产出部分 token：回退会重复，直接标记结束避免 tts() 挂起
                print(f"[WARN] LLM CUDA graph decode aborted after {appended} tokens: {exc}")
                self.llm_end_dict[uuid] = True

        cv.model.llm_job = _types.MethodType(_patched_llm_job, cv.model)
        return True

    except Exception as exc:
        print(f"[WARN] LLM CUDA graph patch failed (fallback original): {exc}")
        return False


# ============================================================================
# FastAPI 应用
# ============================================================================
def create_app():
    import fastapi

    # 按 model_dir 推断展示名（cosyvoice2.yaml / cosyvoice3.yaml / cosyvoice.yaml）
    _model_name = "CosyVoice2-0.5B"
    if args and args.model_dir:
        if os.path.exists(os.path.join(args.model_dir, "cosyvoice3.yaml")):
            _model_name = "Fun-CosyVoice3-0.5B-2512"
        elif os.path.exists(os.path.join(args.model_dir, "cosyvoice.yaml")):
            _model_name = "CosyVoice-300M"

    app = fastapi.FastAPI(title="CosyVoice OpenAI-compatible TTS")

    @app.get("/health")
    async def health():
        if cosyvoice is None:
            return JSONResponse(status_code=503, content={"status": "unhealthy"})
        return {"status": "healthy", "model": _model_name}

    @app.get("/v1/models")
    async def models():
        return {"object": "list", "data": [{"id": _model_name, "object": "model"}]}

    @app.post("/v1/audio/speech")
    async def speech(request: Request):
        try:
            data = await request.json()
        except Exception:
            data = dict(await request.form())
        text = str(data.get("input") or data.get("text") or "").strip()
        if not text:
            return JSONResponse(status_code=400, content={"error": {"message": "input is required"}})

        # Provider 发送 ref_audio 为列表（兼容多来源），取第一项
        ref_audio = data.get("ref_audio") or data.get("voice_audio")
        if isinstance(ref_audio, list):
            ref_audio = ref_audio[0] if ref_audio else None
        voice = data.get("voice")
        ref_text = data.get("ref_text") or data.get("ref_transcript") or ""
        # Provider 发送 ref_text 为列表（与被兼容的 ref_audio 一致，兼容多来源），取第一项；
        # 否则 str(list) 会得到 "['文本']" 畸形 ref_text，导致克隆 prompt 崩坏、输出满幅削波噪声。
        if isinstance(ref_text, list):
            ref_text = ref_text[0] if ref_text else ""
        ref_text = str(ref_text)
        instruction = data.get("instructions") or data.get("voice_description") or data.get("emo_text")
        stream = bool(data.get("stream", False))
        speed = float(data.get("speed", 1.0) or 1.0)
        volume = float(data.get("volume", 1.0) or 1.0)
        if volume <= 0:
            volume = 1.0

        # CosyVoice3 要求 prompt_text 含 <|endofprompt|>（token 151646），自动补全
        _is_cv3 = hasattr(cosyvoice, "model") and "CosyVoice3" in type(cosyvoice.model).__name__
        if _is_cv3 and ref_text and "<|endofprompt|>" not in ref_text:
            ref_text = "You are a helpful assistant.<|endofprompt|>" + ref_text

        # 参考音频来源：ref_audio（data URL/路径）优先，其次 voice（资产名）
        # 注意：以下整段同步推理（ref 解析 + speaker 注册 + 推理 gen + 全量合成）原本
        # 都在 async 事件循环内执行，阻塞 /health 与并发请求。现统一挪入 asyncio.to_thread
        # 后台线程执行，并用 _SYNTH_LOCK 串行化对共享模型的访问（防卸载后模型竞争）。
        def _prepare_clone():
            pw = None
            zid = ""
            if ref_audio:
                raw = _decode_data_url(ref_audio)
                h = hashlib.sha1(raw).hexdigest()[:16]
                zid = f"spk_{h}"
                pw = _load_wav_bytes(raw, 16000)
            elif voice:
                spk_path = os.path.join(args.assets_dir, f"{voice}.wav")
                if not os.path.exists(spk_path):
                    raise _SpeechHttpError(422, f"voice asset not found: {voice}")
                with open(spk_path, "rb") as f:
                    raw = f.read()
                h = hashlib.sha1(raw).hexdigest()[:16]
                zid = f"spk_{h}"
                pw = _load_wav_bytes(raw, 16000)
            if pw is None:
                raise _SpeechHttpError(422, "CosyVoice3 requires ref_audio/voice for cloning")
            return pw, zid

        # cross_lingual 模式用「仅含 <|endofprompt|> 标记」的 prompt_text，避免参考转写被念出
        _spk_prompt = (
            "You are a helpful assistant.<|endofprompt|>"
            if args.zero_shot_mode == "cross_lingual"
            else ref_text
        )

        def _create_gen(pw, zid):
            # speaker 嵌入缓存：同内容 ref 首次注册，后续命中 frontend.spk2info
            if zid not in cosyvoice.frontend.spk2info:
                cosyvoice.add_zero_shot_spk(_spk_prompt, pw, zid)
            if instruction:
                return cosyvoice.inference_instruct2(
                    text, str(instruction), pw, zero_shot_spk_id=zid,
                    stream=stream, speed=speed,
                )
            if args.zero_shot_mode == "cross_lingual":
                return cosyvoice.inference_zero_shot(
                    text, _spk_prompt, pw, zero_shot_spk_id=zid,
                    stream=stream, speed=speed,
                )
            return cosyvoice.inference_zero_shot(
                text, ref_text, pw, zero_shot_spk_id=zid,
                stream=stream, speed=speed,
            )

        t0 = time.monotonic()
        _t_parse_done = t0
        # 请求进行中：请求计数 +1 暂停 GPU 保活（保活 GEMM 与真实请求竞争算力，
        # 详见 .trae/documents/20260817_模块0_GPU保活增强消除降频.md）。
        # 并发流式语义：多请求重叠时计数累加，先结束的请求只减自己的份额，
        # 全部结束（count==0）后才恢复保活 GEMM。
        _active_count += 1
        try:
            # CosyVoice3 的 LLM 会把 prompt_text + text 拼接后整体生成语音（llm.py concat）。
            # 参考转写文本若进入 prompt_text 会被念出来（回声/前缀问题）。
            # cross_lingual 模式改用「仅含 <|endofprompt|> 标记」的 prompt_text：
            #   1) 满足 vLLM 引擎对 <|endofprompt|>（token 151646）的强制断言；
            #   2) prompt_text 不含参考转写文本 → 模型只念目标文本，不再回声。
            if stream:
                # 流式：在后台线程完成 ref 解析 + speaker 注册 + 推理 gen 构造；
                # 逐块合成仍由弱网异步生成器承担（每块 await asyncio.sleep(0) 让出循环）。
                def _stream_prep():
                    with _SYNTH_LOCK:
                        pw, zid = _prepare_clone()
                        gen = _create_gen(pw, zid)
                    return gen, zid

                gen, zero_shot_spk_id = await asyncio.to_thread(_stream_prep)
            else:
                # 非流式：整段（ref 解析 + speaker 注册 + gen 构造 + 全量合成）在线程内完成
                def _full_synth():
                    with _SYNTH_LOCK:
                        pw, zid = _prepare_clone()
                        gen = _create_gen(pw, zid)
                        sr, wav = _synth_chunks(gen)
                        if wav.size == 0:
                            raise _SpeechHttpError(500, "synthesis returned empty")
                        return _encode_wav(int(sr), wav, volume=volume), zid

                audio_bytes, zero_shot_spk_id = await asyncio.to_thread(_full_synth)
            _t_spk_done = time.monotonic()
            _t_gen_done = _t_spk_done
        except _SpeechHttpError as exc:
            _active_count -= 1  # 异常路径：撤销本请求的保活暂停计数
            return JSONResponse(status_code=exc.status_code, content={"error": {"message": exc.message}})
        except Exception as exc:
            _active_count -= 1  # 异常路径：撤销本请求的保活暂停计数
            return JSONResponse(status_code=500, content={"error": {"message": str(exc)}})

        # [DIAG-TIMING] 阶段计时：parse → spk → gen 创建
        print(f"[DIAG-TIMING] parse={( _t_parse_done - t0)*1000:.0f}ms "
              f"spk={(_t_spk_done - _t_parse_done)*1000:.0f}ms "
              f"gen_ctor={(_t_gen_done - _t_spk_done)*1000:.0f}ms "
              f"cache_hit={zero_shot_spk_id in cosyvoice.frontend.spk2info}")

        if stream:
            # 真正流式：llm_job 后台线程逐 token 生成，token2wav 够一 hop 即输出，
            # StreamingResponse 逐块下发，首块延迟显著低于全量合成（WAV 头先发，PCM 逐段）。
            # 注意：CosyVoice tts() 流式循环内会自增 token_hop_len（*stream_scale_factor），
            # 且跨请求持久化——此处每请求重置，避免后续请求首 hop 被放大到 100。
            if args.stream_hop_len and hasattr(cosyvoice.model, "token_hop_len"):
                # 并发流式语义：token_hop_len/token_max_hop_len 是跨请求共享模型态，
                # 复位须与 hift CUDA graph 静态缓冲一样纳入 _MODEL_STATE_LOCK，
                # 防止与另一请求正在进行的流式 hop 推进竞写。
                with _MODEL_STATE_LOCK:
                    cosyvoice.model.token_hop_len = int(args.stream_hop_len)
                    cosyvoice.model.token_max_hop_len = max(
                        cosyvoice.model.token_max_hop_len, 4 * int(args.stream_hop_len)
                    )
            print(f"[CosyVoice] streaming start {len(text)} chars cache_hit={zero_shot_spk_id in cosyvoice.frontend.spk2info} "
                  f"token_hop_len={getattr(cosyvoice.model, 'token_hop_len', 'n/a')} speed={speed} volume={volume}")
            return StreamingResponse(
                _stream_wav_pcm_keepalive(gen, int(cosyvoice.sample_rate), volume=volume),
                media_type="audio/wav",
            )

        # 非流式：audio_bytes 已在后台线程（_full_synth）内完成全量合成并编码
        print(f"[CosyVoice] synthesized {len(text)} chars -> {len(audio_bytes)} bytes ({time.monotonic()-t0:.2f}s) cache_hit={zero_shot_spk_id in cosyvoice.frontend.spk2info}")
        _active_count -= 1  # 非流式完成：撤销本请求的保活暂停计数（归零恢复保活）
        return Response(content=audio_bytes, media_type="audio/wav")

    return app


def _run_warmup(cv, args) -> None:
    """启动预热：用 1s 正弦波 ref 触发一次完整零样本合成，把 CUDA/cuDNN 一次性开销移到启动期。

    不用静音 ref：CosyVoice3 的 speech_tokenizer_v3 对静音提取 token 过短会导致 flow Conv 失败。
    """
    try:
        import numpy as _np
        import soundfile as _sf

        os.makedirs(args.tmp_dir, exist_ok=True)
        warmup_path = os.path.join(args.tmp_dir, "warmup_ref.wav")
        sr = 16000
        # 1s 正弦波（440Hz），非静音，确保 speech_tokenizer 提取到有效 token
        t_axis = _np.arange(int(sr * 1.0), dtype=_np.float32) / sr
        tone = 0.3 * _np.sin(2 * _np.pi * 440.0 * t_axis).astype(_np.float32)
        _sf.write(warmup_path, tone, sr, format="wav", subtype="PCM_16")

        print(">> Running startup warmup (full synthesis, expected ~30-60s) ...")
        t0 = time.monotonic()
        # CosyVoice3 的 prompt_text 须含 <|endofprompt|>
        _is_cv3 = "CosyVoice3" in type(cv.model).__name__
        prompt_text = "You are a helpful assistant.<|endofprompt|>你好" if _is_cv3 else "你好"
        for _ in cv.inference_zero_shot(
            "你好", prompt_text, warmup_path, stream=False, speed=1.0
        ):
            pass
        # 追加一次流式合成预热：流式路径的 CUDA graph 流式 shape / token_hop_len 逻辑
        # 与逐 hop token2wav 首次开销一次性移到启动期，避免首个真实流式请求首包被拖到 ~11s。
        if args.stream_hop_len and hasattr(cv.model, "token_hop_len"):
            cv.model.token_hop_len = int(args.stream_hop_len)
            cv.model.token_max_hop_len = max(
                cv.model.token_max_hop_len, 4 * int(args.stream_hop_len)
            )
        print(">> Running streaming warmup (stream=True) ...")
        _ts0 = time.monotonic()
        for _ in cv.inference_zero_shot(
            "今天天气怎么样，适合出门散步。", prompt_text, warmup_path, stream=True, speed=1.0
        ):
            pass
        print(f">> Streaming warmup complete in {time.monotonic()-_ts0:.1f}s")
        print(f">> Warmup complete in {time.monotonic()-t0:.1f}s")
    except Exception as exc:
        print(f"[WARN] Warmup failed (server will still start): {exc}")


# GPU 保活信号：_active_count 为进行中请求数（引用计数）。并发流式请求会重叠，
# 原 Event 的 set/clear 二值语义在多请求交叉时会被先结束的请求提前 clear（此时
# 另一请求仍在推理），保活 GEMM 与真实请求竞争算力。改为引用计数：
# _active_count > 0 暂停保活；count == 0 恢复保活 GEMM。
# 所有 += / -= 写点均在 asyncio 事件循环线程（speech handler / 流式包装器
# finally），天然串行无竞写；保活线程仅做读取（GIL 下 int 读取原子）。
# 详见 .trae/documents/20260817_模块0_GPU保活增强消除降频.md
_active_count = 0  # >0 = 有请求进行中（暂停保活），==0 = 空闲（保活可执行 GEMM）


class _SpeechHttpError(Exception):
    """speech 端点内部用于映射固定 HTTP 状态码的信号异常（worker 线程内抛出）。"""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


# speech 端点推理互斥采用「细粒度锁」策略，本锁并非覆盖全部推理段：
# - _SYNTH_LOCK 仅覆盖 speech 端点的 prep 段（ref 解析 + add_zero_shot_spk speaker
#   注册 + gen 构造）与非流式全量合成段（_full_synth 含 _synth_chunks）；#3 会把部分
#   权重临时卸载，prep/全量段持本锁可防卸载后模型竞争。
# - 流式路径的逐块推理（llm_job / flow / hift 逐 hop）刻意不持 _SYNTH_LOCK（整段包锁
#   会显著伤 TTFT 与并发度），改用细粒度锁保护共享模型态：
#   * llm CUDA graph：extra['lock']（_patch_llm_cudagraph 内，replay 与 eager fallback 同锁）；
#   * hift CUDA graph：_MODEL_STATE_LOCK（replay / eager 计算 / capture 全部持锁）；
#   * token_hop_len 等 hop 共享模型态：_MODEL_STATE_LOCK（speech 端点流式复位处）。
# 注：threading 已在模块头导入；此前此处误用 _patch_llm_cudagraph 函数内的
# `import threading as _threading` 别名（模块级执行时 NameError），已改回 threading。
_SYNTH_LOCK = threading.Lock()

# 模型态互斥锁：保护 hift CUDA graph patch 的静态缓冲（xc_static/sstft_static/
# mag_out/phase_out 等 closure 单例）与 cosyvoice.model.token_hop_len 等跨请求
# 共享模型态。并发流式请求若同时执行 copy_→replay→读静态输出，会把对方输入写进
# 同一静态缓冲产生错乱音频；token_hop_len 复位与流式 hop 推进同理。锁粒度仅覆盖
# 模型态写段，不覆盖网络/文本处理。
_MODEL_STATE_LOCK = threading.Lock()


def _patch_hift_decode_cudagraph(cosyvoice) -> bool:
    """若设备为 CUDA 且 hift 为 CausalHiFTGenerator，则给 decode 中间段加 CUDA graph 加速。

    背景（2026-08-18，diag_middle_graph.py 概念验证）：hift decode 中间 conv 段
    （conv_pre 之后、istft 之前）占 decode 主要耗时（实测 conv 段 67ms→4ms、diff=0）。
    stft/_istft（cuFFT）保留 eager，仅中间段捕获为 CUDA graph；shape 命中走 graph 静态缓冲，
    shape 不匹配/异常自动回退原始 decode，保证输出完全一致。

    采用闭包方案（不依赖 types.MethodType 显式绑定 self）：将 hift 模块与原 decode 捕获进
    闭包，`h.decode = wrapped_decode` 直接赋给实例属性，避免绑定冲突导致
    "got multiple values for argument 'x'".
    """
    try:
        import torch as _t

        if not _t.cuda.is_available():
            return False
        h = cosyvoice.model.hift
        if h is None or not hasattr(h, "decode"):
            return False
        if not hasattr(h, "conv_pre_look_right") or not hasattr(h, "upsample_rates"):
            return False
        if getattr(h, "num_upsamples", 0) <= 0:
            return False

        orig_decode = h.decode  # 原始 decode（未绑定实例的类方法函数）

        # 可变状态（闭包持有，跨调用保持）
        # graph_failed / graph_retry_left：capture 失败退避标记——失败后不再逐 hop 重试
        # （每次重试含 3 次 warmup+capture，持续失败会持续劣化性能），每模型进程生命
        # 周期至多重试一次，重试机会耗尽后只走 eager 路径（见 wrapped_decode）。
        state = {
            "graph": None,
            "xc_static": None,
            "sstft_static": None,
            "mag_out": None,
            "phase_out": None,
            "captured_key": None,
            "device": None,
            "graph_failed": False,
            "graph_retry_left": 1,
        }

        def _transform_source(s: _t.Tensor):
            spec = _t.stft(
                s.squeeze(1),
                h.istft_params["n_fft"], h.istft_params["hop_len"], h.istft_params["n_fft"],
                window=h.stft_window.to(s.device), return_complex=True,
            )
            spec = _t.view_as_real(spec)  # [B, F, TT, 2]
            return spec[..., 0], spec[..., 1]

        def _middle(xc: _t.Tensor, s_stft: _t.Tensor):
            """decode 中间段（conv，可 graph）：xc/s_stft -> (magnitude, phase)。精确复刻 decode。"""
            x = xc
            for i in range(h.num_upsamples):
                x = _t.nn.functional.leaky_relu(x, h.lrelu_slope)
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
            x = _t.nn.functional.leaky_relu(x)
            x = h.conv_post(x)
            magnitude = _t.exp(x[:, : h.istft_params["n_fft"] // 2 + 1, :])
            phase = _t.sin(x[:, h.istft_params["n_fft"] // 2 + 1 :, :])
            return magnitude, phase

        def _istft(magnitude: _t.Tensor, phase: _t.Tensor):
            magnitude = _t.clip(magnitude, max=1e2)
            real = magnitude * _t.cos(phase)
            img = magnitude * _t.sin(phase)
            return _t.istft(
                _t.complex(real, img),
                h.istft_params["n_fft"], h.istft_params["hop_len"], h.istft_params["n_fft"],
                window=h.stft_window.to(magnitude.device),
            )

        def _capture(xc: _t.Tensor, s_stft: _t.Tensor):
            """按 (xc, s_stft) 形状捕获中间段 CUDA graph。失败记 graph_failed 标记（保持 eager，退避见 wrapped_decode）。"""
            try:
                dev = xc.device
                state["device"] = dev
                xc_s = xc.detach().contiguous().clone()
                s_s = s_stft.detach().contiguous().clone()
                # warmup（同 shape 若干次后再捕获，确保 autotuner/内存池稳定）
                for _ in range(3):
                    m, p = _middle(xc_s, s_s)
                    _ = _istft(m, p)
                _t.cuda.synchronize()
                g = _t.cuda.CUDAGraph()
                with _t.cuda.graph(g):
                    mag_g, phase_g = _middle(xc_s, s_s)
                _t.cuda.synchronize()
                state.update(graph=g, xc_static=xc_s, sstft_static=s_s,
                             mag_out=mag_g, phase_out=phase_g,
                             captured_key=(tuple(xc.shape), tuple(s_stft.shape)))
                print(f"[Patch] hift decode middle CUDA graph captured for "
                      f"{tuple(xc.shape)}/{tuple(s_stft.shape)}")
            except Exception as exc:  # noqa: BLE001 - 捕获失败不影响正确性
                state["graph"] = None
                state["graph_failed"] = True  # 失败标记：停止逐 hop 重试（退避见 wrapped_decode）
                print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [WARN] hift decode CUDA graph capture "
                      f"failed (mark graph_failed, eager-only until retry): {exc}")

        def wrapped_decode(x: _t.Tensor, s: _t.Tensor, finalize: bool = True) -> _t.Tensor:
            """替代 hift.decode。stft/conv_pre/istft eager；中间 conv 段走 CUDA graph（shape 匹配时）。"""
            U = int(np.prod(h.upsample_rates))
            cp = int(h.conv_pre_look_right)
            try:
                s_stft_r, s_stft_i = _transform_source(s)
                if finalize:
                    xc = h.conv_pre(x)
                else:
                    xc = h.conv_pre(x[:, :, :-cp], x[:, :, -cp:])
                    s_stft_r = s_stft_r[:, :, :-int(U * cp)]
                    s_stft_i = s_stft_i[:, :, :-int(U * cp)]
                s_stft = _t.cat([s_stft_r, s_stft_i], dim=1)
                key = (tuple(xc.shape), tuple(s_stft.shape))

                if (not finalize and state["graph"] is not None
                        and key == state["captured_key"]
                        and xc.device == state["device"]
                        and s_stft.device == state["device"]):
                    # shape 命中：copy 输入进静态缓冲 → replay → 读静态输出。
                    # 并发流式语义：xc_static/sstft_static/mag_out/phase_out 是闭包
                    # 单例（跨请求共享），copy_→replay→消费输出（istft/clamp 生成
                    # 独立张量）必须整段持 _MODEL_STATE_LOCK 原子完成，否则并发请求
                    # 交叉写同一静态缓冲会产生错乱音频；返回值不再引用静态缓冲。
                    with _MODEL_STATE_LOCK:
                        xc_c = xc.contiguous()
                        s_stft_c = s_stft.contiguous()
                        with _t.no_grad():
                            state["xc_static"].copy_(xc_c)
                            state["sstft_static"].copy_(s_stft_c)
                            state["graph"].replay()
                        out = _istft(state["mag_out"], state["phase_out"])
                        out = out[:, :-int(U * h.istft_params["hop_len"])]
                        return _t.clamp(out, -h.audio_limit, h.audio_limit)

                # eager 或捕获新 graph（首 hop / shape 变化时在此捕获）。
                # 并发语义：capture 的 warmup+捕获需独占 CUDA stream（其他线程并发提交
                # 会破坏捕获），与 replay 路径同锁（_MODEL_STATE_LOCK）串行化；capture
                # 失败记 graph_failed 后不再逐 hop 重试，每模型进程生命周期至多重试一次，
                # 重试机会耗尽后只走 eager 路径。
                if (not finalize and state["graph"] is None
                        and (not state["graph_failed"] or state["graph_retry_left"] > 0)):
                    with _MODEL_STATE_LOCK:
                        if state["graph_failed"] and state["graph_retry_left"] > 0:
                            state["graph_retry_left"] -= 1  # 消耗最后一次重试机会
                        _capture(xc, s_stft)

                # eager 计算段（shape 不匹配 / capture 失败 / finalize 尾块）：与 replay
                # 共享 hift 模块与窗口，同样纳入 _MODEL_STATE_LOCK 防跨线程并发 forward。
                with _MODEL_STATE_LOCK:
                    magnitude, phase = _middle(xc, s_stft)
                    out = _istft(magnitude, phase)
                    if not finalize:
                        out = out[:, :-int(U * h.istft_params["hop_len"])]
                    return _t.clamp(out, -h.audio_limit, h.audio_limit)
            except Exception:  # noqa: BLE001 - 任何异常回退原始 decode
                return orig_decode(x, s, finalize=finalize)

        # 直接赋普通函数作实例属性；orig_decode 仍是独立引用不会无限递归
        h.decode = wrapped_decode  # type: ignore[attr-defined]
        print("[Patch] hift decode CUDA graph middleware installed")
        return True
    except Exception as exc:
        print(f"[WARN] hift decode CUDA graph patch failed (keep eager): {exc}")
        return False


def _start_gpu_keepalive() -> None:
    """后台 GPU 保活：空闲时执行 4096x4096 bf16 GEMM，请求中暂停。

    背景（2026-08-17 全链路 TTFT 优化）：WS 全链路请求间隔 ~1.5s（ASR/LLM/TTS
    串联），GPU 在请求间隙降频到 ~210MHz（nvidia-smi 实测 idle 36°C/22W），下一请求
    首块须等待升频 → 0.35s/0.70s 冷热交替，P95 超标。原 1024x1024 GEMM @ 20ms
    占空比 <1%（~0.2ms 计算 + 20ms 空闲），不足以阻止降频。升级到 4096x4096 GEMM
    （~5.3ms 计算）+ 时隙 10ms，占 GPU ~50%，通过 _active_count 引用计数在真实
    请求进行中暂停保活（并发流式下 count==0 才恢复），消除竞争。

    管理员权限下 `nvidia-smi -lgc` 不可用（Windows 平台 exit=4），此为软件替代方案。
    """
    try:
        import torch as _torch

        if not _torch.cuda.is_available():
            return
        _dev = _torch.device("cuda:0")
        _a = _torch.randn(4096, 4096, device=_dev, dtype=_torch.bfloat16)
        _b = _torch.randn(4096, 4096, device=_dev, dtype=_torch.bfloat16)
        _stop = threading.Event()
        def _pulse():
            while not _stop.is_set():
                # 请求进行中（_active_count > 0）→ 跳过本次保活（等待 ~10ms 后重试）
                if _active_count != 0:
                    _stop.wait(0.01)
                    continue
                with _torch.inference_mode():
                    # 3 次连续 GEMM 组成脉冲（~16ms），提高空闲态 SM 时钟到高频；
                    # 真实请求进行中会暂停本线程，不会与请求竞争算力。
                    for _ in range(3):
                        (_a @ _b).sum().item()
                _stop.wait(0.005)  # 5ms 间隔

        _t = threading.Thread(target=_pulse, daemon=True, name="gpu-keepalive")
        _t.start()
        print("[KeepAlive] GPU 保活线程已启动（4096x4096 GEMM x3 @ 5ms，请求中暂停）")
    except Exception as exc:  # noqa: BLE001 - 保活失败不影响主服务
        print(f"[WARN] GPU keepalive failed (ignore): {exc}")


# ============================================================================
# 启动
# ============================================================================
def main() -> None:
    global args, cosyvoice

    ap = argparse.ArgumentParser()
    ap.add_argument("--model_dir", default=r"C:\CX-O\models\Fun-CosyVoice3-0.5B-2512")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8094)
    ap.add_argument("--device", default="cuda:0")
    ap.add_argument("--bf16", action="store_true", default=False,
                    help="启用 fp16/bf16 推理（CosyVoice2Model fp16 标志）")
    ap.add_argument("--assets_dir", default=r"C:\CX-O\CX-O-SERVER\data\ref_audio_assets")
    ap.add_argument("--tmp_dir", default=r"C:\CX-O\docker\llm\cosyvoice_tmp")
    ap.add_argument("--no-warmup", action="store_true",
                    help="跳过启动预热（默认启动时预热一次完整合成）")
    ap.add_argument("--stream-hop-len", type=int, default=None,
                    help="流式首 hop token 数（默认用模型 token_hop_len=25；减小可降低首包延迟，但增加 hop 边界数量）")
    ap.add_argument("--flow-steps", type=int, default=None,
                    help="flow matching decoder ODE 步数（默认 10；3 为 TTFT 推荐值：首个 flow 推理 ~0.55s、TTFT ~1.1s，质量略降；5 为质量更稳折中）")
    ap.add_argument("--flow-cfg-rate", type=float, default=None,
                    help="flow decoder classifier-free guidance rate（0 关闭 CFG：每 ODE 步只用 conditional 路径、计算减半，首块显著加速但音质可能略变；None 保持模型默认 0.7）")
    ap.add_argument("--vllm", action="store_true", default=False,
                    help="LLM 走 vLLM 进程内引擎（官方 load_vllm，Linux/Docker 下无 WDDM 开销，decode 显著提速；需 vllm 已安装且模型已导出 vllm 格式）")
    ap.add_argument("--zero-shot-mode", choices=["cross_lingual", "zero_shot"], default="cross_lingual",
                    help="零样本克隆模式：cross_lingual 使用仅含 <|endofprompt|> 标记的 prompt_text（不含参考转写），"
                         "避免 CosyVoice3 LLM 把参考转写文本念出来（默认，修复回声前缀问题）；"
                         "zero_shot 保留参考转写文本作为条件（可能回声参考转写文本）")
    args = ap.parse_args()

    # 把 torch 自带 CUDA 12.x DLL 目录加入 PATH，使 onnxruntime-gpu 的 CUDAExecutionProvider
    # 能加载 cudart/cublas/cudnn（避免依赖系统级 CUDA 安装）。
    import torch as _torch

    _torch_lib = os.path.join(os.path.dirname(os.path.dirname(_torch.__file__)), "torch", "lib")
    if os.path.isdir(_torch_lib) and _torch_lib not in os.environ.get("PATH", ""):
        os.environ["PATH"] = _torch_lib + os.pathsep + os.environ.get("PATH", "")
    # CUDA_PATH 指向不匹配的 CUDA 版本时清除，交由 torch 自带 DLL 提供运行时
    if os.environ.get("CUDA_PATH"):
        os.environ.pop("CUDA_PATH", None)

    # cosyvoice 包位于第三方仓库（非 pip 安装），显式加入 sys.path
    _THIRD_PARTY = os.path.abspath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "third_party", "cosyvoice-official")
    )
    if os.path.isdir(_THIRD_PARTY) and _THIRD_PARTY not in sys.path:
        sys.path.insert(0, _THIRD_PARTY)
    # Matcha-TTS 子模块（cosyvoice.flow.flow_matching 依赖）
    _MATCHA = os.path.join(_THIRD_PARTY, "third_party", "Matcha-TTS")
    if os.path.isdir(_MATCHA) and _MATCHA not in sys.path:
        sys.path.insert(0, _MATCHA)

    import torch
    from cosyvoice.cli.cosyvoice import AutoModel

    # 用 soundfile 替换 CosyVoice 内部 load_wav（绕开 torchaudio 2.11 torchcodec DLL 依赖）
    _patch_load_wav()

    print(f">> Loading CosyVoice2 from {args.model_dir} on {args.device} (fp16={args.bf16}, vllm={args.vllm}) ...")
    t0 = time.monotonic()
    # CosyVoice2Model 在初始化时自动选择 cuda 设备（self.device），load() 会 .to(device)。
    # 由 CUDA_VISIBLE_DEVICES 控制实际物理 GPU，不显式调用 model.to()（CosyVoice2Model 无该方法）。
    if args.vllm:
        # vLLM 进程内引擎：需先注册 CosyVoice2ForCausalLM，再由 AutoModel(load_vllm=True)
        # 导出(若未导出)并加载 LLMEngine。注意流式输入文本(bistream)不支持 vllm，输出流式正常。
        from vllm import ModelRegistry
        from cosyvoice.vllm.cosyvoice2 import CosyVoice2ForCausalLM
        ModelRegistry.register_model("CosyVoice2ForCausalLM", CosyVoice2ForCausalLM)
        cosyvoice = AutoModel(
            model_dir=args.model_dir,
            load_vllm=True,
            fp16=args.bf16 and torch.cuda.is_available(),
        )
    else:
        cosyvoice = AutoModel(
            model_dir=args.model_dir,
            fp16=args.bf16 and torch.cuda.is_available(),
        )
    print(f">> Model loaded in {time.monotonic()-t0:.1f}s (sample_rate={cosyvoice.sample_rate})")

    # campplus ONNX 会话切到 GPU（speaker 嵌入提取加速）
    _patch_campplus_gpu(cosyvoice)

    # LLM CUDA graph + StaticCache 加速（decode 逐 token 延迟优化）
    # vLLM 模式下跳过：vLLM 引擎接管 LLM（torch 层已被 del），自研 patch 会绕过 vLLM。
    if not args.vllm and _patch_llm_cudagraph(cosyvoice):
        print("[Patch] LLM CUDA graph + StaticCache enabled")
    elif not args.vllm:
        print("[WARN] LLM CUDA graph patch failed (fallback original)")
    else:
        print("[Patch] LLM via vLLM in-process engine (skip CUDA graph patch)")

    # flow decoder ODE 步数覆盖（降低 TTFT；仅当显式指定时）
    if args.flow_steps:
        _patch_flow_steps(cosyvoice, args.flow_steps)

    # flow decoder CFG rate 覆盖（关闭 CFG 时每 ODE 步只用 conditional 路径、计算减半；仅当显式指定时）
    if args.flow_cfg_rate is not None:
        try:
            _dec = cosyvoice.model.flow.decoder
            _orig_cfg = getattr(_dec, "inference_cfg_rate", None)
            _dec.inference_cfg_rate = float(args.flow_cfg_rate)
            print(f"[Patch] flow cfg_rate {_orig_cfg} -> {args.flow_cfg_rate} "
                  f"(batch2={'on' if float(args.flow_cfg_rate) > 0 else 'off'})")
        except Exception as exc:
            print(f"[WARN] flow cfg_rate patch failed (keep model default): {exc}")

    # GPU 预分配（TTFT 优化 2026-08-18）：消除 hift/flow 每调用一次的 CPU->GPU 拷贝。
    # 1) hift.stft_window 移到 GPU（否则 decode 内 .to(device) 每调用一次 CPU->GPU 拷贝）
    # 2) flow.decoder.rand_noise 移到 GPU（CausalConditionalCFM 确定性噪声，同理）
    # 3) hift.f0_predictor 强制 fp32（generator.inference 已改为 fp32 路径，避免 fp64
    #    转换；实测 fp32/fp64 输出完全一致，SNR 155.6dB）
    try:
        _dec = cosyvoice.model.flow.decoder
        if hasattr(_dec, "rand_noise") and _dec.rand_noise.device.type == "cpu":
            _dec.rand_noise = _dec.rand_noise.to(cosyvoice.model.device)
            print("[Patch] flow rand_noise moved to GPU")
        _hift = cosyvoice.model.hift
        if hasattr(_hift, "stft_window") and _hift.stft_window.device.type == "cpu":
            _hift.stft_window = _hift.stft_window.to(cosyvoice.model.device)
        _fp0 = getattr(_hift, "f0_predictor", None)
        if _fp0 is not None and next(_fp0.parameters(), None) is not None:
            _fp0_dtype = next(_fp0.parameters()).dtype
            if _fp0_dtype != torch.float32:
                _fp0.to(torch.float32)
                print(f"[Patch] hift f0_predictor {_fp0_dtype} -> float32")
        # 4) 移除 hift weight_norm parametrizations（推理时安全，输出完全一致，
        #    实测 89.8ms→61.9ms，-31% CPU 派发）
        import torch.nn.utils.parametrize as _parametrize
        _wn_count = 0
        for _m in _hift.modules():
            for _wn_name in ["weight"]:
                try:
                    if _parametrize.is_parametrized(_m, _wn_name):
                        _parametrize.remove_parametrizations(_m, _wn_name)
                        _wn_count += 1
                except Exception:
                    pass
        if _wn_count > 0:
            print(f"[Patch] hift weight_norm removed from {_wn_count} modules (diff=0)")
        # 5) SineGen2 的 CPU 常量缓冲移到 GPU（CUDA graph 前置 + 省每调用 CPU->GPU 拷贝）
        try:
            _sg2 = _hift.m_source.l_sin_gen
            for _attr in ("rand_ini", "sine_waves", "uv"):
                _buf = getattr(_sg2, _attr, None)
                if _buf is not None and _buf.device.type == "cpu":
                    setattr(_sg2, _attr, _buf.to(cosyvoice.model.device))
            print("[Patch] SineGen2 buffers moved to GPU")
        except Exception as _sg_exc:
            print(f"[WARN] SineGen2 buffer move failed (ignore): {_sg_exc}")
    except Exception as exc:
        print(f"[WARN] hift/flow GPU pre-alloc patch failed (ignore): {exc}")
    # 6) hift.decode 中间段 CUDA graph 加速（2026-08-18）：conv 段 67ms→4ms、diff=0；
    #    仅流式 hop（finalize=False）首段命中，shape 变化/失败自动回退 eager。
    _patch_hift_decode_cudagraph(cosyvoice)

    # 流式首 hop token 数覆盖（减小可降低首包延迟；仅当显式指定时）
    # 注意：tts() 流式循环用 token_min_hop_len 作为首 hop 初始值（CosyVoice3 默认 100），
    # 必须同时覆盖 token_min_hop_len 才能真正降低 TTFT。
    if args.stream_hop_len and hasattr(cosyvoice.model, "token_hop_len"):
        _orig_hop = cosyvoice.model.token_hop_len
        _orig_min = getattr(cosyvoice.model, "token_min_hop_len", None)
        cosyvoice.model.token_hop_len = int(args.stream_hop_len)
        if hasattr(cosyvoice.model, "token_min_hop_len"):
            cosyvoice.model.token_min_hop_len = int(args.stream_hop_len)
        cosyvoice.model.token_max_hop_len = max(cosyvoice.model.token_max_hop_len, 4 * int(args.stream_hop_len))
        print(f"[Patch] stream token_hop_len {_orig_hop} -> {args.stream_hop_len} "
              f"(token_min_hop_len {_orig_min} -> {args.stream_hop_len})")

    if not args.no_warmup:
        _run_warmup(cosyvoice, args)

    # GPU 保活：防止请求间隙降频导致首块升频等待（WS 全链路 P95 优化）
    _start_gpu_keepalive()

    import uvicorn

    _banner_model = "Fun-CosyVoice3-0.5B-2512" if os.path.exists(os.path.join(args.model_dir, "cosyvoice3.yaml")) else "CosyVoice2-0.5B"
    print(f">> {_banner_model} serving on http://{args.host}:{args.port}")
    uvicorn.run(create_app(), host=args.host, port=args.port, log_level="info")


cosyvoice = None
args = None

if __name__ == "__main__":
    main()
