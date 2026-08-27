"""E2E 测试专用 agent 公共模块。

所有打真实后端的 E2E 脚本统一使用同一个测试用 agent（E2E_AGENT_ID），
避免测试数据混入用户真实聊天记录（agent-default 等会话）。

用法：
    from _e2e_agent import E2E_AGENT_ID, reset_agent_state, restore_agent_state

    # 测试开始前：清空测试 agent 会话，保证起点干净（幂等）
    reset_agent_state()

    # ... 测试逻辑（agent_id 一律用 E2E_AGENT_ID）...

    # 测试结束（finally）：清空测试期间写入，恢复测试前状态
    restore_agent_state()

清理接口只动 `agent-{E2E_AGENT_ID}` 这一个会话，绝不触碰其他会话。
"""
import os
import urllib.error
import urllib.request

# 测试专用 agent：默认 test-agent，可用环境变量覆盖（多套件并行时各自指定）
E2E_AGENT_ID = os.environ.get("CXO_E2E_AGENT_ID", "test-agent")

# 后端地址：与各 E2E 脚本的 CXO_SERVER 环境变量约定一致
E2E_SERVER_HTTP = os.environ.get("CXO_SERVER_HTTP", "http://127.0.0.1:8000")


def _clear_session_messages(base_url: str) -> bool:
    """清空 agent 会话消息（后端懒创建语义：会话不存在时 DELETE 返回 success/404 均视为干净）。"""
    url = f"{base_url}/api/context/sessions/agent-{E2E_AGENT_ID}/messages"
    request = urllib.request.Request(url, method="DELETE")
    try:
        with urllib.request.urlopen(request, timeout=10) as resp:
            return resp.status == 200
    except urllib.error.HTTPError as exc:
        # 404 = 会话不存在 = 本来就是干净状态
        if exc.code == 404:
            return True
        print(f"[e2e-agent] 清理会话失败: HTTP {exc.code}")
        return False
    except Exception as exc:  # 清理失败不阻塞测试主流程，仅告警
        print(f"[e2e-agent] 清理会话异常: {exc}")
        return False


def reset_agent_state(base_url: str = E2E_SERVER_HTTP) -> None:
    """测试开始前调用：确保测试 agent 会话处于干净状态（幂等）。"""
    _clear_session_messages(base_url)


def restore_agent_state(base_url: str = E2E_SERVER_HTTP) -> None:
    """测试结束时调用（建议放 finally）：清空测试期间写入，恢复测试前状态。"""
    if _clear_session_messages(base_url):
        print(f"[e2e-agent] 已恢复测试前状态（清空 agent-{E2E_AGENT_ID} 会话）")


def history_url(base_url: str = E2E_SERVER_HTTP) -> str:
    """测试 agent 的聊天历史端点（供脚本断言使用）。"""
    return f"{base_url}/api/chat/history/agent-{E2E_AGENT_ID}"


__all__ = ["E2E_AGENT_ID", "E2E_SERVER_HTTP", "reset_agent_state", "restore_agent_state", "history_url"]
