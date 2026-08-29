"""统一参考音频资产存储（source=prompt / source=file）。

源真理: public/schema/ref_audio_asset.schema.json + public/interface_stub/ref_audio_store.pyi
完成 Skill: s0201
当前状态: Task 3 实现——资产存储层。

职责：
- 将 source=prompt（Qwen3 VoiceDesign 提示词生成）与 source=file（外部音频文件）统一为
  同一内部形状（``RefAudioAsset``），具有稳定 ID、来源元数据、checksum、格式元数据与
  生命周期状态（registered / failed / deleted）。
- 提供注册、解析、列表、注释、删除（软删除）、checksum 去重等能力。
- 禁止客户端传任意本地路径读取文件；非法文件/路径穿越抛 ``InvalidRefAudioError``，
  不存在/已删除抛 ``RefAudioNotFoundError``。
- 严格匹配 public/interface_stub/ref_audio_store.pyi 的签名。

存储布局（基于 ``settings.tts.ref_audio_assets_dir``）：
- ``index.json`` —— 资产元数据索引（JSON List，与既有 voice_refs JSON 风格一致）。
- ``{asset_id}.{format}`` —— 每个资产的音频文件，文件路径由资产 ID 确定性推导，
  无需在公开资产形状中暴露磁盘路径。

说明：
- ``register_from_prompt`` 依赖一个可注入的 prompt 音频生成器（Qwen3 VoiceDesign 任务）。
  生产环境通过 ``set_prompt_generator`` 注入真实生成实现；未注入时抛
  ``RuntimeUnavailableError``。测试注入 Mock 生成器即可无外部运行时验证注册链路。
- 非 wav 格式的音频元数据解析优先尝试 soundfile；不可用时回退到内置的轻量头部解析
  （flac/opus/aac/mp3）。wav 使用标准库 ``wave`` 全量解析。
"""
from __future__ import annotations

import base64
import builtins
import dataclasses
import hashlib
import io
import json
import logging
import os
import re
import threading
import uuid
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from server.config import get_settings
from server.qwen3_tts_provider import (
    InvalidRefAudioError,
    RefAudioNotFoundError,
    RuntimeUnavailableError,
)

logger = logging.getLogger(__name__)

# 进程级可重入锁：保护索引/绑定/当前指针/音频文件读改写的整写串行化
# （仅普通线程锁，兼容同步/异步混用调用；禁用 asyncio 锁以避免跨线程并发失效）。
_LOCK = threading.RLock()


class AssetBoundError(Exception):
    """资产被某 Agent 绑定，拒绝删除（提示先解绑）。"""


__all__ = [
    "AssetBoundError",
    "RefAudioAsset",
    "GeneratedAudio",
    "register_from_prompt",
    "register_from_file",
    "resolve",
    "get",
    "list",
    "update_note",
    "delete",
    "exists",
    "set_current",
    "get_current",
    "clear_current",
    "set_prompt_generator",
    "get_audio_path",
    # per-agent 绑定新增
    "set_for_agent",
    "get_for_agent",
    "clear_for_agent",
    "list_bindings",
    "asset_used_by_any_agent",
    # 集群接入
    "set_emit_hook",
    "build_snapshot",
    "restore_snapshot",
    "build_bindings",
]

# ============================================================================
# 契约常量
# ============================================================================

_ASSET_ID_PATTERN = re.compile(r"^ref_[a-zA-Z0-9_-]+$")

# 参考音频支持格式（ref_audio_asset.schema.json format enum）
_FORMATS = ("wav", "mp3", "flac", "opus", "aac")
_ALLOWED_EXTENSIONS = {f".{f}" for f in _FORMATS}

# 输入采样率范围（ref_audio_asset.schema.json sample_rate minimum/maximum）
_SAMPLE_RATE_MIN = 8000
_SAMPLE_RATE_MAX = 48000

# 最小参考音频时长（秒，契约 minimum: 1）
_MIN_DURATION_SECONDS = 1.0

# 索引文件名
_INDEX_FILENAME = "index.json"
# 当前默认参考音频指针文件名（独立于资产索引，存储 {"asset_id": ...}）
_CURRENT_FILENAME = "current.json"
# per-agent 绑定文件名（独立于资产索引，存储 {agent_id: {"asset_id":..., "tts_voice":...}}）
_BINDINGS_FILENAME = "agent_bindings.json"

# 快照字典版本
_SNAPSHOT_VERSION = 1


@dataclasses.dataclass
class GeneratedAudio:
    """prompt 音频生成器返回结果（source=prompt 注册输入）。"""

    audio: bytes
    format: str
    sample_rate: int
    channels: int
    duration_seconds: float


# 模块级可注入生成器：由 Qwen3 VoiceDesign 任务 / 测试注入。
_prompt_generator: Optional[Callable[..., Any]] = None
# 模块级资产目录覆盖（测试隔离用）；None 时从配置惰性解析。
_assets_dir_override: Optional[Path] = None
# 模块级集群事件 emit hook：既集群启用时注入 replicator.emit；未注入（None）时短路，单机零影响。
_emit_hook: Optional[Callable[[str, str, dict], Any]] = None


# ============================================================================
# 配置与目录解析
# ============================================================================

