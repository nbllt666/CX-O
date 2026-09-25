#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""CXO-ModelStation 便携 Python 运行时构建器（change-id: package-modelstation-desktop-installer / Task 2）。

目标：构建一个「包内嵌、可整体搬迁」的 CPython 3.10 运行时：
  build/runtime/python/python.exe        —— 官方嵌入式 amd64 发行版解压所得解释器
  build/runtime/python/Lib/site-packages —— 依赖安装目录
  build/runtime/runtime_manifest.json    —— 构建清单（版本/来源/探针/体积/命令）

幂等：重复执行会复用缓存与已就绪产物；``--force`` 强制重建运行时目录。
退出码：0 = 所有「应测」探针就绪；非 0 = 存在未就绪项（明细写入清单与日志）。

日志行格式（stdout 与 build/build_runtime.log 同步）::

    [2026-09-25 12:00:00] [INFO] [  12.3s] message

关键设计决策（已实测，见 Task 2 报告「._pth 隔离实验」）：
    嵌入式发行版自带的 ``python310._pth`` 会令解释器忽略 ``PYTHONPATH`` 环境变量、
    且 ``-m`` 启动时不再把 CWD 加入 ``sys.path``。而本项目的 VoxCPM 引擎依赖
    ``PYTHONPATH=<engines>/VoxCPM-main/src``、后端依赖 ``-m modelstation.main``（CWD=包根），
    两者都会被 ``._pth`` 破坏。故构建器删除 ``python310._pth``：删除后 CPython 走默认
    「landmark」路径方案，仍能定位同目录的 ``python310.zip`` 与 ``python/Lib/site-packages``，
    自动 import site，同时正常响应 ``PYTHONPATH`` 与 ``-m`` 的 CWD——且全程不写入任何绝对路径，
    搬迁能力不受影响。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

# --------------------------------------------------------------------------- #
# 路径与常量                                                                    #
# --------------------------------------------------------------------------- #
_T0 = time.time()

TOOLS_DIR = Path(__file__).resolve().parent
MS_ROOT = TOOLS_DIR.parent                       # CXO-ModelStation
BUILD_DIR = MS_ROOT / "build"
CACHE_DIR = BUILD_DIR / "cache"
STAGING_DIR = BUILD_DIR / "staging"
RUNTIME_DIR = BUILD_DIR / "runtime"
PY_DIR = RUNTIME_DIR / "python"
SP_DIR = PY_DIR / "Lib" / "site-packages"
LOG_FILE = BUILD_DIR / "build_runtime.log"
MANIFEST_PATH = RUNTIME_DIR / "runtime_manifest.json"
GEN_BACKEND_REQS = BUILD_DIR / "requirements-backend-runtime.txt"
GEN_ENGINE_REQS = BUILD_DIR / "requirements-engines-runtime.txt"

PY_EXE = PY_DIR / "python.exe"

PYTHON_VERSION = "3.10.11"
PY_EMBED_URL = (
    f"https://www.python.org/ftp/python/{PYTHON_VERSION}/"
    f"python-{PYTHON_VERSION}-embed-amd64.zip"
)
GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"
PYPI_INDEX = "https://pypi.tuna.tsinghua.edu.cn/simple"
TORCH_INDEX = {
    "cuda": "https://download.pytorch.org/whl/cu128",
    "cpu": "https://download.pytorch.org/whl/cpu",
}
# CPython 头文件/导入库（嵌入式发行版不含 Python.h，源码编译第三方扩展时必需）：
# 取官方 NuGet 包 python/<ver>（内含 tools/include/*.h 与 tools/libs/python3xx.lib）。
PY_HEADERS_URL = (
    f"https://api.nuget.org/v3-flatcontainer/python/{PYTHON_VERSION}/python.{PYTHON_VERSION}.nupkg"
)
PY_HEADERS_DIR = CACHE_DIR / "pyheaders"
# fairseq==0.12.2 的 PyPI sdist 缺 fairseq/clib/libbase/balanced_assignment.cpp（上游打包缺陷），
# 故源码改用 GitHub tag 归档（src 目录缓存复用，便于增量编译）。
FAIRSEQ_SRC_URL = "https://codeload.github.com/facebookresearch/fairseq/zip/refs/tags/v0.12.2"
FAIRSEQ_SRC_DIR = CACHE_DIR / "fairseq-src"
# 首次删除 python310._pth 时缓存其原文，供后续轮次的 manifest 保持完整 removed 记录
PTH_ORIGINAL_CACHE = CACHE_DIR / "python310._pth.original"
# 官方嵌入式发行版 zip 的缓存路径（同时也是取回原始 ._pth 的同一来源）
EMBED_ZIP_CACHE = CACHE_DIR / f"python-{PYTHON_VERSION}-embed-amd64.zip"

ENGINES_DIR = MS_ROOT / "engines"
SOVITS_DIR = ENGINES_DIR / "so-vits-svc-4.1-Stable"
MELOTTS_DIR = ENGINES_DIR / "MeloTTS"
VOXCPM_DIR = ENGINES_DIR / "VoxCPM-main"
VOXCPM_SRC = VOXCPM_DIR / "src"

SOVITS_REQUIRED_SCRIPTS = [
    "resample.py",
    "preprocess_flist_config.py",
    "preprocess_hubert_f0.py",
    "train.py",
    "inference_main.py",
    "train_index.py",
]

# 需单独安装的包：fairseq 依赖 omegaconf<2.1，而 omegaconf 2.0.x 的 wheel 元数据在 modern pip
# 下非法（PyYAML>=5.1.*）→ 与清单中的 omegaconf==2.3.0 直接冲突，无法进整单解析，必须 --no-deps 单独装。
RISKY_BUILDS = {"fairseq"}

# 后端探针（含 python-multipart：FastAPI 文件上传所需，pyproject.toml 声明）
_BACKEND_IMPORTS = "fastapi, uvicorn, pydantic, httpx, multipart"
# so-vits 就绪探针（任务规定集合）
_SOVITS_IMPORTS = "torch, librosa, soundfile, scipy, sklearn, faiss, pyworld"
# so-vits 扩展探针（信息性，不计入退出码）
_SOVITS_EXT_IMPORTS = "torchaudio, transformers, fairseq, torchcrepe, parselmouth, pynvml, soundfile"
# MeloTTS 扩展探针（信息性；`import melo` 因 melo/__init__.py 为空而过弱）
_MELO_EXT_IMPORTS = (
    "librosa, numba, cn2an, pypinyin, jieba, g2p_en, pykakasi, gruut, inflect, "
    "transformers, cached_path, huggingface_hub, unidic_lite, fugashi, anyascii, jamo"
)
# VoxCPM 职责分离：轻量可导入探针 vs 声明依赖探针（信息性）
_VOXCPM_DEEP_IMPORTS = "torchaudio, einops, safetensors, regex, huggingface_hub, librosa"

