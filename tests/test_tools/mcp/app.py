# MCP 测试工具 Streamlit UI
import os
import sys
import json

import streamlit as st

# 注入模块搜索路径，避免相对导入问题
_HERE = os.path.dirname(os.path.abspath(__file__))
_TESTS_TOOLS = os.path.dirname(_HERE)   # tests/test_tools
_TESTS = os.path.dirname(_TESTS_TOOLS)  # tests
_PROJECT_ROOT = os.path.dirname(_TESTS) # 项目根

# tests/test_tools：用于 from common.api_client / from mcp.mock_mcp_server
sys.path.insert(0, _TESTS_TOOLS)
# 项目根：mock_mcp_server 内部使用 from tests.test_tools.mcp.preset_tools import ...
sys.path.insert(0, _PROJECT_ROOT)

from common.api_client import MainSystemClient  # noqa: E402
from mcp.mock_mcp_server import MockMCPServer  # noqa: E402
from mcp.preset_tools import get_preset_definitions, list_tool_names  # noqa: E402


# ===== 会话状态初始化 =====
def init_state() -> None:
    """初始化 st.session_state 关键字段，避免 KeyError 与重复创建客户端。"""
    if "mcp_base_url" not in st.session_state:
        st.session_state.mcp_base_url = "http://localhost:8000"
    if "client" not in st.session_state:
        st.session_state.client = MainSystemClient(st.session_state.mcp_base_url)
    if "mock_server" not in st.session_state:
        st.session_state.mock_server = None
    if "mock_server_port" not in st.session_state:
        st.session_state.mock_server_port = 8600
    if "mock_server_running" not in st.session_state:
        st.session_state.mock_server_running = False


def ensure_client(base_url: str) -> MainSystemClient:
    """主系统地址变化时重建客户端，否则复用缓存实例。"""
    if st.session_state.client is None or st.session_state.mcp_base_url != base_url:
        try:
            st.session_state.client.close()
        except Exception:
            pass
        st.session_state.client = MainSystemClient(base_url)
        st.session_state.mcp_base_url = base_url
    return st.session_state.client


# ===== 通用工具函数 =====
def is_api_ok(resp: dict) -> bool:
    """判断 API 返回 dict 是否成功（success 字段或 status 在白名单内）。"""
    if not isinstance(resp, dict):
        return False
    if "success" in resp and resp["success"] is False:
        return False
    if "status" in resp and resp["status"] not in ("success", "ok"):
        return False
    return True


def show_api_error(resp: dict, default_msg: str = "API 调用失败") -> None:
    """统一展示 API 错误，使用 st.error。"""
    if isinstance(resp, dict):
        err = resp.get("error") or resp.get("detail") or resp.get("message") or default_msg
    else:
        err = default_msg
    st.error(f"{default_msg}: {err}")


def safe_list(resp: dict, key: str) -> list:
    """从 API 返回 dict 中安全取出列表字段。"""
    if not isinstance(resp, dict):
        return []
    val = resp.get(key, [])
    return val if isinstance(val, list) else []


