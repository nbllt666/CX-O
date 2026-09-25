#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""CXO-ModelStation 便携运行时 —— 搬迁自检（change-id: package-modelstation-desktop-installer / Task 2）。

验证「整体拷贝到任意路径后仍可用」：
  1) 把 build/runtime/ 整体拷贝到第二路径（默认 %TEMP%/cxo-ms-runtime-probe-<ts>）；
  2) 用副本解释器跑导入自检（证明依赖无绝对路径绑定）；
  3) 用副本解释器启动后端（-m modelstation.main，cwd=CXO-ModelStation，
     经 CXO_MODELSTATION_CONFIG 把 python_path/引擎目录/数据目录指到副本可用路径），
     轮询 http://127.0.0.1:<临时端口>/health，要求 healthy；
  4) 绝对路径扫描：pyvenv.cfg / *.pth / *.egg-link / direct_url.json / __editable__* /
     site-packages 文本文件中的构建机绝对路径（C:\\CX-O、C:\\CX-A、C:\\Users\\）；
  5) 收尾停掉临时进程并清理临时目录。

判据：搬迁可用 <=> 无「内容级绝对路径命中」（且无 pyvenv.cfg/egg-link/direct_url/editable）。
      仅「存在性命中」（如 setuptools 的 distutils-precedence.pth）不阻断搬迁，逐项报告。
退出码：0 = 搬迁自检通过；1 = 存在阻断项或后端健康检查失败。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

_T0 = time.time()

TOOLS_DIR = Path(__file__).resolve().parent
MS_ROOT = TOOLS_DIR.parent
BUILD_DIR = MS_ROOT / "build"
DEFAULT_RUNTIME = BUILD_DIR / "runtime"
REPORT_PATH = BUILD_DIR / "relocation_check_report.json"
SCAN_ONLY_REPORT_PATH = BUILD_DIR / "relocation_scan_only_report.json"

ENGINES_DIR = MS_ROOT / "engines"

# 构建机绝对路径特征（命中即视为内容级不搬迁证据）
ABSOLUTE_NEEDLES = [r"C:\CX-O", r"C:\CX-A", r"C:\Users\\"]
TEXT_SUFFIXES = {
    ".py", ".txt", ".json", ".cfg", ".ini", ".pth", ".toml", ".yaml", ".yml",
    ".md", ".rst", ".in", ".tmpl", ".cmake", ".sh", ".bat", ".ps1", ".html",
}
SCAN_MAX_BYTES = 8 * 1024 * 1024


def log(level: str, msg: str) -> None:
    elapsed = time.time() - _T0
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [{level}] [{elapsed:7.1f}s] {msg}", flush=True)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def child_env(extra: dict | None = None) -> dict:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"   # 保护只读的 modelstation/ 与 engines/（不写 __pycache__）
    env["PYTHONNOUSERSITE"] = "1"
    env.pop("PYTHONPATH", None)
    if extra:
        env.update({k: str(v) for k, v in extra.items()})
    return env


# --------------------------------------------------------------------------- #
# 1) 拷贝 + 导入自检                                                            #
# --------------------------------------------------------------------------- #
def copy_runtime(runtime: Path, dest: Path) -> None:
    log("INFO", f"拷贝运行时 {runtime} -> {dest}（这是搬迁能力的最强证据：绝对路径已改变）")
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    shutil.copytree(runtime, dest)


def import_selfcheck(copy_py: Path) -> dict:
    code = (
        "import sys, json\n"
        "info = {'executable': sys.executable, 'prefix': sys.prefix, 'version': sys.version.split()[0]}\n"
        "import fastapi, uvicorn, pydantic, httpx, multipart\n"
        "info['imports'] = 'ok'\n"
        "print('SELFCHECK=' + json.dumps(info))\n"
    )
    rc, out, err = _run([str(copy_py), "-c", code], env=child_env(), timeout=300)
    payload = {}
    for line in (out or "").splitlines():
        if line.startswith("SELFCHECK="):
            payload = json.loads(line.split("=", 1)[1])
    return {"rc": rc, "info": payload, "stderr_tail": _tail(err or out, 500),
            "status": "PASS" if rc == 0 and payload.get("imports") == "ok" else "FAIL"}