LOG_LEVELS = ("INFO", "WARN", "ERROR")


# --------------------------------------------------------------------------- #
# 日志                                                                          #
# --------------------------------------------------------------------------- #
def log(level: str, msg: str) -> None:
    elapsed = time.time() - _T0
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [{level}] [{elapsed:7.1f}s] {msg}"
    print(line, flush=True)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def _short(s: str, limit: int = 1500) -> str:
    s = (s or "").strip()
    return s if len(s) <= limit else "...(截断)..." + s[-limit:]


# --------------------------------------------------------------------------- #
# 子进程 / 下载                                                                 #
# --------------------------------------------------------------------------- #
def run(cmd, cwd=None, env=None, timeout=None) -> tuple[int, str, str]:
    """执行子进程并记录命令与输出尾部；返回 (returncode, stdout, stderr)。"""
    log("INFO", "RUN: " + subprocess.list2cmdline([str(c) for c in cmd]))
    try:
        proc = subprocess.run(
            [str(c) for c in cmd],
            cwd=str(cwd) if cwd else None,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        rc, out, err = proc.returncode, proc.stdout or "", proc.stderr or ""
    except subprocess.TimeoutExpired as exc:
        rc = 124
        out = (exc.stdout or b"").decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        err = f"TIMEOUT after {timeout}s\n" + (
            (exc.stderr or b"").decode("utf-8", "replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        )
    log("INFO", f"  -> rc={rc}")
    if rc != 0:
        for stream, text in (("stdout", out), ("stderr", err)):
            if text.strip():
                log("ERROR", f"  {stream} tail: {_short(text)}")
    return rc, out, err


def download(url: str, dest: Path, timeout: int = 300) -> None:
    """流式下载 url -> dest（幂等：dest 已存在且非空则跳过）。"""
    if dest.exists() and dest.stat().st_size > 0:
        log("INFO", f"缓存命中，跳过下载：{dest} ({dest.stat().st_size} bytes)")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    log("INFO", f"下载 {url} -> {dest}")
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url, timeout=timeout) as resp, open(tmp, "wb") as fh:
        shutil.copyfileobj(resp, fh)
    tmp.replace(dest)
    log("INFO", f"下载完成：{dest.stat().st_size} bytes")


# --------------------------------------------------------------------------- #
# 运行时基础环境                                                                #
# --------------------------------------------------------------------------- #
def resolve_embed_zip(from_local: str | None) -> Path:
    """定位嵌入式发行版 zip：优先 --from-local（zip 或目录），否则缓存/官方下载。"""
    zip_name = f"python-{PYTHON_VERSION}-embed-amd64.zip"
    cache_path = CACHE_DIR / zip_name
    if from_local:
        src = Path(from_local).expanduser()
        if src.is_dir():
            cands = sorted(src.glob("python-3.10*-embed-amd64.zip"))
            if not cands:
                raise SystemExit(f"[ERROR] --from-local 目录内未找到 python-3.10*-embed-amd64.zip: {src}")
            src = cands[-1]
        if not src.is_file():
            raise SystemExit(f"[ERROR] --from-local 路径不是文件/目录: {src}")
        log("INFO", f"--from-local 使用本地发行版：{src}")
        if src.resolve() != cache_path.resolve():
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, cache_path)
        return cache_path
    download(PY_EMBED_URL, cache_path)
    return cache_path


def pth_strategy_record(allow_remove: bool = True) -> dict:
    """返回 ``python310._pth`` 的处理记录。

    首次删除时把原文缓存到 ``build/cache/python310._pth.original``，使后续轮次仍能给出
    完整的 ``removed`` 记录（原文/理由/证据），避免退化成无信息的 ``absent``。
    """
    pth = PY_DIR / "python310._pth"
    reason = (
        "._pth 会使解释器忽略 PYTHONPATH 且 -m 不加 CWD 到 sys.path；"
        "VoxCPM 需 PYTHONPATH 指向 engines/VoxCPM-main/src，后端需 -m modelstation.main。"
        "删除后走默认 landmark 路径方案（同目录 python310.zip + Lib/site-packages 仍自动生效，"
        "自动 import site，.pth 文件开始生效），且不写入任何绝对路径。"
    )
    evidence = ("实测：_pth 存在时 `python -c \"import pkg\"`（PYTHONPATH 已设）与 "
                "`python -m pkg`（CWD=src）均 ModuleNotFoundError。")
    if pth.exists() and allow_remove:
        content = pth.read_text(encoding="utf-8", errors="replace")
        pth.unlink()
        try:
            PTH_ORIGINAL_CACHE.write_text(content, encoding="utf-8")
        except OSError:
            pass
        log("WARN", "已删除 python310._pth（保证 PYTHONPATH 与 -m 的 CWD 生效；见 manifest.pth_strategy）")
        return {"mode": "removed", "file": str(pth), "original_content": content,
                "cached_original": str(PTH_ORIGINAL_CACHE), "reason": reason, "evidence": evidence}
    if PTH_ORIGINAL_CACHE.is_file() or EMBED_ZIP_CACHE.is_file():
        content = None
        source = "cache"
        if PTH_ORIGINAL_CACHE.is_file():
            content = PTH_ORIGINAL_CACHE.read_text(encoding="utf-8", errors="replace")
        else:
            # 从缓存的官方嵌入发行版 zip 中取回原始 ._pth（同一来源文件，非臆造），并补写缓存
            try:
                import zipfile
                with zipfile.ZipFile(EMBED_ZIP_CACHE) as zf:
                    content = zf.read("python310._pth").decode("utf-8", "replace")
                PTH_ORIGINAL_CACHE.write_text(content, encoding="utf-8")
                source = "recovered_from_embed_zip"
            except Exception:  # noqa: BLE001
                content = None
        if content is not None:
            return {"mode": "removed", "file": str(pth), "original_content": content,
                    "cached_original": str(PTH_ORIGINAL_CACHE), "original_source": source,
                    "note": "本次未发现 ._pth（前序轮次已删除）；原文取自缓存/官方发行版以保持记录完整",
                    "reason": reason, "evidence": evidence}
    return {"mode": "absent", "file": str(pth), "note": "未发现 python310._pth 且无缓存原文"}


def extract_runtime(embed_zip: Path, force: bool) -> dict:
    """解压嵌入式 python 到 build/runtime/python，并处理 ._pth / site-packages。"""
    info: dict = {"pth_strategy": None, "extracted": False}
    need_extract = force or not PY_EXE.exists()
    if need_extract:
        if PY_DIR.exists():
            log("INFO", f"--force 清理既有运行时目录：{PY_DIR}")
            shutil.rmtree(PY_DIR, ignore_errors=True)
        PY_DIR.mkdir(parents=True, exist_ok=True)
        log("INFO", f"解压 {embed_zip.name} -> {PY_DIR}")
        shutil.unpack_archive(str(embed_zip), str(PY_DIR), "zip")
        info["extracted"] = True
    else:
        log("INFO", f"运行时已存在，跳过解压：{PY_EXE}")

    if not PY_EXE.exists():
        raise SystemExit(f"[ERROR] 解压后未找到解释器：{PY_EXE}")

    # 删除 ._pth（理由见模块 docstring）；原文缓存到 build/cache 以便后续轮次保持完整记录
    info["pth_strategy"] = pth_strategy_record(allow_remove=True)

    SP_DIR.mkdir(parents=True, exist_ok=True)
    return info


def base_env(extra: dict | None = None, keep_pythonpath: bool = False) -> dict:
    """构造运行时子进程环境：禁 pyc 写入（保护只读的 engines/）、禁用户 site、清 PYTHONPATH。"""
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONNOUSERSITE"] = "1"
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    env["PIP_NO_INPUT"] = "1"
    if not keep_pythonpath:
        env.pop("PYTHONPATH", None)
    if extra:
        env.update({k: str(v) for k, v in extra.items()})
    return env


def ensure_pip(pypi_index: str, force: bool) -> None:
    if not force:
        rc, _, _ = run([PY_EXE, "-m", "pip", "--version"], env=base_env(), timeout=120)
        if rc == 0:
            log("INFO", "pip 已就绪，跳过安装")
            return
    get_pip = CACHE_DIR / "get-pip.py"
    download(GET_PIP_URL, get_pip)
    rc, out, err = run(
        [PY_EXE, str(get_pip), "--no-input", "--no-warn-script-location", "-i", pypi_index],
        env=base_env(),
        timeout=900,
    )
    if rc != 0:
        raise SystemExit(f"[ERROR] get-pip 安装失败 rc={rc}\n{_short(err or out)}")
    run([PY_EXE, "-m", "pip", "install", "--no-input", "setuptools", "wheel",
         "-i", pypi_index, "--no-warn-script-location"], env=base_env(), timeout=900)


# --------------------------------------------------------------------------- #
# 依赖安装                                                                      #
# --------------------------------------------------------------------------- #
def _read_req_lines(path: Path) -> list[str]:
    lines = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        lines.append(s)
    return lines


def _clean_req(req_line: str) -> str:
    """去除行内注释，得到可直接交给 pip 的 requirement 字符串。"""
    return req_line.split("#", 1)[0].strip()


def _pkg_name(req_line: str) -> str:
    s = req_line.split("#", 1)[0].strip()
    for sep in ("==", ">=", "<=", "~=", "!=", ">", "<", "[", ";", " "):
        s = s.split(sep, 1)[0]
    return s.strip().lower().replace("_", "-")


def build_backend_requirements() -> tuple[Path, list[str], list[str]]:
    """生成后端运行时依赖文件：过滤 pytest 类测试专用依赖，补 python-multipart。"""
    src = MS_ROOT / "requirements.txt"
    kept, dropped = [], []
    for line in _read_req_lines(src):
        name = _pkg_name(line)
        if name.startswith("pytest"):
            dropped.append(line)
            continue
        kept.append(line)
    if not any(_pkg_name(x) == "python-multipart" for x in kept):
        kept.append("python-multipart    # pyproject.toml（FastAPI 文件上传；requirements.txt 漏列）")
    GEN_BACKEND_REQS.write_text(
        "# 由 tools/build_runtime.py 生成：MS_ROOT/requirements.txt 过滤测试依赖 + python-multipart（行内注释已剥离）\n"
        + "\n".join(_clean_req(x) for x in kept) + "\n",
        encoding="utf-8",
    )
    return GEN_BACKEND_REQS, kept, dropped


def build_engine_requirements() -> tuple[Path, list[str], list[str], list[str]]:
    """生成引擎依赖文件（行内注释已剥离）。

    剔除两类不进整单安装的行：
      - torch/torchaudio（由 --torch-index 轮子源单独安装）；
      - RISKY_BUILDS（fairseq：依赖 omegaconf<2.1，其 2.0.x 元数据在 modern pip 下非法，
        与清单中的 omegaconf==2.3.0 解析冲突，需 --no-deps 单独安装）。
    返回 (生成文件, 整单安装行, 单独安装行, 被剔除的 torch 行)。
    """
    src = TOOLS_DIR / "requirements-engines.txt"
    kept, risky, dropped = [], [], []
    for line in _read_req_lines(src):
        name = _pkg_name(line)
        if name in ("torch", "torchaudio"):
            dropped.append(line)
            continue
        if name in RISKY_BUILDS:
            risky.append(line)
            continue
        kept.append(line)
    GEN_ENGINE_REQS.write_text(
        "# 由 tools/build_runtime.py 生成：requirements-engines.txt 剔除 torch/torchaudio 与单独安装项（行内注释已剥离）\n"
        + "\n".join(_clean_req(x) for x in kept) + "\n",
        encoding="utf-8",
    )
    return GEN_ENGINE_REQS, kept, risky, dropped


def pip_install(args: list[str], timeout: int, stage: str) -> tuple[int, str, str]:
    cmd = [PY_EXE, "-m", "pip", "install", "--no-input", "--no-warn-script-location",
           "--disable-pip-version-check"] + args
    log("INFO", f"[{stage}] pip 安装开始（timeout={timeout}s）")
    return run(cmd, env=base_env(), timeout=timeout)


def install_backend(timeout: int) -> dict:
    req_file, kept, dropped = build_backend_requirements()
    rc, out, err = pip_install(["-r", str(req_file), "-i", PYPI_INDEX], timeout, "backend")
    return {
        "requirements_file": str(req_file),
        "installed_lines": kept,
        "filtered_out": dropped,
        "rc": rc,
        "tail": _short(err or out, 800),
        "index": PYPI_INDEX,
    }


def _torch_state() -> dict:
    """读取运行时当前 torch/torchaudio 版本与 CUDA 风味（无法导入时返回 error）。"""
    code = (
        "import json\n"
        "try:\n"
        "    import torch, torchaudio\n"
        "    print('TORCH=' + json.dumps({'torch': torch.__version__, 'torchaudio': torchaudio.__version__, 'cuda': torch.version.cuda}))\n"
        "except Exception as exc:\n"
        "    print('TORCH=' + json.dumps({'error': f'{type(exc).__name__}: {exc}'}))\n"
    )
    rc, out, err = run([PY_EXE, "-c", code], env=base_env(), timeout=300)
    for line in (out or "").splitlines():
        if line.startswith("TORCH="):
            return json.loads(line.split("=", 1)[1])
    return {"error": _short(err or out, 200)}


def install_torch(torch_index_url: str, timeout: int, desired: str = "cuda") -> dict:
    """安装 torch/torchaudio，并强制使实际风味与 --torch-index 一致。

    坑（实测）：不带版本约束的 ``pip install torch`` 会把已装的其它风味视为「已满足」
    （如已装 2.14.0+cpu 时，请求 cu128 源的 2.11.0+cu128 不会被安装），导致
    「manifest 写 cuda、实装却是 cpu」。故先探测实际风味，不一致时用
    ``--force-reinstall --no-deps`` 从目标轮子源重装，并在结果中给出 after 状态。
    """
    before = _torch_state()
    actual = "cuda" if before.get("cuda") else ("cpu" if before.get("torch") else None)
    args = ["torch", "torchaudio", "--index-url", torch_index_url]
    info = {"index": torch_index_url, "desired_flavor": desired, "before": before, "actual_before": actual}
    if actual is not None and actual != desired:
        args += ["--force-reinstall", "--no-deps"]
        log("WARN", f"已装 torch 风味={actual} 与目标={desired} 不一致，改用 --force-reinstall --no-deps 重装")
    rc, out, err = pip_install(args, timeout, "torch")
    after = _torch_state()
    info.update({"rc": rc, "cmd_args": args, "after": after,
                 "tail": _short(err or out, 500) if rc else ""})
    info["flavor_ok"] = bool(after.get("cuda")) if desired == "cuda" else (
        bool(after.get("torch")) and not after.get("cuda"))
    return info


def ensure_python_headers() -> dict:
    """下载并展开官方 CPython NuGet 包，取得 Include/ 与 libs/（源码编译第三方扩展用）。

    嵌入式发行版不含 Python.h，导致 C/C++ 扩展（fairseq 的 libbleu/clib 等）编译报
    `fatal error C1083: 无法打开包括文件: "Python.h"`。头文件/导入库仅构建期使用，
    不放进交付运行时目录（保持运行时精简）。
    """
    nupkg = CACHE_DIR / f"python.{PYTHON_VERSION}.nupkg"
    download(PY_HEADERS_URL, nupkg)
    include = PY_HEADERS_DIR / "tools" / "include"
    libs = PY_HEADERS_DIR / "tools" / "libs"
    if not (include.is_dir() and libs.is_dir()):
        log("INFO", f"展开 CPython 头文件/导入库 -> {PY_HEADERS_DIR}")
        if PY_HEADERS_DIR.exists():
            shutil.rmtree(PY_HEADERS_DIR, ignore_errors=True)
        PY_HEADERS_DIR.mkdir(parents=True, exist_ok=True)
        shutil.unpack_archive(str(nupkg), str(PY_HEADERS_DIR), "zip")
    return {
        "url": PY_HEADERS_URL,
        "nupkg": str(nupkg),
        "include": str(include),
        "libs": str(libs),
        "header_count": len(list(include.glob("*.h"))) if include.is_dir() else 0,
    }


def _build_env(headers: dict | None) -> dict:
    """源码编译用环境：在 base_env 上注入 INCLUDE/LIB（cl.exe/link.exe 借此定位 Python.h 与 python310.lib）。"""
    if not headers:
        return base_env()
    env = base_env()
    extra = {
        "INCLUDE": os.pathsep.join([headers.get("include", ""), env.get("INCLUDE", "")]).strip(os.pathsep),
        "LIB": os.pathsep.join([headers.get("libs", ""), env.get("LIB", "")]).strip(os.pathsep),
    }
    return base_env(extra)


def sanitize_runtime_for_relocation() -> dict:
    """安装收尾的「搬迁净化」，消除一切构建机绝对路径绑定。

    处理两类实测命中：
      1) ``python/Scripts/*``：pip 生成的 console 入口（.exe 启动器二进制内嵌 + .py 的
         ``#!C:\\...\\python.exe`` shebang）把构建机解释器绝对路径烘死，搬迁后全部失效。
         本项目运行时不依赖任何 console_scripts（后端/引擎一律用 ``python.exe -m`` 或
         ``python.exe <script>``；pip 亦可用 ``python -m pip``），故整体移除 Scripts。
      2) ``*.dist-info/direct_url.json``：仅当安装来源为本地路径（file:// 或含构建机盘符）
         才写入，属 pip 溯源元数据，不影响运行时；清除以保证零命中。
    """
    report: dict = {"removed_scripts_dir": None, "removed_direct_urls": [], "kept_direct_urls": []}

    scripts = PY_DIR / "Scripts"
    if scripts.exists():
        exe_n = len(list(scripts.glob("*.exe")))
        py_n = len(list(scripts.glob("*.py")))
        shutil.rmtree(scripts, ignore_errors=True)
        report["removed_scripts_dir"] = {
            "path": str(scripts), "exe_launchers": exe_n, "py_scripts": py_n,
            "reason": "console 入口内嵌构建机解释器绝对路径，搬迁后失效；运行时统一走 `python -m`",
        }
        log("WARN", f"已移除 {scripts}（{exe_n} 个 .exe / {py_n} 个 .py console 入口，均内嵌构建机绝对路径）")

    if SP_DIR.is_dir():
        for du in list(SP_DIR.glob("*.dist-info/direct_url.json")):
            try:
                raw = du.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            rel = str(du.relative_to(RUNTIME_DIR))
            if "file://" in raw or any(n in raw for n in (r"C:\CX-O", r"C:\CX-A", r"C:\Users\\")):
                report["removed_direct_urls"].append({"path": rel, "content": raw.strip()[:200]})
                du.unlink()
            else:
                report["kept_direct_urls"].append({"path": rel, "content": raw.strip()[:200]})
    if report["removed_direct_urls"]:
        log("WARN", f"已清除指向构建机本地路径的 direct_url.json {len(report['removed_direct_urls'])} 个（pip 溯源元数据）")
    return report


def install_fairseq_fallback(timeout: int, torch_index_url: str, headers: dict | None) -> dict:
    """fairseq==0.12.2 的退化安装链（三步全部留证）。

    实证阻断链：
      1) 依赖解析：fairseq 依赖 omegaconf<2.1，而 omegaconf 2.0.x 元数据在 modern pip 下非法
         （`PyYAML>=5.1.*`）→ ResolutionImpossible；
      2) PyPI sdist 构建：sdist 缺 fairseq/clib/libbase/balanced_assignment.cpp（上游打包缺陷）
         → C1083 编译失败；
      3) GitHub tag 源码：需 CPython 头文件（嵌入式发行版不含，由 ensure_python_headers 提供），
         且 setup.py 会 `os.symlink('../examples', 'fairseq/examples')`（Windows 非开发者模式报
         WinError 1314），故先预建该目录以跳过符号链接。
    通过条件：`import fairseq` 成功。
    """
    info: dict = {"steps": [], "python_headers": headers}
    pip_head = [PY_EXE, "-m", "pip", "install", "--no-input", "--no-warn-script-location",
                "--disable-pip-version-check"]

    # 步骤 1：留证——复现 omegaconf 元数据导致的解析不可解
    log("INFO", "[fairseq] 步骤1：复现依赖解析阻断（--dry-run）")
    run(pip_head + ["fairseq==0.12.2", "--dry-run", "-i", PYPI_INDEX], env=base_env(), timeout=timeout)

    # 步骤 2：留证——PyPI sdist 缺 cpp 文件的构建失败（带 Python 头文件，排除头文件因素）
    log("INFO", "[fairseq] 步骤2：PyPI sdist --no-deps --no-build-isolation 构建")
    rc, out, err = run(pip_head + ["fairseq==0.12.2", "--no-deps", "--no-build-isolation", "-i", PYPI_INDEX],
                       env=_build_env(headers), timeout=timeout)
    info["steps"].append({"step": "PyPI sdist --no-deps --no-build-isolation", "rc": rc,
                          "tail": _short(err or out, 700) if rc else ""})
    if rc == 0:
        already = "already satisfied" in (out + err).lower()
        info.update({"rc": 0, "method": "already-satisfied" if already else "pypi-sdist"})
        probe = _probe(["-c", "import fairseq; print('fairseq', fairseq.__version__)"])
        info["import_probe"] = {"status": probe["status"], "stderr_tail": probe["stderr_tail"]}
        return info

    # 步骤 3：GitHub tag 源码（缓存复用以便增量编译），预建 examples 目录，带头文件编译
    log("INFO", "[fairseq] 步骤3：改用 GitHub tag 源码构建（含缺失的 libbase/*.cpp）")
    src_root = FAIRSEQ_SRC_DIR / "fairseq-0.12.2"
    if not (src_root / "setup.py").is_file():
        tar = CACHE_DIR / "fairseq-0.12.2-github.zip"
        download(FAIRSEQ_SRC_URL, tar)
        if FAIRSEQ_SRC_DIR.exists():
            shutil.rmtree(FAIRSEQ_SRC_DIR, ignore_errors=True)
        shutil.unpack_archive(str(tar), str(FAIRSEQ_SRC_DIR), "zip")
    (src_root / "fairseq" / "examples").mkdir(parents=True, exist_ok=True)
    cmd = pip_head + ["--no-deps", "--no-build-isolation", str(src_root),
                      "-i", PYPI_INDEX, "--extra-index-url", torch_index_url]
    log("INFO", "RUN: " + subprocess.list2cmdline(cmd))
    rc3, out3, err3 = run(cmd, env=_build_env(headers), timeout=timeout)
    info["steps"].append({"step": "GitHub tag 源码 --no-deps --no-build-isolation（INCLUDE/LIB=Python 头文件）",
                          "rc": rc3, "source": FAIRSEQ_SRC_URL, "tail": _short(err3 or out3, 700) if rc3 else ""})
    info["rc"] = rc3
    info["method"] = "github-tag-source" if rc3 == 0 else "failed"
    if rc3 == 0:
        probe = _probe(["-c", "import fairseq; print('fairseq', fairseq.__version__)"])
        info["import_probe"] = {"status": probe["status"], "stdout_tail": probe["stdout_tail"],
                                "stderr_tail": probe["stderr_tail"]}
        log("INFO" if probe["status"] == "PASS" else "WARN",
            f"fairseq 安装完成，import 探针={probe['status']}")
    else:
        log("ERROR", "fairseq 安装失败（三条路径均失败）")
    return info


def install_engines(timeout: int, torch_index_url: str, best_effort: bool, headers: dict | None = None) -> dict:
    req_file, kept, risky, dropped = build_engine_requirements()
    args = ["-r", str(req_file), "-i", PYPI_INDEX, "--extra-index-url", torch_index_url]
    rc, out, err = pip_install(args, timeout, "engines")
    result = {
        "requirements_file": str(req_file),
        "installed_lines": kept,
        "excluded_risky_lines": risky,
        "filtered_out_torch": dropped,
        "attempts": [{"cmd_args": args, "rc": rc, "tail": _short(err or out, 800)}],
    }
    method = None
    if rc != 0:
        log("WARN", "引擎依赖整单安装失败，尝试 --no-build-isolation 二次安装")
        rc2, out2, err2 = pip_install(args + ["--no-build-isolation"], timeout, "engines-retry")
        result["attempts"].append({"cmd_args": args + ["--no-build-isolation"], "rc": rc2,
                                   "tail": _short(err2 or out2, 800)})
        if rc2 == 0:
            method = "requirements-single-pass(no-build-isolation)"
        elif not best_effort:
            method = "failed"
        else:
            log("WARN", "整单安装仍失败，转入逐条尽力安装（记录逐项结果，最大化覆盖）")
            per_pkg = []
            for line in kept:
                name = _pkg_name(line)
                clean = _clean_req(line)
                base_args = [clean, "-i", PYPI_INDEX, "--extra-index-url", torch_index_url]
                rc3, out3, err3 = pip_install(base_args, timeout, f"pkg:{name}")
                entry = {"line": line, "rc": rc3, "mode": "build-isolation",
                         "tail": _short(err3 or out3, 400) if rc3 else ""}
                if rc3 != 0:
                    # 无 cp310 win 轮子的包需源码编译：用运行时内已装的 cython/numpy/torch/setuptools
                    # 直接构建（关闭构建隔离）。
                    log("WARN", f"  逐条安装 {name} 隔离构建失败，改用 --no-build-isolation 重试")
                    rc4, out4, err4 = pip_install(base_args + ["--no-build-isolation"], timeout, f"pkg:{name}:nobi")
                    entry["rc_no_build_isolation"] = rc4
                    if rc4 == 0:
                        entry["rc"] = 0
                        entry["mode"] = "no-build-isolation"
                        entry["tail"] = ""
                    else:
                        entry["tail"] = _short(err4 or out4, 400)
                per_pkg.append(entry)
                log("INFO" if entry["rc"] == 0 else "WARN",
                    f"  逐条安装 {name}: rc={entry['rc']} ({entry['mode']})")
            result["per_package"] = per_pkg
            method = "best-effort-per-package"
    else:
        method = "requirements-single-pass"
    result["method"] = method
    result["fairseq"] = install_fairseq_fallback(timeout, torch_index_url, headers)
    return result


def install_melo(timeout: int) -> dict:
    """MeloTTS 的 melo 包：优先「暂存副本 + 非可编辑 pip install」，失败/数据缺失则拷贝源码。

    绝不直接 pip install engines/MeloTTS（会向只读引擎目录写 egg-info/build），
    也绝不使用 -e/可编辑安装。
    """
    info: dict = {
        "engine_dir": str(MELOTTS_DIR),
        "edit": False,
        "engine_dir_mutated": False,
    }
    staging = STAGING_DIR / "MeloTTS"

    def _copy_staging() -> None:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True, exist_ok=True)
        ignore = shutil.ignore_patterns("__pycache__", "*.pyc", ".git", "test", "docs")
        for item in ("setup.py", "requirements.txt", "melo"):
            s = MELOTTS_DIR / item
            if s.is_dir():
                shutil.copytree(s, staging / item, ignore=ignore)
            elif s.is_file():
                shutil.copy2(s, staging / item)
        log("INFO", f"MeloTTS 源码已暂存（避免写入只读引擎目录）：{staging}")

    def _installed_melo_has_data() -> tuple[bool, str]:
        code = (
            "import os, melo\n"
            "p = os.path.dirname(melo.__file__)\n"
            "need = [os.path.join(p,'text','cmudict.rep'), os.path.join('text','cmudict_cache.pickle')]\n"
            "miss = [n for n in need if not os.path.exists(os.path.join(p,n))]\n"
            "print('MELO_PATH=' + p)\n"
            "print('MISSING=' + ','.join(miss))\n"
        )
        rc, out, err = run([PY_EXE, "-c", code], env=base_env(), timeout=180)
        if rc != 0:
            return False, f"import melo 失败: {_short(err or out, 300)}"
        missing = ""
        for line in (out or "").splitlines():
            if line.startswith("MISSING="):
                missing = line.split("=", 1)[1].strip()
        return (missing == ""), (f"缺少数据文件: {missing}" if missing else "ok")

    try:
        _copy_staging()
        rc, out, err = pip_install([str(staging), "--no-deps", "--no-build-isolation"], timeout, "melotts")
        info["pip_attempt"] = {"staging_dir": str(staging), "rc": rc, "tail": _short(err or out, 800)}
        if rc == 0:
            ok, why = _installed_melo_has_data()
            if ok:
                info["method"] = "pip-install-staged-non-editable"
                info["reason"] = "从 build/staging 的源码副本非可编辑安装成功，且数据文件完整"
                return info
            info["pip_attempt"]["data_check"] = why
            log("WARN", f"pip 安装成功但数据文件不完整（{why}），退化拷贝源码")
        else:
            log("WARN", "MeloTTS pip 安装失败，退化拷贝源码")
    except Exception as exc:  # noqa: BLE001
        info["pip_attempt"] = {"staging_dir": str(staging), "rc": -1, "tail": f"{type(exc).__name__}: {exc}"}
        log("WARN", f"MeloTTS pip 安装异常，退化拷贝源码: {exc}")

    # 退化：拷贝源码（含全部数据文件），不使用 -e
    dest = SP_DIR / "melo"
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    shutil.copytree(MELOTTS_DIR / "melo", dest, ignore=ignore)
    info["method"] = "copy-source"
    info["reason"] = (
        "pip 安装（含 --no-build-isolation / --no-deps）失败或数据文件不完整；"
        "退化拷贝 engines/MeloTTS/melo 源码树到 site-packages（含 cmudict 数据），未使用 -e。"
    )
    info["dest"] = str(dest)
    info["engine_dir_mutated"] = False
    log("INFO", f"已拷贝 melo 源码 -> {dest}")
    return info


