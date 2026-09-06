"""
Task 7「CXFC 插件端点与注册心跳」测试

对应 spec：add-voicews-music-cxfc-suite（Task 7.1 / 7.2）。

覆盖：
- GET /tools：{"tools": [...]} 包裹，4 个工具（music_validate_score / music_sing /
  music_get_task / music_list_songs），各含 name/description/parameters，
  歌谱 schema 引用 Task 2 的 SCORE_SCHEMA
- GET /skills：{"skills": [...]} 包裹，virtual-singer-compose 技能字段与
  CX-O-SERVER SkillDefinition 模型对齐（prompt_template 含完整流程指引）
- POST /call：music_validate_score 合法/非法/缺参；music_sing 成功/非法歌谱/非法增益；
  music_get_task 成功/任务不存在/缺参；music_list_songs；未知工具明确报错
- 全链路：/call music_sing → 轮询 /call music_get_task → completed + audio_url
  → music_list_songs 含该曲（mock 引擎 + 无和弦静音伴奏原生路径）
- GET /health：含 name（= settings.cxfc.plugin_name）/version
- 注册服务（httpx MockTransport 假 CX-O-SERVER）：
  注册/心跳请求形状、心跳循环启动停止与注销、注册失败指数退避重试、
  心跳 404 触发重新注册、server 不可达持续重试不崩溃、
  enabled=false / auto_register=false 零请求零副作用、lifespan 集成冒烟
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient, MockTransport

# 项目根目录入 sys.path（与 pyproject pythonpath=["."] 对齐，兼容任意 cwd 运行）
_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_DIR not in sys.path:
    sys.path.insert(0, _PROJECT_DIR)

from workstation.config import get_settings  # noqa: E402
from workstation.main import create_app  # noqa: E402
from workstation.services.song_pipeline import SongPipelineService  # noqa: E402
import workstation.api.cxfc_plugin as cxfc_plugin  # noqa: E402
import workstation.services.cxfc_registration as cxfc_registration  # noqa: E402
from workstation.services.cxfc_registration import CXFCRegistrationService  # noqa: E402

# ---------------------------------------------------------------------------
# 测试辅助
# ---------------------------------------------------------------------------


def _valid_score(**overrides) -> dict:
    """合法歌谱：2 音符共 2 拍 @120BPM（1 秒音频）；无和弦走静音伴奏原生路径"""
    score = {
        "title": "CXFC测试歌",
        "bpm": 120,
        "melody": [
            {"pitch": "C4", "beats": 1.0, "lyric": "你"},
            {"pitch": "E4", "beats": 1.0, "lyric": "好"},
        ],
        "chords": [],
    }
    score.update(overrides)
    return score


@pytest_asyncio.fixture
async def cxfc_client(tmp_path, monkeypatch):
    """
    隔离的 CXFC 端点测试环境（与 test_music_api.py 的 fixture 同构）：
    - songs/svc 目录落 tmp_path；mock 歌声引擎；无 soundfont（无和弦歌谱走静音伴奏）
    - cxfc_plugin 的 get_song_pipeline 指向独立 SongPipelineService（不污染模块级单例）
    - draft_registry 草稿落盘目录隔离到 tmp_path/drafts（默认相对项目根，避免污染真实 data 目录）
    """
    settings = get_settings()
    monkeypatch.setattr(settings.music, "songs_dir", str(tmp_path / "songs"))
    monkeypatch.setattr(settings.music, "singing_engine", "mock")
    monkeypatch.setattr(settings.music, "soundfont_path", "")
    monkeypatch.setattr(settings.sovits_svc, "infer_output_dir", str(tmp_path / "svc_results"))

    # 草稿落盘隔离（draft_registry._drafts_dir_abs 默认返回项目根/data/music/drafts）
    _drafts_tmp = str(tmp_path / "drafts")
    monkeypatch.setattr(
        cxfc_plugin.draft_registry, "_drafts_dir_abs", lambda: _drafts_tmp
    )

    service = SongPipelineService(settings)
    monkeypatch.setattr(cxfc_plugin, "get_song_pipeline", lambda: service)

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, service


async def _call(client: AsyncClient, tool: str, arguments: dict | None = None) -> dict:
    """POST /call 便捷封装：返回响应 JSON（协议约定 HTTP 恒 200）"""
    resp = await client.post("/call", json={"tool": tool, "arguments": arguments or {}})
    assert resp.status_code == 200
    return resp.json()


# ---------------------------------------------------------------------------
# GET /tools
# ---------------------------------------------------------------------------


class TestToolsEndpoint:
    @pytest.mark.asyncio
    async def test_tools_wrapped_and_complete(self, cxfc_client):
        """响应包裹 {"tools": [...]}；6 个工具齐备，各含 name/description/parameters"""
        client, _ = cxfc_client
        resp = await client.get("/tools")
        assert resp.status_code == 200
        body = resp.json()
        assert "tools" in body
        tools = body["tools"]
        assert [t["name"] for t in tools] == [
            "music_edit_score",
            "music_list_instruments",
            "music_validate_score",
            "music_sing",
            "music_get_task",
            "music_list_songs",
        ]
        for tool in tools:
            assert tool["description"], f"{tool['name']} 缺 description"
            assert isinstance(tool["parameters"], dict), f"{tool['name']} 缺 parameters"
            assert tool["parameters"]["type"] == "object"

    @pytest.mark.asyncio
    async def test_tools_score_schema_reference(self, cxfc_client):
        """工具参数引用冻结契约：SCORE_SCHEMA_V2 / command-protocol / music-inventory"""
        client, _ = cxfc_client
        tools = (await client.get("/tools")).json()["tools"]
        by_name = {t["name"]: t for t in tools}

        # music_validate_score：required=["score"]，score 引用 SCORE_SCHEMA_V2
        vs_params = by_name["music_validate_score"]["parameters"]
        assert vs_params["required"] == ["score"]
        vs_score = vs_params["properties"]["score"]
        assert vs_score["required"] == ["title", "bpm", "melody"]
        assert "melody" in vs_score["properties"]

        # music_sing：draft_id 与 score 二选一（required 不强制 score），含 draft_id + 可选参数
        sing_params = by_name["music_sing"]["parameters"]
        assert "score" not in sing_params.get("required", [])  # 二选一，不强制
        sing_props = sing_params["properties"]
        assert "draft_id" in sing_props, "music_sing 缺 draft_id 参数"
        assert sing_props["score"]["required"] == ["title", "bpm", "melody"]  # 引用 SCORE_SCHEMA_V2
        for opt in ("svc_model", "transpose", "vocal_gain", "accompaniment_gain"):
            assert opt in sing_props, f"music_sing 缺可选参数 {opt}"

        # music_edit_score：required=["command","args"]，command enum 来自契约（20 命令）
        es_params = by_name["music_edit_score"]["parameters"]
        assert es_params["required"] == ["command", "args"]
        es_command = es_params["properties"]["command"]
        assert "create_draft" in es_command["enum"]
        assert "submit_draft" in es_command["enum"]
        assert len(es_command["enum"]) == 20  # command-protocol 20 命令
        assert "draft_id" in es_params["properties"]

        # music_list_instruments：无参
        li_params = by_name["music_list_instruments"]["parameters"]
        assert li_params["properties"] == {}

        assert by_name["music_get_task"]["parameters"]["required"] == ["task_id"]


# ---------------------------------------------------------------------------
# GET /skills
# ---------------------------------------------------------------------------


class TestSkillsEndpoint:
    @pytest.mark.asyncio
    async def test_skills_wrapped_and_skill_fields(self, cxfc_client):
        """响应包裹 {"skills": [...]}；virtual-singer-compose 字段与 SkillDefinition 对齐，含命令流指引"""
        client, _ = cxfc_client
        resp = await client.get("/skills")
        assert resp.status_code == 200
        body = resp.json()
        assert "skills" in body
        skills = body["skills"]
        assert len(skills) == 1
        skill = skills[0]
        assert skill["name"] == "virtual-singer-compose"
        assert skill["description"]
        assert skill["auto_inject"] is True
        assert skill["trigger_events"] == []
        for keyword in ("唱歌", "作曲", "写歌", "演唱"):
            assert keyword in skill["trigger_keywords"]
        # prompt_template 内置命令流指引（merged.md §8）：create_draft → 编辑 → arrange_track
        # → validate_draft → submit_draft/music_sing → 轮询 music_get_task → audio_url
        template = skill["prompt_template"]
        assert "music_edit_score" in template
        assert "create_draft" in template
        assert "arrange_track" in template
        assert "validate_draft" in template
        assert "submit_draft" in template
        assert "music_sing" in template
        assert "music_get_task" in template
        assert "audio_url" in template
        # 旧整谱 PUT 流程不应再作为主流程（命令流取代，v1 字段 accompaniment_style 不再出现）
        assert "accompaniment_style" not in template


# ---------------------------------------------------------------------------
# POST /call：music_validate_score
# ---------------------------------------------------------------------------


class TestCallValidateScore:
    @pytest.mark.asyncio
    async def test_valid_score(self, cxfc_client):
        """合法歌谱 → success=true，result.valid=true，附带规范化 v2 歌谱（normalized_score）"""
        client, _ = cxfc_client
        body = await _call(client, "music_validate_score", {"score": _valid_score()})
        assert body["success"] is True
        result = body["result"]
        assert result["valid"] is True
        assert result["errors"] == []
        assert result["normalized_score"]["time_signature"] == "4/4"  # 默认值填充
        assert result["normalized_score"]["key"] == "C"

    @pytest.mark.asyncio
    async def test_v1_score_migration(self, cxfc_client):
        """v1 输入（含 accompaniment_style）→ 自动迁移 v2，valid=true，normalized_score 含 accompaniment_tracks"""
        client, _ = cxfc_client
        v1 = {
            "title": "v1测试歌",
            "bpm": 120,
            "melody": [{"pitch": "C4", "beats": 1.0, "lyric": "你"}],
            "chords": [{"chord": "C", "beats": 4}],
            "accompaniment_style": "piano",
        }
        body = await _call(client, "music_validate_score", {"score": v1})
        assert body["success"] is True
        result = body["result"]
        assert result["valid"] is True
        normalized = result["normalized_score"]
        # v1 迁移后 accompaniment_style 删除，生成 accompaniment_tracks（piano → block_chords）
        assert "accompaniment_style" not in normalized
        assert isinstance(normalized.get("accompaniment_tracks"), list)
        assert len(normalized["accompaniment_tracks"]) == 1
        trk = normalized["accompaniment_tracks"][0]
        assert trk["program"] == 0
        assert trk["mode"] == "auto"
        assert trk["style"] == "block_chords"

    @pytest.mark.asyncio
    async def test_invalid_score(self, cxfc_client):
        """非法歌谱 → success=true（工具本身执行成功），result.valid=false + 逐条错误"""
        client, _ = cxfc_client
        bad = _valid_score(melody=[{"pitch": "C4", "beats": 0}])
        body = await _call(client, "music_validate_score", {"score": bad})
        assert body["success"] is True
        result = body["result"]
        assert result["valid"] is False
        assert any("melody[0].beats" in e for e in result["errors"])

    @pytest.mark.asyncio
    async def test_missing_score_argument(self, cxfc_client):
        """缺 score 参数 → success=false 且错误可读"""
        client, _ = cxfc_client
        body = await _call(client, "music_validate_score", {})
        assert body["success"] is False
        assert "score" in body["error"]


# ---------------------------------------------------------------------------
# POST /call：music_edit_score / music_list_instruments
# ---------------------------------------------------------------------------


class TestCallEditScore:
    @pytest.mark.asyncio
    async def test_create_draft_returns_command_result(self, cxfc_client):
        """create_draft → CommandResult：success=true，含 draft_id/version/snapshot"""
        client, _ = cxfc_client
        body = await _call(client, "music_edit_score", {
            "command": "create_draft",
            "args": {"score": _valid_score()},
        })
        assert body["success"] is True
        cr = body["result"]  # CommandResult
        assert cr["success"] is True
        assert cr["draft_id"]
        assert cr["version"] == 0
        assert isinstance(cr["snapshot"], dict)
        assert cr["snapshot"]["title"] == "CXFC测试歌"

    @pytest.mark.asyncio
    async def test_create_draft_blank(self, cxfc_client):
        """create_draft 缺省 score → 建空白草稿（version=0）"""
        client, _ = cxfc_client
        body = await _call(client, "music_edit_score", {
            "command": "create_draft",
            "args": {},
        })
        assert body["success"] is True
        cr = body["result"]
        assert cr["success"] is True
        assert cr["draft_id"]
        assert cr["version"] == 0

    @pytest.mark.asyncio
    async def test_add_note_missing_draft_id_command_args_invalid(self, cxfc_client):
        """add_note 缺 draft_id → COMMAND_ARGS_INVALID（仅 create_draft 可缺省）"""
        client, _ = cxfc_client
        body = await _call(client, "music_edit_score", {
            "command": "add_note",
            "args": {"track": "melody", "pitch": "C4", "beats": 1.0},
        })
        assert body["success"] is False
        error = body["error"]
        assert error["code"] == "COMMAND_ARGS_INVALID"
        assert "draft_id" in error["message"]

    @pytest.mark.asyncio
    async def test_unknown_command(self, cxfc_client):
        """未知命令 → COMMAND_UNKNOWN（draft_id 按契约放 args 内，避免先被 draft_id 缺失拦截）"""
        client, _ = cxfc_client
        body = await _call(client, "music_edit_score", {
            "command": "sing_loudly",
            "args": {"draft_id": "any"},
        })
        assert body["success"] is False
        error = body["error"]
        assert error["code"] == "COMMAND_UNKNOWN"
        assert "sing_loudly" in error["message"]

    @pytest.mark.asyncio
    async def test_full_edit_flow_add_note_and_validate(self, cxfc_client):
        """命令流：create_draft → add_note → validate_draft（验证 CommandResult 透传）"""
        client, _ = cxfc_client
        # create_draft 空白草稿
        body = await _call(client, "music_edit_score", {
            "command": "create_draft", "args": {},
        })
        assert body["success"] is True
        draft_id = body["result"]["draft_id"]
        # add_note 到 melody（args 内须含 draft_id 满足 args_add_note schema）
        body = await _call(client, "music_edit_score", {
            "draft_id": draft_id,
            "command": "add_note",
            "args": {"draft_id": draft_id, "track": "melody", "pitch": "C4", "beats": 1.0, "lyric": "你"},
        })
        assert body["success"] is True
        assert body["result"]["success"] is True
        assert body["result"]["version"] == 1
        # validate_draft
        body = await _call(client, "music_edit_score", {
            "draft_id": draft_id,
            "command": "validate_draft",
            "args": {"draft_id": draft_id},
        })
        assert body["success"] is True
        assert body["result"]["result"]["valid"] is True


class TestCallListInstruments:
    @pytest.mark.asyncio
    async def test_list_instruments_shape(self, cxfc_client):
        """music_list_instruments → {instrument_groups(16), styles, drum_keys}"""
        client, _ = cxfc_client
        body = await _call(client, "music_list_instruments", {})
        assert body["success"] is True
        result = body["result"]
        assert len(result["instrument_groups"]) == 16  # GM 16 组
        # 每组 8 音色，program 严格 = program_range[0] + i
        for group in result["instrument_groups"]:
            assert len(group["instruments"]) == 8
            start = group["program_range"][0]
            for i, inst in enumerate(group["instruments"]):
                assert inst["program"] == start + i
        # 节奏型枚举含 block_chords / rock_4beat
        style_ids = [s["id"] for s in result["styles"]]
        assert "block_chords" in style_ids
        assert "rock_4beat" in style_ids
        # 鼓键含 kick=36 / snare=38
        drum_keys = {d["key"]: d["midi"] for d in result["drum_keys"]}
        assert drum_keys["kick"] == 36
        assert drum_keys["snare"] == 38

    @pytest.mark.asyncio
    async def test_list_instruments_no_args(self, cxfc_client):
        """music_list_instruments 无参，空 arguments 同样工作"""
        client, _ = cxfc_client
        body = await _call(client, "music_list_instruments")
        assert body["success"] is True
        assert "instrument_groups" in body["result"]


# ---------------------------------------------------------------------------
# POST /call：music_sing
# ---------------------------------------------------------------------------


class TestCallSing:
    @pytest.mark.asyncio
    async def test_sing_success(self, cxfc_client):
        """合法歌谱 → success=true，返回 song_id/task_id，status=pending"""
        client, _ = cxfc_client
        body = await _call(client, "music_sing", {"score": _valid_score()})
        assert body["success"] is True
        result = body["result"]
        assert result["song_id"]
        assert result["task_id"] == result["song_id"]
        assert result["status"] == "pending"

    @pytest.mark.asyncio
    async def test_sing_invalid_score_fast_fail(self, cxfc_client):
        """非法歌谱 → success=false 逐条可读错误（快速失败，不产生 failed 任务）"""
        client, service = cxfc_client
        bad = _valid_score(melody=[{"pitch": "H9", "beats": 1.0}])
        body = await _call(client, "music_sing", {"score": bad})
        assert body["success"] is False
        assert "校验失败" in body["error"]
        assert "melody[0].pitch" in body["error"]
        assert service.list_songs() == []

    @pytest.mark.asyncio
    async def test_sing_invalid_gain_fast_fail(self, cxfc_client):
        """非法增益（负数）→ success=false；非法歌谱之外的其他参数错误同样快速失败"""
        client, service = cxfc_client
        body = await _call(
            client, "music_sing", {"score": _valid_score(), "vocal_gain": -1.0}
        )
        assert body["success"] is False
        assert "vocal_gain" in body["error"]
        assert service.list_songs() == []

    @pytest.mark.asyncio
    async def test_sing_with_draft_id(self, cxfc_client):
        """draft_id 路径：从草稿取 score 走 submit_draft，返回 {task_id, song_id, status}"""
        client, _ = cxfc_client
        # 先 create_draft 建草稿
        body = await _call(client, "music_edit_score", {
            "command": "create_draft", "args": {"score": _valid_score()},
        })
        assert body["success"] is True
        draft_id = body["result"]["draft_id"]
        # music_sing draft_id → submit_draft 路径
        body = await _call(client, "music_sing", {"draft_id": draft_id})
        assert body["success"] is True
        result = body["result"]
        assert result["task_id"]
        assert result["song_id"] == result["task_id"]
        assert result["status"] == "pending"

    @pytest.mark.asyncio
    async def test_sing_neither_draft_id_nor_score(self, cxfc_client):
        """draft_id 与 score 都缺 → success=false 可读错误"""
        client, _ = cxfc_client
        body = await _call(client, "music_sing", {"svc_model": "x"})
        assert body["success"] is False
        assert "draft_id" in body["error"] or "score" in body["error"]


# ---------------------------------------------------------------------------
# POST /call：music_get_task / music_list_songs / 未知工具
# ---------------------------------------------------------------------------


class TestCallQueryAndUnknown:
    @pytest.mark.asyncio
    async def test_get_task_not_found(self, cxfc_client):
        """任务不存在 → success=false + 可读错误"""
        client, _ = cxfc_client
        body = await _call(client, "music_get_task", {"task_id": "not-exist-song"})
        assert body["success"] is False
        assert "不存在" in body["error"]

    @pytest.mark.asyncio
    async def test_get_task_missing_argument(self, cxfc_client):
        client, _ = cxfc_client
        body = await _call(client, "music_get_task", {})
        assert body["success"] is False
        assert "task_id" in body["error"]

    @pytest.mark.asyncio
    async def test_list_songs_empty(self, cxfc_client):
        """空历史 → success=true，songs 为空列表"""
        client, _ = cxfc_client
        body = await _call(client, "music_list_songs")
        assert body["success"] is True
        assert body["result"]["songs"] == []

    @pytest.mark.asyncio
    async def test_unknown_tool(self, cxfc_client):
        """未知工具 → success=false，错误含工具名与可用清单（HTTP 仍 200）"""
        client, _ = cxfc_client
        body = await _call(client, "music_dance", {"foo": 1})
        assert body["success"] is False
        assert "未知工具" in body["error"]
        assert "music_dance" in body["error"]
        assert "music_sing" in body["error"]  # 可用工具清单


# ---------------------------------------------------------------------------
# 全链路：/call music_sing → 轮询 music_get_task → completed
# ---------------------------------------------------------------------------


class TestFullFlow:
    @pytest.mark.asyncio
    async def test_sing_poll_to_completed_and_list(self, cxfc_client):
        """mock 引擎下 CXFC 全链路：演唱 → 轮询 → completed + audio_url → 历史含该曲"""
        client, _ = cxfc_client
        sing_body = await _call(client, "music_sing", {"score": _valid_score()})
        assert sing_body["success"] is True
        task_id = sing_body["result"]["task_id"]

        deadline = time.monotonic() + 15.0
        while True:
            task_body = await _call(client, "music_get_task", {"task_id": task_id})
            assert task_body["success"] is True
            info = task_body["result"]
            if info["status"] in ("completed", "failed"):
                break
            if time.monotonic() > deadline:
                raise TimeoutError(f"任务 {task_id} 未收敛: {info}")
            await asyncio.sleep(0.02)

        assert info["status"] == "completed", f"任务失败: {info['error']}"
        assert info["progress"] == 1.0
        assert info["audio_url"] == f"/api/audio-files/songs/{task_id}/final.wav"

        # 成品音频经统一音频服务可访问
        audio_resp = await client.get(info["audio_url"])
        assert audio_resp.status_code == 200
        assert audio_resp.content[:4] == b"RIFF"

        # 历史列表含该曲（摘要口径）
        list_body = await _call(client, "music_list_songs")
        assert list_body["success"] is True
        songs = list_body["result"]["songs"]
        assert any(
            s["song_id"] == task_id and s["status"] == "completed" for s in songs
        )


# ---------------------------------------------------------------------------
# GET /health：name/version
# ---------------------------------------------------------------------------


class TestHealth:
    @pytest.mark.asyncio
    async def test_health_contains_name_and_version(self, cxfc_client):
        """/health 响应含 name（= cxfc.plugin_name）与 version（主系统 connect 时读取）"""
        client, _ = cxfc_client
        resp = await client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "healthy"
        assert body["name"] == get_settings().cxfc.plugin_name
        assert body["version"]


# ---------------------------------------------------------------------------
# 注册服务：假 CX-O-SERVER（httpx MockTransport）
# ---------------------------------------------------------------------------


class _FakeCXOServer:
    """模拟 CX-O-SERVER 的 CXFC 端点，记录全部入站请求用于断言"""

    def __init__(self):
        self.registers: list[dict] = []
        self.heartbeats: list[dict] = []
        self.unregisters: list[str] = []
        self.fail_registers = 0  # 前 N 次注册返回 500（测试重试）
        self.heartbeat_404_once = False  # 下一次心跳返回 404（测试重注册）

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/cxfc/register" and request.method == "POST":
            if self.fail_registers > 0:
                self.fail_registers -= 1
                return httpx.Response(500, json={"detail": "internal error"})
            payload = json.loads(request.content)
            self.registers.append(payload)
            plugin_id = f"cxfc_{payload['host']}_{payload['port']}"
            return httpx.Response(200, json={"status": "ok", "plugin_id": plugin_id})
        if path == "/api/cxfc/heartbeat" and request.method == "POST":
            payload = json.loads(request.content)
            self.heartbeats.append(payload)
            if self.heartbeat_404_once:
                self.heartbeat_404_once = False
                return httpx.Response(404, json={"detail": "插件不存在"})
            return httpx.Response(200, json={"status": "alive"})
        if path.startswith("/api/cxfc/plugins/") and request.method == "DELETE":
            self.unregisters.append(path.rsplit("/", 1)[-1])
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(404, json={"detail": "not found"})


@pytest_asyncio.fixture
async def reg_env(monkeypatch):
    """
    注册服务测试环境：
    - cxfc 配置指向假 server（MockTransport，零真实网络）；心跳间隔 0.05s 加速循环
    - server.host=0.0.0.0（验证注册地址归一化为 127.0.0.1）、port=8200
    - teardown 统一 stop（幂等），避免后台任务泄漏到其他测试
    """
    settings = get_settings()
    monkeypatch.setattr(settings.cxfc, "enabled", True)
    monkeypatch.setattr(settings.cxfc, "auto_register", True)
    monkeypatch.setattr(settings.cxfc, "server_url", "http://cxo-test")
    monkeypatch.setattr(settings.cxfc, "heartbeat_interval", 0.05)
    monkeypatch.setattr(settings.cxfc, "plugin_name", "voiceworkstation-music-test")
    monkeypatch.setattr(settings.server, "host", "0.0.0.0")
    monkeypatch.setattr(settings.server, "port", 8200)

    server = _FakeCXOServer()
    service = CXFCRegistrationService(settings)
    service._client = httpx.AsyncClient(transport=MockTransport(server.handler))  # noqa: SLF001
    yield service, server
    await service.stop()


async def _wait_registered(service: CXFCRegistrationService, timeout: float = 5.0) -> str:
    """等待注册完成并返回 plugin_id"""
    deadline = time.monotonic() + timeout
    while service.plugin_id is None:
        if time.monotonic() > deadline:
            raise TimeoutError("注册未在预期时间内完成")
        await asyncio.sleep(0.02)
    return service.plugin_id


class TestRegisterAndHeartbeatShapes:
    @pytest.mark.asyncio
    async def test_register_payload_shape(self, reg_env):
        """注册请求形状：host 归一化 + port + name + tools/skills/capabilities"""
        service, server = reg_env
        await service._register()  # noqa: SLF001 - 直接验证单次协议请求

        assert len(server.registers) == 1
        payload = server.registers[0]
        assert payload["host"] == "127.0.0.1"  # 0.0.0.0 监听地址归一化为回环
        assert payload["port"] == 8200
        assert payload["name"] == "voiceworkstation-music-test"
        assert isinstance(payload["capabilities"], list) and payload["capabilities"]
        # 工具/技能清单与 /tools、/skills 端点同源（6 工具，含命令门面与枚举清单）
        assert [t["name"] for t in payload["tools"]] == [
            "music_edit_score",
            "music_list_instruments",
            "music_validate_score",
            "music_sing",
            "music_get_task",
            "music_list_songs",
        ]
        assert payload["skills"][0]["name"] == "virtual-singer-compose"
        # plugin_id 采用主系统返回值（cxfc_<host>_<port> 规则）
        assert service.plugin_id == "cxfc_127.0.0.1_8200"

    @pytest.mark.asyncio
    async def test_heartbeat_payload_shape(self, reg_env):
        """心跳请求形状：{plugin_id, port}；200 → True"""
        service, server = reg_env
        await service._register()  # noqa: SLF001
        alive = await service._heartbeat()  # noqa: SLF001
        assert alive is True
        assert server.heartbeats == [{"plugin_id": "cxfc_127.0.0.1_8200", "port": 8200}]


class TestHeartbeatLoop:
    @pytest.mark.asyncio
    async def test_loop_register_heartbeat_and_unregister_on_stop(self, reg_env):
        """start → 注册+周期心跳；stop → 取消任务 + 注销 + 关闭客户端"""
        service, server = reg_env
        assert await service.start() is True
        assert service.running is True

        plugin_id = await _wait_registered(service)
        await asyncio.sleep(0.25)  # interval=0.05 → 多次心跳
        assert len(server.registers) >= 1
        assert len(server.heartbeats) >= 2
        assert all(h["plugin_id"] == plugin_id for h in server.heartbeats)

        await service.stop()
        assert service.running is False
        assert service.plugin_id is None
        assert server.unregisters == [plugin_id]

    @pytest.mark.asyncio
    async def test_register_failure_retries_with_backoff(self, reg_env):
        """注册连续失败 → 指数退避重试直至成功，服务不崩溃"""
        service, server = reg_env
        server.fail_registers = 2  # 前两次注册 500
        assert await service.start() is True

        plugin_id = await _wait_registered(service, timeout=10.0)
        assert plugin_id == "cxfc_127.0.0.1_8200"
        assert len(server.registers) >= 1  # 第 3 次尝试成功
        await service.stop()

    @pytest.mark.asyncio
    async def test_heartbeat_404_triggers_reregister(self, reg_env):
        """心跳 404（主系统丢失插件）→ 自动重新注册"""
        service, server = reg_env
        assert await service.start() is True
        await _wait_registered(service)
        assert len(server.registers) == 1

        server.heartbeat_404_once = True
        deadline = time.monotonic() + 5.0
        while len(server.registers) < 2:
            if time.monotonic() > deadline:
                raise TimeoutError("心跳 404 后未触发重新注册")
            await asyncio.sleep(0.02)
        await service.stop()

    @pytest.mark.asyncio
    async def test_unreachable_server_retries_without_crash(self, reg_env):
        """主系统不可达 → 持续重试不崩溃，stop 可干净收尾"""

        def _refused(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        service, _ = reg_env
        service._client = httpx.AsyncClient(transport=MockTransport(_refused))  # noqa: SLF001
        assert await service.start() is True
        await asyncio.sleep(0.3)
        assert service.plugin_id is None  # 始终未注册成功
        assert service.running is True  # 后台任务存活并持续重试
        await service.stop()  # 干净收尾，无异常泄漏
        assert service.running is False


class TestDisabledZeroSideEffects:
    @pytest.mark.asyncio
    async def test_enabled_false_no_requests(self, reg_env, monkeypatch):
        """cxfc.enabled=false → start 返回 False，零网络请求，无后台任务"""
        service, server = reg_env
        monkeypatch.setattr(get_settings().cxfc, "enabled", False)
        assert await service.start() is False
        await asyncio.sleep(0.15)
        assert service.running is False
        assert server.registers == [] and server.heartbeats == []
        await service.stop()  # 幂等，无异常
        assert server.unregisters == []

    @pytest.mark.asyncio
    async def test_auto_register_false_no_requests(self, reg_env, monkeypatch):
        """auto_register=false → 同样完全关闭（零请求）"""
        service, server = reg_env
        monkeypatch.setattr(get_settings().cxfc, "auto_register", False)
        assert await service.start() is False
        await asyncio.sleep(0.15)
        assert service.running is False
        assert server.registers == [] and server.heartbeats == []


class TestLifespanIntegration:
    @pytest.mark.asyncio
    async def test_lifespan_disabled_cxfc_clean_start_stop(self, monkeypatch):
        """app lifespan 冒烟：enabled=false 时启动/关闭均无 CXFC 副作用"""
        settings = get_settings()
        monkeypatch.setattr(settings.cxfc, "enabled", False)
        monkeypatch.setattr(cxfc_registration, "_service_instance", None)

        app = create_app()
        async with app.router.lifespan_context(app):
            service = cxfc_registration.get_cxfc_registration()
            assert service.running is False  # 禁用时未起后台任务
        # 关闭后单例已复位（stop_registration 清理）
        assert cxfc_registration._service_instance is None  # noqa: SLF001
