"""
音频处理器 (ASR/TTS)
"""
from __future__ import annotations

import base64
import logging
import asyncio
import time
from typing import TYPE_CHECKING, Optional

from server.protocol.message import create_response, create_error, create_stream
from server.protocol.actions import ASRActions, TTSActions, EmotionActions, EffectActions, VoiceActions
from server.services.emotion_parser import get_supported_emotions, extract_emotions_with_text
from server.services.effect_parser import EffectParser
# 模块级导入实时语音单例访问器：vad_processor 无对 audio 的反向依赖（无循环导入），
# 消除双流式/流式 ASR handler 每帧重复执行函数级 import（16.7 帧/s 热路径）。
from server.services.vad_processor import get_audio_stream_processor

if TYPE_CHECKING:
    from server.core.websocket.manager import WebSocketManager
    from server.services.asr_service import ASRService
    from server.services.tts_service import TTSService

logger = logging.getLogger(__name__)

_tts_playing_clients: set = set()
_tts_playing_lock = asyncio.Lock()

# 【停顿续接确认窗口】Feature B 的 is_final 由 VAD speech_end 驱动，长句内部停顿
# 也会产生中段 final。若立即 ensure_reply，会把"还没说完的停顿"当"说完"触发回复
# （停顿即说完误判，长句被腰斩回复）。路由侧延迟该窗口：用户停顿后继续说时，新
# partial 已启动主管线（基于完整文本），ensure_reply 因 _has_triggered_this_utterance
# 守卫 no-op；确认说完后才兜底启动。仅影响 Feature B 兜底路径（主管线未启动时），
# 不引入 partial 驱动主管线的额外延迟。
REPLY_CONFIRM_S = 0.5


async def route_agent_interrupt_result(session, res: dict) -> None:
    """按打断/回复独立标签路由 AI 插话判定结果（标签解耦核心路由）。

    - should_interrupt=True（真打断）：→ interrupt_and_reply（停 TTS/让位，带内容则直接播报）
    - should_reply=True 且未打断（Feature B 回复）：→ 停顿续接确认后 ensure_reply
      （主管线产出回复，不打断；窗口内用户继续说则 no-op，防"停顿即说完"误判）
    - 二者皆真（LLM INTERRUPT 带内容）：先打断再播 reply_content
    """
    if res.get("should_interrupt"):
        await session.interrupt_and_reply(res.get("reply_content", ""))
    elif res.get("should_reply"):
        # 【停顿续接确认】见 REPLY_CONFIRM_S 注释：延迟窗口让"停顿后继续说"的
        # partial 先启动主管线，ensure_reply 随后因已触发守卫 no-op。
        try:
            await asyncio.sleep(REPLY_CONFIRM_S)
            await session.ensure_reply()
        except asyncio.CancelledError:
            # 任务已取消（连接断开/会话终止），无需继续 ensure_reply 兜底回复
            return


def _is_continuation(prev: str, cur: str) -> bool:
    """判断 cur 是否为 prev 的延续（同句复现 / 累积扩展）。

    SenseVoice 流式对同一语音段会连续复现相同文本或递增扩展
    （如 '你好' → '你好。'，'今天' → '今天天'），而音频起始边缘的幻觉
    （如 'Yeah。'）只闪现一次即被后续真实文本替换、与前后无延续关系。
    据此用"文本延续性"而非字符类型/长度区分真实输入与边缘幻觉：
    真实输入（含 '好'、'how are you' 等短句/英文/单字）会被下一帧复现或
    延续而确认；孤立无延续的片段判为幻觉丢弃，不误杀任何真实内容。
    """
    prev, cur = prev.strip(), cur.strip()
    if not prev or not cur:
        return False
    return cur.startswith(prev) or prev.startswith(cur)

# 双流式会话存储：client_id -> DualStreamSession
# 每个客户端独立维护流水线状态，避免跨客户端干扰
_dual_stream_sessions: dict[str, "DualStreamSession"] = {}


async def set_tts_playing(client_id: str, playing: bool):
    """更新指定客户端的 TTS 播放状态，并将聚合结果同步到 ASR 打断模块。"""
    from server.services.asr_interrupt import get_asr_interrupt_module
    interrupt_module = get_asr_interrupt_module()

    async with _tts_playing_lock:
        if playing:
            _tts_playing_clients.add(client_id)
        else:
            _tts_playing_clients.discard(client_id)

        has_tts_playing = len(_tts_playing_clients) > 0

    interrupt_module.set_tts_playing(has_tts_playing)


async def cleanup_dual_stream_session(client_id: str) -> None:
    """WS 断开时清理双流式会话，取消正在运行的 LLM+TTS 流水线

    根治孤儿会话泄漏：客户端断开后若不清理，pipeline 会持续占用
    LLM/TTS 资源并向空连接推流，多轮累积导致 TTS 服务被并发打爆。
    """
    session = _dual_stream_sessions.pop(client_id, None)
    if session:
        try:
            await session.finish()
            logger.info(f"WS 断开，已清理双流式会话: client_id={client_id}")
        except Exception as e:
            logger.warning(f"清理双流式会话失败 {client_id}: {e}")


