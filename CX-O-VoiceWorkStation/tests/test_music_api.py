"""
Task 6「音乐 API 路由 /api/music/*」契约测试

对应 spec：add-voicews-music-cxfc-suite（Task 6）。

覆盖：
- POST /score/validate：合法歌谱 → {valid, errors: [], score 规范化}；
  非法歌谱（缺 bpm / beats<=0 / 非法 pitch）→ {valid: false, errors 逐条含字段定位}，HTTP 200
- POST /import-musicxml：合法 MusicXML → 歌谱 JSON（可再校验通过）；
  损坏/空文件 → 400 + 可读错误
- POST /synthesize → 202 {song_id, status} → GET /tasks/{id} 轮询至 completed
  → audio_url 经 /api/audio-files/ 可访问（mock 引擎 + 无和弦静音伴奏原生路径）
- 非法歌谱提交 → 任务 failed 且错误可读；非法增益 → 提交时 400
- GET /songs 列表摘要、GET /songs/{id} 单曲详情、不存在 404
- DELETE /songs/{id}：完成态删除成功、运行中 409、不存在 404
- 非法 song_id（%2e%2e 路径穿越尝试）在 tasks/songs/delete 三个端点均被拒（404）
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# 项目根目录入 sys.path（与 pyproject pythonpath=["."] 对齐，兼容任意 cwd 运行）
_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_DIR not in sys.path:
    sys.path.insert(0, _PROJECT_DIR)

from workstation.config import get_settings  # noqa: E402
from workstation.main import create_app  # noqa: E402
from workstation.music import draft_registry as dr  # noqa: E402
from workstation.services.song_pipeline import SongPipelineService  # noqa: E402
import workstation.api.music as music_api  # noqa: E402

# ---------------------------------------------------------------------------
# 测试辅助
# ---------------------------------------------------------------------------


def _valid_score(**overrides) -> dict:
    """一份合法歌谱：2 音符共 2 拍 @120BPM（1 秒音频，测试快速）；无和弦走静音伴奏原生路径"""
    score = {
        "title": "API测试歌",
        "bpm": 120,
        "melody": [
            {"pitch": "C4", "beats": 1.0, "lyric": "你"},
            {"pitch": "E4", "beats": 1.0, "lyric": "好"},
        ],
        "chords": [],
    }
    score.update(overrides)
    return score


_MINIMAL_MUSICXML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <movement-title>导入测试歌</movement-title>
  <part-list>
    <score-part id="P1"><part-name>Voice</part-name></score-part>
  </part-list>
  <part id="P1">
    <measure number="1">
      <attributes>
        <divisions>1</divisions>
        <key><fifths>0</fifths></key>
        <time><beats>4</beats><beat-type>4</beat-type></time>
        <clef><sign>G</sign><line>2</line></clef>
      </attributes>
      <direction>
        <direction-type>
          <metronome><beat-unit>quarter</beat-unit><per-minute>96</per-minute></metronome>
        </direction-type>
        <sound tempo="96"/>
      </direction>
      <note>
        <pitch><step>C</step><octave>4</octave></pitch>
        <duration>1</duration><type>quarter</type>
        <lyric><text>你</text></lyric>
      </note>
      <note>
        <pitch><step>E</step><octave>4</octave></pitch>
        <duration>1</duration><type>quarter</type>
        <lyric><text>好</text></lyric>
      </note>
      <harmony>
        <root><root-step>C</root-step></root>
        <kind>major</kind>
      </harmony>
    </measure>
  </part>
</score-partwise>
"""


@pytest_asyncio.fixture
async def music_client(tmp_path, monkeypatch):
    """
    隔离的音乐 API 测试环境：
    - get_settings() 单例的 songs/svc 目录全部落 tmp_path（audio_files 与 DELETE 同源）
    - music 路由的 get_song_pipeline 指向独立 SongPipelineService（不污染模块级单例）
    - mock 歌声引擎（singing_engine=mock），无 soundfont（测试均用无和弦歌谱走静音伴奏）
    - 草稿注册表隔离：_REGISTRY 清空 + drafts_dir 指向 tmp_path/drafts（不污染真实文件系统）
    """
    settings = get_settings()
    monkeypatch.setattr(settings.music, "songs_dir", str(tmp_path / "songs"))
    monkeypatch.setattr(settings.music, "singing_engine", "mock")
    monkeypatch.setattr(settings.music, "soundfont_path", "")
    monkeypatch.setattr(settings.sovits_svc, "infer_output_dir", str(tmp_path / "svc_results"))

    service = SongPipelineService(settings)
    monkeypatch.setattr(music_api, "get_song_pipeline", lambda: service)

    # 草稿注册表隔离（与 test_draft_registry 同构）：清空内存 + drafts_dir → tmp_path
    dr._REGISTRY.clear()
    monkeypatch.setattr(dr, "_drafts_dir_abs", lambda: str(tmp_path / "drafts"))

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, service

    # teardown：清理草稿注册表（monkeypatch 自动恢复 _drafts_dir_abs）
    dr._REGISTRY.clear()


