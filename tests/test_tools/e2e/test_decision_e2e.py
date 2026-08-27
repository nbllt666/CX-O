"""E2E: 6 决策点 D1-D6 + write_with_decision + rejected_content 表（D5.2）

依赖服务：CX-O-SERVER @ http://127.0.0.1:8001
若服务不可达，整体 SKIP（exit 77，pytest 惯例），不报 FAIL。

测试覆盖：
  1. D1_LOCATION: 决定存储位置（3 分支：rejected / permanent_memories / memories）
  2. D2_METADATA: 元数据抽取（验证 time/importance/source/tags 4 字段齐全）
  3. D3_ASK_USER: 是否向用户提问（low confidence → True, high confidence → False）
  4. D4_REDISTILL: 是否重新蒸馏（current_turn < max → True, >= max → False）
  5. D5_CROSS_VALIDATE: 是否交叉验证（sources 非空 + content 非空 → True; sources 空 → False）
  6. D6_REJECT: 拒绝路径 + write_with_decision 写入 rejected_content 表
  7. write_with_decision accept 路径（permanent_memories）→ memory_id 非空
  8. rejected_content 表: 写入（D6 触发）/ 查询（GET）/ 清理（POST cleanup）

闭合判据：
  - 6 决策点全部返回 200 + 字段齐全 + 分支行为符合契约
  - write_with_decision reject/accept 双路径验证通过
  - rejected_content 表写入/查询/清理链路畅通

对应契约:
  - 接口契约: public/interface_stub/decision_core.pyi
  - 接口契约: public/interface_stub/memory_manager_v2.pyi
  - 数据契约: public/schema/storage_decision.schema.json
  - 数据契约: public/schema/rejected_content.schema.json

注：importance 由 LLM 决定，LLM 不可用时 DecisionCore 回退 _FALLBACK_IMPORTANCE=0.75
   （decision_core.py line 134/299）。E2E 环境通常 LLM 不可用，importance 恒为 0.75。
   通过设置不同 importance_threshold_permanent 控制 D1 的 permanent_memories vs memories 分支。
"""
from __future__ import annotations

import os
import sys
import time
import uuid
from typing import Any, Dict, Optional, Tuple

import requests

# 注入项目根路径，便于直接以脚本方式运行
sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ),
)

# CX-O-SERVER HTTP 端口（与 test_asr_llm_tts_latency.py 一致，默认 8001）
MAIN_URL = os.environ.get("CXO_SERVER_HTTP", "http://127.0.0.1:8001")
TIMEOUT = 15.0

# 完整 RubricSnapshot（严格匹配 RubricSnapshotModel 的 4 必填字段 + cross_validate_sources）
# 不可添加非契约字段（如 prefer_local/ask_threshold/min_quality 等），避免 pydantic 校验歧义
# 阈值设计：
#   - importance_threshold_permanent=0.7：importance 回退值 0.75 >= 0.7 → permanent_memories
#   - quality_reject_threshold=0.4：quality_score < 0.4 → rejected
#   - max_redistill_turns=3：current_turn < 3 → redistill=True
#   - ask_user_confidence_threshold=0.6：llm_confidence < 0.6 → ask_user=True
_DEFAULT_RUBRIC: Dict[str, Any] = {
    "importance_threshold_permanent": 0.7,
    "quality_reject_threshold": 0.4,
    "max_redistill_turns": 3,
    "ask_user_confidence_threshold": 0.6,
    "cross_validate_sources": [],
}


# --------------------------------------------------------------------------- #
# 工具函数
# --------------------------------------------------------------------------- #

def _print(tag: str, msg: str) -> None:
    """带统一前缀的打印，便于在 run_e2e_tests.py 汇总中识别。"""
    print(f"[decision-e2e:{tag}] {msg}")


def _skip(msg: str) -> int:
    """输出 SKIP 信息并返回标准退出码 77（pytest 惯例）。

    run_e2e_tests.py 识别 77 为 SKIP，不阻断总体但显式标注。
    """
    _print("skip", msg)
    print("=== decision E2E SKIPPED ===")
    return 77