# --------------------------------------------------------------------------- #
# 探针与扫描                                                                    #
# --------------------------------------------------------------------------- #
def _probe(py_args: list[str], cwd: Path | None = None, extra_env: dict | None = None) -> dict:
    rc, out, err = run([PY_EXE] + py_args, cwd=cwd, env=base_env(extra_env), timeout=600)
    return {
        "status": "PASS" if rc == 0 else "FAIL",
        "cmd": subprocess.list2cmdline([str(PY_EXE)] + [str(a) for a in py_args]),
        "cwd": str(cwd) if cwd else None,
        "env_extra": extra_env or {},
        "rc": rc,
        "stdout_tail": _short(out, 600),
        "stderr_tail": _short(err, 600),
    }


def run_probes(profile: str) -> dict:
    probes: dict = {}

    probes["backend"] = _probe(["-c", f"import {_BACKEND_IMPORTS}; print('backend-imports-ok')"])
    probes["backend"]["role"] = "运行时就绪基线（fastapi/uvicorn/pydantic/httpx/python-multipart）"

    if profile != "full":
        for key, role in (
            ("sovits", "so-vits-svc 训练/推理链路"),
            ("voxcpm", "VoxCPM 引擎（PYTHONPATH 指向包源码）"),
            ("melotts", "MeloTTS 引擎（cwd=引擎根 import melo）"),
        ):
            probes[key] = {"status": "SKIPPED", "reason": f"profile={profile} 不含引擎依赖", "role": role}
        return probes

    # so-vits：脚本存在性 + 导入探针
    missing = [s for s in SOVITS_REQUIRED_SCRIPTS if not (SOVITS_DIR / s).is_file()]
    p = _probe(["-c", f"import {_SOVITS_IMPORTS}; print('sovits-imports-ok')"])
    p["role"] = "so-vits-svc 训练/推理链路"
    p["required_scripts_missing"] = missing
    p["scripts_checked"] = SOVITS_REQUIRED_SCRIPTS
    if missing and p["status"] == "PASS":
        p["status"] = "FAIL"
        p["stderr_tail"] = f"缺少必需脚本: {missing}"
    probes["sovits"] = p
    probes["sovits_extended"] = _probe(["-c", f"import {_SOVITS_EXT_IMPORTS}; print('sovits-ext-ok')"])
    probes["sovits_extended"]["informational"] = True

    # fairseq：so-vits 预处理（hubert 特征）实码依赖，单列为就绪门（计入退出码）
    fq = _probe(["-c", "import fairseq; print('fairseq-ok')"])
    fq["role"] = "so-vits 预处理链路 fairseq（vencoder 实码 from fairseq import checkpoint_utils）"
    probes["sovits_fairseq"] = fq

    # VoxCPM：带 PYTHONPATH 指向包源码
    v_env = {"PYTHONPATH": str(VOXCPM_SRC)}
    v1 = _probe(["-c", "import transformers, torch; print('voxcpm-base-ok')"], extra_env=v_env)
    v2 = _probe(["-c", "import voxcpm; print('voxcpm-ok')"], extra_env=v_env)
    v2["role"] = "VoxCPM（PYTHONPATH=engines/VoxCPM-main/src，非 editable）"
    v2["pythonpath"] = str(VOXCPM_SRC)
    v2["declared_deps_note"] = (
        "engines/VoxCPM-main/pyproject.toml 声明 transformers>=4.36.2；"
        "本运行时因 MeloTTS 钉 transformers==4.27.4，可能存在声明与实装版本差异。"
    )
    v2["base_imports"] = {"status": v1["status"], "tail": v1["stderr_tail"]}
    if v1["status"] == "FAIL" and v2["status"] == "PASS":
        v2["status"] = "FAIL"
        v2["stderr_tail"] = "transformers/torch 基线导入失败"
    probes["voxcpm"] = v2
    probes["voxcpm_extended"] = _probe(["-c", f"import {_VOXCPM_DEEP_IMPORTS}; print('voxcpm-ext-ok')"], extra_env=v_env)
    probes["voxcpm_extended"]["informational"] = True

    # VoxCPM CLI 入口（后端以 `sys.executable -m voxcpm ...` 调用）——信息性，用于暴露入口缺口
    vcli = _probe(["-m", "voxcpm", "--help"], extra_env=v_env)
    vcli["role"] = "VoxCPM CLI 入口可用性（后端 modelstation/services/voxcpm_client.py 用 -m voxcpm 调用）"
    vcli["informational"] = True
    vcli["note"] = (
        "实测 engines/VoxCPM-main/src/voxcpm 内无 __main__.py，`-m voxcpm` 必然报 "
        "No module named voxcpm.__main__；引擎实际入口为 console_script `voxcpm = voxcpm.cli:main`。"
        "打包态需由 Task 3 调整调用方式（改用 `-m voxcpm.cli` 或直接执行 console 脚本）。"
    )
    probes["voxcpm_cli"] = vcli

    # MeloTTS：cwd=引擎根 import melo（教练器就绪探针实码）
    m1 = _probe(["-c", "import melo; print('melo-ok')"], cwd=MELOTTS_DIR)
    m1["role"] = "MeloTTS 训练就绪探针（cwd=engines/MeloTTS）"
    probes["melotts"] = m1
    probes["melotts_extended"] = _probe(["-c", f"import {_MELO_EXT_IMPORTS}; print('melo-ext-ok')"], cwd=MELOTTS_DIR)
    probes["melotts_extended"]["informational"] = True

    # 说明：上面的 `cwd=引擎根 import melo` 会被引擎目录自身遮蔽（melo/ 就在 CWD 下），
    # 因此额外用中性 CWD 验证 melo 是否真的落入 runtime 的 Lib/site-packages。
    m_site = _probe(["-c", "import melo, os; print('melo_path=' + os.path.dirname(melo.__file__))"], cwd=MS_ROOT)
    m_site["role"] = "验证 melo 包位于 runtime site-packages（CWD 中性，避免引擎目录遮蔽）"
    m_site["informational"] = True
    probes["melotts_site_packages"] = m_site

    return probes


