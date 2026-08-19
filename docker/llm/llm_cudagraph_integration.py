# -*- coding: utf-8 -*-
"""将 CUDA graph + StaticCache 集成到 CosyVoice2 的 LLM 解码, 验证完整推理 RTF。

流程:
  1. 加载完整 CosyVoice2 (cv)
  2. 构造 lm_input (sos + text_emb + task + prompt_speech_token_emb, shape (1,L,896))
  3. StaticCache prefill: 把 lm_input 编码进固定长度 cache
  4. CUDA graph 捕获 decode 一步 (固定 shape)
  5. 完整解码 (graph replay + graph 外采样 + 构造新 token embedding)
  6. 测 llm 解码总耗时 + 估算 RTF (flow/hift 用实测常量)
"""
import sys, os, io, time
import numpy as np
import torch
import soundfile as sf

sys.path.insert(0, r'C:\CX-O\third_party\cosyvoice-official')
sys.path.insert(0, r'C:\CX-O\third_party\cosyvoice-official\third_party\Matcha-TTS')

from transformers import StaticCache

MODEL_DIR = r'C:\CX-O\models\CosyVoice2-0.5B'
TMP_DIR = r'C:\CX-O\docker\llm\cosyvoice_tmp'
REF_WAV = os.path.join(TMP_DIR, 'profile_ref.wav')
MAX_CACHE = 512


def patch_load_wav():
    import cosyvoice.cli.frontend as _frontend
    import cosyvoice.utils.file_utils as _file_utils

    def _load_wav_soundfile(wav, target_sr, min_sr=16000):
        import torchaudio
        if isinstance(wav, torch.Tensor):
            return wav
        if isinstance(wav, (str, os.PathLike)):
            speech, sample_rate = sf.read(str(wav), dtype='float32')
        else:
            speech, sample_rate = sf.read(io.BytesIO(wav.read()), dtype='float32')
        if speech.ndim > 1:
            speech = speech.mean(axis=1)
        speech = speech.reshape(1, -1)
        if sample_rate != target_sr:
            speech = torchaudio.transforms.Resample(orig_freq=sample_rate, new_freq=target_sr)(
                torch.from_numpy(speech))
        else:
            speech = torch.from_numpy(speech)
        return speech

    _file_utils.load_wav = _load_wav_soundfile
    _frontend.load_wav = _load_wav_soundfile


def fix_onnx_env():
    _torch_lib = os.path.join(os.path.dirname(os.path.dirname(torch.__file__)), "torch", "lib")
    if os.path.isdir(_torch_lib) and _torch_lib not in os.environ.get("PATH", ""):
        os.environ["PATH"] = _torch_lib + os.pathsep + os.environ.get("PATH", "")
    if os.environ.get("CUDA_PATH"):
        os.environ.pop("CUDA_PATH", None)


def build_lm_input(cv, model_input):
    model = cv.model
    device = model.device
    llm = model.llm
    text = model_input['text']
    text_len = model_input['text_len']
    prompt_text = model_input['prompt_text']
    prompt_text_len = model_input['prompt_text_len']
    llm_prompt_speech_token = model_input['llm_prompt_speech_token']
    llm_prompt_speech_token_len = torch.tensor([llm_prompt_speech_token.shape[1]], dtype=torch.int32)
    llm_embedding = model_input['llm_embedding']

    text_full = torch.concat([prompt_text, text], dim=1)
    with torch.cuda.amp.autocast(model.fp16):
        text_emb = llm.llm.model.model.embed_tokens(text_full.to(device))
        sos_emb = llm.llm_embedding.weight[llm.sos].reshape(1, 1, -1)
        task_id_emb = llm.llm_embedding.weight[llm.task_id].reshape(1, 1, -1)
        if llm_prompt_speech_token_len != 0:
            prompt_speech_token_emb = llm.speech_embedding(llm_prompt_speech_token.to(device))
        else:
            prompt_speech_token_emb = torch.zeros(1, 0, llm.llm_input_size, dtype=text_emb.dtype).to(device)
        lm_input = torch.concat([sos_emb, text_emb, task_id_emb, prompt_speech_token_emb], dim=1)
    return lm_input, device, llm, int(text_len.item())


