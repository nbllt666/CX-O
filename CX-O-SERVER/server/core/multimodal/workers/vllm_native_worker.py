"""vLLM 原生视频/音频解码 worker（CX-O 扩展，v1.1.0 新增）。

逻辑与数据分离：本模块负责视频/音频模态的 vLLM 原生解码逻辑（通过 OpenAI
兼容 API 投递原生 video/audio 文件，由 vLLM 内部解码），不承载数据模型定义。
返回构造 MultimodalArtifact 所需的原料 dict（含 native_decode_used 字段）。

双场景策略（由 use_native 参数控制）:
    - use_native=True（provider=vllm 且 vllm_native_enabled=true）:
        通过 vLLM OpenAI 兼容 API 直接投递原生视频/音频文件，
        vLLM 内部解码后返回文本描述/转录。
        native_decode_used=True, vision_degraded=False, confidence=0.88。
    - use_native=False（provider!=vllm 或 vllm_native 被禁用 或端点不可达）:
        降级路径，返回占位文本 + 降级标记。
        native_decode_used=False, vision_degraded=True, confidence=0.5。

vLLM API 调用方式:
    - 端点: {vllm_base_url}/v1/chat/completions
    - 视频模态: content 包含 {"type": "video_url", "video_url": {"url": <data_url>}}
    - 音频模态: content 包含 {"type": "input_audio", "input_audio": {"data": <base64>, "format": <ext>}}
    - OpenAI 兼容响应: choices[0].message.content

对应契约:
    - public/interface_stub/multimodal_pipeline.pyi :: _vllm_native_worker
    - public/schema/multimodal_artifact.schema.json :: type=video/audio +
      native_decode_used 字段 + definitions.exceptions.ConnectionError_503

@version 1.1.0  # CX-O 扩展
"""

import base64
import logging
import os
from typing import Any, Dict

logger = logging.getLogger(__name__)


# 视频文件扩展名 → MIME 类型映射
_VIDEO_MIME_MAP = {
    "mp4": "video/mp4",
    "webm": "video/webm",
    "avi": "video/x-msvideo",
    "mov": "video/quicktime",
    "mkv": "video/x-matroska",
    "flv": "video/x-flv",
    "wmv": "video/x-ms-wmv",
}

# 音频文件扩展名 → 格式标识（用于 vLLM input_audio.format 字段）
_AUDIO_FORMAT_MAP = {
    "wav": "wav",
    "mp3": "mp3",
    "flac": "flac",
    "ogg": "ogg",
    "m4a": "mp4",
    "aac": "aac",
}


