"""CX-O-VoiceWorkStation 分离引擎完整性检查与克隆工具

change-id: enhance-cover-pitch-analysis-duet（Task 1）。
引擎目录位于 CX-O-VoiceWorkStation/engines/ 下（依赖与 VWS 主环境隔离）：
  - demucs    （facebookresearch/demucs，htdemucs + --two-stems=vocals 两轨人声分离）
  - AudioSep  （Audio-AGI/AudioSep，文本查询拆分双人声部）

功能：
  1. 两引擎存在性与完整性检查：
     - demucs：demucs 包目录与 CLI 入口 demucs/separate.py；
       引擎内 python -c "import demucs" 可导入校验（失败=依赖缺失，不计为引擎缺失）。
     - AudioSep：pipeline.py 推理入口、config/audiosep_base.yaml、models/ 包目录；
       权重存在性（checkpoint/ 下 .ckpt 与 CLAP 权重
       music_speech_audioset_epoch_15_esc_89.98.pt，或 config 显式 audiosep_checkpoint）。
  2. --clone：两引擎缺失时从 GitHub 克隆官方仓库（已存在则跳过）。

用法：
    python tools/setup_separation.py            # 仅检查，不改动
    python tools/setup_separation.py --clone    # 检查 + 缺失时克隆两引擎

终端输出格式：[timestamp] [INFO/ERROR] [elapsed]；退出码 0=全部就绪，1=存在缺失项。
路径全部基于 __file__ 锚定，对 CWD 免疫（rules-0 §三）。
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# 路径锚定
# ---------------------------------------------------------------------------
_TOOLS_DIR = Path(__file__).resolve().parent   # .../CX-O-VoiceWorkStation/tools
_VWS_ROOT = _TOOLS_DIR.parent                  # .../CX-O-VoiceWorkStation
_ENGINES_DIR = _VWS_ROOT / "engines"

_DEMUCS_DIR = _ENGINES_DIR / "demucs"
_AUDIODEP_DIR = _ENGINES_DIR / "AudioSep"

_DEMUCS_REPO_URL = "https://github.com/facebookresearch/demucs.git"
_AUDIODEP_REPO_URL = "https://github.com/Audio-AGI/AudioSep.git"

# AudioSep CLAP 文本编码器权重（models/clap_encoder.py L7 默认路径）
_CLAP_WEIGHT_NAME = "music_speech_audioset_epoch_15_esc_89.98.pt"

_START = time.monotonic()
_MISSING: list[str] = []


def _log(level: str, msg: str) -> None:
    """[timestamp] [INFO/ERROR] [elapsed] 格式终端输出"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    elapsed = time.monotonic() - _START
    print(f"[{ts}] [{level}] [{elapsed:.1f}s] {msg}")


def _require(desc: str, path: Path) -> bool:
    """检查路径存在；缺失时记录并输出修复提示。"""
    if path.exists():
        _log("INFO", f"[OK] {desc}: {path}")
        return True
    _log("ERROR", f"[缺失] {desc}: {path} 不存在")
    _MISSING.append(desc)
    return False


def _clone_repo(repo_url: str, target: Path, name: str) -> bool:
    """克隆官方引擎仓库；目标已存在时跳过。"""
    if target.exists():
        _log("INFO", f"{name} 已存在，跳过克隆: {target}")
        return True
    if not _ENGINES_DIR.exists():
        _ENGINES_DIR.mkdir(parents=True, exist_ok=True)
    _log("INFO", f"开始克隆 {name}: {repo_url} -> {target}")
    try:
        result = subprocess.run(
            ["git", "clone", "--depth", "1", repo_url, str(target)],
            capture_output=True,
            text=True,
            timeout=600,
        )
    except FileNotFoundError:
        _log("ERROR", f"未找到 git 命令，无法克隆 {name}；请安装 git 后重试")
        return False
    except subprocess.TimeoutExpired:
        _log("ERROR", f"git clone 超时（600s）；请检查网络后重试")
        return False
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        _log("ERROR", f"git clone 失败（exit={result.returncode}）: {stderr[:500]}")
        return False
    _log("INFO", f"{name} 克隆完成: {target}")
    return True


# ---------------------------------------------------------------------------
# 各引擎完整性检查
# ---------------------------------------------------------------------------
def check_demucs() -> bool:
    """demucs：包目录 + CLI 入口 + 模块可导入（依赖缺失不计为引擎缺失）。"""
    _log("INFO", f"检查 demucs 引擎（{_DEMUCS_DIR.name}）...")
    ok = _require("demucs 引擎根目录", _DEMUCS_DIR)
    if not ok:
        _log("INFO", "demucs 缺失时可用 --clone 从 GitHub 克隆（详见 DEPLOY-SEPARATION.md）")
        return False
    all_ok = _require("demucs CLI 入口 demucs/separate.py", _DEMUCS_DIR / "demucs" / "separate.py")
    all_ok = _require("demucs 包初始化 demucs/__init__.py", _DEMUCS_DIR / "demucs" / "__init__.py") and all_ok
    # 模块可导入校验（引擎目录内执行；依赖 torch/dora 等未装时=依赖缺失，非引擎缺失）
    _log("INFO", '校验 demucs 模块可导入（python -c "import demucs"）...')
    try:
        result = subprocess.run(
            [sys.executable, "-c", "import demucs"],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(_DEMUCS_DIR),
        )
    except subprocess.TimeoutExpired:
        _log("ERROR", "demucs 导入校验超时（120s）")
        _MISSING.append("demucs 模块导入（依赖）")
        return False
    if result.returncode == 0:
        _log("INFO", "[OK] demucs 模块可导入（依赖已安装）")
    else:
        last_err = ((result.stderr or "").strip().splitlines() or ["<无 stderr>"])[-1]
        _log("ERROR", f"demucs 模块导入失败（依赖缺失，非引擎缺失）: {last_err}")
        _log("ERROR", "修复指引: 按 DEPLOY-SEPARATION.md 为 demucs 单独环境安装依赖（pip install demucs）")
        _MISSING.append("demucs 依赖（import demucs）")
        all_ok = False
    return all_ok


