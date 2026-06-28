FROM python:3.11-slim

# ELP-Orpheus FT 引擎 Docker 镜像
# 轻量级：python:3.11-slim + pip 安装 PyTorch/Triton
# 使用国内镜像源加速（Debian apt + PyPI）
#
# 构建：docker build -t elp-orpheus .
# 运行：docker compose run --rm elp-orpheus

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
# PyPI 阿里云镜像源
ENV PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
ENV PIP_TRUSTED_HOST=mirrors.aliyun.com

# 替换 Debian apt 源为阿里云镜像（加速 apt-get install）
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null \
    || sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list 2>/dev/null \
    || true

# 安装编译工具（g++ for pybind11 token_router.cpp 编译）
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    git \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖（使用阿里云 PyPI 镜像）
# - torch：PyTorch with CUDA（pip 包含 nvidia-cuda-runtime 等运行时库）
# - triton：Linux 下 Triton JIT 编译器（解决 Windows 不可用问题）
# - pyzmq：ZeroMQ IPC
# - pybind11：C++ Token Router 编译
# - pytest / pyyaml：测试与配置读取
RUN pip install --no-cache-dir \
    torch \
    triton \
    pyzmq \
    pybind11 \
    setuptools \
    pytest \
    pyyaml \
    numpy

WORKDIR /workspace

# 默认命令：运行完整测试套件
CMD ["python", "-m", "pytest", "tests/", "-v", "--tb=short"]
