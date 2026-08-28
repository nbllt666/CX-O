"""
Agent 打断用户模块 - 双向全双工
Agent 可以在用户说话过程中判断是否可以插话
"""
import json
import logging
import time
from collections import deque
from typing import Optional, Callable, Any
from dataclasses import dataclass, field

from server.services.interrupt_llm import InterruptModuleBase

logger = logging.getLogger(__name__)

# 提问/请求确定性意图闸门词表（Feature A/B 共享，O2）
_QUESTION_WORDS = ("？", "?", "吗", "呢", "什么", "怎么", "为什么", "哪里", "谁", "多少", "啥", "嘛", "怎样", "怎么样")
_REQUEST_WORDS = ("帮我", "告诉", "查", "搜索", "打开", "播放", "设", "提醒", "请")
# 非问句固定搭配：虽含提问/请求字但为陈述、客套或情绪填充，命中即从文本剔除（不视作提问/请求）。
# 硬性提问信号（？/?/吗）与不在表内的真正疑问词（为什么/多少/啥/谁 等）不受影响。
_NON_QUESTION_PHRASES = (
    "什么都不", "什么也没", "没什么", "这有什么", "有什么好", "不怎么",
    "哪里哪里", "哪里话", "管他呢", "还没呢", "没办法嘛", "就是嘛",
    "假设", "设备",
    # 反诘/反问句式（含"什么"但属情绪宣泄，非对 Agent 的提问）：
    # 覆盖"这有什么好问的/什么好问的"等 ASR 缺前缀变体（"什么"残留致误判）。
    "什么好问", "什么好笑", "什么好奇怪", "有什么了不起",
)


@dataclass
class UserSpeechState:
    is_speaking: bool = False
    current_text: str = ""
    start_time: float = 0
    last_update_time: float = 0
    # B3 有界化：segments 列表仅写不读（诊断用途），超长 utterance 的逐帧 append
    # 会无界累积。改为 deque(maxlen=50)——超过 50 条自动丢弃最旧。
    text_segments: deque = field(default_factory=lambda: deque(maxlen=50))


