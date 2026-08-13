"""统一参考音频资产存储接口契约存根（零实现，仅签名）。

源真理: public/schema/ref_audio_asset.schema.json
完成 Skill: s0201
当前状态: 契约冻结——仅声明签名，无实现逻辑。

职责：source=prompt 与 source=file 的统一注册、解析、列表、试听、选择、注释、删除与 checksum 去重。
禁止客户端传任意本地路径读取文件；非法文件/路径穿越抛 InvalidRefAudioError。
"""
from __future__ import annotations

from typing import List, Optional

from qwen3_tts_provider import InvalidRefAudioError, RefAudioNotFoundError

__all__ = [
    "RefAudioAsset",
    "register_from_prompt", "register_from_file", "resolve", "get",
    "list", "update_note", "delete", "exists",
    "set_current", "get_current", "clear_current",
]


class RefAudioAsset:
    """参考音频资产（对应 ref_audio_asset.schema.json）。"""
    id: str
    source: str  # prompt | file
    prompt: Optional[str]
    file_name: Optional[str]
    ref_text: Optional[str]
    checksum: str
    format: str
    sample_rate: int
    channels: int
    duration_seconds: float
    size_bytes: int
    status: str
    note: str
    created_at: str


def register_from_prompt(prompt: str, language: Optional[str] = None) -> RefAudioAsset:
    """调用 Qwen3 VoiceDesign 根据自然语言提示词生成参考音频并持久化元数据（source=prompt）。"""
    ...


def register_from_file(file_path: str, ref_text: Optional[str] = None, note: str = "") -> RefAudioAsset:
    """注册外部音频文件为资产（source=file）。校验格式/大小/时长/采样率/路径安全，非法抛 InvalidRefAudioError。"""
    ...


def resolve(asset_id: str) -> RefAudioAsset:
    """按 ID 解析资产。不存在抛 RefAudioNotFoundError。"""
    ...


def get(asset_id: str) -> Optional[RefAudioAsset]:
    """按 ID 获取资产，不存在返回 None。"""
    ...


def list() -> List[RefAudioAsset]:
    """列出全部可用资产。"""
    ...


def update_note(asset_id: str, note: str) -> RefAudioAsset:
    """更新资产注释。"""
    ...


def delete(asset_id: str) -> None:
    """删除资产（软删除，status=deleted）。若为当前默认资产，同时清除当前指针。"""
    ...


def set_current(asset_id: str) -> RefAudioAsset:
    """将资产设为当前默认参考音频（仅 registered 资产）。不存在或已删除抛 RefAudioNotFoundError。"""
    ...


def get_current() -> Optional[RefAudioAsset]:
    """返回当前默认参考音频资产；未设置或已删除/指针非法返回 None。"""
    ...


def clear_current() -> None:
    """清除当前默认参考音频设置（不删除资产本身）。"""
    ...


def exists(checksum: str) -> bool:
    """按 checksum 判断是否已存在（去重）。"""
    ...