def _resolve_assets_dir() -> Path:
    """解析资产持久化根目录（优先测试覆盖，否则读取统一配置）。"""
    if _assets_dir_override is not None:
        return _assets_dir_override
    settings = get_settings()
    return Path(settings.tts.ref_audio_assets_dir)


def _allowed_dirs() -> List[Path]:
    """返回允许 register_from_file 读取的目录集合（含资产目录）。"""
    bases = [_resolve_assets_dir()]
    settings = get_settings()
    for d in settings.tts.allowed_ref_audio_dirs:
        if d:
            bases.append(Path(d))
    return [b.resolve() for b in bases]


def set_prompt_generator(fn: Optional[Callable[..., Any]]) -> None:
    """注入/清除 prompt 音频生成器（Qwen3 VoiceDesign 任务接入点）。

    fn 签名：``async fn(prompt: str, language: Optional[str]) -> GeneratedAudio``。
    """
    global _prompt_generator
    _prompt_generator = fn


def set_emit_hook(fn: Optional[Callable[["str", "str", "dict"], Any]]) -> None:
    """注入/清除集群事件 emit hook（签名：``fn(unit, op, payload)``）。

    集群启用装配时注入 ``replicator.emit``；停用/关闭时注入 None（短路，单机零影响）。
    """
    global _emit_hook
    _emit_hook = fn


def _emit(unit: str, op: str, payload: dict) -> None:
    """触发集群事件（emit hook 为空时直接短路，不抛错）。"""
    fn = _emit_hook
    if fn is None:
        return
    try:
        fn(unit, op, payload)
    except Exception as e:  # noqa: BLE001 - 集群 emit 失败不回滚本地写变更
        logger.warning(f"集群 emit 失败 (unit={unit}, op={op}): {e}")


def _set_assets_dir(path: Optional[Path]) -> None:
    """覆盖资产根目录（仅供测试隔离使用）。"""
    global _assets_dir_override
    _assets_dir_override = Path(path) if path is not None else None


# ============================================================================
# RefAudioAsset
# ============================================================================

@dataclasses.dataclass
class RefAudioAsset:
    """参考音频资产（对应 ref_audio_asset.schema.json 的公开形状）。"""

    id: str
    source: str
    checksum: str
    status: str
    created_at: str
    prompt: Optional[str] = None
    file_name: Optional[str] = None
    ref_text: Optional[str] = None
    format: Optional[str] = None
    sample_rate: Optional[int] = None
    channels: Optional[int] = None
    duration_seconds: Optional[float] = None
    size_bytes: Optional[int] = None
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """序列化为公开资产形状（仅含非空字段，符合 schema）。"""
        out: Dict[str, Any] = {
            "id": self.id,
            "source": self.source,
            "checksum": self.checksum,
            "status": self.status,
            "created_at": self.created_at,
        }
        for field in (
            "prompt", "file_name", "ref_text", "format", "sample_rate",
            "channels", "duration_seconds", "size_bytes", "note",
        ):
            value = getattr(self, field, None)
            if value is not None and value != "":
                out[field] = value
        return out

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RefAudioAsset":
        """从字典构建资产（缺失可空字段自动补默认）。"""
        return cls(**{k: v for k, v in data.items() if k in _ASSET_FIELDS})

    @property
    def is_deleted(self) -> bool:
        return self.status == "deleted"


_ASSET_FIELDS = set(RefAudioAsset.__dataclass_fields__)


# ============================================================================
# 持久化
# ============================================================================