# ===== Tab 1: 模拟 MCP 服务器 =====
def render_mock_server_tab(client: MainSystemClient) -> None:
    """模拟 MCP 服务器 Tab：配置端口 / 启动停止 / 运行状态 / 预置工具。"""
    st.subheader("模拟 MCP 服务器")

    mock_server = st.session_state.mock_server
    port = st.session_state.mock_server_port
    endpoint_url = f"http://127.0.0.1:{port}"

    # ----- 配置端口 -----
    st.markdown("#### 配置端口")
    st.write(f"当前端口：**{port}**（请在侧边栏修改）")
    st.markdown("**模拟服务器端点 URL**")
    st.code(endpoint_url, language="text")

    st.markdown("---")

    if mock_server is None:
        # ----- 启动区（模拟服务未启动时显示） -----
        st.markdown("#### 启动模拟 MCP 服务器")
        if st.button("启动模拟 MCP 服务器", key="btn_start_mock_mcp"):
            try:
                server = MockMCPServer(host="127.0.0.1", port=int(port))
                server.start()
                st.session_state.mock_server = server
                st.session_state.mock_server_running = True
                st.success(f"模拟 MCP 服务器已启动：{endpoint_url}")
                st.rerun()
            except Exception as e:
                st.error(f"启动模拟 MCP 服务器失败: {e}")
    else:
        # ----- 运行状态区（模拟服务已启动时显示） -----
        st.markdown("#### 运行状态")
        running = mock_server.is_running()
        st.metric("运行状态", "运行中" if running else "已停止")

        if st.button("停止模拟 MCP 服务器", key="btn_stop_mock_mcp"):
            try:
                mock_server.stop()
            except Exception:
                pass
            st.session_state.mock_server = None
            st.session_state.mock_server_running = False
            st.success("模拟 MCP 服务器已停止")
            st.rerun()

    st.markdown("---")

    # ----- 预置工具列表 -----
    st.markdown("#### 预置工具列表")
    preset_tools = get_preset_definitions()
    if preset_tools:
        table_rows = []
        for t in preset_tools:
            table_rows.append({
                "name": t.get("name", ""),
                "description": t.get("description", ""),
            })
        st.dataframe(table_rows, use_container_width=True)
    else:
        st.info("暂无预置工具")

    # ----- 调用日志 -----
    if mock_server is not None and mock_server.call_logs:
        st.markdown("---")
        st.markdown("#### 调用日志（模拟服务器侧）")
        st.caption("模拟 MCP 服务器接收到的工具调用请求记录")
        st.json(mock_server.call_logs[-20:])


