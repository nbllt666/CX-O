"""CX-A 批量编排（对齐 cx_admin.pyi AdminBatchExecutor 契约；返回结构对齐
public/schema/admin_batch.schema.json）。
"""
import asyncio
import inspect
import time
from typing import Any, Dict, List

from server.core.admin.control_plane import resolve_invoke_result


class AdminBatchExecutor:
    """批量编排。mode=sequential 按序执行，parallel 并行执行。

    每步为 dict {target, action, agent_id?, params?}，委托 control_plane.dispatch。
    返回 {"mode": ..., "steps": [{"step", "ok", "result", "duration_ms"}]}。
    """

    def __init__(self, control_plane):
        self.control_plane = control_plane

    async def execute(self, request_id: str, mode: str, steps: List[Dict[str, Any]], stop_on_error: bool = True) -> Dict[str, Any]:
        """按 mode 编排执行 steps。任一步异常/失败均置 ok=False。"""
        results: List[Dict[str, Any]] = []

        if mode == "sequential":
            for idx, step in enumerate(steps):
                res = await self._run_step(idx, step, request_id)
                results.append(res)
                if stop_on_error and not res["ok"]:
                    break
        elif mode == "parallel":
            if not steps:
                results = []
            else:
                gathered = await asyncio.gather(
                    *(self._run_step(idx, step, request_id) for idx, step in enumerate(steps))
                )
                results = list(gathered)
        else:
            raise ValueError(f"未知批量编排 mode: {mode!r}")

        return {"mode": mode, "steps": results}

    async def _run_step(self, idx: int, step: Dict[str, Any], request_id: str) -> Dict[str, Any]:
        t0 = time.monotonic()
        ok = False
        result: Any = {"error": "step 缺少 target/action"}
        try:
            target = step.get("target")
            action = step.get("action")
            agent_id = step.get("agent_id", "default")
            params = step.get("params", {}) or {}
            if not target or not action:
                result = {"error": "step 缺少 target/action"}
            else:
                result = self.control_plane.dispatch(
                    action=action,
                    target=target,
                    request_id=request_id,
                    agent_id=agent_id,
                    params=params,
                )
                # H1: dispatch 顶层恒为 dict，旧逻辑 isawaitable 判恒 False；
                # result 可能内嵌裸协程（async 服务方法），统一 await 后替换。
                result = await resolve_invoke_result(result)
                ok = bool(result.get("ok", True)) if isinstance(result, dict) else True
        except Exception as e:
            result = {"error": str(e)}
            ok = False
        duration_ms = (time.monotonic() - t0) * 1000.0
        return {
            "step": idx,
            "ok": ok,
            "result": result,
            "duration_ms": round(duration_ms, 3),
        }