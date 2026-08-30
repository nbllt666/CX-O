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
    校验 training_data_dir 解析后必须位于 data/training 根目录之下（fail-closed），
    拒绝根目录之外的任意路径与 .. 目录穿越，防止创建/读取任意目录。

    CX-NEW-1+C3：旧实现以"是否为绝对路径"为判据，与本服务自身的使用方式自相矛盾——
    api/sovits_svc.py 先调用本函数得到 resolve 后的绝对路径，再把它传给
    trainer.preprocess() 二次校验，命中 is_absolute() 拒绝分支必 500。
    新口径：校验目标从"必须是相对路径"改为"必须落在 _TRAINING_DATA_ROOT 之下"。
    相对路径锚定 _WS_ROOT 解析（不依赖进程 CWD）；位于 _TRAINING_DATA_ROOT 之下的
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

    # 相对路径锚定 _WS_ROOT 解析（替换旧的 CWD 基准）；绝对路径原样 resolve
    try:
        resolved = (
            candidate if candidate.is_absolute() else (_WS_ROOT / candidate)
        ).resolve()
    except Exception as e:
        raise ValueError(f"Invalid training_data_dir: {path}: {e}")

    # 确保解析后的路径位于允许的根目录之下（外部绝对路径在此被拒）
    if not resolved.is_relative_to(_TRAINING_DATA_ROOT):
        raise ValueError(
            f"training_data_dir must be located under {_TRAINING_DATA_ROOT}, got: {resolved}"
        )

    return resolved
