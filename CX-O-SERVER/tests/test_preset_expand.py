"""Task 4（预设展开与提示词注入，服务端）单元测试。

spec: enhance-emotion-tts-and-action-presets「per-agent 预设」Scenario 与
「动作清单上报与注入」Requirement 的服务端展开侧闭合判据：

- SubTask 4.1 情感预设展开：命中展开（text/speed/volume 来自预设）、未命中回退
  中性、不传 agent_id 向后兼容（行为与现状一致）、text 与 preset 并存 text 优先。
- SubTask 4.1b TTS 透传：_gen_instruction_full(agent_id=...) 透传、_preset_hit
  判定与 _inject_label_params 的预设参数注入（命中注入/未命中保留 config 默认）。
- SubTask 4.2 动作预设展开：命中展开、未命中透传、一层防环（不递归）、多预设
  混合、agent_id 缺失/非法安全透传。
- SubTask 4.3 提示词注入：有预设/有清单时注入内容与位置、无数据不注入、
  agent_id 缺失不注入不报错。

运行：python -m pytest tests/test_preset_expand.py -x -q
"""
import asyncio
import sys
from pathlib import Path

import pytest

# 项目根（CX-O-SERVER）加入 sys.path，保证 import server.*
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from server.services import preset_service as ps  # noqa: E402
from server.services import avatar_manifest_registry as amr  # noqa: E402
from server.services.emotion_instruction_service import (  # noqa: E402
    generate_instruction,
)
from server.services.preset_expand import expand_action_presets  # noqa: E402
from server.services.tts_service import (  # noqa: E402
    TTSService,
    _inject_label_params,
    _label_requests_preset,
    _preset_hit,
)
from server.prompt_builder import build_messages  # noqa: E402


@pytest.fixture
def presets_root(monkeypatch, tmp_path):
    """重定向预设根目录到 tmp_path 并清空模块级缓存（与 test_preset_service 同款隔离）。"""
    root = tmp_path / "presets"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(ps, "_PRESETS_ROOT", root)
    monkeypatch.setattr(ps, "_CACHE", {})
    return root


@pytest.fixture
def fresh_manifest(monkeypatch):
    """用全新 AvatarManifestRegistry 实例替换进程级单例，隔离测试。"""
    registry = amr.AvatarManifestRegistry()
    monkeypatch.setattr(amr, "_registry", registry)
    return registry


# ============================================================================ #
# SubTask 4.1：语音管线情感预设展开（generate_instruction 层）
# ============================================================================ #
class TestEmotionPresetExpansion:
    @pytest.mark.asyncio
    async def test_preset_hit_expands(self, presets_root):
        """命中展开：text/speed/volume 全部来自预设，source 沿用 llm，raw 记录引用名。"""
        ps.save_emotion_preset(
            "agentA", "元气满满", "元气活泼、声音明亮上扬", speed=1.3, volume=1.5, description="开朗问候"
        )
        reply = '正文<tts_instruction>{"preset":"元气满满"}</tts_instruction>'
        inst = await generate_instruction(reply, agent_id="agentA")
        assert inst.neutral is False
        assert inst.source == "llm"
        assert inst.text == "元气活泼、声音明亮上扬"
        assert inst.speed == pytest.approx(1.3)
        assert inst.volume == pytest.approx(1.5)
        assert "元气满满" in (inst.raw or "")

    @pytest.mark.asyncio
    async def test_preset_miss_falls_back_neutral(self, presets_root):
        """未命中：引用的预设不存在 → 按无 text 非法结构回退中性（不报错）。"""
        reply = '<tts_instruction>{"preset":"不存在的预设"}</tts_instruction>'
        inst = await generate_instruction(reply, agent_id="agentA")
        assert inst.neutral is True
        assert inst.source == "fallback"

    @pytest.mark.asyncio
    async def test_no_agent_id_backward_compat(self, presets_root):
        """向后兼容：不传 agent_id 时不查预设——preset 引用（无 text）与现状一致回退中性，
        含 text 的普通 JSON 行为不变。"""
        ps.save_emotion_preset("agentA", "元气满满", "元气活泼")
        ref_only = '<tts_instruction>{"preset":"元气满满"}</tts_instruction>'
        inst = await generate_instruction(ref_only)  # 不传 agent_id
        assert inst.neutral is True
        assert inst.source == "fallback"

        # 普通指令（不传 agent_id）行为不变
        normal = '<tts_instruction>{"text":"用开心的语气说"}</tts_instruction>'
        inst2 = await generate_instruction(normal)
        assert inst2.neutral is False
        assert inst2.text == "用开心的语气说"

    @pytest.mark.asyncio
    async def test_text_priority_over_preset(self, presets_root):
        """优先级：JSON 同时带 text 与 preset 时 text 优先（preset 不生效）。"""
        ps.save_emotion_preset("agentA", "元气满满", "元气活泼、声音明亮上扬", speed=1.3)
        reply = (
            '<tts_instruction>{"preset":"元气满满", '
            '"text":"用低沉悲伤的语气说", "speed":0.7}</tts_instruction>'
        )
        inst = await generate_instruction(reply, agent_id="agentA")
        assert inst.text == "用低沉悲伤的语气说"  # text 赢，非预设 text
        assert inst.speed == pytest.approx(0.7)  # 显式 speed 生效，非预设 speed

    @pytest.mark.asyncio
    async def test_preset_ref_in_markdown_fence(self, presets_root):
        """Markdown 围栏 JSON 形态的 preset 引用同样可展开。"""
        ps.save_emotion_preset("agentA", "温柔", "温柔轻缓的语气")
        reply = (
            '<tts_instruction>```json\n{"preset":"温柔"}\n```</tts_instruction>'
        )
        inst = await generate_instruction(reply, agent_id="agentA")
        assert inst.neutral is False
        assert inst.text == "温柔轻缓的语气"

    @pytest.mark.asyncio
    async def test_invalid_agent_id_safe_fallback(self, presets_root):
        """非法 agent_id（路径穿越形态）→ preset_service 抛错被吞掉 → 中性回退，不抛异常。"""
        reply = '<tts_instruction>{"preset":"x"}</tts_instruction>'
        inst = await generate_instruction(reply, agent_id="../evil")
        assert inst.neutral is True