def _request(
    method: str, path: str, json_body: Optional[Dict] = None
) -> Dict[str, Any]:
    """统一 HTTP 请求封装。

    失败时 raise_for_status 抛出 HTTPError，由调用方捕获并转为测试失败。
    proxies 显式禁用代理，避免环境代理污染本地请求。
    """
    url = f"{MAIN_URL}{path}"
    proxies = {"http": None, "https": None}
    resp = requests.request(
        method, url, json=json_body, timeout=TIMEOUT, proxies=proxies
    )
    resp.raise_for_status()
    return resp.json()


def _ensure_service() -> bool:
    """探测 CX-O-SERVER 可达性（GET /health，status < 500 视为可达）。"""
    try:
        r = requests.get(
            f"{MAIN_URL}/health",
            timeout=3.0,
            proxies={"http": None, "https": None},
        )
        return r.status_code < 500
    except Exception:
        return False


def _new_session_id() -> str:
    """生成 E2E 用唯一 session_id（UUID v4，匹配 schema pattern）。

    schema 要求 ^[0-9a-fA-F]{8}-...-{12}$，DecisionCore 实现仅检查非空，
    但审计日志路径 data/distillation_logs/{session_id}.json 对特殊字符敏感，
    故用 UUID v4 保证文件名安全 + 契约合规。
    """
    return str(uuid.uuid4())


# --------------------------------------------------------------------------- #
# 6 决策点测试
# --------------------------------------------------------------------------- #

def test_d1_location() -> Tuple[bool, str]:
    """D1_LOCATION: 决定存储位置（3 分支验证）。

    分支覆盖：
      - rejected: quality_score < quality_reject_threshold（0.2 < 0.4）
      - permanent_memories: importance >= importance_threshold_permanent
        （importance 回退 0.75 >= 0.7）
      - memories: importance < importance_threshold_permanent
        （importance 回退 0.75 < 0.8，需调高阈值）

    契约依据：decision_core.pyi decide_location + storage_decision.schema.json location 枚举。
    """
    _print("d1", "测试 D1_LOCATION（3 分支：rejected / permanent_memories / memories）")

    # 分支 1: rejected（quality_score=0.2 < 0.4）
    sid1 = _new_session_id()
    try:
        r_reject = _request(
            "POST",
            "/api/decision/D1_LOCATION",
            json_body={
                "session_id": sid1,
                "decision_input": {
                    "session_state": "S_STORAGE_DECISION",
                    "extracted_content": "E2E D1 rejected 分支",
                    "quality_score": 0.2,
                },
                "rubric": _DEFAULT_RUBRIC,
            },
        )
    except Exception as e:
        return False, f"D1 rejected 分支请求失败: {e}"

    if r_reject.get("location") != "rejected":
        return False, (
            f"D1 rejected 分支预期 location=rejected，实际="
            f"{r_reject.get('location')}（quality_score=0.2 < threshold=0.4）"
        )
    if r_reject.get("decision_point") != "D1_LOCATION":
        return False, (
            f"D1 rejected 分支 decision_point 预期 D1_LOCATION，实际="
            f"{r_reject.get('decision_point')}"
        )

    # 分支 2: permanent_memories（quality_score=0.8 >= 0.4，importance=0.75 >= 0.7）
    sid2 = _new_session_id()
    try:
        r_perm = _request(
            "POST",
            "/api/decision/D1_LOCATION",
            json_body={
                "session_id": sid2,
                "decision_input": {
                    "session_state": "S_STORAGE_DECISION",
                    "extracted_content": "E2E D1 permanent_memories 分支",
                    "quality_score": 0.8,
                },
                "rubric": _DEFAULT_RUBRIC,
            },
        )
    except Exception as e:
        return False, f"D1 permanent_memories 分支请求失败: {e}"

    if r_perm.get("location") != "permanent_memories":
        return False, (
            f"D1 permanent_memories 分支预期 location=permanent_memories，实际="
            f"{r_perm.get('location')}（importance 回退=0.75 >= threshold=0.7）"
        )

    # 分支 3: memories（quality_score=0.8 >= 0.4，importance=0.75 < 0.8）
    sid3 = _new_session_id()
    try:
        r_mem = _request(
            "POST",
            "/api/decision/D1_LOCATION",
            json_body={
                "session_id": sid3,
                "decision_input": {
                    "session_state": "S_STORAGE_DECISION",
                    "extracted_content": "E2E D1 memories 分支",
                    "quality_score": 0.8,
                },
                "rubric": {
                    **_DEFAULT_RUBRIC,
                    "importance_threshold_permanent": 0.8,
                },
            },
        )
    except Exception as e:
        return False, f"D1 memories 分支请求失败: {e}"

    if r_mem.get("location") != "memories":
        return False, (
            f"D1 memories 分支预期 location=memories，实际="
            f"{r_mem.get('location')}（importance 回退=0.75 < threshold=0.8）"
        )

    _print("d1", "3 分支全部通过: rejected / permanent_memories / memories")
    return True, "3 分支全部通过（rejected/permanent_memories/memories）"


