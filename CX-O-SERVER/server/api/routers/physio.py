"""CX-O-Dream 生理信号 REST 端点（前端 DreamPage 生理信号区块依赖）。

- POST  /physio/hr                 前端上送 HR 样本 {bpm, ts, device_fingerprint}（仅内存）
- POST  /physio/state              前端上送系统状态 {system_idle_sec, user_active}
- GET   /physio/status             采集/估计器/融合状态（未启用返回 {"status":"disabled"}，不抛错）
- GET   /physio/sleep              当前 SleepSensor 状态 + 各信号 value/weight + confidence
- GET   /physio/devices            已配对设备列表 {name, fingerprint(脱敏展示), id(真实指纹仅供 forget)}
- POST  /physio/devices/{id}/forget  解除配对（404 若不存在；须传真实指纹 id，脱敏展示指纹不可用）
- GET/PUT /physio/config           读 / 深度合并更新 physio 配置（model_validate 非法 422）
- POST  /physio/clear              一键清除生理基线（含 audit 记录）

依赖注入对齐 dream.py / autonomy.py 模式：模块级 `_runtime` 全局 + `set_physio_runtime`
注入函数，由 server/main.py 装配成功后注入。runtime 为 None（未装配）或未启用时
所有依赖引擎的端点以 disabled 口径响应（不抛 500）。配置读写走独立 config 模块
（load_config/save_config），不依赖 runtime 实例，始终可用。

runtime 契约（Task 4 装配，路由侧以 getattr 容忍缺失）：
    .estimator / .store / .is_enabled() / .get_config() / .set_config()
    .sleep_sensor（可选，snapshot() 返回融合状态）
    .update_system_state(system_idle_sec, user_active)（可选，S1/S6 provider 输入）
    .get_devices() / .forget_device(fp)（可选，设备配对管理）
任何运行时异常被捕获隔离（异常隔离），绝不影响主服务与梦境主流程（隐私红线 R6）。
"""
import logging
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ValidationError

from server.autonomy.dream.config import DreamConfig, load_config, save_config

logger = logging.getLogger(__name__)

router = APIRouter()

_runtime = None


def get_physio_runtime():
    """返回模块级 PhysioRuntime 单例（未设置时为 None）。"""
    return _runtime


def set_physio_runtime(runtime):
    """设置 PhysioRuntime 实例。"""
    global _runtime
    _runtime = runtime


class HrSampleRequest(BaseModel):
    """HR 样本：{"bpm": float, "ts": Any, "device_fingerprint": str|None}。"""

    bpm: float
    ts: Any = None
    device_fingerprint: Optional[str] = None


class SystemStateRequest(BaseModel):
    """系统状态：{"system_idle_sec": float|None, "user_active": bool|None}。"""

    system_idle_sec: Optional[float] = None
    user_active: Optional[bool] = None


def _runtime_ready() -> bool:
    """返回 physio runtime 是否已装配且启用（is_enabled()）。"""
    runtime = _runtime
    if runtime is None:
        return False
    is_enabled = getattr(runtime, "is_enabled", None)
    if callable(is_enabled):
        return bool(is_enabled())
    return bool(getattr(runtime, "enabled", False))


def _runtime_config(runtime) -> Any:
    """读取 runtime 当前配置；缺失/异常时回退独立配置模块（始终可读）。"""
    getter = getattr(runtime, "get_config", None)
    if callable(getter):
        try:
            cfg = getter()
            if cfg is not None:
                return cfg
        except Exception as e:
            logger.warning("读取 physio runtime 配置失败（异常隔离）: %s", e)
    return load_config()


def _notify_runtime_config(runtime, updated: DreamConfig) -> None:
    """将更新后的配置应用到运行中 runtime（enabled 变更生效，尽力而为）。"""
    if runtime is None:
        return
    setter = getattr(runtime, "set_config", None)
    if not callable(setter):
        return
    try:
        setter(updated)
    except Exception as e:
        logger.warning("physio 运行期配置应用失败（尽力而为）: %s", e)


def _mask_fp(fp: Any) -> str:
    """设备指纹脱敏：前 8 位 + ****（隐私红线 R6）。"""
    fp = str(fp or "")
    if len(fp) <= 8:
        return f"{fp}****"
    return f"{fp[:8]}****"


def _list_paired_devices(runtime) -> list:
    """收集已配对设备 [{"name": str|None, "id": str}]。

    优先 runtime.get_devices()（每项可为 str 或 dict：dict 读取
    id/fingerprint/device_fingerprint 作为真实指纹、name/device_name 作为名称）；
    缺失/异常时回退配置中的单指纹 device_fingerprint（id=config.device_fingerprint）。
    返回的 id 为**真实指纹**，仅供 forget 端点使用；展示脱敏由调用方完成。
    任何异常被捕获隔离。
    """
    getter = getattr(runtime, "get_devices", None)
    if callable(getter):
        try:
            raw = getter() or []
        except Exception as e:
            logger.warning("读取已配对设备失败（异常隔离）: %s", e)
            raw = []
        devices = []
        for item in raw:
            if isinstance(item, dict):
                fp = item.get("id") or item.get("fingerprint") or item.get("device_fingerprint")
                name = item.get("name") or item.get("device_name")
            else:
                fp, name = item, None
            if fp:
                devices.append({"name": name, "id": str(fp)})
        return devices
    cfg = _runtime_config(runtime)
    fp = getattr(cfg, "device_fingerprint", None)
    if fp:
        return [{"name": getattr(cfg, "device_name_hint", None) or None, "id": str(fp)}]
    return []


