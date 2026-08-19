# -*- coding: utf-8 -*-
"""
CosyVoice2-0.5B 非流式推理 RTF 逐环节 profiling v2
==================================================
v1 实测结论(见日志 profile_cosyvoice.log):
  - 瓶颈是 llm 逐 token 解码(占 89%), 平均 104ms/token
  - 根因: ras_sampling 采样函数中 Python 循环逐元素索引 GPU tensor + 多次 .item()
          导致每 token ~27 次 GPU->CPU 同步; Windows WDDM 下同步开销巨大
  - torch.compile: triton 缺失(inductor 不可用), cudagraphs 编译 flow.estimator 后
          在真实推理中卡死/重捕获, 且 flow 仅占 9.5%, 不是瓶颈

本版:
  1. 手动复刻 Qwen2LM 解码循环, 拆出 forward(模型前向) vs sampling(采样) 耗时
  2. before: 官方 ras_sampling
  3. after : GPU 向量化快速采样(monkey-patch llm.sampling)
  4. 输出 before/after RTF 对比

运行:
  powershell: $env:CUDA_VISIBLE_DEVICES="1"; python profile_cosyvoice.py
"""
import sys, os, io, time, argparse
import numpy as np
import torch
import soundfile as sf

sys.path.insert(0, r'C:\CX-O\third_party\cosyvoice-official')
sys.path.insert(0, r'C:\CX-O\third_party\cosyvoice-official\third_party\Matcha-TTS')

MODEL_DIR = r'C:\CX-O\models\CosyVoice2-0.5B'
TMP_DIR = r'C:\CX-O\docker\llm\cosyvoice_tmp'
REF_WAV = os.path.join(TMP_DIR, 'profile_ref.wav')


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


def make_ref_wav(path, secs=1.0, sr=16000):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        sf.write(path, np.zeros(int(sr * secs), dtype=np.float32), sr, format='wav', subtype='PCM_16')


def sync():
    if torch.cuda.is_available():
        torch.cuda.synchronize()


def fmt_ms(sec):
    return f'{sec * 1000:.1f} ms'


def nucleus_sampling_fast(weighted_scores, top_p=0.8, top_k=25):
    """GPU 向量化 nucleus sampling: 一次 topk + cumsum, 避免逐元素 Python 循环同步。"""
    probs = weighted_scores.softmax(dim=0)
    top_probs, top_indices = torch.topk(probs, top_k)
    cumsum = torch.cumsum(top_probs, dim=0)
    cutoff = int((cumsum < top_p).sum().item()) + 1
    cutoff = min(max(cutoff, 1), top_k)
    top_probs = top_probs[:cutoff]
    top_indices = top_indices[:cutoff]
    top_ids = top_indices[top_probs.multinomial(1, replacement=True)].item()
    return top_ids


def ras_sampling_fast(weighted_scores, decoded_tokens, sampling, top_p=0.8, top_k=25, win_size=10, tau_r=0.1):
    top_ids = nucleus_sampling_fast(weighted_scores, top_p=top_p, top_k=top_k)
    if decoded_tokens:
        last = torch.tensor(decoded_tokens[-win_size:], device=weighted_scores.device)
        rep_num = int((last == top_ids).sum().item())
        if rep_num >= win_size * tau_r:
            weighted_scores[top_ids] = -float('inf')
            top_ids = weighted_scores.softmax(dim=0).multinomial(1, replacement=True).item()
    return top_ids


