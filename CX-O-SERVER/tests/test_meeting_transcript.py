"""MeetingTranscript 会议记录单元测试（§8）。

覆盖：append 结构、render_context（最近 N 轮 + 更早摘要）、summarize_older、roll_up 沉淀。
运行：python -m pytest tests/test_meeting_transcript.py -v
"""
from server.core.meeting.transcript import MeetingTranscript


def _fill(transcript, n_user, n_agent, prefix="t"):
    """填充用户与 agent 交替发言，返回内容列表。"""
    spoken = []
    for i in range(n_user):
        transcript.append("user", "user", f"{prefix}用户{i}")
        spoken.append(f"{prefix}用户{i}")
        for j in range(n_agent):
            transcript.append(f"agent_{j}", "agent", f"agent_{j} 说{i}")
            spoken.append(f"agent_{j} 说{i}")
    return spoken


class TestMeetingTranscript:
    def test_append_structure(self):
        """追加条目结构含 speaker/role/text/ts。"""
        transcript = MeetingTranscript()
        entry = transcript.append("user", "user", "周末去哪玩？")
        assert entry.speaker == "user"
        assert entry.role == "user"
        assert entry.text == "周末去哪玩？"
        assert entry.ts
        assert len(transcript) == 1

    def test_render_context_recent_only(self):
        """render_context 只含最近 N 轮全量。"""
        transcript = MeetingTranscript(max_turns=4)
        _fill(transcript, 3, 1)  # 3 用户 + 3 agent = 6 条
        ctx = transcript.render_context(max_turns=4)
        # 最近 4 条：用户2, agent_0说2, 用户2..., 依序
        assert "用户0" not in ctx  # 早期条目已被窗口裁掉
        assert "agent_0 说2" in ctx
        assert "用户2" in ctx

    def test_summarize_older_compacts(self):
        """summarize_older 把窗口外早期条目压缩为摘要。"""
        transcript = MeetingTranscript(max_turns=4)
        _fill(transcript, 3, 1)
        # 显式摘要器：压缩为固定文本
        summary = transcript.summarize_older(max_turns=4, summarizer=lambda entries: "早期要点")
        assert summary == "早期要点"
        # render_context 现在 = 摘要 + 最近窗口
        ctx = transcript.render_context(max_turns=4)
        assert "早期要点" in ctx
        assert transcript.older_summary == "早期要点"

    def test_roll_up_full_meeting(self):
        """roll_up 沉淀整场会议为记忆文本。"""
        transcript = MeetingTranscript()
        _fill(transcript, 2, 1)
        rolled = transcript.roll_up()
        assert "用户0" in rolled
        assert "agent_0 说0" in rolled

    def test_roll_up_empty(self):
        """空会议 roll_up 返回占位。"""
        transcript = MeetingTranscript()
        assert transcript.roll_up() == "（空会议）"

    def test_default_summarizer_joins(self):
        """默认摘要器拼接说话者+内容。"""
        transcript = MeetingTranscript(max_turns=0)
        transcript.append("user", "user", "你好")
        rolled = transcript.roll_up()
        assert "user: 你好" in rolled