async def _poll_task(client: AsyncClient, song_id: str, timeout: float = 15.0) -> dict:
    """经 API 轮询任务直至 completed / failed"""
    deadline = time.monotonic() + timeout
    while True:
        resp = await client.get(f"/api/music/tasks/{song_id}")
        assert resp.status_code == 200
        info = resp.json()
        if info["status"] in ("completed", "failed"):
            return info
        if time.monotonic() > deadline:
            raise TimeoutError(f"任务 {song_id} 未在 {timeout}s 内收敛: {info}")
        await asyncio.sleep(0.02)


# ---------------------------------------------------------------------------
# POST /score/validate
# ---------------------------------------------------------------------------


class TestScoreValidate:
    @pytest.mark.asyncio
    async def test_valid_score(self, music_client):
        """合法歌谱 → valid=true，errors 为空，返回规范化后的歌谱（默认值已填充）"""
        client, _ = music_client
        resp = await client.post("/api/music/score/validate", json=_valid_score())
        assert resp.status_code == 200
        body = resp.json()
        assert body["valid"] is True
        assert body["errors"] == []
        normalized = body["score"]
        assert normalized["title"] == "API测试歌"
        assert normalized["time_signature"] == "4/4"  # 默认值填充
        assert normalized["key"] == "C"
        # 歌谱契约 v2（MAJOR 2.0.0）：accompaniment_style 已移除；OBS-3 裸 dict
        # 不触发迁移，规范化后 accompaniment_tracks 落默认值 []
        assert "accompaniment_style" not in normalized
        assert normalized["accompaniment_tracks"] == []
        assert normalized["melody"][0]["pitch"] == "C4"

    @pytest.mark.asyncio
    async def test_invalid_score_missing_bpm(self, music_client):
        """缺 bpm → valid=false，错误逐条定位到字段，HTTP 仍为 200"""
        client, _ = music_client
        bad = {"title": "缺bpm", "melody": [{"pitch": "C4", "beats": 1.0}]}
        resp = await client.post("/api/music/score/validate", json=bad)
        assert resp.status_code == 200
        body = resp.json()
        assert body["valid"] is False
        assert any("bpm" in e for e in body["errors"])
        assert "score" not in body

    @pytest.mark.asyncio
    async def test_invalid_score_bad_beats_and_pitch(self, music_client):
        """beats<=0 与非法 pitch → 错误含 melody[i].beats / melody[i].pitch 字段定位"""
        client, _ = music_client
        resp = await client.post(
            "/api/music/score/validate",
            json=_valid_score(melody=[{"pitch": "C4", "beats": 0}]),
        )
        body = resp.json()
        assert body["valid"] is False
        assert any("melody[0].beats" in e for e in body["errors"])

        resp2 = await client.post(
            "/api/music/score/validate",
            json=_valid_score(melody=[{"pitch": "H9", "beats": 1.0}]),
        )
        body2 = resp2.json()
        assert body2["valid"] is False
        assert any("melody[0].pitch" in e for e in body2["errors"])


# ---------------------------------------------------------------------------
# POST /import-musicxml
# ---------------------------------------------------------------------------


