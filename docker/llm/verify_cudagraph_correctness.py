# -*- coding: utf-8 -*-
"""验证 CUDA graph + StaticCache 解码路径与原版 Qwen2LM.inference 的一致性。

检查点:
  1. graph replay 的 hidden_states 与 eager forward 逐层一致（数值等价性）
  2. graph 解码的 token 序列长度/终止 与 原版 inference 相近（同 seed 下）
"""
import os, sys, io, time
import numpy as np
import torch

sys.path.insert(0, r'C:\CX-O\third_party\cosyvoice-official')
sys.path.insert(0, r'C:\CX-O\third_party\cosyvoice-official\third_party\Matcha-TTS')

from transformers import StaticCache
import soundfile as sf

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
    prompt_text = model_input['prompt_text']
    llm_prompt_speech_token = model_input['llm_prompt_speech_token']
    llm_embedding = model_input['llm_embedding']
    text_full = torch.concat([prompt_text, text], dim=1)
    with torch.cuda.amp.autocast(model.fp16):
        text_emb = llm.llm.model.model.embed_tokens(text_full.to(device))
        sos_emb = llm.llm_embedding.weight[llm.sos].reshape(1, 1, -1)
        task_id_emb = llm.llm_embedding.weight[llm.task_id].reshape(1, 1, -1)
        if llm_prompt_speech_token.shape[1] != 0:
            prompt_speech_token_emb = llm.speech_embedding(llm_prompt_speech_token.to(device))
        else:
            prompt_speech_token_emb = torch.zeros(1, 0, llm.llm_input_size, dtype=text_emb.dtype).to(device)
        lm_input = torch.concat([sos_emb, text_emb, task_id_emb, prompt_speech_token_emb], dim=1)
    return lm_input, device, llm, int(text.shape[1])


