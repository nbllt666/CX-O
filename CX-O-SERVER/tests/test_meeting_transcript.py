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

    def test_summarize_older_merges_instead_of_overwrite(self):
        """H3 回归：二次 summarize_older 拼接保留既有摘要，不整体覆盖丢历史。"""
        transcript = MeetingTranscript(max_turns=2)
        # 第一轮：仅 2 条，无窗口外内容 → 不产生摘要
        transcript.append("user", "user", "第一条")
        transcript.append("a1", "agent", "回复一")
        assert transcript.summarize_older(max_turns=2) == ""
        # 追加至窗口外后首次压缩：产生"要点A"
        transcript.append("user", "user", "第二条")
        transcript.append("a1", "agent", "回复二")
        s1 = transcript.summarize_older(max_turns=2, summarizer=lambda e: "要点A")
        assert s1 == "要点A"
        # 再次压缩：新要点拼接在旧要点之后，既有历史不被整体覆盖
        transcript.append("user", "user", "第三条")
        transcript.append("a1", "agent", "回复三")
        s2 = transcript.summarize_older(max_turns=2, summarizer=lambda e: "要点B")
        assert "要点A" in s2, "既有 older_summary 被整体覆盖，早期历史丢失"
        assert "要点B" in s2
        assert s2.index("要点A") < s2.index("要点B")  # 新要点拼接在旧要点之后

    def test_summarize_older_length_capped_from_head(self):
        """H3 回归：older_summary 超长时从头部截断，总长受限。"""
        long_old = "旧" * 3000
        transcript = MeetingTranscript(max_turns=2, summarizer=lambda e: "新" * 2000)
        for i in range(3):          # 需要存在窗口外条目才会执行拼接压缩
            transcript.append(f"a{i}", "agent", f"msg{i}")
        transcript.older_summary = long_old  # 预置超长旧摘要
        merged = transcript.summarize_older(max_turns=2)
        assert len(merged) <= 4000
        assert merged.endswith("新" * 1000)   # 最新拼接的尾部被保留

    def test_roll_up_includes_older_summary(self):
        """H3 回归：roll_up 以伪 entry 并入 older_summary，整场记忆不缺早期历史。"""
        transcript = MeetingTranscript(max_turns=2)
        transcript.older_summary = "已压缩的早期历史"
        transcript.append("user", "user", "最新发言")
        rolled = transcript.roll_up()
        assert "已压缩的早期历史" in rolled
        assert "最新发言" in rolled
        # 空会议且无摘要仍为占位
        assert MeetingTranscript().roll_up() == "（空会议）"

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