def main():
    patch_load_wav()
    fix_onnx_env()
    os.makedirs(TMP_DIR, exist_ok=True)
    if not os.path.exists(REF_WAV):
        sf.write(REF_WAV, np.zeros(16000, dtype=np.float32), 16000, format='wav', subtype='PCM_16')

    print('=' * 70)
    print('CosyVoice2 LLM: CUDA graph + StaticCache 集成验证')
    print('=' * 70)

    print('\n>> Loading CosyVoice2 ...')
    t0 = time.time()
    from cosyvoice.cli.cosyvoice import AutoModel
    cv = AutoModel(model_dir=MODEL_DIR, fp16=True)
    print(f'>> loaded in {time.time() - t0:.1f}s')
    model = cv.model
    llm = model.llm
    device = model.device
    config = llm.llm.model.config

    model_input = cv.frontend.frontend_zero_shot(
        '今天天气真不错，我们一起出去走走吧。', '希望你以后能够做的比我还好呦。',
        REF_WAV, cv.sample_rate, '')
    lm_input, device, llm, tts_text_len = build_lm_input(cv, model_input)
    prefill_len = lm_input.shape[1]
    print(f'  prefill_len={prefill_len}, tts_text_len={tts_text_len}')

    # ---------------- StaticCache prefill ----------------
    print('\n>> StaticCache prefill ...')
    cache = StaticCache(config, max_batch_size=1, max_cache_len=MAX_CACHE,
                        device=device, dtype=torch.bfloat16)
    with torch.inference_mode(), torch.cuda.amp.autocast(True):
        cache_position = torch.arange(0, prefill_len, device=device)
        out = llm.llm.model(inputs_embeds=lm_input, cache_position=cache_position,
                            past_key_values=cache, use_cache=True, output_hidden_states=True)
    torch.cuda.synchronize()
    print(f'  prefill done')

    # ---------------- CUDA graph 捕获 decode 一步 ----------------
    print('\n>> capture CUDA graph for decode step ...')
    inp_buf = torch.zeros((1, 1, config.hidden_size), dtype=torch.bfloat16, device=device)
    cache_pos_buf = torch.zeros((1,), dtype=torch.long, device=device)
    graph = torch.cuda.CUDAGraph()
    s = torch.cuda.Stream()
    s.wait_stream(torch.cuda.current_stream())
    with torch.cuda.stream(s):
        for _ in range(3):
            with torch.inference_mode(), torch.cuda.amp.autocast(True):
                out = llm.llm.model(inputs_embeds=inp_buf, cache_position=cache_pos_buf,
                                    past_key_values=cache, use_cache=True, output_hidden_states=True)
    torch.cuda.current_stream().wait_stream(s)
    with torch.cuda.graph(graph):
        with torch.inference_mode(), torch.cuda.amp.autocast(True):
            out = llm.llm.model(inputs_embeds=inp_buf, cache_position=cache_pos_buf,
                                past_key_values=cache, use_cache=True, output_hidden_states=True)
    hidden_buf = out.hidden_states[-1]  # graph 输出 buffer: (1,1,896), 与 forward_one_step 一致
    print('  graph captured')

    # ---------------- decode 循环 ----------------
    min_len = tts_text_len * 2
    max_len = tts_text_len * 20
    out_tokens = []
    pos = prefill_len

    def decode_with_graph(n_steps):
        nonlocal pos
        pos = prefill_len
        out_tokens.clear()
        with torch.inference_mode(), torch.cuda.amp.autocast(True):
            for i in range(n_steps):
                cache_pos_buf.copy_(torch.tensor([pos], device=device))
                graph.replay()
                hidden = hidden_buf[:, -1].float()  # (1,896)
                logp = llm.llm_decoder(hidden).log_softmax(dim=-1)
                top_ids = llm.sampling_ids(logp.squeeze(dim=0), out_tokens, 25,
                                           ignore_eos=True if i < min_len else False)
                if top_ids in llm.stop_token_ids:
                    break
                out_tokens.append(top_ids)
                new_emb = llm.speech_embedding.weight[top_ids].reshape(1, 1, -1).to(torch.bfloat16)
                inp_buf.copy_(new_emb)
                pos += 1
        torch.cuda.synchronize()
        return len(out_tokens)

    # warmup
    print('\n>> warmup decode ...')
    decode_with_graph(20)
    torch.cuda.synchronize()
    print('  warmup done')

    # 计时
    print('\n>> measure decode (CUDA graph) ...')
    reps = 5
    times = []
    for _ in range(reps):
        t0 = time.perf_counter()
        n_tok = decode_with_graph(300)
        times.append((time.perf_counter() - t0) * 1000)
    llm_ms = float(np.mean(times))
    print(f'  llm decode (graph): {llm_ms:.1f} ms, {n_tok} tokens, '
          f'{llm_ms/n_tok:.1f} ms/token (官方 {82:.0f} ms/token)')

    # ---------------- RTF 估算 ----------------
    # flow/hift 用 v2 实测常量
    flow_ms, hift_ms, speech_secs = 2100.0, 225.0, 9.3
    total_ms = llm_ms + flow_ms + hift_ms
    rtf = total_ms / 1000 / speech_secs
    print('\n' + '=' * 70)
    print('RTF 估算 (llm 用 CUDA graph 实测, flow/hift 用 v2 常量)')
    print('=' * 70)
    print(f'  llm  decode: {llm_ms:7.1f} ms   (官方 20465 ms, x{20465/llm_ms:.1f})')
    print(f'  flow (10步): {flow_ms:7.1f} ms')
    print(f'  hift        : {hift_ms:7.1f} ms')
    print(f'  total       : {total_ms:7.1f} ms')
    print(f'  speech      : {speech_secs:7.2f} s')
    print(f'  估算 RTF    : {rtf:.3f}   (官方 before RTF 2.473)')
    print('=' * 70)


if __name__ == '__main__':
    main()
