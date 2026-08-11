"""DistillationService 主实现（CX-O 迁移版）。

RADIX-Lite 蒸馏服务，CX-O-SERVER 主路由注册（端口 8000）。
9 状态机多轮蒸馏工作流，与 MultimodalPipeline（B2）+ DecisionCore（B4）协同。

从 CXHMS modules/模块9_蒸馏服务/distillation_service.py 迁移。
CX-O 扩展要点:
    - source_type 扩展为 5 模态（text / character_card / image / video / audio）
      + 向后兼容 conversation_log（映射到 text 模态）
    - MultimodalPipeline 真实接入（server.core.multimodal.MultimodalPipeline）
    - DecisionCore 真实接入（server.core.decision.DecisionCore，6 决策点真实签名）
    - 配置加载优先级：server.config.get_settings() → radix_config.json → 代码默认值
    - 路径锚点：os.path.dirname(os.path.abspath(__file__))，禁止相对路径

状态机（9 状态）:
    S_INIT -> S_PREREAD -> S_QUESTION -> S_REFLECT -> S_CROSSVALIDATE
           -> S_EXTRACT -> S_STORAGE_DECISION -> S_FINALIZE / S_REJECT

    回环: S_REFLECT -> S_QUESTION (D4_REDISTILL 决策驱动，受 max_redistill_turns 限制)
    主动追问: ask_user_on_ambiguity=True 且 S_QUESTION 时 agent_action=ask_user
    拒绝路径: S_REJECT (quality_score < rubric.quality_reject_threshold)

DecisionCore 接入点（6 决策点调用顺序）:
    - S_PREREAD/S_QUESTION: D3_ASK_USER (decide_ask_user) — 决定是否追问
    - S_REFLECT: D4_REDISTILL (decide_redistill) — 决定是否回环至 S_QUESTION
    - S_CROSSVALIDATE: D5_CROSS_VALIDATE (decide_cross_validate) — 决定是否跨源验证
    - S_STORAGE_DECISION → S_FINALIZE:
        D6_REJECT (decide_reject) 优先判定 → 若拒绝则 S_REJECT
        D1_LOCATION (decide_location) + D2_METADATA (decide_metadata) → S_FINALIZE

MultimodalPipeline 接入点:
    - S_PREREAD 状态（_run_preread 方法）调用 preprocess(source_type, source_ref)

对应契约:
    - 接口契约: public/interface_stub/distillation_service.pyi
    - 数据契约: public/schema/distillation_session.schema.json
    - 数据契约: public/schema/distillation_log.schema.json
    - 配置契约: public/config_template/radix_config.json

@version 1.1.0  # CX-O 迁移版
"""

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# 路径锚点（rules-0 §三：os.path.dirname(os.path.abspath(__file__))，禁止相对路径）
# CX-O 迁移版：_THIS_DIR     = c:\CX-O\CX-O-SERVER\server\core\distillation
#   _PROJECT_ROOT = c:\CX-O\CX-O-SERVER（上 3 级）
#   _PUBLIC_ROOT  = c:\CX-O（上 4 级，public/ 契约区根）
# 与 decision_core.py L35-37 路径锚点模式对齐。
# D12 修复（20260719）：原 4 级 dirname 多 1 级，导致 _PROJECT_ROOT = c:\CX-O（错误），
#   _resolve_path 把 data/distillation_sessions 解析到 c:\CX-O\data\（错误位置）。
# --------------------------------------------------------------------------- #
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_THIS_DIR)))
_PUBLIC_ROOT = os.path.dirname(_PROJECT_ROOT)
_DATA_DIR = os.path.join(_PROJECT_ROOT, "data")
_DEFAULT_SESSION_DIR = os.path.join(_DATA_DIR, "distillation_sessions")
_DEFAULT_LOG_DIR = os.path.join(_DATA_DIR, "distillation_logs")
_CONFIG_PATH = os.path.join(
    _PUBLIC_ROOT, "public", "config_template", "radix_config.json"
)


def _iso_now() -> str:
    """返回 ISO 8601 带时区时间戳（UTC）。"""
    return datetime.now(timezone.utc).isoformat()


def _new_uuid() -> str:
    """生成 UUID v4 字符串。"""
    return str(uuid.uuid4())


def _ensure_dir(path: str) -> None:
    """确保目录存在（auto_init: data补全，rules-0 §三）。"""
    if not os.path.exists(path):
        try:
            os.makedirs(path, exist_ok=True)
        except OSError:
            # 目录创建失败不阻断启动，写入时再报错
            pass


# --------------------------------------------------------------------------- #
# Pydantic 请求/响应模型（严格匹配 distillation_service.pyi）
# --------------------------------------------------------------------------- #


class StartDistillationRequest(BaseModel):
    """启动蒸馏会话请求。"""

    source_type: str  # enum: text / character_card / image / video / audio / conversation_log
    source_ref: Optional[str] = None
    template_id: str
    max_turns: int = 4  # 1-6
    ask_user_on_ambiguity: bool = True


class StartDistillationResponse(BaseModel):
    """启动蒸馏会话响应。"""

    session_id: str
    initial_state: str  # S_PREREAD
    preread_summary: Optional[str]


class AdvanceDistillationRequest(BaseModel):
    """推进蒸馏状态机请求。"""

    user_response: Optional[str] = None  # ask_user 时的用户响应


class AdvanceDistillationResponse(BaseModel):
    """推进蒸馏状态机响应。"""

    session_id: str
    current_state: str
    agent_action: str  # enum: ask_user / proceed / reflect / cross_validate / extract / decide / finalize / reject
    next_needed: bool  # 是否需要用户进一步输入


class FinalizeDistillationRequest(BaseModel):
    """终结蒸馏会话请求。"""

    override_decision: Optional[str] = None  # 人类覆盖决策


class FinalizeDistillationResponse(BaseModel):
    """终结蒸馏会话响应。"""

    stored: bool
    location: str  # enum: memories / permanent_memories / rejected
    memory_id: Optional[int]
    metadata: Dict[str, Any]
    reason: str


class SessionStatusResponse(BaseModel):
    """会话状态查询响应。字段与 distillation_session.schema.json 一致。"""

    session_id: str
    source_type: str
    state: str
    template_id: str
    max_turns: int
    ask_user_on_ambiguity: bool
    turns: List[Dict[str, Any]]
    preread_summary: Optional[str]
    ambiguity_questions: List[str]
    extracted_content: Optional[str]
    quality_score: Optional[float]
    created_at: str
    updated_at: Optional[str]
    finalized_at: Optional[str]
    is_finalized: bool
    error_message: Optional[str]


# --------------------------------------------------------------------------- #
# 状态机定义（与 distillation_session.schema.json enum 一致）
# --------------------------------------------------------------------------- #

# CX-O 扩展：5 模态 + conversation_log 向后兼容
_SOURCE_TYPES = {
    "text",
    "character_card",
    "image",
    "video",
    "audio",
    "conversation_log",
}

# MultimodalPipeline 原生支持的 5 模态（conversation_log 映射到 text）
_MULTIMODAL_SOURCE_TYPES = {"text", "character_card", "image", "video", "audio"}

_STATES = (
    "S_INIT",
    "S_PREREAD",
    "S_QUESTION",
    "S_REFLECT",
    "S_CROSSVALIDATE",
    "S_EXTRACT",
    "S_STORAGE_DECISION",
    "S_FINALIZE",
    "S_REJECT",
)

_AGENT_ACTIONS = (
    "ask_user",
    "proceed",
    "reflect",
    "cross_validate",
    "extract",
    "decide",
    "finalize",
    "reject",
)

# 终态集合
_TERMINAL_STATES = {"S_FINALIZE", "S_REJECT"}

# 状态机转移表：(current_state, agent_action) -> next_state
_TRANSITIONS: Dict[str, Dict[str, str]] = {
    "S_INIT": {"proceed": "S_PREREAD"},
    "S_PREREAD": {"ask_user": "S_QUESTION", "proceed": "S_QUESTION"},
    "S_QUESTION": {"proceed": "S_REFLECT", "ask_user": "S_QUESTION"},
    "S_REFLECT": {
        "proceed": "S_CROSSVALIDATE",
        "reflect": "S_QUESTION",
    },
    "S_CROSSVALIDATE": {
        "cross_validate": "S_EXTRACT",
        "proceed": "S_EXTRACT",
    },
    "S_EXTRACT": {"extract": "S_STORAGE_DECISION"},
    "S_STORAGE_DECISION": {
        "decide": "S_FINALIZE",
        "reject": "S_REJECT",
    },
    "S_FINALIZE": {"finalize": "S_FINALIZE"},
    "S_REJECT": {"reject": "S_REJECT"},
}