# ===== Tab 2: MCP 管理 =====
def render_mcp_manage_tab(client: MainSystemClient) -> None:
    """MCP 管理 Tab：添加服务器 / 列表 / 操作 / 同步。"""
    st.subheader("MCP 管理")

    # 顶部操作按钮
    col1, col2 = st.columns(2)
    with col1:
        if st.button("刷新服务器列表", key="btn_list_mcp_servers"):
            st.rerun()
    with col2:
        if st.button("同步全部工具", key="btn_sync_mcp_tools"):
            with st.spinner("正在同步工具..."):
                resp = client.sync_mcp_tools()
            if is_api_ok(resp):
                msg = resp.get("message", "工具同步完成")
                st.success(msg)
            else:
                show_api_error(resp, "同步工具失败")

    st.markdown("---")

    # 添加服务器表单
    st.markdown("#### 添加 MCP 服务器")
    with st.form("add_mcp_server_form"):
        name = st.text_input("服务器名称", key="mcp_server_name_input")
        command = st.text_input(
            "命令（可选，如 python）",
            value="",
            key="mcp_server_command_input",
            help="stdio 接入方式时填写，例如 python",
        )
        args_str = st.text_input(
            "参数（可选，空格分隔）",
            value="",
            key="mcp_server_args_input",
            help="stdio 接入方式时填写，多个参数以空格分隔",
        )
        endpoint_url = st.text_input(
            "端点 URL（必填，如 http://127.0.0.1:8600）",
            value=f"http://127.0.0.1:{st.session_state.mock_server_port}",
            key="mcp_server_endpoint_input",
            help="SSE/HTTP 接入方式时填写",
        )
        add_submitted = st.form_submit_button("添加服务器")
        if add_submitted:
            if not name.strip():
                st.warning("服务器名称不能为空")
            elif not endpoint_url.strip():
                st.warning("端点 URL 不能为空")
            else:
                args_list = args_str.split() if args_str.strip() else None
                resp = client.add_mcp_server(
                    name=name.strip(),
                    command=command.strip() or None,
                    args=args_list,
                    endpoint_url=endpoint_url.strip(),
                )
                if is_api_ok(resp):
                    st.success(resp.get("message", f"服务器 '{name.strip()}' 已添加"))
                else:
                    show_api_error(resp, "添加服务器失败")

    st.markdown("---")

    # 服务器列表
    st.markdown("#### 服务器列表")
    list_resp = client.list_mcp_servers()
    servers = []
    if is_api_ok(list_resp):
        servers = safe_list(list_resp, "servers")
        if servers:
            table_rows = []
            for s in servers:
                tools = s.get("tools") or []
                tools_count = len(tools) if isinstance(tools, list) else 0
                table_rows.append({
                    "name": s.get("name", ""),
                    "status": s.get("status", "unknown"),
                    "tools_count": tools_count,
                    "endpoint_url": s.get("endpoint_url", ""),
                })
            st.dataframe(table_rows, use_container_width=True)
        else:
            st.info("当前没有已注册的 MCP 服务器")
    else:
        show_api_error(list_resp, "获取服务器列表失败")

    st.markdown("---")

    # 服务器操作区
    st.markdown("#### 服务器操作")
    if servers:
        for s in servers:
            sname = s.get("name", "")
            with st.expander(f"服务器：{sname}", expanded=False):
                st.write(f"**状态**: {s.get('status', 'unknown')}")
                st.write(f"**端点**: {s.get('endpoint_url', '')}")
                tools = s.get("tools") or []
                tools_count = len(tools) if isinstance(tools, list) else 0
                st.write(f"**工具数**: {tools_count}")

                col1, col2, col3, col4, col5 = st.columns(5)
                with col1:
                    if st.button("启动", key=f"btn_start_{sname}"):
                        r = client.start_mcp_server(sname)
                        if is_api_ok(r):
                            st.success(r.get("message", "启动请求已发送"))
                        else:
                            show_api_error(r, "启动失败")
                with col2:
                    if st.button("停止", key=f"btn_stop_{sname}"):
                        r = client.stop_mcp_server(sname)
                        if is_api_ok(r):
                            st.success(r.get("message", "停止请求已发送"))
                        else:
                            show_api_error(r, "停止失败")
                with col3:
                    if st.button("删除", key=f"btn_del_{sname}"):
                        r = client.remove_mcp_server(sname)
                        if is_api_ok(r):
                            st.success(r.get("message", "服务器已删除"))
                            st.rerun()
                        else:
                            show_api_error(r, "删除失败")
                with col4:
                    if st.button("健康检查", key=f"btn_health_{sname}"):
                        r = client.check_mcp_health(sname)
                        if is_api_ok(r):
                            st.success("健康检查通过")
                            st.json(r)
                        else:
                            show_api_error(r, "健康检查失败")
                with col5:
                    if st.button("查看工具", key=f"btn_tools_{sname}"):
                        r = client.get_mcp_tools(sname)
                        if is_api_ok(r):
                            tools_list = safe_list(r, "tools")
                            st.success(f"共 {len(tools_list)} 个工具")
                            st.json(tools_list)
                        else:
                            show_api_error(r, "获取工具列表失败")
    else:
        st.info("没有可操作的服务器")