# ============================================================================ #
# SubTask 4.1b：tts_service 透传与预设参数注入
# ============================================================================ #
class TestTTSPresetPassthrough:
    def _svc(self):
        return TTSService(qwen3_enabled=True, qwen3_provider=object(), emotion_instruction_enabled=True)

    @pytest.mark.asyncio
    async def test_gen_instruction_full_passes_agent_id(self, presets_root):
        """_gen_instruction_full 透传 agent_id：预设命中时 speed/volume 来自预设且非中性。"""
        ps.save_emotion_preset("agentA", "元气满满", "元气活泼", speed=1.4, volume=0.8)
        svc = self._svc()
        inst = await svc._gen_instruction_full(
            '<tts_instruction>{"preset":"元气满满"}</tts_instruction>', agent_id="agentA"
        )
        assert inst is not None
        assert inst.text == "元气活泼"
        assert inst.speed == pytest.approx(1.4)
        assert inst.volume == pytest.approx(0.8)
        assert inst.neutral is False

    @pytest.mark.asyncio
    async def test_gen_instruction_full_without_agent_id_neutral(self, presets_root):
        """不传 agent_id：preset 引用回退中性（与现状一致）。"""
        ps.save_emotion_preset("agentA", "元气满满", "元气活泼")
        svc = self._svc()
        inst = await svc._gen_instruction_full('<tts_instruction>{"preset":"元气满满"}</tts_instruction>')
        assert inst is not None
        assert inst.neutral is True

    def test_label_requests_preset_detection(self):
        """_label_requests_preset：纯 preset 引用 True；带 text False；纯文本 False。"""
        assert _label_requests_preset('<tts_instruction>{"preset":"名"}</tts_instruction>') is True
        assert (
            _label_requests_preset('<tts_instruction>{"preset":"名","text":"x"}</tts_instruction>')
            is False
        )
        assert _label_requests_preset("<tts_instruction>用开心语气说</tts_instruction>") is False
        assert _label_requests_preset("普通正文，无标签") is False

    @pytest.mark.asyncio
    async def test_preset_hit_injects_speed_volume(self, presets_root):
        """端到端参数组装：preset 命中 → _preset_hit True → 预设 speed/volume 注入 kwargs。"""
        ps.save_emotion_preset("agentA", "元气满满", "元气活泼", speed=1.4, volume=0.8)
        svc = self._svc()
        text = '<tts_instruction>{"preset":"元气满满"}</tts_instruction>今天真开心呀'
        kwargs = {"agent_id": "agentA", "speed": 1.0}  # 模拟 config 层默认 speed
        instruction = await svc._gen_instruction_full(text, agent_id=kwargs["agent_id"])
        hit = _preset_hit(kwargs, text, instruction)
        assert hit is True
        seg_kwargs = _inject_label_params(kwargs, text, instruction, preset_hit=hit)
        assert seg_kwargs["speed"] == pytest.approx(1.4)  # 预设 speed 覆盖 config 默认
        assert seg_kwargs["volume"] == pytest.approx(0.8)  # 预设 volume 注入

    @pytest.mark.asyncio
    async def test_preset_miss_keeps_config_defaults(self, presets_root):
        """preset 未命中回退中性 → 不注入，config 层默认 speed/volume 保持不变。"""
        # 预设不存在（空存储）
        svc = self._svc()
        text = '<tts_instruction>{"preset":"不存在"}</tts_instruction>今天真开心呀'
        kwargs = {"agent_id": "agentA", "speed": 1.2}
        instruction = await svc._gen_instruction_full(text, agent_id=kwargs["agent_id"])
        assert instruction is not None and instruction.neutral is True
        hit = _preset_hit(kwargs, text, instruction)
        assert hit is False
        seg_kwargs = _inject_label_params(kwargs, text, instruction, preset_hit=hit)
        assert seg_kwargs["speed"] == pytest.approx(1.2)  # config 默认不被回退值覆盖
        assert "volume" not in seg_kwargs

    @pytest.mark.asyncio
    async def test_fine_stream_path_covers_agent_id(self, presets_root):
        """细粒度流式路径：逐段 _gen_instruction_full 均透传 agent_id（首段含完整标签）。"""
        ps.save_emotion_preset("agentA", "元气满满", "元气活泼", speed=1.4)
        svc = self._svc()
        # 前置标签 + 正文（Task 1 的前置缓冲保证标签完整落入首个切片）
        tag = '<tts_instruction>{"preset":"元气满满"}</tts_instruction>'
        chunks = [tag + "今天天", "气真好呀"]

        async def token_stream():
            for c in chunks:
                yield c

        segments = [s async for s in svc.split_text_streaming(token_stream(), char_threshold=3)]
        assert tag in segments[0]
        inst = await svc._gen_instruction_full(segments[0], agent_id="agentA")
        assert inst.neutral is False
        assert inst.speed == pytest.approx(1.4)


