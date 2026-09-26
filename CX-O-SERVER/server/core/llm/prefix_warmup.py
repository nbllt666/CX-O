"""Agent 语音前缀 KV cache 预热器（第 1 项"非 default agent 冷启动"修复）。

背景
----
服务端启动预热（main.py::_warm_voice_prefix）只预热 ``default`` agent 的
system_prompt 前缀；EvalKit 自建的一次性 eval agent 与用户新建的自定义 agent
首次实时语音会话前缀不在 vLLM cache，需全量 prefill（~2747 tokens），
致 TTFT 多付 ~320ms（全新前缀 395ms vs 同前缀重放 78ms，证据见留痕文档
``.trae/documents/20260919_模块0_修复评测客户端建连开销.md`` 第五章）。

本模块提供统一的单 agent 前缀预热实现，供两处复用：
- 启动预热（main.py）：遍历全部已有 agent 后台预热（覆盖重启后已有 agent）；
- 创建/更新（agents.py）：create/update 落盘后非阻塞触发（覆盖新建/更新 agent）。

预热目标按 agent 的 ``model`` 经 ``config.models`` 解析（与
``get_llm_client_for_agent`` 同口径：main/summary/memory 当前均指向同一 vLLM
端点），仅发送预请求建 cache，不写任何数据；失败静默不阻塞调用方。
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Tuple

from server.core.logging_config import get_contextual_logger
from server.core.utils import get_shared_http_client
from server.prompt_builder import REALTIME_VOICE_PROMPT_PADDING

logger = get_contextual_logger(__name__)

# 单 agent 预热轮数：首轮建立前缀 KV cache，后续轮次容错（瞬时失败不放弃）。
# 远小于 default 的 10 轮——Triton JIT kernel shape 已由启动时的 default 预热建立，
# 此处只需写入该 agent 独有的前缀 cache。
WARM_ROUNDS = 3

_PROBE_TEXT = "你好"

# 后台任务强引用集：防止 asyncio.create_task 的任务被 GC 中途回收（同 main.py A1）。
_background_tasks: set[asyncio.Task] = set()

# 跨调用游标（限流配套）：单轮上限下逐批推进预热目标，避免"每次从 0 开始"导致
# 靠后的 agent 永远不被预热；走到末尾后归零并视为完成一轮。
_warm_cursor = 0

_MODEL_TYPES = ("main", "summary", "memory", "dream")

# ---------------------------------------------------------------------------
# 限流参数（2026-09-25 全双工首包后置停滞修复）
# 实测：一次性顺序预热 20 个 agent（每个为一次全量 prefill）会让 vLLM 单步
# 长间隔达 90~180s（引擎日志 470 tok/s 吞吐后置），期间实时语音首包被拖住
# ~4~5.4s（EvalKit 全双工段 P95 因此翻转）。故对预热施加三重限流：
#   1) 活体让行：检测到在线语音会话即中止本轮，交回 main.py 自愈循环（60s 后重试）；
#   2) 单轮上限：每次调用最多预热 MAX_AGENTS_PER_ROUND 个 agent；
#   3) 错峰间隔：相邻 agent 之间留出呼吸窗口，供在线请求调度。
# ---------------------------------------------------------------------------
MAX_AGENTS_PER_ROUND = 6
INTER_AGENT_DELAY_SECONDS = 0.5
# 创建/更新触发的单 agent 预热：最多等待在线空闲的秒数（超时后仍执行，保证预热语义）
MAX_IDLE_WAIT_SECONDS = 20.0


def _live_voice_active() -> bool:
    """当前是否有在线实时语音（让行判据）。

    判据取 handlers.audio 的两个模块级注册表：存在双流式会话（WS 已连接）
    或正在播报 TTS，即视为有活体流量。导入置于函数内避免模块级循环依赖。
    """
    try:
        from server.handlers import audio as _audio_mod

        if getattr(_audio_mod, "_dual_stream_sessions", None):
            return True
        return bool(getattr(_audio_mod, "_tts_playing_clients", None))
    except Exception:
        return False


def _on_task_done(task: asyncio.Task) -> None:
    """后台任务收尾：移出强引用集并消费异常（避免 Task exception was never retrieved）。"""
    _background_tasks.discard(task)
    if task.cancelled():
        return
    _exc = task.exception()
    if _exc is not None:
        logger.debug("agent 前缀预热后台任务异常: %s", _exc)


def build_voice_prefix_messages(
    system_prompt: str, user_text: str = _PROBE_TEXT
) -> List[Dict[str, Any]]:
    """构造与生产 ``build_messages(is_realtime_voice=True)`` 同构的稳定前缀。

    system 末尾追加 REALTIME_VOICE_PROMPT_PADDING（含 prefix-cache padding 与
    回应边界），使完整 prompt 满足 vLLM prefix cache 写入/命中长度（>=353 tokens）
    阈值。仅追加、不精简生产内容，语义无害。
    """
    return [
        {"role": "system", "content": system_prompt.strip() + REALTIME_VOICE_PROMPT_PADDING},
        {"role": "user", "content": user_text},
    ]


def _resolve_target(agent: Dict[str, Any]) -> Tuple[str, str]:
    """解析该 agent 实时语音实际会走的 (host, model)。

    与 ``get_llm_client_for_agent`` 同口径：model 为 main/summary/memory/dream
    时取 ``config.models`` 对应节；为具体模型名时沿用 main 的 host + 该模型名。
    解析失败回退全局 ``config.llm``（与启动预热原实现一致）。
    """
    from server.config import get_settings

    _settings = get_settings()
    _fallback = (_settings.config.llm.host.rstrip("/"), _settings.config.llm.model)
    _model = str(agent.get("model") or "main").strip()
    try:
        _cfg = _settings.config.models.get_model_config(
            _model.lower() if _model.lower() in _MODEL_TYPES else "main"
        )
        if not _cfg or not _cfg.host:
            return _fallback
        _name = _cfg.model if _model.lower() in _MODEL_TYPES else _model
        return _cfg.host.rstrip("/"), (_name or _fallback[1])
    except Exception as _e:
        logger.debug("解析 agent 预热目标失败，回退全局 llm 配置: %s", _e)
        return _fallback


async def _run_single(agent: Dict[str, Any], rounds: int = WARM_ROUNDS) -> bool:
    """发送流式预请求，建立该 agent system_prompt 前缀的 KV cache。

    rounds 为最大尝试次数：首轮成功即返回——重复发送同一请求不会带来额外预热
    （Triton kernel 按 shape 编译一次，KV cache 首轮 prefill 即写入），
    多轮仅用于瞬时失败重试。启动时遍历 19 个 agent 实测 28s → 10s 量级。
    """
    _system_prompt = (agent.get("system_prompt") or "").strip()
    if not _system_prompt:
        return True  # 无内容可预热，视为完成（不阻塞启动自愈循环）
    _host, _model = _resolve_target(agent)
    _client = get_shared_http_client()
    _msgs = build_voice_prefix_messages(_system_prompt)
    # 修复 3（2026-09-26）：与语音生产路径同形——audio.py::_resolve_voice_tools() 恒带
    # get_tools_for_agent() 全量工具，而 vLLM 前缀缓存按「从头对齐的 token 块」哈希：
    # 不带 tools 的预热块与生产请求的块边界整体位移 → 永不命中（实测新建 agent 首轮
    # 前缀缓存命中仅 44.7%，首 token 640ms vs 常态 ~90ms）。此处补齐同源同口径 tools。
    _tools: Optional[list] = None
    try:
        from server.chat_helpers import get_tools_for_agent

        _tools = get_tools_for_agent() or None
    except Exception as _e:  # noqa: BLE001 —— 取不到工具时退回无 tools 预热（命中率可能下降）
        logger.debug("预热 tools 解析失败，按无 tools 预热: %s", _e)
    _payload: Dict[str, Any] = {
        "model": _model,
        "messages": _msgs,
        "stream": True,
        "max_tokens": 32,
    }
    if _tools:
        _payload["tools"] = _tools
    for _ in range(max(1, rounds)):
        try:
            async with _client.stream(
                "POST", f"{_host}/v1/chat/completions",
                json=_payload,
                timeout=30.0,
            ) as _resp:
                if _resp.status_code != 200:
                    continue
                async for _chunk in _resp.aiter_bytes():
                    pass
                return True
        except Exception as _e:
            logger.debug("agent 前缀预热请求失败 (agent=%s): %s", agent.get("id"), _e)
            continue
    return False


async def warm_agents_prefixes(
    agents: Optional[List[Dict[str, Any]]] = None, rounds: int = WARM_ROUNDS
) -> bool:
    """顺序预热全部 agent 的前缀（启动预热入口），全部命中才返回 True。

    agents 为 None 时从 agent_store 读取全量（唯一真相源）。顺序而非并发：
    单个 agent 预热是一次全量 prefill，并发会争抢 GPU 反而拉长总时长；
    后台任务中执行，耗时可接受。无 agent / 全部无 system_prompt → True。
    """
    if agents is None:
        from server.core.agent_store import load_agents

        agents = load_agents()
    _targets = [a for a in agents if (a.get("system_prompt") or "").strip()]
    if not _targets:
        logger.info("语音前缀预热跳过：无带 system_prompt 的 agent")
        return True
    global _warm_cursor
    _total = len(_targets)
    if _warm_cursor >= _total:
        _warm_cursor = 0  # 上一轮已走完：开启新一轮（供自愈循环判定完成）
    _batch = _targets[_warm_cursor : _warm_cursor + MAX_AGENTS_PER_ROUND]
    _ok = 0
    for _agent in _batch:
        # 限流 1/3：活体让行——有在线语音会话即中止本轮，交回自愈循环稍后重试
        # （不推进游标：下次自本批开头重试，保证不漏预 Warm）
        if _live_voice_active():
            logger.info(
                "语音前缀预热让行：检测到在线语音会话，当前批剩余 %s 个延后（自愈循环将重试）",
                len(_batch) - _batch.index(_agent),
            )
            return False
        if await _run_single(_agent, rounds=rounds):
            _ok += 1
        # 限流 3/3：错峰间隔——给在线请求留出调度窗口
        await asyncio.sleep(INTER_AGENT_DELAY_SECONDS)
    _warm_cursor += len(_batch)
    _done = _warm_cursor >= _total
    logger.info(
        "语音前缀预热：本轮 %s/%s 个成功（累计推进 %s/%s，单轮上限 %s，最多 %s 轮/agent，含 prefix-cache padding）",
        _ok, len(_batch), _warm_cursor, _total, MAX_AGENTS_PER_ROUND, rounds,
    )
    return _done and _ok == len(_batch)


async def _warm_when_idle(agent: Dict[str, Any], rounds: int) -> None:
    """活体让行（限流）：在线语音活动时最多等 MAX_IDLE_WAIT_SECONDS 再预热。

    单 agent 预热 = 一次全量 prefill（实测约 5s GPU 占用），与在线会话并发会让
    语音首包被拖住。等待有界：超时后仍执行，保证预热语义不被无限推迟。
    """
    _waited = 0.0
    while _live_voice_active() and _waited < MAX_IDLE_WAIT_SECONDS:
        await asyncio.sleep(0.5)
        _waited += 0.5
    if _waited > 0:
        logger.debug("agent 前缀预热让行 %.1fs 后执行 (agent=%s)", _waited, agent.get("id"))
    await _run_single(agent, rounds=rounds)


def warm_agent_prefix_background(agent: Dict[str, Any], rounds: int = WARM_ROUNDS) -> bool:
    """非阻塞触发单 agent 前缀预热（创建/更新落盘后调用）。

    返回是否需要预热（False 表示无 system_prompt 可跳过）；实际预热在后台任务执行，
    调用方不等待，失败静默。

    无运行事件循环时（同步上下文 / 测试的同步调用路径）直接跳过：`asyncio.create_task`
    在无 loop 时会抛 `RuntimeError`，而调用方位于「已落盘」之后的收尾段——若冒泡到
    端点的 `except Exception` 会造成"数据已写入却返回 500"的半提交语义。预热是可选的
    性能优化，此场景下静默跳过比报错更符合语义。
    """
    if not (agent.get("system_prompt") or "").strip():
        return False
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        logger.debug("无运行事件循环，跳过 agent 前缀预热 (agent=%s)", agent.get("id"))
        return False
    try:
        _task = asyncio.create_task(_warm_when_idle(agent, rounds))
    except Exception as _e:  # noqa: BLE001 —— 预热失败不得影响已完成的写操作
        logger.debug("agent 前缀预热任务创建失败 (agent=%s): %s", agent.get("id"), _e)
        return False
    _background_tasks.add(_task)
    _task.add_done_callback(_on_task_done)
    return True