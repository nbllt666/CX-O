"""CUDA Graphs 配置与算子分离优化。

模块关系:
    - orpheus_engine.OrpheusFTEngine -> 通过本模块生成 FT 启动参数并校验算子配置
    - benchmark_decode.py -> 调用 CudaGraphConfig 控制 ON/OFF 对比基准
    - tests/test_cuda_graph.py -> 验证 CudaGraphConfig / OperatorOptimizer 接口

设计决策(核心):
    1. CUDA Graphs 仅用于 Decode 阶段:Decode 每步输入形状恒为 [batch, 1],KV Cache
       偏移恒 +1,计算图形状固定,捕获一次重放即可省去 kernel launch 与 driver 开销。
       Prefill 阶段输入长度可变(chunk_len 不定),不进 Graphs。
    2. 算子分离(Operator Separation):
       - Prefill 路径用 cutlass GEMM(大矩阵乘法最优,吞吐导向)
       - Decode 路径用 FlashAttention + Fused LayerNorm(小批量访存密集,延迟导向)
       FT 在 C++ 侧根据 is_context 标志自动切换两条路径,本模块负责生成启动参数
       并在引擎构造后校验算子是否按预期启用。
    3. 连续显存 + CUDA Graphs 协同:连续 KV Cache 保证 Attention kernel 一次读取
       [0:seq_len] 完整上下文,无需跨不连续块拼接;CUDA Graphs 重放时输入指针仅
       更新 KV Cache 偏移与当前 token,图结构不变,二者共同支撑 Decode < 1ms。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from .orpheus_engine import OrpheusFTEngine


class CudaGraphConfig:
    """CUDA Graphs 与 FT 算子分离启动参数配置。

    职责:
        1. 生成 FT C++ 引擎启动参数列表(--cuda-graph / --enable-flash-attention 等),
           供 OrpheusFTEngine 构造时透传给 FTLlamaBinding。
        2. 提供 validate(engine) 方法,在引擎构造后校验 CUDA Graphs 是否真正启用
           (Mock 路径下返回 False,真实 FT 下检查引擎内部 graph_captured 标志)。

    为什么单独抽出一个配置类:
        - OrpheusFTEngine 关注 KV Cache 状态机与前向接口,不应混入启动参数拼装逻辑。
        - benchmark_decode.py 需要对比 ON/OFF 两种配置,通过本类可清晰生成两套参数。
        - 后续若需调整算子策略(如换 FusedAttention),只改本类不改引擎。
    """

    def __init__(
        self,
        enabled: bool = True,
        capture_iterations: int = 1,
        enable_flash_attention: bool = True,
        enable_fused_layernorm: bool = True,
        prefill_gemm_backend: str = "cutlass",
        max_batch_size: int = 1,
        max_seq_len: int = 512,
    ) -> None:
        """初始化 CUDA Graphs 与算子分离配置。

        Args:
            enabled: 是否开启 CUDA Graphs(Decode 单 token <1ms 的关键)。
            capture_iterations: CUDA Graphs 捕获迭代次数(FT C++ 侧参数,1=首次
                forward 即捕获,>1=预热若干次再捕获以稳定形状)。
            enable_flash_attention: Decode 阶段是否启用 FlashAttention
                (减少 HBM 读写,小批量 Decode 延迟最优)。
            enable_fused_layernorm: Decode 阶段是否启用 Fused LayerNorm
                (融合 RMSNorm + residual,减少 kernel launch)。
            prefill_gemm_backend: Prefill 阶段 GEMM 后端,默认 "cutlass"
                (大矩阵乘法吞吐最优)。
            max_batch_size: 流式 TTS 单批=1。
            max_seq_len: KV Cache 最大序列长度,用于 CUDA Graphs 捕获时分配静态输入。
        """
        self._enabled = enabled
        self._capture_iterations = capture_iterations
        self._enable_flash_attention = enable_flash_attention
        self._enable_fused_layernorm = enable_fused_layernorm
        self._prefill_gemm_backend = prefill_gemm_backend
        self._max_batch_size = max_batch_size
        self._max_seq_len = max_seq_len

    # ------------------------------------------------------------------
    # 启动参数生成
    # ------------------------------------------------------------------
    def to_ft_args(self) -> List[str]:
        """生成 FT C++ 引擎启动参数列表。

        返回的参数列表与 NVIDIA FasterTransformer examples/cpp/llama 的命令行
        参数风格一致,供 OrpheusFTEngine 透传给 FTLlamaBinding(真实 FT 路径下
        C++ 侧解析这些参数初始化引擎;Mock 路径下忽略)。

        Returns:
            参数列表,如 ['--cuda-graph', '--enable-flash-attention', ...]。

        为什么用命令行参数风格而非 dict:
            FT C++ 侧的 argparse 解析器天然接受这种格式,避免在 Python/C++ 边界
            再做一次 dict->struct 转换,减少 pybind11 绑定代码量。
        """
        args: List[str] = []

        # CUDA Graphs:仅影响 Decode 阶段,Prefill 不受此参数控制。
        if self._enabled:
            args.append("--cuda-graph")
            # capture_iterations 仅在开启 Graphs 时有意义。
            args.extend(["--capture-iterations", str(self._capture_iterations)])

        # Decode 阶段算子:FlashAttention + Fused LayerNorm。
        # 这两个 kernel 针对小批量访存密集场景优化,是 Decode < 1ms 的关键。
        if self._enable_flash_attention:
            args.append("--enable-flash-attention")
        if self._enable_fused_layernorm:
            args.append("--enable-fused-layernorm")

        # Prefill 阶段 GEMM 后端:cutlass 对大矩阵乘法吞吐最优。
        args.extend(["--gemm-backend", self._prefill_gemm_backend])

        # 静态形状参数:CUDA Graphs 捕获时需要预分配固定大小的输入/输出缓冲区。
        args.extend([
            "--max-batch-size", str(self._max_batch_size),
            "--max-seq-len", str(self._max_seq_len),
        ])

        return args

    # ------------------------------------------------------------------
    # 配置查询
    # ------------------------------------------------------------------
    @property
    def enabled(self) -> bool:
        """是否开启 CUDA Graphs。"""
        return self._enabled

    @property
    def capture_iterations(self) -> int:
        """CUDA Graphs 捕获迭代次数。"""
        return self._capture_iterations

    @property
    def flash_attention_enabled(self) -> bool:
        """是否启用 FlashAttention(Decode 阶段)。"""
        return self._enable_flash_attention

    @property
    def fused_layernorm_enabled(self) -> bool:
        """是否启用 Fused LayerNorm(Decode 阶段)。"""
        return self._enable_fused_layernorm

    @property
    def prefill_gemm_backend(self) -> str:
        """Prefill 阶段 GEMM 后端。"""
        return self._prefill_gemm_backend

    # ------------------------------------------------------------------
    # 运行时校验
    # ------------------------------------------------------------------
    def validate(self, engine: "OrpheusFTEngine") -> bool:
        """校验引擎是否真正按本配置启用了 CUDA Graphs。

        真实 FT 路径下检查 C++ 侧 graph_captured 标志;Mock 路径下返回 False
        (Mock 不模拟 CUDA Graphs 捕获,仅保证接口可调用)。

        Args:
            engine: OrpheusFTEngine 实例。

        Returns:
            True 表示 CUDA Graphs 已真正启用;False 表示未启用(Mock 路径、
            配置关闭、或引擎构造时 cuda_graph=False)。

        为什么需要运行时校验:
            启动参数只是"请求"启用,真实 FT 可能在显存不足、形状不支持等情况下
            静默回退到非 Graphs 路径。运行时校验能在生产环境捕获这种静默回退,
            避免误以为已达标而上线后出现 Decode 延迟毛刺。
        """
        # 配置关闭时直接返回 False。
        if not self._enabled:
            return False

        # 引擎本身构造时 cuda_graph=False,即使配置 enabled=True 也无法启用。
        # 这覆盖 test_validate_returns_false_when_engine_cuda_graph_off 场景。
        if not getattr(engine, "_cuda_graph", False):
            return False

        # Mock 路径:不模拟 CUDA Graphs 捕获。
        if engine.backend == "mock":
            return False

        # 真实 FT 路径:检查 C++ 侧 graph_captured 标志(pybind11 暴露的属性)。
        binding = getattr(engine, "_binding", None)
        if binding is None:
            return False
        real_engine = getattr(binding, "_real_engine", None)
        if real_engine is None:
            return False

        # 真实 FT 引擎应在构造后暴露 graph_captured: bool 属性。
        # 若属性不存在(FT 版本不匹配),保守返回 False。
        return bool(getattr(real_engine, "graph_captured", False))


class OperatorOptimizer:
    """FT 算子分离配置校验器。

    职责:
        - verify_prefill_operators(): 校验 Prefill 路径使用 cutlass GEMM。
        - verify_decode_operators(): 校验 Decode 路径启用 FlashAttention + Fused LayerNorm。

    为什么用静态方法:
        校验逻辑从引擎实例自身状态派生(backend / _cuda_graph / _binding),
        无需外部传入 CudaGraphConfig。这样测试与生产代码都可直接
        `OperatorOptimizer.verify_prefill_operators(engine)` 调用,简洁直观。

    设计决策:
        Prefill 与 Decode 算子分离的依据是两者计算模式差异巨大:
            - Prefill:一次处理 chunk_len 个 token(可数十),GEMM 为大矩阵乘法,
              cutlass 在此场景吞吐最优。
            - Decode:每步仅 1 个 token,GEMM 退化为 GEMV,访存密集而非计算密集,
              FlashAttention(减少 HBM 读写)+ Fused LayerNorm(减少 kernel launch)
              才是延迟最优组合。
        FT 在 C++ 侧通过 is_context 标志自动切换两条路径,本类只做"是否按预期启用"的校验。

    返回值约定:
        所有 verify_* 方法返回 dict(而非 bool),含每个算子的启用状态 + note 说明。
        Mock 路径下 note 标注 "unverified"(Mock 无法验证真实算子选择,只验证配置意图)。
        真实 FT 路径下 note 标注实际查到的算子状态。
    """

    @staticmethod
    def verify_prefill_operators(engine: "OrpheusFTEngine") -> dict:
        """校验 Prefill 路径算子配置。

        检查项:
            - Prefill GEMM 后端为 cutlass(吞吐最优)。

        Args:
            engine: OrpheusFTEngine 实例。

        Returns:
            {
                'cutlass_gemm': bool,   # cutlass GEMM 是否启用
                'note': str,            # 说明文字(Mock 路径含 'unverified')
            }

        为什么 Prefill 用 cutlass 而非 cuBLAS:
            cutlass 针对 Ampere 架构的 Tensor Core 做了深度优化,且支持 FP16
            accumulator 等特殊精度组合,在 Prefill 的大矩阵场景下吞吐优于 cuBLAS。
            cuBLAS 优势在小批量 GEMV(Decode 场景),但 Decode 路径已切到
            FlashAttention,故 Prefill 统一用 cutlass。
        """
        # Mock 路径:无法验证真实算子选择,标注 unverified。
        # cutlass_gemm 返回 True 表示"配置意图"是用 cutlass(默认值),
        # 但 Mock 不实际选择算子,需在真实 FT 环境验证。
        if engine.backend == "mock":
            return {
                "cutlass_gemm": True,
                "note": (
                    "Mock path: prefill GEMM backend configured as cutlass "
                    "but unverified (real FT required for runtime verification)"
                ),
            }

        # 真实 FT 路径:检查 C++ 侧 prefill_gemm_backend 属性。
        binding = getattr(engine, "_binding", None)
        real_engine = getattr(binding, "_real_engine", None) if binding else None
        if real_engine is None:
            return {
                "cutlass_gemm": False,
                "note": "Real FT engine not available",
            }

        actual_backend = getattr(real_engine, "prefill_gemm_backend", None)
        if actual_backend is None:
            return {
                "cutlass_gemm": False,
                "note": "FT engine does not expose prefill_gemm_backend attribute",
            }
        return {
            "cutlass_gemm": actual_backend == "cutlass",
            "note": f"Prefill GEMM backend: {actual_backend}",
        }

    @staticmethod
    def verify_decode_operators(engine: "OrpheusFTEngine") -> dict:
        """校验 Decode 路径算子配置。

        检查项:
            - FlashAttention 已启用(减少 HBM 读写)。
            - Fused LayerNorm 已启用(融合 RMSNorm + residual)。

        Args:
            engine: OrpheusFTEngine 实例。

        Returns:
            {
                'flash_attention': bool,    # FlashAttention 是否启用
                'fused_layernorm': bool,    # Fused LayerNorm 是否启用
                'note': str,                # 说明文字(Mock 路径含 'unverified')
            }

        为什么 Decode 必须同时启用这两个算子:
            Decode 单 token 的瓶颈在 kernel launch 与 HBM 带宽,而非计算。
            - FlashAttention 将 attention 的 HBM 读写从 O(n^2) 降到 O(n),Decode
              场景 n=seq_len 可达数百,收益显著。
            - Fused LayerNorm 将 RMSNorm + residual + dropout 融合为单 kernel,
              减少 2-3 次 kernel launch(每次 launch ~10us,累计可省 30us+)。
            二者缺一都会让 Decode 单 token 延迟突破 1ms 目标。
        """
        # Mock 路径:无法验证真实算子选择,标注 unverified。
        if engine.backend == "mock":
            return {
                "flash_attention": True,
                "fused_layernorm": True,
                "note": (
                    "Mock path: FlashAttention + Fused LayerNorm configured as "
                    "enabled but unverified (real FT required for runtime verification)"
                ),
            }

        # 真实 FT 路径:检查 C++ 侧实际启用的算子标志。
        binding = getattr(engine, "_binding", None)
        real_engine = getattr(binding, "_real_engine", None) if binding else None
        if real_engine is None:
            return {
                "flash_attention": False,
                "fused_layernorm": False,
                "note": "Real FT engine not available",
            }

        fa_actual = bool(getattr(real_engine, "flash_attention_enabled", False))
        fln_actual = bool(getattr(real_engine, "fused_layernorm_enabled", False))
        return {
            "flash_attention": fa_actual,
            "fused_layernorm": fln_actual,
            "note": (
                f"FlashAttention={fa_actual}, FusedLayerNorm={fln_actual} "
                f"(verified from FT engine runtime)"
            ),
        }

    @staticmethod
    def verify_all(engine: "OrpheusFTEngine") -> dict:
        """一次性校验所有算子配置,返回详细诊断字典。

        用于生产环境部署时的"算子就绪检查"步骤,任一项未达标即视为部署失败。

        Args:
            engine: OrpheusFTEngine 实例。

        Returns:
            {
                'prefill': dict,          # verify_prefill_operators 结果
                'decode': dict,           # verify_decode_operators 结果
                'cuda_graph_ok': bool,    # CUDA Graphs 是否真正捕获
                'all_ok': bool,           # 全部达标
                'backend': str,           # 'ft' 或 'mock'
            }
        """
        prefill_result = OperatorOptimizer.verify_prefill_operators(engine)
        decode_result = OperatorOptimizer.verify_decode_operators(engine)

        # CUDA Graphs 校验:用默认 CudaGraphConfig(enabled=True)检查引擎。
        cfg = CudaGraphConfig(enabled=True)
        cuda_graph_ok = cfg.validate(engine)

        # all_ok:Mock 路径下 cuda_graph_ok 恒为 False,故 all_ok 也恒为 False。
        # 这是有意为之——Mock 环境不应声称"全部达标"。
        all_ok = (
            prefill_result.get("cutlass_gemm", False)
            and decode_result.get("flash_attention", False)
            and decode_result.get("fused_layernorm", False)
            and cuda_graph_ok
        )

        return {
            "prefill": prefill_result,
            "decode": decode_result,
            "cuda_graph_ok": cuda_graph_ok,
            "all_ok": all_ok,
            "backend": engine.backend,
        }