def check_audiosep() -> bool:
    """AudioSep：推理入口/配置/模型包 + 权重存在性。"""
    _log("INFO", f"检查 AudioSep 引擎（{_AUDIODEP_DIR.name}）...")
    ok = _require("AudioSep 引擎根目录", _AUDIODEP_DIR)
    if not ok:
        _log("INFO", "AudioSep 缺失时可用 --clone 从 GitHub 克隆（详见 DEPLOY-SEPARATION.md）")
        return False
    all_ok = _require("AudioSep 推理入口 pipeline.py", _AUDIODEP_DIR / "pipeline.py")
    all_ok = _require("AudioSep 模型配置 config/audiosep_base.yaml",
                      _AUDIODEP_DIR / "config" / "audiosep_base.yaml") and all_ok
    all_ok = _require("AudioSep 模型包目录 models/", _AUDIODEP_DIR / "models") and all_ok
    all_ok = _require("AudioSep 推理 wrapper tools/audiosep_runner.py",
                      _TOOLS_DIR / "audiosep_runner.py") and all_ok

    # 权重存在性：config 显式 audiosep_checkpoint 优先，否则引擎 checkpoint/ 目录
    config_ckpt = _resolve_config_checkpoint()
    ckpt_dir = _AUDIODEP_DIR / "checkpoint"
    if config_ckpt:
        if Path(config_ckpt).exists():
            _log("INFO", f"[OK] AudioSep checkpoint（配置显式指定）: {config_ckpt}")
        else:
            _log("ERROR", f"[缺失] AudioSep checkpoint（配置显式指定）: {config_ckpt}")
            _MISSING.append("AudioSep checkpoint（配置指定路径）")
            all_ok = False
    else:
        ckpts = sorted(ckpt_dir.glob("*.ckpt")) if ckpt_dir.exists() else []
        if ckpts:
            _log("INFO", f"[OK] AudioSep checkpoint: {ckpt_dir}（{len(ckpts)} 个 .ckpt）")
        else:
            _log("ERROR", f"[缺失] AudioSep checkpoint: {ckpt_dir} 下无 .ckpt "
                          f"（下载 audiosep_base_4M_steps.ckpt，见 DEPLOY-SEPARATION.md）")
            _MISSING.append("AudioSep checkpoint（.ckpt）")
            all_ok = False

    clap_weight = ckpt_dir / _CLAP_WEIGHT_NAME
    if clap_weight.exists():
        _log("INFO", f"[OK] CLAP 编码器权重: {clap_weight}")
    else:
        _log("ERROR", f"[缺失] CLAP 编码器权重: {clap_weight}（见 DEPLOY-SEPARATION.md）")
        _MISSING.append("AudioSep CLAP 权重（.pt）")
        all_ok = False
    return all_ok


def _resolve_config_checkpoint() -> str | None:
    """从 VWS config 读取显式 audiosep_checkpoint（读取失败不阻断）。"""
    try:
        sys.path.insert(0, str(_VWS_ROOT))
        from workstation.config import get_settings
        value = get_settings().separation.audiosep_checkpoint
        return value or None
    except Exception:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="CX-O-VoiceWorkStation 分离引擎完整性检查与克隆（demucs + AudioSep）"
    )
    parser.add_argument(
        "--clone",
        action="store_true",
        help="engines/demucs 与 engines/AudioSep 缺失时从 GitHub 克隆官方仓库",
    )
    args = parser.parse_args()

    _log("INFO", f"CX-O-VoiceWorkStation 分离引擎就绪检查开始（engines 根: {_ENGINES_DIR}）")

    if args.clone:
        if not _clone_repo(_DEMUCS_REPO_URL, _DEMUCS_DIR, "demucs"):
            _log("ERROR", "demucs 克隆未完成，后续检查将继续报告其缺失状态")
        if not _clone_repo(_AUDIODEP_REPO_URL, _AUDIODEP_DIR, "AudioSep"):
            _log("ERROR", "AudioSep 克隆未完成，后续检查将继续报告其缺失状态")

    ok_demucs = check_demucs()
    ok_audiosep = check_audiosep()

    _log("INFO", "===== 分离引擎就绪报告 =====")
    _log("INFO", f"demucs  : {'OK' if ok_demucs else '缺失/依赖缺失'}")
    _log("INFO", f"AudioSep: {'OK' if ok_audiosep else '缺失/权重缺失'}")
    if _MISSING:
        _log("ERROR", f"存在 {len(_MISSING)} 项缺失: {'; '.join(_MISSING)}")
        _log("ERROR", "修复指引见 CX-O-VoiceWorkStation/DEPLOY-SEPARATION.md"
                      "（--clone / 两引擎依赖 / 权重下载放置）")
        return 1
    _log("INFO", "全部分离引擎就绪检查通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