def test_d2_metadata() -> Tuple[bool, str]:
    """D2_METADATA: 元数据抽取（验证 4 字段齐全）。

    契约依据：decision_core.pyi decide_metadata 返回 Dict 含
    time / importance / source / tags 4 字段。
    """
    _print("d2", "测试 D2_METADATA（验证 time/importance/source/tags 4 字段）")
    sid = _new_session_id()
    try:
        r = _request(
            "POST",
            "/api/decision/D2_METADATA",
            json_body={
                "session_id": sid,
                "decision_input": {
                    "session_state": "S_STORAGE_DECISION",
                    "extracted_content": "E2E D2 元数据测试",
                    "artifact_summary": "e2e-artifact",
                },
            },
        )
    except Exception as e:
        return False, f"D2 请求失败: {e}"

    metadata = r.get("metadata") or {}
    required_fields = ["time", "importance", "source", "tags"]
    missing = [f for f in required_fields if f not in metadata]
    if missing:
        return False, (
            f"D2 metadata 缺失字段: {missing}（实际 keys={list(metadata.keys())}）"
        )

    if not isinstance(metadata.get("tags"), list):
        return False, (
            f"D2 metadata.tags 预期 list，实际 type={type(metadata.get('tags')).__name__}"
        )

    if not isinstance(metadata.get("importance"), (int, float)):
        return False, (
            f"D2 metadata.importance 预期 number，实际 type="
            f"{type(metadata.get('importance')).__name__}"
        )

    _print("d2", f"metadata 4 字段齐全: {list(metadata.keys())}")
    return True, "metadata 4 字段齐全（time/importance/source/tags）"


def test_d3_ask_user() -> Tuple[bool, str]:
    """D3_ASK_USER: low confidence → True, high confidence → False。

    契约依据：decision_core.pyi decide_ask_user 返回 bool。
    实现：return llm_confidence < rubric.ask_user_confidence_threshold。
    """
    _print("d3", "测试 D3_ASK_USER（low=0.3 → True, high=0.9 → False）")
    sid = _new_session_id()
    try:
        r_low = _request(
            "POST",
            "/api/decision/D3_ASK_USER",
            json_body={
                "session_id": sid,
                "llm_confidence": 0.3,
                "rubric": _DEFAULT_RUBRIC,
            },
        )
        r_high = _request(
            "POST",
            "/api/decision/D3_ASK_USER",
            json_body={
                "session_id": sid,
                "llm_confidence": 0.9,
                "rubric": _DEFAULT_RUBRIC,
            },
        )
    except Exception as e:
        return False, f"D3 请求失败: {e}"

    low_ask = r_low.get("should_ask_user")
    high_ask = r_high.get("should_ask_user")
    if low_ask is not True:
        return False, (
            f"D3 llm_confidence=0.3 预期 should_ask_user=True，实际={low_ask}"
            f"（threshold=0.6）"
        )
    if high_ask is not False:
        return False, (
            f"D3 llm_confidence=0.9 预期 should_ask_user=False，实际={high_ask}"
            f"（threshold=0.6）"
        )

    _print("d3", f"low_conf(0.3)→{low_ask}, high_conf(0.9)→{high_ask}")
    return True, "low=True, high=False（阈值 0.6）"