# ============================================================================ #
# SubTask 4.2：消息下发动作预设展开（preset_expand）
# ============================================================================ #
class TestActionPresetExpansion:
    def test_expand_hit(self, presets_root):
        """命中展开：[action:预设名] → 预设 tags 依序拼接。"""
        ps.save_action_preset("agentA", "打招呼", ["[emotion:happy]", "[action:wave]"], description="开心挥手")
        text = "你好呀！[action:打招呼]今天天气不错。"
        out = expand_action_presets(text, "agentA")
        assert out == "你好呀！[emotion:happy][action:wave]今天天气不错。"

    def test_expand_miss_passthrough(self, presets_root):
        """未命中：预设不存在 → 原样透传（前端容错剥离/触发 manifest 动作）。"""
        ps.save_action_preset("agentA", "打招呼", ["[action:wave]"])
        text = "看看[action:不存在]和[action:wave]"
        assert expand_action_presets(text, "agentA") == text

    def test_one_layer_no_recursion(self, presets_root):
        """一层防环：预设 tags 内再含 [action:x] 引用原样保留，不递归展开。"""
        ps.save_action_preset("agentA", "自指", ["[action:自指]", "[action:wave]"])
        out = expand_action_presets("[action:自指]", "agentA")
        # 展开一层：得到 tags 原文，其中 [action:自指] 不再被二次展开
        assert out == "[action:自指][action:wave]"

    def test_mixed_multiple_presets(self, presets_root):
        """多预设混合：同文本多个不同引用依序各自展开。"""
        ps.save_action_preset("agentA", "打招呼", ["[emotion:happy]", "[action:wave]"])
        ps.save_action_preset("agentA", "再见", ["[action:bye]"])
        text = "[action:打招呼]中间正文[action:再见]"
        out = expand_action_presets(text, "agentA")
        assert out == "[emotion:happy][action:wave]中间正文[action:bye]"

    def test_none_agent_id_and_empty_text(self, presets_root):
        """agent_id 缺失 / 空文本 / 无引用：零开销直返。"""
        assert expand_action_presets("", "agentA") == ""
        assert expand_action_presets("[action:打招呼]", None) == "[action:打招呼]"
        assert expand_action_presets("普通文本无标签", "agentA") == "普通文本无标签"

    def test_invalid_agent_id_passthrough(self, presets_root):
        """非法 agent_id（路径穿越形态）→ 服务抛错被吞 → 原样透传不抛异常。"""
        text = "正文[action:x]结尾"
        assert expand_action_presets(text, "../evil") == text


