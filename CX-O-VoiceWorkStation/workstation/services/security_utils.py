"""
安全验证工具模块
统一管理路径验证、权限检查等安全相关功能
"""
from __future__ import annotations

from pathlib import Path

# G6: 锚点基于文件绝对路径（rules-0 §三 禁相对路径）——旧实现 Path("data/training")
# 相对进程 CWD 解析，启动目录不同会指向错误位置（误拒合法音频或放大允许范围）。
_WS_ROOT = Path(__file__).resolve().parents[2]

# 训练数据目录允许的根目录
_TRAINING_DATA_ROOT = (_WS_ROOT / "data" / "training").resolve()


def validate_training_data_dir(path: str) -> Path:
    """
    校验 training_data_dir 必须位于 data/training 根目录之下，
    拒绝绝对路径与 .. 目录穿越，防止创建/读取任意目录。

    Args:
        path: 用户提供的训练数据目录路径

    Returns:
        解析后的安全路径对象

    Raises:
        ValueError: 当路径为空、是绝对路径或不在允许的根目录下时
    """
    if not path:
        raise ValueError("training_data_dir must not be empty")

    candidate = Path(path)

    # 拒绝绝对路径，防止访问任意系统目录
    if candidate.is_absolute():
        raise ValueError(
            f"training_data_dir must be a relative path under {_TRAINING_DATA_ROOT}, "
            f"got absolute path: {path}"
        )

    # 解析相对路径，处理 .. 等符号
    resolved = candidate.resolve()

    # 确保解析后的路径位于允许的根目录之下
    if not resolved.is_relative_to(_TRAINING_DATA_ROOT):
        raise ValueError(
            f"training_data_dir must be located under {_TRAINING_DATA_ROOT}, got: {resolved}"
        )

    return resolved