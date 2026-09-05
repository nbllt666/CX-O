"""
安全验证工具模块
统一管理路径验证、权限检查等安全相关功能

自 CX-O-VoiceWorkStation/workstation/services/security_utils.py 迁移
（change-id: split-audio-workstation-cxfc-modelstation），
锚点语义平移：_MS_ROOT 指向 CXO-ModelStation 包根。
"""
from __future__ import annotations

from pathlib import Path

# G6: 锚点基于文件绝对路径（rules-0 §三 禁相对路径）。
# 本文件位于 CXO-ModelStation/modelstation/services/security_utils.py，
# parents[2] 解析结果 = CXO-ModelStation（与原 VWS 布局层级相同，语义平移）。
_MS_ROOT = Path(__file__).resolve().parents[2]

# 训练数据目录允许的根目录（CXO-ModelStation/data/training）
_TRAINING_DATA_ROOT = (_MS_ROOT / "data" / "training").resolve()


def validate_training_data_dir(path: str) -> Path:
    """
    校验 training_data_dir 解析后必须位于 data/training 根目录之下（fail-closed），
    拒绝根目录之外的任意路径与 .. 目录穿越，防止创建/读取任意目录。

    口径与原 VWS 实现一致：校验目标为"必须落在 _TRAINING_DATA_ROOT 之下"。
    相对路径锚定 _MS_ROOT 解析（不依赖进程 CWD）；位于 _TRAINING_DATA_ROOT 之下的
    绝对路径（即本服务自己 resolve 出来的路径）放行；外部绝对路径仍拒。

    Args:
        path: 用户提供的训练数据目录路径（相对或绝对）

    Returns:
        解析后的安全路径对象

    Raises:
        ValueError: 当路径为空、解析失败或不在允许的根目录下时
    """
    if not path:
        raise ValueError("training_data_dir must not be empty")

    candidate = Path(path)

    # 相对路径锚定 _MS_ROOT 解析；绝对路径原样 resolve
    try:
        resolved = (
            candidate if candidate.is_absolute() else (_MS_ROOT / candidate)
        ).resolve()
    except Exception as e:
        raise ValueError(f"Invalid training_data_dir: {path}: {e}")

    # 确保解析后的路径位于允许的根目录之下（外部绝对路径在此被拒）
    if not resolved.is_relative_to(_TRAINING_DATA_ROOT):
        raise ValueError(
            f"training_data_dir must be located under {_TRAINING_DATA_ROOT}, got: {resolved}"
        )

    return resolved