def test_d4_redistill() -> Tuple[bool, str]:
    """D4_REDISTILL: current_turn < max → True, >= max → False。

    契约依据：decision_core.pyi decide_redistill 返回 bool。
    实现：return current_turn < rubric.max_redistill_turns。
    """
    _print("d4", "测试 D4_REDISTILL（turn=2 → True, turn=3 → False, max=3）")
    sid = _new_session_id()
    try:
        r_below = _request(
            "POST",
            "/api/decision/D4_REDISTILL",
            json_body={
                "session_id": sid,
                "current_turn": 2,
                "rubric": _DEFAULT_RUBRIC,
            },
        )
        r_at = _request(
            "POST",
            "/api/decision/D4_REDISTILL",
            json_body={
                "session_id": sid,
                "current_turn": 3,
                "rubric": _DEFAULT_RUBRIC,
            },
        )
    except Exception as e:
        return False, f"D4 请求失败: {e}"

    below = r_below.get("should_redistill")
    at = r_at.get("should_redistill")
    if below is not True:
        return False, (
            f"D4 current_turn=2 预期 should_redistill=True，实际={below}"
            f"（max_redistill_turns=3）"
        )
    if at is not False:
        return False, (
            f"D4 current_turn=3 预期 should_redistill=False，实际={at}"
            f"（max_redistill_turns=3）"
        )

    _print("d4", f"turn=2→{below}, turn=3→{at}")
    return True, "turn<max=True, turn>=max=False（max=3）"


def test_d5_cross_validate() -> Tuple[bool, str]:
    """D5_CROSS_VALIDATE: sources 非空 + content 非空 → True; sources 空 → False。

    契约依据：decision_core.pyi decide_cross_validate 返回 bool。
    实现：return len(rubric.cross_validate_sources) > 0 and bool(decision_input.extracted_content)
    """
    _print("d5", "测试 D5_CROSS_VALIDATE（sources 非空 → True, sources 空 → False）")
    sid = _new_session_id()

    # 分支 1: sources 非空 + content 非空 → True
    try:
        r_yes = _request(
            "POST",
            "/api/decision/D5_CROSS_VALIDATE",
            json_body={
                "session_id": sid,
                "decision_input": {
                    "session_state": "S_CROSSVALIDATE",
                    "extracted_content": "需要验证的内容",
                },
                "rubric": {
                    **_DEFAULT_RUBRIC,
                    "cross_validate_sources": ["web", "knowledge_graph"],
                },
            },
        )
    except Exception as e:
        return False, f"D5 sources 非空分支请求失败: {e}"

    if r_yes.get("should_cross_validate") is not True:
        return False, (
            f"D5 sources 非空预期 should_cross_validate=True，实际="
            f"{r_yes.get('should_cross_validate')}"
        )

    # 分支 2: sources 空 → False
    try:
        r_no = _request(
            "POST",
            "/api/decision/D5_CROSS_VALIDATE",
            json_body={
                "session_id": sid,
                "decision_input": {
                    "session_state": "S_CROSSVALIDATE",
                    "extracted_content": "需要验证的内容",
                },
                "rubric": _DEFAULT_RUBRIC,
            },
        )
    except Exception as e:
        return False, f"D5 sources 空分支请求失败: {e}"

    if r_no.get("should_cross_validate") is not False:
        return False, (
            f"D5 sources 空预期 should_cross_validate=False，实际="
            f"{r_no.get('should_cross_validate')}"
        )

    _print(
        "d5",
        f"sources 非空→{r_yes.get('should_cross_validate')}, "
        f"sources 空→{r_no.get('should_cross_validate')}",
    )
    return True, "sources 非空=True, sources 空=False"