class DualStreamSession:
    """双流式语音会话状态管理器（per-client）

    核心设计：ASR Partial Result 是主驱动器，VAD 仅作兜底。
    - Partial Result 立即触发 LLM Speculative Prefill，省去等待 VAD on_end 的 ~500ms 静默判定
    - VAD on_end 仅修正 Final 文本用于上下文记录，不重启已由 Partial 启动的 LLM 流程
    - 用户开口（VAD speech_start）时立即打断 TTS 播放，实现毫秒级全双工打断

    上下文整合策略（避免上下文爆炸）：
    - 未触发 LLM 回复的 utterance 合并到 _pending_user_text
    - 触发回复的 utterance 记为完整轮次（user+assistant 对）
    - 上下文记录数 = 实际对话轮次数，不因 Partial 数量增加而膨胀
    """

    def __init__(
        self,
        client_id: str,
        agent_id: str,
        request_id: str,
        manager: "WebSocketManager",
        tts_service: "TTSService",
        ref_audio_path: Optional[str] = None,
        ref_text: Optional[str] = None,
        # Qwen3 统一编排：参考音频资产 ID（ref_ 前缀）与多参考音频列表
        ref_asset_id: Optional[str] = None,
        refs: Optional[list] = None,
    ):
        self.client_id = client_id
        self.agent_id = agent_id
        self.request_id = request_id
        self.manager = manager
        self.tts_service = tts_service
        self._ref_audio_path = ref_audio_path
        self._ref_text = ref_text
        # Qwen3 统一编排状态
        self._ref_asset_id = ref_asset_id
        self._refs = refs

        # 上下文管理 session_id（与 chat.py 保持一致）
        self.session_id = f"agent-{agent_id}"

        # ---- 上下文整合状态 ----
        # 累积未触发 LLM 回复的 utterance 文本，供下一轮合并为单条 user 上下文
        self._pending_user_text: str = ""
        # 当前触发 LLM 的用户文本（Partial 驱动）
        self._current_user_text: str = ""
        # 当前 LLM 回复累积文本
        self._current_assistant_text: str = ""
        # VAD on_end 修正后的 Final 文本（比 Partial 更准确）
        self._final_user_text: str = ""

        # ---- 流水线状态 ----
        self._pipeline_task: Optional[asyncio.Task] = None
        self._tts_chunk_index: int = 0
        # 当前 utterance 是否已触发 LLM（避免同一 utterance 内重复触发）
        self._has_triggered_this_utterance: bool = False
        # 当前 utterance 是否已由 LLM 插话打断（interrupt_and_reply 置位，
        # 供 speech_end_fallback 抑制 VAD speech_end 兜底触发、避免双路 TTS 并发）
        self._agent_interrupt_triggered: bool = False
        # 流水线是否正常完成（区分完成 vs 被打断）
        self._pipeline_completed: bool = False
        self._is_active: bool = True

        # 触发阈值：Partial 文本达到此字数才触发 LLM Speculative Prefill
        # 设为 2：用户说出 2 个字即触发，省去等待 VAD on_end 的 ~500ms 静默判定
        self._trigger_char_threshold: int = 2

        # ---- 首帧延续性确认状态（边缘幻觉防护）----
        # _pending_partial: 未确认的候选 partial（延迟一拍等下一帧确认）
        self._pending_partial: str = ""
        # _partial_confirmed: 当前 utterance 是否已确认首帧真实；确认后直通，
        # 后续 partial 不再做延续性校验，避免对稳定流引入额外延迟。
        self._partial_confirmed: bool = False

        # ---- VAD 打断保护状态 ----
        # 用户语音结束时间（VAD speech_end 记录）。语音结束后短窗口内的 speech_start
        # 多为 VAD 处理用户语音尾部残留帧的滞后误判（voice_e2e 实测：TTS 刚启动即被
        # 假 speech_start 打断，回复输出为 0B）。该窗口内不打断，覆盖残留处理滞后；
        # 窗口外（用户真正再次开口）仍正常打断。
        self._last_speech_end_time: float = 0.0
        # speech_end 后忽略 speech_start 打断的保护窗口（毫秒）
        self._speech_end_guard_ms: float = 1000.0

        # 后台任务引用集合：防止 _finalize_turn / _maybe_agent_interrupt 等长任务
        # 被 GC 提前回收（asyncio 不持有裸 create_task 的引用）。
        self._background_tasks: set = set()

    def _track_background_task(self, task: asyncio.Task) -> asyncio.Task:
        """追踪后台任务，防止被 GC 回收；任务完成后自动从集合中移除。"""
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return task

    async def on_vad_speech_start(self) -> None:
        """VAD 检测到用户开始说话 —— 全双工打断触发点

        用户开口即立即停止 TTS 播放，无需等待 ASR 识别出完整文本，
        省去 ASR 识别延迟（~200ms），实现毫秒级全双工打断。
        """
        # 仅当本客户端 TTS 确实在播放（Agent 正在说话）时才打断流水线。
        # LLM 预填充/尚未出声阶段（_tts_playing_clients 未标记）触发打断会误伤
        # 刚启动的回复——VAD 对语音尾部/静音边缘的假 speech_start 实测会取消
        # 尚未输出的回复，导致双流无 TTS 输出（2026-08-19 复现）。
        if self.client_id in _tts_playing_clients:
            # 打断保护窗口：VAD 处理用户语音尾部残留帧存在滞后，用户语音结束
            # （speech_end）后短窗口内的 speech_start 多为残留误判，跳过打断，
            # 避免 TTS 刚启动即被取消（voice_e2e 实测回复 0B）。
            in_guard_window = (
                self._last_speech_end_time
                and (time.monotonic() - self._last_speech_end_time) * 1000 < self._speech_end_guard_ms
            )
            if not in_guard_window and self._pipeline_task and not self._pipeline_task.done():
                await self._interrupt_pipeline()
        # 重置当前 utterance 的触发标志，允许新 utterance 触发 LLM
        self._has_triggered_this_utterance = False
        # 重置 LLM 插话打断标记（新 utterance 开始，speech_end_fallback 互斥失效）
        self._agent_interrupt_triggered = False
        # 重置首帧延续性确认状态（新 utterance 重新做边缘幻觉确认）
        self._pending_partial = ""
        self._partial_confirmed = False

    async def on_partial_result(self, asr_result: dict) -> None:
        """ASR Partial Result 主驱动：立即触发 LLM Speculative Prefill

        这是双流式模式的核心：Partial Result（is_final=False）产出即触发 LLM，
        不等 VAD on_end 的 500ms 静默判定，可省下约 500ms 端到端延迟。
        每个 utterance 仅触发一次（由 _has_triggered_this_utterance 控制），
        避免同一 utterance 内多个 Partial 重复触发 LLM。

        边缘幻觉防护（首帧延续性确认，2026-08-19 重构）：
        音频起始边缘的首个 partial 可能是 SenseVoice 幻觉（如 'Yeah。'），
        但 'Yeah。'/'二？'/'好'/'how are you' 也可能是真实输入，不能按
        字符类型/长度一刀切。改为延续性确认：未确认的候选 partial 延迟一拍，
        若下一帧延续/复现它则确认为真实输入（推送+触发），否则丢弃
        （幻觉只闪现一次即被真实内容替换、无延续关系）。已确认后直通，
        对稳定流不引入额外延迟。
        """
        text = asr_result.get("text", "").strip()
        # 诊断日志：确认 on_partial_result 被调用及其参数
        logger.debug("[DIAG-PARTIAL] on_partial_result called, text='%s' (len=%d), is_final=%s, has_triggered=%s, confirmed=%s, threshold=%s", text, len(text), asr_result.get('is_final'), self._has_triggered_this_utterance, self._partial_confirmed, self._trigger_char_threshold)
        if not text:
            return

        # ---- 首帧延续性确认（仅未确认时启用，已确认后直通）----
        if not self._partial_confirmed:
            if not self._pending_partial:
                # 尚无候选：暂存当前帧，等下一帧确认；不推送前端、不触发
                self._pending_partial = text
                logger.debug("[DIAG-PARTIAL] cache candidate partial for confirmation: %r", text)
                return
            if not _is_continuation(self._pending_partial, text):
                # 候选未被延续/复现 → 判定为音频边缘幻觉，丢弃（不推送、不触发）
                logger.debug("[DIAG-PARTIAL] drop unconfirmed edge partial: %r (replaced by %r)", self._pending_partial, text)
                self._pending_partial = text
                return
            # 候选被下一帧延续/复现 → 确认为真实输入，用较完整的一帧继续
            prev = self._pending_partial
            self._partial_confirmed = True
            self._pending_partial = ""
            text = text if len(text) >= len(prev) else prev
            logger.debug("[DIAG-PARTIAL] confirmed real input: %r (continued by %r)", prev, text)

        # 推送 Partial 文本给前端（实时显示用户正在说什么）
        logger.debug("[DIAG-PARTIAL] before _send_partial")
        await self._send_partial(text)
        logger.debug("[DIAG-PARTIAL] after _send_partial")

        # 同一 utterance 内仅触发一次 LLM，避免 Partial 增量导致重复 Prefill
        if self._has_triggered_this_utterance:
            return

        # 触发条件：文本达到阈值字数（2 字），避免单字误触发
        if len(text) < self._trigger_char_threshold:
            return

        self._has_triggered_this_utterance = True

        # 上下文整合：合并未触发 LLM 的 pending 文本 + 当前 Partial 文本
        # 这样前几句未触发回复的话不会丢失，也不会膨胀上下文轮次数
        if self._pending_user_text:
            full_user_text = f"{self._pending_user_text} {text}"
            self._pending_user_text = ""
        else:
            full_user_text = text

        self._current_user_text = full_user_text

        # 通知前端 LLM Prefill 已启动（前端可显示"正在思考"状态）
        logger.debug("[DIAG-PARTIAL] before _send_prefill_started")
        await self._send_prefill_started(full_user_text)
        logger.debug("[DIAG-PARTIAL] after _send_prefill_started, creating pipeline task")

        # 异步启动 LLM → TextSmoother → TTS 流水线，不阻塞音频帧接收
        self._pipeline_task = asyncio.create_task(self._run_pipeline(full_user_text))

    async def on_vad_speech_end(self, asr_result: Optional[dict]) -> None:
        """VAD 兜底：修正 Final 文本并兜底触发未启动的 pipeline

        双流式模式下主流程由 ASR Partial Result 驱动，此处做收尾：
        - 已触发：用 VAD on_end 后的 Final 文本修正上下文记录（比 Partial 更准确）
        - 未触发：兜底触发 pipeline（2026-08-19 新增）
          实测 SenseVoice 对短音频常只产出 final（无 partial），且 final 可能在
          VAD speech_end **之前**到达（此时 on_final_result 因 is_speaking=True
          判定"final 迟到"而拦截触发，仅累积 pending）。若不在此兜底，该 utterance
          的 pipeline 永不启动（无回复，voice_e2e 偶发复现）。VAD speech_end 是
          语音结束的可靠信号，据此用 pending+final 兜底触发。
        """
        final_text = ""
        if asr_result:
            final_text = asr_result.get("text", "").strip()

        # 记录语音结束时间：供 on_vad_speech_start 的打断保护窗口使用
        self._last_speech_end_time = time.monotonic()

        if self._has_triggered_this_utterance:
            # 当前 utterance 已触发 LLM：用 Final 文本修正上下文记录
            # Final 文本比 Partial 更准确（VAD on_end 后 ASR 有完整上下文）
            self._final_user_text = final_text or self._current_user_text

            # 调度后台任务：等待流水线完成后记录上下文
            # 不阻塞音频帧接收，流水线可能仍在生成 TTS
            pipeline_task = self._pipeline_task
            if pipeline_task is not None:
                self._track_background_task(
                    asyncio.create_task(self._finalize_turn(pipeline_task))
                )
            return

        # ---- 未触发：VAD speech_end 兜底触发 ----
        # 若本 utterance 已由 LLM 插话打断（interrupt_and_reply 置位）且配置启用
        # speech_end_fallback，则跳过 VAD 兜底触发：插话回应（_play_reply）已作为
        # 新 pipeline 在播，此刻再兜底触发主 pipeline 会形成双路 TTS 并发。此互斥
        # 仅当 LLM 插话打断确实发生时生效，普通场景兜底行为与现状一致。
        if self._agent_interrupt_triggered:
            from server.services.agent_interrupt_user import get_agent_interrupt_module
            if get_agent_interrupt_module().speech_end_fallback:
                return

        # final 若已在 speech_end 前到达，会被 on_final_result 以 is_speaking=True
        # 累积进 pending；此处合并 pending + final 触发（文本过短则留待合并）。
        candidate = final_text or self._pending_user_text
        if len(candidate) < self._trigger_char_threshold:
            return

        if self._pending_user_text and final_text and final_text not in self._pending_user_text:
            full_user_text = f"{self._pending_user_text} {final_text}"
        elif final_text:
            full_user_text = final_text
        else:
            full_user_text = self._pending_user_text
        self._pending_user_text = ""

        self._has_triggered_this_utterance = True
        self._current_user_text = full_user_text
        self._final_user_text = final_text or full_user_text

        logger.debug("[DIAG-PARTIAL] on_vad_speech_end fallback trigger, text='%s'", full_user_text)
        await self._send_prefill_started(full_user_text)
        self._pipeline_task = asyncio.create_task(self._run_pipeline(full_user_text))
        self._track_background_task(
            asyncio.create_task(self._finalize_turn(self._pipeline_task))
        )

        # 注意：不在此处重置 _has_triggered_this_utterance。
        # final 结果在 speech_end 之后才到达，on_final_result 需要凭此 flag
        # 判断该 utterance 是否已触发 pipeline；flag 由下一次 speech_start 重置。

    async def on_final_result(self, asr_result: dict, is_speaking: bool = False) -> None:
        """ASR Final Result 兜底驱动：短语音无 partial 时的 pipeline 触发入口

        VAD 门控下语音段常被切到 <1.5s，短句可能全程无 partial（说话即结束），
        若仅依赖 on_partial_result 触发，短语音永远得不到 LLM 响应（2026-08-05
        实测：4 轮测试 pipeline 零启动）。此处兜底：
        - 已触发：仅修正 Final 文本用于上下文记录（比 Partial 准确）
        - 未触发且文本达阈值：合并 pending + final 直接触发 pipeline
        - 未触发且文本过短：累积 pending，留待下一 utterance 合并
        - is_speaking=True（final 迟到，用户已开说下一句）：仅合并 pending，
          不得触发过时 pipeline 抢话（2026-08-05 实测 pending 重复合并复现）
        """
        text = asr_result.get("text", "").strip()
        if not text:
            return

        # 推送 Final 转写文本给前端（语音识别的最终确认）
        await self._send_partial(text, is_final=True)

        if self._has_triggered_this_utterance:
            # 已由 Partial 触发：仅修正 Final 文本
            self._final_user_text = text
            return

        # 未触发：文本过短（<2 字）或 final 迟到（用户已在说下一句），
        # 均只累积 pending，不单独触发
        if len(text) < self._trigger_char_threshold or is_speaking:
            if self._pending_user_text:
                self._pending_user_text = f"{self._pending_user_text} {text}"
            else:
                self._pending_user_text = text
            return

        # 兜底触发：合并 pending + final，直接启动 pipeline
        self._has_triggered_this_utterance = True
        if self._pending_user_text:
            full_user_text = f"{self._pending_user_text} {text}"
            self._pending_user_text = ""
        else:
            full_user_text = text

        self._current_user_text = full_user_text
        self._final_user_text = text  # Final 即最准确文本，直接用于上下文记录

        logger.debug("[DIAG-PARTIAL] on_final_result fallback trigger, text='%s'", full_user_text)
        await self._send_prefill_started(full_user_text)

        # 异步启动 LLM → TextSmoother → TTS 流水线，不阻塞音频帧接收
        self._pipeline_task = asyncio.create_task(self._run_pipeline(full_user_text))
        # 兜底路径 speech_end 已过，无人调度 _finalize_turn，此处自行调度记录上下文
        self._track_background_task(
            asyncio.create_task(self._finalize_turn(self._pipeline_task))
        )

    async def ensure_reply(self) -> None:
        """回复兜底（Feature B should_reply=True 专用）：确保主管线产出回复。

        与 interrupt_and_reply 解耦：**不** cancel 主管线、**不**置
        _agent_interrupt_triggered、**不**发送 voice.interrupted——回复由主
        LLM 管线（LLM→TextSmoother→TTS）产出，保持 low-latency partial 驱动路径。
        - 主管线已启动（_has_triggered_this_utterance=True）：no-op，防重复管线
        - 未启动且候选文本达阈值：启动主管线（合并 pending/final 文本）
        """
        if self._has_triggered_this_utterance:
            return
        candidate = self._current_user_text or self._pending_user_text or self._final_user_text
        if not candidate or len(candidate) < self._trigger_char_threshold:
            return
        self._has_triggered_this_utterance = True
        self._current_user_text = candidate
        self._final_user_text = candidate
        await self._send_prefill_started(candidate)
        self._pipeline_task = asyncio.create_task(self._run_pipeline(candidate))
        self._track_background_task(
            asyncio.create_task(self._finalize_turn(self._pipeline_task))
        )

    async def _run_pipeline(self, user_text: str) -> None:
        """运行 LLM → TextSmoother → TTS 全链路流水线

        数据流向：
          LLM stream_chat() → TextSmoother.smooth() → TTS synthesize_stream_fine()
          → voice.tts_chunk 流式返回前端

        每一环都是 async generator，形成流水线并行：
        LLM 吐出第一个 token 即开始平滑缓冲，平滑缓冲输出第一个词组即开始 TTS 合成，
        TTS 合成出第一个音频块即推送给前端。全链路首包音频延迟 < 300ms。
        """
        try:
            # 延迟导入避免循环依赖
            from server.chat_helpers import (
                get_agent_config,
                get_llm_client_for_agent,
                retrieve_memory_context,
            )
            from server.prompt_builder import build_messages
            from server.dependencies import get_context_manager, get_memory_manager
            from server.services.text_smoother import TextSmoother

            # 1. 获取 Agent 配置
            agent_config = get_agent_config(self.agent_id)
            if not agent_config:
                await self.manager.send_message(self.client_id, create_error(
                    request_id=self.request_id,
                    action=VoiceActions.DUAL_STREAM,
                    code="AGENT_NOT_FOUND",
                    message=f"Agent '{self.agent_id}' 不存在"
                ))
                return

            context_mgr = get_context_manager()

            # 2. 记忆策略：voice_memory_fast 决定「每轮预检索」还是「仅工具触发」
            #   - 默认(auto，voice_memory_fast=False)：每轮调用 retrieve_memory_context
            #     （MemoryRouter 完整检索）预注入记忆——记忆强、首字微延迟（用户已裁定接受）。
            #   - 快速模式(fast，voice_memory_fast=True)：不预检索，LLM 通过记忆工具按需召回，
            #     省去每轮 Embedding 检索与大量记忆 token；代价是仅当用户话题触及历史时才触发检索。
            fast_mode = bool(agent_config.get("voice_memory_fast", False))
            memory_context = None
            if not fast_mode:
                try:
                    memory_mgr = get_memory_manager()
                    if memory_mgr is not None:
                        memory_context = await retrieve_memory_context(
                            agent_config, memory_mgr, user_text, self.session_id
                        )
                except Exception as _mem_e:
                    logger.warning(f"双流式记忆检索失败，降级为无记忆: {_mem_e}")

            # 3. 构建 messages（实时语音模式）
            # 保留：核心 System Prompt(padded) + 记忆(auto 预注入) + 最近 2 轮对话
            # 跳过：重型隐藏提示词、技能注入（控制 token 膨胀，维持语音低延迟）
            messages = build_messages(
                agent_config, context_mgr, self.session_id,
                user_text, memory_context=memory_context, is_realtime_voice=True,
            )

            # 4. 获取 LLM client
            llm = get_llm_client_for_agent(agent_config)

            # 5. LLM 流式输出（vLLM 90 tokens/s, TTFT ~80ms）
            # 实时语音回复应为短口语（2~3 句），max_tokens 限制 150：
            # 阻断多轮上下文污染后 LLM 进入长文总结模式（实测单轮 370+ chunk），
            # 避免单 pipeline 长时间占用 TTS 导致并发排队、端到端延迟暴涨
            # 语音注入与普通模式一致的完整工具（get_tools_for_agent），使语音链路具备
            # 相同的工具能力；工具调用经 _voice_stream_with_tools 执行并二次生成文本。
            # 两种模式的工具能力相同，差异仅在记忆获取方式：
            #   - auto：每轮预注入记忆 + 也可工具调用
            #   - fast：不预检索，靠工具按需召回
            llm_stream = llm.stream_chat(
                messages=messages,
                temperature=agent_config.get("temperature", 0.7),
                max_tokens=min(agent_config.get("max_tokens", 4096), 150),
                tools=self._resolve_voice_tools(),
            )
            llm_stream = self._voice_stream_with_tools(
                llm_stream, messages, llm,
                temperature=agent_config.get("temperature", 0.7),
                max_tokens=min(agent_config.get("max_tokens", 4096), 150),
            )

            # 6. TextSmoother 平滑缓冲（30ms 滑动窗口聚合碎片 Token）
            # LLM 吐出的 token 往往只有 1~2 字，直接喂 TTS 会导致发音诡异。
            # TextSmoother 以 30ms 窗口聚合为 3~5 字词组块，用 ~40ms 延迟换取音质提升。
            # ~40ms 远小于 300ms 总预算，且 TTS 合成与播放可流水线并行，用户无感。
            # C4 P50<600ms 优化：window_ms 40 → 30（TextSmoother 内部 clamp 到 30~50ms）
            # 节省 ~10ms 首块输出延迟
            # C4 P50<400ms 三轮激进优化：char_threshold 3 → 2（绕过 TextSmoother 默认硬下限 3）
            # 让 LLM 吐 2 字即触发 TTS，省额外 ~30-50ms
            # 注意：2 字切片可能影响音质，TextSmoother 的 30ms 窗口会聚合部分碎片
            smoothed_stream = TextSmoother.smooth(
                llm_stream, window_ms=30, char_threshold=2
            )

            # 7. TTS 细粒度流式合成（边收边切边合成）
            # synthesize_stream_fine 接受 token 流，4 字即切片送 TTS，
            # 不必等整句，首包音频延迟压缩数百毫秒
            await set_tts_playing(self.client_id, True)
            self._tts_chunk_index = 0
            self._current_assistant_text = ""

            # 构建 Qwen3 统一编排合成参数（参考音频资产/路径）
            tts_kwargs: dict = self._build_tts_kwargs()

            async for chunk in self.tts_service.synthesize_stream_fine(
                token_stream=smoothed_stream,
                # char_threshold 3→2（2026-08-18 WS 全链路 <800ms 优化）：首个 TTS 片段
                # 在 2 字即触发，减少 LLM 生成等待 ~10-20ms。仅影响首片段触发时机，
                # 后续片段仍按标点/窗口聚合，音质不受影响。
                char_threshold=2,
                **tts_kwargs
            ):
                # 流结束标记
                if chunk.get("is_final"):
                    await self._send_tts_chunk(chunk, is_final=True)
                    break

                # 累积助手回复文本（用于上下文记录）
                text_segment = chunk.get("text_segment", "")
                if text_segment:
                    self._current_assistant_text += text_segment

                # 有音频数据则推送给前端，不等整句合成完毕
                audio_data = chunk.get("audio_data")
                if audio_data:
                    await self._send_tts_chunk(chunk, is_final=False)

            self._pipeline_completed = True

        except asyncio.CancelledError:
            # 被打断（用户开口触发全双工打断）：将当前用户文本累积到 pending
            # 供下一轮合并，不丢失用户已说的内容
            self._pipeline_completed = False
            if user_text:
                if self._pending_user_text:
                    self._pending_user_text = f"{self._pending_user_text} {user_text}"
                else:
                    self._pending_user_text = user_text
            raise
        except Exception as e:
            logger.error(f"双流式流水线错误: {e}", exc_info=True)
            self._pipeline_completed = False
            await self.manager.send_message(self.client_id, create_error(
                request_id=self.request_id,
                action=VoiceActions.DUAL_STREAM,
                code="PIPELINE_ERROR",
                message=str(e)
            ))
        finally:
            try:
                await set_tts_playing(self.client_id, False)
            except Exception as e:
                logger.error(f"重置 TTS 播放状态失败: {e}")

    def _resolve_voice_tools(self) -> Optional[list]:
        """双流式语音的工具集：与普通模式一致的完整工具（get_tools_for_agent）。

        直接透传全部工具（内置 + 主模型工具），使语音链路具备与普通聊天相同的
        工具能力（记忆召回 / 搜索 / 助手 / 插件等）。工具调用经 _voice_stream_with_tools
        执行并二次生成。失败时返回 None（等价于不注入工具，静默降级）。
        """
        from server.chat_helpers import get_tools_for_agent

        try:
            return get_tools_for_agent() or None
        except Exception as e:
            logger.warning(f"双流式工具解析失败: {e}")
            return None

    async def _voice_stream_with_tools(
        self, llm_stream, messages, llm, temperature: float, max_tokens: int
    ):
        """快速模式：透传内容 token，若 LLM 发出记忆工具调用则执行并二次生成纯文本。

        同一轮内内容与工具调用互斥（模型要么流文本、要么调工具），因此工具触发
        时前面不会已有可误喂 TTS 的内容。工具执行后经 llm.chat 二次生成，把最终
        文本作为单个 token 继续交给 TextSmoother 产出语音。
        """
        tool_calls = []
        async for chunk in llm_stream:
            if isinstance(chunk, dict) and chunk.get("tool_calls"):
                tool_calls.extend(chunk["tool_calls"])
                continue
            yield chunk

        if not tool_calls:
            return

        from server.core.tools.builtin import execute_tool_calls_async

        try:
            await execute_tool_calls_async(tool_calls, messages)
        except Exception as e:
            logger.warning(f"双流式快速模式工具执行失败: {e}")

        try:
            resp = await llm.chat(
                messages=messages, stream=False, temperature=temperature, max_tokens=max_tokens
            )
        except TypeError:
            resp = await llm.chat(messages=messages, stream=False)
        text = (getattr(resp, "content", None) or "").strip()
        if text:
            yield text

    async def _interrupt_pipeline(self) -> None:
        """打断当前流水线（毫秒级全双工打断）

        用户开口说话时立即取消正在运行的 LLM+TTS 流水线，
        停止 TTS 播放。CancelledError 处理器会将当前用户文本累积到 pending。
        """
        if self._pipeline_task and not self._pipeline_task.done():
            self._pipeline_task.cancel()
            try:
                await self._pipeline_task
            except asyncio.CancelledError:
                pass
        # 通知前端 TTS 已被打断
        await self.manager.send_message(self.client_id, {
            "type": "voice.interrupted",
            "data": {"reason": "user_speech"}
        })

    async def _finalize_turn(self, pipeline_task: asyncio.Task) -> None:
        """等待流水线完成后记录上下文（使用 VAD 修正后的 Final 文本）

        后台任务：不阻塞音频帧接收。等待 _pipeline_task 完成后，
        使用 _final_user_text（VAD on_end 修正后的 Final 文本）记录上下文。
        若流水线被新 utterance 打断（_pipeline_task is not self._pipeline_task），
        则跳过记录（用户文本已由 CancelledError 处理器累积到 pending）。
        """
        try:
            await pipeline_task
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

        # 仅当此 task 仍是当前流水线时才记录上下文
        # （若已被新 utterance 的 pipeline 替换，则跳过，避免覆盖新轮次状态）
        if self._pipeline_task is pipeline_task and self._pipeline_completed:
            # 使用 VAD 修正后的 Final 文本记录上下文（比 Partial 更准确）
            user_text = self._final_user_text or self._current_user_text
            await self._record_context(user_text, self._current_assistant_text)

        # 重置状态（仅当此 task 仍是当前流水线时）
        if self._pipeline_task is pipeline_task:
            self._current_user_text = ""
            self._current_assistant_text = ""
            self._final_user_text = ""
            self._pipeline_completed = False
            self._pipeline_task = None

    def _build_tts_kwargs(self) -> dict:
        """构建 Qwen3 统一编排合成参数：
        优先传 ref_asset_id/refs（参考音频资产），无则回退旧 ref_audio_path/ref_text。
        """
        tts_kwargs: dict = {}
        if self._ref_asset_id:
            tts_kwargs["ref_asset_id"] = self._ref_asset_id
        if self._refs:
            tts_kwargs["refs"] = self._refs
        if self._ref_audio_path:
            tts_kwargs["ref_audio_path"] = self._ref_audio_path
        if self._ref_text:
            tts_kwargs["ref_text"] = self._ref_text
        return tts_kwargs

    async def interrupt_and_reply(self, reply_content: str) -> None:
        """AI 主动插话打断：停止当前 TTS 播放，并（若有 content）立即播一条插话回应。

        由 LLM 打断判定（agent_interrupt_user）命中后调用，是"AI 打断人"的动作执行点。
        【标签解耦】打断与回复独立（用户裁决全量重构）：
        - 有 reply_content（AI 插话回应）：真打断——cancel 主管线 + 置打断标记 +
          发 voice.interrupted + _play_reply 直接播报（后续用户开口可再次打断）。
        - 无 reply_content（仅让位，回复由主 pipeline 生成，对应独立 LLM 模式）：
          **不** cancel 主管线、**不**置 _agent_interrupt_triggered，仅发打断事件
          （保持 should_interrupt 场景归因信号）。避免"空打断"反复摧毁在途回复
          ——paused_long 等长句场景实测根因：LLM 在用户组织语言中反复判 INTERRUPT，
          空打断逐个 cancel 主管线，导致用户实际听不到任何回复。
        """
        if reply_content:
            # 标记当前 utterance 已由 LLM 插话打断（供 speech_end_fallback 互斥使用：
            # on_vad_speech_end 据此跳过 VAD 兜底触发，避免双路 TTS 并发）
            self._agent_interrupt_triggered = True

            # 停止当前正在播放的 TTS（若有）
            if self._pipeline_task and not self._pipeline_task.done():
                self._pipeline_task.cancel()
                try:
                    await self._pipeline_task
                except (asyncio.CancelledError, Exception):
                    pass

            # 通知前端 TTS 已打断
            await self.manager.send_message(self.client_id, {
                "type": "voice.interrupted",
                "data": {"reason": "agent_interrupt"}
            })

            logger.debug("[DIAG-INTERRUPT] AI 插话播报: %s", reply_content[:40])
            # 插话回应作为新的 pipeline，后续用户开口可再次打断
            self._pipeline_task = asyncio.create_task(self._play_reply(reply_content))
        else:
            # 仅让位：不 cancel 主管线、不置打断标记；仅发打断事件供 should_interrupt 场景归因。
            # 回复由主 LLM 管线产出（partial/final/ensure_reply 已驱动），不被空打断摧毁。
            await self.manager.send_message(self.client_id, {
                "type": "voice.interrupted",
                "data": {"reason": "agent_interrupt"}
            })

    async def _play_reply(self, reply_content: str) -> None:
        """直接合成并播报一段固定文本（AI 插话回应），不经过 LLM。

        复用 TextSmoother + TTS 细粒度流式合成链路，与主 pipeline 一致。
        """
        if not reply_content:
            return
        from server.services.text_smoother import TextSmoother

        async def _reply_tokens():
            # 按字符产出，模拟 LLM token 流（TextSmoother 会按窗口聚合）
            for ch in reply_content:
                yield ch

        await set_tts_playing(self.client_id, True)
        self._tts_chunk_index = 0
        self._current_assistant_text = ""
        try:
            async for chunk in self.tts_service.synthesize_stream_fine(
                token_stream=TextSmoother.smooth(
                    _reply_tokens(), window_ms=30, char_threshold=2
                ),
                **self._build_tts_kwargs(),
            ):
                if chunk.get("is_final"):
                    await self._send_tts_chunk(chunk, is_final=True)
                    break
                text_segment = chunk.get("text_segment", "")
                if text_segment:
                    self._current_assistant_text += text_segment
                if chunk.get("audio_data"):
                    await self._send_tts_chunk(chunk, is_final=False)
        finally:
            await set_tts_playing(self.client_id, False)

    async def _send_partial(self, text: str, is_final: bool = False) -> None:
        """发送 ASR 识别文本给前端（Partial 实时显示 / Final 最终确认）"""
        await self.manager.send_message(self.client_id, {
            "type": VoiceActions.PARTIAL,
            "data": {
                "text": text,
                "is_final": is_final
            }
        })

    async def _send_prefill_started(self, text: str) -> None:
        """发送 LLM Prefill 已启动信号给前端

        前端收到此信号可显示"正在思考"状态，并准备接收 TTS 音频流。
        这比等 LLM 第一个 token 到达再通知前端快 ~80ms（TTFT）。
        """
        await self.manager.send_message(self.client_id, {
            "type": VoiceActions.PREFILL_STARTED,
            "data": {
                "partial_text": text,
                "timestamp": time.time()
            }
        })

    async def _send_tts_chunk(self, chunk: dict, is_final: bool) -> None:
        """发送 TTS 音频块给前端（流式推送，不等整句）"""
        audio_data = chunk.get("audio_data")
        audio_base64 = None
        if audio_data:
            audio_base64 = base64.b64encode(audio_data).decode("utf-8")

        stream_msg = create_stream(
            request_id=self.request_id,
            action=VoiceActions.TTS_CHUNK,
            chunk_index=self._tts_chunk_index,
            data={
                "text_segment": chunk.get("text_segment", ""),
                "audio_data": audio_base64,
            },
            is_final=is_final
        )

        await self.manager.send_message(self.client_id, stream_msg)
        self._tts_chunk_index += 1

    async def _record_context(self, user_text: str, assistant_text: str) -> None:
        """记录上下文（合并未触发 LLM 的 partial 为单条 user 上下文）

        上下文整合核心逻辑：
        - 一轮对话 = 一条 user + 一条 assistant
        - 未触发 LLM 回复的 utterance 已在 on_partial_result 中合并到 user_text
        - 上下文记录数 = 实际对话轮次数，不因 Partial 数量增加而膨胀
        """
        if not user_text or not assistant_text:
            return

        try:
            from server.dependencies import get_context_manager
            context_mgr = get_context_manager()

            # 确保 session 存在
            context_mgr.ensure_session(
                self.session_id,
                workspace_id="agent-chats",
                title="双流式对话",
                metadata={"agent_id": self.agent_id},
            )

            # 记录完整轮次：user + assistant
            context_mgr.add_message(
                session_id=self.session_id, role="user", content=user_text
            )
            context_mgr.add_message(
                session_id=self.session_id, role="assistant", content=assistant_text
            )
        except Exception as e:
            logger.error(f"记录双流式上下文失败: {e}")

    async def finish(self) -> None:
        """结束会话，清理资源"""
        self._is_active = False
        # 取消正在运行的流水线
        if self._pipeline_task and not self._pipeline_task.done():
            self._pipeline_task.cancel()
            try:
                await self._pipeline_task
            except asyncio.CancelledError:
                pass
        # 取消所有追踪中的后台任务（打断判定/finalize 等），
        # 防止断连后在途任务仍启动新的 LLM+TTS pipeline 向已死连接推流。
        for task in list(self._background_tasks):
            if not task.done():
                task.cancel()
        # 重置 TTS 播放状态
        try:
            await set_tts_playing(self.client_id, False)
        except Exception:
            pass


