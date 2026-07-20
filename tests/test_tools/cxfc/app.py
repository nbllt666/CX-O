# CXFC 测试工具 Streamlit UI
import os
import sys
import json

import streamlit as st

# 注入模块搜索路径，避免相对导入问题
_HERE = os.path.dirname(os.path.abspath(__file__))
_TESTS_TOOLS = os.path.dirname(_HERE)   # tests/test_tools
_TESTS = os.path.dirname(_TESTS_TOOLS)  # tests
_PROJECT_ROOT = os.path.dirname(_TESTS) # 项目根

# tests/test_tools：用于 from common.api_client / from cxfc.mock_plugin_server
sys.path.insert(0, _TESTS_TOOLS)
# 项目根：mock_plugin_server 内部使用 from tests.test_tools.common.api_client import ...
sys.path.insert(0, _PROJECT_ROOT)

from common.api_client import MainSystemClient  # noqa: E402
from cxfc.mock_plugin_server import MockPluginServer  # noqa: E402
from cxfc.preset_tools import (  # noqa: E402
    get_preset_definitions,
    list_tool_names,
    get_preset_skills,
    list_skill_names,
    get_multimodal_definitions,
    list_multimodal_tool_names,
    get_modality,
)


# ===== 会话状态初始化 =====
def init_state() -> None:
    """初始化 st.session_state 关键字段，避免 KeyError 与重复创建客户端。"""
    if "cxfc_base_url" not in st.session_state:
        st.session_state.cxfc_base_url = "http://localhost:8000"
    if "client" not in st.session_state:
        st.session_state.client = MainSystemClient(st.session_state.cxfc_base_url)
    if "mock_server" not in st.session_state:
        st.session_state.mock_server = None
    if "plugin_id" not in st.session_state:
        st.session_state.plugin_id = None
    if "tools_definitions" not in st.session_state:
        # 默认加载预置工具定义，模拟插件启动时自带工具
        st.session_state.tools_definitions = get_preset_definitions()
    if "skills_definitions" not in st.session_state:
        # 默认加载预置 skills 定义，模拟插件启动时自带 skills
        st.session_state.skills_definitions = get_preset_skills()
    if "presets_loaded" not in st.session_state:
        st.session_state.presets_loaded = True


def ensure_client(base_url: str) -> MainSystemClient:
    """主系统地址变化时重建客户端，否则复用缓存实例。"""
    if st.session_state.client is None or st.session_state.cxfc_base_url != base_url:
        try:
            st.session_state.client.close()
        except Exception:
            pass
        st.session_state.client = MainSystemClient(base_url)
        st.session_state.cxfc_base_url = base_url
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


def _call_plugin_direct(mock_server, tool_name: str, arguments: dict) -> dict:
    """直连 mock_plugin_server 的 /call 端点，绕过主系统，用于端到端链路验证。

    请求格式与 CXFC 协议一致：{"tool": <name>, "arguments": {...}}。
    当 CX-O-SERVER 的 cxfc 路由未暴露插件 /call 端点时，可用此路径验证多模态工具。
    """
    import httpx
    url = f"http://{mock_server.host}:{mock_server.port}/call"
    try:
        with httpx.Client(timeout=30.0) as c:
            r = c.post(url, json={"tool": tool_name, "arguments": arguments})
            r.raise_for_status()
            return r.json()
    except Exception as e:
        return {"success": False, "error": str(e)}


