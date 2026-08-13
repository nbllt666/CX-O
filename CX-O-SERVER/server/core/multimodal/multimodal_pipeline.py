"""MultimodalPipeline 真实实现（CX-O 迁移版，v1.1.0 扩展）。

RADIX-Lite 多模态预处理管线，CX-O 扩展为 5 模态（text / character_card /
image / video / audio）统一入口，产出 MultimodalArtifact（含 native_decode_used
字段）。接管 parser.py 下沉的解析能力（Task 6 改造 parser.py 为 thin wrapper，
调用本管线）。

CX-O 扩展要点（相对 CXHMS v1.0.0）:
    - 新增 video/audio 模态，路由到 _vllm_native_worker
    - 新增 _vllm_native_worker 方法：检测 LLM provider，vllm 时走原生 API，
      非 vllm 时降级（vision_degraded=True, native_decode_used=False）
    - 新增 _get_llm_provider() helper：从 server/config.py 读取 provider
    - MultimodalArtifact 新增 native_decode_used 字段
    - 配置加载优先级：server/config.py (MultimodalPipelineConfig) →
      public/config_template/radix_config.json schema defaults → 代码内兜底

对应契约（严格匹配签名，rules-3 §二 signature_match）:
    - public/interface_stub/multimodal_pipeline.pyi
    - public/schema/multimodal_artifact.schema.json
    - public/config_template/radix_config.json（multimodal_pipeline + vllm 段）
    - server/config.py 的 MultimodalPipelineConfig（B6 扩展节）

设计要点:
    - 数据模型（MultimodalArtifact / OCRBlock / CharacterCardFields）定义在本文件，
      与 .pyi 存根字段完全对齐（含 CX-O 扩展的 native_decode_used）。
    - 预处理逻辑下沉到 workers/ 子包（逻辑与数据分离）。
    - worker 池调度使用 ThreadPoolExecutor（避免 Windows ProcessPool pickle 问题）。
    - 配置 auto_fill（rules-3 §三）：缺失字段自动补齐默认值。
    - vision 不可用时降级（vision_degraded=True），仅返回 OCR。
    - vllm_native 不可用时降级（vision_degraded=True, native_decode_used=False）。

@version 1.1.0  # CX-O 扩展版
"""

import atexit
import json
import logging
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from .workers import CharacterCardWorker, ImageWorker, TextWorker, VLLMNativeWorker

from server.core.utils import iso_now as _iso_now

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# 路径锚点（rules-0 §三：os.path.dirname(os.path.abspath(__file__))，禁止相对路径）
# CX-O 迁移版：_THIS_DIR = c:\CX-O\CX-O-SERVER\server\core\multimodal
#   _SERVER_ROOT  = c:\CX-O\CX-O-SERVER（上 3 级，server/ 的父目录 = CX-O-SERVER 项目根）
#   _PROJECT_ROOT = c:\CX-O（上 4 级，CX-O-SERVER 的父目录 = 整个项目根，public/ 契约区根）
# 与 decision_core.py L35-37 路径锚点模式对齐。
# --------------------------------------------------------------------------- #
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
# CX-O-SERVER 项目根（server/ 的父目录）
_SERVER_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_THIS_DIR)))
# 整个项目根（CX-O-SERVER 的父目录，public/ 契约区根）
_PROJECT_ROOT = os.path.dirname(_SERVER_ROOT)
_PUBLIC_CONFIG_TEMPLATE_DIR = os.path.join(_PROJECT_ROOT, "public", "config_template")
_CONFIG_TEMPLATE_PATH = os.path.join(
    _PUBLIC_CONFIG_TEMPLATE_DIR, "radix_config.json"
)

# --------------------------------------------------------------------------- #
# 源类型枚举（与 multimodal_artifact.schema.json type enum 一致；CX-O 扩展 5 模态）
# --------------------------------------------------------------------------- #
_SOURCE_TYPES = ("text", "character_card", "image", "video", "audio")

# 走 vLLM 原生解码的模态
_VLLM_NATIVE_MODALITIES = ("video", "audio")

