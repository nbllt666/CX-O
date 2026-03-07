#!/usr/bin/env python3
"""
F5TTS 模型导出到 ONNX 格式
"""

import os
import sys
import json
import argparse
import torch
import torch.nn as nn
import torch.nn.functional as F
import math


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
    def __init__(self, dim: int):
        super().__init__()
        self.time_mlp = nn.Sequential(
            nn.Linear(dim, dim * 4),
            nn.SiLU(),
            nn.Linear(dim * 4, dim),
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
        self.dim_head = dim_head
        
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
        
    def forward(self, x: torch.Tensor, t: torch.Tensor, rope_cos: torch.Tensor, rope_sin: torch.Tensor, input_lengths: torch.Tensor = None) -> torch.Tensor:
        residual = x
        x = self.norm1(x)
        
        B, L, C = x.shape
        
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
        self.conv_pos_embed = nn.Conv1d(out_dim, out_dim, kernel_size=3, padding=1)
        
    def forward(self, x: torch.Tensor, cond: torch.Tensor) -> torch.Tensor:
        x = self.proj(torch.cat([x, cond], dim=-1))
        x = x.transpose(1, 2)
        x = self.conv_pos_embed(x)
        x = x + x.transpose(1, 2)
        return x.transpose(1, 2)


class F5TTSExporter(nn.Module):
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
        
        self.time_embed = TimestepEmbedding(hidden_size)
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
        rope_cos: torch.Tensor,
        rope_sin: torch.Tensor,
        input_lengths: torch.Tensor,
    ) -> torch.Tensor:
        time = time_expand[:, 0, :]
        t = self.time_embed(time)
        x = self.input_embed(noise, cond)
        
        for block in self.transformer_blocks:
            x = block(x, t, rope_cos=rope_cos, rope_sin=rope_sin, input_lengths=input_lengths)
        
        x = self.norm_out(x, t)
        denoised = self.proj_out(x)
        
        return denoised


def load_checkpoint(checkpoint_path: str):
    checkpoint = torch.load(checkpoint_path, weights_only=True)
    state_dict = {}
    for key, value in checkpoint['ema_model_state_dict'].items():
        if key.startswith('text_embedding.'):
            new_key = key.replace('ema_model.', '')
            state_dict[new_key] = value
    return state_dict


def export_f5tts_to_onnx(
    model_path: str,
    output_path: str,
    vocab_size: int = 256,
    hidden_size: int = 1024,
    num_hidden_layers: int = 22,
    num_attention_heads: int = 16,
    dim_head: int = 64,
    ff_mult: int = 2,
    dropout: float = 0.1,
    mel_dim: int = 100,
    text_dim: int = 512,
    max_seq_len: int = 2048,
):
    print("Creating F5TTS model...")
    
    model = F5TTSExporter(
        hidden_size=hidden_size,
        num_hidden_layers=num_hidden_layers,
        num_attention_heads=num_attention_heads,
        dim_head=dim_head,
        ff_mult=ff_mult,
        dropout=dropout,
        mel_dim=mel_dim,
        text_dim=text_dim,
    )
    model = model.half()
    
    checkpoint = torch.load(model_path, weights_only=True)
    ema_state_dict = checkpoint['ema_model_state_dict']
    
    model_state_dict = {}
    for key, value in ema_state_dict.items():
        if key.startswith('model.'):
            new_key = key.replace('model.', '')
            model_state_dict[new_key] = value.half() if isinstance(value, torch.Tensor) else value
    
    model.load_state_dict(model_state_dict, strict=False)
    model.eval()
    
    print(f"Exporting to ONNX: {output_path}")
    
    dummy_batch_size = 2
    dummy_seq_len = 100
    time_steps = 16
    time_dim = 256
    
    noise = torch.randn(dummy_batch_size, dummy_seq_len, mel_dim, dtype=torch.float16)
    cond = torch.randn(dummy_batch_size, dummy_seq_len, mel_dim + text_dim, dtype=torch.float16)
    time_expand = torch.randn(dummy_batch_size, time_steps, time_dim, dtype=torch.float16)
    rope_cos = torch.randn(dummy_batch_size, dummy_seq_len, dim_head, dtype=torch.float16)
    rope_sin = torch.randn(dummy_batch_size, dummy_seq_len, dim_head, dtype=torch.float16)
    input_lengths = torch.tensor([dummy_seq_len] * dummy_batch_size, dtype=torch.int32)
    
    torch.onnx.export(
        model,
        (noise, cond, time_expand, rope_cos, rope_sin, input_lengths),
        output_path,
        input_names=['noise', 'cond', 'time_expand', 'rope_cos', 'rope_sin', 'input_lengths'],
        output_names=['denoised'],
        dynamic_axes={
            'noise': {0: 'batch_size', 1: 'seq_len'},
            'cond': {0: 'batch_size', 1: 'seq_len'},
            'time_expand': {0: 'batch_size', 1: 'time_steps'},
            'rope_cos': {0: 'batch_size', 1: 'seq_len'},
            'rope_sin': {0: 'batch_size', 1: 'seq_len'},
            'input_lengths': {0: 'batch_size'},
            'denoised': {0: 'batch_size', 1: 'seq_len'},
        },
        opset_version=17,
        verbose=False,
    )
    
    print(f"ONNX model exported to: {output_path}")
    
    file_size = os.path.getsize(output_path) / (1024 * 1024)
    print(f"Model size: {file_size:.2f} MB")
    
    return output_path


def main():
    parser = argparse.ArgumentParser(description="Export F5TTS to ONNX")
    parser.add_argument("--model_path", type=str, default="/models/F5TTS_Base/model_1200000.pt")
    parser.add_argument("--output_path", type=str, default="/models/F5TTS_Base/f5tts.onnx")
    parser.add_argument("--vocab_size", type=int, default=256)
    parser.add_argument("--hidden_size", type=int, default=1024)
    parser.add_argument("--num_hidden_layers", type=int, default=22)
    parser.add_argument("--num_attention_heads", type=int, default=16)
    parser.add_argument("--dim_head", type=int, default=64)
    parser.add_argument("--ff_mult", type=int, default=2)
    parser.add_argument("--dropout", type=float, default=0.1)
    parser.add_argument("--mel_dim", type=int, default=100)
    parser.add_argument("--text_dim", type=int, default=512)
    parser.add_argument("--max_seq_len", type=int, default=2048)
    
    args = parser.parse_args()
    
    export_f5tts_to_onnx(
        model_path=args.model_path,
        output_path=args.output_path,
        vocab_size=args.vocab_size,
        hidden_size=args.hidden_size,
        num_hidden_layers=args.num_hidden_layers,
        num_attention_heads=args.num_attention_heads,
        dim_head=args.dim_head,
        ff_mult=args.ff_mult,
        dropout=args.dropout,
        mel_dim=args.mel_dim,
        text_dim=args.text_dim,
        max_seq_len=args.max_seq_len,
    )


if __name__ == "__main__":
    main()