# ===== Tab 1: 模拟插件 =====
def render_mock_plugin_tab(client: MainSystemClient) -> None:
    """模拟插件 Tab：配置启动 / 运行状态 / 事件日志。"""
    st.subheader("模拟插件")

    mock_server = st.session_state.mock_server

    if mock_server is None:
        # ----- 配置区（模拟服务未启动时显示） -----
        st.markdown("#### 配置")
        with st.form("mock_plugin_config_form"):
            name = st.text_input("插件名称", value="测试插件", key="mock_name")
            port = st.number_input(
                "插件端口", min_value=8000, max_value=9999, value=9000, step=1, key="mock_port"
            )
            heartbeat_interval = st.slider(
                "心跳间隔（秒）", min_value=5, max_value=30, value=10, key="mock_heartbeat"
            )
            capabilities = st.multiselect(
                "能力", options=["tools", "skills", "events"], key="mock_capabilities"
            )
            submitted = st.form_submit_button("启动模拟插件")
            if submitted:
                if not name.strip():
                    st.warning("插件名称不能为空")
                else:
                    try:
                        server = MockPluginServer(
                            host="localhost",
                            port=int(port),
                            name=name.strip(),
                            tools=list(st.session_state.tools_definitions),
                            capabilities=list(capabilities),
                            skills=list(st.session_state.skills_definitions),
                            main_system_url=st.session_state.cxfc_base_url,
                            heartbeat_interval=float(heartbeat_interval),
                        )
                        server.start()
                        plugin_id = server.register_to_main_system()
                        server.start_heartbeat(plugin_id)
                        st.session_state.mock_server = server
                        st.session_state.plugin_id = plugin_id
                        st.success(f"模拟插件已启动，plugin_id: {plugin_id}")
                        st.rerun()
                    except Exception as e:
                        st.error(f"启动模拟插件失败: {e}")
    else:
        # ----- 运行状态区（模拟服务已启动时显示） -----
        st.markdown("#### 运行状态")
        plugin_id = st.session_state.plugin_id or mock_server.plugin_id
        st.markdown("**Plugin ID**")
        st.code(plugin_id or "未知", language="text")

        # 心跳状态：线程存活情况 + 错误数
        heartbeat_alive = (
            mock_server._heartbeat_thread is not None
            and mock_server._heartbeat_thread.is_alive()
        )
        col_h1, col_h2 = st.columns(2)
        with col_h1:
            st.metric("心跳状态", "运行中" if heartbeat_alive else "已停止")
        with col_h2:
            st.metric("心跳错误数", len(mock_server.heartbeat_errors))

        if mock_server.heartbeat_errors:
            with st.expander("查看心跳错误", expanded=False):
                for err in mock_server.heartbeat_errors[-20:]:
                    st.text(err)

        col1, col2 = st.columns(2)
        with col1:
            if st.button("刷新事件日志", key="btn_refresh_events"):
                st.rerun()
        with col2:
            if st.button("停止模拟插件", key="btn_stop_mock"):
                try:
                    mock_server.stop()
                except Exception:
                    pass
                st.session_state.mock_server = None
                st.session_state.plugin_id = None
                st.success("模拟插件已停止")
                st.rerun()

        # ----- 事件日志区 -----
        st.markdown("#### 事件日志")
        events = mock_server.events
        if events:
            st.caption(f"共 {len(events)} 条事件")
            st.json(events)
        else:
            st.info("暂无事件")


# ===== Tab 2: 插件管理 =====
def render_plugin_manage_tab(client: MainSystemClient) -> None:
    """插件管理 Tab：列表 / 发现 / 手动连接 / 插件操作。"""
    st.subheader("插件管理")

    # 顶部操作按钮
    col1, col2 = st.columns(2)
    with col1:
        if st.button("刷新插件列表", key="btn_list_plugins"):
            st.rerun()
    with col2:
        if st.button("发现插件", key="btn_discover"):
            with st.spinner("正在发现插件..."):
                resp = client.cxfc_discover()
            if is_api_ok(resp):
                # 兼容 plugins / discovered 两种可能的字段名
                discovered = safe_list(resp, "plugins") or safe_list(resp, "discovered")
                msg = resp.get("message", f"发现 {len(discovered)} 个插件")
                st.success(msg)
                if discovered:
                    st.dataframe(discovered)
                else:
                    st.info("未发现任何插件")
            else:
                show_api_error(resp, "发现插件失败")

    # 插件列表
    st.markdown("#### 插件列表")
    list_resp = client.cxfc_list_plugins()
    plugins = []
    if is_api_ok(list_resp):
        plugins = safe_list(list_resp, "plugins")
        if plugins:
            st.dataframe(plugins)
        else:
            st.info("当前没有已注册的插件")
    else:
        show_api_error(list_resp, "获取插件列表失败")

    st.markdown("---")

    # 手动连接表单
    st.markdown("#### 手动连接插件")
    with st.form("connect_plugin_form"):
        host = st.text_input("Host", value="127.0.0.1", key="connect_plugin_host")
        port = st.number_input(
            "Port", min_value=1, max_value=65535, value=9000, step=1, key="connect_plugin_port"
        )
        connect_submitted = st.form_submit_button("连接")
        if connect_submitted:
            resp = client.cxfc_connect(host=host.strip(), port=int(port))
            if is_api_ok(resp):
                st.success(resp.get("message", "连接请求已发送"))
            else:
                show_api_error(resp, "连接失败")

    st.markdown("---")

    # 插件操作区
    st.markdown("#### 插件操作")
    if plugins:
        plugin_options = {
            f"{p.get('name', '')} ({p.get('id', '')})": p.get("id", "") for p in plugins
        }
        sel_label = st.selectbox("选择插件", list(plugin_options.keys()), key="plugin_ops_sel")
        sel_pid = plugin_options.get(sel_label, "")

        col_ref, col_del = st.columns(2)
        with col_ref:
            if st.button("刷新工具", key="btn_refresh_plugin"):
                if not sel_pid:
                    st.warning("无效的 plugin_id")
                else:
                    r = client.cxfc_refresh_plugin(plugin_id=sel_pid)
                    if is_api_ok(r):
                        st.success(r.get("message", "刷新请求已发送"))
                    else:
                        show_api_error(r, "刷新插件失败")
        with col_del:
            if st.button("删除插件", key="btn_delete_plugin"):
                if not sel_pid:
                    st.warning("无效的 plugin_id")
                else:
                    r = client.cxfc_delete_plugin(plugin_id=sel_pid)
                    if is_api_ok(r):
                        st.success(r.get("message", "插件已删除"))
                        st.rerun()
                    else:
                        show_api_error(r, "删除插件失败")
    else:
        st.info("没有可操作的插件")