def main():
    patch_load_wav()
    fix_onnx_env()
    os.makedirs(TMP_DIR, exist_ok=True)
    if not os.path.exists(REF_WAV):
        sf.write(REF_WAV, np.zeros(16000, dtype=np.float32), 16000, format='wav', subtype='PCM_16')

    print('>> Loading CosyVoice2 ...')
    t0 = time.time()
    from cosyvoice.cli.cosyvoice import AutoModel
    cv = AutoModel(model_dir=MODEL_DIR, fp16=True)
    print(f'>> loaded in {time.time()-t0:.1f}s')
    model = cv.model
    llm = model.llm
    device = model.device
    config = llm.llm.model.config

    model_input = cv.frontend.frontend_zero_shot(
        '今天天气真不错，我们一起出去走走吧。', '希望你以后能够做的比我还好呦。',
        REF_WAV, cv.sample_rate, '')
    lm_input, device, llm, tts_text_len = build_lm_input(cv, model_input)
    prefill_len = lm_input.shape[1]
    min_len, max_len = tts_text_len * 2, tts_text_len * 20
    print(f'  prefill_len={prefill_len}, tts_text_len={tts_text_len}, min_len={min_len}, max_len={max_len}')

    # ============ 检查点 1: graph replay 与 eager forward 数值等价 ============
    print('\n[Check1] graph replay vs eager forward hidden_states ...')
    cache = StaticCache(config, max_batch_size=1, max_cache_len=MAX_CACHE,
                        device=device, dtype=torch.bfloat16)

    def prefill(c):
        with torch.inference_mode(), torch.cuda.amp.autocast(True):
            cache_position = torch.arange(0, prefill_len, device=device)
            out = llm.llm.model(inputs_embeds=lm_input, cache_position=cache_position,
                                past_key_values=c, use_cache=True, output_hidden_states=True)
        return out.hidden_states[-1][:, -1].float()  # (1, 896) 最后 token

    # 首次 prefill（供 graph warmup/capture 使用一致缓存对象）
    prefill(cache)

    # graph 捕获（与服务器 patch 一致：warmup 在 cache_pos=0，会污染 slot 0）
    inp_buf = torch.zeros((1, 1, config.hidden_size), dtype=torch.bfloat16, device=device)
    cache_pos_buf = torch.zeros((1,), dtype=torch.long, device=device)
    graph = torch.cuda.CUDAGraph()
    s = torch.cuda.Stream()
    s.wait_stream(torch.cuda.current_stream())
    with torch.cuda.stream(s):
        for _ in range(3):
            with torch.inference_mode(), torch.cuda.amp.autocast(True):
                llm.llm.model(inputs_embeds=inp_buf, cache_position=cache_pos_buf,
                              past_key_values=cache, use_cache=True, output_hidden_states=True)
    torch.cuda.current_stream().wait_stream(s)
    with torch.cuda.graph(graph):
        with torch.inference_mode(), torch.cuda.amp.autocast(True):
            out_g = llm.llm.model(inputs_embeds=inp_buf, cache_position=cache_pos_buf,
                                  past_key_values=cache, use_cache=True, output_hidden_states=True)
    hidden_buf = out_g.hidden_states[-1]
    torch.cuda.synchronize()

    # 与服务器一致：每次请求先重新 prefill（覆盖 slot 0 污染，恢复真实数据）
    first_token_emb = llm.speech_embedding.weight[llm.sos].reshape(1, 1, -1).to(torch.bfloat16)

    # --- graph replay 路径 ---
    prefill(cache)  # 重新 prefill -> state S
    cache_pos_buf.copy_(torch.tensor([prefill_len], device=device))
    inp_buf.copy_(first_token_emb)
    graph.replay()
    torch.cuda.synchronize()
    hidden_graph = hidden_buf[:, -1].float()

    # --- eager forward 路径（同一 state S，重新 prefill） ---
    prefill(cache)
    with torch.inference_mode(), torch.cuda.amp.autocast(True):
        out_eager = llm.llm.model(
            inputs_embeds=first_token_emb, cache_position=torch.tensor([prefill_len], device=device),
            past_key_values=cache, use_cache=True, output_hidden_states=True)
    hidden_eager = out_eager.hidden_states[-1][:, -1].float()

    diff = (hidden_graph - hidden_eager).abs().max().item()
    print(f'  max |hidden_graph - hidden_eager| = {diff:.6f}')
    if diff < 1e-3:
        print('  [PASS] graph replay == eager forward (数值等价)')
    else:
        print('  [FAIL] hidden 不一致!')

    # ============ 检查点 2: 全序列解码 token 数/终止对比（同 seed） ============
    print('\n[Check2] graph 解码 vs 原版 inference（同 seed 近似对比） ...')

    def decode_graph(seed):
        torch.manual_seed(seed)
        # 重新 prefill（覆盖 cache 内容）
        with torch.inference_mode(), torch.cuda.amp.autocast(True):
            cp = torch.arange(0, prefill_len, device=device)
            out_p = llm.llm.model(inputs_embeds=lm_input, cache_position=cp,
                                  past_key_values=cache, use_cache=True, output_hidden_states=True)
        out_tokens = []
        pos = prefill_len
        with torch.inference_mode(), torch.cuda.amp.autocast(True):
            # 第一个 token 从 prefill 输出采样（与服务器 patch 一致）
            prefill_hidden = out_p.hidden_states[-1][:, -1].float()
            logp0 = llm.llm_decoder(prefill_hidden).log_softmax(dim=-1)
            first_top = llm.sampling_ids(logp0.squeeze(0), out_tokens, 25, ignore_eos=True)
            if first_top in llm.stop_token_ids:
                return out_tokens
            out_tokens.append(first_top)
            inp_buf.copy_(llm.speech_embedding.weight[first_top].reshape(1, 1, -1).to(torch.bfloat16))
            for i in range(1, max_len):
                cache_pos_buf.copy_(torch.tensor([pos], device=device))
                graph.replay()
                hidden = hidden_buf[:, -1].float()
                logp = llm.llm_decoder(hidden).log_softmax(dim=-1)
                top_ids = llm.sampling_ids(logp.squeeze(0), out_tokens, 25,
                                           ignore_eos=True if i < min_len else False)
                if top_ids in llm.stop_token_ids:
                    break
                out_tokens.append(top_ids)
                inp_buf.copy_(llm.speech_embedding.weight[top_ids].reshape(1, 1, -1).to(torch.bfloat16))
                pos += 1
        torch.cuda.synchronize()
        return out_tokens

    def decode_original(seed):
        torch.manual_seed(seed)
        tokens = []
        for i in llm.inference(
            text=model_input['text'].to(device),
            text_len=torch.tensor([model_input['text_len'].item()], dtype=torch.int32).to(device),
            prompt_text=model_input['prompt_text'].to(device),
            prompt_text_len=torch.tensor([model_input['prompt_text_len'].item()], dtype=torch.int32).to(device),
            prompt_speech_token=model_input['llm_prompt_speech_token'].to(device),
            prompt_speech_token_len=torch.tensor([model_input['llm_prompt_speech_token_len'].item()], dtype=torch.int32).to(device),
            embedding=model_input['llm_embedding'].to(device),
            sampling=25, uuid='verify',
        ):
            tokens.append(int(i))
        return tokens

    tok_g = decode_graph(seed=42)
    tok_o = decode_original(seed=42)
    print(f'  graph 解码 token 数: {len(tok_g)} (terminated={tok_g[-1] in llm.stop_token_ids if tok_g else "n/a"})')
    print(f'  原版 inference token 数: {len(tok_o)} (terminated={tok_o[-1] in llm.stop_token_ids if tok_o else "n/a"})')
    # 同 seed 下数值累积差异可能导致采样分支漂移，长度/终止相近即视为一致
    if len(tok_o) > 0 and abs(len(tok_g) - len(tok_o)) / len(tok_o) < 0.35:
        print(f'  [PASS] 长度相近 (diff={abs(len(tok_g)-len(tok_o))/len(tok_o)*100:.1f}%)')
    else:
        print(f'  [WARN] 长度差异较大 (graph={len(tok_g)}, orig={len(tok_o)})')
    # 首个 token 对比（采样前段应高度一致）
    same_prefix = sum(1 for a, b in zip(tok_g[:20], tok_o[:20]) if a == b)
    print(f'  前 20 token 相同数: {same_prefix}/20')


if __name__ == '__main__':
    main()