# --------------------------------------------------------------------------- #
# LLM 质量评估 prompt（OBS-6 方案 C：自然 S_REJECT 可达性修复）
# 评分范围 0.0~1.0；< quality_reject_threshold(默认 0.3) 触发自然 S_REJECT
# 输出强制 JSON：{"quality_score": float, "reason": str}
# --------------------------------------------------------------------------- #
QUALITY_ESTIMATE_PROMPT = """你是 RADIX-Lite 蒸馏服务质量评估器。请基于以下蒸馏会话内容评估其质量评分。

【评估维度】
1. preread_summary 预读摘要的语义完整性（是否包含可识别的主题、实体、关系）
2. turns 多轮对话的实质性（是否产生有效信息增量，而非空转或重复）
3. extracted_content 抽取内容与 source_type 的匹配度
4. 内容是否低质（乱码、空白、无意义重复、过短无法形成记忆）

【评分标准】
- 0.0~0.2：极低质（乱码、空白、纯噪声、无任何可记忆信息）→ 应触发 S_REJECT
- 0.3~0.5：低质（信息稀薄、内容过短、语义不完整）→ 临界拒绝
- 0.6~0.8：合格（有明确主题、一定信息量、可形成记忆）
- 0.9~1.0：优质（信息丰富、语义完整、有长期记忆价值）

【输入会话】
source_type: {source_type}
template_id: {template_id}
preread_summary: {preread_summary}
turns_count: {turns_count}
turns_summary: {turns_summary}
extracted_content: {extracted_content}

【输出要求】
- 严格输出 JSON，不要包含任何额外文字或 markdown 代码块标记
- 格式：{{"quality_score": <float 0.0-1.0>, "reason": "<不超过 100 字的评分理由>"}}
"""


# --------------------------------------------------------------------------- #
# 配置加载（rules-3 §三 auto_fill，best-effort）
# 优先级：server.config.get_settings() → radix_config.json → 代码默认值
# --------------------------------------------------------------------------- #


def _load_distillation_config() -> Dict[str, Any]:
    """加载 distillation 配置（CX-O 适配版）。

    优先级:
        1. server.config.get_settings().config.distillation（B6 DistillationConfig）
        2. public/config_template/radix_config.json 的 distillation_service 段
        3. 代码内默认值

    Returns:
        Dict[str, Any]: distillation 配置段
    """
    defaults = {
        "host": "127.0.0.1",
        "port": 8000,  # CX-O-SERVER 主服务端口（不再独立 8011）
        "max_turns": 4,
        "session_timeout_seconds": 1800,
        "session_storage_dir": "data/distillation_sessions",
        "log_storage_dir": "data/distillation_logs",
        "main_backend_url": "http://127.0.0.1:8000",
        # OBS-6 方案 C：LLM 质量评估配置
        "quality_llm_enabled": True,
        "quality_llm_model": "",  # 空字符串表示从 llm 段继承默认模型
        "quality_llm_timeout_seconds": 30,
    }

    # 1. 从 server.config 读取（B6 扩展节）
    try:
        from server.config import get_settings  # type: ignore

        settings = get_settings()
        unified = getattr(settings, "config", None)
        if unified is not None:
            distill_cfg = getattr(unified, "distillation", None)
            if distill_cfg is not None:
                return {
                    "host": getattr(distill_cfg, "host", defaults["host"]),
                    "port": getattr(distill_cfg, "port", defaults["port"]),
                    "max_turns": getattr(distill_cfg, "max_turns", defaults["max_turns"]),
                    "session_timeout_seconds": getattr(
                        distill_cfg, "session_timeout_seconds", defaults["session_timeout_seconds"]
                    ),
                    "session_storage_dir": getattr(
                        distill_cfg, "session_storage_dir", defaults["session_storage_dir"]
                    ),
                    "log_storage_dir": getattr(
                        distill_cfg, "log_storage_dir", defaults["log_storage_dir"]
                    ),
                    "main_backend_url": getattr(
                        distill_cfg, "main_backend_url", defaults["main_backend_url"]
                    ),
                    # OBS-6 方案 C：LLM 质量评估配置
                    "quality_llm_enabled": getattr(
                        distill_cfg, "quality_llm_enabled", defaults["quality_llm_enabled"]
                    ),
                    "quality_llm_model": getattr(
                        distill_cfg, "quality_llm_model", defaults["quality_llm_model"]
                    ),
                    "quality_llm_timeout_seconds": getattr(
                        distill_cfg, "quality_llm_timeout_seconds", defaults["quality_llm_timeout_seconds"]
                    ),
                }
    except Exception as e:  # noqa: BLE001
        logger.debug("server.config.distillation 不可用（%s），降级到 radix_config.json", e)

    # 2. 从 radix_config.json 读取
    try:
        if os.path.exists(_CONFIG_PATH):
            with open(_CONFIG_PATH, "r", encoding="utf-8") as fh:
                full = json.load(fh)
            seg = full.get("distillation_service", {})
            if not isinstance(seg, dict):
                seg = {}
            for k, v in defaults.items():
                if k not in seg or seg[k] is None:
                    seg[k] = v
            # 范围校验（best-effort，超范围回退默认值）
            try:
                if not (1 <= int(seg["max_turns"]) <= 6):
                    seg["max_turns"] = defaults["max_turns"]
                if not (1024 <= int(seg["port"]) <= 65535):
                    seg["port"] = defaults["port"]
                if not (60 <= int(seg["session_timeout_seconds"]) <= 7200):
                    seg["session_timeout_seconds"] = defaults["session_timeout_seconds"]
            except (ValueError, TypeError):
                pass
            # CX-O-SERVER 主服务端口固定 8000（RADIX 子服务已合并）
            seg["port"] = 8000
            return seg
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("radix_config.json 解析失败（%s），使用默认值", e)

    # 3. 默认值
    return defaults


def _load_vllm_base_url() -> str:
    """加载 vLLM 主模型服务 URL（CX-O 适配版）。

    优先级:
        1. server.config.get_settings().config.llm.base_url（或 vllm.base_url）
        2. radix_config.json 的 vllm.base_url
        3. 默认 http://127.0.0.1:8002

    Returns:
        str: vLLM 主模型服务 URL
    """
    default_url = "http://127.0.0.1:8002"

    # 1. server.config
    try:
        from server.config import get_settings  # type: ignore

        settings = get_settings()
        unified = getattr(settings, "config", None)
        if unified is not None:
            # 优先 vllm 段（若存在），否则 llm 段
            vllm_cfg = getattr(unified, "vllm", None)
            if vllm_cfg is not None:
                url = getattr(vllm_cfg, "base_url", None) or getattr(vllm_cfg, "host", None)
                if url:
                    return url
            llm_cfg = getattr(unified, "llm", None)
            if llm_cfg is not None:
                # LLMConfig 可能有 base_url / host / api_base
                for attr in ("base_url", "host", "api_base"):
                    url = getattr(llm_cfg, attr, None)
                    if url:
                        return url
    except Exception as e:  # noqa: BLE001
        logger.debug("server.config vllm url 不可用（%s），降级", e)

    # 2. radix_config.json
    try:
        if os.path.exists(_CONFIG_PATH):
            with open(_CONFIG_PATH, "r", encoding="utf-8") as fh:
                full = json.load(fh)
            vllm_seg = full.get("vllm", {})
            if isinstance(vllm_seg, dict):
                return vllm_seg.get("base_url", default_url)
    except (json.JSONDecodeError, OSError):
        pass

    return default_url


def _load_decision_core_config() -> Dict[str, Any]:
    """加载 decision_core 配置（CX-O 适配版）。

    优先级:
        1. server.config.get_settings().config.decision_core（B6 DecisionCoreConfig）
        2. radix_config.json 的 decision_core 段
        3. 代码默认值

    Returns:
        Dict[str, Any]: decision_core 配置段（rubric 默认值）
    """
    defaults = {
        "importance_threshold_permanent": 0.7,
        "quality_reject_threshold": 0.3,
        "max_redistill_turns": 2,
        "ask_user_confidence_threshold": 0.4,
        "cross_validate_sources": [],
        "rejected_content_retention_days": 30,
        "system_prompt_fallback_enabled": True,
    }

    # 1. server.config
    try:
        from server.config import get_settings  # type: ignore

        settings = get_settings()
        unified = getattr(settings, "config", None)
        if unified is not None:
            dc_cfg = getattr(unified, "decision_core", None)
            if dc_cfg is not None:
                return {
                    "importance_threshold_permanent": getattr(
                        dc_cfg, "importance_threshold_permanent", defaults["importance_threshold_permanent"]
                    ),
                    "quality_reject_threshold": getattr(
                        dc_cfg, "quality_reject_threshold", defaults["quality_reject_threshold"]
                    ),
                    "max_redistill_turns": getattr(
                        dc_cfg, "max_redistill_turns", defaults["max_redistill_turns"]
                    ),
                    "ask_user_confidence_threshold": getattr(
                        dc_cfg, "ask_user_confidence_threshold", defaults["ask_user_confidence_threshold"]
                    ),
                    "cross_validate_sources": list(
                        getattr(dc_cfg, "cross_validate_sources", defaults["cross_validate_sources"])
                    ),
                    "rejected_content_retention_days": getattr(
                        dc_cfg, "rejected_content_retention_days", defaults["rejected_content_retention_days"]
                    ),
                    "system_prompt_fallback_enabled": getattr(
                        dc_cfg, "system_prompt_fallback_enabled", defaults["system_prompt_fallback_enabled"]
                    ),
                }
    except Exception as e:  # noqa: BLE001
        logger.debug("server.config.decision_core 不可用（%s），降级", e)

    # 2. radix_config.json
    try:
        if os.path.exists(_CONFIG_PATH):
            with open(_CONFIG_PATH, "r", encoding="utf-8") as fh:
                full = json.load(fh)
            seg = full.get("decision_core", {})
            if not isinstance(seg, dict):
                seg = {}
            for k, v in defaults.items():
                if k not in seg or seg[k] is None:
                    seg[k] = v
            return seg
    except (json.JSONDecodeError, OSError):
        pass

    return defaults


