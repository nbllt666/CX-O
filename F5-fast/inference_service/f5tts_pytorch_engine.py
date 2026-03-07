import io
import json
import logging
import math
import time
import threading
from typing import Optional, Tuple

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
import torchaudio
import jieba

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def load_text_embedding_checkpoint(checkpoint_path: str):
    checkpoint = torch.load(checkpoint_path, weights_only=True)
    state_dict = {}
    for key, value in checkpoint['ema_model_state_dict'].items():
        if key.startswith('ema_model.transformer.text_embed.'):
            new_key = key.replace('ema_model.transformer.', '')
            state_dict[new_key] = value
    return state_dict


class TextEmbedding(nn.Module):
    def __init__(self, text_num_embeds: int, text_dim: int = 512, conv_layers: int = 4):
        super().__init__()
        self.text_embed = nn.Embedding(text_num_embeds, text_dim)
        self.text_dim = text_dim
        
        self.norm = nn.LayerNorm(text_dim)
        
        self.conv_layers = nn.ModuleList([
            nn.Conv1d(text_dim, text_dim, kernel_size=3, padding=1)
            for _ in range(conv_layers)
        ])
        
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.text_embed(x)
        x = self.norm(x)
        x = x.transpose(1, 2)
        for conv in self.conv_layers:
            x = F.silu(conv(x))
        x = x.transpose(1, 2)
        return x


class TimestepEmbedding(nn.Module):
    def __init__(self, time_dim: int = 256, hidden_dim: int = 1024):
        super().__init__()
        self.time_mlp = nn.Sequential(
            nn.Linear(time_dim, hidden_dim),
            nn.SiLU(),
            nn.Linear(hidden_dim, hidden_dim),
        )
        
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.time_mlp(x)


class GRN(nn.Module):
    def __init__(self, dim: int):
        super().__init__()
        self.gamma = nn.Parameter(torch.zeros(1, 1, dim))
        self.beta = nn.Parameter(torch.zeros(1, 1, dim))
        
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        Gx = torch.norm(x, p=2, dim=1, keepdim=True)
        Nx = Gx / (Gx.mean(dim=-1, keepdim=True) + 1e-6)
        return self.gamma * (x * Nx) + self.beta + x


class ConvNeXtV2Block(nn.Module):
    def __init__(self, dim: int, intermediate_dim: int, dilation: int = 1):
        super().__init__()
        padding = (dilation * (7 - 1)) // 2
        self.dwconv = nn.Conv1d(dim, dim, kernel_size=7, padding=padding, groups=dim, dilation=dilation)
        self.norm = nn.LayerNorm(dim, eps=1e-6)
        self.pwconv1 = nn.Linear(dim, intermediate_dim)
        self.act = nn.GELU()
        self.grn = GRN(intermediate_dim)
        self.pwconv2 = nn.Linear(intermediate_dim, dim)
        
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        residual = x
        x = x.transpose(1, 2)
        x = self.dwconv(x)
        x = x.transpose(1, 2)
        x = self.norm(x)
        x = self.pwconv1(x)
        x = self.act(x)
        x = self.grn(x)
        x = self.pwconv2(x)
        return residual + x


class DiTBlock(nn.Module):
    def __init__(self, dim: int, heads: int = 16, dim_head: int = 64, ff_mult: int = 2, dropout: float = 0.0):
        super().__init__()
        self.dim = dim
        self.heads = heads
        
        self.norm1 = nn.LayerNorm(dim)
        self.attn = nn.MultiheadAttention(dim, heads, dropout=dropout, batch_first=True)
        self.norm2 = nn.LayerNorm(dim)
        self.ff = nn.Sequential(
            nn.Linear(dim, dim * ff_mult),
            nn.GELU(),
            nn.Linear(dim * ff_mult, dim),
        )
        self.norm3 = nn.LayerNorm(dim)
        self.grn = GRN(dim)
        
    def forward(self, x: torch.Tensor, t: torch.Tensor, rope_cos: torch.Tensor = None, rope_sin: torch.Tensor = None, input_lengths: torch.Tensor = None) -> torch.Tensor:
        residual = x
        x = self.norm1(x)
        
        attn_output, _ = self.attn(x, x, x)
        x = residual + attn_output
        
        residual = x
        x = self.norm2(x)
        x = x + self.ff(x)
        
        residual = x
        x = self.norm3(x)
        x = self.grn(x)
        x = x + residual
        
        return x


class AdaLayerNormZero_Final(nn.Module):
    def __init__(self, dim: int):
        super().__init__()
        self.norm = nn.LayerNorm(dim, elementwise_affine=False, eps=1e-6)
        self.linear = nn.Linear(dim, dim * 2)
        
    def forward(self, x: torch.Tensor, t: torch.Tensor) -> torch.Tensor:
        x = self.norm(x)
        t = self.linear(t)
        t = t.unsqueeze(1)
        scale, shift = t.chunk(2, dim=-1)
        return x * (1 + scale) + shift


