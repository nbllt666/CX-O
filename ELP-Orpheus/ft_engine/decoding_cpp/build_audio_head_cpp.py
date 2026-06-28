"""编译 audio_head_cpp C++ 扩展模块（CPU 回退路径）。

用法:
    python ft_engine/decoding_cpp/build_audio_head_cpp.py

产物:
    audio_head_cpp.<arch>.pyd  (Windows)
    audio_head_cpp.<arch>.so   (Linux/macOS)

依赖:
    pip install pybind11 setuptools

说明:
    本脚本编译 CPU 回退路径（无 CUDA/cublasLt）：
        - 源文件仅 binding.cpp（其 #include audio_head_kernel.cu 内联实现，HAVE_CUDA 未定义）
        - 用 pybind11 + 标准 C++ 编译器（g++/MSVC/clang++）
    CUDA 路径需 nvcc 单独编译 audio_head_kernel.cu，本脚本不处理（见 INTEGRATION_NOTES.md）。

    编译成功后扩展模块与本脚本同目录，可直接 `import audio_head_cpp`。
    为使 `import audio_head_cpp` 可被 audio_head/audio_head_cpp.py 找到，需将本目录
    加入 sys.path（与 ft_engine/ft_binding.py 同模式）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# setuptools / pybind11 仅在构建时需要，延迟导入以便给出清晰错误。
try:
    from setuptools import setup
    from pybind11.setup_helpers import Pybind11Extension, build_ext
except ImportError as e:  # pragma: no cover - 构建环境错误路径
    sys.stderr.write(
        "[build_audio_head_cpp] 缺少构建依赖，请先安装：\n"
        "    pip install pybind11 setuptools\n"
        f"原始错误: {e}\n"
    )
    raise SystemExit(1)


HERE = Path(__file__).resolve().parent
SRC = HERE / "binding.cpp"


def build_extension():
    """构造 Pybind11Extension。

    仅编译 binding.cpp：CPU 回退路径下，binding.cpp 通过 #include "audio_head_kernel.cu"
    内联全部实现（g++ 无法直接编译 .cu 扩展名）。CUDA 路径见 INTEGRATION_NOTES.md。
    """
    ext = Pybind11Extension(
        name="audio_head_cpp",     # 模块名：导入时 import audio_head_cpp
        sources=[str(SRC)],
        cxx_std=17,
        # 不定义 HAVE_CUDA / HAVE_CUBLASLT：走纯 CPU 回退路径。
        extra_compile_args=[],     # Pybind11Extension 已处理平台差异
        include_dirs=[str(HERE)],   # 保证找到 audio_head_kernel.h
    )
    return ext


def main():
    if not SRC.exists():
        sys.stderr.write(f"[build_audio_head_cpp] 源文件不存在: {SRC}\n")
        raise SystemExit(1)

    # --inplace：产物输出到源码目录，便于 import。
    build_lib = str(HERE)
    argv = [
        "build_ext",
        "--inplace",
        f"--build-lib={build_lib}",
    ]

    sys.argv = [str(__file__)] + argv

    setup(
        name="audio_head_cpp",
        version="0.1.0",
        description="Audio Head C++/CUDA operator for ELP-Orpheus (CPU fallback).",
        ext_modules=[build_extension()],
        cmdclass={"build_ext": build_ext},
        zip_safe=False,
    )

    # 校验产物是否存在。
    produced = (
        list(HERE.glob("audio_head_cpp*.pyd"))
        + list(HERE.glob("audio_head_cpp*.so"))
    )
    if produced:
        sys.stdout.write(
            "[build_audio_head_cpp] 编译成功，产物：\n"
            + "\n".join(f"    {p}" for p in produced)
            + "\n请将本目录加入 sys.path 后 `import audio_head_cpp`。\n"
        )
    else:  # pragma: no cover - 依赖具体平台编译器
        sys.stderr.write(
            "[build_audio_head_cpp] 未发现编译产物，请检查编译器"
            "（MSVC/g++/clang++）是否可用。\n"
        )
        raise SystemExit(2)


if __name__ == "__main__":
    main()