def init_interrupt_module():
    """初始化 ASR 打断与 AI 插话打断模块单例，并加载 config.json 配置。

    此前 agent_interrupt 的 set_config 仅在 live_client 的运行时 config 消息中
    被调用，普通 WS 场景下单例保持默认 enabled=True——config.json 的
    agent_interrupt.enabled=false 从未生效（UnifiedConfig 未声明该节，
    config.json 的 agent_interrupt 键被 pydantic 静默丢弃）。此处启动时直接
    读取 config.json 原始内容补齐配置，使禁用/阈值等全局生效。
    """
    import json as _json
    from pathlib import Path

    from server.services.asr_interrupt import get_asr_interrupt_module
    get_asr_interrupt_module()

    from server.services.agent_interrupt_user import get_agent_interrupt_module
    agent_interrupt = get_agent_interrupt_module()

    # UnifiedConfig 未声明 agent_interrupt 节，直接读 config.json 原始内容应用
    try:
        cfg_path = Path(__file__).resolve().parent.parent.parent / "config.json"
        with open(cfg_path, "r", encoding="utf-8") as f:
            raw_cfg = _json.load(f)
        if "agent_interrupt" in raw_cfg:
            agent_interrupt.set_config({"agent_interrupt": raw_cfg["agent_interrupt"]})
            logger.info("已加载 agent_interrupt 配置: %s", raw_cfg["agent_interrupt"])
    except Exception as e:
        logger.warning(f"加载 agent_interrupt 配置失败: {e}")