def scan_runtime() -> dict:
    total = 0
    count = 0
    for root, _dirs, files in os.walk(RUNTIME_DIR):
        for f in files:
            fp = Path(root) / f
            try:
                total += fp.stat().st_size
                count += 1
            except OSError:
                pass
    return {"size_mb": round(total / (1024 * 1024), 2), "file_count": count}


def collect_packages() -> dict:
    code = (
        "import importlib.metadata as m, json\n"
        "d = {}\n"
        "for dist in m.distributions():\n"
        "    name = dist.metadata['Name']\n"
        "    if name:\n"
        "        d[name] = dist.version\n"
        "print(json.dumps(d, sort_keys=True))\n"
    )
    rc, out, err = run([PY_EXE, "-c", code], env=base_env(), timeout=300)
    if rc != 0:
        return {"_error": _short(err or out, 400)}
    try:
        return json.loads(out.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"_error": "无法解析包清单输出"}


def compute_exit_code(probes: dict) -> tuple[int, list[str]]:
    pending = []
    for name, p in probes.items():
        if p.get("informational"):
            continue
        status = p.get("status")
        if status == "PASS" or status == "SKIPPED":
            continue
        pending.append(f"{name}: {status} ({p.get('stderr_tail') or p.get('reason') or ''})")
    return (0 if not pending else 1), pending


