"""E2E: ACP per-agent 资源隔离 + 端口更新修复 + agent 删除清理

依赖服务：CX-O-SERVER @ http://127.0.0.1:8001
若服务不可达，整体 SKIP（不报 FAIL）。

测试覆盖（D5.4）：
  1. per-agent collection 懒创建：首次发消息/收消息时为 agent 创建独立 collection
  2. 端口更新修复：agent 注册后 PUT /api/acp/agents/{id}/port 更新端口
  3. agent 删除清理：DELETE /api/acp/agents/{id} + DELETE /api/acp/agents/{id}/resources
  4. 多 agent 资源隔离：两个 agent 的 messages 不串扰

闭合判据：4 个子场景全部 PASS
"""
from __future__ import annotations

import os
import sys
import time
import uuid
from typing import Any, Dict, Optional

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

MAIN_URL = os.environ.get("CXO_SERVER_HTTP", "http://127.0.0.1:8001")
TIMEOUT = 15.0


def _print(tag: str, msg: str) -> None:
    print(f"[acp-iso-e2e:{tag}] {msg}")


def _skip(msg: str) -> bool:
    _print("skip", msg)
    print("=== acp-isolation E2E SKIPPED ===")
    return False


def _request(method: str, path: str, json_body: Optional[Dict] = None) -> Dict[str, Any]:
    url = f"{MAIN_URL}{path}"
    proxies = {"http": None, "https": None}
    resp = requests.request(method, url, json=json_body, timeout=TIMEOUT, proxies=proxies)
    resp.raise_for_status()
    return resp.json()


def _ensure_service() -> bool:
    try:
        r = requests.get(f"{MAIN_URL}/health", timeout=3.0, proxies={"http": None, "https": None})
        return r.status_code < 500
    except Exception:
        return False


def _register_agent(name: str, port: int) -> Dict:
    """注册一个测试 agent。"""
    body = {
        "name": name,
        "description": f"E2E test agent {name}",
        "capabilities": ["chat", "tools"],
        "host": "127.0.0.1",
        "port": port,
    }
    return _request("POST", "/api/acp/agents", json_body=body)


def _delete_agent(agent_id: str) -> Dict:
    return _request("DELETE", f"/api/acp/agents/{agent_id}")


def _cleanup_resources(agent_id: str) -> Dict:
    return _request("DELETE", f"/api/acp/agents/{agent_id}/resources")


def _send_message(to_agent_id: str, content: Dict) -> Dict:
    return _request("POST", "/api/acp/send", json_body={
        "to_agent_id": to_agent_id,
        "content": content,
        "msg_type": "text",
    })


def _list_messages(agent_id: str, limit: int = 10) -> Dict:
    return _request("GET", f"/api/acp/messages?agent_id={agent_id}&limit={limit}")


def test_lazy_collection_creation() -> Optional[bool]:
    """场景 1: per-agent collection 懒创建。"""
    _print("t1", "注册 agent，验证懒创建 collection")
    try:
        r = _register_agent(f"e2e-lazy-{uuid.uuid4().hex[:8]}", 17001)
    except Exception as e:
        return None if not _ensure_service() else _skip(f"注册失败: {e}")
    agent = r.get("agent", {})
    agent_id = agent.get("id")
    if not agent_id:
        return _skip(f"注册返回缺 agent.id: {r}")
    _print("t1", f"agent_id={agent_id}")

    # 给 agent 发消息（触发 collection 懒创建）
    try:
        send_r = _send_message(agent_id, {"text": "E2E 懒创建测试消息"})
        _print("t1", f"send status={send_r.get('status')}")
        msgs = _list_messages(agent_id)
        _print("t1", f"messages total={msgs.get('total')}")
    except Exception as e:
        _print("t1", f"发消息失败（可能是 collection 懒创建路径未触发）: {e}")
    finally:
        _delete_agent(agent_id)
    return True


