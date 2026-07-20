"""图片模态 worker（双通道：PaddleOCR + vLLM vision）。

逻辑与数据分离：本模块负责图片预处理逻辑（OCR 文本识别 + vision 视觉描述），
不承载数据模型定义。返回构造 MultimodalArtifact 所需的原料 dict。

双通道策略:
    - PaddleOCR 通道：识别图片中的文本，产出 OCR 文本块（text + bbox）
    - vLLM vision 通道：调用 OpenAI 兼容 API 描述图片内容
    - vision 不可用时降级为仅 OCR（vision_degraded=True）

对应契约:
    - public/interface_stub/multimodal_pipeline.pyi :: _image_worker / _ocr_worker / _vision_worker / _merge_ocr_vision
    - public/schema/multimodal_artifact.schema.json :: type=image

@version 1.0.0
"""

import base64
import logging
import os
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)


class ImageWorker:
    """图片模态预处理 worker（双通道）。

    处理流程:
        1. _ocr_worker：PaddleOCR 识别文本块 → [{text, bbox}] + 记录平均置信度
        2. _vision_worker：HTTP 调用 vLLM vision 描述图片 → str
        3. merge：合并 OCR 文本 + vision 描述 → 原料 dict

    降级策略:
        - vision 不可用（ConnectionError）→ vision_degraded=True，仅返回 OCR
        - PaddleOCR 不可用 → RuntimeError（500 OCR_FAILED，不降级）

    Note:
        OCRBlock 接口契约（.pyi）仅含 text / bbox 字段，不含 confidence。
        本 worker 内部追踪 PaddleOCR 原始置信度（self._last_ocr_confidence），
        供 merge 计算 artifact.confidence，但不放入 OCRBlock（严格匹配 .pyi 签名）。
    """

    def __init__(
        self,
        vision_base_url: str = "http://127.0.0.1:8002",
        vision_model: str = "",
        ocr_language: str = "ch",
        task_timeout_seconds: int = 120,
        vision_timeout_seconds: int = 300,
    ) -> None:
        """初始化图片 worker。

        Args:
            vision_base_url: vLLM vision 服务 URL（OpenAI 兼容）。
            vision_model: vision 模型名。空字符串表示未配置 → vision 不可用。
            ocr_language: PaddleOCR 语言（ch/en/japan 等）。
            task_timeout_seconds: OCR 任务超时（秒）。
            vision_timeout_seconds: vision HTTP 调用超时（秒）。
        """
        self._vision_base_url = vision_base_url.rstrip("/")
        self._vision_model = vision_model
        self._ocr_language = ocr_language
        self._timeout = task_timeout_seconds
        self._vision_timeout = vision_timeout_seconds

        # PaddleOCR 实例懒加载（首次 ocr 调用时初始化，避免构造时即失败）
        self._paddleocr_instance: Any = None
        # 最近一次 OCR 的平均置信度（供 merge 使用）
        self._last_ocr_confidence: float = 0.9

    # ------------------------------------------------------------------ #
    # OCR 通道
    # ------------------------------------------------------------------ #

    def ocr(self, image_path: str) -> Tuple[List[Dict[str, Any]], float]:
        """PaddleOCR 识别图片文本。

        Args:
            image_path: 图片文件绝对路径

        Returns:
            (ocr_blocks, avg_confidence):
                ocr_blocks: List[{text, bbox}]，bbox=[x1,y1,x2,y2]
                avg_confidence: OCR 平均置信度（0-1）

        Raises:
            FileNotFoundError: 图片文件不存在（404）
            RuntimeError: PaddleOCR 引擎异常 / 图片解码失败（500 OCR_FAILED）
        """
        if not image_path:
            raise RuntimeError("image_path 不能为空（500 OCR_FAILED）")
        if not os.path.isfile(image_path):
            raise FileNotFoundError(f"图片文件不存在（404）: {image_path}")

        ocr_engine = self._get_paddleocr()
        raw_result = self._invoke_paddleocr(ocr_engine, image_path)

        blocks: List[Dict[str, Any]] = []
        confidences: List[float] = []

        for line in raw_result:
            parsed = self._parse_ocr_line(line)
            if parsed is not None:
                block, conf = parsed
                blocks.append(block)
                confidences.append(conf)

        # 排序：按 bbox 升序（先 y_top 升序，再 x_left 升序）—— 阅读顺序
        blocks.sort(key=lambda b: (b["bbox"][1], b["bbox"][0]))

        avg_conf = sum(confidences) / len(confidences) if confidences else 0.9
        self._last_ocr_confidence = avg_conf

        logger.info(
            "ocr 完成: blocks=%d, avg_confidence=%.3f", len(blocks), avg_conf
        )
        return blocks, avg_conf

    def _get_paddleocr(self) -> Any:
        """懒加载 PaddleOCR 实例。

        Raises:
            RuntimeError: PaddleOCR 未安装 / 初始化失败（500 OCR_FAILED）
        """
        if self._paddleocr_instance is not None:
            return self._paddleocr_instance

        try:
            from paddleocr import PaddleOCR  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                "PaddleOCR 未安装（500 OCR_FAILED），无法执行图片 OCR。"
                "请运行: pip install paddleocr paddlepaddle"
            ) from e

        try:
            # 兼容 PaddleOCR 2.x：use_angle_cls + lang
            try:
                self._paddleocr_instance = PaddleOCR(
                    use_angle_cls=True, lang=self._ocr_language, show_log=False
                )
            except TypeError:
                # 新版 PaddleOCR 可能移除 show_log 参数
                self._paddleocr_instance = PaddleOCR(
                    use_angle_cls=True, lang=self._ocr_language
                )
        except Exception as e:
            raise RuntimeError(
                f"PaddleOCR 初始化失败（500 OCR_FAILED）: {e}"
            ) from e

        return self._paddleocr_instance

    def _invoke_paddleocr(self, engine: Any, image_path: str) -> List[Any]:
        """调用 PaddleOCR.ocr 并返回原始行列表。

        兼容 PaddleOCR 不同版本返回结构:
            - 旧版: [[ [box, (text, confidence)], ... ]]
            - 新版: [[ {rec_txt, dt_scores, ...}, ... ]] 或类似

        Raises:
            RuntimeError: OCR 推理失败（500）
        """
        try:
            result = engine.ocr(image_path, cls=True)
        except Exception as e:
            raise RuntimeError(
                f"PaddleOCR 推理失败（500 OCR_FAILED）: {e}"
            ) from e

        # 标准化为行列表
        if not result:
            return []
        # result 通常为 [page] 或 [list_of_lines]
        first_page = result[0]
        if first_page is None:
            return []
        if isinstance(first_page, list):
            return first_page
        return [first_page]

    @staticmethod
    def _parse_ocr_line(line: Any) -> Tuple[Dict[str, Any], float]:
        """解析单行 OCR 结果为 {text, bbox} + confidence。

        兼容多种返回结构:
            - [box, (text, confidence)]
            - [box, text]  （无 confidence）

        Returns:
            (block_dict, confidence) 或 None（无法解析时）
        """
        try:
            if not isinstance(line, (list, tuple)) or len(line) < 2:
                return None
            box = line[0]
            text_info = line[1]

            # 解析 bbox: 4 点 → [x1, y1, x2, y2]
            bbox = ImageWorker._normalize_bbox(box)

            # 解析 text + confidence
            if isinstance(text_info, (list, tuple)):
                text = str(text_info[0]) if text_info else ""
                conf = float(text_info[1]) if len(text_info) > 1 else 0.9
            else:
                text = str(text_info)
                conf = 0.9

            if not text.strip():
                return None

            return {"text": text, "bbox": bbox}, conf
        except Exception:
            return None

    @staticmethod
    def _normalize_bbox(box: Any) -> List[float]:
        """将 PaddleOCR 的 4 点 bbox 转为 [x1, y1, x2, y2]。

        PaddleOCR box 格式: [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
        转换为: [min_x, min_y, max_x, max_y]

        Args:
            box: 4 点坐标列表

        Returns:
            [x1, y1, x2, y2] 矩形边界
        """
        try:
            xs = [float(p[0]) for p in box]
            ys = [float(p[1]) for p in box]
            return [min(xs), min(ys), max(xs), max(ys)]
        except Exception:
            return [0.0, 0.0, 0.0, 0.0]

    # ------------------------------------------------------------------ #
    # vision 通道
    # ------------------------------------------------------------------ #

    def vision(self, image_path: str) -> str:
        """调用 vLLM vision 模型描述图片内容。

        Args:
            image_path: 图片文件绝对路径

        Returns:
            视觉描述文本

        Raises:
            ConnectionError: vLLM vision 端点不可用 / 未配置（503）
            RuntimeError: vision 推理失败（500）
            FileNotFoundError: 图片不存在（404）
        """
        if not image_path:
            raise RuntimeError("image_path 不能为空（500）")
        if not os.path.isfile(image_path):
            raise FileNotFoundError(f"图片文件不存在（404）: {image_path}")

        if not self._vision_model:
            raise ConnectionError(
                "vLLM vision 未配置（503 VISION_FAILED）：vision_model 为空，"
                "触发降级路径（vision_degraded=true, OCR-only）"
            )

        # 构建 OpenAI 兼容 chat/completions 请求
        data_url = self._image_to_data_url(image_path)
        payload = {
            "model": self._vision_model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "请详细描述这张图片的内容，包括场景、对象、文字和布局。"},
                        {
                            "type": "image_url",
                            "image_url": {"url": data_url},
                        },
                    ],
                }
            ],
            "max_tokens": 1024,
            "temperature": 0.3,
        }

        response = self._post_vision_request(payload)
        return self._extract_vision_text(response)

    def _post_vision_request(self, payload: Dict[str, Any]) -> Any:
        """POST vision 请求到 vLLM 端点。

        Raises:
            ConnectionError: requests 未安装 / 连接失败（503）
            RuntimeError: HTTP 5xx / 推理失败（500）
        """
        try:
            import requests  # type: ignore
        except ImportError as e:
            raise ConnectionError(
                "requests 未安装（503 VISION_FAILED），无法调用 vLLM vision。"
                "请运行: pip install requests。触发降级路径。"
            ) from e

        url = f"{self._vision_base_url}/v1/chat/completions"
        try:
            response = requests.post(
                url,
                json=payload,
                timeout=self._vision_timeout,
                headers={"Content-Type": "application/json"},
            )
        except requests.exceptions.ConnectionError as e:
            raise ConnectionError(
                f"vLLM vision 端点连接失败（503 VISION_FAILED）: {url} - {e}。"
                "触发降级路径。"
            ) from e
        except requests.exceptions.Timeout as e:
            raise ConnectionError(
                f"vLLM vision 端点超时（503 VISION_FAILED）: {url} - {e}。"
                "触发降级路径。"
            ) from e
        except Exception as e:
            raise ConnectionError(
                f"vLLM vision 调用异常（503 VISION_FAILED）: {e}。触发降级路径。"
            ) from e

        if response.status_code >= 500:
            raise RuntimeError(
                f"vLLM vision 推理失败（500 INTERNAL_ERROR）: "
                f"HTTP {response.status_code}"
            )
        if response.status_code >= 400:
            raise ConnectionError(
                f"vLLM vision 端点错误（503 VISION_FAILED）: "
                f"HTTP {response.status_code}。触发降级路径。"
            )
        return response

    @staticmethod
    def _extract_vision_text(response: Any) -> str:
        """从 vLLM OpenAI 兼容响应提取文本。

        Raises:
            RuntimeError: 响应解析失败（500）
        """
        try:
            data = response.json()
        except Exception as e:
            raise RuntimeError(
                f"vision 响应 JSON 解析失败（500 INTERNAL_ERROR）: {e}"
            ) from e

        try:
            choices = data.get("choices") or []
            if not choices:
                raise RuntimeError(
                    "vision 响应无 choices（500 INTERNAL_ERROR）"
                )
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
                f"vision 响应结构异常（500 INTERNAL_ERROR）: {e}"
            ) from e

    @staticmethod
    def _image_to_data_url(image_path: str) -> str:
        """将图片转为 base64 data URL。

        Args:
            image_path: 图片文件路径

        Returns:
            data:image/<ext>;base64,<payload>
        """
        ext = os.path.splitext(image_path)[1].lower().lstrip(".")
        mime_map = {
            "jpg": "jpeg",
            "jpeg": "jpeg",
            "png": "png",
            "gif": "gif",
            "webp": "webp",
            "bmp": "bmp",
        }
        mime_sub = mime_map.get(ext, "jpeg")
        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
        return f"data:image/{mime_sub};base64,{b64}"

    # ------------------------------------------------------------------ #
    # merge 通道
    # ------------------------------------------------------------------ #

    def merge(
        self,
        ocr_blocks: List[Dict[str, Any]],
        vision_description: str,
    ) -> Dict[str, Any]:
        """合并 OCR 文本块 + vision 描述为 MultimodalArtifact 原料 dict。

        置信度策略（任务要求 confidence = min(ocr_confidence, 0.9)）:
            - vision 描述不贡献 confidence
            - ocr_confidence 取最近一次 OCR 平均置信度（self._last_ocr_confidence）
            - 若 OCR 不可得，默认 0.9
            - 降级（vision 为空）时 confidence 进一步降至 0.7

        Args:
            ocr_blocks: OCR 文本块列表 [{text, bbox}]
            vision_description: vision 描述文本（降级时为空串）

        Returns:
            dict 含字段: text_content / extra_metadata / confidence / vision_degraded
        """
        ocr_text = "\n".join(b.get("text", "") for b in ocr_blocks)

        has_vision = bool(vision_description)
        if has_vision:
            text_content = f"{ocr_text}\n\n[视觉描述] {vision_description}"
            confidence = min(self._last_ocr_confidence, 0.9)
            vision_degraded = False
        else:
            text_content = ocr_text
            confidence = 0.7
            vision_degraded = True

        return {
            "text_content": text_content,
            "extra_metadata": {
                "ocr_blocks": ocr_blocks,
                "vision_description": vision_description,
            },
            "confidence": confidence,
            "vision_degraded": vision_degraded,
        }
