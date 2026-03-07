import os
import json
import math
import time
import threading
import ctypes
import io
import logging
from typing import Optional, Tuple, List

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
import tensorrt as trt
import torchaudio
import jieba
from tensorrt_llm._utils import str_dtype_to_torch
from tensorrt_llm import plugin

from .utils import (
    get_tokenizer,
    convert_char_to_pinyin,
    list_str_to_idx,
    normalize_audio,
    compute_mel_spectrogram,
)
from .vocoder import Vocoder

logger = logging.getLogger(__name__)


def load_text_embedding_checkpoint(checkpoint_path: str):
    checkpoint = torch.load(checkpoint_path, weights_only=True)
    state_dict = {}
    for key, value in checkpoint['ema_model_state_dict'].items():
        if key.startswith('text_embedding.'):
            new_key = key.replace('ema_model.', '')
            state_dict[new_key] = value
    return state_dict


class TextEmbedding(nn.Module):
    def __init__(self, text_num_embeds: int, text_dim: int = 512, conv_layers: int = 4, precompute_max_pos: int = 4096):
        super().__init__()
        self.text_embed = nn.Embedding(text_num_embeds, text_dim)
        self.text_dim = text_dim
        self.precompute_max_pos = precompute_max_pos
        
        self.norm = nn.LayerNorm(text_dim)
        
        self.conv_layers = nn.ModuleList([
            nn.Conv1d(text_dim, text_dim, kernel_size=3, padding=1)
            for _ in range(conv_layers)
        ])
        
    def forward(self, x: torch.Tensor, mask=None) -> torch.Tensor:
        x = self.text_embed(x)
        x = self.norm(x)
        x = x.transpose(1, 2)
        for conv in self.conv_layers:
            x = F.silu(conv(x))
        x = x.transpose(1, 2)
        return x