def _run(cmd, cwd=None, env=None, timeout=None):
    try:
        p = subprocess.run(cmd, cwd=str(cwd) if cwd else None, env=env,
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout)
        return p.returncode, p.stdout or "", p.stderr or ""
    except subprocess.TimeoutExpired:
        return 124, "", f"TIMEOUT {timeout}s"


def _tail(s: str, n: int) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else "...(截断)..." + s[-n:]


# --------------------------------------------------------------------------- #
# 2) 用副本解释器启动后端并探活                                                 #
# --------------------------------------------------------------------------- #
def backend_healthcheck(copy_py: Path, port: int, timeout_s: int, tmp_root: Path) -> dict:
    data_root = tmp_root / "probe-data"
    cfg = {
        "server": {"host": "127.0.0.1", "port": port, "log_level": "info"},
        "sovits_svc": {
            "python_path": str(copy_py),
            "so_vits_svc_dir": str(ENGINES_DIR / "so-vits-svc-4.1-Stable"),
            "training_data_dir": str(data_root / "training" / "sovits_svc"),
            "models_dir": str(data_root / "models" / "sovits_svc"),
            "audition_dir": str(data_root / "audition"),
            "input_dir": str(data_root / "input"),
        },
        "melotts": {
            "python_path": str(copy_py),
            "engine_dir": str(ENGINES_DIR / "MeloTTS"),
            "training_data_dir": str(data_root / "training" / "melotts"),
            "models_dir": str(data_root / "models" / "melotts"),
        },
        "voxcpm": {"working_dir": str(ENGINES_DIR / "VoxCPM-main")},
    }
    env = child_env({"CXO_MODELSTATION_CONFIG": json.dumps(cfg, ensure_ascii=False)})
    out_file = tmp_root / "backend_stdout.log"
    err_file = tmp_root / "backend_stderr.log"
    cmd = [str(copy_py), "-m", "modelstation.main"]
    log("INFO", f"启动后端（副本解释器）：{subprocess.list2cmdline(cmd)} cwd={MS_ROOT} port={port}")
    with open(out_file, "wb") as fo, open(err_file, "wb") as fe:
        proc = subprocess.Popen(
            cmd, cwd=str(MS_ROOT), env=env, stdout=fo, stderr=fe,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
        )

    healthy = False
    health_payload = None
    deadline = time.time() + timeout_s
    url = f"http://127.0.0.1:{port}/health"
    while time.time() < deadline:
        if proc.poll() is not None:
            break
        try:
            with urllib.request.urlopen(url, timeout=3) as resp:
                health_payload = json.loads(resp.read().decode("utf-8", "replace"))
                healthy = health_payload.get("status") == "healthy"
                if healthy:
                    break
        except Exception:  # noqa: BLE001
            time.sleep(1.0)

    result = {
        "status": "PASS" if healthy else "FAIL",
        "url": url,
        "http_payload": health_payload,
        "process_returncode_before_stop": proc.poll(),
        "config_injected": cfg,
        "stdout_tail": _read_tail(out_file, 1500),
        "stderr_tail": _read_tail(err_file, 1500),
    }
    _stop_process_tree(proc)
    return result


def _read_tail(path: Path, n: int) -> str:
    try:
        return _tail(path.read_text(encoding="utf-8", errors="replace"), n)
    except OSError:
        return ""


def _stop_process_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        log("INFO", f"临时后端进程已退出 rc={proc.returncode}")
        return
    log("INFO", "停止临时后端进程树")
    if os.name == "nt":
        _run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], timeout=60)
    else:
        proc.terminate()
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()
    log("INFO", f"临时后端进程已停止 rc={proc.returncode}")


