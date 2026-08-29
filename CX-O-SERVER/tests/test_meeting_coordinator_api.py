"""MeetingCoordinator 总控 + REST 全链路测试（§10、§16、§17）。

覆盖：
① 协调器建会 / 并入 / 退出 / 结束（含记忆沉淀）
② 用户发言主流程：仲裁 → 令牌 → 转录（responder 注入）
③ REST 端点：start / state / join / leave / speak / end
④ 未装配 404 / 未启用 400 降级

运行：python -m pytest tests/test_meeting_coordinator_api.py -v
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api.routers import meeting as meeting_router
from server.core.meeting.coordinator import (
    MeetingCoordinator,
    MeetingRoomConflictError,
)
from server.core.meeting.models import AgentMember


def _make_coordinator(responder=None, **kwargs) -> MeetingCoordinator:
    """构造带注入 responder 的协调器。"""
    return MeetingCoordinator(responder=responder, relay_pause_sec=kwargs.pop("relay_pause_sec", 0.001), **kwargs)


# ================================================================ 协调器（纯 Python）
class TestCoordinatorCore:
    @pytest.mark.asyncio
    async def test_start_join_leave_end_flow(self):
        """建会→并入→退出→结束全流程 + 记忆沉淀。"""
        coord = _make_coordinator()
        room = await coord.start_meeting(
            user="用户", agents=[AgentMember("A"), AgentMember("B")], room_id="r1"
        )
        assert room.room_id == "r1"
        assert room.state.value == "in_meeting"
        assert len(room.agents) == 2

        assert await coord.join("r1", "C") is True
        assert await coord.join("r1", "C") is False  # 重复加入
        assert len(room.agents) == 3

        # 注入对话以便沉淀非空
        room.transcript.append("user", "user", "讨论一下周末")
        room.transcript.append("A", "agent", "去公园")

        assert await coord.leave("r1", "B") is True
        assert await coord.leave("r1", "B") is False  # 不在场

        summary = await coord.end_meeting("r1")
        assert "讨论一下周末" in summary
        assert "r1" not in coord.rooms

    @pytest.mark.asyncio
    async def test_process_user_speech_arbitrates_and_records(self):
        """用户发言主流程：仲裁选定发言者并写入转录。"""
        async def responder(room, agent_id, user_text):
            return f"{agent_id}回应:{user_text}"

        coord = _make_coordinator(responder=responder)
        await coord.start_meeting(
            user="用户", agents=[AgentMember("A", relevance=0.9, desire_to_speak=0.9), AgentMember("B")], room_id="r2"
        )
        result = await coord.process_user_speech("r2", "大家觉得呢")
        assert result["decision"]["speaker"] == "A"  # 发言欲最高
        assert result["turns"] and result["turns"][0]["speaker"] == "A"
        assert result["turns"][0]["audio_allowed"] is True
        # 转录含用户 + agent 两轮
        texts = [e.speaker for e in coord.get_room("r2").transcript.entries]
        assert "user" in texts and "A" in texts

    @pytest.mark.asyncio
    async def test_room_not_found_raises(self):
        """查询不存在房间抛 KeyError。"""
        coord = _make_coordinator()
        with pytest.raises(KeyError):
            await coord.process_user_speech("nope", "hi")

    @pytest.mark.asyncio
    async def test_start_same_room_conflict_raises(self):
        """H5 回归：同名房间未结束时再次开会抛业务冲突，不再静默覆盖。"""
        coord = _make_coordinator()
        await coord.start_meeting(user="用户", agents=[AgentMember("A")], room_id="conflict-1")
        first = coord.rooms["conflict-1"]
        with pytest.raises(MeetingRoomConflictError):
            await coord.start_meeting(user="用户", agents=[], room_id="conflict-1")
        # 旧房间对象未被顶替
        assert coord.rooms["conflict-1"] is first

    @pytest.mark.asyncio
    async def test_end_meeting_pops_room_then_reusable_id(self):
        """H5 回归：结束后房间移除，同名房号可重新开会。"""
        coord = _make_coordinator()
        await coord.start_meeting(user="用户", agents=[], room_id="reuse-1")
        await coord.end_meeting("reuse-1")
        room = await coord.start_meeting(user="用户", agents=[], room_id="reuse-1")
        assert room.room_id == "reuse-1"
        await coord.end_meeting("reuse-1")

    @pytest.mark.asyncio
    async def test_end_meeting_stops_danmaku_connector(self):
        """H5 回归：end_meeting 在移除房间前先停弹幕连接器（启停联动）。"""

        class _FakeConn:
            def __init__(self):
                self.stopped = False

            async def stop(self):
                self.stopped = True

        coord = _make_coordinator()
        await coord.start_meeting(user="用户", agents=[], room_id="dk-1")
        fake = _FakeConn()
        coord._connector["dk-1"] = fake
        await coord.end_meeting("dk-1")
        assert fake.stopped is True
        assert "dk-1" not in coord._connector   # 连接器登记已清理
        assert "dk-1" not in coord.rooms        # 房间随后被移除

    @pytest.mark.asyncio
    async def test_drive_turn_resets_interrupted_flag(self):
        """L 回归：本轮发言开始时复位上一轮被打断的 interrupted 标记。"""

        async def responder(room, agent_id, user_text):
            return f"{agent_id}回应:{user_text}"

        coord = _make_coordinator(responder=responder)
        await coord.start_meeting(
            user="用户",
            agents=[AgentMember("A", relevance=0.9, desire_to_speak=0.9), AgentMember("B")],
            room_id="itl-1",
        )
        coord.get_room("itl-1").get_agent("A").interrupted = True
        result = await coord.process_user_speech("itl-1", "大家觉得呢")
        assert result["decision"]["speaker"] == "A"
        assert coord.get_room("itl-1").get_agent("A").interrupted is False


# ================================================================ REST 全链路
class FakeMeetingCfg:
    enabled = True


class FakeUnifiedCfg:
    def __init__(self, enabled=True):
        self.meeting = FakeMeetingCfg() if enabled else type("MeetingCfg2", (), {"enabled": False})()


class FakeSettings:
    def __init__(self, enabled=True):
        self.config = FakeUnifiedCfg(enabled)


@pytest.fixture(autouse=True)
def _reset_globals():
    meeting_router.set_meeting_coordinator(None)
    yield
    meeting_router.set_meeting_coordinator(None)


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(meeting_router.router, prefix="/api")
    return TestClient(app)


@pytest.fixture
def patch_broadcast():
    """对广播回调打桩避免真实测试客户端无订阅者报错（no-op 即可）。"""

    return


async def _fake_responder(room, agent_id, user_text):
    return f"回复-{agent_id}"


class TestMeetingREST:
    def test_start_join_speak_end(self, client, monkeypatch):
        """REST 全链路：开会→并入→发言→状态→结束。"""
        monkeypatch.setattr(meeting_router, "get_settings", lambda: FakeSettings())
        coord = _make_coordinator(responder=_fake_responder)
        meeting_router.set_meeting_coordinator(coord)

        # 开会
        r = client.post("/api/meeting/start", json={"user": "用户", "agents": [{"agent_id": "A"}, {"agent_id": "B"}]})
        assert r.status_code == 200
        room_id = r.json()["data"]["room_id"]
        assert r.json()["success"] is True

        # 状态
        r = client.get(f"/api/meeting/{room_id}/state")
        assert r.status_code == 200
        assert r.json()["data"]["state"] == "in_meeting"

        # 并入 C
        r = client.post(f"/api/meeting/{room_id}/join", json={"agent_id": "C"})
        assert r.status_code == 200
        assert "C" in [a["agent_id"] for a in r.json()["data"]["agents"]]

        # 用户发言（开放提问 → moderator → 发言欲最高）
        r = client.post(f"/api/meeting/{room_id}/speak", json={"text": "大家觉得去哪玩"})
        assert r.status_code == 200
        body = r.json()["data"]
        assert body["turns"]  # 有 agent 响应
        assert body["decision"]["speaker"] in {"A", "B", "C"}

        # 离开 C
        r = client.post(f"/api/meeting/{room_id}/leave", json={"agent_id": "C"})
        assert r.status_code == 200

        # 结束
        r = client.post(f"/api/meeting/{room_id}/end")
        assert r.status_code == 200
        assert "summary" in r.json()["data"]

        # 结束后房间已移除 → state 404
        r = client.get(f"/api/meeting/{room_id}/state")
        assert r.status_code == 404

    def test_disabled_returns_400(self, client, monkeypatch):
        """meeting.enabled=false 时开会返回 400。"""
        monkeypatch.setattr(meeting_router, "get_settings", lambda: FakeSettings(enabled=False))
        meeting_router.set_meeting_coordinator(_make_coordinator())
        r = client.post("/api/meeting/start", json={"user": "用户", "agents": []})
        assert r.status_code == 400

    def test_unassembled_returns_404(self, client, monkeypatch):
        """coordinator 未装配时房间型端点返回 404。"""
        monkeypatch.setattr(meeting_router, "get_settings", lambda: FakeSettings())
        meeting_router.set_meeting_coordinator(None)
        r = client.get("/api/meeting/x/state")
        assert r.status_code == 404

    def test_validation_422(self, client, monkeypatch):
        """非法请求体返回 422。"""
        monkeypatch.setattr(meeting_router, "get_settings", lambda: FakeSettings())
        meeting_router.set_meeting_coordinator(_make_coordinator())
        r = client.post("/api/meeting/start", json={"agents": []})  # 缺 user
        assert r.status_code == 422

    def test_start_duplicate_room_returns_409(self, client, monkeypatch):
        """H5 回归：同名房间未结束时重复开会 → 409；结束后可复用房号。"""
        monkeypatch.setattr(meeting_router, "get_settings", lambda: FakeSettings())
        meeting_router.set_meeting_coordinator(_make_coordinator(responder=_fake_responder))
        r1 = client.post("/api/meeting/start", json={"user": "用户", "room_id": "dup-1"})
        assert r1.status_code == 200
        r2 = client.post("/api/meeting/start", json={"user": "用户", "room_id": "dup-1"})
        assert r2.status_code == 409          # 修复前为 200（静默覆盖）
        # 结束后房号可复用
        r3 = client.post("/api/meeting/dup-1/end")
        assert r3.status_code == 200
        r4 = client.post("/api/meeting/start", json={"user": "用户", "room_id": "dup-1"})
        assert r4.status_code == 200

    def test_start_param_bounds_422(self, client, monkeypatch):
        """M 回归：max_agents>=1 与 relevance/desire_to_speak∈[0,1] 校验。"""
        monkeypatch.setattr(meeting_router, "get_settings", lambda: FakeSettings())
        meeting_router.set_meeting_coordinator(_make_coordinator())
        r = client.post("/api/meeting/start", json={"user": "u", "max_agents": 0})
        assert r.status_code == 422
        r = client.post(
            "/api/meeting/start",
            json={"user": "u", "agents": [{"agent_id": "A", "relevance": 1.5}]},
        )
        assert r.status_code == 422

    def test_speak_invalid_role_422(self, client, monkeypatch):
        """M 回归：role 仅接受 user/audience，非法值 422 而非落入用户分支。"""
        monkeypatch.setattr(meeting_router, "get_settings", lambda: FakeSettings())
        meeting_router.set_meeting_coordinator(_make_coordinator(responder=_fake_responder))
        start = client.post("/api/meeting/start", json={"user": "用户"})
        room_id = start.json()["data"]["room_id"]
        r = client.post(f"/api/meeting/{room_id}/speak", json={"text": "hi", "role": "host"})
        assert r.status_code == 422

    def test_audience_toggle_and_speak(self, client, monkeypatch):
        """观众席开关端点返回房间快照含 audience_enabled；speak role=audience 写入转录。"""
        monkeypatch.setattr(meeting_router, "get_settings", lambda: FakeSettings())
        coord = _make_coordinator(responder=_fake_responder)
        meeting_router.set_meeting_coordinator(coord)

        # 开会（默认观众席关）
        r = client.post("/api/meeting/start", json={"user": "用户", "agents": [{"agent_id": "A"}]})
        assert r.status_code == 200
        room_id = r.json()["data"]["room_id"]
        assert r.json()["data"]["audience_enabled"] is False

        # toggle 开观众席 → 快照 audience_enabled=True
        r = client.post(f"/api/meeting/{room_id}/audience/toggle", json={"enabled": True})
        assert r.status_code == 200
        assert r.json()["data"]["audience_enabled"] is True

        # speak role=audience → 转录出现 audience: 条目
        r = client.post(
            f"/api/meeting/{room_id}/speak",
            json={"text": "主播好", "role": "audience", "username": "水友", "userid": "u1", "mention": "@A"},
        )
        assert r.status_code == 200
        assert r.json()["data"]["turns"]  # 有 Agent 回应

        r = client.get(f"/api/meeting/{room_id}/state")
        recent = r.json()["data"]["recent_messages"]
        assert any(m["role"] == "audience" and m["speaker"] == "audience:水友" for m in recent)

        # toggle 关观众席
        r = client.post(f"/api/meeting/{room_id}/audience/toggle", json={"enabled": False})
        assert r.status_code == 200
        assert r.json()["data"]["audience_enabled"] is False


# ================================================================ 上下文回写异步化（_ingest_context）
class _FakeCtxAsync:
    """带 add_message_async 变体的假 ContextManager（对齐真实实现的 async 变体）。"""

    def __init__(self):
        self.calls = []

    async def add_message_async(self, room_id, role, content):
        self.calls.append(("async", room_id, role, content))


class _FakeCtxSync:
    """仅同步 add_message 的假 ContextManager（降级路径）。"""

    def __init__(self):
        self.calls = []

    def add_message(self, room_id, role, content):
        self.calls.append(("sync", room_id, role, content))


class TestIngestContextAsync:
    @pytest.mark.asyncio
    async def test_ingest_prefers_async_variant(self):
        """_ingest_context 优先调用 add_message_async，内容含会议记录标记。"""
        cm = _FakeCtxAsync()
        coord = _make_coordinator(context_manager=cm)
        room = await coord.start_meeting(user="用户", agents=[AgentMember("A")], room_id="ctx-a1")
        room.transcript.append("user", "user", "聊聊天气")
        await coord._ingest_context(room)
        assert cm.calls, "应调用 add_message_async"
        kind, room_id, role, content = cm.calls[0]
        assert kind == "async"
        assert room_id == "ctx-a1"
        assert role == "system"
        assert "[会议记录]" in content and "聊聊天气" in content

    @pytest.mark.asyncio
    async def test_ingest_falls_back_to_threaded_sync_add(self):
        """无 async 变体时同步 add_message 经线程池调用，参数一致。"""
        cm = _FakeCtxSync()
        coord = _make_coordinator(context_manager=cm)
        await coord.start_meeting(user="用户", agents=[AgentMember("A")], room_id="ctx-s1")
        await coord._ingest_context(coord.get_room("ctx-s1"))
        assert cm.calls and cm.calls[0][0] == "sync"
        assert cm.calls[0][1] == "ctx-s1"
        assert cm.calls[0][2] == "system"

    @pytest.mark.asyncio
    async def test_ingest_without_cm_is_noop(self):
        """未装配 context_manager 时静默返回不抛错。"""
        coord = _make_coordinator()
        await coord.start_meeting(user="用户", agents=[], room_id="ctx-n1")
        await coord._ingest_context(coord.get_room("ctx-n1"))  # 不抛异常即通过