def init_audio_stream_processor(asr_client):
    from server.services.vad_processor import get_audio_stream_processor
    from server.services.agent_interrupt_user import get_agent_interrupt_module

    stream_processor = get_audio_stream_processor()
    stream_processor.set_asr_client(asr_client)

    agent_interrupt = get_agent_interrupt_module()
    stream_processor.set_agent_interrupt(agent_interrupt)


def register_audio_handlers(
    manager: "WebSocketManager",
    asr_service: "ASRService",
    tts_service: "TTSService",
    effects_dir: str | None = None
):
    """将全部音频（ASR/TTS/情感/音效/双流式）处理器注册到 WebSocket 管理器。"""
    effect_parser = EffectParser(effects_dir)

    async def handle_asr_recognize(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})

        try:
            audio_base64 = data.get("audio")
            language = data.get("language", "auto")

            if not audio_base64:
                await manager.send_message(client_id, create_error(
                    request_id=request_id,
                    action=ASRActions.RECOGNIZE,
                    code="INVALID_REQUEST",
                    message="Missing audio data"
                ))
                return

            audio_data = base64.b64decode(audio_base64)
            result = await asr_service.recognize(audio_data, language)

            await manager.send_message(client_id, create_response(
                request_id=request_id,
                action=ASRActions.RECOGNIZE,
                data=result
            ))

            asr_text = result.get("text", "")
            if asr_text:
                try:
                    from server.services.asr_interrupt import get_asr_interrupt_module
                    interrupt_module = get_asr_interrupt_module()
                    if interrupt_module.enabled:
                        await interrupt_module.on_asr_result(asr_text)
                except Exception as e:
                    logger.error(f"ASR interrupt check error: {e}")
        except Exception as e:
            logger.error(f"ASR recognize error: {e}")
            await manager.send_message(client_id, create_error(
                request_id=request_id,
                action=ASRActions.RECOGNIZE,
                code="ASR_ERROR",
                message=str(e)
            ))

    async def handle_tts_synthesize(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})

        try:
            text = data.get("text", "")
            ref_audio_base64 = data.get("ref_audio")
            ref_text = data.get("ref_text", "")
            # Qwen3 统一编排：参考音频资产 ID（ref_ 前缀）与多参考音频列表
            ref_asset_id = data.get("ref_asset_id")
            refs = data.get("refs")

            if not text:
                await manager.send_message(client_id, create_error(
                    request_id=request_id,
                    action=TTSActions.SYNTHESIZE,
                    code="INVALID_REQUEST",
                    message="Missing text"
                ))
                return

            kwargs = {}
            if ref_asset_id:
                kwargs["ref_asset_id"] = ref_asset_id
            if refs:
                kwargs["refs"] = refs if isinstance(refs, list) else [refs]
            if ref_audio_base64:
                import tempfile
                import os
                audio_data = base64.b64decode(ref_audio_base64)
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                    f.write(audio_data)
                    kwargs["ref_audio_path"] = f.name
                if ref_text:
                    kwargs["ref_text"] = ref_text

            audio_bytes = await tts_service.synthesize(text, **kwargs)

            if "ref_audio_path" in kwargs:
                try:
                    os.unlink(kwargs["ref_audio_path"])
                except Exception:
                    pass

            audio_base64 = base64.b64encode(audio_bytes).decode("utf-8")

            await manager.send_message(client_id, create_response(
                request_id=request_id,
                action=TTSActions.SYNTHESIZE,
                data={
                    "audio_data": audio_base64,
                    "format": "wav"
                }
            ))
        except Exception as e:
            logger.error(f"TTS synthesize error: {e}")
            await manager.send_message(client_id, create_error(
                request_id=request_id,
                action=TTSActions.SYNTHESIZE,
                code="TTS_ERROR",
                message=str(e)
            ))

    async def handle_tts_synthesize_stream(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})

        try:
            text = data.get("text", "")
            ref_audio_base64 = data.get("ref_audio")
            ref_text = data.get("ref_text", "")
            emotion_enabled = data.get("emotion_enabled", False)
            effects_enabled = data.get("effects_enabled", False)
            # Qwen3 统一编排：参考音频资产 ID（ref_ 前缀）与多参考音频列表
            ref_asset_id = data.get("ref_asset_id")
            refs = data.get("refs")

            if not text:
                await manager.send_message(client_id, create_error(
                    request_id=request_id,
                    action=TTSActions.SYNTHESIZE_STREAM,
                    code="INVALID_REQUEST",
                    message="Missing text"
                ))
                return

            kwargs = {}
            if ref_asset_id:
                kwargs["ref_asset_id"] = ref_asset_id
            if refs:
                kwargs["refs"] = refs if isinstance(refs, list) else [refs]
            temp_file = None
            if ref_audio_base64:
                import tempfile
                import os
                audio_data = base64.b64decode(ref_audio_base64)
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                    f.write(audio_data)
                    temp_file = f.name
                    kwargs["ref_audio_path"] = temp_file
                if ref_text:
                    kwargs["ref_text"] = ref_text

            chunk_index = 0
            await set_tts_playing(client_id, True)

            try:
                if emotion_enabled or effects_enabled:
                    async for chunk in tts_service.synthesize_stream_with_emotions(text, **kwargs):
                        audio_base64 = None
                        if chunk.get("audio_data"):
                            audio_base64 = base64.b64encode(chunk["audio_data"]).decode("utf-8")

                        stream_msg = create_stream(
                            request_id=request_id,
                            action=TTSActions.SYNTHESIZE_STREAM,
                            chunk_index=chunk_index,
                            data={
                                "text_segment": chunk.get("text_segment", ""),
                                "audio_data": audio_base64,
                                "emotion": chunk.get("emotion"),
                                "is_effect": chunk.get("is_effect", False),
                                "effect_name": chunk.get("effect_name")
                            },
                            is_final=chunk.get("is_final", False)
                        )

                        await manager.send_message(client_id, stream_msg)
                        chunk_index += 1
                else:
                    async for chunk in tts_service.synthesize_stream(text, **kwargs):
                        audio_base64 = None
                        if chunk.get("audio_data"):
                            audio_base64 = base64.b64encode(chunk["audio_data"]).decode("utf-8")

                        stream_msg = create_stream(
                            request_id=request_id,
                            action=TTSActions.SYNTHESIZE_STREAM,
                            chunk_index=chunk_index,
                            data={
                                "text_segment": chunk.get("text_segment", ""),
                                "audio_data": audio_base64
                            },
                            is_final=chunk.get("is_final", False)
                        )

                        await manager.send_message(client_id, stream_msg)
                        chunk_index += 1
            except Exception as e:
                logger.error(f"TTS stream error: {e}")
                await manager.send_message(client_id, create_error(
                    request_id=request_id,
                    action=TTSActions.SYNTHESIZE_STREAM,
                    code="TTS_ERROR",
                    message=str(e)
                ))
            finally:
                try:
                    await set_tts_playing(client_id, False)
                except Exception as reset_error:
                    logger.error(f"重置 TTS 播放状态失败：{reset_error}")

                if temp_file:
                    try:
                        os.unlink(temp_file)
                    except Exception as cleanup_error:
                        logger.warning(f"清理临时文件失败：{cleanup_error}")

        except Exception as e:
            logger.error(f"TTS synthesize error: {e}")
            try:
                await set_tts_playing(client_id, False)
            except Exception as reset_error:
                logger.error(f"重置 TTS 播放状态失败：{reset_error}")
            await manager.send_message(client_id, create_error(
                request_id=request_id,
                action=TTSActions.SYNTHESIZE_STREAM,
                code="TTS_ERROR",
                message=str(e)
            ))

    async def handle_emotions_list(websocket, message, client_id):
        request_id = message.get("request_id", "")

        try:
            emotions = get_supported_emotions()
            await manager.send_message(client_id, create_response(
                request_id=request_id,
                action=EmotionActions.LIST,
                data={"emotions": emotions}
            ))
        except Exception as e:
            logger.error(f"Emotions list error: {e}")
            await manager.send_message(client_id, create_error(
                request_id=request_id,
                action=EmotionActions.LIST,
                code="EMOTION_ERROR",
                message=str(e)
            ))

    async def handle_emotions_parse(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})

        try:
            text = data.get("text", "")

            if not text:
                await manager.send_message(client_id, create_error(
                    request_id=request_id,
                    action=EmotionActions.PARSE,
                    code="INVALID_REQUEST",
                    message="Missing text"
                ))
                return

            segments = extract_emotions_with_text(text)
            await manager.send_message(client_id, create_response(
                request_id=request_id,
                action=EmotionActions.PARSE,
                data={"segments": segments}
            ))
        except Exception as e:
            logger.error(f"Emotions parse error: {e}")
            await manager.send_message(client_id, create_error(
                request_id=request_id,
                action=EmotionActions.PARSE,
                code="EMOTION_ERROR",
                message=str(e)
            ))

    async def handle_effects_list(websocket, message, client_id):
        request_id = message.get("request_id", "")

        try:
            effects = effect_parser.get_available_effects()
            await manager.send_message(client_id, create_response(
                request_id=request_id,
                action=EffectActions.LIST,
                data={"effects": effects}
            ))
        except Exception as e:
            logger.error(f"Effects list error: {e}")
            await manager.send_message(client_id, create_error(
                request_id=request_id,
                action=EffectActions.LIST,
                code="EFFECT_ERROR",
                message=str(e)
            ))

    async def handle_effects_parse(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})

        try:
            text = data.get("text", "")

            if not text:
                await manager.send_message(client_id, create_error(
                    request_id=request_id,
                    action=EffectActions.PARSE,
                    code="INVALID_REQUEST",
                    message="Missing text"
                ))
                return

            segments = effect_parser.parse_text_with_effects(text)
            await manager.send_message(client_id, create_response(
                request_id=request_id,
                action=EffectActions.PARSE,
                data={"segments": segments}
            ))
        except Exception as e:
            logger.error(f"Effects parse error: {e}")
            await manager.send_message(client_id, create_error(
                request_id=request_id,
                action=EffectActions.PARSE,
                code="EFFECT_ERROR",
                message=str(e)
            ))

    async def handle_asr_stream(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})

        try:
            stream_processor = get_audio_stream_processor()

            audio_base64 = data.get("audio")
            reset = data.get("reset", False)

            if reset:
                stream_processor.reset()
                await manager.send_message(client_id, create_response(
                    request_id=request_id,
                    action=ASRActions.STATUS,
                    data={"status": "reset"}
                ))
                return

            if not audio_base64:
                # 静默返回改为明确错误，前端可区分"无音频数据"与"处理成功"
                await manager.send_message(client_id, create_error(
                    request_id=request_id,
                    action=ASRActions.STREAM,
                    code="INVALID_REQUEST",
                    message="Missing audio data"
                ))
                return

            audio_data = base64.b64decode(audio_base64)

            result = await stream_processor.process_audio_chunk(audio_data)

            vad_result = result.get("vad", {})
            asr_result = result.get("asr")

            if vad_result.get("state_changed"):
                status = "speech_start" if vad_result["is_speaking"] else "speech_end"
                await manager.send_message(client_id, {
                    "type": "vad_status",
                    "data": {
                        "status": status,
                        "speech_duration_ms": vad_result.get("speech_duration_ms", 0)
                    }
                })

            if asr_result:
                await manager.send_message(client_id, create_response(
                    request_id=request_id,
                    action=ASRActions.RESULT,
                    data={
                        "text": asr_result.get("text", ""),
                        "is_final": not vad_result.get("is_speaking", False)
                    }
                ))

            await manager.send_message(client_id, {
                "type": "vad_frame",
                "data": {
                    "is_speaking": vad_result.get("is_speaking", False),
                    "speech_probability": vad_result.get("speech_probability", 0),
                    "speech_duration_ms": vad_result.get("speech_duration_ms", 0)
                }
            })

        except Exception as e:
            logger.error(f"ASR stream error: {e}")
            await manager.send_message(client_id, create_error(
                request_id=request_id,
                action=ASRActions.STREAM,
                code="ASR_STREAM_ERROR",
                message=str(e)
            ))

    async def _maybe_agent_interrupt(session, asr_result):
        """非阻塞"AI 打断人"判定：命中后停当前 TTS 并播插话回应。

        内部判定（agent_interrupt_user.on_asr_partial_result）可能调用 LLM（~8s），
        因此必须由调用方以 create_task 异步发起，绝不阻塞音频帧处理。
        """
        try:
            from server.services.agent_interrupt_user import get_agent_interrupt_module
            agent_interrupt = get_agent_interrupt_module()
            text = (asr_result.get("text") or "").strip()
            if not text:
                return
            res = await agent_interrupt.on_asr_partial_result(
                text,
                is_final=bool(asr_result.get("is_final", False)),
            )
            # 【标签解耦】路由决策收敛到 route_agent_interrupt_result：
            # should_interrupt（真打断）→ interrupt_and_reply；
            # should_reply（Feature B 回复）→ ensure_reply 回复兜底（不打断）。
            await route_agent_interrupt_result(session, res)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"AI 插话判定错误: {e}")

    async def handle_voice_dual_stream(websocket, message, client_id):
        """双流式语音 handler：编排 ASR → LLM → TTS 全链路流水线

        消息协议（前端 → 后端，均使用 voice.dual_stream action）：
        - init: {"data": {"init": true, "agent_id": "default", "ref_audio_path": "...", "ref_text": "..."}}
        - audio: {"data": {"audio": "<base64>"}}
        - end:   {"data": {"end": true}}

        消息协议（后端 → 前端）：
        - voice.partial: ASR Partial 识别文本（实时显示）
        - voice.prefill_started: LLM Prefill 已启动信号
        - voice.tts_chunk: TTS 音频块（流式推送）
        - voice.interrupted: TTS 被用户打断通知
        - vad_status / vad_frame: VAD 状态（与半双工模式一致）
        """
        request_id = message.get("request_id", "")
        data = message.get("data", {})

        # ---- 初始化会话 ----
        if data.get("init"):
            # 清理同 client_id 的旧会话（避免资源泄漏）
            old_session = _dual_stream_sessions.pop(client_id, None)
            if old_session:
                await old_session.finish()

            # 清理孤儿会话：WS 已断开但 session 仍在的会话
            # 场景：测试脚本每轮用新 WS 连接（新 client_id），上一轮 session 不会主动清理。
            # 若不清理，旧 session 的 _run_pipeline 仍会运行并向已断开的 client_id 发送 TTS chunk，
            # 产生大量 "[DIAG-SEND] connection is None" 警告日志，干扰诊断。
            stale_ids = [
                cid for cid in list(_dual_stream_sessions.keys())
                if cid != client_id and cid not in manager.connections
            ]
            for cid in stale_ids:
                stale = _dual_stream_sessions.pop(cid, None)
                if stale:
                    try:
                        await stale.finish()
                        logger.info(f"清理孤儿会话: client_id={cid}")
                    except Exception as e:
                        logger.warning(f"清理孤儿会话失败 {cid}: {e}")

            agent_id = data.get("agent_id", "default")
            ref_audio_path = data.get("ref_audio_path")
            ref_text = data.get("ref_text")
            # Qwen3 统一编排：参考音频资产 ID（ref_ 前缀）与多参考音频列表
            ref_asset_id = data.get("ref_asset_id")
            refs = data.get("refs")

            session = DualStreamSession(
                client_id=client_id,
                agent_id=agent_id,
                request_id=request_id,
                manager=manager,
                tts_service=tts_service,
                ref_audio_path=ref_audio_path,
                ref_text=ref_text,
                ref_asset_id=ref_asset_id,
                refs=refs,
            )
            _dual_stream_sessions[client_id] = session

            await manager.send_message(client_id, create_response(
                request_id=request_id,
                action=VoiceActions.DUAL_STREAM,
                data={"status": "initialized", "session_id": session.session_id}
            ))
            return

        # 获取会话
        session = _dual_stream_sessions.get(client_id)
        if not session:
            await manager.send_message(client_id, create_error(
                request_id=request_id,
                action=VoiceActions.DUAL_STREAM,
                code="SESSION_NOT_FOUND",
                message="双流式会话未初始化，请先发送 init 信号"
            ))
            return

        # ---- 结束会话 ----
        if data.get("end"):
            _dual_stream_sessions.pop(client_id, None)
            await session.finish()
            await manager.send_message(client_id, create_response(
                request_id=request_id,
                action=VoiceActions.DUAL_STREAM,
                data={"status": "ended"}
            ))
            return

        # ---- 处理音频帧 ----
        audio_base64 = data.get("audio")
        if not audio_base64:
            # 静默返回改为明确错误，前端可区分"无音频数据"与"处理成功"
            await manager.send_message(client_id, create_error(
                request_id=request_id,
                action=VoiceActions.DUAL_STREAM,
                code="INVALID_REQUEST",
                message="Missing audio data"
            ))
            return

        try:
            audio_data = base64.b64decode(audio_base64)

            stream_processor = get_audio_stream_processor()

            # 诊断计时：定位 WS 端到端延迟瓶颈（DEBUG 模式才计时，热路径不产生开销）
            _diag_enabled = logger.isEnabledFor(logging.DEBUG)
            if _diag_enabled:
                import time as _diag_time
                _t0 = _diag_time.monotonic()

            # 复用现有 AudioStreamProcessor 进行 VAD + ASR 处理
            # 不设置 on_partial_result 回调，避免单例跨客户端干扰
            # 直接从返回值中检查 asr_result 判断是否为 Partial
            # skip_interrupt=True：vad_processor 内部的 agent_interrupt 判定不触发，
            # 由下方 handler 层 _maybe_agent_interrupt 统一接管（可捕获当前 session，
            # 且用非阻塞 create_task，避免主 LLM 判定阻塞帧处理）
            result = await stream_processor.process_audio_chunk(audio_data, skip_interrupt=True)

            if _diag_enabled:
                _t1 = _diag_time.monotonic()
                logger.debug("[DIAG] process_audio_chunk took %.1fms, vad_state_changed=%s, has_asr=%s", (_t1-_t0)*1000, result.get('vad',{}).get('state_changed'), result.get('asr') is not None)

            vad_result = result.get("vad", {})
            asr_result = result.get("asr")

            # VAD 状态变化处理
            if vad_result.get("state_changed"):
                if vad_result["is_speaking"]:
                    # 用户开始说话 → 全双工打断触发点
                    # 用户开口即停止 TTS，省去等待 ASR 识别的 ~200ms
                    await session.on_vad_speech_start()
                    # 通知插话判定模块：用户开始说话（用于正确计算说话时长）
                    try:
                        from server.services.agent_interrupt_user import get_agent_interrupt_module
                        get_agent_interrupt_module().on_user_speech_start()
                    except Exception:
                        pass
                else:
                    # 用户说话结束 → VAD 兜底修正 Final 文本
                    # 不重启已由 Partial 启动的 LLM 流程
                    await session.on_vad_speech_end(asr_result)
                    # 通知插话判定模块：用户结束说话
                    try:
                        from server.services.agent_interrupt_user import get_agent_interrupt_module
                        get_agent_interrupt_module().on_user_speech_end()
                    except Exception:
                        pass

                # 发送 VAD 状态给前端（与半双工模式格式一致，保持兼容）
                status = "speech_start" if vad_result["is_speaking"] else "speech_end"
                await manager.send_message(client_id, {
                    "type": "vad_status",
                    "data": {
                        "status": status,
                        "speech_duration_ms": vad_result.get("speech_duration_ms", 0)
                    }
                })

            # ASR Partial Result 主驱动：立即触发 LLM Speculative Prefill
            # is_final=False 即为 Partial，不等 VAD on_end，省下 ~500ms
            if asr_result and not asr_result.get("is_final", True):
                await session.on_partial_result(asr_result)
            # ASR Final Result 兜底：短语音（VAD 段 < partial 阈值）全程无 partial，
            # final 是唯一触发机会；已触发时仅修正上下文文本（详见 on_final_result）。
            # 透传当前 VAD 状态：final 迟到且用户已开说下一句时仅合并 pending 不触发
            elif asr_result and asr_result.get("is_final"):
                await session.on_final_result(
                    asr_result,
                    is_speaking=vad_result.get("is_speaking", False),
                )

            # "AI 打断人"：任何时刻，只要 ASR 产出有效文本，就用非阻塞协程判定
            # 是否要插话。判定内部有说话时长(1s)+冷却(3s)保护，频率受限；
            # 命中后停当前 TTS 并播插话回应（主 LLM 模式带 reply_content）。
            # 非阻塞 create_task：判定内部会调 LLM（可能 ~8s），绝不阻塞帧处理。
            if asr_result and asr_result.get("text"):
                session._track_background_task(
                    asyncio.create_task(_maybe_agent_interrupt(session, asr_result))
                )

            # 发送 VAD 帧状态给前端（与半双工模式格式一致）
            await manager.send_message(client_id, {
                "type": "vad_frame",
                "data": {
                    "is_speaking": vad_result.get("is_speaking", False),
                    "speech_probability": vad_result.get("speech_probability", 0),
                    "speech_duration_ms": vad_result.get("speech_duration_ms", 0)
                }
            })

        except Exception as e:
            logger.error(f"双流式音频处理错误: {e}", exc_info=True)
            await manager.send_message(client_id, create_error(
                request_id=request_id,
                action=VoiceActions.DUAL_STREAM,
                code="DUAL_STREAM_ERROR",
                message=str(e)
            ))

    manager.register_handler(ASRActions.RECOGNIZE, handle_asr_recognize)
    manager.register_handler(ASRActions.RECOGNIZE_BASE64, handle_asr_recognize)
    manager.register_handler(TTSActions.SYNTHESIZE, handle_tts_synthesize)
    manager.register_handler(TTSActions.SYNTHESIZE_STREAM, handle_tts_synthesize_stream)
    manager.register_handler(EmotionActions.LIST, handle_emotions_list)
    manager.register_handler(EmotionActions.PARSE, handle_emotions_parse)
    manager.register_handler(EffectActions.LIST, handle_effects_list)
    manager.register_handler(EffectActions.PARSE, handle_effects_parse)
    manager.register_handler(ASRActions.STREAM, handle_asr_stream)
    # 修复 WS action 路由错位：用 register_action_handler 注册到 _action_handlers
    # gateway/server.py:113 用 get_handler(action) 从 _action_handlers 取
    # 原 register_handler 注册到 message_handlers（type 路由），导致 voice.dual_stream 永远找不到
    # 详见 .trae/documents/20260718_模块0_WS端到端ASR阻塞修复.md §1.3 根因3
    manager.register_action_handler(VoiceActions.DUAL_STREAM, handle_voice_dual_stream)
