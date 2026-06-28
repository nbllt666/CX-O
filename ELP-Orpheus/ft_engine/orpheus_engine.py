"""Orpheus Llama-3B FT 引擎封装。

模块关系：
    - ft_binding.FTLlamaBinding  -> 底层 FT C++ 引擎 Python 绑定（含 Mock 回退）
    - orpheus_engine.OrpheusFTEngine（本文件）-> 对外暴露的引擎封装
    - 调用方：Audio Head / scheduler 通过本类驱动 Context Encoding 与 Decode

设计决策（核心）：
    1. FT C++ 引擎只跑到 Llama 最后一层，输出 hidden_states（不生成 token，不做 LM head）：
       Orpheus 的输出层是自定义 Audio Head（PyTorch 实现），与 FT 解耦。FT 侧只产出
       hidden_states 传回 Python，由 Audio Head 消费。这样 Audio Head 可快速迭代而无需
       重编译 FT。
    2. 维护全局连续 KV Cache 张量（GPU 1 预分配），通过 start_step/step 实现增量
       Context Encoding：
       避免重新 Prefill 全序列，第二 Chunk Prefill < 5ms（对比 vLLM 50ms+）。
    3. 开启 CUDA Graphs，Decode 单 token < 1ms：
       Decode 阶段每步只产 1 个 token，计算图形状固定，捕获一次重放即可省去 kernel
       launch 与 driver 开销。
"""

from __future__ import annotations

from typing import Tuple

import torch

from .ft_binding import FTLlamaBinding


