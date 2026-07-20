# ACP 独立聊天客户端 Streamlit UI
"""基于独立 ACP 协议栈的聊天客户端 UI

不再依赖主系统 REST API 中转消息，作为独立 ACP Agent 运行，
通过 UDP 发现其他 Agent，通过 HTTP 点对点通信。
"""
import os
import sys
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import streamlit as st

# 注入模块搜索路径，避免相对导入问题（与 cxfc/app.py 保持一致的模式）
_HERE = os.path.dirname(os.path.abspath(__file__))
_TESTS_TOOLS = os.path.dirname(_HERE)   # tests/test_tools
_TESTS = os.path.dirname(_TESTS_TOOLS)  # tests
_PROJECT_ROOT = os.path.dirname(_TESTS) # 项目根

# tests/test_tools：用于 from acp.acp_node / from common.api_client
sys.path.insert(0, _TESTS_TOOLS)
# 项目根：保持与 cxfc/app.py 一致，供内部模块的 from tests.test_tools... 导入
sys.path.insert(0, _PROJECT_ROOT)

from acp.acp_node import ACPNode  # noqa: E402


def init_state() -> None:
    if "acp_agent_id" not in st.session_state:
        st.session_state.acp_agent_id = "test-tool-001"
    if "acp_agent_name" not in st.session_state:
        st.session_state.acp_agent_name = "ACP Test Tool"
    if "acp_http_port" not in st.session_state:
        st.session_state.acp_http_port = 8505
    if "main_system_url" not in st.session_state:
        st.session_state.main_system_url = "http://localhost:8000"
    if "acp_node" not in st.session_state:
        st.session_state.acp_node = None
    if "node_running" not in st.session_state:
        st.session_state.node_running = False
    if "shown_message_ids" not in st.session_state:
        st.session_state.shown_message_ids = set()
    if "current_chat_target" not in st.session_state:
        st.session_state.current_chat_target = None
    if "poll_interval" not in st.session_state:
        st.session_state.poll_interval = 3
    if "main_system_registered" not in st.session_state:
        st.session_state.main_system_registered = False
    if "main_system_agent_id" not in st.session_state:
        st.session_state.main_system_agent_id = ""


def parse_host_port(url: str) -> tuple:
    try:
        parsed = urlparse(url)
        host = parsed.hostname or "localhost"
        port = parsed.port or 8000
        return host, port
    except Exception:
        return "localhost", 8000


def ensure_node(agent_id: str, agent_name: str, http_port: int) -> Optional[ACPNode]:
    if st.session_state.acp_node is None:
        return None
    node = st.session_state.acp_node
    if node.agent_id != agent_id or node.agent_name != agent_name or node.http_port != http_port:
        return None
    return node


def start_node(agent_id: str, agent_name: str, http_port: int) -> Dict[str, Any]:
    if st.session_state.acp_node is not None:
        try:
            st.session_state.acp_node.stop()
        except Exception:
            pass

    node = ACPNode(
        agent_id=agent_id,
        agent_name=agent_name,
        http_host="0.0.0.0",
        http_port=http_port,
        capabilities=["chat"],
    )
    result = node.start()
    if result.get("success"):
        st.session_state.acp_node = node
        st.session_state.node_running = True
        st.session_state.shown_message_ids = set()
        st.session_state.main_system_registered = False
    return result


def stop_node() -> None:
    if st.session_state.acp_node:
        try:
            st.session_state.acp_node.stop()
        except Exception:
            pass
    st.session_state.acp_node = None
    st.session_state.node_running = False
    st.session_state.main_system_registered = False


def extract_text(content) -> str:
    if isinstance(content, dict):
        if "text" in content:
            return str(content["text"])
        for key in ("message", "data", "body"):
            if key in content:
                return str(content[key])
        return str(content)
    return str(content)


def render_message_bubble(msg: dict) -> None:
    is_sent = bool(msg.get("is_sent", False))
    content_text = extract_text(msg.get("content", {}))
    from_name = msg.get("from_agent_name", "") or msg.get("from_agent_id", "未知")
    timestamp = msg.get("timestamp", "")

    role = "user" if is_sent else "assistant"
    with st.chat_message(role):
        st.markdown(content_text)
        meta_parts = []
        if not is_sent:
            meta_parts.append(f"来自: {from_name}")
        if timestamp:
            meta_parts.append(f"时间: {timestamp}")
        if meta_parts:
            st.caption(" | ".join(meta_parts))


def build_chat_targets(node: ACPNode) -> List[tuple]:
    targets = []
    agents = node.list_known_agents()
    for agent in agents:
        aid = agent.get("id", "")
        aname = agent.get("name", "") or aid
        is_main = agent.get("is_main_system", False)
        tag = "[主系统]" if is_main else "[Agent]"
        label = f"{tag} {aname} ({aid})"
        targets.append((label, "agent", aid))
    return targets