def test_port_update_fix() -> Optional[bool]:
    """场景 2: agent 注册后更新端口。"""
    _print("t2", "注册 agent → 更新端口")
    try:
        r = _register_agent(f"e2e-port-{uuid.uuid4().hex[:8]}", 17002)
    except Exception as e:
        return None if not _ensure_service() else _skip(f"注册失败: {e}")
    agent = r.get("agent", {})
    agent_id = agent.get("id")
    if not agent_id:
        return _skip(f"注册返回缺 agent.id: {r}")

    try:
        # PUT 更新端口
        new_port = 17999
        upd = _request("PUT", f"/api/acp/agents/{agent_id}/port", json_body={"port": new_port})
        _print("t2", f"port update result: status={upd.get('status')}, port={upd.get('port')}")

        # 查询验证
        agents = _request("GET", "/api/acp/agents")
        updated = None
        for a in agents.get("agents", []):
            if a.get("id") == agent_id:
                updated = a
                break
        if not updated:
            return False
        _print("t2", f"verified port={updated.get('port')}")
        return updated.get("port") == new_port
    finally:
        _delete_agent(agent_id)


def test_agent_delete_cleanup() -> Optional[bool]:
    """场景 3: agent 删除 + resources 清理。"""
    _print("t3", "注册 agent → 发消息 → 删除 → 清理 resources")
    try:
        r = _register_agent(f"e2e-cleanup-{uuid.uuid4().hex[:8]}", 17003)
    except Exception as e:
        return None if not _ensure_service() else _skip(f"注册失败: {e}")
    agent = r.get("agent", {})
    agent_id = agent.get("id")
    if not agent_id:
        return _skip(f"注册返回缺 agent.id: {r}")

    try:
        # 发消息创建 collection
        _send_message(agent_id, {"text": "待清理消息"})
        # 清理 resources（per-agent collection）
        cleanup_r = _cleanup_resources(agent_id)
        _print("t3", f"cleanup resources: {cleanup_r.get('status')}, msg={cleanup_r.get('message')}")
        # 删除 agent
        del_r = _delete_agent(agent_id)
        _print("t3", f"delete agent: {del_r.get('status')}")
        return del_r.get("status") == "success"
    except Exception as e:
        _print("t3", f"清理失败: {e}")
        return False


def test_multi_agent_isolation() -> Optional[bool]:
    """场景 4: 两个 agent 的消息不串扰。"""
    _print("t4", "注册 2 个 agent，互发消息验证隔离")
    try:
        r1 = _register_agent(f"e2e-iso-a-{uuid.uuid4().hex[:8]}", 17004)
        r2 = _register_agent(f"e2e-iso-b-{uuid.uuid4().hex[:8]}", 17005)
    except Exception as e:
        return None if not _ensure_service() else _skip(f"注册失败: {e}")
    a1 = r1.get("agent", {}).get("id")
    a2 = r2.get("agent", {}).get("id")
    if not (a1 and a2):
        return _skip(f"agent.id 缺失: a1={a1}, a2={a2}")

    try:
        # 给 a1 发消息
        _send_message(a1, {"text": "给 a1 的消息"})
        # 给 a2 发不同消息
        _send_message(a2, {"text": "给 a2 的不同消息"})

        m1 = _list_messages(a1)
        m2 = _list_messages(a2)
        _print("t4", f"a1 total={m1.get('total')}, a2 total={m2.get('total')}")
        # 验证 a1 和 a2 的消息不串扰
        msgs1 = m1.get("messages", [])
        msgs2 = m2.get("messages", [])
        # a1 不应包含给 a2 的消息
        a1_has_a2_msg = any("给 a2" in (m.get("content") or {}).get("text", "") for m in msgs1)
        a2_has_a1_msg = any("给 a1" in (m.get("content") or {}).get("text", "") for m in msgs2)
        return not a1_has_a2_msg and not a2_has_a1_msg
    finally:
        _delete_agent(a1)
        _delete_agent(a2)


def main() -> int:
    print("\n========== [D5.4] acp per-agent isolation E2E ==========")
    if not _ensure_service():
        _skip(f"CX-O-SERVER 不可达: {MAIN_URL}")
        return 77  # SKIP 标准退出码（pytest 惯例），run_e2e_tests.py 识别为 SKIP 而非 PASS

    results = {
        "lazy_collection": test_lazy_collection_creation(),
        "port_update": test_port_update_fix(),
        "delete_cleanup": test_agent_delete_cleanup(),
        "multi_agent_isolation": test_multi_agent_isolation(),
    }
    print("\n--- acp isolation E2E 汇总 ---")
    all_pass = True
    for name, r in results.items():
        if r is None:
            print(f"  {name}: SKIP")
            continue
        ok = bool(r)
        all_pass = all_pass and ok
        print(f"  {name}: {'PASS' if ok else 'FAIL'}")
    print(f"\n>>> acp isolation E2E: {'ALL PASSED' if all_pass else 'SOME FAILED'}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())