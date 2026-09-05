"""
一次性迁移工具：CX-O-VoiceWorkStation 训练数据/模型 → CXO-ModelStation/data/

迁移对（change-id: split-audio-workstation-cxfc-modelstation，spec「训练数据与模型目录迁移」）：
- CX-O-VoiceWorkStation/data/training/sovits_svc/  → CXO-ModelStation/data/training/sovits_svc/
- CX-O-VoiceWorkStation/data/models/sovits_svc/    → CXO-ModelStation/data/models/sovits_svc/

幂等语义（零丢失优先于目录清洁）：
- 源目录不存在 → 跳过并报告，不计错误；
- 目标同名文件已存在 → 目标与源均保留不动，逐项计入 conflicts 并列入明细；
- 仅当某迁移对「全部文件成功移动（零 conflicts/零 errors）」时才清除源端对应子路径；
  存在 conflicts 时源目录完整保留，并在报告中列出全部明细；
- 重复运行安全（第二次运行所有文件命中 conflicts，源端不动）。

用法：
    python tools/migrate_from_vws.py --dry-run   # 仅打印计划，不做任何改动
    python tools/migrate_from_vws.py             # 实际执行迁移

终端输出格式：[timestamp] [INFO/ERROR] [elapsed]；结束打印统计
（moved/skipped/conflicts/errors）。路径全部基于 __file__ 锚定，对 CWD 免疫。
"""
from __future__ import annotations

import argparse
import shutil
import time
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# 路径锚定（rules-0 §三：基于 __file__，禁 CWD 相对路径）
# ---------------------------------------------------------------------------
_TOOLS_DIR = Path(__file__).resolve().parent      # .../CXO-ModelStation/tools
_MS_ROOT = _TOOLS_DIR.parent                      # .../CXO-ModelStation
_PROJECT_ROOT = _MS_ROOT.parent                   # .../CX-O
_VWS_DATA = _PROJECT_ROOT / "CX-O-VoiceWorkStation" / "data"

# (标签, 源目录, 目标目录)
_MIGRATIONS = [
    (
        "训练数据 training/sovits_svc",
        _VWS_DATA / "training" / "sovits_svc",
        _MS_ROOT / "data" / "training" / "sovits_svc",
    ),
    (
        "模型 models/sovits_svc",
        _VWS_DATA / "models" / "sovits_svc",
        _MS_ROOT / "data" / "models" / "sovits_svc",
    ),
]

_START = time.monotonic()
_STATS = {"moved": 0, "skipped": 0, "conflicts": 0, "errors": 0}


def _log(level: str, msg: str) -> None:
    """[timestamp] [INFO/ERROR] [elapsed] 格式终端输出"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    elapsed = time.monotonic() - _START
    print(f"[{ts}] [{level}] [{elapsed:.1f}s] {msg}")


def _iter_source_files(source: Path) -> list[Path]:
    """列出源目录下全部文件（含子目录），按相对路径稳定排序"""
    if not source.is_dir():
        return []
    return sorted(p for p in source.rglob("*") if p.is_file())


def _migrate_pair(label: str, source: Path, target: Path, dry_run: bool) -> None:
    """迁移单个源/目标对；返回后 _STATS 已累计，明细经 _log 打印"""
    _log("INFO", f"== 迁移对: {label} ==")
    _log("INFO", f"   源: {source}")
    _log("INFO", f"   目标: {target}")

    if not source.is_dir():
        _log("INFO", f"   源目录不存在，跳过（幂等）: {source}")
        _STATS["skipped"] += 1
        return

    files = _iter_source_files(source)
    if not files:
        _log("INFO", f"   源目录为空（无可迁移文件）: {source}")
        # 空目录视为零冲突，可安全清除源端子路径
        if not dry_run:
            _remove_source_subtree(label, source)
        return

    _log("INFO", f"   待迁移文件数: {len(files)}")

    pair_conflicts: list[str] = []
    pair_errors: list[str] = []
    pair_moved = 0

    if dry_run:
        for src in files:
            rel = src.relative_to(source)
            dst = target / rel
            if dst.exists():
                pair_conflicts.append(str(rel))
            else:
                _log("INFO", f"   [计划] {rel} -> {dst}")
                pair_moved += 1
    else:
        target.mkdir(parents=True, exist_ok=True)
        for src in files:
            rel = src.relative_to(source)
            dst = target / rel
            try:
                if dst.exists():
                    # 同名冲突：目标与源均保留不动（零丢失优先）
                    pair_conflicts.append(str(rel))
                    _log("INFO", f"   [冲突·双方保留] {rel}")
                    continue
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst))
                pair_moved += 1
            except Exception as e:
                pair_errors.append(f"{rel}: {e}")
                _log("ERROR", f"   移动失败 {rel}: {e}")

    _STATS["moved"] += pair_moved
    _STATS["conflicts"] += len(pair_conflicts)
    _STATS["errors"] += len(pair_errors)

    _log("INFO", f"   本对统计: moved={pair_moved} conflicts={len(pair_conflicts)} errors={len(pair_errors)}")

    if pair_conflicts:
        _log("INFO", "   冲突明细（目标与源均保留，未移动）:")
        for rel in pair_conflicts:
            _log("INFO", f"     - {rel}")

    if dry_run:
        _log("INFO", "   --dry-run：未做任何改动")
        return

    # 零丢失才清除源端：全部文件成功移动（零冲突/零错误）时移除源端对应子路径；
    # 存在冲突/错误时源目录保留（明细已列出）
    if not pair_conflicts and not pair_errors:
        _remove_source_subtree(label, source)
    else:
        _log("INFO", f"   存在冲突/错误，源目录保留: {source}")


def _remove_source_subtree(label: str, source: Path) -> None:
    """清除源端对应子路径（仅零冲突/零错误时调用）；父级空目录 best-effort 清理"""
    try:
        if source.is_dir():
            shutil.rmtree(source)
            _log("INFO", f"   源端子路径已清除: {source}")
        # 尝试清理空的父级目录（data/training、data/models），非空则保留
        for parent in (source.parent, source.parent.parent):
            if parent == _VWS_DATA:
                break
            try:
                parent.rmdir()
                _log("INFO", f"   空父级目录已移除: {parent}")
            except OSError:
                break  # 非空即停止向上清理
    except Exception as e:
        _STATS["errors"] += 1
        _log("ERROR", f"   清除源端子路径失败（数据不受影响）: {e}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="一次性迁移 VWS 训练数据/模型到 CXO-ModelStation/data（幂等，零丢失优先）"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅打印迁移计划，不做任何改动",
    )
    args = parser.parse_args()

    mode = "DRY-RUN（计划）" if args.dry_run else "EXECUTE（实际执行）"
    _log("INFO", f"VWS -> ModelStation 数据迁移启动: {mode}")
    _log("INFO", f"项目根: {_PROJECT_ROOT}")

    for label, source, target in _MIGRATIONS:
        _migrate_pair(label, source, target, dry_run=args.dry_run)

    _log("INFO", "=" * 52)
    _log(
        "INFO",
        f"迁移结束统计: moved={_STATS['moved']} skipped={_STATS['skipped']} "
        f"conflicts={_STATS['conflicts']} errors={_STATS['errors']}",
    )
    if args.dry_run:
        _log("INFO", "以上为 dry-run 计划；确认无误后去掉 --dry-run 实际执行")
    if _STATS["errors"]:
        _log("ERROR", "存在迁移错误，请检查上方明细后重跑（幂等，不会重复移动已迁移文件）")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