def render_chat_tab(node: ACPNode) -> None:
    st.subheader("聊天")

    targets = build_chat_targets(node)
    if not targets:
        st.warning("当前没有可用的聊天对象。请到「发现与连接」Tab 注册主系统或发现其他 Agent。")
        return

    label_list = [t[0] for t in targets]
    default_index = 0
    if st.session_state.current_chat_target:
        prev_label = st.session_state.current_chat_target.get("label")
        if prev_label in label_list:
            default_index = label_list.index(prev_label)

    selected_label = st.selectbox("选择聊天对象", label_list, index=default_index, key="chat_target_select")
    selected = next((t for t in targets if t[0] == selected_label), None)
    if selected is None:
        st.session_state.current_chat_target = None
        return

    target_type, target_id = selected[1], selected[2]
    st.session_state.current_chat_target = {
        "label": selected_label,
        "type": target_type,
        "id": target_id,
    }

    st.markdown("---")

    messages = node.get_messages(agent_id=target_id, limit=50)
    try:
        messages = sorted(messages, key=lambda m: m.get("timestamp", ""))
    except Exception:
        pass

    shown = st.session_state.shown_message_ids
    new_count = 0
    msg_container = st.container()
    with msg_container:
        for msg in messages:
            mid = msg.get("id", "")
            if not mid:
                mid = f"{msg.get('from_agent_id','')}|{msg.get('timestamp','')}|{extract_text(msg.get('content',''))[:30]}"
            if mid in shown:
                continue
            shown.add(mid)
            new_count += 1
            render_message_bubble(msg)

    if new_count == 0 and len(messages) == 0:
        st.caption("暂无消息记录")

    st.markdown("---")

    with st.form("chat_send_form", clear_on_submit=True):
        msg_text = st.text_input("输入消息", placeholder="输入消息内容后按回车或点击发送", key="chat_input_text")
        submitted = st.form_submit_button("发送")
        if submitted:
            if not msg_text.strip():
                st.warning("消息内容不能为空")
            else:
                content = {"text": msg_text.strip()}
                target_agent = node.get_agent(target_id)
                if target_agent and target_agent.get("is_main_system"):
                    host, port = parse_host_port(st.session_state.main_system_url)
                    resp = node.send_to_main_system(
                        main_system_host=host,
                        main_system_port=port,
                        main_system_agent_id=target_id,
                        content=content,
                    )
                else:
                    resp = node.send_message(to_agent_id=target_id, content=content)

                if resp.get("success"):
                    st.success("消息已发送")
                    st.rerun()
                else:
                    st.error(f"发送失败: {resp.get('error', '未知错误')}")


def render_connect_tab(node: ACPNode) -> None:
    st.subheader("发现与连接")

    col_d1, col_d2 = st.columns(2)
    with col_d1:
        if st.button("发现 Agent", key="btn_discover"):
            with st.spinner("正在发现 Agent（等待 5 秒）..."):
                agents = node.discover_once(timeout=5.0)
            st.success(f"发现 {len(agents)} 个 Agent")
            if agents:
                st.table(agents)

    with col_d2:
        if st.button("刷新已知 Agent 列表", key="btn_refresh_agents"):
            st.rerun()

    st.markdown("#### 已知 Agent 列表")
    agents = node.list_known_agents()
    if agents:
        table_rows = []
        for a in agents:
            table_rows.append({
                "id": a.get("id", ""),
                "name": a.get("name", ""),
                "host": a.get("host", ""),
                "port": a.get("port", ""),
                "status": a.get("status", ""),
                "is_main": a.get("is_main_system", False),
            })
        st.table(table_rows)
    else:
        st.info("当前没有已知 Agent")

    st.markdown("---")
    st.markdown("#### 注册主系统")

    with st.form("register_main_form"):
        main_url = st.text_input(
            "主系统地址",
            value=st.session_state.main_system_url,
            key="register_main_url",
        )
        main_agent_id = st.text_input(
            "主系统 Agent ID（可选，留空自动获取）",
            value="",
            key="register_main_agent_id",
        )
        reg_submitted = st.form_submit_button("注册主系统")
        if reg_submitted:
            host, port = parse_host_port(main_url)
            result = node.register_main_system(
                main_system_host=host,
                main_system_port=port,
                main_system_agent_id=main_agent_id.strip(),
            )
            if result.get("success"):
                st.session_state.main_system_registered = True
                st.session_state.main_system_agent_id = result["agent"]["id"]
                st.success(f"主系统已注册: {result['agent']['id']}")
                st.rerun()
            else:
                st.error(f"注册失败: {result.get('error', '未知错误')}")

    st.markdown("---")
    st.markdown("#### 健康检查")
    if agents:
        check_options = {f"{a.get('name','')} ({a.get('id','')})": a.get("id", "") for a in agents}
        sel_label = st.selectbox("选择 Agent 进行健康检查", list(check_options.keys()), key="health_check_sel")
        if st.button("健康检查", key="btn_health_check"):
            sel_id = check_options.get(sel_label, "")
            if sel_id:
                result = node.health_check_agent(sel_id)
                if result.get("success"):
                    st.success(f"健康状态: {result.get('info', {})}")
                else:
                    st.error(f"健康检查失败: {result.get('error', '未知错误')}")