def test_d6_reject_and_table() -> Tuple[bool, str]:
    """D6_REJECT: 拒绝路径 + write_with_decision 写入 rejected_content 表 + 查询验证。

    契约依据：
      - decision_core.pyi decide_reject 返回 StorageDecision(location=rejected)
      - memory_manager_v2.pyi write_with_decision（rejected 分支）写入 rejected_content 表
      - rejected_content.schema.json 字段：rejected_id/session_id/original_content/...
    """
    _print("d6", "测试 D6_REJECT + write_with_decision(reject) + rejected_content 表查询")
    sid = _new_session_id()
    test_content = "E2E D6 拒绝内容"
    try:
        reject = _request(
            "POST",
            "/api/decision/D6_REJECT",
            json_body={
                "session_id": sid,
                "quality_score": 0.15,
                "rubric": _DEFAULT_RUBRIC,
                "content": test_content,
                "metadata": {"source": "e2e", "test_run": True},
            },
        )
        records = _request("GET", f"/api/decision/rejected/{sid}")
    except Exception as e:
        return False, f"D6 请求失败: {e}"

    # 验证 D6 决策结果
    if reject.get("location") != "rejected":
        return False, (
            f"D6 预期 location=rejected，实际={reject.get('location')}"
        )
    if reject.get("decision_point") != "D6_REJECT":
        return False, (
            f"D6 预期 decision_point=D6_REJECT，实际={reject.get('decision_point')}"
        )
    if reject.get("memory_id") is not None:
        return False, (
            f"D6 预期 memory_id=None（rejected 不分配 memory_id），实际="
            f"{reject.get('memory_id')}"
        )

    # 验证 write_with_decision 写入 rejected_content 表
    write_result = reject.get("write_result") or {}
    if write_result.get("location") != "rejected":
        return False, (
            f"D6 write_result 预期 location=rejected，实际="
            f"{write_result.get('location')}"
        )
    if not write_result.get("rejected_id"):
        return False, (
            f"D6 write_result 缺少 rejected_id（write_result={write_result}），"
            f"可能 memory_manager 未集成 decision mixin"
        )

    # 验证 rejected_content 表查询
    count = records.get("count", 0)
    if count < 1:
        return False, (
            f"D6 rejected_content 查询预期 count>=1，实际 count={count}"
        )
    record_list = records.get("records") or []
    if not record_list:
        return False, "D6 rejected_content records 列表为空"

    first = record_list[0]
    if first.get("session_id") != sid:
        return False, (
            f"D6 rejected_content session_id 不匹配：预期={sid}，实际="
            f"{first.get('session_id')}"
        )
    if first.get("original_content") != test_content:
        return False, (
            f"D6 rejected_content original_content 不匹配：预期={test_content}，"
            f"实际={first.get('original_content')}"
        )
    if first.get("quality_score") != 0.15:
        return False, (
            f"D6 rejected_content quality_score 不匹配：预期=0.15，实际="
            f"{first.get('quality_score')}"
        )

    _print(
        "d6",
        f"location=rejected, rejected_id={write_result.get('rejected_id')}, "
        f"records count={count}",
    )
    return True, (
        f"location=rejected, rejected_id={write_result.get('rejected_id')}, "
        f"count={count}"
    )


# --------------------------------------------------------------------------- #
# write_with_decision accept 路径
# --------------------------------------------------------------------------- #

def test_write_with_decision_accept() -> Tuple[bool, str]:
    """write_with_decision accept 路径（permanent_memories）。

    通过 D1_LOCATION + content 触发 write_with_decision，验证 memory_id 非空。
    条件：quality_score=0.85 >= 0.4（不拒绝），importance 回退=0.75 >= 0.7 → permanent_memories。

    契约依据：memory_manager_v2.pyi write_with_decision 返回
    WriteWithDecisionResult(stored/location/memory_id/metadata/reason)。
    """
    _print("write", "测试 write_with_decision accept 路径（permanent_memories）")
    sid = _new_session_id()
    try:
        r = _request(
            "POST",
            "/api/decision/D1_LOCATION",
            json_body={
                "session_id": sid,
                "decision_input": {
                    "session_state": "S_STORAGE_DECISION",
                    "extracted_content": "E2E write_with_decision accept 测试",
                    "quality_score": 0.85,
                },
                "rubric": _DEFAULT_RUBRIC,
                "content": "E2E accept 内容（permanent_memories）",
                "metadata": {"source": "e2e", "tags": ["accept_test"]},
            },
        )
    except Exception as e:
        return False, f"write_with_decision accept 请求失败: {e}"

    if r.get("location") != "permanent_memories":
        return False, (
            f"accept 路径预期 location=permanent_memories，实际={r.get('location')}"
        )

    write_result = r.get("write_result") or {}
    if write_result.get("location") != "permanent_memories":
        return False, (
            f"write_result 预期 location=permanent_memories，实际="
            f"{write_result.get('location')}"
        )
    if write_result.get("memory_id") is None:
        return False, (
            f"write_result 缺少 memory_id（write_result={write_result}），"
            f"可能 write_permanent_memory 失败"
        )

    _print(
        "write",
        f"location=permanent_memories, memory_id={write_result.get('memory_id')}",
    )
    return True, f"memory_id={write_result.get('memory_id')}"


