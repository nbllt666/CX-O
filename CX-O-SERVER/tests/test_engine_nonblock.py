"""streaming_engine 声纹延迟不阻塞改造单元测试（对应已批准 spec llm-tool-voiceprint-registration）。

验证点：
  1. 声纹 embedding 慢时：文本 final（pending）先下发，spk 补充消息后到；
  2. 声纹就绪（快速路径）：final 直接带 ready speaker；
  3. SPK_INFLIGHT_MAX 超限：第三句不产生 spk 后台任务、不阻塞；
  4. spk 补充消息含 em_embedding（192 float）与 speaker_status。

宿主环境可能无 funasr：在 import streaming_engine 前先注入 funasr 模块桩。
异步断言通过同步 wrapper + asyncio.run() 执行（环境无需 pytest-asyncio）。
"""
from __future__ import annotations

import asyncio
import os
import sys
import threading
import types

import numpy as np

# --- 在 import streaming_engine 前注入 funasr 桩 --- #
_funasr = types.ModuleType("funasr")


class _DummyAutoModel:
    def __init__(self, *args, **kwargs):
        pass


_funasr.AutoModel = _DummyAutoModel
sys.modules["funasr"] = _funasr

# 确保 asr_container 可导入
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pytest  # noqa: E402

from asr_container import streaming_engine as engine  # noqa: E402

DIM = 192


@pytest.fixture(autouse=True)
def _no_model_load(monkeypatch):
    """阻止 StreamSession.__init__ 触发真实模型加载。"""
    monkeypatch.setattr(engine, "_loaded", True)
    monkeypatch.setattr(engine, "_ASR", object())
    monkeypatch.setattr(engine, "_VAD", object())
    monkeypatch.setattr(engine, "_SPK", object())


def _make_session():
    s = engine.StreamSession()
    s._audio = np.arange(20000, dtype=np.float32)
    s._cur_start = 0
    s._vad_cache = {}
    return s


def _patch_vad(monkeypatch, session):
    """VAD 总是回报一个以当前句起点为 begins 的单句，供 _vad_sweep 产出句子。"""

    def _fake_vad(audio, is_final, vad_cache):
        return [[session._cur_start, session._cur_start + 1000]]

    monkeypatch.setattr(engine, "_run_vad", _fake_vad)


def _patch_asr(monkeypatch, text="你好"):
    monkeypatch.setattr(engine, "_run_asr_final", lambda audio: text)
    monkeypatch.setattr(engine, "_run_asr_partial", lambda audio, cache: "")
    monkeypatch.setattr(engine, "_run_asr_speculative", lambda audio: "")


def _unit_emb():
    return np.ones(DIM, dtype=np.float32) * 0.01


async def _run_delayed_pending_then_supplement(monkeypatch):
    session = _make_session()
    _patch_vad(monkeypatch, session)
    _patch_asr(monkeypatch)

    spk_gate = threading.Event()

    def _slow_spk(audio):
        spk_gate.wait(timeout=5)
        return _unit_emb()

    monkeypatch.setattr(engine, "_run_spk_embedding", _slow_spk)

    msgs = await session._vad_sweep()
    assert len(msgs) == 1
    assert msgs[0]["is_final"] is True
    assert msgs[0]["text"] == "你好"
    assert msgs[0]["speaker_status"] == "pending"   # 声纹未就绪 → pending 先发
    assert msgs[0]["speaker_id"] == ""
    assert session.drain_spk_messages() == []       # 补充消息尚未就绪

    # 放行声纹，等待后台 pump 完成补充消息
    spk_gate.set()
    drained = []
    for _ in range(100):
        await asyncio.sleep(0.05)
        drained = session.drain_spk_messages()
        if drained:
            break
    assert drained, "spk 补充消息未就绪"
    m = drained[0]
    assert m["type"] == "spk"
    assert m["speaker_status"] == "ready"
    assert m["speaker_id"] == "spk_0"
    assert isinstance(m["em_embedding"], list)
    assert len(m["em_embedding"]) == DIM


def test_delayed_embedding_pending_then_supplement(monkeypatch):
    asyncio.run(_run_delayed_pending_then_supplement(monkeypatch))


async def _run_fast_path_ready_speaker(monkeypatch):
    session = _make_session()
    _patch_vad(monkeypatch, session)
    _patch_asr(monkeypatch)
    monkeypatch.setattr(engine, "_run_spk_embedding", lambda audio: _unit_emb())

    msgs = await session._vad_sweep()
    assert len(msgs) == 1
    assert msgs[0]["speaker_status"] == "ready"
    assert msgs[0]["speaker_id"] == "spk_0"


def test_fast_path_ready_speaker(monkeypatch):
    asyncio.run(_run_fast_path_ready_speaker(monkeypatch))


async def _run_spk_inflight_limit_drops_third(monkeypatch):
    monkeypatch.setattr(engine, "SPK_INFLIGHT_MAX", 2)
    session = _make_session()
    _patch_vad(monkeypatch, session)
    _patch_asr(monkeypatch)

    gate = threading.Event()  # 两个 in-flight 的 spk 一直卡住

    def _slow_spk(audio):
        gate.wait(timeout=5)
        return _unit_emb()

    monkeypatch.setattr(engine, "_run_spk_embedding", _slow_spk)

    # 前两句 → pending，并登记两个后台任务（in-flight=2）
    m1 = await session._vad_sweep()
    m2 = await session._vad_sweep()
    assert m1[0]["speaker_status"] == "pending"
    assert m2[0]["speaker_status"] == "pending"
    assert session._spk_pending_count == 2

    # 第三句：超限，_track_spk_pump 直接丢弃，不新增任务、不阻塞
    m3 = await session._vad_sweep()
    assert m3[0]["speaker_status"] == "pending"
    assert session._spk_pending_count == 2            # 未超过上限
    assert session.drain_spk_messages() == []        # 无补充消息产生

    # 清理：放行两个卡住的声纹任务，避免悬挂后台任务
    gate.set()
    for _ in range(100):
        await asyncio.sleep(0.05)
        if session._spk_pending_count == 0:
            break


def test_spk_inflight_limit_drops_third(monkeypatch):
    asyncio.run(_run_spk_inflight_limit_drops_third(monkeypatch))


async def _run_finish_pending_and_ready(monkeypatch):
    session = _make_session()
    _patch_asr(monkeypatch)

    # ready 快速路径
    monkeypatch.setattr(engine, "_run_spk_embedding", lambda audio: _unit_emb())
    msgs = await session.finish()
    assert len(msgs) == 1
    assert msgs[0]["speaker_status"] == "ready"
    assert msgs[0]["speaker_id"] == "spk_0"

    # pending 路径（声纹慢）
    session2 = _make_session()
    _patch_asr(monkeypatch)
    gate = threading.Event()

    def _slow_spk(audio):
        gate.wait(timeout=5)
        return _unit_emb()

    monkeypatch.setattr(engine, "_run_spk_embedding", _slow_spk)
    m = (await session2.finish())[0]
    assert m["speaker_status"] == "pending"
    gate.set()
    drained = []
    for _ in range(100):
        await asyncio.sleep(0.05)
        drained = session2.drain_spk_messages()
        if drained:
            break
    assert drained and drained[0]["type"] == "spk"


def test_finish_pending_and_ready(monkeypatch):
    asyncio.run(_run_finish_pending_and_ready(monkeypatch))