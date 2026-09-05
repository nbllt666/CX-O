"""人脸档案服务（spec add-vlm-frame-filter-face-match Task 2）。

对称 voiceprint_service 三层结构（提取→本地 JSON 档案→服务）：
  - 提取器双 provider：local（insightface buffalo_l + onnxruntime 懒加载，库缺失
    →unavailable 优雅降级）/ external（POST 外部端点 multipart，对称声纹容器调用形态）
  - 档案本地落盘（data/face/profiles.json，tmp+os.replace 原子写 + asyncio.Lock RMW 互斥）
  - register（取最大 bbox 人脸）/ match（逐脸余弦比对）/ list_profiles / delete_profile / get_status
  - 隐私红线：只落 embedding 向量，不落原始图像；列表接口不透出向量本体

依赖安装（provider=local 需要）：pip install insightface onnxruntime
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from server.core.utils import get_shared_http_client

logger = logging.getLogger(__name__)

# 数据文件默认绝对路径（CX-O-SERVER/data/face/profiles.json），
# 基于文件位置解析（与 config._resolve_data_path / voiceprint_service 同惯例），
# 禁止相对路径 / 禁止依赖运行时工作目录。
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_DATA_DIR = _PROJECT_ROOT / "data" / "face"
_DEFAULT_PROFILES_FILE = _DEFAULT_DATA_DIR / "profiles.json"

# 档案文件结构版本（public/schema/face_profile.schema.json）
_PROFILE_FILE_VERSION = "1.0"


class FaceServiceUnavailable(RuntimeError):
    """人脸服务不可用（功能未启用 / 本地模型依赖缺失或初始化失败 / 外部端点不可用）。"""


def _check_local_deps() -> bool:
    """检测 local provider 依赖（insightface/onnxruntime）是否可导入。

    用 find_spec 探测（不执行模块代码、不加载模型），保证 get_status 轻量同步。
    """
    import importlib.util

    return (
        importlib.util.find_spec("insightface") is not None
        and importlib.util.find_spec("onnxruntime") is not None
    )


def _decode_image_bytes(image_b64: str) -> bytes:
    """解码 base64/dataURL 图像为二进制（dataURL 前缀剥离 + base64 解码）。

    Raises:
        ValueError: 图像数据为空 / base64 解码失败。
    """
    raw = (image_b64 or "").strip()
    if not raw:
        raise ValueError("图像数据为空")
    if raw.startswith("data:"):  # dataURL 形如 data:image/jpeg;base64,xxxx
        raw = raw.partition(",")[2]
    try:
        return base64.b64decode(raw)
    except (binascii.Error, ValueError) as e:
        raise ValueError(f"图像 base64 解码失败: {e}")


def _bbox_area(bbox: Any) -> float:
    """计算 bbox [x1,y1,x2,y2] 面积（非法/缺失按 0 处理）。"""
    try:
        x1, y1, x2, y2 = (float(v) for v in bbox)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)


class BaseFaceExtractor:
    """人脸提取器抽象基类（local / external 双实现）。"""

    def is_available(self) -> bool:
        """提取器可用性（同步、轻量探测，不触发模型加载/网络请求）。"""
        raise NotImplementedError

    async def extract(self, image_b64: str) -> List[Dict[str, Any]]:
        """提取图像中全部人脸。

        Returns:
            list: [{embedding: list[float], bbox: [x1,y1,x2,y2]}, ...]

        Raises:
            ValueError: 图像解码失败。
            FaceServiceUnavailable: 提取依赖/端点不可用。
        """
        raise NotImplementedError


class LocalFaceExtractor(BaseFaceExtractor):
    """本地提取器：insightface buffalo_l + onnxruntime（懒加载，CPU 优先）。

    首次 extract 才 import insightface/onnxruntime（禁止模块顶层导入）；
    ImportError 或任何初始化异常置 unavailable 并抛 FaceServiceUnavailable
    （中文信息含安装提示），主链路不受影响。
    """

    def __init__(self, model_root: str = ""):
        self._model_root = model_root or ""
        self._app: Optional[Any] = None  # FaceAnalysis 实例（懒加载缓存）
        self._unavailable = False  # 依赖缺失/初始化失败后置 True，后续调用快速失败

    def is_available(self) -> bool:
        if self._unavailable:
            return False
        if self._app is not None:
            return True
        return _check_local_deps()

    def _ensure_loaded(self) -> Any:
        """懒加载 FaceAnalysis（buffalo_l，CPU provider）；失败置 unavailable。"""
        if self._unavailable:
            raise FaceServiceUnavailable(
                "本地人脸模型不可用（此前初始化失败）；请确认依赖: pip install insightface onnxruntime"
            )
        if self._app is not None:
            return self._app
        if not _check_local_deps():
            self._unavailable = True
            raise FaceServiceUnavailable(
                "本地人脸模型依赖未安装（insightface/onnxruntime）；请执行: pip install insightface onnxruntime"
            )
        try:
            from insightface.app import FaceAnalysis  # 懒加载：首次调用才 import

            kwargs: Dict[str, Any] = {"providers": ["CPUExecutionProvider"]}
            if self._model_root:
                kwargs["root"] = self._model_root
            app = FaceAnalysis(name="buffalo_l", **kwargs)
            app.prepare(ctx_id=-1, det_size=(640, 640))  # ctx_id=-1 强制 CPU 推理
            self._app = app
            return self._app
        except Exception as e:  # noqa: BLE001  ImportError/模型文件缺失等一律降级
            self._unavailable = True
            raise FaceServiceUnavailable(
                f"本地人脸模型初始化失败（{e}）；请确认依赖: pip install insightface onnxruntime"
            )

    def _extract_sync(self, image_b64: str) -> List[Dict[str, Any]]:
        import cv2  # 局部导入：跟随 insightface 依赖链（其安装自带 opencv）
        import numpy as np

        app = self._ensure_loaded()
        img_bytes = _decode_image_bytes(image_b64)
        arr = np.frombuffer(img_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("图像解码失败（非有效 JPEG/PNG 内容）")
        faces = app.get(img)
        results: List[Dict[str, Any]] = []
        for f in faces or []:
            emb = getattr(f, "normed_embedding", None)
            if emb is None:
                emb = getattr(f, "embedding", None)
            if emb is None:
                continue
            results.append(
                {
                    "embedding": [float(v) for v in emb],
                    "bbox": [float(v) for v in f.bbox],
                }
            )
        return results

    async def extract(self, image_b64: str) -> List[Dict[str, Any]]:
        # 模型推理为 CPU 重计算，挪线程池避免阻塞事件循环
        return await asyncio.to_thread(self._extract_sync, image_b64)


class ExternalFaceExtractor(BaseFaceExtractor):
    """外部容器提取器：POST {endpoint} multipart（字段 image），对称声纹容器调用形态。

    响应兼容 {faces: [{embedding, bbox}]} 与直接数组两种形态；非 200/网络异常
    →FaceServiceUnavailable（由路由转 503），图像解码失败→ValueError。
    """

    def __init__(self, endpoint: str):
        self._endpoint = (endpoint or "").strip()

    def is_available(self) -> bool:
        # 同步轻量判定：端点已配置即视为可用（不做网络探测，get_status 不阻塞）
        return bool(self._endpoint)

    async def extract(self, image_b64: str) -> List[Dict[str, Any]]:
        if not self._endpoint:
            raise FaceServiceUnavailable("外部人脸服务端点未配置（face_match.endpoint 为空）")
        img_bytes = _decode_image_bytes(image_b64)  # ValueError 原样透出
        try:
            client = get_shared_http_client()
            files = {"image": ("image.jpg", img_bytes, "image/jpeg")}
            resp = await client.post(self._endpoint, files=files, timeout=10.0)
            if resp.status_code != 200:
                raise FaceServiceUnavailable(f"外部人脸服务调用失败: HTTP {resp.status_code}")
            body = resp.json()
        except FaceServiceUnavailable:
            raise
        except Exception as e:  # noqa: BLE001  网络/超时/响应解析失败统一按不可用处理
            logger.error(f"外部人脸服务调用异常: {e}")
            raise FaceServiceUnavailable(f"外部人脸服务调用异常: {e}")
        items = body.get("faces") if isinstance(body, dict) else body
        if not isinstance(items, list):
            raise FaceServiceUnavailable("外部人脸服务响应格式无效（缺少 faces 数组）")
        results: List[Dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict) or not item.get("embedding"):
                continue
            results.append(
                {
                    "embedding": [float(v) for v in item["embedding"]],
                    "bbox": [float(v) for v in item.get("bbox", [])],
                }
            )
        return results


class FaceProfileService:
    """人脸档案服务：注册（最大 bbox 人脸入档）/ 匹配（逐脸余弦）/ 列举 / 删除 / 状态。

    档案持久化于 data/face/profiles.json（store_path 可覆盖），结构
    {version, profiles: [{name, embedding, created_at}]}；tmp+os.replace 原子写，
    asyncio.Lock 串行化 RMW（对称 voiceprint_service._io_lock）。
    """

    def __init__(self, config: Any = None, extractor: Optional[BaseFaceExtractor] = None):
        self._config = config  # 注入的 FaceMatchConfig（None=延迟读全局 settings，避免导入期加载）
        self._extractor = extractor  # 测试注入点；None=按 provider 惰性构造
        self._local_extractor: Optional[LocalFaceExtractor] = None
        # RMW（读-改-写）互斥锁：register/delete 并发串行化防丢更新（对称 voiceprint）
        self._io_lock = asyncio.Lock()

    # ------------------------------------------------------------------ 配置与提取器
    def _get_config(self) -> Any:
        """读取 face_match 配置（延迟读取，支持热更新感知）。"""
        if self._config is not None:
            return self._config
        from server.config import get_settings

        return get_settings().config.face_match

    def _require_enabled(self) -> Any:
        """功能总开关闸门：enabled=false 时抛 FaceServiceUnavailable（对齐 face.pyi 契约）。"""
        cfg = self._get_config()
        if not cfg.enabled:
            raise FaceServiceUnavailable("人脸匹配功能未启用（face_match.enabled=false）")
        return cfg

    def _get_extractor(self) -> BaseFaceExtractor:
        """解析提取器：注入优先；否则按 provider 构造（local 实例跨调用复用缓存状态）。"""
        if self._extractor is not None:
            return self._extractor
        cfg = self._get_config()
        if cfg.provider == "external":
            return ExternalFaceExtractor(cfg.endpoint)  # 无状态，可直接构造
        # local 提取器带模型缓存/unavailable 状态，须跨调用复用同一实例
        if self._local_extractor is None:
            self._local_extractor = LocalFaceExtractor(model_root=cfg.model_root)
        return self._local_extractor

    async def _extract_faces(self, image_b64: str, max_faces: int) -> List[Dict[str, Any]]:
        """提取人脸并截断至 max_faces_per_frame；依赖缺失统一转 FaceServiceUnavailable。"""
        try:
            faces = await self._get_extractor().extract(image_b64)
        except ImportError as e:
            raise FaceServiceUnavailable(
                f"人脸提取依赖缺失（{e}）；请执行: pip install insightface onnxruntime"
            )
        return list(faces or [])[:max_faces]

    # ------------------------------------------------------------------ 档案存储
    def _get_store_path(self) -> Path:
        """档案文件路径：store_path 非空时优先（相对路径锚定项目根，对齐
        config._resolve_data_path 惯例），空=内置默认 data/face/profiles.json。"""
        cfg = self._get_config()
        if cfg.store_path:
            p = Path(cfg.store_path)
            return p if p.is_absolute() else _PROJECT_ROOT / p
        return _DEFAULT_PROFILES_FILE

    def _load_profiles(self) -> List[Dict[str, Any]]:
        """读取本地人脸档案列表（文件缺失/损坏时返回空列表）。"""
        path = self._get_store_path()
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            profiles = data.get("profiles", []) if isinstance(data, dict) else []
            return profiles if isinstance(profiles, list) else []
        except Exception as e:  # noqa: BLE001
            logger.error(f"读取人脸档案失败: {e}")
            return []

    def _save_profiles(self, profiles: List[Dict[str, Any]]) -> None:
        """原子写人脸档案文件（tmp + os.replace），只落向量不落原始图像（隐私红线）。"""
        path = self._get_store_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".json.tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(
                    {"version": _PROFILE_FILE_VERSION, "profiles": profiles},
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
            os.replace(tmp_path, str(path))
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    # ------------------------------------------------------------------ 对外接口
    async def register(self, name: str, image_b64: str) -> Dict[str, Any]:
        """注册（或覆盖）人脸档案：提取→取最大 bbox 人脸→落盘（重名覆盖）。

        Returns:
            dict: {name, created_at, embedding_dim, faces_detected}

        Raises:
            ValueError: name 为空 / 图像解码失败 / 未检出人脸。
            FaceServiceUnavailable: 功能未启用或提取依赖不可用。
        """
        name = (name or "").strip()
        if not name:
            raise ValueError("人脸档案名不能为空")
        cfg = self._require_enabled()
        faces = await self._extract_faces(image_b64, cfg.max_faces_per_frame)
        if not faces:
            raise ValueError("未检出人脸，无法注册（图像需包含至少一张可检出人脸）")
        # 决策点 #8：register 取最大 bbox 人脸入档（对齐"注册眼前这个人"工具语义）
        target_face = max(faces, key=lambda f: _bbox_area(f.get("bbox")))
        embedding = [float(v) for v in target_face["embedding"]]

        async with self._io_lock:
            profiles = await asyncio.to_thread(self._load_profiles)
            created_at = time.strftime("%Y-%m-%dT%H:%M:%S")
            target = next((p for p in profiles if p.get("name") == name), None)
            if target is None:
                target = {"name": name, "embedding": embedding, "created_at": created_at}
                profiles.append(target)
            else:
                # 重名覆盖语义：覆盖向量与创建时间（对齐 voiceprint 注册/更新行为）
                target["embedding"] = embedding
                target["created_at"] = created_at
            await asyncio.to_thread(self._save_profiles, profiles)

        return {
            "name": name,
            "created_at": target["created_at"],
            "embedding_dim": len(embedding),
            "faces_detected": len(faces),
        }

    async def match(self, image_b64: str) -> List[Dict[str, Any]]:
        """逐脸比对：检测全部人脸（≤max_faces_per_frame）→与全部档案算余弦相似度。

        Returns:
            list: 命中项 {name, similarity, bbox}；未命中项 {unknown: True,
            best_similarity, bbox}（best_similarity=全档案最高，不自动入档）。
        """
        cfg = self._require_enabled()
        faces = await self._extract_faces(image_b64, cfg.max_faces_per_frame)
        if not faces:
            return []
        profiles = await asyncio.to_thread(self._load_profiles)
        if not profiles:
            # 无档案：各脸均 unknown（best_similarity=0.0），不自动入档（决策点 #9）
            return [
                {"unknown": True, "best_similarity": 0.0, "bbox": f.get("bbox")}
                for f in faces
            ]
        # 纯 numpy 计算，挪线程池避免阻塞事件循环
        return await asyncio.to_thread(self._compare_faces, faces, profiles, cfg.sim_threshold)

    def _compare_faces(
        self, faces: List[Dict[str, Any]], profiles: List[Dict[str, Any]], threshold: float
    ) -> List[Dict[str, Any]]:
        """余弦相似度逐脸比对（纯同步 numpy，调用方负责挪线程池）。"""
        import numpy as np

        results: List[Dict[str, Any]] = []
        for face in faces:
            vec = np.asarray(face.get("embedding") or [], dtype=np.float32)
            item: Dict[str, Any] = {"bbox": face.get("bbox")}
            best_sim, best_name = 0.0, None
            if vec.size:
                for profile in profiles:
                    pvec = np.asarray(profile.get("embedding") or [], dtype=np.float32)
                    # 维度不一致的档案跳过（如切换 provider 后向量维度不同）
                    if pvec.size != vec.size:
                        continue
                    denom = float(np.linalg.norm(vec) * np.linalg.norm(pvec))
                    if denom == 0.0:
                        continue
                    sim = float(np.dot(vec, pvec) / denom)
                    if sim > best_sim:
                        best_sim, best_name = sim, profile.get("name")
            if best_name is not None and best_sim >= threshold:
                item["name"] = best_name
                item["similarity"] = best_sim
            else:
                item["unknown"] = True
                item["best_similarity"] = best_sim
            results.append(item)
        return results

    async def list_profiles(self) -> List[Dict[str, Any]]:
        """列出现有全部人脸档案（脱敏：不含 embedding 向量本体）。"""
        self._require_enabled()
        profiles = await asyncio.to_thread(self._load_profiles)
        return [
            {
                "name": p.get("name", ""),
                "embedding_dim": len(p.get("embedding") or []),
                "created_at": p.get("created_at", ""),
            }
            for p in profiles
        ]

    async def delete_profile(self, name: str) -> bool:
        """删除指定人脸档案；存在删除返回 True，不存在返回 False（幂等）。"""
        self._require_enabled()
        async with self._io_lock:
            profiles = await asyncio.to_thread(self._load_profiles)
            remaining = [p for p in profiles if p.get("name") != name]
            if len(remaining) == len(profiles):
                return False
            await asyncio.to_thread(self._save_profiles, remaining)
        return True

    def get_status(self) -> Dict[str, Any]:
        """运行状态（同步方法，不触发模型加载；字段对齐 face.pyi 契约）。"""
        cfg = self._get_config()
        available = bool(self._get_extractor().is_available())
        return {
            "enabled": cfg.enabled,
            "provider": cfg.provider,
            "available": available,
            "ready": available,  # face.pyi 契约要求的字段（与 available 同义）
            "sim_threshold": cfg.sim_threshold,
            "max_faces_per_frame": cfg.max_faces_per_frame,
            "profile_count": len(self._load_profiles()),
        }


_service: Optional[FaceProfileService] = None


def get_face_profile_service() -> FaceProfileService:
    """获取 FaceProfileService 单例（工厂入口，配置延迟读取；enabled=false 仍返回实例）。"""
    global _service
    if _service is None:
        _service = FaceProfileService()
    return _service
