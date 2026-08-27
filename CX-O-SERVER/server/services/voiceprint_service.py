"""声纹识别服务（Task 5）。

对接声纹容器（FunASR cam++ SV 语音说话人模型）的 HTTP 接口：
  - 可用性探测（GET /api/v1/voiceprint/status，带 10s 缓存）
  - 提取说话人 embedding（POST /api/v1/voiceprint/extract multipart）
  - 声纹档案本地落盘（CX-O-SERVER/data/voiceprint/speaker_profiles.json，tmp+replace 原子写）
  - 档案列表 / 注册 / 删除，成功注册/删除后同步到容器（profiles/sync，失败仅告警）
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import List, Optional

from server.core.utils import get_shared_http_client

logger = logging.getLogger(__name__)

# 数据文件绝对路径（CX-O-SERVER/data/voiceprint/speaker_profiles.json），
# 基于文件位置解析，禁止相对路径 / 禁止依赖运行时工作目录。
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DATA_DIR = _PROJECT_ROOT / "data" / "voiceprint"
_PROFILES_FILE = _DATA_DIR / "speaker_profiles.json"

# 声纹容器基础地址（settings.asr.remote_url，默认指向声纹/ASR 容器）
_DEFAULT_BASE = "http://127.0.0.1:8005"

# 可用性探测/状态缓存 TTL（秒）
_AVAIL_CACHE_TTL = 10.0

# 档案 name 长度上限
NAME_MAX_LEN = 32


class VoiceprintUnavailableError(Exception):
    """声纹容器不可用（探测失败 / 总开关关闭）。"""


class VoiceprintServiceError(Exception):
    """声纹容器调用失败（HTTP 非 2xx / 响应解析失败）。"""


def _profile_summary(profile: dict) -> dict:
    """档案序列化为公开摘要（仅暴露编码数量，不暴露原始向量）。"""
    return {
        "name": profile.get("name", ""),
        "embeddings_count": len(profile.get("embeddings", [])),
        "created_at": profile.get("created_at", ""),
    }


class VoiceprintService:
    """声纹识别服务：档案本地持久化 + 容器 embedding 提取/同步。"""

    def __init__(self):
        self._avail_cache_at: Optional[float] = None
        self._avail_cache_value: bool = False
        # M 修复：档案文件 RMW（读-改-写）互斥锁——register/register_embedding/delete
        # 并发时此前可互相覆盖丢更新（如并发注册两个说话人只落盘一个）。
        self._io_lock = asyncio.Lock()

    @property
    def base_url(self) -> str:
        """声纹容器基础地址（settings.asr.remote_url）。"""
        from server.config import get_settings
        return get_settings().asr.remote_url or _DEFAULT_BASE

    # ------------------------------------------------------------------ 读/写档案文件
    def _load_profiles(self) -> list:
        """读取本地声纹档案列表（文件缺失/损坏时返回空列表）。"""
        if not _PROFILES_FILE.exists():
            return []
        try:
            data = json.loads(_PROFILES_FILE.read_text(encoding="utf-8"))
            profiles = data.get("profiles", []) if isinstance(data, dict) else []
            return profiles if isinstance(profiles, list) else []
        except Exception as e:  # noqa: BLE001
            logger.error(f"读取声纹档案失败: {e}")
            return []

    def _save_profiles(self, profiles: list) -> None:
        """原子写声纹档案文件（tmp + os.replace）。"""
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=str(_DATA_DIR), suffix=".json.tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"version": 1, "profiles": profiles}, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, str(_PROFILES_FILE))
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    # ------------------------------------------------------------------ 容器交互
    async def _sync_remote(self) -> None:
        """将本地档案同步到容器（profiles/sync）。失败仅告警，不影响本地落盘。"""
        try:
            client = get_shared_http_client()
            resp = await client.post(f"{self.base_url}/api/v1/voiceprint/profiles/sync", timeout=5.0)
            if resp.status_code >= 400:
                logger.warning(f"声纹档案同步失败: HTTP {resp.status_code}")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"声纹档案同步告警（不影响本地落盘）: {e}")

    # ------------------------------------------------------------------ 对外接口
    async def is_available(self) -> bool:
        """容器可用性探测，带 10s 结果缓存；总开关关闭时直接 False。"""
        from server.config import get_settings
        if not get_settings().asr.voiceprint_enabled:
            return False
        now = time.monotonic()
        if self._avail_cache_at is not None and (now - self._avail_cache_at) < _AVAIL_CACHE_TTL:
            return self._avail_cache_value
        ok = await self._check_status()
        self._avail_cache_at = now
        self._avail_cache_value = ok
        return ok

    async def _check_status(self) -> bool:
        """GET {base}/api/v1/voiceprint/status，2s 超时。"""
        try:
            client = get_shared_http_client()
            resp = await client.get(f"{self.base_url}/api/v1/voiceprint/status", timeout=2.0)
            return resp.status_code == 200
        except Exception as e:  # noqa: BLE001
            logger.debug(f"声纹容器可用性探测失败: {e}")
            return False

    async def extract(self, audio_bytes: bytes) -> List[float]:
        """提取说话人 embedding 列表。失败抛 VoiceprintServiceError。"""
        try:
            client = get_shared_http_client()
            files = {"file": ("audio.wav", audio_bytes, "audio/wav")}
            resp = await client.post(
                f"{self.base_url}/api/v1/voiceprint/extract", files=files, timeout=10.0
            )
            if resp.status_code != 200:
                raise VoiceprintServiceError(f"声纹提取失败: HTTP {resp.status_code}")
            body = resp.json()
            embedding = body.get("embedding")
            if not isinstance(embedding, list) or not embedding:
                raise VoiceprintServiceError("声纹提取响应缺少 embedding")
            return [float(x) for x in embedding]
        except VoiceprintServiceError:
            raise
        except Exception as e:  # noqa: BLE001
            logger.error(f"声纹提取异常: {e}")
            raise VoiceprintServiceError(f"声纹提取异常: {e}")

    async def register(self, name: str, audio_bytes: bytes) -> dict:
        """注册/更新声纹档案：校验 name → 探活 → 提取 → 落盘 → 同步。"""
        name = (name or "").strip()
        if not name or len(name) > NAME_MAX_LEN:
            raise ValueError("声纹档案名不能为空且长度不能超过 32")
        if not await self.is_available():
            raise VoiceprintUnavailableError("voiceprint service unavailable")

        embedding = await self.extract(audio_bytes)
        # M 修复：RMW 全程持 _io_lock；磁盘 IO 挪 asyncio.to_thread，不阻塞事件循环
        async with self._io_lock:
            profiles = await asyncio.to_thread(self._load_profiles)

            updated = False
            target = next((p for p in profiles if p.get("name") == name), None)
            if target is None:
                target = {
                    "name": name,
                    "embeddings": [],
                    "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                }
                profiles.append(target)
            else:
                updated = True
            target["embeddings"].append(embedding)
            await asyncio.to_thread(self._save_profiles, profiles)
        # 同步失败仅告警，不影响本地已落盘档案
        await self._sync_remote()

        summary = _profile_summary(target)
        summary["updated"] = updated
        return summary

    async def register_embedding(self, name: str, embedding: list) -> dict:
        """基于实时聚类 embedding 注册/更新声纹档案（不重新提取音频特征）。

        与 register() 的区别：不走容器 /extract（embedding 来自容器实时聚类，
        容器必然已可用），仅本地落盘 + 同步容器。失败策略：落盘异常上抛
        ValueError（参数非法）/ 落盘 IO 异常上抛，同步容器失败仅告警。
        """
        name = (name or "").strip()
        if not name or len(name) > NAME_MAX_LEN:
            raise ValueError("声纹档案名不能为空且长度不能超过 32")
        if not isinstance(embedding, (list, tuple)) or not embedding:
            raise ValueError("声纹特征 embedding 无效")
        embeddings = [float(x) for x in embedding]
        # M 修复：RMW 全程持 _io_lock；磁盘 IO 挪 asyncio.to_thread
        async with self._io_lock:
            profiles = await asyncio.to_thread(self._load_profiles)

            updated = False
            target = next((p for p in profiles if p.get("name") == name), None)
            if target is None:
                target = {
                    "name": name,
                    "embeddings": [],
                    "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                }
                profiles.append(target)
            else:
                updated = True
            target["embeddings"].append(embeddings)
            await asyncio.to_thread(self._save_profiles, profiles)
        await self._sync_remote()          # 失败仅告警（_sync_remote 已内部捕获）

        summary = _profile_summary(target)
        summary["updated"] = updated
        return summary

    def list_profiles(self) -> List[dict]:
        """返回全部声纹档案摘要。"""
        return [_profile_summary(p) for p in self._load_profiles()]

    async def delete(self, name: str) -> bool:
        """删除指定声纹档案；存在则删除并同步，返回 True；不存在返回 False。"""
        # M 修复：RMW 全程持 _io_lock；磁盘 IO 挪 asyncio.to_thread
        async with self._io_lock:
            profiles = await asyncio.to_thread(self._load_profiles)
            remaining = [p for p in profiles if p.get("name") != name]
            if len(remaining) == len(profiles):
                return False
            await asyncio.to_thread(self._save_profiles, remaining)
        await self._sync_remote()
        return True

    async def get_status(self) -> dict:
        """容器可用性 + 本地档案数 + 相似度阈值。"""
        from server.config import get_settings
        available = await self.is_available()
        # M 修复：档案计数读取挪 asyncio.to_thread，磁盘 IO 不阻塞事件循环
        profiles = await asyncio.to_thread(self._load_profiles)
        return {
            "available": available,
            "profiles": len(profiles),
            "threshold": get_settings().asr.spk_sim_threshold,
        }


_service = VoiceprintService()


async def is_available() -> bool:
    """模块级出口：容器可用性探测（带缓存）。"""
    return await _service.is_available()


async def extract(audio_bytes: bytes) -> List[float]:
    """模块级出口：提取说话人 embedding。"""
    return await _service.extract(audio_bytes)


async def register(name: str, audio_bytes: bytes) -> dict:
    """模块级出口：注册/更新声纹档案。"""
    return await _service.register(name, audio_bytes)


async def register_embedding(name: str, embedding: list) -> dict:
    """模块级出口：基于 embedding 注册/更新声纹档案。"""
    return await _service.register_embedding(name, embedding)


def list_profiles() -> List[dict]:
    """模块级出口：声纹档案列表。"""
    return _service.list_profiles()


async def delete(name: str) -> bool:
    """模块级出口：删除声纹档案。"""
    return await _service.delete(name)


async def get_status() -> dict:
    """模块级出口：声纹服务状态。"""
    return await _service.get_status()