# --------------------------------------------------------------------------- #
# 默认配置（与 radix_config.json schema defaults 一致，auto_fill 兜底）
# --------------------------------------------------------------------------- #
_DEFAULT_CONFIG: Dict[str, Any] = {
    "worker_pool_size": 4,
    "task_timeout_seconds": 120,
    "enabled_modalities": ["text", "character_card", "image", "video", "audio"],
    "ocr_language": "ch",
    "vision_base_url": "http://127.0.0.1:8080",
    "vision_model": "",
    "vision_timeout_seconds": 300,
    "vllm_native_enabled": True,
    "vllm_base_url": "http://127.0.0.1:8080",
    "vllm_timeout_seconds": 300,
}


# =========================================================================== #
# 数据模型（与 multimodal_pipeline.pyi 字段完全对齐，含 CX-O 扩展字段）
# =========================================================================== #


class MultimodalArtifact(BaseModel):
    """多模态预处理产物。字段与 multimodal_artifact.schema.json 一致。

    CX-O 扩展（v1.1.0）: 新增 native_decode_used 字段，标记是否使用 vLLM 原生解码。
    """

    artifact_id: str
    type: str  # enum: text / character_card / image / video / audio
    source: str
    text_content: str
    native_decode_used: bool = False  # 是否使用 vLLM 原生解码（仅 video/audio 有意义）
    extra_metadata: Dict[str, Any] = {}
    confidence: float = 1.0
    vision_degraded: bool = False
    processing_time_ms: Optional[int] = None
    created_at: str


class OCRBlock(BaseModel):
    """OCR 文本块。"""

    text: str
    bbox: List[float]  # [x1, y1, x2, y2]


class CharacterCardFields(BaseModel):
    """角色卡字段（标准化后）。"""

    name: str
    description: str = ""
    personality: str = ""
    scenario: str = ""
    first_mes: str = ""
    mes_example: str = ""


# =========================================================================== #
# MultimodalPipeline 主类
# =========================================================================== #


