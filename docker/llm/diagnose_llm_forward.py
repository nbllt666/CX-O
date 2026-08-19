# -*- coding: utf-8 -*-
"""
LLM 前向性能诊断: 0.5B Qwen2 为什么每 token 前向 ~80ms

1. 用 CUDA event 测 GPU 计算时间 vs wall(CPU) 时间, 判断是计算密集还是 launch/同步瓶颈
2. 打印 per-token 时间序列(前5/中/后5), 判断 KV cache 是否生效(若生效时间应基本恒定)
3. 测试 llm.half()(权重转 fp16) 后前向提速

运行:
  powershell: $env:CUDA_VISIBLE_DEVICES="1"; python diagnose_llm_forward.py
"""
import sys, os, io, time
import numpy as np
import torch
import soundfile as sf

sys.path.insert(0, r'C:\CX-O\third_party\cosyvoice-official')
sys.path.insert(0, r'C:\CX-O\third_party\cosyvoice-official\third_party\Matcha-TTS')

MODEL_DIR = r'C:\CX-O\models\CosyVoice2-0.5B'
TMP_DIR = r'C:\CX-O\docker\llm\cosyvoice_tmp'
REF_WAV = os.path.join(TMP_DIR, 'profile_ref.wav')
N_STEPS = 40


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
    """复刻 Qwen2LM.inference 的 lm_input 构造。返回 lm_input, device, llm"""
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
    tts_text_len = int(text_len.item())
    return lm_input, device, llm, tts_text_len


def decode_steps(llm, lm_input, device, n_steps, tag):
    """跑 n_steps 步, 每步用 CUDA event 测 GPU 时间 + wall 时间。返回时间数组。"""
    cache = None
    lm_input = lm_input.clone()
    gpu_times, wall_times = [], []
    with torch.inference_mode(), torch.cuda.amp.autocast(True):
        for i in range(n_steps):
            masks = torch.tril(torch.ones((1, lm_input.shape[1], lm_input.shape[1]),
                                          device=lm_input.device)).to(torch.bool)
            e0 = torch.cuda.Event(enable_timing=True)
            e1 = torch.cuda.Event(enable_timing=True)
            t_w0 = time.perf_counter()
            e0.record()
            y_pred, cache = llm.llm.forward_one_step(lm_input, masks=masks, cache=cache)
            e1.record()
            e1.synchronize()
            gpu_ms = e0.elapsed_time(e1)
            wall_ms = (time.perf_counter() - t_w0) * 1000
            gpu_times.append(gpu_ms)
            wall_times.append(wall_ms)
            # 采样一步(保持与真实路径一致)
            logp = llm.llm_decoder(y_pred[:, -1]).log_softmax(dim=-1)
            top_ids = llm.sampling_ids(logp.squeeze(dim=0), [], 25, ignore_eos=True)
            lm_input = llm.speech_embedding.weight[top_ids].reshape(1, 1, -1)
    gpu = np.array(gpu_times)
    wall = np.array(wall_times)
    print(f'\n[{tag}] {n_steps} steps:')
    print(f'  GPU time (CUDA event): mean {gpu.mean():.1f} ms, first5 {[round(x,1) for x in gpu[:5]]}, '
          f'mid {[round(x,1) for x in gpu[n_steps//2-2:n_steps//2+3]]}, last5 {[round(x,1) for x in gpu[-5:]]}')
    print(f'  Wall time (CPU):       mean {wall.mean():.1f} ms')
    return gpu, wall


def main():
    patch_load_wav()
    fix_onnx_env()
    os.makedirs(TMP_DIR, exist_ok=True)
    if not os.path.exists(REF_WAV):
        sf.write(REF_WAV, np.zeros(16000, dtype=np.float32), 16000, format='wav', subtype='PCM_16')

    print('=' * 72)
    print('LLM forward 诊断 (0.5B Qwen2)')
    print(f'  torch {torch.__version__}  cuda={torch.version.cuda}')
    print('=' * 72)

    print('\n>> Loading model ...')
    t0 = time.time()
    from cosyvoice.cli.cosyvoice import AutoModel
    cv = AutoModel(model_dir=MODEL_DIR, fp16=True)
    print(f'>> loaded in {time.time() - t0:.1f}s')
    model = cv.model
    llm = model.llm
    print(f'  llm={type(llm).__name__}, Qwen2 layers={llm.llm.model.config.num_hidden_layers}, '
          f'hidden={llm.llm.model.config.hidden_size}')

    # 构造输入
    t0 = time.perf_counter()
    model_input = cv.frontend.frontend_zero_shot(
        '今天天气真不错，我们一起出去走走吧。', '希望你以后能够做的比我还好呦。',
        REF_WAV, cv.sample_rate, '')
    lm_input, device, llm, tts_len = build_lm_input(cv, model_input)
    torch.cuda.synchronize()
    print(f'>> lm_input shape={tuple(lm_input.shape)} (prefill seq len={lm_input.shape[1]})')

    # warmup 2 步
    cache = None
    with torch.inference_mode():
        for _ in range(2):
            masks = torch.tril(torch.ones((1, lm_input.shape[1], lm_input.shape[1]), device=device)).to(torch.bool)
            y_pred, cache = llm.llm.forward_one_step(lm_input, masks=masks, cache=cache)
            lm_input = llm.speech_embedding.weight[0].reshape(1, 1, -1)
    torch.cuda.synchronize()
    lm_input, _, _, _ = build_lm_input(cv, model_input)  # 重置

    # 1) fp32 权重 + autocast (官方默认)
    print('\n>> [FP32 weight + autocast] 官方默认')
    gpu_fp32, wall_fp32 = decode_steps(llm, lm_input, device, N_STEPS, 'FP32+autocast')

    # 2) fp16 权重 (llm.half())
    print('\n>> Applying llm.half() ...')
    llm.half()
    torch.cuda.synchronize()
    lm_input, _, _, _ = build_lm_input(cv, model_input)  # 重建输入(fp16)
    print('>> [FP16 weight]')
    gpu_fp16, wall_fp16 = decode_steps(llm, lm_input, device, N_STEPS, 'FP16 weight')

    # 3) 恢复 fp32 + tf32
    print('\n>> Restore fp32 + enable tf32 matmul ...')
    llm.float()
    torch.backends.cuda.matmul.allow_tf32 = True
    torch.backends.cudnn.allow_tf32 = True
    torch.cuda.synchronize()
    lm_input, _, _, _ = build_lm_input(cv, model_input)
    print('>> [FP32 + tf32]')
    gpu_fp32t, wall_fp32t = decode_steps(llm, lm_input, device, N_STEPS, 'FP32+TF32')

    print('\n' + '=' * 72)
    print('对比 (GPU mean / Wall mean)')
    print('=' * 72)
    for tag, g, w in [('FP32+autocast', gpu_fp32, wall_fp32),
                      ('FP16 weight  ', gpu_fp16, wall_fp16),
                      ('FP32+TF32    ', gpu_fp32t, wall_fp32t)]:
        print(f'  {tag}: GPU {g.mean():6.1f} ms   Wall {w.mean():6.1f} ms')
    print('=' * 72)


if __name__ == '__main__':
    main()