# --------------------------------------------------------------------------- #
# 3) 绝对路径扫描                                                               #
# --------------------------------------------------------------------------- #
def scan_absolute_paths(runtime_dir: Path) -> dict:
    flagged_files = []
    content_hits = []
    suffix_counts: dict[str, int] = {}
    scanned_text_files = 0

    for root, _dirs, files in os.walk(runtime_dir):
        for name in files:
            fp = Path(root) / name
            rel = str(fp.relative_to(runtime_dir))
            low = name.lower()
            if low == "pyvenv.cfg":
                flagged_files.append({"kind": "pyvenv.cfg", "path": rel, "blocking": True,
                                      "reason": "venv 配置会把解释器绑定到构建机绝对路径"})
            if low == "direct_url.json":
                # 仅当内容含构建机绝对路径（file:// 本地来源）才阻断；纯 https 来源不影响搬迁
                try:
                    raw = fp.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    raw = ""
                has_abs = any(n in raw for n in ABSOLUTE_NEEDLES) or "file://" in raw
                flagged_files.append({"kind": "direct_url.json", "path": rel, "blocking": has_abs,
                                      "reason": "pip 直接来源溯源元数据", "content": raw.strip()[:300]})
            if low.endswith(".egg-link"):
                flagged_files.append({"kind": "egg-link", "path": rel, "blocking": True,
                                      "reason": "egg-link 指向构建机源码目录绝对路径"})
            if low.startswith("__editable__"):
                flagged_files.append({"kind": "editable-artifact", "path": rel, "blocking": True,
                                      "reason": "editable 安装产物绑定源码绝对路径"})
            if low.endswith(".pth"):
                suffix_counts[".pth"] = suffix_counts.get(".pth", 0) + 1
                try:
                    content = fp.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    content = ""
                has_abs = any(needle in content for needle in ABSOLUTE_NEEDLES)
                flagged_files.append({
                    "kind": ".pth",
                    "path": rel,
                    "content": content.strip()[:400],
                    "contains_absolute_path": has_abs,
                    "blocking": has_abs,
                    "reason": "site 路径文件；内容无绝对路径即不阻断（可经 site-packages 相对解析）",
                })

            if fp.suffix.lower() in TEXT_SUFFIXES:
                try:
                    if fp.stat().st_size > SCAN_MAX_BYTES:
                        continue
                    text = fp.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                scanned_text_files += 1
                for needle in ABSOLUTE_NEEDLES:
                    if needle in text:
                        idx = text.find(needle)
                        content_hits.append({
                            "path": rel,
                            "needle": needle,
                            "count": text.count(needle),
                            "snippet": text[max(0, idx - 60): idx + 120].replace("\n", "\\n"),
                        })
                        break

    blocking = list(content_hits)
    blocking_meta = [f for f in flagged_files if f.get("blocking")]
    non_blocking = [f for f in flagged_files if not f.get("blocking")]
    relocatable = (not blocking) and (not blocking_meta)

    return {
        "verdict": "RELOCATABLE" if relocatable else "BLOCKED",
        "blocking_content_hits": blocking,
        "blocking_metadata_findings": blocking_meta,
        "non_blocking_findings": non_blocking,
        "scanned_text_files": scanned_text_files,
        "pth_count": suffix_counts.get(".pth", 0),
        "judgement": (
            "阻断判据（两类）：(a) site-packages 文本文件内容含构建机绝对路径（C:\\CX-O / C:\\CX-A / C:\\Users\\）；"
            "(b) 元数据绑定绝对路径——pyvenv.cfg / .egg-link / __editable__* 存在，"
            "或 direct_url.json 内容含本地绝对路径（file://）。"
            "非阻断项（如实报告）：.pth 内容无绝对路径、direct_url.json 为纯 https 来源。"
        ),
    }