class TestImportMusicXML:
    @pytest.mark.asyncio
    async def test_import_success(self, music_client):
        """合法 MusicXML → 200 返回歌谱 JSON，且该歌谱可通过 /score/validate"""
        client, _ = music_client
        resp = await client.post(
            "/api/music/import-musicxml",
            files={"file": ("song.musicxml", _MINIMAL_MUSICXML.encode("utf-8"), "text/xml")},
        )
        assert resp.status_code == 200
        score = resp.json()
        assert score["title"] == "导入测试歌"
        assert isinstance(score["bpm"], (int, float)) and score["bpm"] > 0
        assert len(score["melody"]) == 2
        assert score["melody"][0]["pitch"] == "C4"
        assert score["melody"][0]["lyric"] == "你"

        # 导入结果可直接进入校验/合成流程
        vresp = await client.post("/api/music/score/validate", json=score)
        assert vresp.status_code == 200
        assert vresp.json()["valid"] is True

    @pytest.mark.asyncio
    async def test_import_broken_file_400(self, music_client):
        """损坏文件 → 400 + 可读错误（统一错误格式 detail）"""
        client, _ = music_client
        resp = await client.post(
            "/api/music/import-musicxml",
            files={"file": ("broken.musicxml", b"this is not xml at all", "text/xml")},
        )
        assert resp.status_code == 400
        assert "detail" in resp.json()
        assert resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_import_empty_file_400(self, music_client):
        """空文件 → 400"""
        client, _ = music_client
        resp = await client.post(
            "/api/music/import-musicxml",
            files={"file": ("empty.musicxml", b"", "text/xml")},
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# POST /synthesize → 轮询 → 成品访问
# ---------------------------------------------------------------------------


class TestSynthesizeFlow:
    @pytest.mark.asyncio
    async def test_synthesize_to_completed_and_audio_accessible(self, music_client):
        """202 提交 → 轮询至 completed → audio_url 经 /api/audio-files/ 可播放"""
        client, _ = music_client
        resp = await client.post(
            "/api/music/synthesize",
            json={"score": _valid_score(), "vocal_gain": 1.0, "accompaniment_gain": 0.8},
        )
        assert resp.status_code == 202
        body = resp.json()
        assert body["song_id"]
        assert body["status"] == "pending"
        song_id = body["song_id"]

        info = await _poll_task(client, song_id)
        assert info["status"] == "completed", f"任务失败: {info['error']}"
        assert info["stage"] == "done"
        assert info["progress"] == 1.0
        assert info["error"] is None
        assert info["audio_url"] == f"/api/audio-files/songs/{song_id}/final.wav"
        # 步骤序列完整（svc 未指定模型 → skipped）
        assert [s["name"] for s in info["steps"]] == [
            "validate", "accompaniment", "vocal", "svc", "mix",
        ]

        # 成品音频经统一音频服务可访问
        audio_resp = await client.get(info["audio_url"])
        assert audio_resp.status_code == 200
        assert audio_resp.headers["content-type"].startswith("audio/wav")
        assert audio_resp.content[:4] == b"RIFF"

    @pytest.mark.asyncio
    async def test_synthesize_invalid_score_fails_readably(self, music_client):
        """非法歌谱提交 → 202 受理后任务 failed，错误可读且含字段定位"""
        client, _ = music_client
        resp = await client.post(
            "/api/music/synthesize",
            json={"score": _valid_score(melody=[{"pitch": "C4", "beats": 0}])},
        )
        assert resp.status_code == 202
        song_id = resp.json()["song_id"]

        info = await _poll_task(client, song_id)
        assert info["status"] == "failed"
        assert info["stage"] == "validate"
        assert "melody[0].beats" in info["error"]

    @pytest.mark.asyncio
    async def test_synthesize_invalid_gain_400(self, music_client):
        """增益非法（负数/NaN）→ 提交时 400 快速失败，不产生任务"""
        client, service = music_client
        resp = await client.post(
            "/api/music/synthesize",
            json={"score": _valid_score(), "vocal_gain": -1.0},
        )
        assert resp.status_code == 400
        assert "vocal_gain" in resp.json()["detail"]
        assert service.list_songs() == []


# ---------------------------------------------------------------------------
# GET /tasks /songs /songs/{id} 与 DELETE
# ---------------------------------------------------------------------------


class TestQueryAndDelete:
    @pytest.mark.asyncio
    async def test_task_not_found_404(self, music_client):
        client, _ = music_client
        resp = await client.get("/api/music/tasks/not-exist-song")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_songs_list_and_detail(self, music_client):
        """列表返回 metadata 摘要 + audio_url；详情返回完整 metadata"""
        client, _ = music_client
        resp = await client.post("/api/music/synthesize", json={"score": _valid_score()})
        song_id = resp.json()["song_id"]
        info = await _poll_task(client, song_id)
        assert info["status"] == "completed"

        # 列表：摘要字段齐全，按创建时间倒序（此处仅一首）
        lresp = await client.get("/api/music/songs")
        assert lresp.status_code == 200
        songs = lresp.json()["songs"]
        assert len(songs) == 1
        summary = songs[0]
        assert summary["song_id"] == song_id
        assert summary["title"] == "API测试歌"
        assert summary["status"] == "completed"
        assert summary["audio_url"].endswith(f"/songs/{song_id}/final.wav")
        assert "score" not in summary  # 摘要不含完整歌谱

        # 详情：完整 metadata（含歌谱快照与文件清单）
        dresp = await client.get(f"/api/music/songs/{song_id}")
        assert dresp.status_code == 200
        detail = dresp.json()
        assert detail["song_id"] == song_id
        assert detail["score"]["title"] == "API测试歌"
        assert detail["files"]["final"] == "final.wav"

    @pytest.mark.asyncio
    async def test_song_detail_not_found_404(self, music_client):
        client, _ = music_client
        resp = await client.get("/api/music/songs/not-exist-song")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_completed_song(self, music_client):
        """完成态歌曲可删除：目录移除后详情/列表均不可见"""
        client, service = music_client
        resp = await client.post("/api/music/synthesize", json={"score": _valid_score()})
        song_id = resp.json()["song_id"]
        info = await _poll_task(client, song_id)
        assert info["status"] == "completed"
        song_dir = Path(get_settings().music.songs_dir) / song_id
        assert song_dir.is_dir()

        dresp = await client.delete(f"/api/music/songs/{song_id}")
        assert dresp.status_code == 200
        assert dresp.json() == {"status": "success", "song_id": song_id}
        assert not song_dir.exists()
        assert service.get_task(song_id) is None
        assert (await client.get(f"/api/music/songs/{song_id}")).status_code == 404
        assert (await client.get("/api/music/songs")).json()["songs"] == []

    @pytest.mark.asyncio
    async def test_delete_running_song_409(self, music_client):
        """运行中任务不可删除（磁盘伪造 running 元数据）→ 409"""
        client, _ = music_client
        songs_dir = Path(get_settings().music.songs_dir)
        running_dir = songs_dir / "running-song"
        running_dir.mkdir(parents=True)
        (running_dir / "metadata.json").write_text(
            json.dumps({
                "song_id": "running-song",
                "title": "进行中",
                "status": "running",
                "created_at": "2026-07-21T00:00:00+08:00",
            }),
            encoding="utf-8",
        )
        resp = await client.delete("/api/music/songs/running-song")
        assert resp.status_code == 409
        assert running_dir.is_dir()  # 目录未被删除

    @pytest.mark.asyncio
    async def test_delete_not_found_404(self, music_client):
        client, _ = music_client
        resp = await client.delete("/api/music/songs/not-exist-song")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 路径穿越防护（song_id 白名单正则）
# ---------------------------------------------------------------------------


class TestSongIdTraversal:
    @pytest.mark.asyncio
    async def test_task_traversal_rejected(self, music_client):
        """%2e%2e 路径穿越尝试 → 流水线白名单正则拦截 → 404"""
        client, _ = music_client
        resp = await client.get("/api/music/tasks/%2e%2e")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_song_detail_traversal_rejected(self, music_client):
        client, _ = music_client
        resp = await client.get("/api/music/songs/%2e%2e")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_traversal_rejected(self, music_client):
        client, _ = music_client
        resp = await client.delete("/api/music/songs/%2e%2e")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 草稿命令总线 REST 端点（spec redesign-composition-staff-editor §5）
# ---------------------------------------------------------------------------


class TestDraftsApi:
    """POST/GET/DELETE /drafts、POST /drafts/{id}/commands 端点契约测试。"""

    @pytest.mark.asyncio
    async def test_create_draft_blank_placeholder(self, music_client):
        """POST /drafts 无 seed → 200 + draft_id + version=0 + snapshot 含 C4 全音符占位"""
        client, _ = music_client
        resp = await client.post("/api/music/drafts", json={})
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["draft_id"]
        assert body["version"] == 0
        assert body["changed_paths"] == ["$"]
        snap = body["snapshot"]
        assert snap["title"] == "未命名"
        assert snap["bpm"] == 120
        assert snap["melody"] == [{"pitch": "C4", "beats": 4, "lyric": ""}]
        # v2 默认值填充
        assert snap["accompaniment_tracks"] == []

    @pytest.mark.asyncio
    async def test_create_draft_with_seed(self, music_client):
        """POST /drafts 有 seed → 200 + snapshot 使用传入歌谱"""
        client, _ = music_client
        seed = {
            "title": "种子歌",
            "bpm": 96,
            "melody": [{"pitch": "E4", "beats": 1.0, "lyric": "嗨"}],
        }
        resp = await client.post("/api/music/drafts", json={"score": seed})
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["version"] == 0
        assert body["snapshot"]["title"] == "种子歌"
        assert body["snapshot"]["melody"][0]["pitch"] == "E4"
        assert body["snapshot"]["melody"][0]["lyric"] == "嗨"

    @pytest.mark.asyncio
    async def test_list_drafts(self, music_client):
        """GET /drafts → 200 + list[摘要]（含 draft_id/title/version/updated_at）"""
        client, _ = music_client
        await client.post("/api/music/drafts", json={})
        await client.post(
            "/api/music/drafts",
            json={"score": {"title": "B", "bpm": 120, "melody": [{"pitch": "C4", "beats": 1.0}]}},
        )
        resp = await client.get("/api/music/drafts")
        assert resp.status_code == 200
        items = resp.json()
        assert isinstance(items, list)
        assert len(items) == 2
        for item in items:
            assert {"draft_id", "title", "version", "updated_at"} <= set(item.keys())

    @pytest.mark.asyncio
    async def test_get_draft_snapshot(self, music_client):
        """GET /drafts/{id} → 200 + CommandResult（snapshot + version 不增）"""
        client, _ = music_client
        draft_id = (await client.post("/api/music/drafts", json={})).json()["draft_id"]
        resp = await client.get(f"/api/music/drafts/{draft_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["draft_id"] == draft_id
        assert body["version"] == 0  # get_draft 不增 version
        assert "snapshot" in body

    @pytest.mark.asyncio
    async def test_get_draft_not_found_404(self, music_client):
        """GET /drafts/{不存在id} → 404 + CommandResult（DRAFT_NOT_FOUND）"""
        client, _ = music_client
        resp = await client.get("/api/music/drafts/nonexistent-id")
        assert resp.status_code == 404
        body = resp.json()
        assert body["success"] is False
        assert body["error"]["code"] == "DRAFT_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_delete_draft(self, music_client):
        """DELETE /drafts/{id} → 200 + {success: true}；删除后 GET → 404"""
        client, _ = music_client
        draft_id = (await client.post("/api/music/drafts", json={})).json()["draft_id"]
        resp = await client.delete(f"/api/music/drafts/{draft_id}")
        assert resp.status_code == 200
        assert resp.json() == {"success": True}
        # 删除后不可再查
        resp2 = await client.get(f"/api/music/drafts/{draft_id}")
        assert resp2.status_code == 404

    @pytest.mark.asyncio
    async def test_execute_add_note_version_increment(self, music_client):
        """POST /drafts/{id}/commands add_note → 200 + version+1 + 占位被替换"""
        client, _ = music_client
        draft_id = (await client.post("/api/music/drafts", json={})).json()["draft_id"]
        resp = await client.post(
            f"/api/music/drafts/{draft_id}/commands",
            json={
                "command": "add_note",
                "args": {
                    "draft_id": draft_id,
                    "track": "melody",
                    "pitch": "D4",
                    "beats": 1.0,
                    "lyric": "你",
                },
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["version"] == 1  # 编辑命令 version+1
        # 空白草稿 C4 占位被首个 add_note 替换
        assert body["snapshot"]["melody"] == [{"pitch": "D4", "beats": 1.0, "lyric": "你"}]

    @pytest.mark.asyncio
    async def test_execute_unknown_command_400(self, music_client):
        """POST /drafts/{id}/commands 未知命令 → 400 + COMMAND_UNKNOWN"""
        client, _ = music_client
        draft_id = (await client.post("/api/music/drafts", json={})).json()["draft_id"]
        resp = await client.post(
            f"/api/music/drafts/{draft_id}/commands",
            json={"command": "not_a_command", "args": {"draft_id": draft_id}},
        )
        assert resp.status_code == 400
        body = resp.json()
        assert body["success"] is False
        assert body["error"]["code"] == "COMMAND_UNKNOWN"

    @pytest.mark.asyncio
    async def test_execute_missing_draft_id_in_args_400(self, music_client):
        """POST /drafts/{id}/commands args 缺 draft_id → 400 + COMMAND_ARGS_INVALID"""
        client, _ = music_client
        draft_id = (await client.post("/api/music/drafts", json={})).json()["draft_id"]
        resp = await client.post(
            f"/api/music/drafts/{draft_id}/commands",
            json={
                "command": "add_note",
                "args": {"track": "melody", "pitch": "D4", "beats": 1.0},  # 缺 draft_id
            },
        )
        assert resp.status_code == 400
        body = resp.json()
        assert body["success"] is False
        assert body["error"]["code"] == "COMMAND_ARGS_INVALID"

    @pytest.mark.asyncio
    async def test_execute_on_nonexistent_draft_404(self, music_client):
        """POST /drafts/{不存在id}/commands → 404 + DRAFT_NOT_FOUND"""
        client, _ = music_client
        resp = await client.post(
            "/api/music/drafts/nonexistent-id/commands",
            json={
                "command": "add_note",
                "args": {
                    "draft_id": "nonexistent-id",
                    "track": "melody",
                    "pitch": "D4",
                    "beats": 1.0,
                },
            },
        )
        assert resp.status_code == 404
        body = resp.json()
        assert body["success"] is False
        assert body["error"]["code"] == "DRAFT_NOT_FOUND"