# --------------------------------------------------------------------------- #
# 子系统导入（CX-O 真实实现，best-effort 降级）
# --------------------------------------------------------------------------- #


def _import_multimodal_pipeline():
    """导入 MultimodalPipeline（CX-O 真实实现，B2 已就位）。

    优先使用 server.core.multimodal.MultimodalPipeline。
    导入失败时返回 None（调用方走降级路径）。

    Returns:
        MultimodalPipeline 类，或 None（导入失败）
    """
    try:
        from server.core.multimodal import MultimodalPipeline

        return MultimodalPipeline
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "MultimodalPipeline 导入失败（%s），S_PREREAD 将走降级路径", e
        )
        return None


def _import_decision_core():
    """导入 DecisionCore 及其数据模型（CX-O 真实实现，B4 已就位）。

    优先使用 server.core.decision.DecisionCore。
    导入失败时返回 None 元组（调用方走降级路径）。

    Returns:
        (DecisionCore, RubricSnapshot, DecisionInput, FinalDecision, StorageDecision) 元组，
        或全 None 元组（导入失败）
    """
    try:
        from server.core.decision import (
            DecisionCore,
            DecisionInput,
            FinalDecision,
            RubricSnapshot,
            StorageDecision,
        )

        return DecisionCore, RubricSnapshot, DecisionInput, FinalDecision, StorageDecision
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "DecisionCore 导入失败（%s），_invoke_decision_core 将走降级路径", e
        )
        return None, None, None, None, None


# --------------------------------------------------------------------------- #
# DistillationService 主类
# --------------------------------------------------------------------------- #