class AgentInterruptUser(InterruptModuleBase):
    """Agent 打断用户模块——在用户说话过程中判定是否可插话并执行插话。"""
    _instance = None

    def __init__(self):
        super().__init__()
        self.enabled = True
        self.mode = "main_llm"  # main_llm / independent_llm
        self.min_speech_duration_ms = 1000
        self._user_state = UserSpeechState()
        self._interrupt_user_callback: Optional[Callable] = None
        self._start_tts_callback: Optional[Callable] = None
        self._asr_client: Any = None
        self._last_interrupt_time: float = 0
        self._interrupt_cooldown_ms = 3000
        self._interrupted_this_utterance = False  # 本 utterance 是否已触发打断（防 Feature B 重复回复）
        self.speech_end_fallback = False  # 是否以打断标记抑制 VAD speech_end 兜底（不改变 enabled 的插话打断语义）
        # Feature A/B 可配置开关（默认打开；置 false 时逐字回退到上一轮行为）
        self.question_intent_required = True   # Feature A：LLM 判 INTERRUPT 后须经提问意图硬闸门二次确认
        self.reply_on_final_question = True    # Feature B：is_final 且经意图闸门的完整请求可触发一次回复
        # 判定统计：总判定数 / 三态 decision 计数 / 触发打断次数 / 触发回复次数
        # （误触发标记不在此模块计算，由评测脚本按场景标签判定）
        self._stats = {
            "total_judgments": 0,
            "decisions": {"INTERRUPT": 0, "CONTINUE": 0, "IGNORE": 0},
            "interrupts_triggered": 0,
            "replies_triggered": 0,
        }
        # 独立小模型判定：只输出 INTERRUPT/IGNORE/CONTINUE 标记，不生成回复内容
        # （回复内容由主 pipeline 生成），避免占用主 LLM 并发槽

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def set_config(self, config: dict):
        """从配置字典加载打断阈值、模式与冷却等参数。"""
        agent_interrupt = config.get("agent_interrupt", {})
        self.enabled = agent_interrupt.get("enabled", True)
        self.mode = agent_interrupt.get("mode", "main_llm")
        self.min_speech_duration_ms = agent_interrupt.get("min_speech_duration_ms", 1000)
        self._interrupt_cooldown_ms = agent_interrupt.get("interrupt_cooldown_ms", 3000)
        self.speech_end_fallback = agent_interrupt.get("speech_end_fallback", False)
        self.question_intent_required = agent_interrupt.get("question_intent_required", True)
        self.reply_on_final_question = agent_interrupt.get("reply_on_final_question", True)
        independent = agent_interrupt.get("independent_llm", {})
        if isinstance(independent, dict) and independent:
            self.independent_llm_config = {
                "enabled": independent.get("enabled", False),
                "model": independent.get("model", self.independent_llm_config["model"]),
                "endpoint": independent.get("endpoint", self.independent_llm_config["endpoint"]),
            }

    def set_asr_client(self, client: Any):
        self._asr_client = client

    def set_callbacks(
        self,
        interrupt_user_callback: Optional[Callable] = None,
        start_tts_callback: Optional[Callable] = None
    ):
        """设置打断用户与开启 TTS 的回调。"""
        self._interrupt_user_callback = interrupt_user_callback
        self._start_tts_callback = start_tts_callback

    def get_stats(self) -> dict:
        """返回判定统计字典。

        - total_judgments：真正执行判定（调用 _check_can_interrupt）的总次数
        - decisions：INTERRUPT / CONTINUE / IGNORE 各 decision 计数
        - interrupts_triggered：触发打断的次数（should_interrupt=True 真打断分支累计，冷却天然防重复）
        - replies_triggered：触发回复的次数（should_reply=True Feature B 分支累计）
        """
        return {
            "total_judgments": self._stats["total_judgments"],
            "decisions": dict(self._stats["decisions"]),
            "interrupts_triggered": self._stats["interrupts_triggered"],
            "replies_triggered": self._stats["replies_triggered"],
        }

    def reset_stats(self):
        """清零判定统计。"""
        self._stats["total_judgments"] = 0
        self._stats["interrupts_triggered"] = 0
        self._stats["replies_triggered"] = 0
        for key in self._stats["decisions"]:
            self._stats["decisions"][key] = 0

    def on_user_speech_start(self):
        self._user_state = UserSpeechState(
            is_speaking=True,
            start_time=time.time(),
            last_update_time=time.time()
        )
        self._interrupted_this_utterance = False
        logger.debug("User speech started")

    def on_user_speech_end(self):
        """记录用户结束说话状态。"""
        if self._user_state.is_speaking:
            logger.debug(f"User speech ended: {self._user_state.current_text}")
            self._user_state.is_speaking = False

    async def on_asr_partial_result(self, text: str, is_final: bool = False) -> dict:
        if not self.enabled:
            return {"should_interrupt": False, "should_reply": False}

        current_time = time.time()
        self._user_state.current_text = text
        self._user_state.last_update_time = current_time

        if text:
            self._user_state.text_segments.append({
                "text": text,
                "time": current_time,
                "is_final": is_final
            })

        speech_duration_ms = (current_time - self._user_state.start_time) * 1000

        if speech_duration_ms < self.min_speech_duration_ms:
            return {"should_interrupt": False, "should_reply": False}

        if current_time - self._last_interrupt_time < self._interrupt_cooldown_ms / 1000:
            return {"should_interrupt": False, "should_reply": False}

        result = await self._check_can_interrupt(text, is_final)

        # Feature A：提问意图硬闸门——LLM 判 INTERRUPT 后经确定性提问/请求意图二次确认。
        # 文本无提问词或祈使请求特征（如情绪独白"唉，今天好累啊"）时强制降级为 IGNORE 不打断。
        if (
            result.get("can_interrupt")
            and self.question_intent_required
            and not self._has_question_or_request(self._user_state.current_text)
        ):
            result = {
                "decision": "IGNORE",
                "can_interrupt": False,
                "should_reply": False,
                "reply_content": "",
            }

        # 判定统计：仅在真正调用 _check_can_interrupt 后累计
        # （disabled / 时长不足 / 冷却早退不产生判定，不计入）。
        # decision 计数按 Feature A 闸门降级后的【实际生效 decision】累计，避免统计语义漂移。
        decision = result.get("decision", "IGNORE")
        if decision not in ("INTERRUPT", "CONTINUE", "IGNORE"):
            decision = "IGNORE"
        self._stats["total_judgments"] += 1
        self._stats["decisions"][decision] += 1

        if result.get("can_interrupt"):
            self._last_interrupt_time = current_time
            self._interrupted_this_utterance = True
            # 触发打断次数：仅在本分支累计；冷却已在 _check_can_interrupt 前拦截重复打断，天然防重复
            self._stats["interrupts_triggered"] += 1
            return {
                "should_interrupt": True,
                "should_reply": result.get("should_reply", True),
                "reply_content": result.get("reply_content", "")
            }

        if is_final:
            # Feature B：最终完整请求回复触发——is_final 且经同一意图闸门（O2）确认为
            # 需回复的完整请求、且本 utterance 尚未触发打断时，触发一次"回复"。
            # 【标签解耦】should_interrupt=False（用户已说完，非真打断），
            # should_reply=True——下游走 ensure_reply 回复兜底，不 cancel 主管线、
            # 不外发打断事件（voice.interrupted 已删除）、不置会话级 _agent_interrupt_triggered。
            if (
                self.reply_on_final_question
                and not self._interrupted_this_utterance
                and self._has_question_or_request(self._user_state.current_text)
            ):
                # [O1 时序标定] 记录 Feature B 触发时刻距 user speech 起始的相对耗时，
                # 供评测侧比对 send_done_rel（完整音频 + 0.8s 尾静音发送完）基准顺序。
                elapsed_ms = (current_time - self._user_state.start_time) * 1000
                logger.info(
                    "reply triggered at %dms since speech_start",
                    elapsed_ms,
                )
                # 仅置模块内"本 utterance 已处理"守卫（防重复 final 再次触发），
                # 不置 _last_interrupt_time（非打断，不占用打断冷却）。
                self._interrupted_this_utterance = True
                # [统计语义 O1] replies_triggered 独立计数 Feature B 补充回复；
                # decisions[INTERRUPT] 仅反映 LLM 自身三态判定分布，不折入 Feature B——
                # 以免与 total_judgments（已在 LLM 判定路径计数一次）重复计数。
                self._stats["replies_triggered"] += 1
                return {
                    "should_interrupt": False,
                    "should_reply": True,
                    "reply_content": "",
                }
            return {
                "should_interrupt": False,
                "should_reply": result.get("should_reply", False),
                "reply_content": result.get("reply_content", "")
            }

        return {"should_interrupt": False, "should_reply": False}

    async def _check_can_interrupt(self, asr_text: str, is_final: bool) -> dict:
        # 独立小模型模式：只输出标记，不占用主 LLM 并发槽
        if self.mode == "independent_llm":
            return await self._check_with_independent_llm(asr_text, is_final)

        try:
            # 注入结构化判定指令：主 LLM 也输出三态标记（CONTINUE/IGNORE/INTERRUPT），
            # 打断时直接输出插话内容，不打断时只输出标记（符合"按模式区分"设计）
            judgment_prompt = self._build_interrupt_prompt(asr_text, is_final)
            response_text = await self._call_main_llm(judgment_prompt)
            if response_text is None:
                return {"decision": "IGNORE", "can_interrupt": False, "should_reply": False}
            return self._parse_interrupt_response(response_text, is_final)

        except Exception as e:
            logger.error(f"Failed to check can interrupt: {e}")
            return {"decision": "IGNORE", "can_interrupt": False, "should_reply": False}

    async def _check_with_independent_llm(self, asr_text: str, is_final: bool) -> dict:
        """独立小模型判定：只输出 INTERRUPT/IGNORE/CONTINUE 标记，不生成回复内容。

        回复内容由主 pipeline 生成（独立模式命中打断后仅停 TTS 让位，不再额外播 reply）。
        """
        if not self.independent_llm_config.get("enabled"):
            logger.info("independent_llm 未启用，跳过插话判定")
            return {"decision": "IGNORE", "can_interrupt": False, "should_reply": False, "reply_content": ""}

        result = await self._call_independent_llm(asr_text)
        decision = result.get("decision", "IGNORE")

        if decision == "INTERRUPT":
            return {"decision": "INTERRUPT", "can_interrupt": True, "should_reply": True, "reply_content": ""}
        if decision == "CONTINUE":
            # 用户还在组织语言：不打断，继续等待
            return {"decision": "CONTINUE", "can_interrupt": False, "should_reply": False, "reply_content": ""}
        return {"decision": "IGNORE", "can_interrupt": False, "should_reply": False, "reply_content": ""}

    def _build_independent_prompt(self, asr_text: str) -> str:
        """独立小模型判定 prompt：只输出 INTERRUPT/IGNORE/CONTINUE 标记，不生成回复内容。"""
        return f"""你是一个语音插话判断助手。请根据规则判断用户的语音输入：

【用户语音】
{asr_text}

【判断规则】
- CONTINUE：用户还在组织语言，没说完，不要打断
- IGNORE：用户在自言自语或情绪表达，不需要 Agent 插话
- INTERRUPT：用户明确提问或需要 Agent 立即互动，可以插话

请严格返回 JSON 格式：
{{"decision": "CONTINUE|IGNORE|INTERRUPT", "reason": "判断原因"}}"""

    def _build_interrupt_prompt(self, asr_text: str, is_final: bool) -> str:
        status = "用户说完了" if is_final else "用户正在说话"

        return f"""你是一个语音交互助手。{status}，你需要判断是否需要插话回复。

【用户说的话】
{asr_text}

【判断规则】
- CONTINUE：用户还在组织语言、没说完，或正在思考、停顿中，继续等待，不要打断
- IGNORE：用户自言自语、情绪表达、抱怨、感慨或发泄（如"唉，好累啊""今天真烦""累死了"），
  纯属陈述或情感宣泄，不是对 Agent 的提问或请求——即使内容显得"需要安慰"，只要用户没有
  直接向 Agent 提出请求，一律 IGNORE，不要插话
- INTERRUPT：用户明确提问（含"吗/呢/什么/怎么/为什么/哪里/谁/？"）或明确请求
  Agent 做某事（命令式、祈使句，如"帮我查一下""告诉我"），可以立即插话回复

【边界提示（必须遵守）】
- 感叹句 / 无主语感慨（"好累""真麻烦""天啊""累死了"）一律判 IGNORE，无论语气多强烈
- 情绪倾诉（"我今天好累""我好难过"）是倾诉不是请求，判 IGNORE，除非用户明确问"你觉得呢"类
- 停顿中的半句话（"我想问一下…""嗯…"）判 CONTINUE，等用户说完
- 完整问句 / 祈使请求（"明天几点？""帮我查一下天气"）判 INTERRUPT
- 拿不准时优先 IGNORE 或 CONTINUE，宁可等一等也不打断用户

【输出格式】严格返回 JSON：
{{"decision": "CONTINUE|IGNORE|INTERRUPT", "reply_content": "当 decision 为 INTERRUPT 时，这是你要插话说出的内容（简短口语）；否则为空字符串", "reason": "判断原因"}}"""

    def _parse_interrupt_response(self, response_text: str, is_final: bool) -> dict:
        try:
            json_start = response_text.find('{')
            json_end = response_text.rfind('}') + 1

            if json_start >= 0 and json_end > json_start:
                json_str = response_text[json_start:json_end]
                result = json.loads(json_str)

                decision = result.get("decision", "CONTINUE")
                reply_content = result.get("reply_content", "")

                # 三态标记映射：INTERRUPT → 打断并播内容；CONTINUE/IGNORE → 不打断
                if decision == "INTERRUPT":
                    return {
                        "decision": "INTERRUPT",
                        "can_interrupt": True,
                        "should_reply": True,
                        "reply_content": reply_content,
                        "reason": result.get("reason", ""),
                    }
                return {
                    "decision": decision,  # CONTINUE / IGNORE
                    "can_interrupt": False,
                    "should_reply": False,
                    "reply_content": "",
                    "reason": result.get("reason", ""),
                }
        except json.JSONDecodeError:
            pass

        question_indicators = ["？", "?", "吗", "呢", "什么", "怎么", "为什么", "哪里", "谁"]
        has_question = any(indicator in response_text for indicator in question_indicators)

        return {
            "decision": "INTERRUPT" if has_question else "CONTINUE",
            "can_interrupt": has_question,
            "should_reply": has_question,
            "reply_content": "",
            "reason": "从文本推断"
        }

    def _has_question_or_request(self, text: str) -> bool:
        """确定性提问/请求意图闸门（Feature A，O2 共享）。

        累计 utterance 文本含任一提问词或祈使请求模式即判定为 True。
        先剔除"非问句固定搭配"（如"什么都不/没什么/还没呢/哪里哪里/没办法嘛"——
        含疑问/请求字但实为陈述、客套或情绪填充），再作子串匹配，避免误判为需回复。
        供 Feature A（LLM-INTERRUPT 二次确认）与
        Feature B（is_final 完整请求回复触发）复用，避免两触发路径边界漂移。
        """
        normalized = (text or "").replace(" ", "").replace("\u3000", "")
        if not normalized:
            return False
        for phrase in _NON_QUESTION_PHRASES:
            normalized = normalized.replace(phrase, "")
        if not normalized:
            return False
        return any(w in normalized for w in _QUESTION_WORDS) or any(
            w in normalized for w in _REQUEST_WORDS
        )

    async def interrupt_user(self, reply_content: str = "") -> bool:
        """执行打断用户动作：触发打断回调，可选播报插话回应。"""
        logger.info(f"Agent interrupting user with reply: {reply_content[:50]}...")

        await self._invoke_callback(self._interrupt_user_callback)

        self._user_state.is_speaking = False

        if reply_content:
            await self._invoke_callback(self._start_tts_callback, reply_content)

        return True

    @property
    def is_user_speaking(self) -> bool:
        """返回用户当前是否正在说话。"""
        return self._user_state.is_speaking

    @property
    def user_current_text(self) -> str:
        """返回用户当前说话文本。"""
        return self._user_state.current_text