def run_llm(cv, model_input, timings):
    """手动复刻 Qwen2LM.inference 解码循环, 拆分 text_embedding / forward / sampling 计时。"""
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

    # ---- text_embedding ----
    text_full = torch.concat([prompt_text, text], dim=1)
    t0 = time.perf_counter()
    with torch.cuda.amp.autocast(model.fp16):
        text_emb = llm.llm.model.model.embed_tokens(text_full.to(device))
    sync()
    timings['text_embedding'] = time.perf_counter() - t0

    # ---- 构造 lm_input (复刻 Qwen2LM.inference) ----
    with torch.cuda.amp.autocast(model.fp16):
        sos_emb = llm.llm_embedding.weight[llm.sos].reshape(1, 1, -1)
        task_id_emb = llm.llm_embedding.weight[llm.task_id].reshape(1, 1, -1)
        if llm_prompt_speech_token_len != 0:
            prompt_speech_token_emb = llm.speech_embedding(llm_prompt_speech_token.to(device))
        else:
            prompt_speech_token_emb = torch.zeros(1, 0, llm.llm_input_size, dtype=text_emb.dtype).to(device)
        lm_input = torch.concat([sos_emb, text_emb, task_id_emb, prompt_speech_token_emb], dim=1)

    tts_text_len = int(text_len.item())
    min_len = tts_text_len * 2   # min_token_text_ratio=2
    max_len = tts_text_len * 20  # max_token_text_ratio=20

    # ---- 逐 token 解码 ----
    out_tokens = []
    cache = None
    forward_times, sampling_times = [], []
    t_llm0 = time.perf_counter()
    with torch.inference_mode():
        for i in range(max_len):
            t0 = time.perf_counter()
            y_pred, cache = llm.llm.forward_one_step(
                lm_input,
                masks=torch.tril(torch.ones((1, lm_input.shape[1], lm_input.shape[1]),
                                            device=lm_input.device)).to(torch.bool),
                cache=cache)
            sync()
            forward_times.append(time.perf_counter() - t0)

            t0 = time.perf_counter()
            logp = llm.llm_decoder(y_pred[:, -1]).log_softmax(dim=-1)
            top_ids = llm.sampling_ids(logp.squeeze(dim=0), out_tokens, 25,
                                       ignore_eos=True if i < min_len else False)
            sync()
            sampling_times.append(time.perf_counter() - t0)

            if top_ids in llm.stop_token_ids:
                break
            out_tokens.append(top_ids)
            lm_input = llm.speech_embedding.weight[top_ids].reshape(1, 1, -1)
    sync()
    timings['llm_total'] = time.perf_counter() - t_llm0
    timings['n_tokens'] = len(out_tokens)
    timings['llm_forward_avg'] = float(np.mean(forward_times)) if forward_times else 0.0
    timings['llm_sampling_avg'] = float(np.mean(sampling_times)) if sampling_times else 0.0
    timings['llm_forward_sum'] = float(np.sum(forward_times))
    timings['llm_sampling_sum'] = float(np.sum(sampling_times))
    return out_tokens


def run_pipeline(cv, model_input, timings):
    """完整非流式推理: llm -> flow -> hift, 各环节计时写入 timings。"""
    model = cv.model
    device = model.device

    out_tokens = run_llm(cv, model_input, timings)

    # ---- flow ----
    token_t = torch.tensor(out_tokens, dtype=torch.int32).unsqueeze(0).to(device)
    t0 = time.perf_counter()
    with torch.cuda.amp.autocast(model.fp16):
        tts_mel, _ = model.flow.inference(
            token=token_t,
            token_len=torch.tensor([token_t.shape[1]], dtype=torch.int32).to(device),
            prompt_token=model_input['flow_prompt_speech_token'].to(device),
            prompt_token_len=torch.tensor([model_input['flow_prompt_speech_token'].shape[1]], dtype=torch.int32).to(device),
            prompt_feat=model_input['prompt_speech_feat'].to(device),
            prompt_feat_len=torch.tensor([model_input['prompt_speech_feat'].shape[1]], dtype=torch.int32).to(device),
            embedding=model_input['flow_embedding'].to(device),
            streaming=False,
            finalize=True)
    sync()
    timings['flow'] = time.perf_counter() - t0

    # ---- hift ----
    t0 = time.perf_counter()
    with torch.cuda.amp.autocast(model.fp16):
        tts_speech, _ = model.hift.inference(
            speech_feat=tts_mel,
            cache_source=torch.zeros(1, 1, 0))
    sync()
    timings['hift'] = time.perf_counter() - t0

    timings['total'] = (timings['text_embedding'] + timings['llm_total']
                        + timings['flow'] + timings['hift'])
    timings['speech_secs'] = tts_speech.shape[1] / cv.sample_rate
    timings['rtf'] = timings['total'] / timings['speech_secs'] if timings['speech_secs'] > 0 else float('inf')
    return timings, tts_speech


def aggregate(results):
    keys = ['text_embedding', 'llm_total', 'llm_forward_avg', 'llm_sampling_avg',
            'llm_forward_sum', 'llm_sampling_sum', 'flow', 'hift', 'total', 'rtf']
    avg = {}
    for k in keys:
        vals = [r[0][k] for r in results if r[0].get(k) is not None]
        avg[k] = float(np.mean(vals)) if vals else 0.0
    avg['n_tokens'] = int(np.mean([r[0]['n_tokens'] for r in results]))
    avg['speech_secs'] = float(np.mean([r[0]['speech_secs'] for r in results]))
    return avg