class DistillationService:
    """DistillationService 实现（CX-O 迁移版）。

    CX-O-SERVER 主路由注册（端口 8000），承载 9 状态机多轮蒸馏工作流。
    接入 MultimodalPipeline（B2）+ DecisionCore（B4）真实实现。

    公开方法签名严格匹配 public/interface_stub/distillation_service.pyi。

    DecisionCore 6 决策点接入:
        - D3_ASK_USER  : S_PREREAD / S_QUESTION 状态，决定是否追问
        - D4_REDISTILL : S_REFLECT 状态，决定是否回环至 S_QUESTION
        - D5_CROSS_VALIDATE : S_CROSSVALIDATE 状态，决定是否跨源验证
        - D6_REJECT / D1_LOCATION / D2_METADATA : S_STORAGE_DECISION 状态，
          finalize_distillation 阶段调用
    """

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        multimodal_pipeline: Optional[Any] = None,
        decision_core: Optional[Any] = None,
    ) -> None:
        """初始化 DistillationService。

        Args:
            config: 配置字典（None 时从 server.config / radix_config.json 加载）
            multimodal_pipeline: MultimodalPipeline 实例（None 时自动实例化）
            decision_core: DecisionCore 实例（None 时自动实例化）
        """
        # 配置加载
        self._config: Dict[str, Any] = (
            config if config is not None else _load_distillation_config()
        )

        # auto_init: data 补全
        self._session_dir = self._resolve_path(
            self._config.get("session_storage_dir", "data/distillation_sessions")
        )
        self._log_dir = self._resolve_path(
            self._config.get("log_storage_dir", "data/distillation_logs")
        )
        _ensure_dir(self._session_dir)
        _ensure_dir(self._log_dir)

        # 子系统实例化：MultimodalPipeline（B2）
        if multimodal_pipeline is not None:
            self._multimodal_pipeline = multimodal_pipeline
        else:
            mp_cls = _import_multimodal_pipeline()
            if mp_cls is not None:
                try:
                    self._multimodal_pipeline = mp_cls()
                except Exception as e:  # noqa: BLE001
                    logger.warning(
                        "MultimodalPipeline 实例化失败（%s），S_PREREAD 将走降级路径", e
                    )
                    self._multimodal_pipeline = None
            else:
                self._multimodal_pipeline = None

        # 子系统实例化：DecisionCore（B4）
        if decision_core is not None:
            self._decision_core = decision_core
            # 尝试加载辅助数据模型（best-effort）
            dc_classes = _import_decision_core()
            self._rubric_cls = dc_classes[1]
            self._decision_input_cls = dc_classes[2]
        else:
            dc_classes = _import_decision_core()
            dc_cls = dc_classes[0]
            self._rubric_cls = dc_classes[1]
            self._decision_input_cls = dc_classes[2]
            if dc_cls is not None:
                try:
                    self._decision_core = dc_cls()
                except Exception as e:  # noqa: BLE001
                    logger.warning(
                        "DecisionCore 实例化失败（%s），_invoke_decision_core 将走降级路径", e
                    )
                    self._decision_core = None
            else:
                self._decision_core = None

        # 内置 rubric（从 decision_core 配置加载）
        self._decision_core_config = _load_decision_core_config()
        self._rubric = self._build_default_rubric()

        # OBS-6 方案 C：LLM 质量评估配置（自然 S_REJECT 可达性修复）
        self._quality_llm_enabled: bool = bool(
            self._config.get("quality_llm_enabled", True)
        )
        self._quality_llm_model: str = str(self._config.get("quality_llm_model", ""))
        self._quality_llm_timeout: int = int(
            self._config.get("quality_llm_timeout_seconds", 30)
        )
        # vLLM 主模型服务 URL（LLM 质量评估调用目标）
        self._vllm_base_url: str = _load_vllm_base_url()

        # 内存态 session 索引（持久化层的缓存，提升查询性能）
        self._sessions_cache: Dict[str, Dict[str, Any]] = {}

    # ------------------------------------------------------------------ #
    # 公开 API（严格匹配 .pyi 签名）
    # ------------------------------------------------------------------ #

    async def start_distillation(
        self,
        source_type: str,
        source_ref: Optional[str],
        template_id: str,
        max_turns: int,
        ask_user_on_ambiguity: bool,
    ) -> StartDistillationResponse:
        """启动蒸馏会话。

        异步触发 MultimodalPipeline 预处理，session 进入 S_PREREAD 状态。

        Args:
            source_type: 数据源类型（text/character_card/image/video/audio/conversation_log）
            source_ref: 数据源引用（文件路径/URL/文本 hash）
            template_id: 关联模板 ID
            max_turns: 最大轮次（1-6）
            ask_user_on_ambiguity: 是否主动追问

        Returns:
            StartDistillationResponse: session_id + initial_state + preread_summary

        Raises:
            ValueError: source_type 不在枚举中 / max_turns 超出范围（422）
            RuntimeError: MultimodalPipeline 预处理失败（422）
            ConnectionError: MultimodalPipeline 不可用（500）
        """
        # 参数校验（422）
        if source_type not in _SOURCE_TYPES:
            raise ValueError(
                f"source_type 不在枚举中（422）: {source_type}，"
                f"合法值: {sorted(_SOURCE_TYPES)}"
            )
        if not (1 <= max_turns <= 6):
            raise ValueError(
                f"max_turns 超出范围 1-6（422）: {max_turns}"
            )
        if not template_id:
            raise ValueError("template_id 不能为空（422）")

        session_id = _new_uuid()
        now = _iso_now()

        # 调用 MultimodalPipeline 预处理（S_PREREAD，B2 接入点）
        preread_summary, ambiguity_questions = await self._run_preread(
            source_type, source_ref, template_id
        )

        # 构造 session（符合 distillation_session.schema.json）
        session: Dict[str, Any] = {
            "session_id": session_id,
            "source_type": source_type,
            "source_ref": source_ref,
            "state": "S_PREREAD",
            "template_id": template_id,
            "max_turns": max_turns,
            "ask_user_on_ambiguity": ask_user_on_ambiguity,
            "turns": [
                {
                    "turn_index": 0,
                    "state": "S_INIT",
                    "agent_action": "proceed",
                    "agent_output": "[DistillationService] 初始化会话",
                    "user_response": None,
                    "timestamp": now,
                },
                {
                    "turn_index": 1,
                    "state": "S_PREREAD",
                    "agent_action": "proceed",
                    "agent_output": preread_summary,
                    "user_response": None,
                    "timestamp": now,
                },
            ],
            "preread_summary": preread_summary,
            "ambiguity_questions": list(ambiguity_questions),
            "extracted_content": None,
            "quality_score": None,
            "created_at": now,
            "updated_at": now,
            "finalized_at": None,
            "is_finalized": False,
            "error_message": None,
        }

        # 持久化 + 缓存
        self._save_session(session)
        self._sessions_cache[session_id] = session

        return StartDistillationResponse(
            session_id=session_id,
            initial_state="S_PREREAD",
            preread_summary=preread_summary,
        )

    async def advance_distillation(
        self,
        session_id: str,
        user_response: Optional[str],
    ) -> AdvanceDistillationResponse:
        """推进蒸馏状态机一步。

        支持回环（S_REFLECT → S_QUESTION）和主动追问（ask_user_on_ambiguity=True）。
        接入 DecisionCore D3/D4/D5 决策点。

        Args:
            session_id: 会话 ID
            user_response: 用户对 ask_user 的响应（如无则为 None）

        Returns:
            AdvanceDistillationResponse: session_id + current_state + agent_action + next_needed

        Raises:
            KeyError: session_id 不存在（404）
            ValueError: 非法状态转移 / 会话已终结 / 超过最大轮次（409）
            RuntimeError: LLM 调用失败（500）
        """
        session = self._load_session(session_id)
        if session is None:
            raise KeyError(f"session_id 不存在（404）: {session_id}")
        if session["is_finalized"]:
            raise ValueError(
                f"会话已终结（409）: state={session['state']}"
            )

        current_state = session["state"]
        current_turn_index = len(session["turns"])

        # 构造 rubric + decision_input（供 D3/D4/D5 使用）
        rubric_snapshot = self._build_rubric_snapshot()
        decision_input = self._build_decision_input(session, session.get("quality_score"))

        # 推进策略（按当前状态决策下一步动作）
        if current_state == "S_PREREAD":
            # D3_ASK_USER 决策 + 疑点清单 + ask_user_on_ambiguity
            should_ask = self._invoke_d3_ask_user(
                session_id, rubric_snapshot
            )
            if (
                should_ask
                and session["ambiguity_questions"]
                and session["ask_user_on_ambiguity"]
                and not user_response
            ):
                action = "ask_user"
                next_state = self._transition_state(current_state, action)
                next_needed = True
                agent_output = (
                    "[DistillationService] D3 决策追问，疑点待澄清: "
                    + "; ".join(session["ambiguity_questions"])
                )
            else:
                action = "proceed"
                next_state = self._transition_state(current_state, action)
                next_needed = False
                agent_output = "[DistillationService] 进入 S_QUESTION 状态"

        elif current_state == "S_QUESTION":
            # D3_ASK_USER 决策 + ask_user_on_ambiguity=True 且用户未答复 → 继续追问
            should_ask = self._invoke_d3_ask_user(
                session_id, rubric_snapshot
            )
            if (
                should_ask
                and session["ask_user_on_ambiguity"]
                and session["ambiguity_questions"]
                and not user_response
            ):
                action = "ask_user"
                next_state = self._transition_state(current_state, action)
                next_needed = True
                agent_output = "[DistillationService] D3 决策继续追问，等待用户响应"
            else:
                action = "proceed"
                next_state = self._transition_state(current_state, action)
                next_needed = False
                agent_output = "[DistillationService] 进入 S_REFLECT 状态"

        elif current_state == "S_REFLECT":
            # D4_REDISTILL 决策：是否回环至 S_QUESTION
            # 受 max_redistill_turns 限制，且总轮次不得超过 max_turns
            redistill_count = self._count_redistill_turns(session)
            should_redistill = self._invoke_d4_redistill(
                session_id, redistill_count, rubric_snapshot
            )
            can_redistill = (
                should_redistill
                and current_turn_index < session["max_turns"]
            )
            if can_redistill:
                action = "reflect"
                next_state = self._transition_state(current_state, action)
                next_needed = True
                agent_output = (
                    f"[DistillationService] D4 决策回环至 S_QUESTION "
                    f"(redistill_count={redistill_count + 1}, "
                    f"max_redistill_turns={self._rubric.get('max_redistill_turns', 2)})"
                )
            else:
                action = "proceed"
                next_state = self._transition_state(current_state, action)
                next_needed = False
                agent_output = (
                    f"[DistillationService] D4 决策不回环，进入 S_CROSSVALIDATE "
                    f"(redistill_count={redistill_count}, "
                    f"max_redistill_turns={self._rubric.get('max_redistill_turns', 2)})"
                )

        elif current_state == "S_CROSSVALIDATE":
            # D5_CROSS_VALIDATE 决策：是否跨源验证
            should_cross_validate = self._invoke_d5_cross_validate(
                session_id, decision_input, rubric_snapshot
            )
            if should_cross_validate:
                action = "cross_validate"
                next_state = self._transition_state(current_state, action)
                agent_output = (
                    f"[DistillationService] D5 跨源验证 "
                    f"sources={self._rubric.get('cross_validate_sources', [])}"
                )
            else:
                action = "proceed"
                next_state = self._transition_state(current_state, action)
                agent_output = "[DistillationService] D5 跳过跨源验证"
            next_needed = False

        elif current_state == "S_EXTRACT":
            # 抽取结构化内容
            action = "extract"
            next_state = self._transition_state(current_state, action)
            next_needed = False
            extracted = self._extract_content(session)
            session["extracted_content"] = extracted
            agent_output = f"[DistillationService] 抽取结果: {extracted[:200]}..."

        elif current_state == "S_STORAGE_DECISION":
            # D1_LOCATION / D6_REJECT 决策
            # 根据 preread_summary 推断 quality_score
            quality_score = self._estimate_quality_score(session)
            session["quality_score"] = quality_score
            reject_threshold = self._rubric.get("quality_reject_threshold", 0.3)
            if quality_score < reject_threshold:
                action = "reject"
                next_state = self._transition_state(current_state, action)
                agent_output = (
                    f"[DistillationService] D6 拒绝存储 "
                    f"(quality_score={quality_score} < {reject_threshold})"
                )
            else:
                action = "decide"
                next_state = self._transition_state(current_state, action)
                agent_output = (
                    f"[DistillationService] D1 决策存储位置 "
                    f"(quality_score={quality_score})"
                )
            next_needed = False

        else:
            raise ValueError(
                f"非法状态转移（409）: current_state={current_state}"
            )

        # 记录新轮次
        now = _iso_now()
        session["state"] = next_state
        session["updated_at"] = now
        # 终态时设置 finalized_at + is_finalized
        # 仅 S_REJECT 在 advance 中设置 is_finalized（拒绝路径，无需记忆存储）
        # S_FINALIZE 不在此处设置 is_finalized，留给 finalize_distillation 执行记忆存储后设置
        if next_state == "S_REJECT":
            session["is_finalized"] = True
            session["finalized_at"] = now

        session["turns"].append(
            {
                "turn_index": len(session["turns"]),
                "state": next_state,
                "agent_action": action,
                "agent_output": agent_output,
                "user_response": user_response,
                "timestamp": now,
            }
        )

        # 持久化 + 缓存更新
        self._save_session(session)
        self._sessions_cache[session_id] = session

        return AdvanceDistillationResponse(
            session_id=session_id,
            current_state=next_state,
            agent_action=action,
            next_needed=next_needed,
        )

    async def finalize_distillation(
        self,
        session_id: str,
        override_decision: Optional[str],
    ) -> FinalizeDistillationResponse:
        """终结蒸馏会话，执行存储决策。

        调用 DecisionCore 执行 6 决策点（D1/D2/D6），返回存储结果。

        DecisionCore 调用顺序:
            1. 若 override_decision 非空 → 人类覆盖优先
            2. D6_REJECT 优先判定（quality_score < threshold）
            3. D1_LOCATION 位置决策 + D2_METADATA 元数据决策

        Args:
            session_id: 会话 ID
            override_decision: 人类覆盖决策（非 None 时覆盖 agent 决策）

        Returns:
            FinalizeDistillationResponse: stored + location + memory_id + metadata + reason

        Raises:
            KeyError: session_id 不存在（404）
            ValueError: 会话已终结（409）
            RuntimeError: DecisionCore 决策失败 / 审计日志写入失败（500）
        """
        session = self._load_session(session_id)
        if session is None:
            raise KeyError(f"session_id 不存在（404）: {session_id}")
        if session["is_finalized"]:
            raise ValueError("会话已终结（409）")

        # 调用 DecisionCore 决策（best-effort，失败时降级到内置规则）
        quality_score = session.get("quality_score")
        if quality_score is None:
            quality_score = self._estimate_quality_score(session)
            session["quality_score"] = quality_score

        location, memory_id, metadata, reason = self._invoke_decision_core(
            session=session,
            quality_score=quality_score,
            override_decision=override_decision,
        )

        # 更新 session 状态
        now = _iso_now()
        session["state"] = "S_REJECT" if location == "rejected" else "S_FINALIZE"
        session["is_finalized"] = True
        session["finalized_at"] = now
        session["updated_at"] = now
        session["turns"].append(
            {
                "turn_index": len(session["turns"]),
                "state": session["state"],
                "agent_action": "reject" if location == "rejected" else "finalize",
                "agent_output": reason,
                "user_response": override_decision,
                "timestamp": now,
            }
        )

        # 持久化
        self._save_session(session)
        self._sessions_cache[session_id] = session

        stored = location != "rejected"
        return FinalizeDistillationResponse(
            stored=stored,
            location=location,
            memory_id=memory_id,
            metadata=metadata,
            reason=reason,
        )

    async def get_session_status(self, session_id: str) -> SessionStatusResponse:
        """查询会话状态。

        Args:
            session_id: 会话 ID

        Returns:
            SessionStatusResponse: 完整会话状态

        Raises:
            KeyError: session_id 不存在（404）
        """
        session = self._load_session(session_id)
        if session is None:
            raise KeyError(f"session_id 不存在（404）: {session_id}")

        return SessionStatusResponse(
            session_id=session["session_id"],
            source_type=session["source_type"],
            state=session["state"],
            template_id=session["template_id"],
            max_turns=session["max_turns"],
            ask_user_on_ambiguity=session["ask_user_on_ambiguity"],
            turns=list(session["turns"]),
            preread_summary=session["preread_summary"],
            ambiguity_questions=list(session["ambiguity_questions"]),
            extracted_content=session["extracted_content"],
            quality_score=session["quality_score"],
            created_at=session["created_at"],
            updated_at=session["updated_at"],
            finalized_at=session["finalized_at"],
            is_finalized=session["is_finalized"],
            error_message=session["error_message"],
        )

    # ------------------------------------------------------------------ #
    # 批量切分蒸馏（CX-O 迁移，精简版）
    # ------------------------------------------------------------------ #

    async def start_batch_distillation(
        self,
        source_type: str,
        source_ref: str,
        template_id: str,
        max_turns: int,
        ask_user_on_ambiguity: bool,
        chunk_size: int = 4000,
        distillation_goal: str = "memory",
        target_agent_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """批量切分启动蒸馏会话。

        将超长 source_ref 按 chunk_size 切分为多个片段，每个片段创建独立 session，
        归属同一 session_group_id。串行蒸馏（一个 chunk 完成后启动下一个）。

        Args:
            source_type: 数据源类型
            source_ref: 超长文本内容
            template_id: 模板 ID
            max_turns: 最大轮次（1-6）
            ask_user_on_ambiguity: 是否主动追问
            chunk_size: 切分大小（token 估算，默认 4000）
            distillation_goal: 蒸馏目标（memory / agent / memory_and_agent）
            target_agent_id: 记忆蒸馏注入的目标 agent

        Returns:
            dict: session_group_id + sessions 数组 + total_chunks

        Raises:
            ValueError: 参数无效（422）
        """
        if source_type not in _SOURCE_TYPES:
            raise ValueError(f"source_type 不在枚举中（422）: {source_type}")
        if not (1 <= max_turns <= 6):
            raise ValueError(f"max_turns 超出范围 1-6（422）: {max_turns}")
        if not template_id:
            raise ValueError("template_id 不能为空（422）")
        if not source_ref:
            raise ValueError("source_ref 不能为空（422）")
        if chunk_size < 500:
            chunk_size = 500
        if distillation_goal not in ("memory", "agent", "memory_and_agent"):
            raise ValueError(
                f"distillation_goal 不在枚举中（422）: {distillation_goal}"
            )

        chunks = self._split_text_into_chunks(source_ref, chunk_size)
        session_group_id = _new_uuid()
        sessions = []

        for idx, chunk in enumerate(chunks):
            start_resp = await self.start_distillation(
                source_type=source_type,
                source_ref=chunk,
                template_id=template_id,
                max_turns=max_turns,
                ask_user_on_ambiguity=ask_user_on_ambiguity,
            )
            # 在 session 中注入 group 信息
            session = self._load_session(start_resp.session_id)
            if session is not None:
                session["session_group_id"] = session_group_id
                session["chunk_index"] = idx
                session["distillation_goal"] = distillation_goal
                session["target_agent_id"] = target_agent_id
                self._save_session(session)
                self._sessions_cache[start_resp.session_id] = session

            sessions.append(
                {
                    "session_id": start_resp.session_id,
                    "chunk_index": idx,
                    "initial_state": start_resp.initial_state,
                    "preread_summary": start_resp.preread_summary,
                }
            )

        return {
            "session_group_id": session_group_id,
            "sessions": sessions,
            "total_chunks": len(chunks),
            "distillation_goal": distillation_goal,
        }

    async def get_group_status(self, group_id: str) -> Dict[str, Any]:
        """查询批量切分组状态。

        Args:
            group_id: 会话组 ID

        Returns:
            dict: group_id + sessions 状态数组 + completed_count + total_count

        Raises:
            KeyError: group_id 不存在（404）
        """
        sessions_in_group = []
        for sid, session in self._sessions_cache.items():
            if session.get("session_group_id") == group_id:
                sessions_in_group.append(session)

        if not sessions_in_group:
            raise KeyError(f"session_group_id 不存在（404）: {group_id}")

        sessions_in_group.sort(key=lambda s: s.get("chunk_index", 0))
        completed = sum(1 for s in sessions_in_group if s.get("is_finalized"))

        return {
            "session_group_id": group_id,
            "total_count": len(sessions_in_group),
            "completed_count": completed,
            "sessions": [
                {
                    "session_id": s["session_id"],
                    "chunk_index": s.get("chunk_index", 0),
                    "state": s["state"],
                    "is_finalized": s.get("is_finalized", False),
                    "quality_score": s.get("quality_score"),
                    "extracted_content": s.get("extracted_content"),
                }
                for s in sessions_in_group
            ],
        }

    async def finalize_with_agent_creation(
        self,
        session_id: str,
        override_decision: Optional[str] = None,
    ) -> Dict[str, Any]:
        """终结蒸馏会话并从抽取内容创建角色卡 Agent。

        RADIX 批量蒸馏 agent 创建路径（batch_routes.py::finalize_with_agent_creation 调用）：
            1. 先调用 finalize_distillation 完成存储决策（可能 S_REJECT）
            2. 若存储成功且会话目标含 agent 创建，从 extracted_content 构建标准
               Agent 配置并写入 data/agents.json（扁平 list，与 agents.py 一致）
            3. 返回 finalize 响应 + agent_creation_result

        Args:
            session_id: 会话 ID
            override_decision: 人类覆盖决策（非 None 时覆盖 agent 决策）

        Returns:
            dict: finalize 响应字段 + agent_creation_result

        Raises:
            KeyError: session_id 不存在（404）
            ValueError: 会话已终结（409）
        """
        finalize_resp = await self.finalize_distillation(
            session_id=session_id,
            override_decision=override_decision,
        )
        base = finalize_resp.model_dump()

        session = self._load_session(session_id)
        goal = (session or {}).get("distillation_goal", "memory")
        wants_agent = goal in ("agent", "memory_and_agent")

        if not finalize_resp.stored or not wants_agent:
            base["agent_creation_result"] = {
                "status": "skipped",
                "reason": "未存储或该会话目标不包含 agent 创建",
            }
            return base

        try:
            agent = self._create_agent_from_session(session)
            base["agent_creation_result"] = {
                "status": "created",
                "agent_id": agent["id"],
                "name": agent["name"],
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("finalize_with_agent_creation agent 创建失败: %s", exc)
            base["agent_creation_result"] = {
                "status": "error",
                "error": str(exc),
            }
        return base

    def _create_agent_from_session(self, session: Dict[str, Any]) -> Dict[str, Any]:
        """从蒸馏会话抽取内容构建并写入标准 Agent 配置（best-effort）。

        写入格式与 server/api/routers/agents.py 一致（扁平 list），
        供前端 AgentsPage / ACP agent 管理读取。agent 创建失败不应阻断
        finalize 结果，故由调用方捕获。

        Args:
            session: 蒸馏会话字典（含 extracted_content）

        Returns:
            dict: 写入的标准 Agent 配置

        Raises:
            OSError / json.JSONDecodeError: agents.json 读写失败（由调用方捕获）
        """
        import uuid

        extracted = (session.get("extracted_content") or "").strip()
        name_line = ""
        for line in extracted.splitlines():
            stripped = line.strip().lstrip("-#* ")
            if stripped:
                name_line = stripped
                break
        name = (name_line or "蒸馏角色")[:40]
        description = extracted[:200] or ""
        system_prompt = (
            f"你是角色「{name}」。以下是该角色的设定与记忆蒸馏内容，请据此扮演：\n"
            f"{extracted}"
        )

        agents_path = os.path.join(_PROJECT_ROOT, "data", "agents.json")
        agents: List[Dict[str, Any]] = []
        if os.path.exists(agents_path):
            try:
                with open(agents_path, "r", encoding="utf-8") as fh:
                    loaded = json.load(fh)
                if isinstance(loaded, list):
                    agents = loaded
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("agents.json 读取失败（%s），将重建", exc)

        now = _iso_now()
        agent: Dict[str, Any] = {
            "id": f"agent-{uuid.uuid4().hex[:8]}",
            "name": name,
            "description": description,
            "system_prompt": system_prompt,
            "model": "main",
            "temperature": 0.7,
            "max_tokens": 131072,
            "use_memory": True,
            "use_tools": True,
            "memory_scene": "chat",
            "decay_model": "exponential",
            "vision_enabled": False,
            "is_default": False,
            "created_at": now,
            "updated_at": now,
        }
        agents.append(agent)
        _ensure_dir(os.path.dirname(agents_path))
        with open(agents_path, "w", encoding="utf-8") as fh:
            json.dump(agents, fh, ensure_ascii=False, indent=2)
        return agent

    # ------------------------------------------------------------------ #
    # 内部方法（严格匹配 .pyi 签名）
    # ------------------------------------------------------------------ #

    def _transition_state(self, current_state: str, agent_action: str) -> str:
        """内部方法：状态机转移。

        Args:
            current_state: 当前状态
            agent_action: agent 动作

        Returns:
            下一个状态

        Raises:
            ValueError: 非法状态转移
        """
        if current_state not in _STATES:
            raise ValueError(f"非法状态（422）: {current_state}")
        if agent_action not in _AGENT_ACTIONS:
            raise ValueError(f"非法 agent_action（422）: {agent_action}")

        transitions = _TRANSITIONS.get(current_state, {})
        next_state = transitions.get(agent_action)
        if next_state is None:
            raise ValueError(
                f"非法状态转移（409）: {current_state} + {agent_action}"
            )
        return next_state

    # ------------------------------------------------------------------ #
    # 私有辅助方法（非 .pyi 范围，内部使用）
    # ------------------------------------------------------------------ #

    def _resolve_path(self, configured: str) -> str:
        """将配置中的相对路径解析为绝对路径。

        Args:
            configured: 配置中的路径（相对或绝对）

        Returns:
            绝对路径
        """
        if os.path.isabs(configured):
            return configured
        return os.path.join(_PROJECT_ROOT, configured.replace("/", os.sep))

    def _build_default_rubric(self) -> Dict[str, Any]:
        """构建默认 rubric 字典。"""
        cfg = self._decision_core_config
        return {
            "importance_threshold_permanent": cfg.get(
                "importance_threshold_permanent", 0.7
            ),
            "quality_reject_threshold": cfg.get("quality_reject_threshold", 0.3),
            "max_redistill_turns": cfg.get("max_redistill_turns", 2),
            "ask_user_confidence_threshold": cfg.get(
                "ask_user_confidence_threshold", 0.4
            ),
            "cross_validate_sources": cfg.get("cross_validate_sources", []),
        }

    def _build_rubric_snapshot(self) -> Any:
        """构造 RubricSnapshot 实例（供 DecisionCore 使用）。

        若 RubricSnapshot 类不可用（B4 导入失败），返回 rubric dict（降级路径）。

        Returns:
            RubricSnapshot 实例，或 rubric dict（降级）
        """
        if self._rubric_cls is not None:
            try:
                return self._rubric_cls(
                    importance_threshold_permanent=self._rubric[
                        "importance_threshold_permanent"
                    ],
                    quality_reject_threshold=self._rubric["quality_reject_threshold"],
                    max_redistill_turns=self._rubric["max_redistill_turns"],
                    ask_user_confidence_threshold=self._rubric[
                        "ask_user_confidence_threshold"
                    ],
                    cross_validate_sources=list(
                        self._rubric.get("cross_validate_sources", [])
                    ),
                )
            except Exception as e:  # noqa: BLE001
                logger.debug("RubricSnapshot 构造失败（%s），降级到 dict", e)
        return dict(self._rubric)

    def _build_decision_input(
        self, session: Dict[str, Any], quality_score: Optional[float]
    ) -> Any:
        """构造 DecisionInput 实例（供 DecisionCore 使用）。

        若 DecisionInput 类不可用，返回 dict（降级路径）。

        Args:
            session: 会话状态字典
            quality_score: 质量评分

        Returns:
            DecisionInput 实例，或 dict（降级）
        """
        if self._decision_input_cls is not None:
            try:
                return self._decision_input_cls(
                    artifact_summary=session.get("preread_summary"),
                    session_state=session["state"],
                    turn_history_summary=str(
                        [t.get("agent_action") for t in session.get("turns", [])]
                    ),
                    extracted_content=session.get("extracted_content"),
                    quality_score=quality_score,
                )
            except Exception as e:  # noqa: BLE001
                logger.debug("DecisionInput 构造失败（%s），降级到 dict", e)
        return {
            "artifact_summary": session.get("preread_summary"),
            "session_state": session["state"],
            "turn_history_summary": str(
                [t.get("agent_action") for t in session.get("turns", [])]
            ),
            "extracted_content": session.get("extracted_content"),
            "quality_score": quality_score,
        }

    # ------------------------------------------------------------------ #
    # DecisionCore 6 决策点接入（D3/D4/D5 在 advance，D1/D2/D6 在 finalize）
    # ------------------------------------------------------------------ #

    def _invoke_d3_ask_user(
        self, session_id: str, rubric: Any
    ) -> bool:
        """D3_ASK_USER 决策：是否追问人类。

        best-effort：DecisionCore 不可用时回退到 ask_user_on_ambiguity 标志。

        Args:
            session_id: 会话 ID
            rubric: RubricSnapshot 实例或 dict

        Returns:
            是否需要追问
        """
        if self._decision_core is None:
            return True  # 降级：默认允许追问

        try:
            # 简化：confidence 从 MultimodalPipeline artifact 读取（若可用），
            # 此处用固定值 0.5（中等置信度）触发 D3 判定
            llm_confidence = 0.5
            return bool(
                self._decision_core.decide_ask_user(
                    session_id=session_id,
                    llm_confidence=llm_confidence,
                    rubric=rubric,
                )
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "D3 decide_ask_user 调用失败（%s），降级到 True（允许追问）", e
            )
            return True

    def _invoke_d4_redistill(
        self,
        session_id: str,
        current_turn: int,
        rubric: Any,
    ) -> bool:
        """D4_REDISTILL 决策：是否回环至 S_QUESTION。

        best-effort：DecisionCore 不可用时回退到内置 rubric 判定。

        Args:
            session_id: 会话 ID
            current_turn: 当前回环次数
            rubric: RubricSnapshot 实例或 dict

        Returns:
            是否需要回环
        """
        if self._decision_core is None:
            # 降级：内置 rubric 判定
            max_redistill = self._rubric.get("max_redistill_turns", 2)
            return current_turn < max_redistill

        try:
            return bool(
                self._decision_core.decide_redistill(
                    session_id=session_id,
                    current_turn=current_turn,
                    rubric=rubric,
                )
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "D4 decide_redistill 调用失败（%s），降级到内置 rubric 判定", e
            )
            max_redistill = self._rubric.get("max_redistill_turns", 2)
            return current_turn < max_redistill

    def _invoke_d5_cross_validate(
        self,
        session_id: str,
        decision_input: Any,
        rubric: Any,
    ) -> bool:
        """D5_CROSS_VALIDATE 决策：是否跨源验证。

        best-effort：DecisionCore 不可用时回退到内置 rubric 判定。

        Args:
            session_id: 会话 ID
            decision_input: DecisionInput 实例或 dict
            rubric: RubricSnapshot 实例或 dict

        Returns:
            是否需要跨源验证
        """
        if self._decision_core is None:
            # 降级：内置 rubric 判定
            cross_sources = self._rubric.get("cross_validate_sources", [])
            return bool(cross_sources) and bool(
                decision_input.get("extracted_content")
                if isinstance(decision_input, dict)
                else getattr(decision_input, "extracted_content", None)
            )

        try:
            return bool(
                self._decision_core.decide_cross_validate(
                    session_id=session_id,
                    decision_input=decision_input,
                    rubric=rubric,
                )
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "D5 decide_cross_validate 调用失败（%s），降级到内置 rubric 判定", e
            )
            cross_sources = self._rubric.get("cross_validate_sources", [])
            return bool(cross_sources)

    def _invoke_decision_core(
        self,
        session: Dict[str, Any],
        quality_score: float,
        override_decision: Optional[str],
    ) -> Tuple[str, Optional[int], Dict[str, Any], str]:
        """调用 DecisionCore 执行 D1/D2/D6 决策（S_STORAGE_DECISION → S_FINALIZE）。

        DecisionCore 调用顺序:
            1. 人类 override 优先（permanent / reject）
            2. D6_REJECT 优先判定（quality_score < threshold）
            3. D1_LOCATION 位置决策 + D2_METADATA 元数据决策

        best-effort：DecisionCore 调用失败时降级到内置规则决策。

        Args:
            session: 会话状态字典
            quality_score: 质量评分
            override_decision: 人类覆盖决策

        Returns:
            (location, memory_id, metadata, reason) 元组
        """
        session_id = session["session_id"]

        # 1. 人类覆盖决策优先
        if override_decision == "permanent":
            location = "permanent_memories"
            memory_id = self._alloc_memory_id()
            metadata = self._build_metadata(session, "permanent")
            reason = "[DistillationService] 人类 override=permanent，存入永久记忆"
            self._write_decision_log(
                session_id=session_id,
                decision_point="D1_LOCATION",
                decision_input=None,
                rubric=None,
                final_action="store",
                final_location=location,
                final_details={
                    "memory_id": memory_id,
                    "quality_score": quality_score,
                    "override_decision": override_decision,
                },
            )
            return location, memory_id, metadata, reason
        if override_decision == "reject":
            location = "rejected"
            metadata = {"retention_days": 30, "quality_score": quality_score}
            reason = "[DistillationService] 人类 override=reject，拒绝存储"
            self._write_decision_log(
                session_id=session_id,
                decision_point="D6_REJECT",
                decision_input=None,
                rubric=None,
                final_action="reject",
                final_location=location,
                final_details={
                    "quality_score": quality_score,
                    "override_decision": override_decision,
                },
            )
            return location, None, metadata, reason

        # 2. DecisionCore 调用（best-effort）
        if self._decision_core is None or self._rubric_cls is None:
            return self._fallback_decision(
                session, quality_score, override_decision,
                "DecisionCore 不可用",
            )

        try:
            rubric = self._build_rubric_snapshot()
            decision_input = self._build_decision_input(session, quality_score)

            # D6 拒绝优先判定
            if quality_score < self._rubric["quality_reject_threshold"]:
                decision = self._decision_core.decide_reject(
                    session_id=session_id,
                    quality_score=quality_score,
                    rubric=rubric,
                )
                location = "rejected"
                memory_id: Optional[int] = None
                metadata = dict(decision.metadata) if hasattr(decision, "metadata") else {}
                metadata["retention_days"] = 30
                reason = decision.reason if hasattr(decision, "reason") else "D6 拒绝存储"
            else:
                # D1 位置决策
                decision = self._decision_core.decide_location(
                    session_id=session_id,
                    decision_input=decision_input,
                    rubric=rubric,
                )
                location = decision.location
                memory_id = decision.memory_id
                metadata = dict(decision.metadata) if hasattr(decision, "metadata") else {}
                reason = decision.reason if hasattr(decision, "reason") else "D1 位置决策"

                # D2 元数据决策（补充 metadata）
                try:
                    d2_metadata = self._decision_core.decide_metadata(
                        session_id=session_id,
                        decision_input=decision_input,
                    )
                    if isinstance(d2_metadata, dict):
                        # D2 字段优先（time/importance/source/tags），保留 D1 的 session_id/quality_score
                        for k in ("time", "importance", "source", "tags"):
                            if k in d2_metadata:
                                metadata[k] = d2_metadata[k]
                except Exception as e:  # noqa: BLE001
                    logger.warning(
                        "D2 decide_metadata 调用失败（%s），使用 D1 metadata", e
                    )

            # 写入决策审计日志（best-effort，不阻断主流程）
            self._write_decision_log(
                session_id=session_id,
                decision_point="D1_LOCATION" if location != "rejected" else "D6_REJECT",
                decision_input=decision_input,
                rubric=rubric,
                final_action="reject" if location == "rejected" else "store",
                final_location=location,
                final_details={
                    "memory_id": memory_id,
                    "quality_score": quality_score,
                    "override_decision": override_decision,
                },
            )

            return location, memory_id, metadata, reason

        except Exception as exc:  # noqa: BLE001
            # 降级到内置规则决策
            return self._fallback_decision(
                session, quality_score, override_decision, str(exc)
            )

    def _fallback_decision(
        self,
        session: Dict[str, Any],
        quality_score: float,
        override_decision: Optional[str],
        error_msg: str,
    ) -> Tuple[str, Optional[int], Dict[str, Any], str]:
        """DecisionCore 不可用时的降级决策。

        Args:
            session: 会话状态字典
            quality_score: 质量评分
            override_decision: 人类覆盖决策
            error_msg: 错误信息

        Returns:
            (location, memory_id, metadata, reason) 元组
        """
        if quality_score < self._rubric["quality_reject_threshold"]:
            return (
                "rejected",
                None,
                {
                    "retention_days": 30,
                    "quality_score": quality_score,
                    "fallback_reason": error_msg,
                },
                f"[DistillationService] 降级决策-拒绝: quality_score={quality_score} < "
                f"threshold={self._rubric['quality_reject_threshold']}",
            )
        # 简化：importance 固定 0.75，与 rubric 阈值比较
        importance = 0.75
        if importance >= self._rubric["importance_threshold_permanent"]:
            location = "permanent_memories"
            reason = (
                f"[DistillationService] 降级决策-永久记忆: importance={importance} >= "
                f"threshold={self._rubric['importance_threshold_permanent']}"
            )
        else:
            location = "memories"
            reason = (
                f"[DistillationService] 降级决策-临时记忆: importance={importance} < "
                f"threshold={self._rubric['importance_threshold_permanent']}"
            )
        return (
            location,
            self._alloc_memory_id(),
            self._build_metadata(session, location),
            reason,
        )

    # ------------------------------------------------------------------ #
    # MultimodalPipeline 接入（S_PREREAD 状态）
    # ------------------------------------------------------------------ #

    async def _run_preread(
        self,
        source_type: str,
        source_ref: Optional[str],
        template_id: str,
    ) -> Tuple[str, List[str]]:
        """执行 S_PREREAD 阶段：调用 MultimodalPipeline.preprocess（B2 接入点）。

        CX-O 扩展：5 模态统一入口，conversation_log 映射到 text 模态。
        video/audio 走 vLLM 原生解码（B2 已实现）。

        Args:
            source_type: 数据源类型
            source_ref: 数据源引用
            template_id: 关联模板 ID

        Returns:
            (preread_summary, ambiguity_questions) 元组

        Raises:
            RuntimeError: MultimodalPipeline 预处理失败
            ConnectionError: MultimodalPipeline 不可用
        """
        artifact_summary = ""
        try:
            if self._multimodal_pipeline is not None:
                # conversation_log 类型映射到 text 模态（MultimodalPipeline 不支持 conversation_log）
                mp_source_type = (
                    "text" if source_type == "conversation_log" else source_type
                )
                ref = source_ref if source_ref else ""
                try:
                    artifact = self._multimodal_pipeline.preprocess(
                        source_type=mp_source_type,
                        source_ref=ref,
                    )
                    # 提取摘要（前 500 字符）
                    text_content = getattr(artifact, "text_content", "")
                    artifact_type = getattr(artifact, "type", mp_source_type)
                    native_decode_used = getattr(artifact, "native_decode_used", False)
                    vision_degraded = getattr(artifact, "vision_degraded", False)
                    artifact_summary = (
                        f"[MultimodalArtifact type={artifact_type} "
                        f"native_decode={native_decode_used} "
                        f"vision_degraded={vision_degraded}] "
                        f"{text_content[:500]}"
                    )
                except (ValueError, FileNotFoundError, RuntimeError, ConnectionError) as e:
                    # best-effort：预处理失败时降级到占位摘要
                    logger.warning(
                        "MultimodalPipeline preprocess 降级 (source_type=%s): %s",
                        source_type, e,
                    )
                    artifact_summary = (
                        f"[DistillationService] MultimodalPipeline 预处理降级: "
                        f"source_type={source_type}, source_ref={source_ref}, error={e}"
                    )
            else:
                artifact_summary = (
                    f"[DistillationService] MultimodalPipeline 不可用，"
                    f"使用占位摘要: source_type={source_type}"
                )
        except Exception as exc:
            raise RuntimeError(
                f"MultimodalPipeline 预处理失败（500）: {exc}"
            ) from exc

        # 生成预读摘要（结合 artifact 摘要）
        preread_summary = (
            f"[S_PREREAD] 数据源类型={source_type}, 模板={template_id}。\n"
            f"预读摘要: {artifact_summary}"
        )

        # 疑点清单（根据 source_type 推断）
        ambiguity_questions: List[str] = []
        if source_type == "text":
            ambiguity_questions = [
                "1. 文本中的关键实体是否需要归一化？",
                "2. 时间戳是否需要转换为 UTC？",
            ]
        elif source_type == "character_card":
            ambiguity_questions = [
                "1. 角色卡字段映射是否完整？",
                "2. 角色描述是否需要分块存储？",
            ]
        elif source_type == "image":
            ambiguity_questions = [
                "1. OCR 文本块的置信度阈值是多少？",
                "2. 视觉描述是否需要单独存储？",
            ]
        elif source_type == "video":
            ambiguity_questions = [
                "1. 视频关键帧抽取的时间间隔是多少？",
                "2. 视频转录文本是否需要分句存储？",
            ]
        elif source_type == "audio":
            ambiguity_questions = [
                "1. 音频转录的语种是否需要标注？",
                "2. 说话人分离是否需要启用？",
            ]
        elif source_type == "conversation_log":
            ambiguity_questions = [
                "1. 对话角色如何区分？",
                "2. 是否需要提取情感倾向？",
            ]

        return preread_summary, ambiguity_questions

    # ------------------------------------------------------------------ #
    # 其他私有辅助方法
    # ------------------------------------------------------------------ #

    def _count_redistill_turns(self, session: Dict[str, Any]) -> int:
        """统计已发生的回环次数（S_REFLECT → S_QUESTION）。"""
        count = 0
        for turn in session.get("turns", []):
            if (
                turn.get("state") == "S_QUESTION"
                and turn.get("agent_action") == "reflect"
            ):
                count += 1
        return count

    def _extract_content(self, session: Dict[str, Any]) -> str:
        """抽取结构化内容（S_EXTRACT 阶段）。"""
        preread = session.get("preread_summary") or ""
        extracted = (
            "[S_EXTRACT] 结构化抽取结果:\n"
            f"- source_type: {session['source_type']}\n"
            f"- template_id: {session['template_id']}\n"
            f"- preread_summary: {preread[:300]}\n"
            f"- turns_count: {len(session.get('turns', []))}\n"
        )
        return extracted

    def _estimate_quality_score(self, session: Dict[str, Any]) -> float:
        """估算质量评分（S_STORAGE_DECISION 阶段）。

        OBS-6 方案 C：LLM 质量评估重构。
        - self._quality_llm_enabled=True 时优先调用 LLM 评估真实质量
        - LLM 调用失败/超时/返回无效时回退启发式（基础分 0.4，使自然 S_REJECT 可达）
        - self._quality_llm_enabled=False 时直接走启发式（基础分 0.4）

        启发式基础分从 0.6 降为 0.4，使 quality_score 范围 (0.4~0.8) 与
        quality_reject_threshold (默认 0.3) 形成边界，低质内容可自然触发 S_REJECT。
        """
        if self._quality_llm_enabled:
            try:
                score = self._llm_estimate_quality_score(session)
                # 范围校验（LLM 返回值兜底）
                if score is not None and 0.0 <= score <= 1.0:
                    return float(score)
                logger.warning(
                    "LLM 质量评估返回值超范围或为 None（%s），回退启发式", score
                )
            except ConnectionError as e:
                # LLM 不可用是合法降级路径，不阻断主流程
                logger.info("LLM 质量评估不可用（%s），回退启发式评分", e)
            except Exception as e:  # noqa: BLE001
                # 其他异常也走回退（rules-0 §三 async fallback：try-except）
                logger.warning("LLM 质量评估异常（%s），回退启发式评分", e)

        # 启发式回退：基础分 0.4（OBS-6 方案 C：从 0.6 降为 0.4，使自然 S_REJECT 可达）
        turns_count = len(session.get("turns", []))
        preread_len = len(session.get("preread_summary") or "")
        # 基础分 0.4，turns 多则加分，preread 长则加分
        score = 0.4 + min(turns_count * 0.05, 0.2) + min(preread_len / 1000, 0.2)
        return float(min(max(score, 0.0), 1.0))

    def _llm_estimate_quality_score(self, session: Dict[str, Any]) -> Optional[float]:
        """LLM 质量评估（OBS-6 方案 C 核心方法）。

        调用 vLLM /v1/chat/completions 端点，让 LLM 基于会话内容评估质量评分。
        调用模式参考 decision_core.py _llm_decide：requests.post + OpenAI 兼容负载。

        Args:
            session: 蒸馏会话字典

        Returns:
            Optional[float]: 质量评分 0.0~1.0，解析失败返回 None（由调用方回退）

        Raises:
            ConnectionError: LLM 服务不可用（触发调用方回退启发式）
        """
        # 解析模型名：配置为空时从 server.config llm 段继承
        model_name = self._quality_llm_model
        if not model_name:
            try:
                from server.config import get_settings  # type: ignore

                settings = get_settings()
                unified = getattr(settings, "config", None)
                if unified is not None:
                    llm_cfg = getattr(unified, "llm", None)
                    if llm_cfg is not None:
                        # 优先 model 字段，其次 models.default
                        model_name = (
                            getattr(llm_cfg, "model", None)
                            or getattr(llm_cfg, "default_model", None)
                            or ""
                        )
            except Exception as e:  # noqa: BLE001
                logger.debug("server.config llm 段不可用（%s），model 名降级", e)

        if not model_name:
            # 最终兜底：使用 vLLM 部署的实际模型名（与 asr_llm_tts_latency 一致）
            model_name = "gemma4-e4b"

        # 构造 prompt 输入
        preread = session.get("preread_summary") or ""
        turns = session.get("turns", [])
        turns_summary = "; ".join(
            f"[{t.get('state', '?')}] {t.get('agent_output', '')[:80]}"
            for t in turns[:6]  # 最多取前 6 轮，避免 prompt 过长
        )[:800]
        extracted = session.get("extracted_content") or ""

        prompt = QUALITY_ESTIMATE_PROMPT.format(
            source_type=session.get("source_type", ""),
            template_id=session.get("template_id", ""),
            preread_summary=preread[:1000],
            turns_count=len(turns),
            turns_summary=turns_summary,
            extracted_content=extracted[:500],
        )

        url = f"{self._vllm_base_url}/v1/chat/completions"
        payload = {
            "model": model_name,
            "messages": [
                {
                    "role": "system",
                    "content": "你是 RADIX-Lite 蒸馏服务质量评估器，严格输出 JSON。",
                },
                {"role": "user", "content": prompt},
            ],
            "max_tokens": 256,
            "temperature": 0.2,  # 低温保证评分稳定性
        }

        # 同步 HTTP（rules-0 §三 async 禁止子线程 asyncio+aiohttp）
        import requests  # type: ignore[import-untyped]

        try:
            resp = requests.post(
                url, json=payload, timeout=self._quality_llm_timeout
            )
            if resp.status_code != 200:
                raise ConnectionError(
                    f"vLLM 返回 {resp.status_code}: {resp.text[:200]}"
                )
            data = resp.json()
            content = (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                .strip()
            )
            if not content:
                raise ConnectionError("vLLM 返回空 content")

            # 解析 JSON（容忍 markdown 代码块包裹）
            content_clean = content
            if content_clean.startswith("```"):
                # 剥离 ```json ... ``` 包裹
                lines = content_clean.split("\n")
                content_clean = "\n".join(
                    line for line in lines
                    if not line.strip().startswith("```")
                ).strip()

            parsed = json.loads(content_clean)
            score = parsed.get("quality_score")
            if score is None:
                raise ConnectionError(f"LLM 响应缺少 quality_score 字段: {content[:200]}")
            return float(score)
        except (ConnectionError,) as e:
            raise e
        except (requests.RequestException, json.JSONDecodeError, ValueError, TypeError, KeyError) as e:
            raise ConnectionError(f"LLM 质量评估调用/解析失败: {e}") from e

    def _alloc_memory_id(self) -> int:
        """分配 memory_id（简化：基于时间戳的递增序列）。"""
        return int(datetime.now(timezone.utc).timestamp() * 1000) % 1000000 + 1

    def _build_metadata(
        self, session: Dict[str, Any], location: str
    ) -> Dict[str, Any]:
        """构建记忆元数据。"""
        return {
            "time": _iso_now(),
            "importance": 0.75,
            "source": session["source_type"],
            "tags": ["radix", "distillation", session["template_id"], location],
            "session_id": session["session_id"],
            "quality_score": session.get("quality_score"),
        }

    def _write_decision_log(
        self,
        session_id: str,
        decision_point: str,
        decision_input: Any,
        rubric: Any,
        final_action: str,
        final_location: Optional[str],
        final_details: Dict[str, Any],
    ) -> None:
        """写入决策审计日志到 data/distillation_logs/{session_id}.json。

        best-effort：写入失败不阻断主流程。
        日志结构符合 distillation_log.schema.json。
        """
        try:
            log_path = os.path.join(self._log_dir, f"{session_id}.json")
            # 读取已有日志（追加模式）
            existing: List[Dict[str, Any]] = []
            if os.path.exists(log_path):
                try:
                    with open(log_path, "r", encoding="utf-8") as fh:
                        existing = json.load(fh)
                        if not isinstance(existing, list):
                            existing = []
                except (json.JSONDecodeError, OSError):
                    existing = []

            # 构造日志条目（符合 distillation_log.schema.json）
            log_entry = {
                "log_id": _new_uuid(),
                "session_id": session_id,
                "decision_point": decision_point,
                "input": (
                    decision_input.model_dump()
                    if hasattr(decision_input, "model_dump")
                    else {}
                ),
                "rubric_snapshot": (
                    rubric.model_dump()
                    if hasattr(rubric, "model_dump")
                    else dict(rubric) if isinstance(rubric, dict) else {}
                ),
                "llm_reasoning": None,
                "llm_confidence": None,
                "final_decision": {
                    "action": final_action,
                    "location": final_location,
                    "details": final_details,
                },
                "timestamp": _iso_now(),
            }
            existing.append(log_entry)

            # 原子写入（先写临时文件再重命名，避免半写损坏）
            tmp_path = log_path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as fh:
                json.dump(existing, fh, ensure_ascii=False, indent=2)
            os.replace(tmp_path, log_path)
        except (OSError, json.JSONDecodeError, ValueError, TypeError):
            # best-effort：写入失败不阻断主流程
            pass

    def _save_session(self, session: Dict[str, Any]) -> None:
        """持久化 session 到 data/distillation_sessions/{session_id}.json。

        原子写入：先写临时文件再重命名，避免半写损坏。

        Raises:
            RuntimeError: 持久化失败（500）
        """
        try:
            session_path = os.path.join(
                self._session_dir, f"{session['session_id']}.json"
            )
            tmp_path = session_path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as fh:
                json.dump(session, fh, ensure_ascii=False, indent=2)
            os.replace(tmp_path, session_path)
        except (OSError, ValueError, TypeError) as exc:
            raise RuntimeError(
                f"session 持久化失败（500）: {exc}"
            ) from exc

    def _load_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """从持久化层加载 session。

        优先从内存缓存读取，缓存未命中时从磁盘加载。
        """
        # 优先缓存
        if session_id in self._sessions_cache:
            return self._sessions_cache[session_id]

        # 从磁盘加载
        session_path = os.path.join(self._session_dir, f"{session_id}.json")
        if not os.path.exists(session_path):
            return None
        try:
            with open(session_path, "r", encoding="utf-8") as fh:
                session = json.load(fh)
            self._sessions_cache[session_id] = session
            return session
        except (json.JSONDecodeError, OSError):
            return None

    @staticmethod
    def _split_text_into_chunks(
        text: str, chunk_size: int
    ) -> List[str]:
        """将超长文本按 chunk_size 切分为多个片段（简化版）。

        切分策略：
        1. 估算 token 数（中文 2 字符/token，英文 4 字符/token，取加权平均 3 字符/token）
        2. 按 chunk_size 估算的字符数切分
        3. 优先在段落边界（\\n\\n）切分，其次 \\n，再次句号

        Args:
            text: 原始文本
            chunk_size: 每个片段的 token 上限

        Returns:
            List[str]: 切分后的片段列表
        """
        if not text:
            return []

        chars_per_token = 3
        target_chars = chunk_size * chars_per_token

        if len(text) <= target_chars:
            return [text]

        chunks = []
        remaining = text

        while remaining:
            if len(remaining) <= target_chars:
                chunks.append(remaining)
                break

            # 在 target_chars 附近寻找最佳切分点
            search_window = remaining[: target_chars + 200]
            split_pos = -1

            # 优先段落边界
            for sep in ["\n\n", "\n", "。", ".", "!", "?", "；", ";"]:
                pos = search_window.rfind(sep)
                if pos > target_chars * 0.5:
                    split_pos = pos + len(sep)
                    break

            if split_pos < 0:
                split_pos = target_chars

            chunks.append(remaining[:split_pos])
            remaining = remaining[split_pos:]

        return chunks
