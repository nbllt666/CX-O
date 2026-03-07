import tensorrt as trt
import os
import math
import time
from typing import List, Optional
from functools import wraps

import tensorrt_llm
from tensorrt_llm._utils import str_dtype_to_torch, trt_dtype_to_torch
from tensorrt_llm.logger import logger

import torch
import torch.nn as nn
import torch.nn.functional as F
import numpy as np


def remove_tensor_padding(input_tensor, input_tensor_lengths=None):
    if input_tensor_lengths is None:
        return input_tensor.reshape(-1, *input_tensor.shape[2:])
    output_tensor = []
    for i in range(input_tensor.shape[0]):
        output_tensor.append(input_tensor[i, : input_tensor_lengths[i]])
    return torch.cat(output_tensor, dim=0)


class TextEmbedding(nn.Module):
    def __init__(self, text_num_embeds, text_dim, conv_layers=4, precompute_max_pos=4096):
        super().__init__()
        self.text_embed = nn.Embedding(text_num_embeds, text_dim)
        self.text_dim = text_dim
        self.precompute_max_pos = precompute_max_pos

        self.norm = nn.LayerNorm(text_dim)

        self.conv_layers = nn.ModuleList([
            nn.Conv1d(text_dim, text_dim, kernel_size=3, padding=1)
            for _ in range(conv_layers)
        ])

    def forward(self, x, mask=None):
        x = self.text_embed(x)
        x = self.norm(x)
        x = x.transpose(1, 2)
        for conv in self.conv_layers:
            x = F.silu(conv(x))
        x = x.transpose(1, 2)
        return x


