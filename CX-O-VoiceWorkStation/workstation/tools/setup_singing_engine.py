"""
DiffSinger 歌声合成引擎安装/检查脚本

逐项检查 DiffSinger 部署就绪情况（目录、Python 解释器、声库），输出逐项检查结果；
全部就绪退出码 0，存在缺失项退出码 1。

用法：
    python -m workstation.tools.setup_singing_engine
    python -m workstation.tools.setup_singing_engine --diffsinger-dir D:\\DiffSinger --voice-bank mybank
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime

# 路径解析规范：基于 os.path.dirname(os.path.abspath(__file__))，禁止相对路径
_TOOL_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_TOOL_DIR))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from workstation.config import get_settings  # noqa: E402
from workstation.services.singing_engine import check_diffsinger_deployment  # noqa: E402

_start_time = time.perf_counter()


def _log(level: str, message: str) -> None:
    """终端输出规范：时间戳 + [INFO]/[ERROR] 前缀 + 累计耗时"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    elapsed = time.perf_counter() - _start_time
    print(f"[{timestamp}] [{level}] {message} (耗时 {elapsed:.2f}s)")


def main() -> int:
    """解析参数并逐项检查 DiffSinger 部署，返回退出码（0 就绪 / 1 缺失）"""
    parser = argparse.ArgumentParser(
        description="检查 DiffSinger 歌声合成引擎部署（目录 / Python 解释器 / 声库）"
    )
    parser.add_argument("--diffsinger-dir", type=str, default=None, help="DiffSinger 部署目录（默认取配置 music.diffsinger_dir）")
    parser.add_argument("--diffsinger-python", type=str, default=None, help="DiffSinger 环境的 Python 解释器（默认取配置 music.diffsinger_python）")
    parser.add_argument("--voice-bank", type=str, default=None, help="声库名称或路径（默认取配置 music.voice_bank）")
    args = parser.parse_args()

    music_cfg = get_settings().music
    diffsinger_dir = args.diffsinger_dir if args.diffsinger_dir is not None else music_cfg.diffsinger_dir
    diffsinger_python = (
        args.diffsinger_python if args.diffsinger_python is not None else music_cfg.diffsinger_python
    )
    voice_bank = args.voice_bank if args.voice_bank is not None else music_cfg.voice_bank

    _log("INFO", "开始检查 DiffSinger 歌声合成引擎部署")
    _log("INFO", f"检查项 1/3: DiffSinger 目录 -> {diffsinger_dir or '(未配置)'}")
    _log("INFO", f"检查项 2/3: Python 解释器 -> {diffsinger_python or '(未配置)'}")
    _log("INFO", f"检查项 3/3: 声库 -> {voice_bank or '(未配置)'}")

    missing = check_diffsinger_deployment(diffsinger_dir, diffsinger_python, voice_bank)
    if missing:
        for item in missing:
            _log("ERROR", f"缺失: {item}")
        _log(
            "ERROR",
            f"检查未通过：共 {len(missing)} 项缺失。请按官方文档部署 DiffSinger 与声库后重试"
            "（或暂用 music.singing_engine=mock 进行开发）",
        )
        return 1

    _log("INFO", "全部检查通过：DiffSinger 引擎就绪")
    return 0


if __name__ == "__main__":
    sys.exit(main())
