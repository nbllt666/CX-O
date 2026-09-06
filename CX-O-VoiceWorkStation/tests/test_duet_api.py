"""
Task 3「双人合唱 API」单测（change-id: enhance-cover-pitch-analysis-duet SubTask 3.4）

覆盖：
- POST /api/cover/duet：503 守卫（separation.enabled=false patch）、202 提交、
  400 参数非法（文件不存在）、422 请求体校验（缺 audio_path）
- GET  /api/cover/duet/{task_id}：404 未知任务、后台任务失败态可查询
- GET  /api/audio-files/duet/...：duet 类别成品播放、路径穿越防护、未知类别 404
（后台任务以失败桩分离器快速收敛，避免测试触达真实 demucs 子进程）
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
import wave
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# 项目根目录入 sys.path（与 pyproject pythonpath=["."] 对齐，兼容任意 cwd 运行）
_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_DIR not in sys.path:
    sys.path.insert(0, _PROJECT_DIR)

import workstation.api.audio_files as audio_files_mod  # noqa: E402
import workstation.api.duet as duet_api_mod  # noqa: E402
import workstation.services.duet_pipeline as duet_mod  # noqa: E402
from workstation.api.cover import separation_ready as _real_separation_ready  # noqa: E402
from workstation.config import get_settings  # noqa: E402
from workstation.main import create_app  # noqa: E402
from workstation.services.vocal_separator import SeparationError  # noqa: E402


def _make_wav(path: Path, frames: int = 200) -> Path:
    """写最小合法 16bit 单声道 WAV。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(44100)
        wf.writeframesraw(b"\x00\x00" * frames)
    return path


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    """API 测试客户端：duet 产物目录/注册表隔离，分离器替换为快速失败桩。"""

    class _FailingSeparator:
        def __init__(self, config=None):
            pass

        async def separate_vocal_accompaniment(self, audio_path):
            raise SeparationError("demucs", "测试桩：引擎未就绪")

    monkeypatch.setattr(duet_mod, "DUET_DIR", tmp_path / "duet")
    monkeypatch.setattr(duet_mod, "_duet_tasks", {})
    monkeypatch.setattr(duet_mod, "_duet_bg_tasks", {})
    monkeypatch.setattr(duet_mod, "VocalSeparator", _FailingSeparator)
    # 引擎就绪与否在本文件内按用例粒度控制（默认就绪，503 用例单独关闭）
    monkeypatch.setattr(duet_api_mod, "separation_ready", lambda: True)

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _poll_task(task_id: str, timeout: float = 5.0) -> dict:
    """轮询内存注册表直至任务收敛（事件循环让步驱动后台任务）。"""
    deadline = time.monotonic() + timeout
    while True:
        info = duet_mod.get_duet_task(task_id)
        assert info is not None
        if info["status"] in ("completed", "failed"):
            return info
        if time.monotonic() > deadline:
            raise TimeoutError(f"任务 {task_id} 未收敛: {info}")
        await asyncio.sleep(0.02)


@pytest.mark.asyncio
async def test_post_duet_503_when_separation_disabled(client, tmp_path, monkeypatch):
    """separation.enabled=false → 503，detail 含未启用说明"""
    # 还原真实守卫（client fixture 已桩替为恒就绪），再关闭 separation 开关
    monkeypatch.setattr(duet_api_mod, "separation_ready", _real_separation_ready)
    settings = get_settings()
    monkeypatch.setattr(settings.separation, "enabled", False)

    audio = _make_wav(tmp_path / "duet_api_503.wav")
    resp = await client.post("/api/cover/duet", json={"audio_path": str(audio)})
    assert resp.status_code == 503
    assert "未启用" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_post_duet_202_and_get_status_flow(client, tmp_path):
    """合法提交 → 202 {status, task_id}；后台任务（失败桩）状态经 GET 可查询"""
    audio = _make_wav(tmp_path / "input.wav")
    resp = await client.post(
        "/api/cover/duet",
        json={"audio_path": str(audio), "model_a": "modelA", "auto_transpose": True},
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "accepted"
    task_id = body["task_id"]
    assert task_id and len(task_id) == 32

    info = await _poll_task(task_id)
    assert info["status"] == "failed"  # 失败桩分离器快速收敛
    assert info["error"].startswith("[separate]")

    detail = await client.get(f"/api/cover/duet/{task_id}")
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["task_id"] == task_id
    assert payload["stage"] in ("separate", "done")
    assert set(payload["stages"]) == set(duet_mod.DUET_STAGES)
    assert {"a", "b", "source"} <= set(payload["transposes"])


@pytest.mark.asyncio
async def test_post_duet_400_when_audio_missing(client, tmp_path):
    """audio_path 文件不存在 → 400 可读错误，任务不注册"""
    resp = await client.post(
        "/api/cover/duet", json={"audio_path": str(tmp_path / "missing.wav")}
    )
    assert resp.status_code == 400
    assert "音频文件不存在" in resp.json()["detail"]
    assert duet_mod._duet_tasks == {}


@pytest.mark.asyncio
async def test_post_duet_422_when_audio_path_missing_field(client):
    """缺 audio_path 字段 → 422 请求体校验错误（先于业务守卫）"""
    resp = await client.post("/api/cover/duet", json={"model_a": "m"})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_get_duet_task_404_unknown(client):
    """未知/非法 task_id → 404"""
    resp = await client.get("/api/cover/duet/does-not-exist")
    assert resp.status_code == 404
    assert "任务不存在" in resp.json()["detail"]

    resp = await client.get("/api/cover/duet/%2E%2E%2Fescape")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_duet_capability_endpoint(client):
    """GET /api/cover/duet（Task 1 骨架保留）报告就绪状态"""
    resp = await client.get("/api/cover/duet")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert body["separation_ready"] is True


@pytest.mark.asyncio
async def test_audio_files_duet_category(tmp_path, monkeypatch):
    """audio-files duet 类别：成品可播放；路径穿越 403；未知类别 404"""
    monkeypatch.setattr(audio_files_mod, "DUET_DIR", tmp_path / "duet")
    task_id = "taskabc123"
    final = _make_wav(tmp_path / "duet" / task_id / "final.wav")
    assert final.is_file()

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get(f"/api/audio-files/duet/{task_id}/final.wav")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "audio/wav"
        assert len(resp.content) > 44

        # 路径穿越防护（编码 ..）：解析后必须位于受控目录内
        resp = await ac.get(f"/api/audio-files/duet/{task_id}/%2E%2E%2F%2E%2E%2Fsecret.wav")
        assert resp.status_code in (403, 404)

        # 未知类别
        resp = await ac.get("/api/audio-files/unknown-category/x.wav")
        assert resp.status_code == 404

        # 白名单外扩展名
        (tmp_path / "duet" / task_id / "note.txt").write_text("hi")
        resp = await ac.get(f"/api/audio-files/duet/{task_id}/note.txt")
        assert resp.status_code == 404