def render_group_tab(node: ACPNode) -> None:
    st.subheader("群组")
    st.info(
        "独立 ACP 节点的群组功能需要多个独立节点之间协调。"
        "当前版本支持点对点聊天，群组功能将在后续版本支持。"
    )

    messages = node.get_messages(limit=20)
    st.markdown("#### 最近消息（全部）")
    if messages:
        for msg in messages[-20:]:
            render_message_bubble(msg)
    else:
        st.caption("暂无消息记录")


def render_stats_tab(node: ACPNode) -> None:
    st.subheader("统计")

    if st.button("刷新统计", key="btn_refresh_stats"):
        st.rerun()

    stats = node.get_statistics()

    metric_cols = st.columns(4)
    metrics = [
        ("total_messages", "消息总数"),
        ("messages_sent", "已发送"),
        ("messages_received", "已接收"),
        ("total_agents", "已知 Agent"),
    ]

    for idx, (key, label) in enumerate(metrics):
        with metric_cols[idx]:
            st.metric(label, stats.get(key, 0))

    st.markdown("---")
    st.markdown("#### 节点状态")
    st.json({
        "local_agent_id": stats.get("local_agent_id", ""),
        "local_agent_name": stats.get("local_agent_name", ""),
        "http_port": stats.get("http_port", ""),
        "running": stats.get("running", False),
        "discovery_status": stats.get("discovery_status", {}),
        "server_status": stats.get("server_status", {}),
    })


def main() -> None:
    init_state()

    st.title("ACP 独立聊天客户端")
    st.caption("作为独立 ACP Agent 运行，通过 UDP 发现 + HTTP 点对点通信")

    with st.sidebar:
        st.header("节点配置")
        agent_id = st.text_input("本地 Agent ID", value=st.session_state.acp_agent_id, key="sidebar_agent_id")
        agent_name = st.text_input("本地 Agent 名称", value=st.session_state.acp_agent_name, key="sidebar_agent_name")
        http_port = st.number_input("HTTP 端口", min_value=1024, max_value=65535, value=st.session_state.acp_http_port, step=1, key="sidebar_http_port")
        main_url = st.text_input("主系统地址", value=st.session_state.main_system_url, key="sidebar_main_url")

        st.session_state.acp_agent_id = agent_id
        st.session_state.acp_agent_name = agent_name
        st.session_state.acp_http_port = int(http_port)
        st.session_state.main_system_url = main_url

        poll_interval = st.slider("消息轮询间隔（秒）", min_value=1, max_value=10, value=st.session_state.poll_interval, key="sidebar_poll_interval")
        st.session_state.poll_interval = poll_interval
        auto_poll = st.checkbox("启用消息自动轮询", value=True, key="sidebar_auto_poll")
        st.session_state.auto_poll = auto_poll

        st.markdown("---")
        col_start, col_stop = st.columns(2)
        with col_start:
            if st.button("启动节点", key="btn_start_node", disabled=st.session_state.node_running):
                result = start_node(agent_id, agent_name, int(http_port))
                if result.get("success"):
                    st.success(f"节点已启动: {agent_id}@0.0.0.0:{http_port}")
                    st.rerun()
                else:
                    st.error(f"启动失败: {result.get('error', '未知错误')}")
        with col_stop:
            if st.button("停止节点", key="btn_stop_node", disabled=not st.session_state.node_running):
                stop_node()
                st.success("节点已停止")
                st.rerun()

        if st.session_state.node_running:
            st.success(f"运行中: {agent_id}")
        else:
            st.warning("节点未启动")

    if not st.session_state.node_running or st.session_state.acp_node is None:
        st.info("请在左侧侧边栏点击「启动节点」启动独立 ACP 节点。")
        return

    node = st.session_state.acp_node

    tab_chat, tab_connect, tab_group, tab_stats = st.tabs(["聊天", "发现与连接", "群组", "统计"])

    with tab_chat:
        render_chat_tab(node)

    with tab_connect:
        render_connect_tab(node)

    with tab_group:
        render_group_tab(node)

    with tab_stats:
        render_stats_tab(node)

    if (
        st.session_state.get("auto_poll", True)
        and st.session_state.get("current_chat_target") is not None
    ):
        st.caption(f"消息轮询中，间隔 {poll_interval} 秒...")
        time.sleep(poll_interval)
        st.rerun()


if __name__ == "__main__":
    main()
