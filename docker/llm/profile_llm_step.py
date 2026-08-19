# -*- coding: utf-8 -*-
"""用 torch.profiler 定位 Qwen2 forward_one_step 的 GPU 热点。"""
import sys, os, io, time
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


def main():
    patch_load_wav()
    fix_onnx_env()
    os.makedirs(TMP_DIR, exist_ok=True)
    if not os.path.exists(REF_WAV):
        sf.write(REF_WAV, np.zeros(16000, dtype=np.float32), 16000, format='wav', subtype='PCM_16')

    print('>> Loading model ...')
    t0 = time.time()
    from cosyvoice.cli.cosyvoice import AutoModel
    cv = AutoModel(model_dir=MODEL_DIR, fp16=True)
    print(f'>> loaded in {time.time() - t0:.1f}s')
    model = cv.model
    llm = model.llm
    device = model.device

    model_input = cv.frontend.frontend_zero_shot(
        '今天天气真不错，我们一起出去走走吧。', '希望你以后能够做的比我还好呦。',
        REF_WAV, cv.sample_rate, '')

    text = model_input['text'].to(device)
    text_len = model_input['text_len'].to(device)
    prompt_text = model_input['prompt_text'].to(device)
    prompt_text_len = model_input['prompt_text_len'].to(device)
    llm_prompt_speech_token = model_input['llm_prompt_speech_token'].to(device)
    llm_prompt_speech_token_len = torch.tensor([llm_prompt_speech_token.shape[1]], dtype=torch.int32).to(device)
    llm_embedding = model_input['llm_embedding'].to(device)

    with torch.cuda.amp.autocast(model.fp16):
        text_emb = llm.llm.model.model.embed_tokens(torch.concat([prompt_text, text], dim=1))
        sos_emb = llm.llm_embedding.weight[llm.sos].reshape(1, 1, -1)
        task_id_emb = llm.llm_embedding.weight[llm.task_id].reshape(1, 1, -1)
        if llm_prompt_speech_token_len != 0:
            prompt_speech_token_emb = llm.speech_embedding(llm_prompt_speech_token)
        else:
            prompt_speech_token_emb = torch.zeros(1, 0, llm.llm_input_size, dtype=text_emb.dtype).to(device)
        lm_input = torch.concat([sos_emb, text_emb, task_id_emb, prompt_speech_token_emb], dim=1)
    torch.cuda.synchronize()

    # warmup: prefill + 2 decode
    cache = None
    with torch.inference_mode():
        for i in range(2):
            masks = torch.tril(torch.ones((1, lm_input.shape[1], lm_input.shape[1]), device=device)).to(torch.bool)
            y_pred, cache = llm.llm.forward_one_step(lm_input, masks=masks, cache=cache)
            logp = llm.llm_decoder(y_pred[:, -1]).log_softmax(dim=-1)
            top_ids = llm.sampling_ids(logp.squeeze(dim=0), [], 25, ignore_eos=True)
            lm_input = llm.speech_embedding.weight[top_ids].reshape(1, 1, -1)
    torch.cuda.synchronize()

    # profile 1 decode step
    masks = torch.tril(torch.ones((1, lm_input.shape[1], lm_input.shape[1]), device=device)).to(torch.bool)
    with torch.profiler.profile(activities=[torch.profiler.ProfilerActivity.CUDA,
                                            torch.profiler.ProfilerActivity.CPU],
                                record_shapes=True) as prof:
        with torch.inference_mode():
            for _ in range(3):
                y_pred, cache = llm.llm.forward_one_step(lm_input, masks=masks, cache=cache)
                logp = llm.llm_decoder(y_pred[:, -1]).log_softmax(dim=-1)
                top_ids = llm.sampling_ids(logp.squeeze(dim=0), [], 25, ignore_eos=True)
                lm_input = llm.speech_embedding.weight[top_ids].reshape(1, 1, -1)
        torch.cuda.synchronize()

    print('\n== Top 25 CUDA time (sum over 3 steps) ==')
    print(prof.key_averages().table(sort_by='cuda_time_total', row_limit=25))
    print('\n== Top 10 CUDA time (avg per step) ==')
    evt = prof.key_averages()
    cuda_evt = [e for e in evt if e.self_cuda_time_total > 0]
    cuda_evt.sort(key=lambda e: e.self_cuda_time_total, reverse=True)
    for e in cuda_evt[:10]:
        print(f'  {e.key[:70]:<72} self_cuda {e.self_cuda_time_total/3:8.2f} ms')


if __name__ == '__main__':
    main()
