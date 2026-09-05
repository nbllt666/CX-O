"""
跨类型训练互斥原语（共享注册表）

change-id: extend-modelstation-standalone-melotts-datasets（spec「MeloTTS 微调训练」：
训练互斥——与 So-VITS-SVC 训练共享「同一时间仅一个训练任务」约束）。

设计要点：
- 进程级注册表（单条目）：同一时刻至多一个训练任务（不限类型）；
  键为 owner_type（sovits_svc / melotts），值为 {owner_type, task_id, started_at}。
- 用 threading.Lock 保护 dict 的读写（临界区内无 await，短临界区不阻塞事件循环）；
  不用 asyncio.Lock——原语需被 sovits/melotts 两个 api 模块共享，
  且 sovits 侧现有 _train_lock 亦为 threading.Lock（语义对齐）。
- 部署要求：单 worker（uvicorn --workers 1），注册表为进程内存状态，不跨进程共享
  （与 api/sovits_svc.py 的模块级状态约束一致）。

owner_type 常量（冻结）：
  TRAINING_SOVITS_SVC = "sovits_svc"
  TRAINING_MELOTTS   = "melotts"
"""
from __future__ import annotations

import threading
from datetime import datetime
from typing import Optional

TRAINING_SOVITS_SVC = "sovits_svc"
TRAINING_MELOTTS = "melotts"

# 保护 _REGISTRY 读写的进程级锁（临界区内无 await）
_GUARD = threading.Lock()

# 注册表：owner_type -> {owner_type, task_id, started_at}；
# 空dict = 无训练进行中。全局单条目语义（同一时间仅一个训练任务）。
_REGISTRY: dict[str, dict] = {}


def _now_iso() -> str:
    """本地时区 ISO8601 时间戳（秒级）"""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def try_begin_training(owner_type: str, task_id: Optional[str]) -> tuple[bool, Optional[dict]]:
    """尝试占用训练互斥（全局唯一训练槽位）。

    Args:
        owner_type: 训练类型标识（TRAINING_SOVITS_SVC / TRAINING_MELOTTS）
        task_id: 任务标识；占用方尚无最终 task_id 时可为 None
                 （如 sovits train 端点在 trainer 生成 task_id 前占位，
                 后续经 update_training_task 回填真实值）

    Returns:
        (ok, current)：ok=True 表示占用成功（current 为 None）；
        ok=False 表示已有训练进行中（current 为当前注册表条目的浅拷贝）。
    """
    with _GUARD:
        if _REGISTRY:
            current = dict(next(iter(_REGISTRY.values())))
            return False, current
        _REGISTRY[owner_type] = {
            "owner_type": owner_type,
            "task_id": task_id,
            "started_at": _now_iso(),
        }
        return True, None


def update_training_task(owner_type: str, task_id: str) -> bool:
    """回填占用方的真实 task_id（仅当该 owner 仍持有槽位时生效）。

    场景：sovits train 端点先以 task_id=None 占位（trainer 内部才生成
    最终 task_id），start_training 成功返回后回填，保证 409 冲突响应
    携带可追溯的任务标识。

    Returns:
        True=回填成功；False=该 owner 已不持有槽位（不写入）。
    """
    with _GUARD:
        entry = _REGISTRY.get(owner_type)
        if entry is None:
            return False
        entry["task_id"] = task_id
        return True


def end_training(owner_type: str) -> bool:
    """释放训练互斥（幂等）。

    仅当注册表当前持有者即 owner_type 时才清除（防止迟到的释放误清
    其他类型的新占用）。重复调用或无占用时安全返回 False。

    Returns:
        True=本次调用实际释放；False=无匹配占用（幂等无害）。
    """
    with _GUARD:
        if _REGISTRY.get(owner_type) is not None:
            del _REGISTRY[owner_type]
            return True
        return False


def current_training() -> Optional[dict]:
    """查询当前训练占用（浅拷贝）；无训练时返回 None。"""
    with _GUARD:
        if _REGISTRY:
            return dict(next(iter(_REGISTRY.values())))
        return None


def reset_registry() -> None:
    """清空注册表（测试专用）。"""
    with _GUARD:
        _REGISTRY.clear()
