"""AdapterStore：LoRA 训练产物（适配器）管理。

每个适配器为 lora_dir 下的一个子目录，元信息可选存于该目录 metadata.json。
骨架阶段：训练引擎未接入，apply 统一返回占位结果。
"""
from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from typing import List, Optional

from tuner.models import AdapterInfo, ApplyAdapterResponse


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AdapterNotFoundError(ValueError):
    """适配器 id 不存在。对应 404。"""


class AdapterStore:
    def __init__(self, lora_dir: str) -> None:
        self.lora_dir = os.path.abspath(lora_dir)
        os.makedirs(self.lora_dir, exist_ok=True)

    def _safe_path(self, adapter_id: str) -> str:
        path = os.path.abspath(os.path.join(self.lora_dir, adapter_id))
        root = os.path.abspath(self.lora_dir)
        try:
            inside = os.path.commonpath([root, path]) == root
        except ValueError:
            # Windows 跨盘符（如 root=C:\x 与 path=D:\y）时 commonpath 抛 ValueError，
            # 一律视为越界路径，按适配器不存在处理（D6）。
            inside = False
        if not inside or not os.path.isdir(path):
            raise AdapterNotFoundError(f"adapter '{adapter_id}' 不存在")
        return path

    def _build(self, adapter_id: str) -> AdapterInfo:
        path = self._safe_path(adapter_id)
        meta: dict = {}
        meta_path = os.path.join(path, "metadata.json")
        if os.path.isfile(meta_path):
            try:
                with open(meta_path, "r", encoding="utf-8") as fh:
                    meta = json.load(fh) or {}
            except Exception:
                meta = {}
        size_bytes = 0
        for root, _dirs, files in os.walk(path):
            for f in files:
                try:
                    size_bytes += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
        return AdapterInfo(
            id=adapter_id,
            name=meta.get("name") or adapter_id,
            created_at=meta.get("created_at") or _now_iso(),
            base_model=meta.get("base_model") or "",
            epochs=int(meta.get("epochs") or 0),
            size_bytes=size_bytes,
        )

    def list_adapters(self) -> List[AdapterInfo]:
        infos: List[AdapterInfo] = []
        try:
            entries = sorted(os.listdir(self.lora_dir))
        except OSError:
            return infos
        for entry in entries:
            if os.path.isdir(os.path.join(self.lora_dir, entry)):
                try:
                    infos.append(self._build(entry))
                except AdapterNotFoundError:
                    continue
        return infos

    def get(self, adapter_id: str) -> AdapterInfo:
        return self._build(adapter_id)

    def delete(self, adapter_id: str) -> bool:
        path = self._safe_path(adapter_id)
        shutil.rmtree(path)
        return True

    def apply(self, adapter_id: str) -> ApplyAdapterResponse:
        """骨架阶段占位：训练引擎未接入，返回 applied=False。"""
        self._build(adapter_id)  # 校验 id 存在，不存在抛 404
        return ApplyAdapterResponse(
            adapter_id=adapter_id,
            applied=False,
            detail="训练引擎未接入，当前为骨架占位阶段",
        )