# ===== Tab 3: 工具定义编辑器 =====
def render_tools_editor_tab(client: MainSystemClient) -> None:
    """工具定义编辑器 Tab：展示 / 添加 / 删除 / 应用到模拟插件 / 加载预置 / 测试调用。"""
    st.subheader("工具定义编辑器")

    # 当前工具列表表格展示
    st.markdown("#### 当前工具定义")
    tools = st.session_state.tools_definitions
    if tools:
        table_rows = []
        for t in tools:
            is_preset = t.get("name", "") in list_tool_names()
            table_rows.append({
                "name": t.get("name", ""),
                "description": t.get("description", ""),
                "preset": "是" if is_preset else "否",
                "parameters": json.dumps(t.get("parameters", {}), ensure_ascii=False),
            })
        st.dataframe(table_rows, use_container_width=True)
    else:
        st.info("当前没有工具定义")

    st.markdown("---")

    # 预置工具操作区
    st.markdown("#### 预置工具")
    col_p1, col_p2 = st.columns(2)
    with col_p1:
        if st.button("加载预置工具（追加）", key="btn_load_presets_append"):
            existing_names = {t.get("name", "") for t in st.session_state.tools_definitions}
            added = 0
            for preset in get_preset_definitions():
                if preset["name"] not in existing_names:
                    st.session_state.tools_definitions.append(preset)
                    added += 1
            st.success(f"已追加 {added} 个预置工具（已存在的工具跳过）")
            st.rerun()
    with col_p2:
        if st.button("加载预置工具（覆盖）", key="btn_load_presets_replace"):
            st.session_state.tools_definitions = get_preset_definitions()
            st.success(f"已用 {len(st.session_state.tools_definitions)} 个预置工具覆盖当前定义")
            st.rerun()

    st.markdown("---")

    # 添加工具表单
    st.markdown("#### 添加自定义工具")
    with st.form("add_tool_form"):
        tool_name = st.text_input("工具名称", key="tool_name_input")
        tool_desc = st.text_area("工具描述", key="tool_desc_input")
        params_json = st.text_area(
            "参数 JSON Schema",
            value='{"type": "object", "properties": {}}',
            key="tool_params_input",
            help="输入符合 JSON Schema 规范的参数定义",
        )
        add_submitted = st.form_submit_button("添加工具")
        if add_submitted:
            if not tool_name.strip():
                st.warning("工具名称不能为空")
            else:
                try:
                    params = json.loads(params_json)
                except json.JSONDecodeError as e:
                    st.error(f"参数 JSON 解析失败: {e}")
                else:
                    st.session_state.tools_definitions.append({
                        "name": tool_name.strip(),
                        "description": tool_desc.strip(),
                        "parameters": params,
                    })
                    st.success(f"工具 '{tool_name.strip()}' 已添加")
                    st.rerun()

    st.markdown("---")

    # 工具列表逐项删除
    st.markdown("#### 删除工具")
    if tools:
        for i, t in enumerate(tools):
            cols = st.columns([3, 3, 4, 1])
            with cols[0]:
                st.text(f"name: {t.get('name', '')}")
            with cols[1]:
                desc_text = t.get("description", "")
                st.text(f"desc: {desc_text[:30]}")
            with cols[2]:
                params_text = json.dumps(t.get("parameters", {}), ensure_ascii=False)
                st.text(f"params: {params_text[:40]}")
            with cols[3]:
                if st.button("删除", key=f"del_tool_{i}"):
                    st.session_state.tools_definitions.pop(i)
                    st.success("工具已删除")
                    st.rerun()
    else:
        st.info("没有可删除的工具")

    st.markdown("---")

    # 应用到模拟插件
    st.markdown("#### 应用到模拟插件")
    mock_server = st.session_state.mock_server
    if mock_server is not None:
        if st.button("应用工具定义到模拟插件", key="btn_apply_tools"):
            mock_server.tools = list(st.session_state.tools_definitions)
            st.success(f"已应用 {len(st.session_state.tools_definitions)} 个工具定义到模拟插件")
    else:
        st.warning("模拟插件未启动，无法应用工具定义")

    st.markdown("---")

    # 工具调用测试区
    st.markdown("#### 工具调用测试")
    st.caption("通过主系统 API 调用插件暴露的工具，验证端到端调用链路。")

    mock_server = st.session_state.mock_server
    plugin_id = st.session_state.plugin_id

    if mock_server is None or not plugin_id:
        st.info("请先在「模拟插件」Tab 启动插件并注册到主系统，然后才能测试工具调用。")
    else:
        # 选择工具
        tool_options = {t.get("name", ""): t for t in mock_server.tools}
        if not tool_options:
            st.warning("模拟插件当前没有暴露任何工具")
        else:
            sel_tool_name = st.selectbox(
                "选择工具",
                list(tool_options.keys()),
                key="call_tool_sel",
            )
            sel_tool = tool_options.get(sel_tool_name)
            if sel_tool:
                # 展示参数 Schema
                with st.expander("工具参数 Schema", expanded=False):
                    st.json(sel_tool.get("parameters", {}))

                # 参数 JSON 输入
                args_json = st.text_area(
                    "参数 JSON",
                    value="{}",
                    key="call_tool_args",
                    help="输入工具参数的 JSON 字符串",
                )

                if st.button("调用工具", key="btn_call_tool"):
                    try:
                        args = json.loads(args_json)
                    except json.JSONDecodeError as e:
                        st.error(f"参数 JSON 解析失败: {e}")
                    else:
                        resp = client.cxfc_call_tool(plugin_id=plugin_id, tool=sel_tool_name, arguments=args)
                        if is_api_ok(resp):
                            st.success("工具调用成功")
                            st.json(resp)
                        else:
                            show_api_error(resp, "工具调用失败")

    # 工具调用日志
    if mock_server is not None and mock_server.call_logs:
        st.markdown("---")
        st.markdown("#### 工具调用日志（插件侧）")
        st.caption("模拟插件接收到的工具调用请求记录")
        st.json(mock_server.call_logs[-20:])

    # ===== Skills 定义编辑器 =====
    st.markdown("---")
    st.markdown("## Skills 定义编辑器")
    st.caption("Skills 与 Tools 并列，模拟插件同时暴露 skills 给主系统。")

    # 当前 skills 列表表格展示
    st.markdown("#### 当前 Skills 定义")
    skills = st.session_state.skills_definitions
    if skills:
        skill_rows = []
        for s in skills:
            is_preset = s.get("name", "") in list_skill_names()
            skill_rows.append({
                "name": s.get("name", ""),
                "description": s.get("description", ""),
                "preset": "是" if is_preset else "否",
                "parameters": json.dumps(s.get("parameters", {}), ensure_ascii=False),
            })
        st.dataframe(skill_rows, use_container_width=True)
    else:
        st.info("当前没有 skills 定义")

    st.markdown("---")

    # 预置 skills 操作区
    st.markdown("#### 预置 Skills")
    col_s1, col_s2 = st.columns(2)
    with col_s1:
        if st.button("加载预置 Skills（追加）", key="btn_load_preset_skills_append"):
            existing_names = {s.get("name", "") for s in st.session_state.skills_definitions}
            added = 0
            for preset in get_preset_skills():
                if preset["name"] not in existing_names:
                    st.session_state.skills_definitions.append(preset)
                    added += 1
            st.success(f"已追加 {added} 个预置 Skills（已存在的跳过）")
            st.rerun()
    with col_s2:
        if st.button("加载预置 Skills（覆盖）", key="btn_load_preset_skills_replace"):
            st.session_state.skills_definitions = get_preset_skills()
            st.success(f"已用 {len(st.session_state.skills_definitions)} 个预置 Skills 覆盖当前定义")
            st.rerun()

    st.markdown("---")

    # 添加 skill 表单
    st.markdown("#### 添加自定义 Skill")
    with st.form("add_skill_form"):
        skill_name = st.text_input("Skill 名称", key="skill_name_input")
        skill_desc = st.text_area("Skill 描述", key="skill_desc_input")
        skill_params_json = st.text_area(
            "参数 JSON Schema",
            value='{"type": "object", "properties": {}}',
            key="skill_params_input",
            help="输入符合 JSON Schema 规范的参数定义",
        )
        add_skill_submitted = st.form_submit_button("添加 Skill")
        if add_skill_submitted:
            if not skill_name.strip():
                st.warning("Skill 名称不能为空")
            else:
                try:
                    params = json.loads(skill_params_json)
                except json.JSONDecodeError as e:
                    st.error(f"参数 JSON 解析失败: {e}")
                else:
                    st.session_state.skills_definitions.append({
                        "name": skill_name.strip(),
                        "description": skill_desc.strip(),
                        "parameters": params,
                    })
                    st.success(f"Skill '{skill_name.strip()}' 已添加")
                    st.rerun()

    st.markdown("---")

    # skill 列表逐项删除
    st.markdown("#### 删除 Skill")
    if skills:
        for i, s in enumerate(skills):
            cols = st.columns([3, 3, 4, 1])
            with cols[0]:
                st.text(f"name: {s.get('name', '')}")
            with cols[1]:
                desc_text = s.get("description", "")
                st.text(f"desc: {desc_text[:30]}")
            with cols[2]:
                params_text = json.dumps(s.get("parameters", {}), ensure_ascii=False)
                st.text(f"params: {params_text[:40]}")
            with cols[3]:
                if st.button("删除", key=f"del_skill_{i}"):
                    st.session_state.skills_definitions.pop(i)
                    st.success("Skill 已删除")
                    st.rerun()
    else:
        st.info("没有可删除的 Skill")

    st.markdown("---")

    # 应用 skills 到模拟插件
    st.markdown("#### 应用 Skills 到模拟插件")
    mock_server = st.session_state.mock_server
    if mock_server is not None:
        if st.button("应用 Skills 定义到模拟插件", key="btn_apply_skills"):
            mock_server.set_skills(list(st.session_state.skills_definitions))
            st.success(f"已应用 {len(st.session_state.skills_definitions)} 个 Skills 定义到模拟插件")
    else:
        st.warning("模拟插件未启动，无法应用 Skills 定义")