def _index_path() -> Path:
    return _resolve_assets_dir() / _INDEX_FILENAME


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """临时文件 + 原子替换写入音频字节，避免读方（如 build_snapshot）读到并发覆盖的半写音频。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name("." + path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _audio_path_for(asset_id: str, fmt: str) -> Path:
    """由资产 ID + 格式确定性推导音频文件路径。"""
    return _resolve_assets_dir() / f"{asset_id}.{fmt}"


def _load_index() -> List[Dict[str, Any]]:
    """加载资产索引（文件不存在时返回空列表）。"""
    with _LOCK:
        path = _index_path()
        if not path.exists():
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"读取参考音频资产索引失败: {path} - {e}")
            return []
        return data if isinstance(data, builtins.list) else []


def _save_index(records: List[Dict[str, Any]]) -> None:
    """原子写入资产索引。"""
    with _LOCK:
        _resolve_assets_dir().mkdir(parents=True, exist_ok=True)
        tmp = _index_path().with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _index_path())


def _append_record(asset: RefAudioAsset) -> None:
    """追加一条资产记录到索引（读改写整写在锁内串行化）。"""
    with _LOCK:
        records = _load_index()
        records.append(asset.to_dict())
        _save_index(records)


def _current_path() -> Path:
    """当前默认参考音频指针文件路径。"""
    return _resolve_assets_dir() / _CURRENT_FILENAME


def _load_current_id() -> Optional[str]:
    """读取当前默认参考音频资产 ID；未设置或文件损坏返回 None。"""
    with _LOCK:
        path = _current_path()
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"读取当前参考音频指针失败: {path} - {e}")
            return None
        asset_id = data.get("asset_id") if isinstance(data, dict) else None
        return asset_id if isinstance(asset_id, str) else None


def _save_current_id(asset_id: Optional[str]) -> None:
    """原子写入当前默认参考音频资产 ID（None 表示清除）。"""
    with _LOCK:
        _resolve_assets_dir().mkdir(parents=True, exist_ok=True)
        tmp = _current_path().with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"asset_id": asset_id}, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _current_path())


def _clear_current_if_matches(asset_id: str) -> None:
    """若指定资产恰为当前默认，则清除指针（删除/软删除资产后调用）。"""
    if _load_current_id() == asset_id:
        _save_current_id(None)


# ============================================================================
# per-agent 参考音频绑定（独立于 current.json，落盘在资产目录下）
# ============================================================================

def _bindings_path() -> Path:
    return _resolve_assets_dir() / _BINDINGS_FILENAME


def _load_bindings() -> Dict[str, dict]:
    """加载 per-agent 绑定表；文件缺失/损坏返回空表。"""
    with _LOCK:
        path = _bindings_path()
        if not path.exists():
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"读取 per-agent 绑定失败: {path} - {e}")
            return {}
        return data if isinstance(data, builtins.dict) else {}


def _save_bindings(bindings: Dict[str, dict]) -> None:
    """原子写入 per-agent 绑定表。"""
    with _LOCK:
        _resolve_assets_dir().mkdir(parents=True, exist_ok=True)
        tmp = _bindings_path().with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(bindings, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _bindings_path())


def _apply_binding(
    agent_id: str,
    asset_id: Optional[str],
    tts_voice: Optional[str] = None,
    emit: bool = True,
) -> Optional[dict]:
    """底层写入绑定（不校验资产存在，供集合 replica/内部幂等落盘用）。

    asset_id 为 None 时清除绑定（binding_clear）；否则设置绑定。
    emit=True 时触发集群事件（默认）。集群回放时传 emit=False 避免形成回环。
    """
    with _LOCK:
        bindings = _load_bindings()
        if asset_id is None:
            bindings.pop(agent_id, None)
        else:
            bindings[agent_id] = {"asset_id": asset_id, "tts_voice": tts_voice}
        _save_bindings(bindings)
    if emit:
        op = "binding_set" if asset_id else "binding_clear"
        _emit(
            "ref_audio", op,
            {"agent_id": agent_id, "asset_id": asset_id, "tts_voice": tts_voice},
        )
    return bindings.get(agent_id)


def set_for_agent(
    agent_id: str,
    asset_id: str,
    tts_voice: Optional[str] = None,
) -> dict:
    """为指定 Agent 绑定参考音频资产（运行真源，落盘 agent_bindings.json）。

    Args:
        agent_id: Agent 唯一标识。
        asset_id: 要绑定的参考音频资产 ID（必须存在且未删除，否则抛 RefAudioNotFoundError）。
        tts_voice: 可选音色标识。

    Returns:
        绑定后的 {asset_id, tts_voice} 字典。
    """
    # 并发修复：resolve 校验（存在且未删除）移入 ``_LOCK`` 临界区内——
    # 旧实现在锁外校验、经 _apply_binding 再取锁写入，与 delete（同锁
    # 软删除）并发时存在 TOCTOU 窗口："校验通过 → delete 软删除 →
    # 绑定照常写入"，产生"已删资产仍被 Agent 绑定"的悬挂绑定。
    # _LOCK 为 RLock 可重入，锁内调用 resolve（内部再取锁）安全。
    with _LOCK:
        resolve(asset_id)  # 不存在/已删除抛 RefAudioNotFoundError
        binding = _apply_binding(agent_id, asset_id, tts_voice=tts_voice, emit=True)
    logger.info(f"Agent {agent_id} 绑定参考音频资产: {asset_id}")
    return binding or {"asset_id": asset_id, "tts_voice": tts_voice}


def get_for_agent(agent_id: str) -> Optional[dict]:
    """返回指定 Agent 的参考音频绑定；未绑定返回 None。"""
    return _load_bindings().get(agent_id)


def clear_for_agent(agent_id: str) -> None:
    """清除指定 Agent 的参考音频绑定（不删除资产本身）。"""
    _apply_binding(agent_id, None, emit=True)
    logger.info(f"清除 Agent {agent_id} 的参考音频绑定")


def list_bindings() -> Dict[str, dict]:
    """返回全部 per-agent 绑定表副本。"""
    return dict(_load_bindings())


def asset_used_by_any_agent(asset_id: str) -> bool:
    """判断资产是否被任一 Agent 绑定（删除保护）。"""
    return any(b.get("asset_id") == asset_id for b in _load_bindings().values())


# ============================================================================
# 工具函数
# ============================================================================

def _new_id() -> str:
    """生成唯一资产 ID（ref_ 前缀 + 随机 hex），碰撞时重试。"""
    with _LOCK:
        records = _load_index()
        existing = {r.get("id") for r in records}
        while True:
            candidate = f"ref_{uuid.uuid4().hex[:16]}"
            if candidate not in existing:
                return candidate


def _now_iso() -> str:
    """生成 UTC ISO8601 时间戳。"""
    return datetime.now(timezone.utc).isoformat()


def _md5(data: bytes) -> str:
    """计算内容 MD5（用于去重与完整性校验）。"""
    return hashlib.md5(data).hexdigest()


def _validate_asset_id(asset_id: str) -> None:
    """校验资产 ID 符合契约 pattern。"""
    if not isinstance(asset_id, str) or not _ASSET_ID_PATTERN.match(asset_id):
        raise InvalidRefAudioError(
            f"资产 ID 非法: {asset_id!r}，须匹配 ^ref_[a-zA-Z0-9_-]+$"
        )


def _find_by_checksum(checksum: str) -> Optional[RefAudioAsset]:
    """在未删除资产中按 checksum 查找（去重）。"""
    for rec in _load_index():
        if rec.get("checksum") == checksum and rec.get("status") != "deleted":
            return RefAudioAsset.from_dict(rec)
    return None


def _validate_audio_meta(
    fmt: str,
    sample_rate: int,
    channels: int,
    duration_seconds: float,
    size_bytes: int,
) -> None:
    """校验音频元数据契约（格式/大小/时长/采样率/声道）。非法资产不用于推理。"""
    if fmt not in _FORMATS:
        raise InvalidRefAudioError(f"不支持的音频格式: {fmt}，仅支持 {_FORMATS}")
    if not (_SAMPLE_RATE_MIN <= sample_rate <= _SAMPLE_RATE_MAX):
        raise InvalidRefAudioError(
            f"采样率越界: {sample_rate}Hz，须在 [{_SAMPLE_RATE_MIN}, {_SAMPLE_RATE_MAX}]Hz"
        )
    if not isinstance(channels, int) or channels < 1:
        raise InvalidRefAudioError(f"声道数非法: {channels}")
    if duration_seconds is None or duration_seconds < _MIN_DURATION_SECONDS:
        raise InvalidRefAudioError(
            f"参考音频时长非法: {duration_seconds}s，须 ≥ {_MIN_DURATION_SECONDS}s"
        )
    max_size = get_settings().tts.max_ref_audio_size_mb * 1024 * 1024
    if size_bytes <= 0:
        raise InvalidRefAudioError("音频文件为空")
    if size_bytes > max_size:
        raise InvalidRefAudioError(
            f"音频文件过大: {size_bytes} 字节，上限 {max_size} 字节"
        )


# ============================================================================
# 路径安全（禁止任意本地路径 / 路径穿越）
# ============================================================================

def _safe_resolve_file_path(file_path: str) -> Path:
    """解析并校验外部文件路径，杜绝路径穿越与任意本地路径读取。

    - 相对路径以允许目录为基准解析；绝对路径必须位于允许目录内。
    - 解析后必须仍位于允许目录之前缀内，否则抛 InvalidRefAudioError。
    """
    if not isinstance(file_path, str) or not file_path.strip():
        raise InvalidRefAudioError("缺少参考音频文件路径")

    bases = _allowed_dirs()
    p = Path(file_path)

    if p.is_absolute():
        candidate = p.resolve()
    else:
        candidate = (bases[0] / p).resolve()

    for base in bases:
        prefix = str(base) + os.sep
        if str(candidate) == str(base) or str(candidate).startswith(prefix):
            if candidate.exists() and candidate.is_file():
                return candidate
            raise InvalidRefAudioError(f"参考音频文件不存在: {file_path}")

    raise InvalidRefAudioError("路径穿越或越出允许目录，拒绝读取")


# ============================================================================
# 音频格式探测与元数据解析
# ============================================================================

def _detect_format(path: Path, data: bytes) -> str:
    """按扩展名 + 魔数识别音频格式。"""
    ext = path.suffix.lower().lstrip(".")
    if ext in _FORMATS:
        return ext
    magic_map = {
        b"RIFF": "wav",
        b"fLaC": "flac",
        b"OggS": "opus",
    }
    for magic, fmt in magic_map.items():
        if data.startswith(magic):
            return fmt
    raise InvalidRefAudioError("无法识别音频格式")


def _probe_audio(data: bytes, fmt: str) -> Tuple[int, int, float]:
    """返回 (sample_rate, channels, duration_seconds)。

    优先尝试 soundfile（libsndfile 全覆盖）；不可用时回退内置轻量头部解析。
    """
    sf = _import_soundfile()
    if sf is not None:
        try:
            info = sf.info(io.BytesIO(data))
            return int(info.samplerate), int(info.channels), float(info.duration)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"soundfile 解析失败，回退内置解析: {e}")

    try:
        if fmt == "wav":
            return _probe_wav(data)
        if fmt == "flac":
            return _probe_flac(data)
        if fmt == "opus":
            return _probe_opus(data)
        if fmt == "aac":
            return _probe_aac(data)
        if fmt == "mp3":
            return _probe_mp3(data)
    except InvalidRefAudioError:
        raise
    except Exception as e:  # noqa: BLE001
        raise InvalidRefAudioError(f"音频元数据解析失败: {e}")

    raise InvalidRefAudioError(f"不支持的音频格式: {fmt}")


def _import_soundfile():
    """可选导入 soundfile（libsndfile），不可用时返回 None。"""
    try:
        import soundfile  # noqa: F401
        return soundfile
    except ImportError:
        return None


def _probe_wav(data: bytes) -> Tuple[int, int, float]:
    """WAV 元数据（标准库 wave 全量解析）。"""
    if not data.startswith(b"RIFF") or data[8:12] != b"WAVE":
        raise InvalidRefAudioError("非合法 WAV 文件")
    with wave.open(io.BytesIO(data), "rb") as wf:
        sample_rate = wf.getframerate()
        channels = wf.getnchannels()
        nframes = wf.getnframes()
    if sample_rate <= 0:
        raise InvalidRefAudioError("WAV 采样率非法")
    return sample_rate, channels, nframes / sample_rate


def _probe_flac(data: bytes) -> Tuple[int, int, float]:
    """FLAC 元数据（解析 STREAMINFO 块）。"""
    if not data.startswith(b"fLaC"):
        raise InvalidRefAudioError("非合法 FLAC 文件")
    offset = 4
    while offset + 4 <= len(data):
        header = data[offset:offset + 4]
        block_type = header[0] & 0x7F
        block_len = int.from_bytes(header[1:4], "big")
        offset += 4
        if block_type == 0:  # STREAMINFO
            if offset + 18 > len(data):
                raise InvalidRefAudioError("FLAC STREAMINFO 不完整")
            si = data[offset:offset + 18]
            sample_rate = (int.from_bytes(si[10:13], "big") >> 4) & 0xFFFFF
            channels = ((si[12] >> 1) & 0x07) + 1
            total_samples = int.from_bytes(si[13:18], "big") & ((1 << 36) - 1)
            if sample_rate <= 0:
                raise InvalidRefAudioError("FLAC 采样率非法")
            return sample_rate, channels, total_samples / sample_rate
        offset += block_len
        if header[0] & 0x80:  # last-metadata-block
            break
    raise InvalidRefAudioError("FLAC 未找到 STREAMINFO")


def _probe_opus(data: bytes) -> Tuple[int, int, float]:
    """Opus 元数据（Ogg 页遍历 + OpusHead）。Opus 输出恒为 48kHz。"""
    if not data.startswith(b"OggS"):
        raise InvalidRefAudioError("非合法 Ogg/Opus 文件")
    head_idx = data.find(b"OpusHead")
    if head_idx < 0 or head_idx + 19 > len(data):
        raise InvalidRefAudioError("Opus 缺少 OpusHead")
    channels = data[head_idx + 9]
    sample_rate = 48000
    last_granule = 0
    found = False
    idx = 0
    while idx + 27 <= len(data) and data[idx:idx + 4] == b"OggS":
        granule = int.from_bytes(data[idx + 6:idx + 14], "little")
        if granule:
            last_granule = granule
            found = True
        seg_count = data[idx + 26]
        seg_table = data[idx + 27:idx + 27 + seg_count]
        payload_len = sum(seg_table)
        idx += 27 + seg_count + payload_len
    if not found or sample_rate <= 0:
        raise InvalidRefAudioError("Opus 时长解析失败")
    return sample_rate, channels, last_granule / sample_rate


_AAC_SAMPLE_RATES = [
    96000, 88200, 64000, 48000, 44100, 32000, 24000, 22050,
    16000, 12000, 11025, 8000, 7350,
]


def _probe_aac(data: bytes) -> Tuple[int, int, float]:
    """AAC(ADTS) 元数据（遍历 ADTS 帧头）。每帧 1024 采样。"""
    if len(data) < 7 or data[0] != 0xFF or (data[1] & 0xF0) != 0xF0:
        raise InvalidRefAudioError("非合法 AAC/ADTS 文件")
    idx = 0
    sample_rate = 0
    channels = 1
    frames = 0
    while idx + 7 <= len(data):
        if data[idx] != 0xFF or (data[idx + 1] & 0xF0) != 0xF0:
            break
        sf_index = (data[idx + 2] >> 2) & 0x0F
        channels = ((data[idx + 2] & 0x01) << 2) | ((data[idx + 3] >> 6) & 0x03)
        sample_rate = (
            _AAC_SAMPLE_RATES[sf_index] if sf_index < len(_AAC_SAMPLE_RATES) else 0
        )
        frame_len = (
            ((data[idx + 3] & 0x03) << 11)
            | (data[idx + 4] << 3)
            | ((data[idx + 5] >> 5) & 0x07)
        )
        if sample_rate == 0 or frame_len < 7:
            break
        frames += 1
        idx += frame_len
    if sample_rate == 0 or frames == 0:
        raise InvalidRefAudioError("AAC 解析失败")
    return sample_rate, channels, frames * 1024 / sample_rate


# MP3 采样率表（按 version 分组）
_MP3_SAMPLE_RATES = {
    3: [44100, 48000, 32000],   # MPEG1
    2: [22050, 24000, 16000],   # MPEG2
    0: [11025, 12000, 8000],    # MPEG2.5
}
# MP3 每帧采样数（Layer I=384，Layer II/III 视版本）
_MP3_SAMPLES_PER_FRAME = {
    (3, 1): 384, (3, 2): 1152, (3, 3): 1152,
    (2, 1): 384, (2, 2): 1152, (2, 3): 576,
    (0, 1): 384, (0, 2): 1152, (0, 3): 576,
}
# MP3 比特率表（kbps），key=(version, layer)
_MP3_BITRATES = {
    (3, 1): [0, 32, 64, 96, 128, 160, 192, 224, 256, 288, 320, 352, 384, 416, 448],
    (3, 2): [0, 32, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 384],
    (3, 3): [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320],
    (2, 1): [0, 32, 48, 56, 64, 80, 96, 112, 128, 144, 160, 176, 192, 224, 256],
    (2, 2): [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160],
    (2, 3): [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160],
    (0, 1): [0, 32, 48, 56, 64, 80, 96, 112, 128, 144, 160, 176, 192, 224, 256],
    (0, 2): [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160],
    (0, 3): [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160],
}


def _probe_mp3(data: bytes) -> Tuple[int, int, float]:
    """MP3 元数据（解析 ID3v2 + MPEG 帧头）。"""
    offset = 0
    # 跳过 ID3v2 标签
    if data.startswith(b"ID3"):
        if len(data) < 10:
            raise InvalidRefAudioError("MP3 ID3 标签不完整")
        size = ((data[6] & 0x7F) << 21) | ((data[7] & 0x7F) << 14) \
            | ((data[8] & 0x7F) << 7) | (data[9] & 0x7F)
        offset = 10 + size

    sample_rate = 0
    channels = 1
    total_frames = 0
    while offset + 4 <= len(data):
        if data[offset] != 0xFF or (data[offset + 1] & 0xE0) != 0xE0:
            offset += 1
            continue
        header = int.from_bytes(data[offset:offset + 4], "big")
        version = (header >> 19) & 0x03
        layer = (header >> 17) & 0x03
        bitrate_idx = (header >> 12) & 0x0F
        sr_idx = (header >> 10) & 0x03
        channel_mode = (header >> 6) & 0x03
        if version == 1 or layer == 0 or bitrate_idx == 0 or bitrate_idx == 15:
            offset += 1
            continue
        sr = _MP3_SAMPLE_RATES.get(version)
        if sr is None or sr_idx >= len(sr):
            offset += 1
            continue
        sample_rate = sr[sr_idx]
        channels = 2 if channel_mode != 3 else 1
        bitrate = _MP3_BITRATES.get((version, layer), [0])[bitrate_idx] * 1000
        spf_key = (version, layer)
        samples = _MP3_SAMPLES_PER_FRAME.get(spf_key, 1152)
        if bitrate <= 0 or sample_rate <= 0:
            offset += 1
            continue
        frame_len = int(144 * bitrate / sample_rate) + (1 if header & 0x0001 else 0)
        if frame_len < 4:
            offset += 1
            continue
        total_frames += 1
        offset += frame_len

    if sample_rate == 0 or total_frames == 0:
        raise InvalidRefAudioError("MP3 解析失败")
    # 首帧可确定采样率/声道；时长用 file_size 估算（存在 ID3 时偏差可忽略）
    duration = total_frames * samples / sample_rate
    return sample_rate, channels, duration


# ============================================================================
# 公开 API（严格匹配 ref_audio_store.pyi）
# ============================================================================

async def register_from_prompt(
    prompt: str, language: Optional[str] = None
) -> RefAudioAsset:
    """调用 Qwen3 VoiceDesign 根据自然语言提示词生成参考音频并持久化元数据（source=prompt）。

    Args:
        prompt: VoiceDesign 自然语言音色描述。
        language: 目标语言（可空，交由生成器解析）。

    Returns:
        已注册的 RefAudioAsset（若 checksum 已存在则复用之）。

    Raises:
        RuntimeUnavailableError: 未注入 prompt 音频生成器（Qwen3 VoiceDesign 运行时未就绪）。
        InvalidRefAudioError: 生成音频元数据非法。
    """
    if not isinstance(prompt, str) or not prompt.strip():
        raise InvalidRefAudioError("prompt 提示词不能为空")

    if _prompt_generator is None:
        raise RuntimeUnavailableError(
            "Qwen3 VoiceDesign 生成运行时未配置（register_from_prompt 依赖 prompt 音频生成器）"
        )

    generated = await _prompt_generator(prompt, language)
    if not isinstance(generated, GeneratedAudio):
        raise InvalidRefAudioError("prompt 生成器返回非 GeneratedAudio")
    audio = generated.audio
    if not audio:
        raise InvalidRefAudioError("prompt 生成器返回空音频")

    checksum = _md5(audio)
    existing = _find_by_checksum(checksum)
    if existing is not None:
        logger.info(f"prompt 资产 checksum 去重命中，复用: {existing.id}")
        return existing

    _validate_audio_meta(
        generated.format, generated.sample_rate, generated.channels,
        generated.duration_seconds, len(audio),
    )

    asset = RefAudioAsset(
        id=_new_id(),
        source="prompt",
        prompt=prompt,
        checksum=checksum,
        format=generated.format,
        sample_rate=generated.sample_rate,
        channels=generated.channels,
        duration_seconds=generated.duration_seconds,
        size_bytes=len(audio),
        status="registered",
        note="",
        created_at=_now_iso(),
    )
    # H8 修复：定稿去重查询移入与 _append_record 同一锁区，消除 TOCTOU——
    # 并发注册同内容音频时只落盘一份（锁内后到者复用先到者）。
    winner: Optional[RefAudioAsset] = None
    with _LOCK:
        winner = _find_by_checksum(checksum)
        if winner is None:
            _atomic_write_bytes(_audio_path_for(asset.id, asset.format), audio)
            _append_record(asset)
    if winner is not None:
        logger.info(f"prompt 资产 checksum 去重命中，复用: {winner.id}")
        return winner
    _emit("ref_audio", "asset_register", {"asset_id": asset.id, "asset": asset.to_dict()})
    logger.info(f"注册 prompt 参考音频资产: {asset.id}")
    return asset


def register_from_file(
    file_path: str, ref_text: Optional[str] = None, note: str = ""
) -> RefAudioAsset:
    """注册外部音频文件为资产（source=file）。

    校验格式/大小/时长/采样率/路径安全，非法抛 InvalidRefAudioError。
    相似内容通过 checksum 去重复用已有资产。

    Args:
        file_path: 位于允许目录内的音频文件路径（相对允许目录或绝对路径）。
        ref_text: 可选参考音频转写（克隆时使用）。
        note: 可选用户注释。

    Returns:
        已注册的 RefAudioAsset（首次注册或 checksum 去重复用）。

    Raises:
        InvalidRefAudioError: 文件非法/路径穿越/元数据越界。
    """
    path = _safe_resolve_file_path(file_path)
    data = path.read_bytes()
    fmt = _detect_format(path, data)

    sample_rate, channels, duration_seconds = _probe_audio(data, fmt)
    _validate_audio_meta(fmt, sample_rate, channels, duration_seconds, len(data))

    checksum = _md5(data)
    existing = _find_by_checksum(checksum)
    if existing is not None:
        logger.info(f"外部文件 checksum 去重命中，复用: {existing.id}")
        return existing

    asset = RefAudioAsset(
        id=_new_id(),
        source="file",
        file_name=path.name,
        ref_text=ref_text or "",
        checksum=checksum,
        format=fmt,
        sample_rate=sample_rate,
        channels=channels,
        duration_seconds=duration_seconds,
        size_bytes=len(data),
        status="registered",
        note=note or "",
        created_at=_now_iso(),
    )
    # H8 修复：定稿去重查询移入与 _append_record 同一锁区，消除 TOCTOU（同 prompt 注册路径）。
    winner: Optional[RefAudioAsset] = None
    with _LOCK:
        winner = _find_by_checksum(checksum)
        if winner is None:
            _atomic_write_bytes(_audio_path_for(asset.id, asset.format), data)
            _append_record(asset)
    if winner is not None:
        logger.info(f"外部文件 checksum 去重命中，复用: {winner.id}")
        return winner
    _emit("ref_audio", "asset_register", {"asset_id": asset.id, "asset": asset.to_dict()})
    logger.info(f"注册外部参考音频资产: {asset.id}")
    return asset


def resolve(asset_id: str) -> RefAudioAsset:
    """按 ID 解析资产。不存在或已删除抛 RefAudioNotFoundError。"""
    asset = get(asset_id)
    if asset is None or asset.is_deleted:
        raise RefAudioNotFoundError(f"参考音频资产不存在或已删除: {asset_id}")
    return asset


def get(asset_id: str) -> Optional[RefAudioAsset]:
    """按 ID 获取资产（含已删除），不存在返回 None。"""
    _validate_asset_id(asset_id)
    for rec in _load_index():
        if rec.get("id") == asset_id:
            return RefAudioAsset.from_dict(rec)
    return None


def list() -> List[RefAudioAsset]:
    """列出全部可用资产（排除 deleted）。"""
    return [
        RefAudioAsset.from_dict(r)
        for r in _load_index()
        if r.get("status") != "deleted"
    ]


def update_note(asset_id: str, note: str) -> RefAudioAsset:
    """更新资产注释。"""
    with _LOCK:
        records = _load_index()
        for rec in records:
            if rec.get("id") == asset_id:
                rec["note"] = note
                _save_index(records)
                return RefAudioAsset.from_dict(rec)
    raise RefAudioNotFoundError(f"参考音频资产不存在: {asset_id}")


def delete(asset_id: str) -> None:
    """删除资产（软删除，status=deleted）。若为当前默认资产，同时清除当前指针。

    被任一 Agent 绑定的资产拒绝删除（抛 AssetBoundError，提示先解绑）。

    并发修复：绑定保护检查移入 ``_LOCK`` 临界区内——旧实现在锁外检查、锁内
    删除，与 ``_apply_binding``（同锁写绑定表）并发时存在 TOCTOU 窗口：
    "检查通过 → set_for_agent 绑定 → 删除照常执行"，产生"资产已删但仍被
    Agent 绑定"的悬挂绑定。_LOCK 为 RLock 可重入，检查函数内部再取锁安全。
    """
    with _LOCK:
        if asset_used_by_any_agent(asset_id):
            raise AssetBoundError(
                f"资产 {asset_id} 被 Agent 绑定，请先解绑再删除"
            )
        records = _load_index()
        for rec in records:
            if rec.get("id") == asset_id:
                rec["status"] = "deleted"
                _save_index(records)
                _clear_current_if_matches(asset_id)
                emit_delete = True
                break
        else:
            emit_delete = False
    if emit_delete:
        _emit("ref_audio", "asset_delete", {"asset_id": asset_id})
        logger.info(f"软删除参考音频资产: {asset_id}")
        return
    raise RefAudioNotFoundError(f"参考音频资产不存在: {asset_id}")


def set_current(asset_id: str) -> RefAudioAsset:
    """将资产设为当前默认参考音频（仅 registered 资产）。

    Args:
        asset_id: 要设为默认的资产 ID。

    Returns:
        被设为当前的 RefAudioAsset。

    Raises:
        RefAudioNotFoundError: 资产不存在或已删除。
    """
    asset = resolve(asset_id)
    _save_current_id(asset.id)
    logger.info(f"设置当前默认参考音频资产: {asset.id}")
    return asset


def get_current() -> Optional[RefAudioAsset]:
    """返回当前默认参考音频资产；未设置或已删除/指针非法返回 None。

    删除当前资产时指针会被自动清除；若指针文件损坏或指向非法 ID，视为未设置。
    """
    asset_id = _load_current_id()
    if not asset_id:
        return None
    try:
        asset = get(asset_id)
    except InvalidRefAudioError:
        return None
    if asset is None or asset.is_deleted:
        return None
    return asset


def clear_current() -> None:
    """清除当前默认参考音频设置（不删除资产本身）。"""
    _save_current_id(None)
    logger.info("清除当前默认参考音频资产")


def exists(checksum: str) -> bool:
    """按 checksum 判断是否已存在（去重，排除已删除）。"""
    return _find_by_checksum(checksum) is not None


def get_audio_path(asset_id: str) -> Path:
    """返回资产音频文件磁盘路径（内部/下游 Provider 使用，不在公开契约）。

    仅返回路径，不读取内容；供推理链路（Task 5 Provider）按需加载音频字节。
    """
    asset = resolve(asset_id)
    fmt = asset.format or "wav"
    return _audio_path_for(asset_id, fmt)


# ============================================================================
# 集群接入：replica 落盘接收端（幂等、不 emit，避免回环）
# ============================================================================

def _apply_asset_register(asset_data: dict) -> bool:
    """按事件落盘资产元数据（asset_register）。已存在则跳过（幂等）。

    H8 修复：load→判重→append→save 的 RMW 三步整体纳入 _LOCK（RLock 可重入，
    内嵌 _load_index/_save_index 自带锁可直接嵌套），消除并发回放丢更新。
    """
    if not isinstance(asset_data, dict) or not asset_data.get("id"):
        return False
    with _LOCK:
        records = _load_index()
        if any(r.get("id") == asset_data["id"] for r in records):
            return False
        records.append(asset_data)
        _save_index(records)
    return True


def _apply_asset_delete(asset_id: str) -> bool:
    """按事件落盘资产软删除（asset_delete）。不存在则跳过（幂等）。"""
    with _LOCK:
        records = _load_index()
        for rec in records:
            if rec.get("id") == asset_id and rec.get("status") != "deleted":
                rec["status"] = "deleted"
                _save_index(records)
                return True
    return False


def build_bindings() -> dict:
    """返回绑定表副本（供快照/对等对齐使用）。"""
    return _load_bindings()


def build_snapshot() -> dict:
    """打包 ref_audio_assets 为可序列化快照 blob（供快照落盘/对等对齐）。

    返回 dict：{version, checksum, assets(list), bindings(dict), audio{id: base64}}。

    H8b 修复：两阶段采集——阶段一在 _LOCK 内仅固化资产元数据清单、绑定表与待读
    路径列表；阶段二在锁外读取音频文件并 base64 编码。此前实现持全局锁完成全部
    音频读取，大资产目录下会长时间阻塞所有注册/绑定路径。音频并发覆盖安全性由
    _atomic_write_bytes 的 tmp+os.replace 原子替换保证（读到完整旧值或完整新值）。
    """
    import copy

    with _LOCK:
        records = _load_index()
        assets = copy.deepcopy([r for r in records if r.get("status") != "deleted"])
        bindings = _load_bindings()
        pending_paths = []
        for rec in records:
            aid = rec.get("id")
            fmt = rec.get("format") or "wav"
            pending_paths.append((aid, _audio_path_for(aid, fmt)))

    # 锁外编码音频（仅读文件，无索引/绑定写竞争）
    audio: dict = {}
    for aid, path in pending_paths:
        try:
            if path.exists():
                audio[aid] = base64.b64encode(path.read_bytes()).decode("ascii")
        except OSError as e:  # noqa: PERF203 - 单文件读取失败不阻断快照
            logger.warning(f"快照读取音频文件失败 asset={aid}: {e}")
    canon = json.dumps({"assets": assets, "bindings": bindings}, ensure_ascii=False, sort_keys=True)
    return {
        "version": _SNAPSHOT_VERSION,
        "checksum": _md5(canon.encode("utf-8")),
        "assets": assets,
        "bindings": bindings,
        "audio": audio,
    }


def restore_snapshot(blob: dict) -> None:
    """从快照 blob 解包写入本机 ref_audio_assets（资产音频 + 索引 + 绑定）。"""
    with _LOCK:
        assets = blob.get("assets", [])
        bindings = blob.get("bindings", {})
        audio = blob.get("audio", {}) or {}
        _save_index(builtins.list(assets))
        _save_bindings(dict(bindings))
        for aid, b64 in audio.items():
            fmt = next((a.get("format", "wav") for a in assets if a.get("id") == aid), "wav")
            try:
                data = base64.b64decode(b64)
            except Exception:  # noqa: BLE001
                continue
            _atomic_write_bytes(_audio_path_for(aid, fmt), data)