def _inject_agent_interrupt_context(module: "AgentInterruptUser", client_id: Optional[str]) -> None:
    """H1 注入层（组装点）：把全局 ContextManager 单例与当前会话 id 绑定到打断模块。

    与 asr_interrupt 同构：基类 ``_context_manager/_session_id`` 此前全仓无注入点，
    主 LLM 判定经 ``_get_context()`` 读取会话历史时恒为空列表 → 判定丢失上下文。
    本模块自身不写回上下文（写回由主管线负责），注入失败仅降级不阻断创建。
    """
    try:
        if getattr(module, "_context_manager", None) is None:
            from server.services.context_manager import get_context_manager

            module.set_context_manager(get_context_manager())
        if getattr(module, "_session_id", None) is None and client_id:
            module.set_session_id(client_id)
    except Exception as e:  # noqa: BLE001 - 组装层兜底，不让注入失败拖垮模块创建
        logger.warning("Agent 打断模块上下文注入失败（判定上下文降级为空）: %s", e)


def get_agent_interrupt_module(client_id: Optional[str] = None) -> AgentInterruptUser:
    """返回 AgentInterruptUser 模块单例。

    未指定 client_id：返回全局默认单例（向后兼容）。
    指定 client_id：返回该客户端的独立实例，使各会话的说话时序、冷却、
    _user_state 等状态互不串扰（per-client 并发隔离）。
    创建/复用实例时按 H1 修复注入 ContextManager 与 per-client session_id。
    """
    if client_id is None:
        instance = AgentInterruptUser.get_instance()
        _inject_agent_interrupt_context(instance, None)
        return instance
    if client_id not in _agent_interrupt_instances:
        instance = AgentInterruptUser()
        _inherit_agent_config(AgentInterruptUser.get_instance(), instance)
        _agent_interrupt_instances[client_id] = instance
    instance = _agent_interrupt_instances[client_id]
    _inject_agent_interrupt_context(instance, client_id)
    return instance


def release_agent_interrupt_module(client_id: str) -> None:
    """释放指定客户端的 AgentInterruptUser 实例（不影响其它客户端与默认单例）。"""
    _agent_interrupt_instances.pop(client_id, None)


def _inherit_agent_config(src: AgentInterruptUser, dst: AgentInterruptUser) -> None:
    """从默认单例复制配置到新创建的 per-client 实例，保持全局配置一致。"""
    dst.enabled = src.enabled
    dst.mode = src.mode
    dst.min_speech_duration_ms = src.min_speech_duration_ms
    dst._interrupt_cooldown_ms = src._interrupt_cooldown_ms
    dst.speech_end_fallback = src.speech_end_fallback
    dst.question_intent_required = src.question_intent_required
    dst.reply_on_final_question = src.reply_on_final_question
    dst.independent_llm_config = dict(src.independent_llm_config)


# per-client 打断模块注册表（client_id -> 独立实例）
_agent_interrupt_instances: dict = {}
