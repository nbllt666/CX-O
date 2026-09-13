"""run 编排：创建 run → 后台线程执行 suite → suite 内部终态化。"""
from __future__ import annotations

import threading
import traceback
import uuid
from typing import Any, Dict, Optional

from evalkit.config import EvalConfig, load_config, merge_overrides
from evalkit.store import EvalStore
from evalkit.suites import SUITE_REGISTRY


def start_run(
    store: EvalStore,
    suite_name: str,
    config_overrides: Optional[Dict[str, Any]] = None,
    base_config: Optional[EvalConfig] = None,
) -> str:
    """创建并启动一个评测 run，返回 run_id。

    - suite 未注册 → ValueError（API 层转 400）
    - config_overrides 深合并到 base config（None 时取 load_config 默认链）后生效
    - daemon 线程执行 suite_fn(run_id, config, store)；suite 内部自行 finish_run 终态化；
      线程内异常兜底 catch → finish_run(error)（suite 已自行终态化时忽略二次终态 ValueError）
    """
    suite_fn = SUITE_REGISTRY.get(suite_name)
    if suite_fn is None:
        raise ValueError(
            f"suite 未注册: {suite_name!r}（已注册: {sorted(SUITE_REGISTRY)}）"
        )

    base = base_config if base_config is not None else load_config(None)
    merged = merge_overrides(base.model_dump(), config_overrides or {})
    config = EvalConfig.model_validate(merged)

    run_id = uuid.uuid4().hex
    store.create_run(run_id, suite_name, config.to_safe_dict())

    def _execute() -> None:
        try:
            suite_fn(run_id, config, store)
        except Exception as exc:  # 兜底：任何未处理异常都不得让 run 悬挂在 running
            try:
                store.finish_run(
                    run_id, "error", error=f"{exc}\n{traceback.format_exc()}"
                )
            except ValueError:
                pass  # suite 已自行终态化，忽略二次终态

    threading.Thread(
        target=_execute, name=f"evalkit-run-{run_id[:8]}", daemon=True
    ).start()
    return run_id