# ============================================================================ #
# SubTask 4.3：提示词注入（prompt_builder）
# ============================================================================ #
_AGENT_BASE = {
    "id": "agentP",
    "name": "注入测试",
    "system_prompt": "你是测试人设",
    "model": "main",
    "use_memory": False,
}


class _FakeContextMgr:
    """最小上下文管理器（与 test_prompt_builder 同款）。"""

    def __init__(self):
        self._history = []

    def get_message_count(self, session_id):
        return 0

    def get_messages(self, session_id, limit=None, offset=0):
        return []


def _system_texts(messages):
    return [m.get("content", "") for m in messages if m.get("role") == "system"]


class TestPromptInjection:
    def test_injection_with_presets_and_manifest(self, presets_root, fresh_manifest):
        """有预设 + 有动作清单：注入内容含预设名/引用写法/真实动作名清单。"""
        ps.save_emotion_preset("agentP", "元气满满", "元气活泼", description="开朗问候")
        ps.save_action_preset("agentP", "打招呼", ["[action:wave]"], description="挥手")
        fresh_manifest.upsert("agentP", ["wave", "nod"])

        msgs = build_messages(_AGENT_BASE, _FakeContextMgr(), "s", "你好")
        joined = "\n".join(_system_texts(msgs))
        assert "元气满满" in joined
        assert '{"preset":"元气满满"}' in joined  # 情感预设引用写法
        assert "[action:打招呼]" in joined  # 动作预设引用写法
        assert "[action:wave] [action:nod]" in joined  # 真实可用动作名清单
        # 注入段必须位于 user 消息之前（历史/用户输入之前）
        user_idx = next(i for i, m in enumerate(msgs) if m["role"] == "user")
        inject_idx = next(
            i for i, m in enumerate(msgs) if m["role"] == "system" and "快捷指令" in m["content"]
        )
        assert inject_idx < user_idx

    def test_no_data_no_injection(self, presets_root, fresh_manifest):
        """无预设且未上报动作清单：不注入，不留空段落。"""
        msgs = build_messages(_AGENT_BASE, _FakeContextMgr(), "s", "你好")
        assert all("快捷指令" not in c for c in _system_texts(msgs))
        assert all("当前形象可用动作名" not in c for c in _system_texts(msgs))

    def test_manifest_only_injection(self, presets_root, fresh_manifest):
        """无预设但已上报动作清单：仅注入动作清单段（消除 LLM 猜动作名）。"""
        fresh_manifest.upsert("agentP", ["wave"])
        msgs = build_messages(_AGENT_BASE, _FakeContextMgr(), "s", "你好")
        joined = "\n".join(_system_texts(msgs))
        assert "[action:wave]" in joined
        assert "快捷指令" not in joined

    def test_missing_agent_id_no_injection_no_error(self, presets_root, fresh_manifest):
        """agent_id 缺失（config 无 id 且未传参）：不注入、不报错。"""
        cfg = {k: v for k, v in _AGENT_BASE.items() if k != "id"}
        msgs = build_messages(cfg, _FakeContextMgr(), "s", "你好")
        assert all("快捷指令" not in c for c in _system_texts(msgs))

    def test_realtime_voice_branch_injection(self, presets_root, fresh_manifest):
        """实时语音瘦身分支同样注入（语音是情感预设/动作的主要消费方）。"""
        ps.save_action_preset("agentP", "打招呼", ["[action:wave]"])
        fresh_manifest.upsert("agentP", ["wave"])
        msgs = build_messages(_AGENT_BASE, _FakeContextMgr(), "s", "你好", is_realtime_voice=True)
        joined = "\n".join(_system_texts(msgs))
        assert "[action:打招呼]" in joined
        assert "[action:wave]" in joined