# --------------------------------------------------------------------------- #
# rejected_content 表清理
# --------------------------------------------------------------------------- #

def test_cleanup_rejected_content() -> Tuple[bool, str]:
    """cleanup: 清理过期拒绝记录。

    契约依据：memory_manager_v2.pyi cleanup_expired_rejected_content 返回清理记录数。

    注：刚写入的记录 expires_at = now + 30 days，cleanup 不会立即清理（purged_count 可能为 0）。
    本测试验证接口可用性 + 字段齐全，不强制要求 purged_count > 0。
    清理逻辑的实际生效验证由 retention_days 参数 + 时间推移自然完成。
    """
    _print("cleanup", "测试 cleanup_expired_rejected_content（retention_days=30）")
    try:
        r = _request(
            "POST",
            "/api/decision/cleanup",
            json_body={"retention_days": 30},
        )
    except Exception as e:
        return False, f"cleanup 请求失败: {e}"

    if "purged_count" not in r:
        return False, f"cleanup 响应缺少 purged_count 字段（实际 keys={list(r.keys())}）"

    purged = r.get("purged_count")
    if not isinstance(purged, int):
        return False, (
            f"cleanup purged_count 预期 int，实际 type={type(purged).__name__}"
        )

    _print("cleanup", f"purged_count={purged}")
    return True, f"purged_count={purged}（接口可用）"


# --------------------------------------------------------------------------- #
# 主入口
# --------------------------------------------------------------------------- #

def main() -> int:
    print("\n========== [D5.2] decision E2E ==========")
    print(f"# CX-O-SERVER: {MAIN_URL}")
    print(f"# 时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)

    if not _ensure_service():
        return _skip(
            f"CX-O-SERVER 不可达: {MAIN_URL}/health（请确认服务已启动在 8001 端口）"
        )

    _print("service", "CX-O-SERVER 可达，开始 6 决策点 + write_with_decision + rejected_content 测试")

    tests = [
        ("D1_LOCATION", test_d1_location),
        ("D2_METADATA", test_d2_metadata),
        ("D3_ASK_USER", test_d3_ask_user),
        ("D4_REDISTILL", test_d4_redistill),
        ("D5_CROSS_VALIDATE", test_d5_cross_validate),
        ("D6_REJECT+rejected_table", test_d6_reject_and_table),
        ("write_with_decision_accept", test_write_with_decision_accept),
        ("cleanup_rejected_content", test_cleanup_rejected_content),
    ]

    results = []
    for name, fn in tests:
        try:
            ok, detail = fn()
        except Exception as e:
            ok, detail = False, f"未捕获异常: {type(e).__name__}: {e}"
        results.append((name, ok, detail))

    print("\n--- decision E2E 汇总 ---")
    all_pass = True
    for name, ok, detail in results:
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {name}: {detail}")
        if not ok:
            all_pass = False

    total = len(results)
    pass_count = sum(1 for _, ok, _ in results if ok)
    fail_count = total - pass_count
    print(
        f"\n>>> 决策核心 E2E: {'ALL PASSED' if all_pass else 'SOME FAILED'}  "
        f"(PASS={pass_count}, FAIL={fail_count}, TOTAL={total})"
    )
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
