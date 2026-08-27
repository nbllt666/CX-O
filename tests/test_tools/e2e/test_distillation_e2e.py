"""DistillationService 蒸馏服务端到端测试（spec migrate-cxhms-radix-acp-multimodal Task D5.1）。

测试目标：验证 CX-O-SERVER 蒸馏服务的 9 状态机推进、回环、拒绝分支与多模态输入处理。

9 状态机：
    S_INIT → S_PREREAD → S_QUESTION → S_REFLECT → S_CROSSVALIDATE
           → S_EXTRACT → S_STORAGE_DECISION → S_FINALIZE / S_REJECT

测试场景：
    1. test_happy_path             — 完整正常推进至 S_FINALIZE（覆盖 7 个非终态 + S_FINALIZE）
    2. test_reflect_question_loop  — S_REFLECT → S_QUESTION 回环（D4_REDISTILL 决策）
    3. test_reject_branch           — S_REJECT 分支（finalize override_decision="reject"）
    4. test_multimodal_input        — 多模态 artifact 输入（character_card/image/video/audio）
    5. test_natural_reject          — 自然 S_REJECT 路径（S_STORAGE_DECISION → S_REJECT，OBS-6 方案 C LLM 评估重构新增）

API 端点（4 单次 + 5 批量，本测试覆盖 4 单次端点）：
    - POST /api/v1/distillation/start                  — 启动蒸馏会话
    - POST /api/v1/distillation/{session_id}/advance   — 推进蒸馏状态机
    - POST /api/v1/distillation/{session_id}/finalize  — 终结蒸馏会话
    - GET  /api/v1/distillation/{session_id}          — 查询会话状态

退出码约定（与 run_e2e_tests.py 对齐）：
    0  = PASS（全部场景通过）
    77 = SKIP（CX-O-SERVER 不可达）
    1  = FAIL（任一场景失败）

用法:
    python tests/test_tools/e2e/test_distillation_e2e.py
    python tests/test_tools/e2e/test_distillation_e2e.py --probe   # 仅探测服务可达性

参考:
    - 契约: public/interface_stub/distillation_service.pyi
    - 契约: public/schema/distillation_session.schema.json
    - 实现: CX-O-SERVER/server/core/distillation/distillation_service.py
    - 路由: CX-O-SERVER/server/core/distillation/api/routes.py
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import requests

# --------------------------------------------------------------------------- #
# 服务地址与超时配置（与 test_asr_llm_tts_latency.py 端口配置一致）
# --------------------------------------------------------------------------- #
# D5.1 任务规范：CX-O-SERVER HTTP 端口 8001
CXO_SERVER_HTTP = os.environ.get("CXO_SERVER_HTTP", "http://127.0.0.1:8001")
HEALTH_CHECK_URL = f"{CXO_SERVER_HTTP}/health"
DISTILLATION_BASE = f"{CXO_SERVER_HTTP}/api/v1/distillation"

# HTTP 超时（秒）
HTTP_TIMEOUT = 15.0
# 单步推进间隔（秒），避免过快请求压垮服务
ADVANCE_INTERVAL = 0.1

# 9 状态机常量（与 distillation_session.schema.json enum 一致）
STATE_INIT = "S_INIT"
STATE_PREREAD = "S_PREREAD"
STATE_QUESTION = "S_QUESTION"
STATE_REFLECT = "S_REFLECT"
STATE_CROSSVALIDATE = "S_CROSSVALIDATE"
STATE_EXTRACT = "S_EXTRACT"
STATE_STORAGE_DECISION = "S_STORAGE_DECISION"
STATE_FINALIZE = "S_FINALIZE"
STATE_REJECT = "S_REJECT"

# 终态集合
TERMINAL_STATES = {STATE_FINALIZE, STATE_REJECT}

# agent_action 枚举（与 distillation_session.schema.json turn.agent_action 一致）
ACTIONS = {
    "ask_user", "proceed", "reflect", "cross_validate",
    "extract", "decide", "finalize", "reject",
}


# --------------------------------------------------------------------------- #
# 数据结构
# --------------------------------------------------------------------------- #
@dataclass
class ScenarioResult:
    """单场景测试结果。"""

    name: str
    description: str
    passed: bool
    state_path: List[str] = field(default_factory=list)
    action_path: List[str] = field(default_factory=list)
    assertions: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None
    elapsed_ms: float = 0.0


@dataclass
class TestReport:
    """测试报告。"""

    service_status: Dict[str, Any] = field(default_factory=dict)
    scenarios: List[ScenarioResult] = field(default_factory=list)
    skipped: bool = False
    skip_reason: Optional[str] = None

    def passed_count(self) -> int:
        return sum(1 for s in self.scenarios if s.passed)

    def failed_count(self) -> int:
        return sum(1 for s in self.scenarios if not s.passed)


# --------------------------------------------------------------------------- #
# 服务探测
# --------------------------------------------------------------------------- #
def probe_cxo_server(timeout: float = 5.0) -> Tuple[bool, str]:
    """探测 CX-O-SERVER (8001) 可达性。

    Returns:
        (ok, message) — ok=True 时 message 为 HTTP 状态描述，ok=False 时为失败原因
    """
    try:
        resp = requests.get(
            HEALTH_CHECK_URL,
            timeout=timeout,
            proxies={"http": None, "https": None},
        )
        if resp.status_code < 500:
            return True, f"HTTP {resp.status_code}"
        return False, f"HTTP {resp.status_code}"
    except requests.ConnectionError:
        return False, f"连接失败: ConnectionError (URL={HEALTH_CHECK_URL})"
    except requests.Timeout:
        return False, f"超时 (>{timeout}s)"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def probe_distillation_endpoint(timeout: float = 5.0) -> Tuple[bool, str]:
    """探测蒸馏 API 路由是否注册。

    使用一个全零 UUID 探测 GET /{session_id}：
        - 404 = 路由已注册，session 不存在（符合契约 KeyError → 404）
        - 404 之外的 4xx/5xx = 路由可能未注册或服务异常

    Returns:
        (ok, message) — 路由已注册返回 True
    """
    probe_url = f"{DISTILLATION_BASE}/00000000-0000-0000-0000-000000000000"
    try:
        resp = requests.get(
            probe_url,
            timeout=timeout,
            proxies={"http": None, "https": None},
        )
        # 404 = 路由存在但 session 不存在；其他 4xx/5xx 可能表征路由未注册
        if resp.status_code == 404:
            return True, "路由已注册（返回 404 = session 不存在，符合契约）"
        if resp.status_code < 400:
            return True, f"HTTP {resp.status_code}（意外成功响应）"
        return False, f"HTTP {resp.status_code}: {resp.text[:200]}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


# --------------------------------------------------------------------------- #
# API 客户端封装
# --------------------------------------------------------------------------- #
class DistillationClient:
    """蒸馏服务 HTTP 客户端。封装 4 个单次端点。"""

    def __init__(self, base_url: str = DISTILLATION_BASE) -> None:
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        # 禁用代理，避免环境变量污染本地服务调用
        self.session.proxies = {"http": None, "https": None}

    def start(
        self,
        source_type: str,
        template_id: str = "default",
        source_ref: Optional[str] = None,
        max_turns: int = 4,
        ask_user_on_ambiguity: bool = False,
    ) -> Tuple[int, Dict[str, Any]]:
        """POST /start — 启动蒸馏会话。

        Returns:
            (status_code, response_json) — 失败时 response_json 含 detail 字段
        """
        payload = {
            "source_type": source_type,
            "source_ref": source_ref,
            "template_id": template_id,
            "max_turns": max_turns,
            "ask_user_on_ambiguity": ask_user_on_ambiguity,
        }
        resp = self.session.post(
            f"{self.base_url}/start",
            json=payload,
            timeout=HTTP_TIMEOUT,
        )
        try:
            data = resp.json()
        except ValueError:
            data = {"_raw_text": resp.text}
        return resp.status_code, data

    def advance(
        self,
        session_id: str,
        user_response: Optional[str] = None,
    ) -> Tuple[int, Dict[str, Any]]:
        """POST /{session_id}/advance — 推进蒸馏状态机一步。"""
        payload = {"user_response": user_response}
        resp = self.session.post(
            f"{self.base_url}/{session_id}/advance",
            json=payload,
            timeout=HTTP_TIMEOUT,
        )
        try:
            data = resp.json()
        except ValueError:
            data = {"_raw_text": resp.text}
        return resp.status_code, data

    def finalize(
        self,
        session_id: str,
        override_decision: Optional[str] = None,
    ) -> Tuple[int, Dict[str, Any]]:
        """POST /{session_id}/finalize — 终结蒸馏会话。"""
        payload = {"override_decision": override_decision}
        resp = self.session.post(
            f"{self.base_url}/{session_id}/finalize",
            json=payload,
            timeout=HTTP_TIMEOUT,
        )
        try:
            data = resp.json()
        except ValueError:
            data = {"_raw_text": resp.text}
        return resp.status_code, data

    def get_status(self, session_id: str) -> Tuple[int, Dict[str, Any]]:
        """GET /{session_id} — 查询会话状态。"""
        resp = self.session.get(
            f"{self.base_url}/{session_id}",
            timeout=HTTP_TIMEOUT,
        )
        try:
            data = resp.json()
        except ValueError:
            data = {"_raw_text": resp.text}
        return resp.status_code, data

    def close(self) -> None:
        """关闭底层 HTTP 会话。"""
        self.session.close()


# --------------------------------------------------------------------------- #
# 断言辅助
# --------------------------------------------------------------------------- #
def _assert(
    result: ScenarioResult,
    condition: bool,
    description: str,
    evidence: Optional[Dict[str, Any]] = None,
) -> None:
    """记录断言结果。condition=False 时标记场景失败。"""
    result.assertions.append({
        "description": description,
        "passed": condition,
        "evidence": evidence or {},
    })
    if not condition:
        if result.error is None:
            result.error = f"断言失败: {description}"
        else:
            result.error += f"; 断言失败: {description}"


def _advance_and_assert(
    client: DistillationClient,
    result: ScenarioResult,
    session_id: str,
    user_response: Optional[str],
    expected_state: str,
    expected_action: Optional[str] = None,
    step_label: str = "",
) -> Optional[Dict[str, Any]]:
    """推进状态机并断言新状态。

    Returns:
        成功时返回 advance 响应 JSON，失败时返回 None（断言已记录到 result）
    """
    status, data = client.advance(session_id, user_response=user_response)
    label = f"[{step_label}] " if step_label else ""
    if status != 200:
        _assert(
            result, False,
            f"{label}advance 应返回 200，实际 {status}",
            {"response": data},
        )
        return None

    current_state = data.get("current_state")
    agent_action = data.get("agent_action")
    next_needed = data.get("next_needed")

    result.state_path.append(current_state or "?")
    result.action_path.append(agent_action or "?")

    _assert(
        result,
        current_state == expected_state,
        f"{label}advance 后状态应为 {expected_state}，实际 {current_state}",
        {"response": data},
    )
    if expected_action is not None:
        _assert(
            result,
            agent_action == expected_action,
            f"{label}advance 后 agent_action 应为 {expected_action}，实际 {agent_action}",
            {"response": data},
        )
    if agent_action is not None:
        _assert(
            result,
            agent_action in ACTIONS,
            f"{label}agent_action 应在合法枚举内，实际 {agent_action}",
            {"valid_actions": sorted(ACTIONS)},
        )

    # next_needed 必须是布尔
    _assert(
        result,
        isinstance(next_needed, bool),
        f"{label}next_needed 应为 bool，实际 {type(next_needed).__name__}",
        {"next_needed": next_needed},
    )

    return data


# --------------------------------------------------------------------------- #
# 场景 1：完整正常推进至 S_FINALIZE（Happy Path）
# --------------------------------------------------------------------------- #
def test_happy_path(client: DistillationClient) -> ScenarioResult:
    """完整状态机推进：S_PREREAD → S_QUESTION → S_REFLECT → S_CROSSVALIDATE
    → S_EXTRACT → S_STORAGE_DECISION → S_FINALIZE。

    策略：
        - ask_user_on_ambiguity=False：避免 D3 触发 ask_user 卡住推进
        - max_turns=4：使用默认值（与 DistillationConfig 默认一致）
        - 通过 user_response="继续" 推进 S_QUESTION → S_REFLECT（绕过 ask_user）
        - 在 S_REFLECT 状态，D4 决策：redistill_count=0 < max_redistill_turns=2
          但 current_turn_index=4 不 < max_turns=4，故 can_redistill=False → proceed
    """
    result = ScenarioResult(
        name="happy_path",
        description="完整 7 状态推进至 S_FINALIZE（覆盖状态机主路径）",
        passed=True,
    )
    t_start = time.monotonic()

    try:
        # 步骤 1：启动会话（start 后进入 S_PREREAD）
        status, data = client.start(
            source_type="text",
            source_ref="测试文本：用于验证蒸馏状态机正常推进的输入数据。",
            template_id="default",
            max_turns=4,
            ask_user_on_ambiguity=False,
        )
        _assert(
            result, status == 200,
            f"start 应返回 200，实际 {status}",
            {"response": data},
        )
        if status != 200:
            return result

        session_id = data.get("session_id")
        initial_state = data.get("initial_state")
        preread_summary = data.get("preread_summary")

        _assert(result, bool(session_id), "session_id 非空", {"session_id": session_id})
        _assert(
            result, initial_state == STATE_PREREAD,
            f"initial_state 应为 S_PREREAD，实际 {initial_state}",
            {"initial_state": initial_state},
        )
        _assert(
            result, isinstance(preread_summary, str) and len(preread_summary) > 0,
            "preread_summary 应为非空字符串",
            {"preread_summary_length": len(preread_summary) if preread_summary else 0},
        )

        result.state_path.append(STATE_PREREAD)
        result.action_path.append("proceed")

        # 步骤 2：S_PREREAD → S_QUESTION
        time.sleep(ADVANCE_INTERVAL)
        _advance_and_assert(
            client, result, session_id,
            user_response="继续",
            expected_state=STATE_QUESTION,
            expected_action="proceed",
            step_label="step2",
        )

        # 步骤 3：S_QUESTION → S_REFLECT
        time.sleep(ADVANCE_INTERVAL)
        _advance_and_assert(
            client, result, session_id,
            user_response="继续",
            expected_state=STATE_REFLECT,
            expected_action="proceed",
            step_label="step3",
        )

        # 步骤 4：S_REFLECT → S_CROSSVALIDATE（不回环，因 current_turn_index=4 不 < max_turns=4）
        time.sleep(ADVANCE_INTERVAL)
        _advance_and_assert(
            client, result, session_id,
            user_response=None,
            expected_state=STATE_CROSSVALIDATE,
            expected_action="proceed",
            step_label="step4",
        )

        # 步骤 5：S_CROSSVALIDATE → S_EXTRACT
        time.sleep(ADVANCE_INTERVAL)
        # cross_validate_sources 默认空 → should_cross_validate=False → action=proceed
        _advance_and_assert(
            client, result, session_id,
            user_response=None,
            expected_state=STATE_EXTRACT,
            step_label="step5",
        )

        # 步骤 6：S_EXTRACT → S_STORAGE_DECISION
        time.sleep(ADVANCE_INTERVAL)
        _advance_and_assert(
            client, result, session_id,
            user_response=None,
            expected_state=STATE_STORAGE_DECISION,
            expected_action="extract",
            step_label="step6",
        )

        # 步骤 7：S_STORAGE_DECISION → S_FINALIZE
        # quality_score = 0.6 + min(7*0.05, 0.2) + min(preread_len/1000, 0.2)
        #              = 0.6 + 0.2 + (0.0~0.2) >= 0.8 > 0.3（quality_reject_threshold）
        # 故走 decide 路径 → S_FINALIZE
        time.sleep(ADVANCE_INTERVAL)
        _advance_and_assert(
            client, result, session_id,
            user_response=None,
            expected_state=STATE_FINALIZE,
            expected_action="decide",
            step_label="step7",
        )

        # 步骤 8：finalize 完成记忆存储
        time.sleep(ADVANCE_INTERVAL)
        f_status, f_data = client.finalize(session_id, override_decision=None)
        _assert(
            result, f_status == 200,
            f"finalize 应返回 200，实际 {f_status}",
            {"response": f_data},
        )
        if f_status == 200:
            stored = f_data.get("stored")
            location = f_data.get("location")
            _assert(
                result, stored is True,
                f"stored 应为 True（已存储），实际 {stored}",
                {"stored": stored},
            )
            _assert(
                result, location in ("memories", "permanent_memories"),
                f"location 应为 memories/permanent_memories，实际 {location}",
                {"location": location},
            )

        # 步骤 9：查询会话状态，验证 is_finalized=True
        time.sleep(ADVANCE_INTERVAL)
        g_status, g_data = client.get_status(session_id)
        _assert(
            result, g_status == 200,
            f"get_session_status 应返回 200，实际 {g_status}",
            {"response": g_data},
        )
        if g_status == 200:
            _assert(
                result, g_data.get("is_finalized") is True,
                f"is_finalized 应为 True，实际 {g_data.get('is_finalized')}",
                {"is_finalized": g_data.get("is_finalized")},
            )
            _assert(
                result, g_data.get("state") == STATE_FINALIZE,
                f"state 应为 S_FINALIZE，实际 {g_data.get('state')}",
                {"state": g_data.get("state")},
            )
            _assert(
                result, g_data.get("finalized_at") is not None,
                "finalized_at 应非空",
                {"finalized_at": g_data.get("finalized_at")},
            )
            _assert(
                result, g_data.get("quality_score") is not None,
                "quality_score 应已计算",
                {"quality_score": g_data.get("quality_score")},
            )

    except Exception as e:
        result.error = f"{type(e).__name__}: {e}"
    finally:
        result.elapsed_ms = round((time.monotonic() - t_start) * 1000, 2)
        result.passed = result.error is None and all(a["passed"] for a in result.assertions)
    return result


# --------------------------------------------------------------------------- #
# 场景 2：S_REFLECT → S_QUESTION 回环（D4_REDISTILL 决策）
# --------------------------------------------------------------------------- #
def test_reflect_question_loop(client: DistillationClient) -> ScenarioResult:
    """验证 S_REFLECT → S_QUESTION 回环逻辑。

    策略：
        - max_turns=6：允许更多轮次容纳回环
        - ask_user_on_ambiguity=False：避免 D3 触发 ask_user
        - 推进到 S_REFLECT 后，D4 判定 redistill_count=0 < max_redistill_turns=2
          且 current_turn_index=4 < max_turns=6 → can_redistill=True → action=reflect
        - 回环后状态应回到 S_QUESTION
    """
    result = ScenarioResult(
        name="reflect_question_loop",
        description="S_REFLECT → S_QUESTION 回环（D4_REDISTILL 决策驱动）",
        passed=True,
    )
    t_start = time.monotonic()

    try:
        # 启动会话
        status, data = client.start(
            source_type="text",
            source_ref="回环测试：验证 S_REFLECT → S_QUESTION 的 D4 决策回环逻辑。",
            template_id="default",
            max_turns=6,
            ask_user_on_ambiguity=False,
        )
        _assert(
            result, status == 200,
            f"start 应返回 200，实际 {status}",
            {"response": data},
        )
        if status != 200:
            return result

        session_id = data.get("session_id")
        result.state_path.append(STATE_PREREAD)
        result.action_path.append("proceed")

        # 推进到 S_QUESTION
        time.sleep(ADVANCE_INTERVAL)
        _advance_and_assert(
            client, result, session_id,
            user_response="继续",
            expected_state=STATE_QUESTION,
            expected_action="proceed",
            step_label="to_question",
        )

        # 推进到 S_REFLECT
        time.sleep(ADVANCE_INTERVAL)
        _advance_and_assert(
            client, result, session_id,
            user_response="继续",
            expected_state=STATE_REFLECT,
            expected_action="proceed",
            step_label="to_reflect",
        )

        # 在 S_REFLECT 触发回环 → S_QUESTION（action=reflect）
        # 此时 current_turn_index=4 < max_turns=6 → can_redistill=True
        time.sleep(ADVANCE_INTERVAL)
        _advance_and_assert(
            client, result, session_id,
            user_response=None,
            expected_state=STATE_QUESTION,
            expected_action="reflect",
            step_label="loop_back",
        )

        # 验证回环后的会话状态：turns 中应包含 reflect action 的 S_QUESTION turn
        time.sleep(ADVANCE_INTERVAL)
        g_status, g_data = client.get_status(session_id)
        _assert(
            result, g_status == 200,
            f"get_session_status 应返回 200，实际 {g_status}",
            {"response": g_data},
        )
        if g_status == 200:
            turns = g_data.get("turns", [])
            reflect_loop_turns = [
                t for t in turns
                if t.get("state") == STATE_QUESTION and t.get("agent_action") == "reflect"
            ]
            _assert(
                result, len(reflect_loop_turns) >= 1,
                f"turns 中应至少有 1 条 reflect-action 的 S_QUESTION 记录，实际 {len(reflect_loop_turns)}",
                {"reflect_loop_turns_count": len(reflect_loop_turns)},
            )
            _assert(
                result, g_data.get("is_finalized") is False,
                "回环后会话不应终结",
                {"is_finalized": g_data.get("is_finalized")},
            )

    except Exception as e:
        result.error = f"{type(e).__name__}: {e}"
    finally:
        result.elapsed_ms = round((time.monotonic() - t_start) * 1000, 2)
        result.passed = result.error is None and all(a["passed"] for a in result.assertions)
    return result


# --------------------------------------------------------------------------- #
# 场景 3：S_REJECT 分支（finalize override_decision="reject"）
# --------------------------------------------------------------------------- #
def test_reject_branch(client: DistillationClient) -> ScenarioResult:
    """验证 S_REJECT 分支处理。

    说明：
        - 实现中 quality_score 基础分 0.6 > quality_reject_threshold(0.3)，
          故正常推进路径下 S_STORAGE_DECISION 不会自然走 reject 路径
        - 测试通过 finalize with override_decision="reject" 触发拒绝分支
          （契约 FinalizeDistillationRequest.override_decision 支持）
        - 验证：location="rejected"，stored=False，state=S_REJECT，is_finalized=True

    测试路径：
        S_PREREAD → S_QUESTION → S_REFLECT → S_CROSSVALIDATE → S_EXTRACT
        → S_STORAGE_DECISION → finalize(override="reject") → S_REJECT
    """
    result = ScenarioResult(
        name="reject_branch",
        description="S_REJECT 分支（人类 override_decision=reject 强制拒绝存储）",
        passed=True,
    )
    t_start = time.monotonic()

    try:
        # 启动会话
        status, data = client.start(
            source_type="text",
            source_ref="拒绝分支测试：验证 S_REJECT 终态与 rejected 存储位置。",
            template_id="default",
            max_turns=4,
            ask_user_on_ambiguity=False,
        )
        _assert(
            result, status == 200,
            f"start 应返回 200，实际 {status}",
            {"response": data},
        )
        if status != 200:
            return result

        session_id = data.get("session_id")
        result.state_path.append(STATE_PREREAD)
        result.action_path.append("proceed")

        # 推进到 S_STORAGE_DECISION
        time.sleep(ADVANCE_INTERVAL)
        _advance_and_assert(
            client, result, session_id,
            user_response="继续",
            expected_state=STATE_QUESTION,
            expected_action="proceed",
            step_label="to_question",
        )
        time.sleep(ADVANCE_INTERVAL)
        _advance_and_assert(
            client, result, session_id,
            user_response="继续",
            expected_state=STATE_REFLECT,
            expected_action="proceed",
            step_label="to_reflect",
        )
        time.sleep(ADVANCE_INTERVAL)
        _advance_and_assert(
            client, result, session_id,
            user_response=None,
            expected_state=STATE_CROSSVALIDATE,
            expected_action="proceed",
            step_label="to_crossvalidate",
        )
        time.sleep(ADVANCE_INTERVAL)
        _advance_and_assert(
            client, result, session_id,
            user_response=None,
            expected_state=STATE_EXTRACT,
            step_label="to_extract",
        )
        time.sleep(ADVANCE_INTERVAL)
        _advance_and_assert(
            client, result, session_id,
            user_response=None,
            expected_state=STATE_STORAGE_DECISION,
            expected_action="extract",
            step_label="to_storage_decision",
        )

        # finalize with override_decision="reject" → 拒绝分支
        time.sleep(ADVANCE_INTERVAL)
        f_status, f_data = client.finalize(session_id, override_decision="reject")
        _assert(
            result, f_status == 200,
            f"finalize(override=reject) 应返回 200，实际 {f_status}",
            {"response": f_data},
        )
        if f_status == 200:
            stored = f_data.get("stored")
            location = f_data.get("location")
            memory_id = f_data.get("memory_id")
            reason = f_data.get("reason")

            _assert(
                result, stored is False,
                f"stored 应为 False（拒绝存储），实际 {stored}",
                {"stored": stored},
            )
            _assert(
                result, location == "rejected",
                f"location 应为 'rejected'，实际 {location}",
                {"location": location},
            )
            _assert(
                result, memory_id is None,
                f"memory_id 应为 None（拒绝时不分配），实际 {memory_id}",
                {"memory_id": memory_id},
            )
            _assert(
                result, isinstance(reason, str) and len(reason) > 0,
                "reason 应为非空字符串",
                {"reason": reason},
            )

        # 验证会话状态进入 S_REJECT 终态
        time.sleep(ADVANCE_INTERVAL)
        g_status, g_data = client.get_status(session_id)
        _assert(
            result, g_status == 200,
            f"get_session_status 应返回 200，实际 {g_status}",
            {"response": g_data},
        )
        if g_status == 200:
            _assert(
                result, g_data.get("state") == STATE_REJECT,
                f"state 应为 S_REJECT，实际 {g_data.get('state')}",
                {"state": g_data.get("state")},
            )
            _assert(
                result, g_data.get("is_finalized") is True,
                f"is_finalized 应为 True（S_REJECT 为终态），实际 {g_data.get('is_finalized')}",
                {"is_finalized": g_data.get("is_finalized")},
            )
            _assert(
                result, g_data.get("finalized_at") is not None,
                "finalized_at 应非空（已终结）",
                {"finalized_at": g_data.get("finalized_at")},
            )

        # 验证已终结会话再次 advance 应返回 409
        time.sleep(ADVANCE_INTERVAL)
        a_status, a_data = client.advance(session_id, user_response=None)
        _assert(
            result, a_status == 409,
            f"已终结会话 advance 应返回 409，实际 {a_status}",
            {"response": a_data},
        )

    except Exception as e:
        result.error = f"{type(e).__name__}: {e}"
    finally:
        result.elapsed_ms = round((time.monotonic() - t_start) * 1000, 2)
        result.passed = result.error is None and all(a["passed"] for a in result.assertions)
    return result


# --------------------------------------------------------------------------- #
# 场景 4：自然 S_REJECT 触发（OBS-6 方案 C：LLM 质量评估重构）
# --------------------------------------------------------------------------- #
def test_natural_reject(client: DistillationClient) -> ScenarioResult:
    """验证自然 S_REJECT 路径可达性（OBS-6 方案 C 修复后）。

    背景：
        - OBS-6 修复前：_estimate_quality_score 基础分 0.6 > reject_threshold(0.3)，
          quality_score 永远 >= 0.6，自然 S_REJECT 不可达
        - OBS-6 方案 C 修复后：LLM 评估优先，失败回退启发式（基础分 0.4）
          LLM 可用时对低质内容应返回 < 0.3 的评分，触发自然 S_REJECT

    测试逻辑：
        - 构造极低质内容（source_ref 为乱码字符串）
        - 推进到 S_STORAGE_DECISION
        - 调用 advance 触发 _estimate_quality_score
        - 验证状态机转移：S_REJECT（LLM 评估低分）或 S_FINALIZE（LLM 不可用/返回高分）

    验证点：
        1. quality_score 字段存在且为 float 0.0-1.0
        2. 状态机正确转移至 S_REJECT 或 S_FINALIZE
        3. 若 S_REJECT：agent_action="reject"（自然拒绝路径触发）
        4. 若 S_FINALIZE：quality_score >= reject_threshold（合理路径）
    """
    result = ScenarioResult(
        name="natural_reject",
        description="自然 S_REJECT 触发（OBS-6 方案 C：LLM 质量评估低质内容）",
        passed=True,
    )
    t_start = time.monotonic()

    try:
        # 构造极低质内容：乱码 + 重复无意义字符，期望 LLM 评估返回低分
        low_quality_content = "啊啊啊呃呃呃嗯嗯嗯" * 10  # 150 字符纯噪声
        status, data = client.start(
            source_type="text",
            source_ref=low_quality_content,
            template_id="default",
            max_turns=4,
            ask_user_on_ambiguity=False,
        )
        _assert(
            result, status == 200,
            f"start 应返回 200，实际 {status}",
            {"response": data},
        )
        if status != 200:
            return result

        session_id = data.get("session_id")
        result.state_path.append(STATE_PREREAD)
        result.action_path.append("proceed")

        # 推进到 S_STORAGE_DECISION
        time.sleep(ADVANCE_INTERVAL)
        _advance_and_assert(
            client, result, session_id,
            user_response="继续",
            expected_state=STATE_QUESTION,
            expected_action="proceed",
            step_label="to_question",
        )
        time.sleep(ADVANCE_INTERVAL)
        _advance_and_assert(
            client, result, session_id,
            user_response="继续",
            expected_state=STATE_REFLECT,
            expected_action="proceed",
            step_label="to_reflect",
        )
        time.sleep(ADVANCE_INTERVAL)
        _advance_and_assert(
            client, result, session_id,
            user_response=None,
            expected_state=STATE_CROSSVALIDATE,
            expected_action="proceed",
            step_label="to_crossvalidate",
        )
        time.sleep(ADVANCE_INTERVAL)
        _advance_and_assert(
            client, result, session_id,
            user_response=None,
            expected_state=STATE_EXTRACT,
            step_label="to_extract",
        )
        time.sleep(ADVANCE_INTERVAL)
        _advance_and_assert(
            client, result, session_id,
            user_response=None,
            expected_state=STATE_STORAGE_DECISION,
            expected_action="extract",
            step_label="to_storage_decision",
        )

        # 调用 advance 触发 _estimate_quality_score + reject_threshold 比较
        time.sleep(ADVANCE_INTERVAL)
        a_status, a_data = client.advance(session_id, user_response=None)
        _assert(
            result, a_status == 200,
            f"advance 应返回 200，实际 {a_status}",
            {"response": a_data},
        )
        if a_status == 200:
            next_state = a_data.get("current_state")
            next_action = a_data.get("agent_action")
            result.state_path.append(next_state or "?")
            result.action_path.append(next_action or "?")

            # 查询会话状态获取 quality_score
            time.sleep(ADVANCE_INTERVAL)
            g_status, g_data = client.get_status(session_id)
            quality_score = None
            if g_status == 200:
                quality_score = g_data.get("quality_score")

            # 验证点 1：quality_score 字段存在且为 float 0.0-1.0
            _assert(
                result, quality_score is not None,
                f"quality_score 应非 None（S_STORAGE_DECISION 后必填），实际 {quality_score}",
                {"quality_score": quality_score},
            )
            if quality_score is not None:
                _assert(
                    result, isinstance(quality_score, (int, float)) and 0.0 <= quality_score <= 1.0,
                    f"quality_score 应为 float 0.0-1.0，实际 {quality_score}（type={type(quality_score).__name__}）",
                    {"quality_score": quality_score},
                )

            # 验证点 2：状态机正确转移至 S_REJECT 或 S_FINALIZE
            valid_terminal = next_state in (STATE_REJECT, STATE_FINALIZE)
            _assert(
                result, valid_terminal,
                f"状态应转移至 S_REJECT 或 S_FINALIZE，实际 {next_state}",
                {"next_state": next_state, "next_action": next_action},
            )

            # 验证点 3 & 4：根据转移结果验证逻辑一致性
            if next_state == STATE_REJECT:
                # 自然拒绝路径触发 → agent_action 应为 "reject"
                _assert(
                    result, next_action == "reject",
                    f"S_REJECT 时 agent_action 应为 'reject'，实际 {next_action}",
                    {"next_action": next_action},
                )
                # quality_score 应 < reject_threshold（自然拒绝触发条件）
                _assert(
                    result,
                    quality_score is not None and quality_score < 0.3,
                    f"S_REJECT 时 quality_score 应 < 0.3（reject_threshold 默认值），实际 {quality_score}",
                    {"quality_score": quality_score, "reject_threshold": 0.3},
                )
            elif next_state == STATE_FINALIZE:
                # LLM 不可用（回退启发式基础分 0.4）或 LLM 评估返回高分
                # quality_score 应 >= reject_threshold（否则状态机转移错误）
                _assert(
                    result,
                    quality_score is not None and quality_score >= 0.3,
                    f"S_FINALIZE 时 quality_score 应 >= 0.3（reject_threshold 默认值），实际 {quality_score}（若 < 0.3 应走 S_REJECT）",
                    {"quality_score": quality_score, "reject_threshold": 0.3},
                )

    except Exception as e:
        result.error = f"{type(e).__name__}: {e}"
    finally:
        result.elapsed_ms = round((time.monotonic() - t_start) * 1000, 2)
        result.passed = result.error is None and all(a["passed"] for a in result.assertions)
    return result


# --------------------------------------------------------------------------- #
# 场景 5：多模态输入（character_card / image / video / audio）
# --------------------------------------------------------------------------- #
def test_multimodal_input(client: DistillationClient) -> ScenarioResult:
    """验证多模态 artifact 输入处理。

    覆盖 4 种 source_type：
        - character_card：角色卡（source_ref 为角色卡 JSON 字符串）
        - image：图片（source_ref 为文件路径或 URL）
        - video：视频（vLLM 原生解码）
        - audio：音频（vLLM 原生解码）

    验证点：
        1. start_distillation 对 4 种模态均返回 200
        2. initial_state=S_PREREAD
        3. preread_summary 非空（MultimodalPipeline 不可用时走降级占位摘要）
        4. ambiguity_questions 对应模态有内容（实现按 source_type 推断）
    """
    result = ScenarioResult(
        name="multimodal_input",
        description="多模态 artifact 输入（character_card/image/video/audio）",
        passed=True,
    )
    t_start = time.monotonic()

    multimodal_cases = [
        {
            "source_type": "character_card",
            "source_ref": '{"name":"测试角色","description":"多模态测试用角色卡","personality":"沉稳"}',
            "expected_question_keywords": ["角色卡"],
        },
        {
            "source_type": "image",
            "source_ref": "test_image.png",
            "expected_question_keywords": ["OCR", "视觉"],
        },
        {
            "source_type": "video",
            "source_ref": "test_video.mp4",
            "expected_question_keywords": ["视频", "关键帧"],
        },
        {
            "source_type": "audio",
            "source_ref": "test_audio.wav",
            "expected_question_keywords": ["音频", "转录"],
        },
    ]

    try:
        for case in multimodal_cases:
            time.sleep(ADVANCE_INTERVAL)
            status, data = client.start(
                source_type=case["source_type"],
                source_ref=case["source_ref"],
                template_id="default",
                max_turns=4,
                ask_user_on_ambiguity=True,
            )
            _assert(
                result, status == 200,
                f"source_type={case['source_type']} start 应返回 200，实际 {status}",
                {"response": data},
            )
            if status != 200:
                continue

            session_id = data.get("session_id")
            initial_state = data.get("initial_state")
            preread_summary = data.get("preread_summary")

            _assert(
                result, bool(session_id),
                f"{case['source_type']} session_id 非空",
                {"session_id": session_id},
            )
            _assert(
                result, initial_state == STATE_PREREAD,
                f"{case['source_type']} initial_state 应为 S_PREREAD，实际 {initial_state}",
                {"initial_state": initial_state},
            )
            _assert(
                result, isinstance(preread_summary, str) and len(preread_summary) > 0,
                f"{case['source_type']} preread_summary 应为非空字符串",
                {"preread_summary_length": len(preread_summary) if preread_summary else 0},
            )
            # preread_summary 应包含 source_type 标识
            _assert(
                result, case["source_type"] in preread_summary,
                f"{case['source_type']} preread_summary 应包含 source_type 标识",
                {"preread_summary": preread_summary[:200]},
            )

            # 查询会话状态，验证 ambiguity_questions 非空（实现按 source_type 推断）
            time.sleep(ADVANCE_INTERVAL)
            g_status, g_data = client.get_status(session_id)
            _assert(
                result, g_status == 200,
                f"{case['source_type']} get_session_status 应返回 200，实际 {g_status}",
                {"response": g_data},
            )
            if g_status == 200:
                ambiguity_questions = g_data.get("ambiguity_questions", [])
                _assert(
                    result, isinstance(ambiguity_questions, list) and len(ambiguity_questions) > 0,
                    f"{case['source_type']} ambiguity_questions 应非空",
                    {"ambiguity_questions": ambiguity_questions},
                )
                # 验证疑点清单包含模态相关关键词
                joined = " ".join(ambiguity_questions)
                matched_keywords = [
                    kw for kw in case["expected_question_keywords"]
                    if kw in joined
                ]
                _assert(
                    result, len(matched_keywords) > 0,
                    f"{case['source_type']} ambiguity_questions 应包含关键词 "
                    f"{case['expected_question_keywords']}，实际匹配 {matched_keywords}",
                    {"ambiguity_questions": ambiguity_questions, "matched": matched_keywords},
                )
                # 验证 source_type 字段
                _assert(
                    result, g_data.get("source_type") == case["source_type"],
                    f"source_type 字段应为 {case['source_type']}",
                    {"source_type": g_data.get("source_type")},
                )

            result.state_path.append(f"{case['source_type']}:{STATE_PREREAD}")
            result.action_path.append("proceed")

    except Exception as e:
        result.error = f"{type(e).__name__}: {e}"
    finally:
        result.elapsed_ms = round((time.monotonic() - t_start) * 1000, 2)
        result.passed = result.error is None and all(a["passed"] for a in result.assertions)
    return result


# --------------------------------------------------------------------------- #
# 报告生成
# --------------------------------------------------------------------------- #
def format_report(report: TestReport) -> str:
    """生成 Markdown 格式测试报告。"""
    lines: List[str] = []
    lines.append("# DistillationService 蒸馏服务 E2E 测试报告")
    lines.append("")
    lines.append("> spec `migrate-cxhms-radix-acp-multimodal` Task D5.1 产出。")
    lines.append(f"> 测试时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"> 服务地址: {CXO_SERVER_HTTP}")
    lines.append(f"> 蒸馏 API: {DISTILLATION_BASE}")
    lines.append("")

    # 服务状态
    lines.append("## 服务状态")
    lines.append("")
    lines.append("| 探测项 | 状态 | 详情 |")
    lines.append("|--------|------|------|")
    for key, info in report.service_status.items():
        status = "OK" if info.get("ok") else "DOWN"
        lines.append(f"| {info.get('label', key)} | {status} | {info.get('message', '')} |")
    lines.append("")

    if report.skipped:
        lines.append("## 测试跳过（SKIP）")
        lines.append("")
        lines.append(f"**跳过原因**: {report.skip_reason}")
        lines.append("")
        lines.append("测试因服务不可达而 SKIP（退出码 77），未执行任何场景。")
        lines.append("")
        return "\n".join(lines)

    # 场景汇总
    lines.append("## 场景汇总")
    lines.append("")
    lines.append(f"- 场景总数: {len(report.scenarios)}")
    lines.append(f"- 通过: {report.passed_count()}")
    lines.append(f"- 失败: {report.failed_count()}")
    lines.append("")

    # 各场景详情
    lines.append("## 场景详情")
    lines.append("")
    for s in report.scenarios:
        status_badge = "PASS" if s.passed else "FAIL"
        lines.append(f"### [{status_badge}] {s.name}")
        lines.append("")
        lines.append(f"**描述**: {s.description}")
        lines.append(f"**耗时**: {s.elapsed_ms} ms")
        if s.error:
            lines.append(f"**错误**: {s.error}")
        lines.append("")

        # 状态流转路径
        if s.state_path:
            lines.append("**状态流转路径**:")
            lines.append("")
            lines.append("```")
            path_str = " -> ".join(s.state_path)
            lines.append(path_str)
            lines.append("```")
            lines.append("")

        # agent_action 路径
        if s.action_path:
            lines.append("**agent_action 序列**:")
            lines.append("")
            lines.append("```")
            lines.append(" -> ".join(s.action_path))
            lines.append("```")
            lines.append("")

        # 断言详情
        if s.assertions:
            lines.append("**断言详情**:")
            lines.append("")
            lines.append("| # | 断言 | 结果 |")
            lines.append("|---|------|------|")
            for idx, a in enumerate(s.assertions, 1):
                passed_str = "PASS" if a["passed"] else "FAIL"
                desc = a["description"].replace("|", "\\|")
                lines.append(f"| {idx} | {desc} | {passed_str} |")
            lines.append("")

    # 总体结论
    all_pass = report.failed_count() == 0 and not report.skipped
    lines.append("## 总体结论")
    lines.append("")
    if all_pass:
        lines.append("所有场景通过，蒸馏服务 9 状态机推进符合契约预期。")
    else:
        lines.append(f"存在 {report.failed_count()} 个失败场景，需排查被测模块实现或契约差异。")
    lines.append("")
    lines.append("---")
    lines.append(f"**报告生成时间**: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    exit_code = "0 (PASS)" if all_pass else ("77 (SKIP)" if report.skipped else "1 (FAIL)")
    lines.append(f"**退出码**: {exit_code}")

    return "\n".join(lines)


def save_report(report: TestReport, output_dir: str = ".") -> str:
    """保存报告到文件。返回报告路径。"""
    from pathlib import Path
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    filename = f"distillation_e2e_report_{time.strftime('%Y%m%d_%H%M%S')}.md"
    path = out / filename
    path.write_text(format_report(report), encoding="utf-8")
    return str(path)


# --------------------------------------------------------------------------- #
# 主入口
# --------------------------------------------------------------------------- #
def run_all_scenarios(skip_on_unreachable: bool = True) -> TestReport:
    """运行全部测试场景。

    Args:
        skip_on_unreachable: True 时服务不可达则 SKIP，False 时直接失败

    Returns:
        TestReport: 完整测试报告
    """
    report = TestReport()

    # 探测服务可达性
    print("=" * 60)
    print("探测 CX-O-SERVER 服务可达性...")
    print(f"  Health: {HEALTH_CHECK_URL}")
    print("=" * 60)

    cxo_ok, cxo_msg = probe_cxo_server()
    report.service_status["cxo_server"] = {
        "label": "CX-O-SERVER (8001)",
        "url": HEALTH_CHECK_URL,
        "ok": cxo_ok,
        "message": cxo_msg,
    }
    print(f"  [{'OK' if cxo_ok else 'DOWN'}] CX-O-SERVER (8001) -> {cxo_msg}")

    distill_ok, distill_msg = (False, "未探测（CX-O-SERVER 不可达）")
    if cxo_ok:
        distill_ok, distill_msg = probe_distillation_endpoint()
        report.service_status["distillation_route"] = {
            "label": "Distillation API 路由",
            "url": f"{DISTILLATION_BASE}/<probe>",
            "ok": distill_ok,
            "message": distill_msg,
        }
        print(f"  [{'OK' if distill_ok else 'DOWN'}] Distillation API 路由 -> {distill_msg}")
    print("")

    # 服务不可达 → SKIP
    if not cxo_ok or not distill_ok:
        if skip_on_unreachable:
            report.skipped = True
            report.skip_reason = (
                f"CX-O-SERVER 或 Distillation API 不可达 "
                f"(cxo_server={cxo_ok}, distillation_route={distill_ok}). "
                f"详情: {cxo_msg} | {distill_msg}"
            )
            print(f"SKIP: {report.skip_reason}")
            return report

    # 运行测试场景
    client = DistillationClient()
    try:
        scenarios = [
            test_happy_path,
            test_reflect_question_loop,
            test_reject_branch,
            test_natural_reject,
            test_multimodal_input,
        ]
        for scenario_fn in scenarios:
            print(f"\n---------- 场景: {scenario_fn.__name__} ----------")
            result = scenario_fn(client)
            report.scenarios.append(result)
            status_str = "PASS" if result.passed else "FAIL"
            print(f"  结果: {status_str}  耗时: {result.elapsed_ms}ms")
            if result.error:
                print(f"  错误: {result.error}")
            if result.state_path:
                print(f"  状态路径: {' -> '.join(result.state_path)}")
            failed_asserts = [a for a in result.assertions if not a["passed"]]
            if failed_asserts:
                print(f"  失败断言数: {len(failed_asserts)}")
                for fa in failed_asserts[:3]:
                    print(f"    - {fa['description']}")
    finally:
        client.close()

    return report


def main() -> int:
    """主入口。返回退出码：0=PASS / 77=SKIP / 1=FAIL。"""
    parser = argparse.ArgumentParser(
        description="DistillationService 蒸馏服务 E2E 测试",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--probe", action="store_true", help="仅探测服务可达性，不执行测试")
    parser.add_argument("--output", default=".", help="报告输出目录（默认当前目录）")
    args = parser.parse_args()

    if args.probe:
        print("仅探测服务可达性...")
        cxo_ok, cxo_msg = probe_cxo_server()
        print(f"  CX-O-SERVER (8001): {'OK' if cxo_ok else 'DOWN'} -> {cxo_msg}")
        if cxo_ok:
            distill_ok, distill_msg = probe_distillation_endpoint()
            print(f"  Distillation API:  {'OK' if distill_ok else 'DOWN'} -> {distill_msg}")
        return 0

    report = run_all_scenarios(skip_on_unreachable=True)

    # 保存报告
    try:
        report_path = save_report(report, args.output)
        print(f"\n报告已保存: {report_path}")
    except Exception as e:
        print(f"\n报告保存失败: {type(e).__name__}: {e}")

    # 输出汇总
    print("\n" + "=" * 60)
    print("汇总")
    print("=" * 60)
    if report.skipped:
        print(f"结论: SKIP (服务不可达)")
        print(f"原因: {report.skip_reason}")
        return 77

    pass_n = report.passed_count()
    fail_n = report.failed_count()
    print(f"场景通过: {pass_n} / {len(report.scenarios)}")
    print(f"场景失败: {fail_n} / {len(report.scenarios)}")
    for s in report.scenarios:
        status = "PASS" if s.passed else "FAIL"
        print(f"  [{status}] {s.name} ({s.elapsed_ms}ms)")

    all_pass = fail_n == 0
    print(f"\n最终结论: {'ALL PASSED' if all_pass else 'SOME FAILED'}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