class F5TTSEngine:
    _instance = None
    _init_lock = threading.Lock()
    _inference_lock = threading.Lock()
    
    _plugin_loaded = False
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._init_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(
        self,
        engine_dir: str = "/engines",
        model_path: str = "/models/F5TTS_Base/model_1200000.pt",
        vocab_file: str = "/models/F5TTS_Base/vocab.txt",
        vocoder_engine_path: Optional[str] = None,
        target_sample_rate: int = 24000,
        max_mel_len: int = 2048,
        device_id: int = 0,
    ):
        if hasattr(self, '_initialized') and self._initialized:
            return
        
        if not F5TTSEngine._plugin_loaded:
            _plugin_lib_path = plugin.plugin_lib_path()
            ctypes.CDLL(_plugin_lib_path)
            F5TTSEngine._plugin_loaded = True
        
        self.device = torch.device(f"cuda:{device_id}")
        torch.cuda.set_device(self.device)
        torch.cuda._sleep(1)
        
        self.target_sample_rate = target_sample_rate
        self.target_rms = 0.15
        self.n_fft = 1024
        self.win_length = 1024
        self.hop_length = 256
        self.n_mel_channels = 100
        self.max_mel_len = max_mel_len
        self.head_dim = 64
        
        self._load_vocab(vocab_file)
        self._load_tensorrt_engine(engine_dir)
        self._load_text_embedding(model_path)
        self._init_rope_embeddings()
        self._init_time_embeddings()
        self._load_vocoder(vocoder_engine_path)
        
        self._initialized = True
    
    def _load_vocab(self, vocab_file: str):
        self.vocab_char_map, self.vocab_size = get_tokenizer(vocab_file)
        
    def _load_tensorrt_engine(self, engine_dir: str):
        engine_path = os.path.join(engine_dir, "rank0.engine")
        config_path = os.path.join(engine_dir, "config.json")
        
        if not os.path.exists(engine_path):
            raise FileNotFoundError(f"TensorRT engine not found: {engine_path}")
        
        with open(config_path) as f:
            self.config = json.load(f)
        
        self.dtype = self.config["pretrained_config"]["dtype"]
        
        with open(engine_path, "rb") as f:
            self.engine_buffer = f.read()
        
        self.trt_logger = trt.Logger(trt.Logger.WARNING)
        self.runtime = trt.Runtime(self.trt_logger)
        self.engine = self.runtime.deserialize_cuda_engine(self.engine_buffer)
        self.context = self.engine.create_execution_context()
        
        self.stream = torch.cuda.Stream(self.device)
        
        self._tensor_buffers = {}
        
    def _load_text_embedding(self, model_path: str):
        self.text_embedding = TextEmbedding(
            text_num_embeds=self.vocab_size,
            text_dim=512,
            conv_layers=4,
        ).to(self.device)
        
        state_dict = load_text_embedding_checkpoint(model_path)
        self.text_embedding.load_state_dict(state_dict, strict=False)
        self.text_embedding.eval()
        
    def _init_rope_embeddings(self):
        base = 10000.0
        inv_freq = 1.0 / (base ** (torch.arange(0, self.head_dim, 2).float() / self.head_dim))
        freqs = torch.outer(torch.arange(self.max_mel_len, dtype=torch.float32), inv_freq)
        self.freqs = freqs.repeat_interleave(2, dim=-1).unsqueeze(0)
        self.rope_cos = self.freqs.cos().half()
        self.rope_sin = self.freqs.sin().half()
        
    def _init_time_embeddings(self):
        self.nfe_steps = 16
        t = torch.linspace(0, 1, self.nfe_steps + 1, dtype=torch.float32)
        time_step = t + (-1.0) * (torch.cos(torch.pi * 0.5 * t) - 1 + t)
        delta_t = torch.diff(time_step)
        
        tmp_dim = 256
        time_expand = torch.zeros((1, self.nfe_steps, tmp_dim), dtype=torch.float32)
        half_dim = tmp_dim // 2
        emb_factor = math.log(10000) / (half_dim - 1)
        emb_factor = 1000.0 * torch.exp(torch.arange(half_dim, dtype=torch.float32) * -emb_factor)
        
        for i in range(self.nfe_steps):
            emb = time_step[i] * emb_factor
            time_expand[:, i, :] = torch.cat((emb.sin(), emb.cos()), dim=-1)
        
        self.time_expand = time_expand.to(self.device)
        self.delta_t = torch.cat((delta_t, delta_t), dim=0).contiguous().to(self.device)
        
    def _load_vocoder(self, vocoder_engine_path: Optional[str]):
        if vocoder_engine_path is None:
            vocoder_engine_path = "/models/vocoder/vocoder.plan"
        
        self.vocoder = Vocoder(vocoder_engine_path, self.device)
        
    def _forward_trt(
        self,
        noise: torch.Tensor,
        cond: torch.Tensor,
        rope_cos: torch.Tensor,
        rope_sin: torch.Tensor,
        input_lengths: torch.Tensor,
    ) -> torch.Tensor:
        cfg_strength = 2.0
        batch_size = noise.shape[0]
        half_batch = batch_size // 2
        noise_half = noise[:half_batch]
        
        input_type = str_dtype_to_torch(self.dtype)
        
        cond = cond.to(input_type)
        rope_cos = rope_cos.to(input_type)
        rope_sin = rope_sin.to(input_type)
        input_lengths = input_lengths.to(str_dtype_to_torch("int32"))
        
        time_expand = self.time_expand.repeat(batch_size, 1, 1).contiguous()
        
        for i in range(self.nfe_steps):
            current_noise = torch.cat([noise_half, noise_half], dim=0).to(input_type)
            current_time = time_expand[:, i].to(input_type)
            
            self.context.set_input_shape("noise", tuple(current_noise.shape))
            self.context.set_input_shape("cond", tuple(cond.shape))
            self.context.set_input_shape("time", tuple(current_time.shape))
            self.context.set_input_shape("rope_cos", tuple(rope_cos.shape))
            self.context.set_input_shape("rope_sin", tuple(rope_sin.shape))
            self.context.set_input_shape("input_lengths", tuple(input_lengths.shape))
            
            output_shape = self.context.get_tensor_shape("denoised")
            output = torch.empty(tuple(output_shape), dtype=input_type, device=self.device)
            
            with torch.cuda.stream(self.stream):
                self.context.set_tensor_address("noise", int(current_noise.data_ptr()))
                self.context.set_tensor_address("cond", int(cond.data_ptr()))
                self.context.set_tensor_address("time", int(current_time.data_ptr()))
                self.context.set_tensor_address("rope_cos", int(rope_cos.data_ptr()))
                self.context.set_tensor_address("rope_sin", int(rope_sin.data_ptr()))
                self.context.set_tensor_address("input_lengths", int(input_lengths.data_ptr()))
                self.context.set_tensor_address("denoised", int(output.data_ptr()))
                
                self.context.execute_async_v3(self.stream.cuda_stream)
            
            self.stream.synchronize()
            
            t_scale = self.delta_t[i].unsqueeze(0).to(input_type)
            pred_cond = output[:half_batch]
            pred_uncond = output[half_batch:]
            guidance = pred_cond + (pred_cond - pred_uncond) * cfg_strength
            noise_half = noise_half + guidance * t_scale
        
        return noise_half
        
    def infer(
        self,
        reference_wav: torch.Tensor,
        reference_wav_len: int,
        reference_sample_rate: int,
        reference_text: str,
        target_text: str,
    ) -> Tuple[torch.Tensor, float]:
        reference_audio = self._tensor_to_bytes(reference_wav, reference_sample_rate)
        audio_bytes = self.forward(reference_audio, reference_text, target_text)
        
        audio = self._bytes_to_tensor(audio_bytes)
        return audio, 0.0
    
    def _tensor_to_bytes(self, waveform: torch.Tensor, sample_rate: int) -> bytes:
        buffer = io.BytesIO()
        torchaudio.save(buffer, waveform.squeeze(0).cpu(), sample_rate, format="wav")
        buffer.seek(0)
        return buffer.read()
    
    def _bytes_to_tensor(self, audio_bytes: bytes) -> torch.Tensor:
        waveform, sample_rate = torchaudio.load(io.BytesIO(audio_bytes))
        return waveform
    
    def forward(
        self,
        reference_audio: bytes,
        reference_text: str,
        target_text: str,
    ) -> bytes:
        with F5TTSEngine._inference_lock:
            return self._forward_impl(reference_audio, reference_text, target_text)
    
    def _forward_impl(
        self,
        reference_audio: bytes,
        reference_text: str,
        target_text: str,
    ) -> bytes:
        target_text_pinyin = convert_char_to_pinyin([target_text])[0]
        
        ref_audio, _ = torchaudio.load(io.BytesIO(reference_audio))
        ref_audio = ref_audio.mean(0)
        
        target_words = target_text.split()
        if not target_words:
            target_words = [" "]
        target_idx = torch.tensor([self.vocab_char_map.get(c, 0) for w in target_words for c in w], dtype=torch.long, device=self.device).unsqueeze(0)
        
        ref_words = reference_text.split()
        if not ref_words:
            ref_words = [" "]
        ref_idx = torch.tensor([self.vocab_char_map.get(c, 0) for w in ref_words for c in w], dtype=torch.long, device=self.device).unsqueeze(0)
        
        mel_spec_transform = torchaudio.transforms.MelSpectrogram(
            n_fft=self.n_fft,
            win_length=self.win_length,
            hop_length=self.hop_length,
            n_mels=self.n_mel_channels,
        ).to(self.device)
        
        ref_audio = ref_audio.to(self.device)
        if ref_audio.dim() == 1:
            ref_audio = ref_audio.unsqueeze(0)
        ref_audio = normalize_audio(ref_audio, target_rms=self.target_rms)
        ref_mel = mel_spec_transform(ref_audio)
        if ref_mel.dim() == 2:
            ref_mel = ref_mel.unsqueeze(0)
        ref_mel = ref_mel.transpose(1, 2)
        ref_mel_len = ref_mel.shape[1]
        
        target_len = len(target_text) * 3
        estimated_mel_len = ref_mel_len + target_len
        estimated_mel_len = min(estimated_mel_len, self.max_mel_len)
        
        mel_features = torch.zeros((1, estimated_mel_len, self.n_mel_channels), dtype=torch.float16).to(self.device)
        mel_features[0, :ref_mel_len, :] = ref_mel.half()
        
        with torch.no_grad():
            text_embedding = self.text_embedding(target_idx)
            
            if text_embedding.shape[1] < estimated_mel_len:
                padding = estimated_mel_len - text_embedding.shape[1]
                text_embedding = torch.nn.functional.pad(text_embedding, (0, 0, 0, padding))
            elif text_embedding.shape[1] > estimated_mel_len:
                text_embedding = text_embedding[:, :estimated_mel_len, :]
            
            noise = torch.randn((1, estimated_mel_len, self.n_mel_channels), dtype=torch.float16, device=self.device)
            
            rope_cos = self.rope_cos[:, :estimated_mel_len, :].half()
            rope_sin = self.rope_sin[:, :estimated_mel_len, :].half()
            
            text_embedding_drop = torch.zeros_like(text_embedding)
            cat_mel_text = torch.cat((mel_features, text_embedding.half()), dim=-1)
            cat_mel_text_drop = torch.cat(
                (torch.zeros((1, estimated_mel_len, self.n_mel_channels), dtype=torch.float16, device=self.device),
                 text_embedding_drop.half()),
                dim=-1,
            )
            
            input_lengths = torch.tensor([estimated_mel_len], dtype=torch.int32, device=self.device)
            
            start_time = time.time()
            denoised = self._forward_trt(
                noise=torch.cat((noise, noise), dim=0).contiguous(),
                cond=torch.cat((cat_mel_text, cat_mel_text_drop), dim=0).contiguous(),
                rope_cos=torch.cat((rope_cos, rope_cos), dim=0).contiguous(),
                rope_sin=torch.cat((rope_sin, rope_sin), dim=0).contiguous(),
                input_lengths=torch.cat((input_lengths, input_lengths), dim=0).contiguous(),
            )
            inference_time = time.time() - start_time
        
        target_mel = denoised[0, ref_mel_len:estimated_mel_len, :].unsqueeze(0).transpose(1, 2)
        
        audio = self.vocoder(target_mel)
        
        audio = audio.squeeze().cpu().numpy()
        audio = (audio * 32767).astype(np.int16)
        
        buffer = io.BytesIO()
        torchaudio.save(buffer, torch.tensor(audio).unsqueeze(0).float(), self.target_sample_rate, format="wav")
        buffer.seek(0)
        
        return buffer.read()
