"""per-agent 预设存储服务（情感TTS预设 + 动作预设，"快捷指令"机制）。

Spec: .trae/specs/enhance-emotion-tts-and-action-presets/spec.md「per-agent 预设」Requirement。
Task 3 范围：仅存储/查询/删除服务（引用展开与提示词注入属 Task 4，不在此实现）。

存储布局（路径锚定项目根，禁止相对路径，与 voiceprint_service 的 _PROJECT_ROOT 模式一致）：
- ``data/presets/{agent_id}/emotion_presets.json`` —— 情感TTS预设
- ``data/presets/{agent_id}/action_presets.json`` —— 动作预设
文件内容统一为 ``{"version": 1, "presets": {name: preset}}`` 键值映射，name 唯一。

字段契约：
- 情感预设：``{name, text(语气描述), speed(0.5~2.0, 默认1.0), volume(0.1~2.0, 默认1.0),
  description, created_at, updated_at}``
- 动作预设：``{name, tags(字符串数组，每项须为 "[...]" 标签形式), description,
  created_at, updated_at}``

并发与安全：
- agent_id 强校验（``[A-Za-z0-9_-]{1,64}``），杜绝路径穿越；
- 所有读改写经进程级 ``threading.RLock`` 串行化（项目教训：JSON 读改写并发会互相覆盖）；
- 写入统一 tmp + ``os.replace`` 原子替换，防并发写坏 JSON；
- 读路径带 mtime 失效缓存，保存/删除后立即刷新缓存。

异常风格：入参非法抛 ``ValueError``（含明确中文错误信息）；删除不存在的预设返回 ``False``。
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 路径锚点（rules-0 §三：禁止相对路径/CWD 依赖）
# 本文件位于 <CX-O-SERVER>/server/services/ → _PROJECT_ROOT = <CX-O-SERVER>（上 2 级）
# ---------------------------------------------------------------------------
_THIS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _THIS_DIR.parent.parent
_PRESETS_ROOT = _PROJECT_ROOT / "data" / "presets"

_EMOTION_FILENAME = "emotion_presets.json"
_ACTION_FILENAME = "action_presets.json"

# 预设类别常量（工具/路由层统一引用）
KIND_EMOTION = "emotion"
KIND_ACTION = "action"
VALID_KINDS = (KIND_EMOTION, KIND_ACTION)

# agent_id 安全校验：仅允许字母/数字/下划线/连字符，1~64 位，防路径穿越与非法目录名
AGENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

# 入参校验上限
NAME_MAX_LEN = 50
TEXT_MAX_LEN = 200
TAG_MAX_LEN = 200
DESCRIPTION_MAX_LEN = 200

# 数值参数收敛范围（spec：speed 0.5~2.0 默认1.0；volume 0.1~2.0 默认1.0）
SPEED_MIN, SPEED_MAX = 0.5, 2.0
VOLUME_MIN, VOLUME_MAX = 0.1, 2.0
DEFAULT_SPEED = 1.0
DEFAULT_VOLUME = 1.0

# 存储文件格式版本
_STORAGE_VERSION = 1

# 进程级可重入锁：串行化所有读改写路径（仅普通线程锁，兼容同步/异步混用调用）
_LOCK = threading.RLock()

# 读缓存：{(agent_id, kind): {"mtime_ns": int, "size": int, "presets": {name: preset}}}
# 写路径（save/delete）持锁更新，读路径经 mtime+size 失效（兼容外部手工编辑）。
_CACHE: Dict[Tuple[str, str], Dict[str, Any]] = {}


class PresetValidationError(ValueError):
    """预设入参校验失败（继承 ValueError，保持服务层异常风格单一）。"""


# ---------------------------------------------------------------------------
# 内部工具函数
# ---------------------------------------------------------------------------

def _validate_agent_id(agent_id: str) -> str:
    """校验 agent_id 并原样返回；非法抛 PresetValidationError（防路径穿越）。"""
    if not isinstance(agent_id, str) or not AGENT_ID_PATTERN.match(agent_id):
        raise PresetValidationError(
            f"非法 agent_id: {agent_id!r}（仅允许字母/数字/下划线/连字符，长度 1~64）"
        )
    return agent_id


def _now_iso() -> str:
    """当前时间 ISO 字符串（与项目其他 JSON 存储时间戳风格一致）。"""
    return datetime.now().isoformat()


def _presets_file(agent_id: str, kind: str) -> Path:
    """定位某 agent 某类预设的存储文件（调用前须已通过 _validate_agent_id）。"""
    if kind not in VALID_KINDS:
        raise PresetValidationError(f"非法预设类别: {kind!r}（须为 {VALID_KINDS} 之一）")
    filename = _EMOTION_FILENAME if kind == KIND_EMOTION else _ACTION_FILENAME
    return _PRESETS_ROOT / agent_id / filename


def _load_mapping(agent_id: str, kind: str) -> Dict[str, Dict[str, Any]]:
    """读取某 agent 某类预设的 name→preset 映射（带缓存；文件缺失/损坏返回空）。"""
    path = _presets_file(agent_id, kind)
    try:
        stat = path.stat()
        cache_key = (agent_id, kind)
        cached = _CACHE.get(cache_key)
        if (
            cached is not None
            and cached["mtime_ns"] == stat.st_mtime_ns
            and cached["size"] == stat.st_size
        ):
            return cached["presets"]
    except OSError:
        # 文件不存在：无缓存可命中
        cached = _CACHE.get((agent_id, kind))
        if cached is not None and cached.get("mtime_ns") is None:
            return cached["presets"]
        return {}

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        presets = raw.get("presets", {}) if isinstance(raw, dict) else {}
        if not isinstance(presets, dict):
            presets = {}
    except (OSError, json.JSONDecodeError) as e:
        logger.error(f"读取预设文件失败（返回空集）: {path} -> {e}")
        presets = {}

    try:
        stat = path.stat()
        mtime_ns: Optional[int] = stat.st_mtime_ns
        size: Optional[int] = stat.st_size
    except OSError:
        mtime_ns, size = None, None
    _CACHE[(agent_id, kind)] = {"mtime_ns": mtime_ns, "size": size, "presets": presets}
    return presets


def _atomic_write_mapping(agent_id: str, kind: str, presets: Dict[str, Dict[str, Any]]) -> None:
    """原子写某 agent 某类预设映射（tmp + os.replace），并同步刷新缓存。须持锁调用。"""
    path = _presets_file(agent_id, kind)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".json.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(
                {"version": _STORAGE_VERSION, "presets": presets},
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

    # 写后刷新缓存（mtime/size 以落盘后的真实 stat 为准）
    try:
        stat = path.stat()
        mtime_ns, size = stat.st_mtime_ns, stat.st_size
    except OSError:
        mtime_ns, size = None, None
    _CACHE[(agent_id, kind)] = {"mtime_ns": mtime_ns, "size": size, "presets": presets}


def _clamp_number(value: Any, name: str, lo: float, hi: float, default: float) -> float:
    """数值收敛：非数值抛错；可转换数值收敛（clamp）到 [lo, hi]；None 取默认值。"""
    if value is None:
        return default
    try:
        num = float(value)
    except (TypeError, ValueError):
        raise PresetValidationError(f"{name} 须为数值，收到: {value!r}")
    if math.isnan(num) or math.isinf(num):
        raise PresetValidationError(f"{name} 须为有限数值，收到: {value!r}")
    return max(min(num, hi), lo)


def _validate_name(name: Any) -> str:
    """name 校验：非空字符串且 ≤50 字符。"""
    if not isinstance(name, str) or not name.strip():
        raise PresetValidationError("预设名 name 不能为空")
    if len(name) > NAME_MAX_LEN:
        raise PresetValidationError(f"预设名 name 过长（>{NAME_MAX_LEN} 字符）")
    return name


def _validate_description(description: Any) -> str:
    """description 校验：可选字符串且 ≤200 字符。"""
    if description is None:
        return ""
    if not isinstance(description, str):
        raise PresetValidationError("description 须为字符串")
    if len(description) > DESCRIPTION_MAX_LEN:
        raise PresetValidationError(f"description 过长（>{DESCRIPTION_MAX_LEN} 字符）")
    return description


def _validate_text(text: Any) -> str:
    """情感预设 text（语气描述）校验：非空字符串且 ≤200 字符。"""
    if not isinstance(text, str) or not text.strip():
        raise PresetValidationError("语气描述 text 不能为空")
    if len(text) > TEXT_MAX_LEN:
        raise PresetValidationError(f"语气描述 text 过长（>{TEXT_MAX_LEN} 字符）")
    return text


def _validate_tags(tags: Any) -> List[str]:
    """动作预设 tags 校验：非空字符串数组，每项非空 ≤200 字符且为 "[...]" 标签形式。"""
    if not isinstance(tags, list) or not tags:
        raise PresetValidationError("tags 须为非空字符串数组（每项如 \"[emotion:happy]\"）")
    validated: List[str] = []
    for tag in tags:
        if not isinstance(tag, str) or not tag.strip():
            raise PresetValidationError(f"tags 每项须为非空字符串，收到: {tag!r}")
        if len(tag) > TAG_MAX_LEN:
            raise PresetValidationError(f"标签过长（>{TAG_MAX_LEN} 字符）: {tag[:50]}...")
        if not (tag.startswith("[") and tag.endswith("]") and len(tag) >= 2):
            raise PresetValidationError(f'标签须为 "[...]" 形式（如 "[action:wave]"），收到: {tag!r}')
        validated.append(tag)
    return validated


def _list_sorted(presets: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """映射转列表，按 name 升序（项目 sorting 规范：ascending）。"""
    return [presets[name] for name in sorted(presets.keys())]


# ---------------------------------------------------------------------------
# 情感TTS预设 API
# ---------------------------------------------------------------------------

def list_emotion_presets(agent_id: str) -> List[Dict[str, Any]]:
    """列出某 agent 的全部情感TTS预设（按 name 升序）。"""
    with _LOCK:
        return _list_sorted(_load_mapping(_validate_agent_id(agent_id), KIND_EMOTION))


def get_emotion_preset(agent_id: str, name: str) -> Optional[Dict[str, Any]]:
    """按 name 获取某 agent 的情感TTS预设；不存在返回 None。"""
    if not isinstance(name, str):
        return None
    with _LOCK:
        return _load_mapping(_validate_agent_id(agent_id), KIND_EMOTION).get(name)


def save_emotion_preset(
    agent_id: str,
    name: str,
    text: str,
    speed: Any = None,
    volume: Any = None,
    description: str = "",
) -> Dict[str, Any]:
    """保存（新增或原子覆盖）某 agent 的情感TTS预设，返回落盘后的完整预设。

    语义：name 唯一，重复保存覆盖同 name 预设（created_at 保留原值，updated_at 刷新）。
    speed/volume 非法（非有限数值）抛 PresetValidationError；越界值收敛到合法区间。
    """
    _validate_agent_id(agent_id)
    _validate_name(name)
    _validate_text(text)
    _validate_description(description)
    speed_v = _clamp_number(speed, "speed", SPEED_MIN, SPEED_MAX, DEFAULT_SPEED)
    volume_v = _clamp_number(volume, "volume", VOLUME_MIN, VOLUME_MAX, DEFAULT_VOLUME)

    with _LOCK:
        presets = _load_mapping(agent_id, KIND_EMOTION)
        existing = presets.get(name)
        now = _now_iso()
        preset = {
            "name": name,
            "text": text,
            "speed": speed_v,
            "volume": volume_v,
            "description": description,
            "created_at": existing["created_at"] if existing else now,
            "updated_at": now,
        }
        presets[name] = preset
        _atomic_write_mapping(agent_id, KIND_EMOTION, presets)
        return dict(preset)


def delete_emotion_preset(agent_id: str, name: str) -> bool:
    """删除某 agent 的情感TTS预设；存在返回 True，不存在返回 False。"""
    if not isinstance(name, str) or not name:
        return False
    with _LOCK:
        presets = _load_mapping(_validate_agent_id(agent_id), KIND_EMOTION)
        if name not in presets:
            return False
        del presets[name]
        _atomic_write_mapping(agent_id, KIND_EMOTION, presets)
        return True


# ---------------------------------------------------------------------------
# 动作预设 API（与情感预设同构）
# ---------------------------------------------------------------------------

def list_action_presets(agent_id: str) -> List[Dict[str, Any]]:
    """列出某 agent 的全部动作预设（按 name 升序）。"""
    with _LOCK:
        return _list_sorted(_load_mapping(_validate_agent_id(agent_id), KIND_ACTION))


def get_action_preset(agent_id: str, name: str) -> Optional[Dict[str, Any]]:
    """按 name 获取某 agent 的动作预设；不存在返回 None。"""
    if not isinstance(name, str):
        return None
    with _LOCK:
        return _load_mapping(_validate_agent_id(agent_id), KIND_ACTION).get(name)


def save_action_preset(
    agent_id: str,
    name: str,
    tags: List[str],
    description: str = "",
) -> Dict[str, Any]:
    """保存（新增或原子覆盖）某 agent 的动作预设，返回落盘后的完整预设。

    语义：name 唯一，重复保存覆盖同 name 预设（created_at 保留原值，updated_at 刷新）。
    """
    _validate_agent_id(agent_id)
    _validate_name(name)
    _validate_description(description)
    tags_v = _validate_tags(tags)

    with _LOCK:
        presets = _load_mapping(agent_id, KIND_ACTION)
        existing = presets.get(name)
        now = _now_iso()
        preset = {
            "name": name,
            "tags": tags_v,
            "description": description,
            "created_at": existing["created_at"] if existing else now,
            "updated_at": now,
        }
        presets[name] = preset
        _atomic_write_mapping(agent_id, KIND_ACTION, presets)
        return dict(preset)


def delete_action_preset(agent_id: str, name: str) -> bool:
    """删除某 agent 的动作预设；存在返回 True，不存在返回 False。"""
    if not isinstance(name, str) or not name:
        return False
    with _LOCK:
        presets = _load_mapping(_validate_agent_id(agent_id), KIND_ACTION)
        if name not in presets:
            return False
        del presets[name]
        _atomic_write_mapping(agent_id, KIND_ACTION, presets)
        return True


# ---------------------------------------------------------------------------
# 聚合查询（管理 API 与 list_presets 工具共用）
# ---------------------------------------------------------------------------

def list_all_presets(agent_id: str) -> Dict[str, List[Dict[str, Any]]]:
    """一次返回某 agent 两类预设（按 name 各自升序），供 GET /api/presets/{agent_id} 使用。"""
    _validate_agent_id(agent_id)
    with _LOCK:
        return {
            KIND_EMOTION: _list_sorted(_load_mapping(agent_id, KIND_EMOTION)),
            KIND_ACTION: _list_sorted(_load_mapping(agent_id, KIND_ACTION)),
        }
