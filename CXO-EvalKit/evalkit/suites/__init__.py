"""suite 包：注册表 + 子模块自动发现。

子模块（latency.py / memory_decay.py / quality.py 等）通过 @register_suite(name)
自注册；本 __init__ 用 pkgutil 遍历包内子模块逐个 import，从而自动填充注册表。
新增 suite 只需新增子模块文件，无需改动任何注册接线（避免同文件并行编辑冲突）。

suite 函数签名: (run_id: str, config: EvalConfig, store: EvalStore) -> Dict[str, Any]
约定：suite 内部自行调用 store.finish_run(...) 终态化，并保存明细/返回 metrics_summary。
"""
from __future__ import annotations

import importlib
import pkgutil
from typing import Callable, Dict, List

from evalkit.suites._registry_core import SUITE_REGISTRY, register_suite  # noqa: F401


def _autodiscover() -> None:
    """遍历本包子模块并 import，触发 @register_suite 自注册。"""
    for mod in pkgutil.iter_modules(__path__):
        if mod.name.startswith("_"):
            continue  # 跳过 _registry_core 等内部模块
        importlib.import_module(f"{__name__}.{mod.name}")


_autodiscover()


def list_suites() -> List[str]:
    """返回当前已注册 suite 名清单（升序，保证输出稳定）。"""
    return sorted(SUITE_REGISTRY.keys())