class MultimodalPipeline:
    """MultimodalPipeline 接口契约实现（CX-O 扩展版 v1.1.0）。

    worker 池（ThreadPoolExecutor），5 模态预处理。
    接管 parser.py 下沉的解析能力。

    CX-O 扩展:
        - video/audio 模态路由到 _vllm_native_worker
        - _vllm_native_worker 检测 LLM provider，vllm 时走原生 API，否则降级

    配置来源（按优先级）:
        1. 构造时显式传入 config dict
        2. server/config.py 的 MultimodalPipelineConfig（B6 扩展节，若可导入）
        3. config/radix_config.json 实例（若存在）
        4. public/config_template/radix_config.json schema 的 default 值
        5. 代码内 _DEFAULT_CONFIG 兜底

    auto_fill（rules-3 §三）: 缺失字段自动补齐默认值。
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        """初始化 MultimodalPipeline。

        Args:
            config: 可选配置 dict。支持两种形态:
                - 扁平形态（本模块直接消费）: {worker_pool_size, vision_base_url, ...}
                - radix_config 嵌套形态: {multimodal_pipeline: {...}, vllm: {...}}
                若为 None，自动从配置文件加载 + auto_fill 默认值。
        """
        merged = self._load_and_merge_config(config)

        self._worker_pool_size: int = int(merged["worker_pool_size"])
        self._task_timeout: int = int(merged["task_timeout_seconds"])
        self._enabled_modalities: List[str] = list(merged["enabled_modalities"])
        self._ocr_language: str = merged["ocr_language"]
        self._vision_base_url: str = merged["vision_base_url"]
        self._vision_model: str = merged["vision_model"]
        self._vision_timeout_seconds: int = int(merged["vision_timeout_seconds"])
        self._vllm_native_enabled: bool = bool(merged["vllm_native_enabled"])
        self._vllm_base_url: str = merged["vllm_base_url"]
        self._vllm_timeout_seconds: int = int(merged["vllm_timeout_seconds"])

        # worker 池（ThreadPoolExecutor，避免 Windows ProcessPool pickle 问题）
        self._executor = ThreadPoolExecutor(
            max_workers=max(1, self._worker_pool_size),
            thread_name_prefix="multimodal-worker",
        )
        atexit.register(self._shutdown_executor)

        # 初始化各模态 worker
        self._text_worker_impl = TextWorker(task_timeout_seconds=self._task_timeout)
        self._character_card_worker_impl = CharacterCardWorker(
            task_timeout_seconds=self._task_timeout
        )
        self._image_worker_impl = ImageWorker(
            vision_base_url=self._vision_base_url,
            vision_model=self._vision_model,
            ocr_language=self._ocr_language,
            task_timeout_seconds=self._task_timeout,
            vision_timeout_seconds=self._vision_timeout_seconds,
        )
        # CX-O 扩展：vLLM 原生视频/音频解码 worker
        self._vllm_native_worker_impl = VLLMNativeWorker(
            vllm_base_url=self._vllm_base_url,
            vllm_timeout_seconds=self._vllm_timeout_seconds,
            task_timeout_seconds=self._task_timeout,
        )

        logger.info(
            "MultimodalPipeline 初始化: pool_size=%d, timeout=%ds, modalities=%s, "
            "vision_model=%s, vllm_native_enabled=%s",
            self._worker_pool_size,
            self._task_timeout,
            self._enabled_modalities,
            self._vision_model or "(disabled)",
            self._vllm_native_enabled,
        )

    # ------------------------------------------------------------------ #
    # 配置加载与 auto_fill
    # ------------------------------------------------------------------ #

    def _load_and_merge_config(
        self, config: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """加载并合并配置，auto_fill 缺失字段。

        Args:
            config: 显式传入配置（可为扁平或嵌套形态）

        Returns:
            扁平化后的配置 dict（含全部字段）
        """
        # 起始：代码内默认值
        merged: Dict[str, Any] = dict(_DEFAULT_CONFIG)

        # 从 public/config_template/radix_config.json 提取 default 值
        template_defaults = self._extract_defaults_from_template()
        if template_defaults:
            merged.update(template_defaults)

        # 从 server/config.py 的 MultimodalPipelineConfig 读取（B6 扩展节，优先于实例文件）
        server_config = self._load_server_config()
        if server_config:
            self._merge_nested_config(merged, server_config)

        # 从 config/radix_config.json 实例加载（若存在）
        instance_config = self._load_instance_config()
        if instance_config:
            self._merge_nested_config(merged, instance_config)

        # 显式传入的 config 优先级最高
        if config:
            self._merge_nested_config(merged, config)

        return merged

    @staticmethod
    def _extract_defaults_from_template() -> Dict[str, Any]:
        """从 public/config_template/radix_config.json 提取 default 值。

        radix_config.json 是 JSON Schema，其 properties.<field>.default 字段
        即默认值。本方法提取 multimodal_pipeline 段 + vllm 段的 default。

        Returns:
            扁平化默认值 dict；模板缺失或解析失败返回空 dict
        """
        if not os.path.isfile(_CONFIG_TEMPLATE_PATH):
            logger.warning("配置模板不存在: %s，使用代码内默认值", _CONFIG_TEMPLATE_PATH)
            return {}

        try:
            with open(_CONFIG_TEMPLATE_PATH, "r", encoding="utf-8") as f:
                template = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("配置模板解析失败: %s，使用代码内默认值", e)
            return {}

        result: Dict[str, Any] = {}
        props = template.get("properties", {})

        # multimodal_pipeline 段
        mp_props = props.get("multimodal_pipeline", {}).get("properties", {})
        for field in ("worker_pool_size", "task_timeout_seconds", "enabled_modalities",
                      "ocr_language", "vllm_native_enabled"):
            if field in mp_props and "default" in mp_props[field]:
                result[field] = mp_props[field]["default"]

        # vllm 段
        vllm_props = props.get("vllm", {}).get("properties", {})
        for field in ("vision_base_url", "vision_model", "base_url"):
            if field in vllm_props and "default" in vllm_props[field]:
                if field == "base_url":
                    result["vllm_base_url"] = vllm_props[field]["default"]
                else:
                    result[field] = vllm_props[field]["default"]
        if "timeout_seconds" in vllm_props and "default" in vllm_props["timeout_seconds"]:
            result["vision_timeout_seconds"] = vllm_props["timeout_seconds"]["default"]
            result["vllm_timeout_seconds"] = vllm_props["timeout_seconds"]["default"]

        return result

    @staticmethod
    def _load_server_config() -> Optional[Dict[str, Any]]:
        """从 server/config.py 的 MultimodalPipelineConfig 读取（B6 扩展节）。

        B6 任务已扩展 server/config.py，新增 MultimodalPipelineConfig 类。
        本方法尝试导入并提取其字段值。若 server/config.py 尚未扩展或导入失败，
        返回 None（降级到实例配置文件 + 默认值）。

        Returns:
            扁平化配置 dict 或 None（导入失败 / 字段缺失）
        """
        try:
            from server.config import get_settings  # type: ignore

            settings = get_settings()
            unified_config = getattr(settings, "config", None)
            if unified_config is None:
                return None

            # MultimodalPipelineConfig 在 B6 中挂为 UnifiedConfig.multimodal_pipeline
            mp_config = getattr(unified_config, "multimodal_pipeline", None)
            vllm_config = getattr(unified_config, "vllm", None) or getattr(
                unified_config, "llm", None
            )

            if mp_config is None:
                return None

            result: Dict[str, Any] = {}

            # multimodal_pipeline 段字段
            for field in ("worker_pool_size", "task_timeout_seconds",
                          "enabled_modalities", "ocr_language",
                          "vision_degraded_fallback", "vision_base_url",
                          "vision_model", "vision_timeout_seconds",
                          "vllm_native_enabled"):
                value = getattr(mp_config, field, None)
                if value is not None:
                    result[field] = value

            # vllm 段字段（若 vllm_config 存在）
            if vllm_config is not None:
                base_url = getattr(vllm_config, "base_url", None) or getattr(
                    vllm_config, "host", None
                )
                if base_url:
                    result["vllm_base_url"] = base_url
                    # 若 vision_base_url 未单独配置，复用 vllm base_url
                    if not result.get("vision_base_url"):
                        result["vision_base_url"] = base_url
                timeout = getattr(vllm_config, "timeout_seconds", None) or getattr(
                    vllm_config, "timeout", None
                )
                if timeout:
                    result["vllm_timeout_seconds"] = int(timeout)

            return result
        except Exception as e:
            # B6 未完成或 server.config 导入失败，降级
            logger.debug(
                "server/config.py 的 MultimodalPipelineConfig 不可用（%s），"
                "降级到实例配置文件 + 默认值", e
            )
            return None

    @staticmethod
    def _load_instance_config() -> Optional[Dict[str, Any]]:
        """从 config/radix_config.json 实例加载实际配置（若存在）。

        Returns:
            配置 dict 或 None（文件不存在 / 解析失败）
        """
        candidates = [
            os.path.join(_SERVER_ROOT, "config", "radix_config.json"),
            os.path.join(_PROJECT_ROOT, "config", "radix_config.json"),
            os.path.join(_PROJECT_ROOT, "radix_config.json"),
        ]
        for path in candidates:
            if os.path.isfile(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        return json.load(f)
                except (json.JSONDecodeError, OSError) as e:
                    logger.warning("配置实例解析失败 %s: %s", path, e)
                    return None
        return None

    @staticmethod
    def _merge_nested_config(
        target: Dict[str, Any], source: Dict[str, Any]
    ) -> None:
        """将 source 合并到 target，支持嵌套（radix_config 形态）与扁平形态。

        radix_config 嵌套形态:
            {multimodal_pipeline: {worker_pool_size, ...}, vllm: {vision_base_url, ...}}
        扁平形态:
            {worker_pool_size, vision_base_url, ...}
        """
        # 嵌套形态：multimodal_pipeline 段
        mp = source.get("multimodal_pipeline")
        if isinstance(mp, dict):
            for field in ("worker_pool_size", "task_timeout_seconds",
                          "enabled_modalities", "ocr_language",
                          "vision_degraded_fallback", "vision_base_url",
                          "vision_model", "vision_timeout_seconds",
                          "vllm_native_enabled"):
                if field in mp:
                    target[field] = mp[field]

        # 嵌套形态：vllm 段
        vllm = source.get("vllm")
        if isinstance(vllm, dict):
            for field in ("vision_base_url", "vision_model", "base_url"):
                if field in vllm:
                    if field == "base_url":
                        target["vllm_base_url"] = vllm[field]
                    else:
                        target[field] = vllm[field]
            if "timeout_seconds" in vllm:
                target["vision_timeout_seconds"] = vllm["timeout_seconds"]
                target["vllm_timeout_seconds"] = vllm["timeout_seconds"]

        # 扁平形态：直接覆盖
        for field in list(_DEFAULT_CONFIG.keys()):
            if field in source:
                target[field] = source[field]

    def _shutdown_executor(self) -> None:
        """关闭 worker 池（atexit 注册）。"""
        try:
            self._executor.shutdown(wait=False, cancel_futures=True)
        except Exception:  # pragma: no cover
            pass

    # ------------------------------------------------------------------ #
    # LLM provider 检测（CX-O 扩展，B2.5）
    # ------------------------------------------------------------------ #

    @staticmethod
    def _get_llm_provider() -> str:
        """检测当前 LLM provider（CX-O 扩展 helper，B2.5）。

        从 server/config.py 的 LLMConfig.provider 读取（B6 已确认存在）。
        若导入失败或字段缺失，返回 "unknown"（触发降级路径）。

        Returns:
            provider 字符串（"vllm" / "ollama" / "openai" / "anthropic" /
            "deepseek" / "unknown"）
        """
        try:
            from server.config import get_settings  # type: ignore

            settings = get_settings()
            unified_config = getattr(settings, "config", None)
            if unified_config is None:
                return "unknown"

            llm_config = getattr(unified_config, "llm", None)
            if llm_config is None:
                return "unknown"

            provider = getattr(llm_config, "provider", None)
            if not provider or not isinstance(provider, str):
                return "unknown"

            return provider.lower().strip()
        except Exception as e:
            logger.debug(
                "LLM provider 检测失败（%s），返回 unknown 触发降级", e
            )
            return "unknown"

    # ------------------------------------------------------------------ #
    # 公开 API（严格匹配 .pyi 签名）
    # ------------------------------------------------------------------ #

    def preprocess(
        self,
        source_type: str,
        source_ref: str,
    ) -> MultimodalArtifact:
        """统一预处理入口。

        根据 source_type 分发到对应 worker，通过 ThreadPoolExecutor 调度并加超时。
        产出统一 MultimodalArtifact。

        CX-O 扩展: source_type=video/audio 时路由到 _vllm_native_worker。

        Args:
            source_type: 模态类型（text/character_card/image/video/audio）
            source_ref: 数据源引用（文件路径/URL/文本内容）

        Returns:
            MultimodalArtifact: 预处理产物

        Raises:
            ValueError: source_type 不在枚举中 / source_ref 为空（422）
            FileNotFoundError: source_ref 指向的文件不存在（404）
            RuntimeError: 解析失败 / OCR 引擎异常 / vLLM 原生解码失败（500）
            ConnectionError: vLLM vision/native 不可用（503，触发降级路径）
            TimeoutError: 预处理超时
        """
        if source_type not in _SOURCE_TYPES:
            raise ValueError(
                f"source_type 不在枚举中（422 UNSUPPORTED_SOURCE_TYPE）: "
                f"{source_type}，合法值: {list(_SOURCE_TYPES)}"
            )
        if not source_ref:
            raise ValueError("source_ref 不能为空（422）")

        # 检查模态是否启用
        if source_type not in self._enabled_modalities:
            raise ValueError(
                f"模态 {source_type} 未启用（422），"
                f"当前 enabled_modalities: {self._enabled_modalities}"
            )

        start_ts = time.time()
        # worker 池调度 + 超时控制
        future = self._executor.submit(self._dispatch, source_type, source_ref)
        try:
            artifact = future.result(timeout=self._task_timeout)
        except FuturesTimeoutError as e:
            future.cancel()
            raise TimeoutError(
                f"预处理超时（{self._task_timeout}s）：source_type={source_type}"
            ) from e

        # 填充处理耗时
        elapsed_ms = int((time.time() - start_ts) * 1000)
        artifact.processing_time_ms = elapsed_ms
        return artifact

    def _dispatch(self, source_type: str, source_ref: str) -> MultimodalArtifact:
        """内部分发到对应 worker。

        CX-O 扩展: video/audio 路由到 _vllm_native_worker。
        """
        if source_type == "text":
            return self._text_worker(source_ref)
        if source_type == "character_card":
            return self._character_card_worker(source_ref)
        if source_type == "image":
            return self._image_worker(source_ref)
        # CX-O 扩展：video/audio 走 vLLM 原生解码
        if source_type in _VLLM_NATIVE_MODALITIES:
            return self._vllm_native_worker(source_ref, source_type)
        # 理论不可达（preprocess 已校验 _SOURCE_TYPES）
        raise ValueError(
            f"未实现的 source_type（422）: {source_type}"
        )

    # ------------------------------------------------------------------ #
    # 内部 worker（严格匹配 .pyi 签名）
    # ------------------------------------------------------------------ #

    def _text_worker(self, source_ref: str) -> MultimodalArtifact:
        """内部方法：文本模态 worker。

        编码检测（chardet）+ NFKC 归一化 + strip。委托给 workers.TextWorker。

        Args:
            source_ref: 文本内容或文件路径

        Returns:
            MultimodalArtifact（type=text, confidence=1.0）

        Raises:
            FileNotFoundError: 文件不存在（404）
            ValueError: 编码检测失败（422）
        """
        raw = self._text_worker_impl.process(source_ref)
        return self._build_artifact("text", source_ref, raw)

    def _character_card_worker(self, source_ref: str) -> MultimodalArtifact:
        """内部方法：角色卡模态 worker。

        Pillow PNG tEXt "chara" chunk → base64 decode → JSON → 字段标准化。
        委托给 workers.CharacterCardWorker。

        Args:
            source_ref: PNG 文件路径 / JSON 文件路径 / base64 字符串 / JSON 字符串

        Returns:
            MultimodalArtifact（type=character_card, extra_metadata=CharacterCardFields）

        Raises:
            FileNotFoundError: 文件不存在（404）
            ValueError: PNG tEXt chunk 缺失 / JSON 解析失败（422）
            RuntimeError: Pillow 解码异常（500）
        """
        raw = self._character_card_worker_impl.process(source_ref)
        return self._build_artifact("character_card", source_ref, raw)

    def _image_worker(self, source_ref: str) -> MultimodalArtifact:
        """内部方法：图片模态 worker（双通道）。

        PaddleOCR 通道产出 OCR 文本块 + vLLM vision 通道产出视觉描述。
        vision 不可用时降级为仅 OCR（vision_degraded=True）。
        委托给 workers.ImageWorker。

        降级策略: _vision_worker 抛 ConnectionError 时，本方法捕获并设置
        vision_degraded=True，仅返回 OCR 文本（不向外抛 ConnectionError）。

        Args:
            source_ref: 图片文件路径

        Returns:
            MultimodalArtifact（type=image, extra_metadata={ocr_blocks, vision_description}）

        Raises:
            FileNotFoundError: 文件不存在（404）
            RuntimeError: PaddleOCR 引擎异常 / 图片解码失败（500）
        """
        # OCR 通道（必须成功，失败 raise RuntimeError）
        ocr_blocks_dicts, _avg_conf = self._image_worker_impl.ocr(source_ref)

        # vision 通道（可降级）
        vision_description = ""
        try:
            vision_description = self._image_worker_impl.vision(source_ref)
        except ConnectionError as e:
            # 降级路径：vision 不可用，仅返回 OCR
            logger.warning(
                "vision 通道降级（vision_degraded=True）: %s", e
            )
            vision_description = ""
        except RuntimeError as e:
            # vision 推理失败（500）也降级，但不吞掉日志
            logger.warning(
                "vision 推理失败，降级为 OCR-only（vision_degraded=True）: %s", e
            )
            vision_description = ""

        raw = self._image_worker_impl.merge(ocr_blocks_dicts, vision_description)
        return self._build_artifact("image", source_ref, raw)

    def _vllm_native_worker(
        self,
        source_ref: str,
        modality: str,
    ) -> MultimodalArtifact:
        """内部方法（CX-O 扩展）：vLLM 原生视频/音频解码 worker。

        检测 LLM provider 配置（通过 _get_llm_provider helper）:
        - 若 provider=vllm 且 vllm_native_enabled=true：通过 vLLM OpenAI 兼容 API
          直接投递原生视频/音频文件，vLLM 内部解码后返回文本描述/转录。
          native_decode_used=True, vision_degraded=False。
        - 若 provider!=vllm 或 vllm_native_enabled=false 或 vLLM 端点不可达：
          降级路径，返回占位文本 + 降级标记。
          native_decode_used=False, vision_degraded=True, confidence=0.5。

        委托给 workers.VLLMNativeWorker。

        Args:
            source_ref: 视频或音频文件路径/URL
            modality: 模态类型（video/audio）

        Returns:
            MultimodalArtifact:
              - 原生路径：type=video/audio, text_content=vLLM 产出文本,
                native_decode_used=True, vision_degraded=False, confidence=vLLM 置信度
              - 降级路径：type=video/audio, text_content=降级提示文本,
                native_decode_used=False, vision_degraded=True, confidence=0.5

        Raises:
            ValueError: modality 不在 video/audio 枚举中（422）
            FileNotFoundError: source_ref 指向的文件不存在（404，降级路径不抛）
            ConnectionError: vLLM 端点不可用（503，触发降级路径，非阻断）
            RuntimeError: vLLM 原生解码失败 / 视频音频文件损坏（422/500）
        """
        if modality not in _VLLM_NATIVE_MODALITIES:
            raise ValueError(
                f"modality 不在 video/audio 枚举中（422）: {modality}"
            )

        # 检测 LLM provider + vllm_native_enabled 开关
        provider = self._get_llm_provider()
        use_native = (
            self._vllm_native_enabled
            and provider == "vllm"
        )

        if not use_native:
            # 降级路径：provider 非 vllm 或 vllm_native 被禁用
            logger.info(
                "vllm_native_worker 降级: provider=%s, vllm_native_enabled=%s "
                "→ 走降级路径（native_decode_used=False, vision_degraded=True）",
                provider, self._vllm_native_enabled,
            )

        raw = self._vllm_native_worker_impl.process(
            source_ref=source_ref,
            modality=modality,
            use_native=use_native,
            provider=provider,
        )
        return self._build_artifact(modality, source_ref, raw)

    # ------------------------------------------------------------------ #
    # 装配辅助
    # ------------------------------------------------------------------ #

    @staticmethod
    def _build_artifact(
        artifact_type: str,
        source: str,
        raw: Dict[str, Any],
    ) -> MultimodalArtifact:
        """根据 worker 原料 dict 装配 MultimodalArtifact。

        CX-O 扩展: 从 raw 提取 native_decode_used 字段（仅 video/audio 有意义）。

        Args:
            artifact_type: 模态类型（text/character_card/image/video/audio）
            source: 原始 source_ref
            raw: worker 返回的原料 dict（text_content/extra_metadata/confidence/
                vision_degraded/native_decode_used）

        Returns:
            MultimodalArtifact 实例
        """
        return MultimodalArtifact(
            artifact_id=str(uuid.uuid4()),
            type=artifact_type,
            source=source,
            text_content=raw.get("text_content", ""),
            native_decode_used=bool(raw.get("native_decode_used", False)),
            extra_metadata=raw.get("extra_metadata", {}),
            confidence=float(raw.get("confidence", 1.0)),
            vision_degraded=bool(raw.get("vision_degraded", False)),
            created_at=_iso_now(),
        )
