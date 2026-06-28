"""编译 probe.cpp 为 Python 扩展模块 probe_cpp。

用法:
    python profiler/build_probe.py              # 无 CUDA（开发环境）
    python profiler/build_probe.py --with-cuda  # 带 CUDA（需 CUDA toolkit + nvcc）

产物:
    probe_cpp.<arch>.pyd  (Windows)
    probe_cpp.<arch>.so   (Linux/macOS)

依赖:
    pip install pybind11 setuptools

说明:
    使用 pybind11 提供的 Pybind11Extension + build_ext，自动处理
    C++17 标准、include 路径与 Python ABI。--with-cuda 时注入 -DHAVE_CUDA=1
    并链接 cudart；无 CUDA 时 probe.cpp 的 cuda_event_* 回退到 steady_clock。

    参考 scheduler/build_token_router.py 的编译模式。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

try:
    from setuptools import setup
    from pybind11.setup_helpers import Pybind11Extension, build_ext
except ImportError as e:  # pragma: no cover - 构建环境错误路径
    sys.stderr.write(
        "[build_probe] 缺少构建依赖，请先安装：\n"
        "    pip install pybind11 setuptools\n"
        f"原始错误: {e}\n"
    )
    raise SystemExit(1)


HERE = Path(__file__).resolve().parent
SRC = HERE / "probe.cpp"


def build_extension(with_cuda: bool = False):
    """构造 Pybind11Extension。

    Args:
        with_cuda: 是否启用 CUDA（注入 -DHAVE_CUDA 并链接 cudart）。
    """
    extra_compile_args = []
    libraries = []
    define_macros = []

    if with_cuda:
        # HAVE_CUDA 由 probe.cpp 的 #ifdef HAVE_CUDA 检测，启用 CUDA event 计时路径。
        define_macros.append(("HAVE_CUDA", "1"))
        libraries.append("cudart")
        # CUDA include 路径需由环境变量 CUDA_PATH 或默认路径提供。
        cuda_path = os.environ.get("CUDA_PATH") or os.environ.get("CUDA_HOME")
        if cuda_path:
            extra_compile_args.append(f"-I{os.path.join(cuda_path, 'include')}")

    ext = Pybind11Extension(
        name="probe_cpp",            # 模块名：导入时 import probe_cpp
        sources=[str(SRC)],
        include_dirs=[str(HERE)],     # 让 probe.cpp 找到 probe.h
        cxx_std=17,
        extra_compile_args=extra_compile_args,
        libraries=libraries,
        define_macros=define_macros,
    )
    return ext


def main():
    if not SRC.exists():
        sys.stderr.write(f"[build_probe] 源文件不存在: {SRC}\n")
        raise SystemExit(1)

    with_cuda = "--with-cuda" in sys.argv
    if with_cuda:
        sys.argv.remove("--with-cuda")

    build_lib = str(HERE)
    argv = [
        "build_ext",
        "--inplace",
        f"--build-lib={build_lib}",
    ]
    sys.argv = [str(__file__)] + argv

    setup(
        name="probe_cpp",
        version="0.1.0",
        description="ELP-Orpheus 超低开销 C++/Python 混合 Profiler 计时探针（GIL-free）。",
        ext_modules=[build_extension(with_cuda=with_cuda)],
        cmdclass={"build_ext": build_ext},
        zip_safe=False,
    )

    produced = list(HERE.glob("probe_cpp*.pyd")) + list(HERE.glob("probe_cpp*.so"))
    if produced:
        sys.stdout.write(
            f"[build_probe] 编译成功，产物：\n"
            + "\n".join(f"    {p}" for p in produced)
            + "\n"
        )
    else:  # pragma: no cover - 依赖具体平台编译器
        sys.stderr.write(
            "[build_probe] 未发现编译产物，请检查编译器（MSVC/g++/clang++）是否可用。\n"
        )
        raise SystemExit(2)


if __name__ == "__main__":
    main()