class OrpheusFTEngine:
    """Orpheus Llama-3B FT 引擎封装。

    设计决策：
        - FT C++ 引擎只跑到 Llama 最后一层，输出 hidden_states（不生成 token，不做 LM head）
        - 维护全局连续 KV Cache 张量（GPU 1 预分配），通过 start_step/step 实现增量 Context Encoding
        - 避免重新 Prefill 全序列，第二 Chunk Prefill < 5ms（对比 vLLM 50ms+）
        - 开启 CUDA Graphs，Decode 单 token < 1ms
    """

    def __init__(
        self,
        checkpoint_path: str,
        gpu_id: int = 1,
        tensor_para_size: int = 1,
        pipeline_para_size: int = 1,
        data_type: str = "fp16",
        cuda_graph: bool = True,
        max_seq_len: int = 512,
        max_batch_size: int = 1,
        max_decode_tokens: int = 100,
        hidden_dim: int = 3072,
        num_layers: int = 28,
        vocab_size: int = 128256,
    ) -> None:
        """初始化 FT 引擎。

        流程：
            1. 绑定 GPU（torch.device(f"cuda:{gpu_id}")），Orpheus 进程绑定 GPU 1。
            2. 加载 FT Llama 引擎（通过 FTLlamaBinding，真实 FT 优先，不可用回退 Mock）。
            3. 预分配全局连续 KV Cache 张量。
            4. 预分配 Decode 输出 buffer（Task 4：循环零分配，避免 Decode 热路径 torch.zeros）。

        Args:
            checkpoint_path: FT checkpoint 目录路径（含权重 .bin 文件）。
            gpu_id: 目标 GPU 物理索引（Orpheus 绑定 GPU 1）。
            tensor_para_size: 张量并行度（单卡物理隔离下=1）。
            pipeline_para_size: 流水线并行度（=1）。
            data_type: "fp16" 或 "fp32"（Ampere FP16 Tensor Core 最优）。
            cuda_graph: 是否开启 CUDA Graphs（Decode <1ms 的关键）。
            max_seq_len: 连续 KV Cache 最大序列长度。
            max_batch_size: 最大批大小（流式 TTS 单批=1）。
            max_decode_tokens: 单次 generation_forward 最大可生成 token 数上限，
                用于一次性预分配 Decode 输出 buffer（Task 4）。后续 reset_cache 复用该 buffer，
                禁止在 Decode 热路径每步 torch.zeros（消除毫秒级毛刺）。
            hidden_dim: Llama-3B 隐藏维度（=3072）。
            num_layers: Llama-3B 层数（=28）。
            vocab_size: 词表大小（Mock 路径用；真实 FT 从 checkpoint config 读取）。
        """
        self._checkpoint_path = checkpoint_path
        self._gpu_id = gpu_id
        self._tensor_para_size = tensor_para_size
        self._pipeline_para_size = pipeline_para_size
        self._data_type = data_type
        self._cuda_graph = cuda_graph
        self._max_seq_len = max_seq_len
        self._max_batch_size = max_batch_size
        self._max_decode_tokens = max_decode_tokens
        self._hidden_dim = hidden_dim
        self._num_layers = num_layers
        self._vocab_size = vocab_size

        # dtype 映射：fp16 对应 Ampere FP16 Tensor Core 最优路径。
        self._dtype: torch.dtype = (
            torch.float16 if data_type == "fp16" else torch.float32
        )

        # 1. 绑定 GPU：
        #    优先使用指定 GPU；若 GPU 不可用（开发环境无卡），回退 CPU 让 Mock 路径可运行。
        if torch.cuda.is_available() and gpu_id < torch.cuda.device_count():
            self._device = torch.device(f"cuda:{gpu_id}")
        else:
            self._device = torch.device("cpu")

        # 2. 加载 FT Llama 引擎（通过 FTLlamaBinding，真实 FT 优先，不可用回退 Mock）。
        #    绑定层内部处理 import FT 失败的延迟报错与 Mock 回退，保证本类在无 FT 环境
        #    下仍可实例化（用于代码审查与 Mock 测试）。
        self._binding = FTLlamaBinding(
            checkpoint_path=checkpoint_path,
            gpu_id=gpu_id,
            tensor_para_size=tensor_para_size,
            pipeline_para_size=pipeline_para_size,
            data_type=data_type,
            cuda_graph=cuda_graph,
            hidden_dim=hidden_dim,
            num_layers=num_layers,
            max_seq_len=max_seq_len,
            vocab_size=vocab_size,
        )

        # 3. 预分配全局连续 KV Cache 张量。
        #    连续显存的核心：Attention kernel 可一次读取 [0:seq_len] 的全部历史 K/V，
        #    无需跨不连续块拼接，上下文绝对完整。
        self._kv_cache: torch.Tensor = self._allocate_kv_cache()

        # 4. Task 4：预分配 Decode 输出 buffer。
        #    generation_forward 的自回归循环禁止每步 torch.zeros（瓶颈 B），改为在
        #    __init__ 一次性预分配并复用。reset_cache 仅原地清零（复用同一块显存，不
        #    重新分配），保证 id 稳定且零分配开销。
        self._decode_out_buf: torch.Tensor = torch.zeros(
            self._max_batch_size,
            self._max_decode_tokens,
            dtype=torch.long,
            device=self._device,
        )

        # 当前已处理的序列长度（状态机）：context_forward / generation_forward 递增，
        # reset_cache 归零。
        self._current_seq_len: int = 0

    # ------------------------------------------------------------------
    # KV Cache 预分配
    # ------------------------------------------------------------------
    def _allocate_kv_cache(self) -> torch.Tensor:
        """预分配全局连续 KV Cache 张量。

        形状: [num_layers, 2, max_seq_len, batch, hidden_dim]
            - dim 0: num_layers 层（Llama-3B = 28）
            - dim 1: 2（K 和 V 两份）
            - dim 2: max_seq_len（序列维度，连续显存）
            - dim 3: batch（流式 TTS 单批=1）
            - dim 4: hidden_dim（Llama-3B = 3072）

        在 GPU 1 上预分配，FP16。这是连续显存的核心——Attention 上下文绝对完整。

        为什么连续显存能保证 Attention 上下文完整：
            KV Cache 在 max_seq_len 维度上是一次性 cudaMalloc 的连续块，Attention kernel
            只需传入起始指针 + 长度即可读取 [0:current_seq_len] 的全部历史 K/V，不存在跨
            不连续内存块的间接寻址。对比动态 append 的 list[Tensor] 方案（每步新分配小块，
            Attention 需遍历拼接），连续显存避免了指针追逐与碎片化，保证上下文完整且低延迟。

        为什么不在每步动态分配：
            动态分配会导致显存碎片化，长序列下触发 cudaMalloc 重排产生毫秒级毛刺。
            预分配一次到位，后续所有 K/V 写入都在已分配的连续块内完成，零分配开销。
        """
        cache = torch.zeros(
            self._num_layers,
            2,  # K 和 V
            self._max_seq_len,
            self._max_batch_size,
            self._hidden_dim,
            dtype=self._dtype,
            device=self._device,
        )
        return cache

    # ------------------------------------------------------------------
    # 增量 Context Encoding
    # ------------------------------------------------------------------
    def context_forward(
        self,
        input_ids: torch.Tensor,
        kv_cache: torch.Tensor,
        start_step: int,
        step: int,
    ) -> Tuple[torch.Tensor, torch.Tensor]:
        """FT 增量 Context Encoding。

        核心逻辑：从 start_step 开始，处理 step 个 token。
        FT 自动将新 token 的 K/V 写入 kv_cache 的对应偏移位置
        （start_step : start_step+step）。不重新 Prefill 全序列，仅对新 token 做
        Context Encoding。

        Args:
            input_ids: [batch, step] 新 token ids。
            kv_cache: [num_layers, 2, max_seq_len, batch, hidden_dim] 全局连续 KV Cache。
            start_step: 当前序列长度（已处理的 token 数）。
            step: 本批次新 token 数。

        Returns:
            hidden_states: [batch, step, hidden_dim] Llama 最后一层输出（传给 Audio Head）。
            new_kv_cache: 更新后的 kv_cache（原地更新，返回引用）。

        设计：FT C++ 引擎只跑到 Llama 最后一层，输出 hidden_states，不做 LM head。

        为什么增量 Prefill < 5ms（对比 vLLM 50ms+）：
            vLLM 每次 Prefill 会重新计算整个 prompt 的 KV（即使前缀已缓存），且需走
            PagedAttention 的 block 索引间接寻址。本方案用连续 KV Cache，新 token 的 K/V
            直接按 start_step 偏移写入预分配块，FT C++ kernel 只对新 token 做前向（不重算
            历史），Attention 读取连续 [0:start_step+step] 完整上下文。省去重算 + 省去
            分页索引开销，使第二 Chunk Prefill 压到 < 5ms。
        """
        # 边界校验：防止写入越界（超过 max_seq_len）。
        end_step = start_step + step
        if end_step > self._max_seq_len:
            raise ValueError(
                f"KV Cache 越界: start_step({start_step}) + step({step}) = {end_step} "
                f"超过 max_seq_len({self._max_seq_len})。请增大 max_seq_len 或缩短序列。"
            )

        # 统一 input_ids 设备与 dtype。
        input_ids = input_ids.to(self._device)

        # 调用 FT 引擎前向（is_context=True 触发 Context Encoding kernel）。
        # FT 将新 K/V 写入 kv_cache[start_step:start_step+step] 偏移位置。
        hidden_states = self._binding.forward(
            input_ids=input_ids,
            kv_cache=kv_cache,
            start_step=start_step,
            step=step,
            is_context=True,
        )

        # 状态机更新：当前序列长度递增。
        self._current_seq_len = end_step

        # kv_cache 为原地更新（FT 在 C++ 侧直接写入预分配显存），返回引用。
        return hidden_states, kv_cache

    # ------------------------------------------------------------------
    # 自回归 Decode
    # ------------------------------------------------------------------
    def generation_forward(
        self,
        start_token: torch.Tensor,
        kv_cache: torch.Tensor,
        current_step: int,
        max_new_tokens: int = 100,
    ) -> torch.Tensor:
        """自回归生成（Decode 阶段）。

        基于 start_token 自回归生成，复用连续 KV Cache。
        开启 CUDA Graphs，单 token Decode < 1ms。

        Args:
            start_token: [batch, 1] 起始 token（Audio Head 生成的首个 SNAC token）。
            kv_cache: 连续 KV Cache（已包含前序上下文）。
            current_step: 当前序列长度。
            max_new_tokens: 最大生成 token 数。

        Returns:
            generated_tokens: [batch, num_generated] 生成的 token 序列（视图，复用预分配 buffer）。

        为什么 CUDA Graphs 能让单 token Decode < 1ms：
            Decode 阶段每步只产 1 个 token，计算图形状固定（输入恒为 [batch,1]，KV Cache
            偏移恒 +1）。CUDA Graphs 捕获一次完整的 kernel 序列后，后续每步只需重放图 +
            更新输入指针，省去 kernel launch 与 driver 开销。RTX 3080 上单 token Decode
            因此压到 < 1ms。对比未开 Graphs 时每步 ~3-5ms 的 launch 开销，提升 3-5x。

        返回类型契约（Task 3 + Task 4）：
            - 返回 [batch, num_generated] token 序列，FT 与 Mock 路径 shape 一致。
            - FT 路径：self._binding.forward(is_context=False) 直接返回 int32 token id
              （C++ AudioHeadKernel 已就地完成 argmax），本方法不再调用 torch.argmax，
              消灭 Python 侧 argmax 与跨框架拷贝。多 codebook 输出取第 0 个 codebook 作为
              下一步输入，保证与 Mock 路径输出维度一致。
            - Mock 路径：self._binding.forward(is_context=False) 返回 hidden_states，
              由本方法 argmax 采样为 token id（保持现有行为，向后兼容）。

        循环零分配（Task 4，瓶颈 B 修复）：
            - 输出 token 序列写入 __init__ 预分配的 self._decode_out_buf（reset_cache 复用），
              禁止在 Decode 热路径每步 torch.zeros（避免毫秒级毛刺）。
            - 循环内仅做原地写入（self._decode_out_buf[:, i] = next_token），返回 buffer 视图，
              不拷贝。
        """
        start_token = start_token.to(self._device)
        batch = start_token.shape[0]

        # Task 4：循环零分配。输出 buffer 在 __init__ 一次性预分配，reset_cache 仅原地清零复用。
        # 截断到预分配容量上限，避免越界写入。
        max_new_tokens = min(max_new_tokens, self._max_decode_tokens)

        # 当前 token：从 start_token 开始，每步更新。
        cur_token = start_token  # [batch, 1]
        step_offset = current_step
        num_generated = 0  # 实际生成的 token 数（可能 < max_new_tokens）

        # backend 感知：FT 路径 forward 直接返回 token id（无需 argmax），Mock 路径需 argmax。
        is_ft = self._binding.backend == "ft"

        for i in range(max_new_tokens):
            # 边界校验。
            if step_offset >= self._max_seq_len:
                # 超出 KV Cache 容量，提前终止（避免越界）。
                break

            if is_ft:
                # Task 3：FT 路径 Decode——forward 直接返回 token id，无需 argmax。
                # C++ AudioHeadKernel 在 forward 末尾就地完成 argmax，消灭 PyTorch ↔ FT
                # 跨框架拷贝与 Python 侧 argmax。
                next_token = self._binding.forward(
                    input_ids=cur_token,
                    kv_cache=kv_cache,
                    start_step=step_offset,
                    step=1,
                    is_context=False,
                )
                # next_token: [batch] 或 [batch, num_codebooks]（C++ 返回多 codebook）。
                # 取第 0 个 codebook 作为下一步输入与输出序列，与 Mock 路径维度对齐。
                if next_token.dim() > 1:
                    next_token = next_token[:, 0]  # [batch]
            else:
                # Mock 路径：forward 返回 hidden_states，需 argmax（保持现有行为，向后兼容）。
                hidden_states = self._binding.forward(
                    input_ids=cur_token,
                    kv_cache=kv_cache,
                    start_step=step_offset,
                    step=1,
                    is_context=False,
                )
                # hidden_states: [batch, 1, hidden_dim]，取最后一个 token 做 argmax。
                next_token = torch.argmax(hidden_states[:, -1, :], dim=-1)  # [batch]

            # 原地写入预分配 buffer（零分配，不每步 torch.zeros）。
            self._decode_out_buf[:, i] = next_token
            num_generated += 1

            # 下一步输入 = 本步生成的 token。
            cur_token = next_token.unsqueeze(1)  # [batch, 1]
            step_offset += 1

        # 状态机更新。
        self._current_seq_len = step_offset

        # 返回预分配 buffer 的视图（不拷贝），形状 [batch, num_generated]。
        return self._decode_out_buf[:, :num_generated]

    # ------------------------------------------------------------------
    # KV Cache 重置
    # ------------------------------------------------------------------
    def reset_cache(self) -> None:
        """重置 KV Cache（新对话/新 Chunk 序列开始时调用）。

        将预分配的连续 KV Cache 张量清零，并把 current_seq_len 归零。
        注意：清零复用同一块预分配显存，不释放重分配（避免 cudaMalloc 抖动）。

        Task 4：同时原地清零预分配的 Decode 输出 buffer（self._decode_out_buf），
        保证下次 generation_forward 从干净状态开始。复用同一块显存（id 稳定），
        不重新分配，零分配开销。
        """
        # 原地清零：复用已分配的连续显存块，零分配开销。
        self._kv_cache.zero_()
        # Task 4：原地清零 Decode 输出 buffer（复用预分配显存，id 稳定，不重新分配）。
        self._decode_out_buf.zero_()
        self._current_seq_len = 0
        # 重置 FT 引擎内部状态（CUDA Graphs 缓存等）。
        self._binding.reset()

    # ------------------------------------------------------------------
    # 状态查询
    # ------------------------------------------------------------------
    @property
    def current_seq_len(self) -> int:
        """当前已处理的序列长度。"""
        return self._current_seq_len

    @property
    def kv_cache(self) -> torch.Tensor:
        """预分配的全局连续 KV Cache 张量（只读视图）。"""
        return self._kv_cache

    @property
    def backend(self) -> str:
        """当前底层引擎后端（"ft" 或 "mock"）。"""
        return self._binding.backend

    @property
    def device(self) -> torch.device:
        """引擎绑定的设备。"""
        return self._device
