#!/usr/bin/env python3
"""CXO-ModelStation 桌面安装包编排器（change-id: package-modelstation-desktop-installer）

串行编排（每步失败即中止并返回非 0）：
  1) 前端构建      frontend/ 下 `npm run build`（含 tsc typecheck + vite build → dist/ + dist-electron/）
  2) 运行时就绪    复用 build/runtime（`build_runtime.py --verify-only`）；缺失或 --rebuild-runtime 时按
                   --runtime-profile/--torch-index 构建；--runtime-dir 指向替代运行时目录
  3) 引擎校验      `python tools/setup_engines.py`（退出码非 0 即失败）
  4) 载荷组装      不做二次拷贝：extraResources 直指 ../modelstation、../engines、../data、运行时目录
  5) 形态判据      payload ≤ 2GiB → NSIS；> 2GiB → Inno Setup（iscc 缺失则回退 dir 便携目录 + 显式报错）
  6) 报告落盘      build/reports/desktop_build_report.json + .md
  7) 打印摘要

硬约束：打包输入只读（modelstation/、engines/、data/ 零写入）。

用法：
    python tools/build_desktop.py                        # full + cuda 正式出包 → release/
    python tools/build_desktop.py --runtime-dir build/runtime-base --out-dir release-nsis-trial
    python tools/build_desktop.py --skip-frontend --form dir

终端输出格式：[timestamp] [INFO/ERROR/WARN] [elapsed]；退出码 0=成功（含 payload 超限时的 dir 降级），
非 0=步骤失败或显式 --form 形态不可用。
路径全部基于 __file__ 锚定，对 CWD 免疫。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# --------------------------------------------------------------------------- #
# 路径与常量                                                                    #
# --------------------------------------------------------------------------- #
_T0 = time.monotonic()

_TOOLS_DIR = Path(__file__).resolve().parent
_MS_ROOT = _TOOLS_DIR.parent
_FRONTEND_DIR = _MS_ROOT / "frontend"
_BUILD_DIR = _MS_ROOT / "build"
_REPORTS_DIR = _BUILD_DIR / "reports"
_DEFAULT_RUNTIME_DIR = _BUILD_DIR / "runtime"
_DEFAULT_OUT_DIR = _MS_ROOT / "release"
_CONFIG_PATH = _FRONTEND_DIR / "electron-builder.yml"
_GENERATED_CONFIG_PATH = _FRONTEND_DIR / "electron-builder.generated.yml"
_INNO_SCRIPT = _TOOLS_DIR / "inno_setup" / "modelstation.iss"
_BUILD_RUNTIME_PY = _TOOLS_DIR / "build_runtime.py"
_SETUP_ENGINES_PY = _TOOLS_DIR / "setup_engines.py"

# NSIS 32 位偏移上限：安装集超过 2GiB 时 electron-builder 会拒绝生成 NSIS
_NSIS_LIMIT_BYTES = 2 * 1024**3
_ISCC_CANDIDATES = [
    r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    r"C:\Program Files\Inno Setup 6\ISCC.exe",
    # 逐用户安装（winget 默认 / 非管理员安装）：本机实测 Inno Setup 6.7.3 落在该位置
    os.path.join(
        os.environ.get("LOCALAPPDATA", ""), "Programs", "Inno Setup 6", "ISCC.exe"
    ),
]


def _emit(level: str, msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] [{level}] [{time.monotonic() - _T0:.1f}s] {msg}", flush=True)


def _info(msg: str) -> None:
    _emit("INFO", msg)


def _warn(msg: str) -> None:
    _emit("WARN", msg)


def _error(msg: str) -> None:
    _emit("ERROR", msg)


class BuildError(RuntimeError):
    """编排步骤失败（消息面向人类，含修复指引）。"""


# --------------------------------------------------------------------------- #
# 基础工具                                                                      #
# --------------------------------------------------------------------------- #
def _quote(part: str) -> str:
    return f'"{part}"' if " " in part else part


def _run(parts: list[str], cwd: Path | None, timeout: int, label: str,
         env: dict | None = None) -> int:
    """执行命令并打印命令原文（shell 语义，兼容 Windows 的 npm.cmd / .cmd 包装器）。

    env 缺省继承父进程环境；传入时完全替换（调用方自行 merge os.environ）。
    """
    command = " ".join(_quote(p) for p in parts)
    _info(f"[{label}] 执行：{command}" + (f"  (cwd={cwd})" if cwd else ""))
    try:
        proc = subprocess.run(
            command, cwd=str(cwd) if cwd else None, shell=True, timeout=timeout, env=env
        )
    except subprocess.TimeoutExpired:
        raise BuildError(f"[{label}] 命令超时（{timeout}s）：{command}")
    _info(f"[{label}] 退出码={proc.returncode}")
    return proc.returncode


def _readonly_python_env() -> dict:
    """引擎校验子进程环境：禁写 .pyc（PYTHONDONTWRITEBYTECODE）并禁读用户 site。

    子进程环境变量可被其后代继承，因此 setup_engines.py 内部的
    `python -c "import melo"` 探针同样受约束，不再向
    engines/MeloTTS/melo/__pycache__ 写入字节码（打包输入只读，硬约束）。
    """
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONNOUSERSITE"] = "1"
    return env


def _dir_stats(path: Path) -> dict:
    """统计目录（递归）或单个文件的体积/文件数。"""
    if not path.exists():
        return {"path": str(path), "exists": False, "files": 0, "bytes": 0}
    if path.is_file():
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        return {"path": str(path), "exists": True, "files": 1, "bytes": size}
    files = 0
    total = 0
    for root, _dirs, names in os.walk(path):
        for name in names:
            try:
                total += (Path(root) / name).stat().st_size
                files += 1
            except OSError:
                continue
    return {"path": str(path), "exists": True, "files": files, "bytes": total}


def _mib(value: int) -> float:
    return round(value / 1024**2, 1)


def _resolve_under_root(value: str) -> Path:
    p = Path(value)
    return p.resolve() if p.is_absolute() else (_MS_ROOT / p).resolve()


def _resolve_iscc() -> str | None:
    found = shutil.which("iscc")
    if found:
        return found
    for cand in _ISCC_CANDIDATES:
        if Path(cand).is_file():
            return cand
    return None


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


# --------------------------------------------------------------------------- #
# 步骤 1：前端构建                                                              #
# --------------------------------------------------------------------------- #
def step_frontend_build(skip: bool) -> dict:
    _info("步骤 1/7 前端构建（frontend/ npm run build）")
    if skip:
        _warn("--skip-frontend：跳过前端构建，复用既有 frontend/dist 与 dist-electron")
    else:
        npm = shutil.which("npm")
        if not npm:
            raise BuildError("未找到 npm（PATH 缺失）；请安装 Node.js 后重试")
        code = _run([npm, "run", "build"], cwd=_FRONTEND_DIR, timeout=1800, label="前端构建")
        if code != 0:
            raise BuildError(f"前端构建失败（npm run build 退出码={code}）")
    dist = _dir_stats(_FRONTEND_DIR / "dist")
    dist_electron = _dir_stats(_FRONTEND_DIR / "dist-electron")
    if not dist["exists"] or dist["files"] == 0:
        raise BuildError("frontend/dist 缺失或为空；前端构建未产出渲染产物")
    if not (_FRONTEND_DIR / "dist-electron" / "main.js").is_file():
        raise BuildError("frontend/dist-electron/main.js 缺失；主进程构建未产出")
    return {"dist": dist, "dist_electron": dist_electron}


# --------------------------------------------------------------------------- #
# 步骤 2：运行时就绪                                                            #
# --------------------------------------------------------------------------- #
def step_runtime(runtime_dir: Path, profile: str, torch_index: str, skip: bool, rebuild: bool) -> dict:
    _info(f"步骤 2/7 运行时就绪（dir={runtime_dir} profile={profile} torch={torch_index}）")
    result: dict = {
        "dir": str(runtime_dir),
        "profile": profile,
        "torch_index": torch_index,
        "source": "skipped",
        "verify_only": False,
    }
    py_exe = runtime_dir / "python" / "python.exe"
    is_default_dir = runtime_dir == _DEFAULT_RUNTIME_DIR

    if skip:
        _warn("--skip-runtime：跳过运行时校验/构建")
        result["source"] = "skipped"
    elif not py_exe.is_file() or rebuild:
        if not is_default_dir:
            raise BuildError(
                f"--runtime-dir 指向的运行时不存在（{py_exe}），且 tools/build_runtime.py 尚无 --runtime-dir "
                "参数（恒写入 build/runtime，登记为已知限制）。请先自行把该运行时目录就位后重跑，"
                "或使用默认 --runtime-dir build/runtime。"
            )
        extra = ["--force"] if rebuild else []
        code = _run(
            [sys.executable, str(_BUILD_RUNTIME_PY), "--profile", profile, "--torch-index", torch_index, *extra],
            cwd=_MS_ROOT,
            timeout=7200,
            label="运行时构建",
        )
        if code != 0:
            raise BuildError(f"运行时构建失败（build_runtime.py 退出码={code}）")
        result["source"] = "built"
    else:
        if is_default_dir:
            code = _run(
                [sys.executable, str(_BUILD_RUNTIME_PY), "--verify-only"],
                cwd=_MS_ROOT,
                timeout=1800,
                label="运行时校验",
            )
            if code != 0:
                raise BuildError(f"运行时校验失败（build_runtime.py --verify-only 退出码={code}）")
            result["verify_only"] = True
            result["source"] = "reused"
        else:
            # 替代目录：build_runtime.py 的 verify-only 只认默认目录，这里做等价最小探针
            code = _run(
                [str(py_exe), "-c", "import sys; print('runtime_ok', sys.version.split()[0])"],
                cwd=runtime_dir,
                timeout=180,
                label="运行时探针",
            )
            if code != 0:
                raise BuildError(f"替代运行时探针失败（{py_exe} 退出码={code}）")
            result["source"] = "reused"

    if not py_exe.is_file():
        raise BuildError(f"运行时解释器缺失：{py_exe}")
    result["python_exe"] = str(py_exe)
    result["size"] = _dir_stats(runtime_dir)

    manifest_path = runtime_dir / "runtime_manifest.json"
    manifest = _read_json(manifest_path)
    result["manifest_path"] = str(manifest_path) if manifest_path.is_file() else None
    if manifest:
        result["manifest_summary"] = {
            "python_version": manifest.get("python_version"),
            "profile": manifest.get("profile"),
            "torch_index": manifest.get("torch_index"),
            "python_exe": manifest.get("python_exe"),
            "pth_strategy_mode": (manifest.get("pth_strategy") or {}).get("mode"),
        }
        _info(
            "运行时 manifest 关键字段："
            f"python_version={manifest.get('python_version')} profile={manifest.get('profile')} "
            f"torch_index={manifest.get('torch_index')}"
        )
    else:
        _warn(f"未找到运行时 manifest：{manifest_path}")
    return result


# --------------------------------------------------------------------------- #
# 步骤 3：引擎校验                                                              #
# --------------------------------------------------------------------------- #
def step_engines_check() -> dict:
    _info("步骤 3/7 引擎完整性校验（tools/setup_engines.py）")
    code = _run(
        [sys.executable, str(_SETUP_ENGINES_PY)],
        cwd=_MS_ROOT,
        timeout=900,
        label="引擎校验",
        env=_readonly_python_env(),
    )
    if code != 0:
        raise BuildError(f"引擎校验失败（setup_engines.py 退出码={code}）；修复指引见 CXO-ModelStation/DEPLOY.md")
    return {"exit_code": code, "engines_dir": str(_MS_ROOT / "engines")}


# --------------------------------------------------------------------------- #
# 步骤 4/5：载荷体积判据与打包                                                  #
# --------------------------------------------------------------------------- #
def _payload_parts(runtime_dir: Path) -> dict:
    return {
        "frontend/dist": _dir_stats(_FRONTEND_DIR / "dist"),
        "frontend/dist-electron": _dir_stats(_FRONTEND_DIR / "dist-electron"),
        "modelstation": _dir_stats(_MS_ROOT / "modelstation"),
        "engines": _dir_stats(_MS_ROOT / "engines"),
        "data": _dir_stats(_MS_ROOT / "data"),
        "runtime": _dir_stats(runtime_dir),
        "electron-client": _dir_stats(_FRONTEND_DIR / "node_modules" / "electron" / "dist"),
    }


def _decide_form(form: str, payload_bytes: int, iscc: str | None) -> tuple[str, str]:
    limit_gi = _NSIS_LIMIT_BYTES / 1024**3
    payload_gi = payload_bytes / 1024**3
    if form == "auto":
        if payload_bytes <= _NSIS_LIMIT_BYTES:
            return "nsis", (
                f"payload≈{payload_gi:.2f}GiB（含 electron 客户端）≤ NSIS 上限 {limit_gi:.0f}GiB → 命中 NSIS"
            )
        if iscc:
            return "inno", (
                f"payload≈{payload_gi:.2f}GiB > NSIS 上限 {limit_gi:.0f}GiB，且检测到 iscc({iscc}) → 命中 Inno Setup"
            )
        return "dir", (
            f"payload≈{payload_gi:.2f}GiB > NSIS 上限 {limit_gi:.0f}GiB，但未检测到 iscc → 降级 dir 便携目录，"
            "安装包未产出"
        )
    if form == "nsis":
        return "nsis", f"--form nsis 显式指定（payload≈{payload_gi:.2f}GiB）"
    if form == "inno":
        if not iscc:
            raise BuildError(
                "--form inno 显式指定，但未检测到 iscc（Inno Setup 6 编译器）。安装指引："
                "从 https://jrsoftware.org/isdl.php 安装 Inno Setup 6 并把 ISCC.exe 加入 PATH，"
                f"或放置到 {' 或 '.join(_ISCC_CANDIDATES)} 后重跑。"
            )
        return "inno", f"--form inno 显式指定（payload≈{payload_gi:.2f}GiB，iscc={iscc}）"
    return "dir", f"--form dir 显式指定（payload≈{payload_gi:.2f}GiB）"


def _write_generated_config(out_dir: Path, runtime_dir: Path, form: str, zip_enabled: bool) -> list[str]:
    """以提交版 electron-builder.yml 为单一真相源，定点覆盖 output/target/runtime 后落临时配置。

    不用 `extends`：app-builder-lib 的 deepAssign 对数组做「并集合并」（win.target 无法收窄、
    extraResources 会翻倍），因此用文本覆盖生成等价独立配置，构建结束后删除。
    """
    targets = ["dir"]
    if form == "nsis":
        targets = ["dir", "nsis"]
    if zip_enabled:
        targets.append("zip")

    if not _CONFIG_PATH.is_file():
        raise BuildError(f"缺少 electron-builder 配置模板：{_CONFIG_PATH}")
    text = _CONFIG_PATH.read_text(encoding="utf-8")

    text, n_output = re.subn(r"(?m)^  output: .*$", f"  output: {out_dir.as_posix()}", text)
    target_block = "win:\n  target:\n" + "".join(f"    - {t}\n" for t in targets)
    text, n_target = re.subn(r"(?m)^win:\r?\n  target:\r?\n(?:    - [a-z]+\r?\n)+", target_block, text)

    n_runtime = 0
    if runtime_dir != _DEFAULT_RUNTIME_DIR:
        rel_runtime = os.path.relpath(runtime_dir, _FRONTEND_DIR).replace("\\", "/")
        text, n_runtime = re.subn(
            r"(?m)^  - from: \.\./build/runtime$", f"  - from: {rel_runtime}", text
        )

    if n_output != 1 or n_target != 1 or (runtime_dir != _DEFAULT_RUNTIME_DIR and n_runtime != 1):
        raise BuildError(
            "electron-builder.yml 模板结构变动导致定点覆盖失败"
            f"（output={n_output} target={n_target} runtime={n_runtime}）；请同步 tools/build_desktop.py"
        )

    header = (
        f"# 本文件由 tools/build_desktop.py 从 electron-builder.yml 自动生成（临时覆盖层），"
        f"构建结束后删除；请勿提交。\n# 覆盖项：directories.output={out_dir} / win.target={targets}"
        + (f" / runtime from={rel_runtime}" if n_runtime else "")
        + "\n"
    )
    _GENERATED_CONFIG_PATH.write_text(header + text, encoding="utf-8")
    _info(f"生成临时配置：{_GENERATED_CONFIG_PATH}（targets={targets}）")
    return targets


def _find_artifacts(out_dir: Path) -> list[dict]:
    artifacts: list[dict] = []
    unpacked = out_dir / "win-unpacked"
    if unpacked.exists():
        stats = _dir_stats(unpacked)
        stats["kind"] = "dir"
        artifacts.append(stats)
    for pattern, kind in (("*.exe", "installer"), ("*.zip", "zip")):
        for path in sorted(out_dir.glob(pattern)):
            stats = _dir_stats(path)
            stats["kind"] = kind
            artifacts.append(stats)
    return artifacts


def step_package(out_dir: Path, runtime_dir: Path, form: str, zip_enabled: bool, version: str,
                 iscc: str | None, out_dir_default: bool) -> dict:
    _info(f"步骤 4/7 载荷组装（零拷贝 extraResources）+ 出包（form={form} → {out_dir}）")
    eb = _FRONTEND_DIR / "node_modules" / ".bin" / "electron-builder.cmd"
    if not eb.is_file():
        raise BuildError(f"未找到 electron-builder：{eb}；请先在 frontend/ 执行 npm install")

    targets = _write_generated_config(out_dir, runtime_dir, form, zip_enabled)
    commands: list[str] = []
    inno_artifacts: list[dict] = []
    try:
        cmd = [str(eb), "--config", str(_GENERATED_CONFIG_PATH), "--publish", "never"]
        commands.append(" ".join(_quote(p) for p in cmd) + f"   (cwd={_FRONTEND_DIR})")
        # 长耗时（6GB 拷贝）交给外层超时/后台轮询；此处给足 3 小时
        code = _run(cmd, cwd=_FRONTEND_DIR, timeout=10800, label="electron-builder")
        if code != 0:
            raise BuildError(f"electron-builder 打包失败（退出码={code}）；配置={_GENERATED_CONFIG_PATH}")
    finally:
        try:
            _GENERATED_CONFIG_PATH.unlink()
        except OSError:
            pass

    if form == "inno":
        _info("步骤 5/7 Inno Setup 编译（iscc）")
        unpacked = out_dir / "win-unpacked"
        if not unpacked.exists():
            raise BuildError("Inno 分支需要 win-unpacked/ 载荷，但 electron-builder 未产出")
        inno_cmd = [
            iscc or "iscc",
            f"/DPayloadDir={unpacked}",
            f"/DOutputDir={out_dir}",
            f"/DAppVersion={version}",
            str(_INNO_SCRIPT),
        ]
        commands.append(" ".join(_quote(p) for p in inno_cmd) + f"   (cwd={_INNO_SCRIPT.parent})")
        code = _run(inno_cmd, cwd=_INNO_SCRIPT.parent, timeout=7200, label="inno-setup")
        if code != 0:
            raise BuildError(f"Inno Setup 编译失败（iscc 退出码={code}）")
        for path in sorted(out_dir.glob("CXO-ModelStation-Setup-*.exe")):
            stats = _dir_stats(path)
            stats["kind"] = "installer"
            inno_artifacts.append(stats)

    found = _find_artifacts(out_dir)
    artifacts: list[dict] = []
    seen: set[str] = set()
    for art in inno_artifacts + found:
        if art["path"] in seen:
            continue
        seen.add(art["path"])
        artifacts.append(art)
    installer = next((a for a in artifacts if a["kind"] == "installer"), None)
    return {
        "form": form,
        "targets": targets,
        "out_dir": str(out_dir),
        "out_dir_is_default": out_dir_default,
        "electron_builder_commands": commands,
        "artifacts": artifacts,
        "installer": installer,
        "installer_produced": installer is not None,
        "degraded": installer is None,
    }


# --------------------------------------------------------------------------- #
# 步骤 6/7：报告落盘与摘要                                                      #
# --------------------------------------------------------------------------- #
def _data_seed_listing() -> list[dict]:
    data_dir = _MS_ROOT / "data"
    items: list[dict] = []
    for root, _dirs, names in os.walk(data_dir):
        for name in names:
            path = Path(root) / name
            try:
                items.append({"rel": str(path.relative_to(data_dir)).replace("\\", "/"), "bytes": path.stat().st_size})
            except OSError:
                continue
    return sorted(items, key=lambda x: x["rel"])


def _md_report(report: dict) -> str:
    lines: list[str] = []
    lines.append(f"# CXO-ModelStation 桌面出包报告（{report['change_id']}）")
    lines.append("")
    lines.append(f"- 生成时间：{report['generated_at']}；总耗时：{report['elapsed_seconds']}s")
    lines.append(f"- 运行形态：profile={report['runtime']['profile']} torch={report['runtime']['torch_index']} "
                 f"source={report['runtime']['source']}")
    lines.append(f"- 判据：{report['payload']['reason']}")
    lines.append(f"- 安装包形态：{report['installer_form']['selected']}；"
                 f"安装包已产出：{report['installer']['installer_produced']}")
    lines.append("")
    lines.append("## 产物")
    lines.append("")
    lines.append("| 路径 | 类型 | 体积(MiB) | 文件数 |")
    lines.append("| --- | --- | --- | --- |")
    for art in report["installer"]["artifacts"]:
        lines.append(f"| `{art['path']}` | {art['kind']} | {_mib(art['bytes'])} | {art['files']} |")
    lines.append("")
    lines.append("## electron-builder / iscc 命令原文")
    lines.append("")
    for cmd in report["installer"]["electron_builder_commands"]:
        lines.append(f"```\n{cmd}\n```")
    lines.append("")
    lines.append("## 随包 data 种子清单")
    lines.append("")
    for item in report["data_seed"]:
        lines.append(f"- `{item['rel']}` ({item['bytes']} B)")
    lines.append("")
    return "\n".join(lines)


def write_report(report: dict) -> dict:
    _info("步骤 6/7 报告落盘")
    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    json_path = _REPORTS_DIR / "desktop_build_report.json"
    md_path = _REPORTS_DIR / "desktop_build_report.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_md_report(report), encoding="utf-8")
    _info(f"报告：{json_path}")
    _info(f"报告：{md_path}")
    return {"json": str(json_path), "md": str(md_path)}


def print_summary(report: dict) -> None:
    _info("步骤 7/7 摘要")
    forms = report["installer_form"]
    _info(f"形态命中：{forms['selected']}（{forms['reason']}）")
    for art in report["installer"]["artifacts"]:
        _info(f"  产物 [{art['kind']}] {art['path']}  {_mib(art['bytes'])}MiB / {art['files']} files")
    if not report["installer"]["installer_produced"]:
        _error("安装包未产出：payload 超过 NSIS 2GiB 上限且本机无 iscc，已产出 dir 便携目录作为交付形态。")
        _error("安装指引：安装 Inno Setup 6（https://jrsoftware.org/isdl.php）后重跑 "
               "`python tools/build_desktop.py --form inno` 即可得到 CXO-ModelStation-Setup-<ver>.exe。")


# --------------------------------------------------------------------------- #
# 入口                                                                          #
# --------------------------------------------------------------------------- #
def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="CXO-ModelStation 桌面安装包编排器")
    ap.add_argument("--runtime-profile", choices=["base", "full"], default="full",
                    help="运行时档位（仅当需要构建时使用；默认 full）")
    ap.add_argument("--torch-index", choices=["cpu", "cuda"], default="cuda",
                    help="torch 轮子源（默认 cuda）")
    ap.add_argument("--runtime-dir", default="build/runtime",
                    help="运行时目录（相对 CXO-ModelStation 或绝对；默认 build/runtime）")
    ap.add_argument("--out-dir", default="release",
                    help="产物目录（相对 CXO-ModelStation 或绝对；默认 release）")
    ap.add_argument("--form", choices=["auto", "nsis", "inno", "dir"], default="auto",
                    help="安装包形态（auto=按 payload 体积判据）")
    ap.add_argument("--skip-frontend", action="store_true", help="跳过前端构建")
    ap.add_argument("--skip-runtime", action="store_true", help="跳过运行时校验/构建")
    ap.add_argument("--rebuild-runtime", action="store_true", help="强制重建运行时（仅默认目录）")
    ap.add_argument("--zip", action="store_true", help="额外产出 zip（默认关）")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    runtime_dir = _resolve_under_root(args.runtime_dir)
    out_dir = _resolve_under_root(args.out_dir)
    out_dir_default = out_dir == _DEFAULT_OUT_DIR
    version = _read_json(_FRONTEND_DIR / "package.json").get("version", "0.1.0")

    _info("=" * 78)
    _info("CXO-ModelStation 桌面出包编排开始")
    _info(f"MS_ROOT={_MS_ROOT}")
    _info(f"runtime_dir={runtime_dir}  out_dir={out_dir}  form={args.form}  zip={args.zip}")

    started = datetime.now().isoformat(timespec="seconds")
    try:
        frontend = step_frontend_build(args.skip_frontend)
        runtime = step_runtime(
            runtime_dir, args.runtime_profile, args.torch_index, args.skip_runtime, args.rebuild_runtime
        )
        engines = step_engines_check()

        parts = _payload_parts(runtime_dir)
        payload_bytes = sum(p["bytes"] for p in parts.values())
        iscc = _resolve_iscc()
        _info(f"payload 估算≈{payload_bytes / 1024**3:.2f}GiB；iscc={'未检测到' if not iscc else iscc}")
        form, reason = _decide_form(args.form, payload_bytes, iscc)
        _info(f"形态判据：{reason}")

        packaged = step_package(out_dir, runtime_dir, form, args.zip, version, iscc, out_dir_default)

        report = {
            "change_id": "package-modelstation-desktop-installer",
            "task": "Task 3 打包编排与产物",
            "generated_at": started,
            "elapsed_seconds": round(time.monotonic() - _T0, 1),
            "frontend_build": frontend,
            "runtime": runtime,
            "engines_check": engines,
            "payload": {
                "reason": reason,
                "judgement_bytes": payload_bytes,
                "judgement_gib": round(payload_bytes / 1024**3, 3),
                "nsis_limit_bytes": _NSIS_LIMIT_BYTES,
                "parts": parts,
            },
            "installer_form": {
                "requested": args.form,
                "selected": form,
                "reason": reason,
                "iscc": iscc,
                "iscc_available": iscc is not None,
            },
            "installer": packaged,
            "data_seed": _data_seed_listing(),
            "cli": vars(args),
            "notes": [],
        }
        if form == "dir" and payload_bytes > _NSIS_LIMIT_BYTES and args.form == "auto":
            report["notes"].append(
                "payload 超过 NSIS 2GiB 上限且本机无 iscc：已产出 dir 便携目录，安装包未产出；"
                "安装 Inno Setup 6 后 `--form inno` 可得到 CXO-ModelStation-Setup-<ver>.exe。"
            )
        report["reports"] = write_report(report)

        print_summary(report)
        if not packaged["installer_produced"] and args.form == "auto":
            _error("本次交付形态为 dir 便携目录（安装包未产出），原因与指引见上。")
        _info("编排结束（成功）")
        return 0
    except BuildError as exc:
        _error(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())