class InputEmbedding(nn.Module):
    def __init__(self, mel_dim: int, text_dim: int, out_dim: int):
        super().__init__()
        self.proj = nn.Linear(mel_dim * 2 + text_dim, out_dim)
        
    def forward(self, x: torch.Tensor, cond: torch.Tensor) -> torch.Tensor:
        x = self.proj(torch.cat([x, cond], dim=-1))
        return x


class F5TTSModel(nn.Module):
    def __init__(
        self,
        hidden_size: int = 1024,
        num_hidden_layers: int = 22,
        num_attention_heads: int = 16,
        dim_head: int = 64,
        ff_mult: int = 2,
        dropout: float = 0.1,
        mel_dim: int = 100,
        text_dim: int = 512,
    ):
        super().__init__()
        
        self.hidden_size = hidden_size
        self.num_hidden_layers = num_hidden_layers
        self.num_attention_heads = num_attention_heads
        self.dim_head = dim_head
        
        self.time_embed = TimestepEmbedding(time_dim=256, hidden_dim=1024)
        self.input_embed = InputEmbedding(mel_dim, text_dim, hidden_size)
        
        self.transformer_blocks = nn.ModuleList([
            DiTBlock(
                dim=hidden_size,
                heads=num_attention_heads,
                dim_head=dim_head,
                ff_mult=ff_mult,
                dropout=dropout,
            )
            for _ in range(num_hidden_layers)
        ])
        
        self.norm_out = AdaLayerNormZero_Final(hidden_size)
        self.proj_out = nn.Linear(hidden_size, mel_dim)
        
    def forward(
        self,
        noise: torch.Tensor,
        cond: torch.Tensor,
        time_expand: torch.Tensor,
        rope_cos: torch.Tensor = None,
        rope_sin: torch.Tensor = None,
        input_lengths: torch.Tensor = None,
    ) -> torch.Tensor:
        if time_expand.dim() == 2:
            time_expand = time_expand.unsqueeze(1)
        if time_expand.shape[1] > 1:
            time = time_expand[:, 0, :]
        else:
            time = time_expand.squeeze(1)
        t = self.time_embed(time)
        x = self.input_embed(noise, cond)
        
        for block in self.transformer_blocks:
            x = block(x, t, rope_cos=rope_cos, rope_sin=rope_sin, input_lengths=input_lengths)
        
        x = self.norm_out(x, t)
        denoised = self.proj_out(x)
        
        return denoised


