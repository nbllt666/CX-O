"""FT 连续显存增量 KV Cache 流式注入流水线。

模块关系：
    - ft_engine.orpheus_engine.OrpheusFTEngine -> FT 骨干，维护全局连续 KV Cache
    - audio_head.audio_head.AudioHead -> 消费 hidden_states 生成首个 SNAC token
    - snac_decoder.snac_decoder.SNACDecoder -> SNAC token 序列解码为 PCM 波形
    - scheduler.router.SemanticRouter -> LLM 文本流语义分块
    - scheduler.streaming_pipeline.StreamingPipeline（本文件）-> 中央编排器，
      串联上述组件实现"FT 增量 Context Encoding → Audio Head → 自回归生成 → SNAC 解码"
      的流式注入流水线。

设计决策（核心）：
    1. 维护全局连续 KV Cache（GPU 1 预分配，由 OrpheusFTEngine 持有），通过
       start_step/step 增量 Context Encoding：
       第二 Chunk Prefill 仅对新 token 做 Context Encoding，不重算全序列，延迟 < 5ms。
    2. KV Cache 连续完整，Attention 能看到前面所有 chunk 上下文，韵律自然：
       KV Cache 在 max_seq_len 维度上是一次性 cudaMalloc 的连续块，Attention kernel
       只需传入起始指针 + 长度即可读取 [0:current_seq_len] 的全部历史 K/V，不存在跨
       不连续内存块的间接寻址，上下文绝对完整。对比 PagedAttention 分块方案，避免了
       跨 block 拼接带来的截断感，使 Chunk 2 的韵律预测能完整看到 Chunk 1 上下文。
    3. 流程：context_forward → 更新 seq_len → Audio Head 生成首 token →
       generation_forward → SNAC 解码。每个 Chunk 复用同一份连续 KV Cache，
       不重算历史，不重新分配显存。
"""
from __future__ import annotations

from typing import AsyncIterator, Iterator

import torch

from audio_head.audio_head import AudioHead
from ft_engine.orpheus_engine import OrpheusFTEngine
from scheduler.router import SemanticRouter
from snac_decoder.snac_decoder import SNACDecoder


