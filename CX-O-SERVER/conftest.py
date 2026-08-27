"""Pytest 配置：添加项目根目录到 Python 路径，并为测试套件固定离线基线。"""
import os
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# E3 修复：测试默认离线——防止任何 transformers/HF 用例在无外网环境下触发
# 模型元数据联网探测并无限期阻塞（audit 2026-08-27 实测卡死全套件）。
# setdefault 保留显式在线模式的覆盖能力（如显式需要 HF 的集成用例可自行
# monkeypatch.delenv 或设 HF_HUB_OFFLINE=0）。
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