# --------------------------------------------------------------------------- #
# 主流程                                                                        #
# --------------------------------------------------------------------------- #
def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="便携运行时搬迁自检")
    ap.add_argument("--runtime", default=str(DEFAULT_RUNTIME), help="待检运行时目录（默认 build/runtime）")
    ap.add_argument("--port", type=int, default=0, help="后端临时端口（默认自动分配，避开 8300）")
    ap.add_argument("--health-timeout", type=int, default=120, help="后端 /health 轮询超时秒（默认 120）")
    ap.add_argument("--scan-only", action="store_true", help="只做绝对路径扫描，不拷贝/不启后端")
    ap.add_argument("--keep", action="store_true", help="保留临时副本目录（默认清理）")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    runtime = Path(args.runtime).resolve()
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    tmp_root = Path(os.environ.get("TEMP", str(BUILD_DIR))) / f"cxo-ms-runtime-probe-{ts}"

    log("INFO", "=" * 78)
    log("INFO", f"搬迁自检 runtime={runtime} 临时路径={tmp_root}")

    report: dict = {
        "change_id": "package-modelstation-desktop-installer",
        "task": "task2-portable-runtime-relocation-check",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "runtime_dir": str(runtime),
        "probe_dir": str(tmp_root),
    }

    if not (runtime / "python" / "python.exe").is_file():
        log("ERROR", f"未找到运行时解释器：{runtime / 'python' / 'python.exe'}")
        return 1

    if args.scan_only:
        report["scan"] = scan_absolute_paths(runtime)
        report["result"] = "PASS" if report["scan"]["verdict"] == "RELOCATABLE" else "FAIL"
        # 独立文件，避免覆盖完整自检报告（relocation_check_report.json）
        _write_report(report, SCAN_ONLY_REPORT_PATH)
        log("INFO", f"扫描结论：{report['scan']['verdict']}")
        return 0 if report["scan"]["verdict"] == "RELOCATABLE" else 1

    try:
        copy_runtime(runtime, tmp_root)
        copy_py = tmp_root / "python" / "python.exe"

        report["import_selfcheck"] = import_selfcheck(copy_py)
        log("INFO", f"副本解释器导入自检：{report['import_selfcheck']['status']} "
                    f"prefix={report['import_selfcheck']['info'].get('prefix')}")

        port = args.port or free_port()
        if port == 8300:
            port = free_port()
        report["backend_healthcheck"] = backend_healthcheck(copy_py, port, args.health_timeout, tmp_root)
        log("INFO", f"后端 /health：{report['backend_healthcheck']['status']} "
                    f"{report['backend_healthcheck']['http_payload']}")

        report["scan"] = scan_absolute_paths(runtime)
        log("INFO", f"绝对路径扫描结论：{report['scan']['verdict']} "
                    f"(内容级阻断 {len(report['scan']['blocking_content_hits'])}，"
                    f"元数据阻断 {len(report['scan']['blocking_metadata_findings'])}，"
                    f"非阻断 {len(report['scan']['non_blocking_findings'])}，"
                    f".pth={report['scan']['pth_count']})")
    finally:
        if args.keep:
            log("INFO", f"--keep：保留临时副本目录 {tmp_root}")
        else:
            log("INFO", f"清理临时副本目录 {tmp_root}")
            shutil.rmtree(tmp_root, ignore_errors=True)

    ok = (
        report.get("import_selfcheck", {}).get("status") == "PASS"
        and report.get("backend_healthcheck", {}).get("status") == "PASS"
        and report.get("scan", {}).get("verdict") == "RELOCATABLE"
    )
    report["result"] = "PASS" if ok else "FAIL"
    _write_report(report)
    log("INFO", f"搬迁自检结果：{report['result']}")
    return 0 if ok else 1


def _write_report(report: dict, path: Path | None = None) -> None:
    target = path or REPORT_PATH
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        log("INFO", f"自检报告已写出：{target}")
    except OSError as exc:
        log("WARN", f"写出自检报告失败：{exc}")


if __name__ == "__main__":
    sys.exit(main())