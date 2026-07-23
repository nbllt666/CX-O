"""
音乐依赖检查工具：music21 / fluidsynth / SoundFont 逐项自检

终端输出规范：每行含时间戳 + [INFO]/[ERROR] 前缀，结束输出总耗时；
退出码 0 = 全部就绪，1 = 存在缺失项（逐行给出修复指引）。

用法：
    python -m workstation.tools.check_music_deps
    python workstation/tools/check_music_deps.py
"""
from __future__ import annotations

import os
import shutil
import sys
import time

# 项目根目录（tools/ → workstation/ → 项目根），保证脚本可直接运行
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_DIR = os.path.dirname(os.path.dirname(_BASE_DIR))
if _PROJECT_DIR not in sys.path:
    sys.path.insert(0, _PROJECT_DIR)


def _timestamp() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _info(message: str) -> None:
    print(f"[{_timestamp()}] [INFO] {message}")


def _error(message: str) -> None:
    print(f"[{_timestamp()}] [ERROR] {message}")


def _check_music21() -> bool:
    """检查 music21 可导入（MusicXML 导入依赖）"""
    try:
        import music21

        _info(f"music21 导入成功（版本 {getattr(music21, '__version__', '未知')}）")
        return True
    except ImportError as exc:
        _error(f"music21 未安装: {exc}；修复: pip install music21")
        return False


def _check_fluidsynth() -> bool:
    """检查 fluidsynth 可执行文件是否在 PATH 中（伴奏渲染依赖）"""
    found = shutil.which("fluidsynth")
    if found:
        _info(f"fluidsynth 可用: {found}")
        return True
    _error(
        "fluidsynth 不在 PATH 中；修复: 安装 FluidSynth "
        "（Windows 可使用预编译包，Linux: apt install fluidsynth）并加入 PATH"
    )
    return False


def _check_soundfont() -> bool:
    """检查 music.soundfont_path 配置与 SoundFont 文件存在性"""
    from workstation.config import get_settings

    soundfont = get_settings().music.soundfont_path
    if not soundfont:
        _error("SoundFont 未配置: music.soundfont_path 为空；修复: 配置 soundfont_path 指向 .sf2 文件")
        return False
    if not os.path.isfile(soundfont):
        _error(f"SoundFont 文件不存在: {soundfont}；修复: 下载 .sf2 音色库并更新 soundfont_path")
        return False
    _info(f"SoundFont 文件存在: {soundfont}")
    return True


def main() -> int:
    start = time.perf_counter()
    _info("开始音乐依赖检查（music21 / fluidsynth / SoundFont）")

    results = {
        "music21": _check_music21(),
        "fluidsynth": _check_fluidsynth(),
        "soundfont": _check_soundfont(),
    }

    elapsed = time.perf_counter() - start
    missing = [name for name, ok in results.items() if not ok]
    if not missing:
        _info(f"依赖检查全部通过，耗时 {elapsed:.2f}s")
        return 0
    _error(f"依赖检查存在缺失项: {', '.join(missing)}，耗时 {elapsed:.2f}s")
    return 1


if __name__ == "__main__":
    sys.exit(main())