class VLLMNativeWorker:
    """vLLM 原生视频/音频解码 worker（CX-O 扩展）。

    处理流程:
        1. 校验 source_ref（文件路径，非空）+ modality（video/audio）
        2. 若 use_native=True:
            a. 读取文件 → base64 编码
            b. 构造 OpenAI 兼容 chat/completions 请求（含 multimodal content）
            c. POST 到 vLLM 端点
            d. 提取响应文本
        3. 若 use_native=False 或 vLLM 调用失败:
            返回降级路径原料 dict（native_decode_used=False, vision_degraded=True）

    降级策略:
        - vLLM 端点不可达（ConnectionError）→ 降级（不向外抛）
        - vLLM 推理失败（RuntimeError, HTTP 5xx）→ 降级
        - 文件不存在（FileNotFoundError）→ 降级路径仍返回占位文本（不阻断，
          因为非 vllm 场景下文件可能仅作记录用途；但若是 use_native=True 场景
          则向外抛 FileNotFoundError 让调用方处理）
    """

    def __init__(
        self,
        vllm_base_url: str = "http://127.0.0.1:8080",
        vllm_timeout_seconds: int = 300,
        task_timeout_seconds: int = 120,
    ) -> None:
        """初始化 vLLM 原生解码 worker。

        Args:
            vllm_base_url: vLLM 服务 URL（OpenAI 兼容）。CX-O 默认 8080。
            vllm_timeout_seconds: vLLM HTTP 调用超时（秒）。
            task_timeout_seconds: 单任务超时（秒），保留参数以与管线配置对齐。
        """
        self._vllm_base_url = vllm_base_url.rstrip("/")
        self._vllm_timeout = vllm_timeout_seconds
        self._timeout = task_timeout_seconds

    # ------------------------------------------------------------------ #
    # 公开方法
    # ------------------------------------------------------------------ #

    def process(
        self,
        source_ref: str,
        modality: str,
        use_native: bool,
        provider: str = "unknown",
    ) -> Dict[str, Any]:
        """执行 vLLM 原生视频/音频解码，返回 MultimodalArtifact 原料 dict。

        Args:
            source_ref: 视频或音频文件路径/URL
            modality: 模态类型（video/audio）
            use_native: 是否走原生路径（True=走 vLLM API，False=降级）
            provider: LLM provider 字符串（用于 extra_metadata 记录）

        Returns:
            dict 含字段: text_content / extra_metadata / confidence /
            vision_degraded / native_decode_used

        Raises:
            ValueError: modality 不在 video/audio 枚举中（422）
            FileNotFoundError: source_ref 为空 或 use_native=True 时文件不存在（404）
        """
        if modality not in ("video", "audio"):
            raise ValueError(
                f"modality 不在 video/audio 枚举中（422）: {modality}"
            )
        if not source_ref:
            raise FileNotFoundError("source_ref 不能为空（404）")

        if not use_native:
            # 降级路径：provider 非 vllm 或 vllm_native 被禁用
            return self._build_degraded_response(
                source_ref, modality, provider,
                degrade_reason=(
                    f"provider={provider} 非 vllm 或 vllm_native_enabled=false"
                ),
            )

        # 原生路径：尝试通过 vLLM API 投递
        try:
            text_content = self._call_vllm_native(source_ref, modality)
            return {
                "text_content": text_content,
                "extra_metadata": {
                    "modality": modality,
                    "vllm_provider": "vllm",
                    "decode_mode": "native",
                    "vllm_base_url": self._vllm_base_url,
                },
                "confidence": 0.88,
                "vision_degraded": False,
                "native_decode_used": True,
            }
        except FileNotFoundError:
            # 原生路径下文件不存在：向上抛（让调用方决定如何处理）
            raise
        except ConnectionError as e:
            # vLLM 端点不可达：降级
            logger.warning(
                "vLLM 原生 %s 解码端点不可达，降级路径: %s", modality, e
            )
            return self._build_degraded_response(
                source_ref, modality, provider,
                degrade_reason=f"vllm endpoint unreachable: {e}",
            )
        except RuntimeError as e:
            # vLLM 推理失败：降级
            logger.warning(
                "vLLM 原生 %s 解码推理失败，降级路径: %s", modality, e
            )
            return self._build_degraded_response(
                source_ref, modality, provider,
                degrade_reason=f"vllm inference failed: {e}",
            )
        except Exception as e:
            # 其他未预期异常：降级（不阻断管线）
            logger.warning(
                "vLLM 原生 %s 解码未知异常，降级路径: %s", modality, e
            )
            return self._build_degraded_response(
                source_ref, modality, provider,
                degrade_reason=f"unexpected error: {e}",
            )

    # ------------------------------------------------------------------ #
    # 内部方法：vLLM API 调用
    # ------------------------------------------------------------------ #

    def _call_vllm_native(self, source_ref: str, modality: str) -> str:
        """调用 vLLM OpenAI 兼容 API 投递原生视频/音频文件。

        Args:
            source_ref: 视频/音频文件路径
            modality: video/audio

        Returns:
            vLLM 返回的文本描述/转录

        Raises:
            FileNotFoundError: 文件不存在（404）
            ConnectionError: requests 未安装 / 连接失败（503）
            RuntimeError: HTTP 5xx / 推理失败 / 响应解析失败（500）
        """
        if not os.path.isfile(source_ref):
            raise FileNotFoundError(
                f"{modality} 文件不存在（404）: {source_ref}"
            )

        # 构造 OpenAI 兼容请求
        payload = self._build_payload(source_ref, modality)
        response = self._post_vllm_request(payload)
        return self._extract_response_text(response)

    def _build_payload(self, source_ref: str, modality: str) -> Dict[str, Any]:
        """构造 OpenAI 兼容 chat/completions 请求 payload。

        视频模态: content 包含 {"type": "video_url", "video_url": {"url": <data_url>}}
        音频模态: content 包含 {"type": "input_audio", "input_audio": {"data": <base64>, "format": <ext>}}

        Args:
            source_ref: 文件路径
            modality: video/audio

        Returns:
            OpenAI 兼容请求 payload dict

        Raises:
            RuntimeError: 文件读取失败 / 不支持的扩展名（500）
        """
        ext = os.path.splitext(source_ref)[1].lower().lstrip(".")

        try:
            with open(source_ref, "rb") as f:
                raw_bytes = f.read()
        except OSError as e:
            raise RuntimeError(
                f"读取 {modality} 文件失败（500）: {e}"
            ) from e

        b64_payload = base64.b64encode(raw_bytes).decode("ascii")

        if modality == "video":
            mime = _VIDEO_MIME_MAP.get(ext, "video/mp4")
            data_url = f"data:{mime};base64,{b64_payload}"
            prompt_text = "请分析这段视频的内容，包括场景、人物动作、对话和关键事件。"
            content = [
                {"type": "text", "text": prompt_text},
                {"type": "video_url", "video_url": {"url": data_url}},
            ]
        else:  # audio
            audio_format = _AUDIO_FORMAT_MAP.get(ext, "wav")
            prompt_text = "请转录这段音频的内容，并描述其中的关键信息。"
            content = [
                {"type": "text", "text": prompt_text},
                {
                    "type": "input_audio",
                    "input_audio": {
                        "data": b64_payload,
                        "format": audio_format,
                    },
                },
            ]

        return {
            "model": "vllm-native",  # vLLM 会根据实际部署的模型路由
            "messages": [{"role": "user", "content": content}],
            "max_tokens": 2048,
            "temperature": 0.3,
        }

    def _post_vllm_request(self, payload: Dict[str, Any]) -> Any:
        """POST vLLM 请求到端点。

        Raises:
            ConnectionError: requests 未安装 / 连接失败 / HTTP 4xx（503）
            RuntimeError: HTTP 5xx（500）
        """
        try:
            import requests  # type: ignore
        except ImportError as e:
            raise ConnectionError(
                "requests 未安装（503 VLLM_NATIVE_UNAVAILABLE），无法调用 vLLM。"
                "请运行: pip install requests。触发降级路径。"
            ) from e

        url = f"{self._vllm_base_url}/v1/chat/completions"
        try:
            response = requests.post(
                url,
                json=payload,
                timeout=self._vllm_timeout,
                headers={"Content-Type": "application/json"},
            )
        except requests.exceptions.ConnectionError as e:
            raise ConnectionError(
                f"vLLM 端点连接失败（503）: {url} - {e}。触发降级路径。"
            ) from e
        except requests.exceptions.Timeout as e:
            raise ConnectionError(
                f"vLLM 端点超时（503）: {url} - {e}。触发降级路径。"
            ) from e
        except Exception as e:
            raise ConnectionError(
                f"vLLM 调用异常（503）: {e}。触发降级路径。"
            ) from e

        if response.status_code >= 500:
            raise RuntimeError(
                f"vLLM 推理失败（500）: HTTP {response.status_code}"
            )
        if response.status_code >= 400:
            raise ConnectionError(
                f"vLLM 端点错误（503）: HTTP {response.status_code}。触发降级路径。"
            )
        return response

    @staticmethod
    def _extract_response_text(response: Any) -> str:
        """从 vLLM OpenAI 兼容响应提取文本。

        Raises:
            RuntimeError: 响应解析失败（500）
        """
        try:
            data = response.json()
        except Exception as e:
            raise RuntimeError(
                f"vLLM 响应 JSON 解析失败（500）: {e}"
            ) from e

        try:
            choices = data.get("choices") or []
            if not choices:
                raise RuntimeError("vLLM 响应无 choices（500）")
            message = choices[0].get("message") or {}
            content = message.get("content") or ""
            if isinstance(content, list):
                # 某些实现返回 content 为列表
                content = " ".join(
                    str(c.get("text", "")) if isinstance(c, dict) else str(c)
                    for c in content
                )
            return str(content).strip()
        except (KeyError, IndexError, TypeError) as e:
            raise RuntimeError(
                f"vLLM 响应结构异常（500）: {e}"
            ) from e

    # ------------------------------------------------------------------ #
    # 降级路径
    # ------------------------------------------------------------------ #

    @staticmethod
    def _build_degraded_response(
        source_ref: str,
        modality: str,
        provider: str,
        degrade_reason: str,
    ) -> Dict[str, Any]:
        """构造降级路径的原料 dict。

        Args:
            source_ref: 原始 source_ref
            modality: video/audio
            provider: LLM provider 字符串
            degrade_reason: 降级原因描述

        Returns:
            dict 含字段: text_content / extra_metadata / confidence /
            vision_degraded / native_decode_used
        """
        text_content = (
            f"[降级] {modality} 模态原生解码不可用（来源：{source_ref}）。"
            f"vLLM 原生解码未启用或端点不可达，返回占位文本。"
            f"降级原因：{degrade_reason}"
        )
        return {
            "text_content": text_content,
            "extra_metadata": {
                "modality": modality,
                "vllm_provider": provider,
                "decode_mode": "degraded",
                "degrade_reason": degrade_reason,
            },
            "confidence": 0.5,
            "vision_degraded": True,
            "native_decode_used": False,
        }
