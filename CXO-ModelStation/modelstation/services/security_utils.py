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

# 训练数据目录允许的根目录默认值（CXO-ModelStation/data/training，开发态生效）
_DEFAULT_TRAINING_DATA_ROOT = (_MS_ROOT / "data" / "training").resolve()


def _resolve_training_data_root() -> Path:
    """解析训练数据白名单根：优先注入配置，回退包内默认根。

    必要性（打包态实测）：安装版把包放在 <安装根>/resources/backend，包内锚点会解析出
    ``resources/backend/data/training``，与运行期注入的数据根
    （%LOCALAPPDATA%\\CXO-ModelStation\\data\\training）不一致 —— 生成的数据集会写进安装
    目录（训练侧读不到、卸载即丢失），注入目录下的路径也会被白名单误拒。
    开发态两者等价（仓库根 data/training）。
    """
    try:
        from modelstation.config import get_settings

        return Path(get_settings().sovits_svc.training_data_dir).resolve().parent
    except Exception:
        return _DEFAULT_TRAINING_DATA_ROOT


# 训练数据白名单根（导入期解析；测试可 patch 本常量隔离到 tmp_path）
_TRAINING_DATA_ROOT = _resolve_training_data_root()


def training_data_root() -> Path:
    """训练数据白名单根（公开访问入口，调用期读取模块常量）。"""
    return _TRAINING_DATA_ROOT


def validate_training_data_dir(path: str) -> Path:
    """
    校验 training_data_dir 解析后必须位于训练数据根目录之下（fail-closed），
    拒绝根目录之外的任意路径与 .. 目录穿越，防止创建/读取任意目录。

    口径：校验目标为"必须落在训练数据根之下"（见 :data:`_TRAINING_DATA_ROOT`）。
    相对路径锚定 _MS_ROOT 解析（不依赖进程 CWD，与既有 `data/training/...` 写法一致）；
    位于根目录之下的绝对路径（即本服务自己 resolve 出来的路径）放行；外部绝对路径仍拒。

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
    root = _TRAINING_DATA_ROOT

    # 相对路径锚定 _MS_ROOT 解析；绝对路径原样 resolve
    try:
        resolved = (
            candidate if candidate.is_absolute() else (_MS_ROOT / candidate)
        ).resolve()
    except Exception as e:
        raise ValueError(f"Invalid training_data_dir: {path}: {e}")

    # 确保解析后的路径位于允许的根目录之下（外部绝对路径在此被拒）
    if not resolved.is_relative_to(root):
        raise ValueError(
            f"training_data_dir must be located under {root}, got: {resolved}"
        )

    return resolved
