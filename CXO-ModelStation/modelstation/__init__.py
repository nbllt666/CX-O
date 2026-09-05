"""
CXO-ModelStation：SVC 模型训练工作站后端包

承接 So-VITS-SVC 训练全链路（数据集管理 / VoxCPM 批量语料 / 预处理 / 训练 / 试听推理 / 工作流编排），
自 CX-O-VoiceWorkStation 拆分而来（change-id: split-audio-workstation-cxfc-modelstation）。

部署要求：单 worker（uvicorn --workers 1），训练状态为进程内缓存。
"""
from __future__ import annotations

__version__ = "1.0.0"
