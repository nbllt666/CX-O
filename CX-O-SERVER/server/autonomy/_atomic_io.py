"""CX-O-Autonomy 统一原子 JSON 写盘工具（R1/R2/R10）。

autonomy 域全部 JSON 持久化点（config / dream config / manager state /
motivation state / token ledger / killswitch / physio store）统一经
atomic_write_json 落盘：

- 与目标同目录 mkstemp 生成 .tmp 临时文件，json.dump（ensure_ascii=False /
  indent=2）后 flush + os.fsync，再 os.replace 原子替换目标文件（Windows 下
  os.replace 覆盖已存在文件安全）——写盘中断/断电不再产生截断坏档；
- 任何一步失败在 finally 中清理临时文件，目标文件保持旧内容完整；
- quarantine_corrupt_file 供 load 侧坏档回退使用：坏档改名 {path}.corrupt
  留痕后返回默认值，替代"坏档直接抛错需人工删档"。

本模块无相对路径访问，禁止 "../../" / "..\\" 形式。
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Union


def atomic_write_json(path: Union[str, Path], data: Any) -> None:
    """将 data 序列化为 JSON 原子写入 path。

    步骤：与目标同目录 mkstemp 生成 .tmp 临时文件 → json.dump → flush +
    os.fsync → os.replace 原子替换。任一步失败时清理临时文件，目标文件不变。
    """
    target = Path(path)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(target.parent), prefix=target.name + ".", suffix=".tmp"
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(str(tmp_path), str(target))
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def quarantine_corrupt_file(path: Union[str, Path]) -> str:
    """将损坏文件改名为 {path}.corrupt 留痕，返回改名后路径；失败返回空串。"""
    src = Path(path)
    dst = Path(str(src) + ".corrupt")
    try:
        os.replace(str(src), str(dst))
        return str(dst)
    except OSError:
        return ""