def precompute_freqs_cis(dim: int, end: int, theta: float = 10000.0, theta_rescale_factor=1.0):
    theta *= theta_rescale_factor ** (dim / (dim - 2))
    freqs = 1.0 / (theta ** (torch.arange(0, dim, 2)[: (dim // 2)].float() / dim))
    t = torch.arange(end, device=freqs.device)
    freqs = torch.outer(t, freqs).float()
    freqs_cos = torch.cos(freqs)
    freqs_sin = torch.sin(freqs)
    return torch.cat([freqs_cos, freqs_sin], dim=-1)


def load_checkpoint(ckpt_path, use_ema=True):
    checkpoint = torch.load(ckpt_path, weights_only=True)
    if use_ema:
        checkpoint["model_state_dict"] = {
            k.replace("ema_model.", ""): v
            for k, v in checkpoint["ema_model_state_dict"].items()
            if k not in ["initted", "step"]
        }
    dict_state = checkpoint["model_state_dict"]
    text_embed_dict = {}
    for key in dict_state.keys():
        if "text_embed" in key:
            text_embed_dict[key.replace("transformer.text_embed.", "")] = dict_state[key]
    return text_embed_dict


class F5TTS(object):
    def __init__(
        self,
        config,
        debug_mode=True,
        stream: Optional[torch.cuda.Stream] = None,
        tllm_model_dir: Optional[str] = None,
        model_path: Optional[str] = None,
        vocab_size: Optional[int] = None,
    ):
        self.dtype = config["pretrained_config"]["dtype"]

        rank = tensorrt_llm.mpi_rank()
        world_size = config["pretrained_config"]["mapping"]["world_size"]
        cp_size = config["pretrained_config"]["mapping"]["cp_size"]
        tp_size = config["pretrained_config"]["mapping"]["tp_size"]
        pp_size = config["pretrained_config"]["mapping"]["pp_size"]
        assert pp_size == 1
        self.mapping = tensorrt_llm.Mapping(
            world_size=world_size, rank=rank, cp_size=cp_size, tp_size=tp_size, pp_size=1, gpus_per_node=1
        )

        local_rank = rank % self.mapping.gpus_per_node
        self.device = torch.device(f"cuda:{local_rank}")

        torch.cuda.set_device(self.device)

        self.stream = stream
        if self.stream is None:
            self.stream = torch.cuda.current_stream(self.device)
        torch.cuda.set_stream(self.stream)

        engine_file = os.path.join(tllm_model_dir, f"rank{rank}.engine")
        logger.info(f"Loading engine from {engine_file}")
        with open(engine_file, "rb") as f:
            self.engine_buffer = f.read()

        assert self.engine_buffer is not None

        # Use TensorRT native API
        self.trt_logger = trt.Logger(trt.Logger.WARNING)
        self.runtime = trt.Runtime(self.trt_logger)
        self.engine = self.runtime.deserialize_cuda_engine(self.engine_buffer)
        self.context = self.engine.create_execution_context()

        self.debug_mode = debug_mode
        self.buffer_allocated = False

        self.max_mel_len = 2048
        self.text_embedding = TextEmbedding(
            text_num_embeds=vocab_size, text_dim=512, conv_layers=4, precompute_max_pos=self.max_mel_len
        ).to(self.device)
        self.text_embedding.load_state_dict(load_checkpoint(model_path), strict=True)

        self.target_audio_sample_rate = 24000
        self.target_rms = 0.15
        self.n_fft = 1024
        self.win_length = 1024
        self.hop_length = 256
        self.n_mel_channels = 100
        self.head_dim = 64
        self.base_rescale_factor = 1.0
        self.interpolation_factor = 1.0
        base = 10000.0 * self.base_rescale_factor ** (self.head_dim / (self.head_dim - 2))
        inv_freq = 1.0 / (base ** (torch.arange(0, self.head_dim, 2).float() / self.head_dim))
        freqs = torch.outer(torch.arange(self.max_mel_len, dtype=torch.float32), inv_freq) / self.interpolation_factor
        self.freqs = freqs.repeat_interleave(2, dim=-1).unsqueeze(0)
        self.rope_cos = self.freqs.cos().half()
        self.rope_sin = self.freqs.sin().half()
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

    def forward(
        self,
        noise: torch.Tensor,
        cond: torch.Tensor,
        time_expand: torch.Tensor,
        rope_cos: torch.Tensor,
        rope_sin: torch.Tensor,
        input_lengths: torch.Tensor,
        delta_t: torch.Tensor,
        use_perf: bool = False,
    ):
        cfg_strength = 2.0
        batch_size = noise.shape[0]
        half_batch = batch_size // 2
        noise_half = noise[:half_batch]

        input_type = str_dtype_to_torch(self.dtype)

        cond = cond.to(input_type)
        rope_cos = rope_cos.to(input_type)
        rope_sin = rope_sin.to(input_type)
        input_lengths = input_lengths.to(str_dtype_to_torch("int32"))

        for i in range(self.nfe_steps):
            current_noise = torch.cat([noise_half, noise_half], dim=0).to(input_type)
            current_time = time_expand[:, i].to(input_type)

            # Set input shapes
            self.context.set_input_shape("noise", tuple(current_noise.shape))
            self.context.set_input_shape("cond", tuple(cond.shape))
            self.context.set_input_shape("time", tuple(current_time.shape))
            self.context.set_input_shape("rope_cos", tuple(rope_cos.shape))
            self.context.set_input_shape("rope_sin", tuple(rope_sin.shape))
            self.context.set_input_shape("input_lengths", tuple(input_lengths.shape))

            # Get output shape
            output_shape = self.context.get_tensor_shape("denoised")
            output = torch.empty(output_shape, dtype=input_type, device=self.device)

            # Set tensor addresses
            self.context.set_tensor_address("noise", int(current_noise.data_ptr()))
            self.context.set_tensor_address("cond", int(cond.data_ptr()))
            self.context.set_tensor_address("time", int(current_time.data_ptr()))
            self.context.set_tensor_address("rope_cos", int(rope_cos.data_ptr()))
            self.context.set_tensor_address("rope_sin", int(rope_sin.data_ptr()))
            self.context.set_tensor_address("input_lengths", int(input_lengths.data_ptr()))
            self.context.set_tensor_address("denoised", int(output.data_ptr()))

            # Execute
            self.context.execute_async_v3(self.stream.cuda_stream)
            torch.cuda.synchronize()

            t_scale = delta_t[i].unsqueeze(0).to(input_type)
            pred_cond = output[:half_batch]
            pred_uncond = output[half_batch:]
            guidance = pred_cond + (pred_cond - pred_uncond) * cfg_strength
            noise_half = noise_half + guidance * t_scale

        return noise_half

    def sample(
        self,
        text_pad_sequence: torch.Tensor,
        ref_mel_batch: torch.Tensor,
        ref_mel_len_batch: torch.Tensor,
        estimated_reference_target_mel_len: List[int],
        remove_input_padding: bool = False,
        use_perf: bool = False,
    ):
        batch = text_pad_sequence.shape[0]
        max_seq_len = ref_mel_batch.shape[1]

        text_pad_sequence_drop = torch.cat(
            (text_pad_sequence, torch.zeros((1, text_pad_sequence.shape[1]), dtype=torch.int32).to(self.device)), dim=0
        )

        text_embedding_drop_list = []
        for i in range(batch + 1):
            text_embedding_drop_list.append(self.text_embedding(text_pad_sequence_drop[i].unsqueeze(0).to(self.device)))
        text_embedding_drop_condition = torch.cat(text_embedding_drop_list, dim=0)

        text_embedding = text_embedding_drop_condition[:-1]
        text_embedding_drop = text_embedding_drop_condition[-1].unsqueeze(0).repeat(batch, 1, 1)

        noise = torch.randn_like(ref_mel_batch).to(self.device)
        rope_cos = self.rope_cos[:, :max_seq_len, :].float().repeat(batch, 1, 1)
        rope_sin = self.rope_sin[:, :max_seq_len, :].float().repeat(batch, 1, 1)

        cat_mel_text = torch.cat((ref_mel_batch, text_embedding), dim=-1)
        cat_mel_text_drop = torch.cat(
            (
                torch.zeros((batch, max_seq_len, self.n_mel_channels), dtype=torch.float32).to(self.device),
                text_embedding_drop,
            ),
            dim=-1,
        )

        time_expand = self.time_expand.repeat(2 * batch, 1, 1).contiguous()
        input_lengths = torch.tensor(estimated_reference_target_mel_len, dtype=torch.int32)

        inputs = {
            "noise": torch.cat((noise, noise), dim=0).contiguous(),
            "cond": torch.cat((cat_mel_text, cat_mel_text_drop), dim=0).contiguous(),
            "time_expand": time_expand,
            "rope_cos": torch.cat((rope_cos, rope_cos), dim=0).contiguous(),
            "rope_sin": torch.cat((rope_sin, rope_sin), dim=0).contiguous(),
            "input_lengths": torch.cat((input_lengths, input_lengths), dim=0).contiguous(),
            "delta_t": self.delta_t,
        }

        for key in inputs:
            inputs[key] = inputs[key].to(self.device)

        start_time = time.time()
        denoised = self.forward(**inputs, use_perf=use_perf)
        cost_time = time.time() - start_time

        return denoised, cost_time
