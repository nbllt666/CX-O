#!/usr/bin/env python3
"""
CXHMS 测试运行器
运行所有前端和后端测试
"""
import subprocess
import sys
import os
import shutil
from pathlib import Path


def get_data_files():
    """获取需要备份的数据文件列表"""
    data_dir = Path(__file__).parent / "data"
    files_to_backup = []
    
    # 数据库文件
    db_files = ["cxhms.db", "memories.db", "sessions.db", "milvus_lite.db"]
    for db in db_files:
        db_path = data_dir / db
        if db_path.exists():
            files_to_backup.append(db_path)
    
    # agents.json
    agents_json = data_dir / "agents.json"
    if agents_json.exists():
        files_to_backup.append(agents_json)
    
    # acp 目录
    acp_dir = data_dir / "acp"
    if acp_dir.exists():
        files_to_backup.append(acp_dir)
    
    return files_to_backup


def backup_state():
    """备份测试前的状态"""
    backup_dir = Path(__file__).parent / ".test_backup"
    if backup_dir.exists():
        shutil.rmtree(backup_dir)
    backup_dir.mkdir(exist_ok=True)
    
    files_to_backup = get_data_files()
    for file_path in files_to_backup:
        if file_path.is_dir():
            dest = backup_dir / file_path.name
            shutil.copytree(file_path, dest)
            print(f"  📦 备份目录: {file_path.name}/")
        else:
            shutil.copy2(file_path, backup_dir / file_path.name)
            print(f"  📦 备份文件: {file_path.name}")
    
    return backup_dir


def restore_state(backup_dir):
    """恢复测试前的状态"""
    import time
    data_dir = Path(__file__).parent / "data"
    
    # 删除测试产生的文件
    print("\n🧹 清理测试产生的数据...")
    
    # 删除数据库文件（带重试）
    db_files = ["cxhms.db", "memories.db", "sessions.db", "milvus_lite.db"]
    for db in db_files:
        db_path = data_dir / db
        if db_path.exists():
            for attempt in range(3):
                try:
                    db_path.unlink()
                    print(f"  🗑️ 删除: {db}")
                    break
                except PermissionError:
                    if attempt < 2:
                        time.sleep(0.5)
                    else:
                        print(f"  ⚠️ 无法删除 {db}（文件被占用）")
    
    # 删除临时测试文件（带重试）
    for pattern in ["test_*.db", "*.db.bak", "*.db-journal"]:
        for f in data_dir.glob(pattern):
            for attempt in range(3):
                try:
                    f.unlink()
                    print(f"  🗑️ 删除临时文件: {f.name}")
                    break
                except PermissionError:
                    if attempt < 2:
                        time.sleep(0.5)
                    else:
                        print(f"  ⚠️ 无法删除 {f.name}（文件被占用）")
    
    # 恢复备份的文件
    print("\n📂 恢复原始数据...")
    for backup_file in backup_dir.iterdir():
        if backup_file.is_dir():
            dest = data_dir / backup_file.name
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(backup_file, dest)
            print(f"  ✅ 恢复目录: {backup_file.name}/")
        else:
            shutil.copy2(backup_file, data_dir / backup_file.name)
            print(f"  ✅ 恢复文件: {backup_file.name}")
    
    # 清理备份目录
    shutil.rmtree(backup_dir)
    print("  🧹 清理备份目录")


def run_frontend_tests():
    """运行前端测试"""
    print("=" * 60)
    print("运行前端测试...")
    print("=" * 60)

    frontend_dir = Path(__file__).parent / "frontend"

    # 检测 npm 命令 (Windows 使用 npm.cmd)
    npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"

    # 检查前端依赖是否已安装
    node_modules = frontend_dir / "node_modules"
    if not node_modules.exists():
        print("\n📦 安装前端依赖...")
        result = subprocess.run(
            [npm_cmd, "install"],
            cwd=frontend_dir,
            capture_output=True,
            text=True,
            shell=True
        )
        if result.returncode != 0:
            print(f"❌ 安装依赖失败: {result.stderr}")
            return False
        print("✅ 依赖安装完成")
    else:
        print("\n✅ 前端依赖已安装")

    # 运行测试
    print("\n🧪 运行前端测试...")
    result = subprocess.run(
        [npm_cmd, "test"],
        cwd=frontend_dir,
        capture_output=False,
        shell=True
    )

    if result.returncode == 0:
        print("✅ 前端测试通过")
        return True
    else:
        print("❌ 前端测试失败")
        return False


def run_backend_tests():
    """运行后端测试"""
    print("\n" + "=" * 60)
    print("运行后端测试...")
    print("=" * 60)

    # 运行 pytest
    print("\n🧪 运行后端测试...")
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "backend/tests", "-v"],
        capture_output=False
    )

    if result.returncode == 0:
        print("✅ 后端测试通过")
        return True
    else:
        print("❌ 后端测试失败")
        return False


def run_backend_tests_with_coverage():
    """运行后端测试并生成覆盖率报告"""
    print("\n" + "=" * 60)
    print("运行后端测试 (带覆盖率)...")
    print("=" * 60)

    result = subprocess.run(
        [
            sys.executable, "-m", "pytest",
            "backend/tests",
            "-v",
            "--cov=backend",
            "--cov-report=term-missing",
            "--cov-report=html:htmlcov"
        ],
        capture_output=False
    )

    if result.returncode == 0:
        print("✅ 后端测试通过")
        print("📊 覆盖率报告已生成: htmlcov/index.html")
        return True
    else:
        print("❌ 后端测试失败")
        return False


def run_specific_test(test_path):
    """运行特定测试"""
    print(f"\n🧪 运行测试: {test_path}")
    result = subprocess.run(
        [sys.executable, "-m", "pytest", test_path, "-v"],
        capture_output=False
    )
    return result.returncode == 0


def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description="CXHMS 测试运行器")
    parser.add_argument(
        "--frontend-only",
        action="store_true",
        help="只运行前端测试"
    )
    parser.add_argument(
        "--backend-only",
        action="store_true",
        help="只运行后端测试"
    )
    parser.add_argument(
        "--coverage",
        action="store_true",
        help="生成覆盖率报告"
    )
    parser.add_argument(
        "--test",
        type=str,
        help="运行特定测试文件或目录"
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="不备份/恢复数据（用于调试）"
    )

    args = parser.parse_args()

    print("\n" + "🚀" * 30)
    print("   CXHMS 测试套件")
    print("🚀" * 30 + "\n")

    # 备份状态
    backup_dir = None
    if not args.no_backup:
        print("📦 备份当前状态...")
        backup_dir = backup_state()
        print()

    success = True

    try:
        if args.test:
            success = run_specific_test(args.test)
        elif args.frontend_only:
            success = run_frontend_tests()
        elif args.backend_only:
            if args.coverage:
                success = run_backend_tests_with_coverage()
            else:
                success = run_backend_tests()
        else:
            # 运行所有测试
            frontend_success = run_frontend_tests()
            if args.coverage:
                backend_success = run_backend_tests_with_coverage()
            else:
                backend_success = run_backend_tests()
            success = frontend_success and backend_success

        print("\n" + "=" * 60)
        if success:
            print("✅ 所有测试通过!")
        else:
            print("❌ 部分测试失败")
        print("=" * 60)
    finally:
        # 恢复状态
        if backup_dir:
            print("\n" + "=" * 60)
            print("🔄 恢复原始状态...")
            print("=" * 60)
            restore_state(backup_dir)
            print("\n✅ 状态已恢复")

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
