"""统一参考音频资产存储接口契约存根（零实现，仅签名）。

源真理: public/schema/ref_audio_asset.schema.json + server/ref_audio_store.py
完成 Skill: s0201
当前状态: 契约冻结——仅声明签名，无实现逻辑。
契约版本: 1.1.0（MINOR：补齐 per-agent 绑定/快照/集群 emit hook 层，register_from_prompt 补 async 标注）

职责：source=prompt 与 source=file 的统一注册、解析、列表、试听、选择、注释、删除与 checksum 去重；
per-agent 参考音频绑定（set_for_agent/get_for_agent/clear_for_agent/list_bindings）；
集群接入（set_emit_hook/build_snapshot/restore_snapshot/build_bindings）。
禁止客户端传任意本地路径读取文件；非法文件/路径穿越抛 InvalidRefAudioError；
不存在/已删除抛 RefAudioNotFoundError；被 Agent 绑定的资产拒绝删除抛 AssetBoundError。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from qwen3_tts_provider import (
    InvalidRefAudioError,
    RefAudioNotFoundError,
    RuntimeUnavailableError,
)

__all__ = [
    "AssetBoundError",
    "RefAudioAsset",
    "GeneratedAudio",
    "register_from_prompt", "register_from_file", "resolve", "get",
    "list", "update_note", "delete", "exists",
    "set_current", "get_current", "clear_current",
    "set_prompt_generator", "get_audio_path",
    "set_for_agent", "get_for_agent", "clear_for_agent",
    "list_bindings", "asset_used_by_any_agent",
    "set_emit_hook", "build_snapshot", "restore_snapshot", "build_bindings",
]


class AssetBoundError(Exception):
    """资产被某 Agent 绑定，拒绝删除（提示先解绑）。"""


class GeneratedAudio:
    """prompt 音频生成器返回结果（source=prompt 注册输入）。"""

    audio: bytes
    format: str
    sample_rate: int
    channels: int
    duration_seconds: float


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


async def register_from_prompt(prompt: str, language: Optional[str] = None) -> RefAudioAsset:
    """调用 Qwen3 VoiceDesign 根据自然语言提示词生成参考音频并持久化元数据（source=prompt）。

    Raises:
        RuntimeUnavailableError: 未注入 prompt 音频生成器（Qwen3 VoiceDesign 运行时未就绪）。
        InvalidRefAudioError: prompt 为空 / 生成音频元数据非法。
    """
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
    """删除资产（软删除，status=deleted）。若为当前默认资产，同时清除当前指针。

    Raises:
        AssetBoundError: 资产被任一 Agent 绑定（提示先解绑）。
        RefAudioNotFoundError: 资产不存在。
    """
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


# ============================================================================
# prompt 生成器 / 音频路径（Provider 与 VoiceDesign 接入点）
# ============================================================================

def set_prompt_generator(fn: Optional[Callable[..., Any]]) -> None:
    """注入/清除 prompt 音频生成器（Qwen3 VoiceDesign 任务接入点）。

    fn 签名：``async fn(prompt: str, language: Optional[str]) -> GeneratedAudio``。
    """
    ...


def get_audio_path(asset_id: str) -> Path:
    """返回资产音频文件磁盘路径（仅返回路径不读取内容；供推理链路 Provider 按需加载）。

    Raises:
        RefAudioNotFoundError: 资产不存在或已删除。
    """
    ...


# ============================================================================
# per-agent 参考音频绑定（独立于 current 默认指针，落盘 agent_bindings.json）
# ============================================================================

def set_for_agent(agent_id: str, asset_id: str, tts_voice: Optional[str] = None) -> dict:
    """为指定 Agent 绑定参考音频资产（运行真源），返回绑定后的 {asset_id, tts_voice} 字典。

    Raises:
        RefAudioNotFoundError: 资产不存在或已删除。
    """
    ...


def get_for_agent(agent_id: str) -> Optional[dict]:
    """返回指定 Agent 的参考音频绑定 {asset_id, tts_voice}；未绑定返回 None。"""
    ...


def clear_for_agent(agent_id: str) -> None:
    """清除指定 Agent 的参考音频绑定（不删除资产本身）。"""
    ...


def list_bindings() -> Dict[str, dict]:
    """返回全部 per-agent 绑定表副本（{agent_id: {asset_id, tts_voice}}）。"""
    ...


def asset_used_by_any_agent(asset_id: str) -> bool:
    """判断资产是否被任一 Agent 绑定（删除保护）。"""
    ...


# ============================================================================
# 集群接入（事件 emit hook 与快照/对等对齐）
# ============================================================================

def set_emit_hook(fn: Optional[Callable[[str, str, dict], Any]]) -> None:
    """注入/清除集群事件 emit hook（签名：``fn(unit, op, payload)``）。

    集群启用装配时注入 replicator.emit；停用/关闭时注入 None（短路，单机零影响）。
    """
    ...


def build_bindings() -> dict:
    """返回绑定表副本（供快照/对等对齐使用）。"""
    ...


def build_snapshot() -> dict:
    """打包 ref_audio_assets 为可序列化快照 blob。

    返回 dict：{version, checksum, assets(list), bindings(dict), audio{id: base64}}。
    """
    ...


def restore_snapshot(blob: dict) -> None:
    """从快照 blob 解包写入本机 ref_audio_assets（资产音频 + 索引 + 绑定）。"""
    ...