# ===== Tab 3: 工具调用测试 =====
def render_tool_call_tab(client: MainSystemClient) -> None:
    """工具调用测试 Tab：选择服务器/工具 / 调用 / 快捷测试。"""
    st.subheader("工具调用测试")

    # 获取服务器列表
    list_resp = client.list_mcp_servers()
    servers = []
    if is_api_ok(list_resp):
        servers = safe_list(list_resp, "servers")

    if not servers:
        st.info("当前没有已注册的 MCP 服务器，请先在「MCP 管理」Tab 添加服务器")
        return

    # 选择服务器
    server_names = [s.get("name", "") for s in servers]
    sel_server = st.selectbox("选择服务器", server_names, key="call_tool_server_sel")

    if not sel_server:
        st.warning("请选择一个服务器")
        return

    # 获取该服务器的工具列表
    tools_resp = client.get_mcp_tools(sel_server)
    tools = []
    if is_api_ok(tools_resp):
        tools = safe_list(tools_resp, "tools")
    else:
        show_api_error(tools_resp, "获取工具列表失败")
        return

    if not tools:
        st.warning("该服务器没有暴露任何工具")
        return

    # 选择工具
    tool_names = [t.get("name", "") for t in tools]
    sel_tool = st.selectbox("选择工具", tool_names, key="call_tool_name_sel")

    if not sel_tool:
        st.warning("请选择一个工具")
        return

    # 展示工具 Schema
    sel_tool_def = next((t for t in tools if t.get("name", "") == sel_tool), None)
    if sel_tool_def:
        with st.expander("工具参数 Schema", expanded=False):
            st.json(sel_tool_def.get("parameters", {}))

    # 参数 JSON 输入
    args_json = st.text_area(
        "工具参数 JSON",
        value="{}",
        key="call_tool_args_input",
        help="输入工具参数的 JSON 字符串",
    )

    if st.button("调用工具", key="btn_call_mcp_tool"):
        try:
            args = json.loads(args_json)
        except json.JSONDecodeError as e:
            st.error(f"参数 JSON 解析失败: {e}")
        else:
            resp = client.call_mcp_tool(
                server_name=sel_server,
                tool_name=sel_tool,
                arguments=args,
            )
            if is_api_ok(resp):
                st.success("工具调用成功")
                st.json(resp)
            else:
                show_api_error(resp, "工具调用失败")

    st.markdown("---")

    # 快捷测试按钮
    st.markdown("#### 快捷测试")
    st.caption("点击下方按钮自动填充参数并调用对应工具（需服务器已暴露该工具）")

    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("echo 测试", key="btn_quick_echo"):
            quick_args = {"text": "hello from MCP test"}
            resp = client.call_mcp_tool(sel_server, "echo", quick_args)
            if is_api_ok(resp):
                st.success("echo 调用成功")
                st.json(resp)
            else:
                show_api_error(resp, "echo 调用失败")
    with col2:
        if st.button("calculator 测试", key="btn_quick_calc"):
            quick_args = {"expression": "1 + 2 * 3"}
            resp = client.call_mcp_tool(sel_server, "calculator", quick_args)
            if is_api_ok(resp):
                st.success("calculator 调用成功")
                st.json(resp)
            else:
                show_api_error(resp, "calculator 调用失败")
    with col3:
        if st.button("string_reverse 测试", key="btn_quick_reverse"):
            quick_args = {"text": "Streamlit MCP"}
            resp = client.call_mcp_tool(sel_server, "string_reverse", quick_args)
            if is_api_ok(resp):
                st.success("string_reverse 调用成功")
                st.json(resp)
            else:
                show_api_error(resp, "string_reverse 调用失败")


# ===== 主入口 =====
def main() -> None:
    """Streamlit 主入口：侧边栏配置 + 三个 Tab 内容。"""
    st.set_page_config(page_title="MCP 测试工具", page_icon="🔧", layout="wide")
    init_state()

    st.title("MCP 测试工具")

    # 侧边栏配置
    with st.sidebar:
        st.header("配置")
        base_url = st.text_input(
            "主系统地址",
            value=st.session_state.mcp_base_url,
            key="sidebar_base_url",
            help="CX-O 主系统 HTTP 地址，例如 http://localhost:8000",
        )
        if st.button("应用地址", key="btn_apply_url"):
            ensure_client(base_url)
            st.success(f"已切换到 {base_url}")

        st.markdown("---")
        port = st.number_input(
            "模拟 MCP 服务器端口",
            min_value=8000,
            max_value=9999,
            value=int(st.session_state.mock_server_port),
            step=1,
            key="sidebar_mcp_port",
            help="模拟 MCP 服务器的监听端口，默认 8600",
        )
        st.session_state.mock_server_port = int(port)

    # 确保客户端与当前地址一致
    client = ensure_client(base_url)

    # 三个 Tab
    tab_mock, tab_manage, tab_call = st.tabs(["模拟 MCP 服务器", "MCP 管理", "工具调用测试"])

    with tab_mock:
        render_mock_server_tab(client)

    with tab_manage:
        render_mcp_manage_tab(client)

    with tab_call:
        render_tool_call_tab(client)


if __name__ == "__main__":
    main()