def _forget_fp(runtime, fp: str) -> bool:
    """尝试解除配对（runtime.forget_device → 回退配置移除），返回是否确实移除。"""
    method = getattr(runtime, "forget_device", None)
    if callable(method):
        try:
            if method(fp):
                return True
        except Exception as e:
            logger.warning("runtime 解除配对异常（异常隔离，回退配置移除）: %s", e)
    # 回退：从配置移除单指纹
    cfg = load_config()
    if getattr(cfg.physio, "device_fingerprint", None) != fp:
        return False
    new_physio = cfg.physio.model_copy(update={"device_fingerprint": None})
    updated = cfg.model_copy(update={"physio": new_physio})
    save_config(updated)
    _notify_runtime_config(runtime, updated)
    return True


def _write_audit(action: str, **fields) -> None:
    """写入审计日志（异常隔离；AuditStore 未装配时静默跳过）。"""
    try:
        from server.autonomy.main import get_audit_store

        store = get_audit_store()
        if store is None or not hasattr(store, "append"):
            return
        entry: Dict[str, Any] = {
            "timestamp": datetime.now().isoformat(),
            "action": action,
            **fields,
        }
        store.append(entry)
    except Exception as e:
        logger.warning("physio 审计写入失败（异常隔离）: %s", e)


# ---------------------------------------------------------------- HR 上报
@router.post("/physio/hr")
def ingest_hr(body: HrSampleRequest):
    """接收前端上送的一个 HR 样本（仅内存，不落盘）。

    runtime 未装配或未启用返回 {"status": "disabled"}（HTTP 200，不抛错）；
    启用时将样本送入估计器，返回 {hr_sleep_confidence}。估计器异常被捕获隔离，
    不影响主服务。
    """
    runtime = _runtime
    if not _runtime_ready():
        return {"status": "disabled"}
    estimator = getattr(runtime, "estimator", None)
    if estimator is None or not hasattr(estimator, "ingest"):
        return {"status": "disabled"}
    ts = body.ts if body.ts is not None else datetime.now()
    try:
        confidence = estimator.ingest(body.bpm, ts)
    except Exception as e:
        logger.warning("HR 样本处理异常（异常隔离）: %s", e)
        confidence = 0.0
        try:
            state = estimator.get_state()
            confidence = state.get("hr_sleep_confidence", 0.0)
        except Exception:
            pass
    if body.device_fingerprint:
        logger.debug("HR 样本来自设备 %s", _mask_fp(body.device_fingerprint))
    return {"hr_sleep_confidence": confidence}


# ---------------------------------------------------------------- 系统状态上报
@router.post("/physio/state")
def ingest_state(body: SystemStateRequest):
    """接收前端上送的系统状态，更新 runtime 的 S1/S6 provider 输入。

    runtime 无此能力（未装配或缺少 update_system_state）时仅记录，返回
    {"ok": true}，不抛错。
    """
    runtime = _runtime
    method = getattr(runtime, "update_system_state", None)
    if callable(method):
        try:
            method(system_idle_sec=body.system_idle_sec, user_active=body.user_active)
        except Exception as e:
            logger.warning("系统状态更新失败（异常隔离）: %s", e)
    else:
        logger.debug(
            "physio runtime 无 update_system_state 能力，仅记录状态: idle_sec=%s active=%s",
            body.system_idle_sec,
            body.user_active,
        )
    return {"ok": True}


# ---------------------------------------------------------------- 状态 / 睡眠 / 设备
@router.get("/physio/status")
def get_status():
    """返回采集/估计器/融合状态快照。

    未装配或未启用（physio.enabled=False）时返回 {"status": "disabled"}，
    HTTP 200，不抛错。
    """
    runtime = _runtime
    if not _runtime_ready():
        return {"status": "disabled"}
    enabled = bool(runtime.is_enabled())
    cfg = _runtime_config(runtime)
    collector = {
        "backend": getattr(cfg, "backend", "noble"),
        "device_fingerprint": getattr(cfg, "device_fingerprint", None),
        "device_name_hint": getattr(cfg, "device_name_hint", ""),
    }
    collector_state = getattr(runtime, "get_collector_state", None)
    if callable(collector_state):
        try:
            collector.update(collector_state() or {})
        except Exception as e:
            logger.warning("读取采集器状态失败（异常隔离）: %s", e)
    estimator = getattr(runtime, "estimator", None)
    estimator_state = {}
    if estimator is not None and hasattr(estimator, "get_state"):
        try:
            estimator_state = estimator.get_state()
        except Exception as e:
            logger.warning("读取估计器状态失败（异常隔离）: %s", e)
    return {
        "status": getattr(runtime, "status", None) or ("active" if enabled else "disabled"),
        "enabled": enabled,
        "collector": collector,
        "estimator": estimator_state,
    }