# ===== Tab 4: 多模态工具调用 =====
def render_multimodal_tab(client: MainSystemClient) -> None:
    """多模态工具调用 Tab：调用 video_summary / audio_transcribe。

    对齐 CX-O CXFC 多模态工具契约（modality 字段）。
    支持两种调用路径：
    - via_server: 经由 CX-O-SERVER (POST /api/cxfc/plugins/{plugin_id}/call)
    - direct: 直连 mock_plugin_server (POST http://{host}:{port}/call)
    """
    st.subheader("多模态工具调用")
    st.caption("CX-O 扩展：视频摘要 / 音频转写。对齐 CX-O CXFC 多模态工具契约（modality 字段）。")

    mm_defs = get_multimodal_definitions()
    if not mm_defs:
        st.warning("未找到多模态工具定义")
        return

    tool_options = {t["name"]: t for t in mm_defs}
    sel_name = st.selectbox("选择多模态工具", list(tool_options.keys()), key="mm_tool_sel")
    sel_tool = tool_options.get(sel_name)
    if not sel_tool:
        return

    col_m1, col_m2 = st.columns(2)
    with col_m1:
        st.metric("模态 (modality)", sel_tool.get("modality", ""))
    with col_m2:
        st.metric("类别 (type)", sel_tool.get("type", ""))
    with st.expander("工具参数 Schema", expanded=False):
        st.json(sel_tool.get("parameters", {}))

    st.markdown("---")

    # 参数输入区（按工具名分支）
    args: Dict[str, Any] = {}
    if sel_name == "video_summary":
        video_url = st.text_input("video_url", value="", key="mm_video_url", help="视频资源 URL")
        max_length = st.number_input(
            "max_length（可选）", min_value=10, max_value=2000, value=200, step=10, key="mm_max_length"
        )
        args["video_url"] = video_url.strip()
        args["max_length"] = int(max_length)
    elif sel_name == "audio_transcribe":
        audio_url = st.text_input("audio_url", value="", key="mm_audio_url", help="音频资源 URL")
        language = st.text_input(
            "language（可选）", value="auto", key="mm_language", help="音频语言，默认 auto"
        )
        args["audio_url"] = audio_url.strip()
        args["language"] = language.strip() or "auto"

    st.markdown("#### 调用模式")
    call_mode = st.radio(
        "选择调用路径",
        options=["via_server", "direct"],
        format_func=lambda x: (
            "经由 CX-O-SERVER (POST /api/cxfc/plugins/{plugin_id}/call)"
            if x == "via_server"
            else "直连插件 (POST http://{plugin_host}:{plugin_port}/call)"
        ),
        key="mm_call_mode",
        help="CX-O-SERVER 的 cxfc 路由当前未暴露插件 /call 端点；如经由主系统返回 404，可改用直连插件模式验证链路。",
    )

    mock_server = st.session_state.mock_server
    plugin_id = st.session_state.plugin_id

    if call_mode == "via_server":
        if mock_server is None or not plugin_id:
            st.info("经由 CX-O-SERVER 调用需要先在「模拟插件」Tab 启动插件并注册到主系统。")
            return
    else:
        if mock_server is None:
            st.info("直连插件调用需要先在「模拟插件」Tab 启动插件。")
            return

    if st.button("调用多模态工具", key="btn_call_mm", type="primary"):
        if sel_name == "video_summary" and not args.get("video_url"):
            st.error("video_url 不能为空")
            return
        if sel_name == "audio_transcribe" and not args.get("audio_url"):
            st.error("audio_url 不能为空")
            return

        with st.spinner("正在调用..."):
            if call_mode == "via_server":
                resp = client.cxfc_call_tool(plugin_id=plugin_id, tool=sel_name, arguments=args)
            else:
                resp = _call_plugin_direct(mock_server, sel_name, args)

        if is_api_ok(resp):
            st.success("多模态工具调用成功")
            st.json(resp)
        else:
            show_api_error(resp, "多模态工具调用失败")
            if call_mode == "via_server":
                st.caption(
                    "提示：CX-O-SERVER 的 cxfc 路由当前未暴露 /api/cxfc/plugins/{plugin_id}/call；"
                    "如需端到端验证，请改用「直连插件」模式。"
                )

    if mock_server is not None and mock_server.call_logs:
        st.markdown("---")
        st.markdown("#### 插件侧调用日志")
        st.json(mock_server.call_logs[-10:])


# ===== 主入口 =====
def main() -> None:
    """Streamlit 主入口：侧边栏配置 + 四个 Tab 内容。"""
    init_state()

    st.title("CXFC 测试工具")

    # 侧边栏配置
    with st.sidebar:
        st.header("配置")
        base_url = st.text_input(
            "主系统地址",
            value=st.session_state.cxfc_base_url,
            key="sidebar_base_url",
            help="CX-O-SERVER 主系统 HTTP 地址，例如 http://localhost:8000",
        )
        if st.button("应用地址", key="btn_apply_url"):
            ensure_client(base_url)
            st.success(f"已切换到 {base_url}")

    # 确保客户端与当前地址一致
    client = ensure_client(base_url)

    # 四个 Tab
    tab_mock, tab_manage, tab_tools, tab_mm = st.tabs(["模拟插件", "插件管理", "工具定义编辑器", "多模态工具调用"])

    with tab_mock:
        render_mock_plugin_tab(client)

    with tab_manage:
        render_plugin_manage_tab(client)

    with tab_tools:
        render_tools_editor_tab(client)

    with tab_mm:
        render_multimodal_tab(client)


if __name__ == "__main__":
    main()