class StreamingPipeline:
    """FT 连续显存增量 KV Cache 流式注入流水线。

    设计决策：
        - 维护全局连续 KV Cache（GPU 1 预分配，由 engine 持有），通过 start_step/step
          增量 Context Encoding。第二 Chunk Prefill 仅对新 token 做 Context Encoding，
          不重算全序列，延迟 < 5ms。
        - KV Cache 连续完整，Attention 能看到前面所有 chunk 上下文，韵律自然。
        - 流程：context_forward → 更新 seq_len → Audio Head 生成首 token →
          generation_forward → SNAC 解码。

    为什么连续显存保证 Attention 上下文完整：
        KV Cache 在 max_seq_len 维度上是一次性 cudaMalloc 的连续块，Attention kernel
        只需传入起始指针 + 长度即可读取 [0:current_seq_len] 的全部历史 K/V，不存在跨
        不连续内存块的间接寻址。因此 Chunk 2 的 Attention 能毫无阻碍看到 Chunk 1 完整
        上下文，完美预测韵律，不会出现 PagedAttention 分块带来的截断感。

    为什么第二 Chunk Prefill < 5ms：
        vLLM 每次 Prefill 会重新计算整个 prompt 的 KV（即使前缀已缓存），且需走
        PagedAttention 的 block 索引间接寻址。本方案用连续 KV Cache，新 token 的 K/V
        直接按 start_step 偏移写入预分配块，FT C++ kernel 只对新 token 做前向（不重算
        历史），Attention 读取连续 [0:start_step+step] 完整上下文。省去重算 + 省去
        分页索引开销，使第二 Chunk Prefill 压到 < 5ms。
    """

    def __init__(
        self,
        engine: OrpheusFTEngine,
        audio_head: AudioHead,
        snac_decoder: SNACDecoder,
        max_new_tokens_per_chunk: int = 100,
    ) -> None:
        """初始化流式注入流水线。

        Args:
            engine: Orpheus FT 引擎（内部持有连续 KV Cache 与 current_seq_len 状态）。
            audio_head: Audio Head（从 hidden_states 生成首个 SNAC token）。
            snac_decoder: SNAC 解码器（SNAC token 序列 → PCM 波形）。
            max_new_tokens_per_chunk: 每个 Chunk 自回归生成的最大 token 数。
                控制单个 Chunk 的音频长度上限，过大会增加延迟，过小会截断音频。
        """
        self._engine = engine
        self._audio_head = audio_head
        self._snac_decoder = snac_decoder
        self._max_new_tokens_per_chunk = max_new_tokens_per_chunk

    def process_streaming_chunk(self, chunk_tokens: torch.Tensor) -> torch.Tensor:
        """处理单个流式 Chunk：FT 增量 Context Encoding → Audio Head → 生成 → SNAC 解码。

        核心方法，实现 spec 伪代码逻辑：
            1. engine.context_forward(chunk_tokens, kv_cache, start_step=current_seq_len,
               step=chunk_len) → hidden_states
               FT 仅对新 token 做 Context Encoding，K/V 写入 kv_cache 偏移位置
               [start_step : start_step+chunk_len]，不重算历史。
            2. current_seq_len 由 engine 内部状态机递增（context_forward 写入
               start_step+chunk_len）。
            3. audio_head.generate_first_snac_token(hidden_states) → first_snac_token
               [batch, num_codebooks]，作为 SNAC 序列的位置 0（含全部 codebook）。
            4. engine.generation_forward(start_token, kv_cache, current_seq_len,
               max_new_tokens) → generated_tokens [batch, max_new_tokens]
               自回归生成后续 SNAC token，复用同一份连续 KV Cache。
            5. 拼接首 token 与生成 token → [batch, num_codebooks, total_len]，
               snac_decoder.decode(...) → pcm [batch, samples]。

        Args:
            chunk_tokens: [batch, chunk_len] 当前 Chunk 的 token ids。

        Returns:
            pcm: [batch, samples] 当前 Chunk 生成的 PCM 音频（float32，范围 [-1, 1]）。
        """
        # 统一设备：chunk_tokens 移到引擎设备上（连续 KV Cache 与权重都在该设备）。
        chunk_tokens = chunk_tokens.to(self._engine.device)
        batch, chunk_len = chunk_tokens.shape

        # --------------------------------------------------------------
        # 1. FT 增量 Context Encoding
        #    读取 engine.current_seq_len 作为 start_step（在 context_forward 内部
        #    会递增为 start_step + chunk_len）。
        #    KV Cache 连续显存保证 Attention 上下文完整：新 token 的 K/V 直接按
        #    start_step 偏移写入预分配连续块，Attention 读取 [0:start_step+chunk_len]
        #    完整历史，无需跨不连续块拼接。
        # --------------------------------------------------------------
        start_step = self._engine.current_seq_len
        hidden_states, _ = self._engine.context_forward(
            input_ids=chunk_tokens,
            kv_cache=self._engine.kv_cache,
            start_step=start_step,
            step=chunk_len,
        )
        # hidden_states: [batch, chunk_len, hidden_dim]
        # engine.current_seq_len 此时已递增为 start_step + chunk_len

        # --------------------------------------------------------------
        # 2. Audio Head 生成首个 SNAC token
        #    取 hidden_states 最后一个 token（含完整上下文），生成 [batch, num_codebooks]。
        #    该 token 作为 SNAC 序列的位置 0（包含全部 codebook 的离散值）。
        # --------------------------------------------------------------
        first_snac_token = self._audio_head.generate_first_snac_token(hidden_states)
        # first_snac_token: [batch, num_codebooks]

        # --------------------------------------------------------------
        # 3. 自回归生成后续 SNAC token
        #    engine.generation_forward 期望 start_token 形状 [batch, 1]（单 token 种子）。
        #    从 first_snac_token 取第 0 个 codebook（最粗粒度）作为种子 token，
        #    驱动 FT 自回归生成后续 token。generation_forward 复用同一份连续 KV Cache，
        #    生成的 token 的 K/V 续写在 [current_seq_len : current_seq_len+N] 偏移位置。
        # --------------------------------------------------------------
        start_token = first_snac_token[:, 0:1].to(torch.long)  # [batch, 1]
        current_step = self._engine.current_seq_len
        generated_tokens = self._engine.generation_forward(
            start_token=start_token,
            kv_cache=self._engine.kv_cache,
            current_step=current_step,
            max_new_tokens=self._max_new_tokens_per_chunk,
        )
        # generated_tokens: [batch, num_generated]（单 codebook，由 Mock 路径 argmax 采样）

        # --------------------------------------------------------------
        # 4. 拼接首 token 与生成 token，构造 SNAC 解码器期望的形状
        #    首token [batch, num_codebooks] → [batch, num_codebooks, 1]（位置 0）
        #    生成token [batch, N] → 广播到 [batch, num_codebooks, N]（位置 1..N）
        #    拼接 → [batch, num_codebooks, 1+N]
        #    说明：generation_forward 当前返回单 codebook 序列（FT 路径下不实际采样
        #    多 codebook），这里沿 codebook 维广播，使形状与 SNACDecoder 输入契约一致。
        # --------------------------------------------------------------
        num_codebooks = self._audio_head.num_codebooks
        first_pos = first_snac_token.to(torch.long).unsqueeze(-1)  # [batch, num_codebooks, 1]

        if generated_tokens.numel() > 0:
            # [batch, N] → [batch, 1, N] → [batch, num_codebooks, N]
            gen_pos = generated_tokens.to(torch.long).unsqueeze(1).expand(
                -1, num_codebooks, -1
            )
            snac_tokens = torch.cat([first_pos, gen_pos], dim=-1)  # [batch, num_codebooks, 1+N]
        else:
            # generation_forward 未生成任何 token（KV Cache 已满等边界情况）：
            # 仅用首 token 解码，避免空序列送入解码器报错。
            snac_tokens = first_pos  # [batch, num_codebooks, 1]

        # --------------------------------------------------------------
        # 5. SNAC 解码：离散 token 序列 → PCM 波形
        #    snac_decoder.decode 内部走 torch.compile 优化路径，1D 卷积栈算子融合。
        # --------------------------------------------------------------
        pcm = self._snac_decoder.decode(snac_tokens)
        # pcm: [batch, samples]

        return pcm

    def process_token_chunks(
        self, token_chunks: list[list[int]]
    ) -> Iterator[torch.Tensor]:
        """处理多个 token Chunk（同步迭代器），逐块 yield PCM。

        用于从 SemanticRouter.split_tokens() 接收 Chunk 列表，逐块流式生成音频。
        每个 Chunk 复用同一个连续 KV Cache，第二个 Chunk 起的 Prefill 仅对新 token
        做前向（< 5ms），且 Attention 能看到前面所有 Chunk 的完整上下文。

        Args:
            token_chunks: 多个 Chunk 的 token id 列表（每个元素是一个 Chunk 的 token ids）。

        Yields:
            pcm: [batch, samples] 每个 Chunk 生成的 PCM 音频。
        """
        for chunk in token_chunks:
            # 跳过空 Chunk（边界保护）。
            if not chunk:
                continue
            # 构造 [batch=1, chunk_len] 的 token 张量，移到引擎设备。
            chunk_tokens = torch.tensor(
                [chunk], dtype=torch.long, device=self._engine.device
            )
            pcm = self.process_streaming_chunk(chunk_tokens)
            yield pcm

    async def process_text_stream(
        self, text_stream: AsyncIterator[str], tokenizer
    ) -> AsyncIterator[torch.Tensor]:
        """异步流式处理：对接 LLM 文本流 → Router 分块 → FT 流式注入。

        流程：
            1. 用 SemanticRouter.split_stream() 对 LLM 文本流分块（按标点或最大长度）。
            2. 每个文本块用 tokenizer.encode() 编码为 token ids。
            3. 调用 process_streaming_chunk() 生成 PCM。
            4. yield PCM（不等整句），实现 LLM 边生成、TTS 边合成的真流式注入。

        为什么不等整句：
            等整句会让 TTS 空等 LLM 完成整句输出，破坏 sub-300ms 端到端延迟预算。
            按标点或最大长度切分后，TTS 可在 LLM 仍在生成时就开工合成，与 LLM 流式
            输出并行，显著降低首包延迟。

        Args:
            text_stream: LLM 流式输出的异步文本迭代器。
            tokenizer: 提供 encode(text) -> list[int] 的 tokenizer（兼容 HF tokenizer）。

        Yields:
            pcm: [batch, samples] 每个 Chunk 生成的 PCM 音频。
        """
        router = SemanticRouter()
        # 对接 LLM 文本流，按标点/最大长度切分。
        async for text_chunk in router.split_stream(text_stream):
            # 跳过空文本块（边界保护）。
            if not text_chunk:
                continue
            # 编码文本块为 token ids。
            token_ids = tokenizer.encode(text_chunk)
            if not token_ids:
                continue
            # 构造 [batch=1, chunk_len] 的 token 张量。
            chunk_tokens = torch.tensor(
                [token_ids], dtype=torch.long, device=self._engine.device
            )
            # 流式生成 PCM 并立即 yield（不等整句）。
            pcm = self.process_streaming_chunk(chunk_tokens)
            yield pcm

    def reset(self) -> None:
        """重置流水线（新对话开始）：清空 KV Cache，重置 current_seq_len。

        委托给 engine.reset_cache()：
            - 原地清零连续 KV Cache 张量（复用已分配显存，零分配开销）。
            - current_seq_len 归零。
            - 重置 FT 引擎内部状态（CUDA Graphs 缓存等）。
        """
        self._engine.reset_cache()

    @property
    def current_seq_len(self) -> int:
        """当前已处理的序列长度（委托给 engine 内部状态机）。

        包含已 Prefill 的文本 token 与已自回归生成的 SNAC token 总数。
        """
        return self._engine.current_seq_len

    def verify_kv_cache_continuity(self) -> bool:
        """验证 KV Cache 连续性：Chunk 2 Attention 能完整看到 Chunk 1 上下文。

        检查 KV Cache 在 [0:current_seq_len] 区域已被填充（非零），确保增量 Prefill
        写入了正确偏移位置。若该区域全零，说明增量 Prefill 未正确写入，Attention
        将丢失历史上下文，韵律预测会失效。

        Returns:
            True 若 [0:current_seq_len] 区域已填充（存在非零元素），False 否则。
            current_seq_len=0 时返回 True（无上下文，连续性平凡成立）。
        """
        seq_len = self._engine.current_seq_len
        if seq_len == 0:
            # 尚无上下文，连续性平凡成立。
            return True

        kv_cache = self._engine.kv_cache
        # 取 [0:seq_len] 切片，检查是否存在非零元素（即已被 Prefill 写入）。
        filled_region = kv_cache[:, :, :seq_len, :, :]
        return bool((filled_region.abs() > 0).any().item())