class F5TTSEngine:
    _instance = None
    _init_lock = threading.Lock()
    _inference_lock = threading.Lock()
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._init_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(
        self,
        model_path: str = "/models/F5TTS_Base/model_1200000.pt",
        vocab_file: str = "/models/F5TTS_Base/vocab.txt",
        vocoder_engine_path: Optional[str] = None,
        target_sample_rate: int = 24000,
        max_mel_len: int = 2048,
        device_id: int = 0,
    ):
        if hasattr(self, '_initialized') and self._initialized:
            return
        
        self.device = torch.device(f"cuda:{device_id}" if torch.cuda.is_available() else "cpu")
        
        if torch.cuda.is_available():
            torch.cuda.set_device(self.device)
        
        self.target_sample_rate = target_sample_rate
        self.target_rms = 0.15
        self.n_fft = 1024
        self.win_length = 1024
        self.hop_length = 256
        self.n_mel_channels = 100
        self.max_mel_len = max_mel_len
        self.head_dim = 64
        
        if torch.cuda.is_available():
            self.stream = torch.cuda.Stream(device=self.device)
        else:
            self.stream = None
        
        self._load_vocab(vocab_file)
        self._load_model(model_path)
        self._init_rope_embeddings()
        self._init_time_embeddings()
        self._load_vocoder()
        self._warmup()
        
        self._initialized = True
        logger.info("F5TTS Engine initialized successfully")
    
    def _load_vocoder(self, vocoder_path: str = "/models/vocos_vocoder.plan"):
        import sys
        sys.path.insert(0, '/app/inference_service')
        from vocoder import Vocoder
        self.vocoder = Vocoder(vocoder_path, self.device, self.stream)
        logger.info("Vocoder loaded successfully")
    
    def _warmup(self):
        logger.info("Starting model warmup...")
        
        mel_dim = 100
        text_dim = 512
        hidden_size = 1024
        
        dummy_noise = torch.randn(1, 100, mel_dim, dtype=torch.float16, device=self.device)
        dummy_cond = torch.randn(1, 100, mel_dim + text_dim, dtype=torch.float16, device=self.device)
        dummy_time = self.time_expand[:, 0, :]
        dummy_rope = self.rope_cos[:, :100, :].half()
        
        with torch.inference_mode():
            for _ in range(3):
                _ = self.model(
                    noise=dummy_noise,
                    cond=dummy_cond,
                    time_expand=dummy_time,
                    rope_cos=dummy_rope,
                    rope_sin=dummy_rope,
                )
        
        if torch.cuda.is_available():
            torch.cuda.synchronize()
        
        logger.info("Model warmup completed")
    
    def _load_vocab(self, vocab_file: str):
        vocab_char_map = {}
        with open(vocab_file, 'r', encoding='utf-8') as f:
            for idx, line in enumerate(f):
                char = line.strip()
                if char:
                    vocab_char_map[char] = idx
        self.vocab_char_map = vocab_char_map
        self.vocab_size = len(vocab_char_map) + 1
    
    def _load_model(self, model_path: str):
        self.model = F5TTSModel(
            hidden_size=1024,
            num_hidden_layers=22,
            num_attention_heads=16,
            dim_head=64,
            ff_mult=2,
            dropout=0.1,
            mel_dim=100,
            text_dim=512,
        ).to(self.device).half()
        
        checkpoint = torch.load(model_path, weights_only=True, map_location=self.device)
        ema_state_dict = checkpoint['ema_model_state_dict']
        
        model_state_dict = {}
        for key, value in ema_state_dict.items():
            if key.startswith('ema_model.transformer.'):
                new_key = key.replace('ema_model.transformer.', '')
                model_state_dict[new_key] = value
        
        self.model.load_state_dict(model_state_dict, strict=False)
        self.model.eval()
        
        self.text_embedding = TextEmbedding(
            text_num_embeds=2546,
            text_dim=512,
            conv_layers=4,
        ).to(self.device).half()
        
        text_state_dict = load_text_embedding_checkpoint(model_path)
        self.text_embedding.load_state_dict(text_state_dict, strict=False)
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
        
        self.time_expand = time_expand.half().to(self.device)
        self.delta_t = torch.cat((delta_t, delta_t), dim=0).contiguous().half().to(self.device)
        
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
        ref_audio, _ = torchaudio.load(io.BytesIO(reference_audio))
        ref_audio = ref_audio.mean(0)
        
        target_words = target_text.split()
        if not target_words:
            target_words = [" "]
        target_idx = torch.tensor([self.vocab_char_map.get(c, 0) for w in target_words for c in w], dtype=torch.long, device=self.device).unsqueeze(0)
        
        mel_spec_transform = torchaudio.transforms.MelSpectrogram(
            n_fft=self.n_fft,
            win_length=self.win_length,
            hop_length=self.hop_length,
            n_mels=self.n_mel_channels,
        ).to(self.device)
        
        ref_audio = ref_audio.to(self.device)
        if ref_audio.dim() == 1:
            ref_audio = ref_audio.unsqueeze(0)
        
        ref_audio = ref_audio - ref_audio.mean()
        ref_audio = ref_audio / (ref_audio.std() + 1e-6) * self.target_rms
        
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
        
        with torch.inference_mode():
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
            
            start_time = time.time()
            denoised = self._forward_diffusion(
                noise=torch.cat((noise, noise), dim=0).contiguous(),
                cond=torch.cat((cat_mel_text, cat_mel_text_drop), dim=0).contiguous(),
                rope_cos=torch.cat((rope_cos, rope_cos), dim=0).contiguous(),
                rope_sin=torch.cat((rope_sin, rope_sin), dim=0).contiguous(),
            )
            inference_time = time.time() - start_time
            logger.info(f"Inference time: {inference_time:.3f}s")
        
        target_mel = denoised[0, ref_mel_len:estimated_mel_len, :].unsqueeze(0).transpose(1, 2)
        
        audio = self.vocoder(target_mel.half())
        
        audio = audio.squeeze().cpu().numpy()
        
        buffer = io.BytesIO()
        torchaudio.save(buffer, torch.tensor(audio).unsqueeze(0).float(), self.target_sample_rate, format="wav")
        buffer.seek(0)
        
        return buffer.read()
    
    def _forward_diffusion(
        self,
        noise: torch.Tensor,
        cond: torch.Tensor,
        rope_cos: torch.Tensor,
        rope_sin: torch.Tensor,
    ) -> torch.Tensor:
        cfg_strength = 2.0
        batch_size = noise.shape[0]
        half_batch = batch_size // 2
        noise_half = noise[:half_batch]
        
        for i in range(self.nfe_steps):
            current_noise = torch.cat([noise_half, noise_half], dim=0)
            current_time = self.time_expand[:, i, :]
            
            denoised = self.model(
                noise=current_noise,
                cond=cond,
                time_expand=current_time,
                rope_cos=rope_cos,
                rope_sin=rope_sin,
            )
            
            t_scale = self.delta_t[i].unsqueeze(0)
            pred_cond = denoised[:half_batch]
            pred_uncond = denoised[half_batch:]
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