# --------------------------------------------------------------------------- #
# 主流程                                                                        #
# --------------------------------------------------------------------------- #
def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="构建 CXO-ModelStation 便携 Python 运行时")
    ap.add_argument("--profile", choices=["base", "full"], default="base",
                    help="base=仅后端依赖；full=后端 + 三引擎依赖（默认 base）")
    ap.add_argument("--torch-index", choices=["cpu", "cuda"], default="cuda",
                    help="torch/torchaudio 轮子源（默认 cuda -> cu128）")
    ap.add_argument("--from-local", default=None, help="本地嵌入式发行版 zip 或包含该 zip 的目录")
    ap.add_argument("--force", action="store_true", help="强制重建运行时目录与重装依赖")
    ap.add_argument("--verify-only", action="store_true", help="只对既有运行时跑探针与扫描，不安装")
    ap.add_argument("--pypi-index", default=PYPI_INDEX, help=f"PyPI 镜像（默认 {PYPI_INDEX}）")
    ap.add_argument("--no-best-effort", action="store_true", help="full 档整单安装失败时不逐条尽力安装")
    ap.add_argument("--pipe-timeout", type=int, default=3600, help="pip 命令超时秒（默认 3600）")
    ap.add_argument("--download-timeout", type=int, default=300, help="下载超时秒（默认 300）")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    started = datetime.now().isoformat(timespec="seconds")
    log("INFO", "=" * 78)
    log("INFO", f"CXO-ModelStation 便携运行时构建器 profile={args.profile} torch_index={args.torch_index} "
                f"verify_only={args.verify_only} force={args.force}")
    log("INFO", f"MS_ROOT={MS_ROOT}")
    log("INFO", f"RUNTIME_DIR={RUNTIME_DIR}")

    manifest: dict
    if args.verify_only and MANIFEST_PATH.is_file():
        try:
            manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
            log("INFO", "verify-only：载入既有 manifest，仅刷新探针/扫描字段")
        except ValueError:
            manifest = {}
    else:
        manifest = {}

    if not args.verify_only:
        embed_zip = resolve_embed_zip(args.from_local)
        extract_info = extract_runtime(embed_zip, force=args.force)
        ensure_pip(args.pypi_index, force=args.force)

        backend_info = install_backend(args.pipe_timeout)
        torch_info = None
        engines_info = None
        melo_info = None
        headers_info = None
        if args.profile == "full":
            torch_info = install_torch(TORCH_INDEX[args.torch_index], args.pipe_timeout, args.torch_index)
            headers_info = ensure_python_headers()
            log("INFO", f"CPython 头文件就绪：{headers_info['header_count']} 个头文件 @ {headers_info['include']}")
            engines_info = install_engines(args.pipe_timeout, TORCH_INDEX[args.torch_index],
                                           best_effort=not args.no_best_effort, headers=headers_info)
            melo_info = install_melo(args.pipe_timeout)
        else:
            log("INFO", "base 档：跳过 torch / 引擎依赖 / melo 安装")

        sanitize_info = sanitize_runtime_for_relocation()
        manifest.update({
            "python_version": PYTHON_VERSION,
            "python_exe": str(PY_EXE),
            "profile": args.profile,
            "torch_index": TORCH_INDEX[args.torch_index],
            "pypi_index": args.pypi_index,
            "pth_strategy": extract_info["pth_strategy"],
            "embed_zip": {"path": str(embed_zip), "url": PY_EMBED_URL},
            "get_pip_url": GET_PIP_URL,
            "install": {
                "backend": backend_info,
                "torch": torch_info,
                "python_headers": headers_info,
                "engines": engines_info,
                "melotts_package": melo_info,
                "sanitization": sanitize_info,
            },
        })
    else:
        if not PY_EXE.exists():
            log("ERROR", f"verify-only 但运行时不存在：{PY_EXE}")
            return 1
        log("INFO", "verify-only：跳过下载与安装步骤")
        # 只读刷新 ._pth 记录（不改动运行时）
        manifest["pth_strategy"] = pth_strategy_record(allow_remove=False)

    # 探针
    profile = manifest.get("profile", args.profile)
    probes = run_probes(profile)
    manifest["probes"] = probes

    # 扫描与包清单
    manifest["packages"] = collect_packages()
    manifest["size"] = scan_runtime()

    manifest["schema"] = 1
    manifest["change_id"] = "package-modelstation-desktop-installer"
    manifest["task"] = "task2-portable-runtime"
    manifest["generated_at"] = datetime.now().isoformat(timespec="seconds")
    manifest["first_build_started_at"] = manifest.get("first_build_started_at", started)
    manifest["build_seconds"] = round(time.time() - _T0, 1)
    if not args.verify_only:
        # verify-only 不改写「构建命令原文」，保留真实安装轮的记录
        manifest["build_command"] = subprocess.list2cmdline(
            [sys.executable, str(TOOLS_DIR / "build_runtime.py")] + sys.argv[1:])
    elif "build_command" not in manifest:
        manifest["build_command"] = subprocess.list2cmdline(
            [sys.executable, str(TOOLS_DIR / "build_runtime.py")] + sys.argv[1:])
    manifest["source_urls"] = {
        "python_embed": PY_EMBED_URL,
        "get_pip": GET_PIP_URL,
        "python_headers_nupkg": PY_HEADERS_URL,
        "fairseq_source": FAIRSEQ_SRC_URL,
        "pypi_index": manifest.get("pypi_index", args.pypi_index),
        "torch_index": manifest.get("torch_index"),
    }
    manifest.setdefault("notes", [])
    if profile == "base":
        manifest["notes"].append("base 档仅含后端依赖；三引擎依赖未安装，引擎探针 SKIPPED。")
    manifest["notes"].append(
        "python-multipart 为 pyproject.toml 声明但 requirements.txt 漏列，构建器已补入后端运行时依赖。"
    )
    if profile == "full":
        manifest["notes"].append(
            "bootstrap 取舍：python310._pth 已删除（否则 PYTHONPATH 与 -m 的 CWD 均失效）；"
            "脚本探测依赖一律设 PYTHONDONTWRITEBYTECODE=1 以保护只读的 engines/。"
        )

    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    log("INFO", f"manifest 已写出：{MANIFEST_PATH}")

    rc, pending = compute_exit_code(probes)
    log("INFO", f"探针汇总：" + ", ".join(f"{k}={v.get('status')}" for k, v in probes.items()))
    log("INFO", f"体积：{manifest['size']['size_mb']} MB / {manifest['size']['file_count']} 文件")
    if pending:
        for item in pending:
            log("ERROR", f"未就绪项 -> {item}")
        log("ERROR", f"构建结束：存在 {len(pending)} 个未就绪项（exit=1）")
        return 1
    log("INFO", "构建结束：全部应测探针就绪（exit=0）")
    return 0


if __name__ == "__main__":
    sys.exit(main())