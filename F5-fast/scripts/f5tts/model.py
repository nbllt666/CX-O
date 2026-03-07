from __future__ import annotations
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import tensorrt as trt
from collections import OrderedDict
from tensorrt_llm._utils import str_dtype_to_trt
from tensorrt_llm.plugin import current_all_reduce_helper
from tensorrt_llm.models.modeling_utils import PretrainedConfig, PretrainedModel
from tensorrt_llm.functional import Tensor, concat
from tensorrt_llm.module import Module, ModuleList
from tensorrt_llm._common import default_net
from tensorrt_llm.layers import Linear

from modules import (
    TimestepEmbedding,
    ConvPositionEmbedding,
    DiTBlock,
    AdaLayerNormZero_Final,
)


class InputEmbedding(Module):
    def __init__(self, mel_dim, text_dim, out_dim):
        super().__init__()
        self.proj = Linear(mel_dim * 2 + text_dim, out_dim)
        self.conv_pos_embed = ConvPositionEmbedding(dim=out_dim)

    def forward(self, x, cond):
        x = self.proj(concat([x, cond], dim=-1))
        return self.conv_pos_embed(x) + x


class F5TTS(PretrainedModel):
    def __init__(self, config: PretrainedConfig):
        super().__init__(config)
        self.dtype = str_dtype_to_trt(config.dtype)

        self.time_embed = TimestepEmbedding(config.hidden_size)
        self.input_embed = InputEmbedding(config.mel_dim, config.text_dim, config.hidden_size)
        self.dim = config.hidden_size
        self.depth = config.num_hidden_layers
        self.transformer_blocks = ModuleList(
            [
                DiTBlock(
                    dim=self.dim,
                    heads=config.num_attention_heads,
                    dim_head=config.dim_head,
                    ff_mult=config.ff_mult,
                    dropout=config.dropout,
                )
                for _ in range(self.depth)
            ]
        )
        self.norm_out = AdaLayerNormZero_Final(config.hidden_size)
        self.proj_out = Linear(config.hidden_size, config.mel_dim)

    def forward(
        self,
        noise,
        cond,
        time,
        rope_cos,
        rope_sin,
        input_lengths,
        scale=1.0,
    ):
        t = self.time_embed(time)
        x = self.input_embed(noise, cond)
        for block in self.transformer_blocks:
            x = block(x, t, rope_cos=rope_cos, rope_sin=rope_sin, input_lengths=input_lengths, scale=scale)
        denoise = self.proj_out(self.norm_out(x, t))
        denoise.mark_output("denoised", self.dtype)
        return denoise

    def prepare_inputs(self, **kwargs):
        max_batch_size = kwargs["max_batch_size"]
        batch_size_range = [2, 2, max_batch_size]
        mel_size = 100
        max_seq_len = 2048
        hidden_size = 512
        concat_feature_dim = mel_size + hidden_size
        freq_embed_dim = 256
        head_dim = 64
        mapping = self.config.mapping
        if mapping.tp_size > 1:
            current_all_reduce_helper().set_workspace_tensor(mapping, 1)
        
        noise = Tensor(
            name="noise",
            dtype=self.dtype,
            shape=[-1, -1, mel_size],
            dim_range=OrderedDict(
                [
                    ("batch_size", [batch_size_range]),
                    ("max_duration", [[100, max_seq_len // 2, max_seq_len]]),
                    ("n_mels", [mel_size]),
                ]
            ),
        )
        cond = Tensor(
            name="cond",
            dtype=self.dtype,
            shape=[-1, -1, concat_feature_dim],
            dim_range=OrderedDict(
                [
                    ("batch_size", [batch_size_range]),
                    ("max_duration", [[100, max_seq_len // 2, max_seq_len]]),
                    ("embeded_length", [concat_feature_dim]),
                ]
            ),
        )
        time = Tensor(
            name="time",
            dtype=self.dtype,
            shape=[-1, freq_embed_dim],
            dim_range=OrderedDict(
                [
                    ("batch_size", [batch_size_range]),
                    ("freq_dim", [freq_embed_dim]),
                ]
            ),
        )
        rope_cos = Tensor(
            name="rope_cos",
            dtype=self.dtype,
            shape=[-1, -1, head_dim],
            dim_range=OrderedDict(
                [
                    ("batch_size", [batch_size_range]),
                    ("max_duration", [[100, max_seq_len // 2, max_seq_len]]),
                    ("head_dim", [head_dim]),
                ]
            ),
        )
        rope_sin = Tensor(
            name="rope_sin",
            dtype=self.dtype,
            shape=[-1, -1, head_dim],
            dim_range=OrderedDict(
                [
                    ("batch_size", [batch_size_range]),
                    ("max_duration", [[100, max_seq_len // 2, max_seq_len]]),
                    ("head_dim", [head_dim]),
                ]
            ),
        )
        input_lengths = Tensor(
            name="input_lengths",
            dtype=trt.int32,
            shape=[-1],
            dim_range=OrderedDict([("batch_size", [batch_size_range])]),
        )
        return {
            "noise": noise,
            "cond": cond,
            "time": time,
            "rope_cos": rope_cos,
            "rope_sin": rope_sin,
            "input_lengths": input_lengths,
        }
