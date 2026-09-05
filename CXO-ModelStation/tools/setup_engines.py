"""CXO-ModelStation 三引擎完整性检查与 MeloTTS 克隆工具

自包含部署（change-id: extend-modelstation-standalone-melotts-datasets）：
引擎目录统一位于 CXO-ModelStation/engines/ 下：
  - so-vits-svc-4.1-Stable  （训练 + VWS 翻唱推理共用，config.sovits_svc.so_vits_svc_dir）
  - VoxCPM-main             （批量语料生成引擎，config.voxcpm.working_dir）
  - MeloTTS                 （微调训练引擎，config.melotts.engine_dir；本工具 --clone-melotts 克隆）

功能：
  1. 三引擎存在性与完整性检查：
     - so-vits：关键推理脚本 inference_main.py 与 configs/ 目录；
     - VoxCPM：pyproject.toml 与 src/voxcpm 关键模块（cli.py/__init__.py）；
     - MeloTTS：melo 包目录与训练入口存在性。
  2. --clone-melotts：engines/MeloTTS 缺失时从 GitHub 克隆官方仓库（已存在则跳过）。
  3. MeloTTS 训练管线可导入校验（在引擎目录执行 python -c "import melo"；
     失败时输出依赖安装指引，不计为引擎缺失）。

用法：
    python tools/setup_engines.py                 # 仅检查，不改动
    python tools/setup_engines.py --clone-melotts # 检查 + 缺失时克隆 MeloTTS

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
_TOOLS_DIR = Path(__file__).resolve().parent      # .../CXO-ModelStation/tools
_MS_ROOT = _TOOLS_DIR.parent                      # .../CXO-ModelStation
_ENGINES_DIR = _MS_ROOT / "engines"

_SO_VITS_DIR = _ENGINES_DIR / "so-vits-svc-4.1-Stable"
_VOXCPM_DIR = _ENGINES_DIR / "VoxCPM-main"
_MELOTTS_DIR = _ENGINES_DIR / "MeloTTS"

_MELOTTS_REPO_URL = "https://github.com/myshell-ai/MeloTTS.git"

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


# ---------------------------------------------------------------------------
# 各引擎完整性检查
# ---------------------------------------------------------------------------
def check_so_vits() -> bool:
    """so-vits-svc-4.1-Stable：推理脚本 + 配置目录。"""
    _log("INFO", f"检查 so-vits 引擎（{_SO_VITS_DIR.name}）...")
    ok = _require("so-vits 引擎根目录", _SO_VITS_DIR)
    if not ok:
        return False
    checks = [
        ("so-vits 推理脚本 inference_main.py", _SO_VITS_DIR / "inference_main.py"),
        ("so-vits 配置目录 configs/", _SO_VITS_DIR / "configs"),
        ("so-vits 模块目录 modules/", _SO_VITS_DIR / "modules"),
    ]
    all_ok = True
    for desc, path in checks:
        all_ok = _require(desc, path) and all_ok
    return all_ok


def check_voxcpm() -> bool:
    """VoxCPM-main：pyproject 入口 + src/voxcpm 关键模块。"""
    _log("INFO", f"检查 VoxCPM 引擎（{_VOXCPM_DIR.name}）...")
    ok = _require("VoxCPM 引擎根目录", _VOXCPM_DIR)
    if not ok:
        return False
    checks = [
        ("VoxCPM pyproject.toml", _VOXCPM_DIR / "pyproject.toml"),
        ("VoxCPM 包目录 src/voxcpm/", _VOXCPM_DIR / "src" / "voxcpm"),
        ("VoxCPM 包初始化 __init__.py", _VOXCPM_DIR / "src" / "voxcpm" / "__init__.py"),
        ("VoxCPM CLI 模块 cli.py", _VOXCPM_DIR / "src" / "voxcpm" / "cli.py"),
        ("VoxCPM 核心模块 core.py", _VOXCPM_DIR / "src" / "voxcpm" / "core.py"),
    ]
    all_ok = True
    for desc, path in checks:
        all_ok = _require(desc, path) and all_ok
    return all_ok


def check_melotts() -> bool:
    """MeloTTS：melo 包目录与训练入口存在性。"""
    _log("INFO", f"检查 MeloTTS 引擎（{_MELOTTS_DIR.name}）...")
    ok = _require("MeloTTS 引擎根目录", _MELOTTS_DIR)
    if not ok:
        _log("INFO", "MeloTTS 缺失时可用 --clone-melotts 从 GitHub 克隆（详见 DEPLOY.md）")
        return False
    # 官方仓库 melo 包目录为必需；训练入口在 melo/train.py（历史版本位于仓库根 train.py）
    all_ok = _require("MeloTTS melo 包目录 melo/", _MELOTTS_DIR / "melo")
    all_ok = _require("MeloTTS 包初始化 melo/__init__.py", _MELOTTS_DIR / "melo" / "__init__.py") and all_ok
    if not (_MELOTTS_DIR / "melo" / "train.py").exists() and not (_MELOTTS_DIR / "train.py").exists():
        _log("ERROR", "[缺失] MeloTTS 训练入口（melo/train.py 或 train.py）不存在")
        _MISSING.append("MeloTTS 训练入口")
        all_ok = False
    else:
        _log("INFO", "[OK] MeloTTS 训练入口存在")
    return all_ok


def clone_melotts() -> bool:
    """克隆官方 MeloTTS 仓库；目标已存在时跳过。"""
    if _MELOTTS_DIR.exists():
        _log("INFO", f"MeloTTS 已存在，跳过克隆: {_MELOTTS_DIR}")
        return True
    if not _ENGINES_DIR.exists():
        _ENGINES_DIR.mkdir(parents=True, exist_ok=True)
    _log("INFO", f"开始克隆 MeloTTS: {_MELOTTS_REPO_URL} -> {_MELOTTS_DIR}")
    try:
        result = subprocess.run(
            ["git", "clone", _MELOTTS_REPO_URL, str(_MELOTTS_DIR)],
            capture_output=True,
            text=True,
            timeout=600,
        )
    except FileNotFoundError:
        _log("ERROR", "未找到 git 命令，无法克隆 MeloTTS；请安装 git 后重试")
        return False
    except subprocess.TimeoutExpired:
        _log("ERROR", "git clone 超时（600s）；请检查网络后重试")
        return False
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        _log("ERROR", f"git clone 失败（exit={result.returncode}）: {stderr[:500]}")
        return False
    _log("INFO", f"MeloTTS 克隆完成: {_MELOTTS_DIR}")
    return True


def verify_melotts_import() -> bool:
    """MeloTTS 训练管线可导入校验：在引擎目录执行 python -c "import melo"。

    导入失败不计为引擎缺失（依赖问题），仅输出依赖安装指引。
    """
    if not (_MELOTTS_DIR / "melo").exists():
        _log("INFO", "MeloTTS 未就位，跳过训练管线导入校验")
        return False
    _log("INFO", "校验 MeloTTS 训练管线可导入（python -c \"import melo\"）...")
    python_exe = sys.executable or "python"
    try:
        result = subprocess.run(
            [python_exe, "-c", "import melo"],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(_MELOTTS_DIR),
        )
    except subprocess.TimeoutExpired:
        _log("ERROR", "MeloTTS 导入校验超时（120s）；可能存在首次导入下载或环境阻塞")
        return False
    if result.returncode == 0:
        _log("INFO", "[OK] MeloTTS 训练管线可导入")
        return True
    stderr = (result.stderr or "").strip().splitlines()
    last_err = stderr[-1] if stderr else "<无 stderr>"
    _log("ERROR", f"MeloTTS 训练管线导入失败: {last_err}")
    _log(
        "ERROR",
        "修复指引: 在 engines/MeloTTS 目录安装依赖后重试 "
        '(如 pip install -e . 或 pip install -r requirements.txt；'
        "conda 环境建议单独创建 melotts 环境，依赖含 torch/numpy/librosa 等)",
    )
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="CXO-ModelStation 三引擎完整性检查与 MeloTTS 克隆")
    parser.add_argument(
        "--clone-melotts",
        action="store_true",
        help="engines/MeloTTS 缺失时从 GitHub 克隆官方 myshell-ai/MeloTTS",
    )
    args = parser.parse_args()

    _log("INFO", f"CXO-ModelStation 引擎就绪检查开始（engines 根: {_ENGINES_DIR}）")

    if args.clone_melotts:
        if not clone_melotts():
            _log("ERROR", "MeloTTS 克隆未完成，后续检查将继续报告其缺失状态")

    ok_so_vits = check_so_vits()
    ok_voxcpm = check_voxcpm()
    ok_melotts = check_melotts()
    ok_import = verify_melotts_import() if ok_melotts else False

    _log("INFO", "===== 引擎就绪报告 =====")
    _log("INFO", f"so-vits-svc-4.1-Stable: {'OK' if ok_so_vits else '缺失'}")
    _log("INFO", f"VoxCPM-main:            {'OK' if ok_voxcpm else '缺失'}")
    melotts_state = "OK" if ok_melotts and ok_import else ("依赖缺失" if ok_melotts else "缺失")
    _log("INFO", f"MeloTTS:                {melotts_state}")
    if _MISSING:
        _log("ERROR", f"存在 {len(_MISSING)} 项缺失: {'; '.join(_MISSING)}")
        _log("ERROR", "修复指引见 CXO-ModelStation/DEPLOY.md（引擎就位 / --clone-melotts / 权重放置）")
        return 1
    _log("INFO", "全部引擎就绪检查通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