_DEFAULT_SLEEP_STATE = {"state": "AWAKE", "signals": [], "confidence": 0.0}


@router.get("/physio/sleep")
def get_sleep():
    """返回当前 SleepSensor 融合状态 + 各信号 value/weight + confidence。

    未装配/未启用返回 {"status": "disabled"}；runtime 无 sleep_sensor 时返回
    默认清醒态 {"state": "AWAKE", "signals": [], "confidence": 0.0}。
    """
    runtime = _runtime
    if not _runtime_ready():
        return {"status": "disabled"}
    sensor = getattr(runtime, "sleep_sensor", None)
    if sensor is not None and hasattr(sensor, "snapshot"):
        try:
            return sensor.snapshot()
        except Exception as e:
            logger.warning("读取 SleepSensor 状态失败（异常隔离，回退默认清醒态）: %s", e)
    return dict(_DEFAULT_SLEEP_STATE)


@router.get("/physio/devices")
def list_devices():
    """返回已配对设备列表 {name, fingerprint, id}。

    - name：设备名（device_name_hint，可能为 null）
    - fingerprint：脱敏展示（前 8 位 + ****，隐私红线 R6），**不可用于 forget**
    - id：真实指纹，仅供 forget 端点使用（forget 精确匹配真实指纹，脱敏值会 404）

    未装配/未启用返回 {"devices": []}，不抛错。
    """
    runtime = _runtime
    if not _runtime_ready():
        return {"devices": []}
    devices = _list_paired_devices(runtime)
    return {
        "devices": [
            {
                "name": device.get("name"),
                "fingerprint": _mask_fp(device["id"]),
                "id": device["id"],
            }
            for device in devices
        ]
    }


@router.post("/physio/devices/{fp}/forget")
def forget_device(fp: str):
    """解除配对：从 runtime 或配置中移除该设备指纹。

    指纹未配对（不存在）返回 404。无论是否启用均可操作（配置始终可读）。
    """
    removed = _forget_fp(_runtime, fp)
    if not removed:
        raise HTTPException(status_code=404, detail=f"设备 {fp} 未配对")
    return {"status": "ok", "fingerprint": fp}


# ---------------------------------------------------------------- 配置
@router.get("/physio/config")
def get_config():
    """返回当前 physio 配置（PhysioConfig.model_dump）。

    独立配置模块（load_config），不依赖 runtime 实例，未启用也可读。
    """
    return load_config().physio.model_dump()


def _deep_merge(base: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    """递归合并：patch 中的 dict 与 base 中同名 dict 深度合并，其余键整体覆盖。

    用于局部更新配置时保留嵌套子对象（physio 等）未被提交的字段，
    配合 model_validate 自动补齐缺失字段。
    """
    result = dict(base)
    for key, value in (patch or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


@router.put("/physio/config")
async def update_config(partial: Dict[str, Any]):
    """局部更新 physio 配置并保存（自动补齐缺失字段）。

    以当前配置为基础做深度合并后经 DreamConfig.model_validate 校验；非法字段
    （extra="forbid"）、store_raw_hr=true（隐私红线 R6）返回 422。运行期 enabled
    变更尽力应用到已装配 runtime（set_config）。
    """
    current = load_config().model_dump()
    # /physio/config 的字段即 physio 子节字段；兼容直接提交 {"physio": {...}} 形式
    patch = partial if "physio" in partial else {"physio": partial}
    merged = _deep_merge(current, patch)
    try:
        updated = DreamConfig.model_validate(merged)
    except (ValidationError, ValueError) as e:
        raise HTTPException(status_code=422, detail=f"配置字段非法: {e}") from e

    save_config(updated)
    _notify_runtime_config(_runtime, updated)
    return updated.physio.model_dump()


# ---------------------------------------------------------------- 一键清除
@router.post("/physio/clear")
def clear_physio():
    """一键清除全部生理基线数据（含 base_hr 与设备指纹）并写审计。

    runtime 或 store 未装配时返回 {"ok": true, "cleared": false}（不抛错），
    审计记录 clear 结果。
    """
    runtime = _runtime
    cleared = False
    store = getattr(runtime, "store", None) if runtime is not None else None
    if store is not None and hasattr(store, "clear"):
        try:
            store.clear()
            cleared = True
        except Exception as e:
            logger.warning("一键清除生理基线失败（异常隔离）: %s", e)
    _write_audit(
        "physio.clear",
        result="success" if cleared else "failed",
        cleared=cleared,
    )
    return {"ok": True, "cleared": cleared}
