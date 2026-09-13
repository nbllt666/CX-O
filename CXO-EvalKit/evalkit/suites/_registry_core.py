"""suite 注册表。

本任务只建注册机制：注册表初始为空（GET /api/v1/suites 返回空清单也可运行），
具体 suite（memory_decay / latency / quality 等）由后续任务实现并注册。
"""
from __future__ import annotations

from typing import Callable, Dict, List

# suite 函数签名: (run_id: str, config: EvalConfig, store: EvalStore) -> Dict[str, Any]
# 约定：suite 内部自行调用 store.finish_run(...) 终态化，并保存明细/返回 metrics_summary。
SUITE_REGISTRY: Dict[str, Callable] = {}


def register_suite(name: str) -> Callable:
    """将函数注册为名为 name 的评测 suite。"""

    def decorator(fn: Callable) -> Callable:
        SUITE_REGISTRY[name] = fn
        return fn

    return decorator


def list_suites() -> List[str]:
    """返回当前已注册 suite 名清单（升序，保证输出稳定）。"""
    return sorted(SUITE_REGISTRY.keys())
