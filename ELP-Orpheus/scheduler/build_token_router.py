"""编译 token_router.cpp 为 Python 扩展模块。

用法:
    python scheduler/build_token_router.py

产物:
    token_router.<arch>.pyd  (Windows)
    token_router.<arch>.so   (Linux/macOS)

依赖:
    pip install pybind11 setuptools

说明:
    使用 pybind11 提供的 Pybind11Extension + build_ext，自动处理
    C++17 标准、include 路径与 Python ABI。编译成功后扩展模块与
    本脚本同目录，可直接 `import token_router`。
"""

from __future__ import annotations

import os
import sys
import subprocess
from pathlib import Path

# setuptools / pybind11 仅在构建时需要，延迟导入以便给出清晰错误。
try:
    from setuptools import setup
    from pybind11.setup_helpers import Pybind11Extension, build_ext
except ImportError as e:  # pragma: no cover - 构建环境错误路径
    sys.stderr.write(
        "[build_token_router] 缺少构建依赖，请先安装：\n"
        "    pip install pybind11 setuptools\n"
        f"原始错误: {e}\n"
    )
    raise SystemExit(1)


HERE = Path(__file__).resolve().parent
SRC = HERE / "token_router.cpp"


def build_extension():
    """构造 Pybind11Extension。"""
    # cxx_std=17：pybind11 推荐 C++17；MSVC 需 /EHsc（异常）与 /bigobj。
    ext = Pybind11Extension(
        name="token_router",            # 模块名：导入时 import token_router
        sources=[str(SRC)],
        cxx_std=17,
        extra_compile_args=[],          # Pybind11Extension 已处理平台差异
    )
    return ext


def main():
    if not SRC.exists():
        sys.stderr.write(f"[build_token_router] 源文件不存在: {SRC}\n")
        raise SystemExit(1)

    # 通过 setup() 的脚本参数直接在本进程内构建，避免另起子进程。
    # --build-lib 指向源码目录，使产物 token_router.*.pyd 落在同目录，
    # 便于 token_router_binding.py 直接 import。
    build_lib = str(HERE)
    argv = [
        "build_ext",
        "--inplace",          # 产物输出到源码目录
        f"--build-lib={build_lib}",
    ]

    sys.argv = [str(__file__)] + argv

    setup(
        name="token_router",
        version="0.1.0",
        description="C++ Token Router for ELP-Orpheus FT engine (GIL-free).",
        ext_modules=[build_extension()],
        cmdclass={"build_ext": build_ext},
        zip_safe=False,
    )

    # 校验产物是否存在。
    produced = list(HERE.glob("token_router*.pyd")) + list(HERE.glob("token_router*.so"))
    if produced:
        sys.stdout.write(
            f"[build_token_router] 编译成功，产物：\n"
            + "\n".join(f"    {p}" for p in produced)
            + "\n"
        )
    else:  # pragma: no cover - 依赖具体平台编译器
        sys.stderr.write(
            "[build_token_router] 未发现编译产物，请检查编译器（MSVC/g++/clang++）是否可用。\n"
        )
        raise SystemExit(2)


if __name__ == "__main__":
    main()