def print_breakdown(title, t):
    print(f'\n-- {title} --')
    print(f"  text_embedding        {fmt_ms(t['text_embedding'])}")
    print(f"  llm_total             {fmt_ms(t['llm_total'])}  ({t['n_tokens']} tokens)")
    print(f"    llm.forward(模型)   每token {fmt_ms(t['llm_forward_avg'])}, 合计 {fmt_ms(t['llm_forward_sum'])}")
    print(f"    llm.sampling(采样)  每token {fmt_ms(t['llm_sampling_avg'])}, 合计 {fmt_ms(t['llm_sampling_sum'])}")
    print(f"  flow(10步)            {fmt_ms(t['flow'])}")
    print(f"  hift                  {fmt_ms(t['hift'])}")
    print(f"  total                 {fmt_ms(t['total'])}")
    print(f"  speech_secs           {t['speech_secs']:.2f} s")
    print(f"  RTF                   {t['rtf']:.3f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--text', default='今天天气真不错，我们一起出去走走吧。')
    ap.add_argument('--prompt', default='希望你以后能够做的比我还好呦。')
    ap.add_argument('--n', type=int, default=3)
    args = ap.parse_args()

    patch_load_wav()
    fix_onnx_env()
    make_ref_wav(REF_WAV)

    print('=' * 72)
    print('CosyVoice2-0.5B 非流式 RTF profiling v2 (LLM 采样优化对比)')
    print(f'  torch {torch.__version__}  cuda={torch.version.cuda}  fp16=True')
    print(f'  text={args.text!r}')
    print('=' * 72)

    print('\n>> Loading model ...')
    t0 = time.time()
    from cosyvoice.cli.cosyvoice import AutoModel
    cv = AutoModel(model_dir=MODEL_DIR, fp16=True)
    print(f'>> loaded in {time.time() - t0:.1f}s')
    model = cv.model
    print(f'  flow={type(model.flow).__name__}  hift={type(model.hift).__name__}  llm={type(model.llm).__name__}')

    t0 = time.perf_counter()
    model_input = cv.frontend.frontend_zero_shot(args.text, args.prompt, REF_WAV, cv.sample_rate, '')
    sync()
    print(f'>> frontend preprocess {fmt_ms(time.perf_counter() - t0)}')

    print('\n>> warmup run ...')
    run_pipeline(cv, model_input, {})
    print('>> warmup done')

    # ---- BEFORE (官方 ras_sampling) ----
    print(f'\n>> measuring BEFORE x{args.n} ...')
    results_before = [run_pipeline(cv, model_input, {}) for _ in range(args.n)]
    before = aggregate(results_before)
    print_breakdown('BEFORE', before)

    # ---- 采样优化: 替换 llm.sampling ----
    print('\n>> applying GPU vectorized sampling ...')
    llm = model.llm
    orig_sampling = llm.sampling
    llm.sampling = ras_sampling_fast
    print('>> attached ras_sampling_fast')

    print('\n>> warmup with fast sampling ...')
    run_pipeline(cv, model_input, {})
    print('>> warmup done')

    # ---- AFTER (快速采样) ----
    print(f'\n>> measuring AFTER x{args.n} ...')
    results_after = [run_pipeline(cv, model_input, {}) for _ in range(args.n)]
    after = aggregate(results_after)
    print_breakdown('AFTER', after)

    # ---- 对比 ----
    print('\n' + '=' * 72)
    print('BEFORE vs AFTER (均值)')
    print('=' * 72)
    for label, key in [('text_embedding', 'text_embedding'),
                       ('llm_total', 'llm_total'),
                       ('llm.forward(模型)', 'llm_forward_sum'),
                       ('llm.sampling(采样)', 'llm_sampling_sum'),
                       ('flow(10步)', 'flow'),
                       ('hift', 'hift'),
                       ('total', 'total')]:
        bv = before[key] * 1000
        av = after[key] * 1000
        sp = before[key] / after[key] if after[key] > 0 else float('inf')
        print(f"  {label:<22} {bv:>8.1f} ms    {av:>8.1f} ms    x{sp:.2f}")
    print(f"  {'llm forward/token':<22} {before['llm_forward_avg']*1000:>8.1f} ms    {after['llm_forward_avg']*1000:>8.1f} ms")
    print(f"  {'llm sampling/token':<22} {before['llm_sampling_avg']*1000:>8.1f} ms    {after['llm_sampling_avg']*1000:>8.1f} ms")
    print(f"  {'RTF':<22} {before['rtf']:>8.3f}    {after['rtf']:>8.3f}")
    print('=' * 72)

    print('\n>> 结论')
    if before['rtf'] > 0 and after['rtf'] > 0:
        print(f'  RTF: {before["rtf"]:.3f} -> {after["rtf"]:.3f}  (x{before["rtf"]/after["rtf"]:.2f})')
        if after['rtf'] < 1.0:
            print(f'  达到 RTF<1.0 目标: 是 (目标 {after["rtf"]*100:.0f}% 完成)')
        else:
            print(f'  达到 RTF<1.0 目标: 否, 仍需进一步优化')


if __name__ == '__main__':
    main()
