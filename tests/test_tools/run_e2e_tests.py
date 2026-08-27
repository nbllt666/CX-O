"""端到端测试统一入口

重新运行三组 E2E 测试，输出完整证据日志：
  1. CXFC 端到端：模拟插件注册主系统 → 主系统转发工具调用 → 插件实际执行
  2. ACP 单向：独立节点 → 主系统（POST /api/acp/receive）
  3. ACP 双向：独立节点 ↔ 主系统（节点收发均可）

运行方式：
  python tests/test_tools/run_e2e_tests.py

前置条件：
  - 主系统后端运行在 http://localhost:8000

第四轮体检收尾重构（20260827）：
  本聚合器不再以子进程方式盲调 e2e/ 下的 pytest 形态测试文件——那批文件
  （test_distillation_e2e.py 等）历史上从未入库（曾被根 *_test.py 忽略规则
  吞掉后从未 add），盲调只会产生必走 FAIL 的假失败入口。
  取而代之，main() 结尾打印 tests/test_tools/e2e/ 下现存独立脚本的手动运行
  指引（每个脚本一行用途 + 命令示例），由开发者按需人工触发。
  ※ 完整 pytest 形态 E2E 套件（含上述文件的补建/入库治理）待另行立项，暂缓。
"""
import sys
import time

# 注入项目根路径，便于直接以脚本方式运行
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tests.test_tools.cxfc.mock_plugin_server import MockPluginServer
from tests.test_tools.cxfc.preset_tools import get_preset_definitions
from tests.test_tools.common.api_client import MainSystemClient
from tests.test_tools.acp.acp_node import ACPNode

# 第四轮体检收尾（20260827）：tests/test_tools/e2e/ 下现存独立诊断/E2E 脚本清单
# （各脚本均可单独人工触发，退出码约定见各脚本自身文档）
MANUAL_E2E_SCRIPTS = [
    # (脚本名, 一行用途)
    ("voice_chat_e2e.py", "语音问答全链路 E2E（输入→ASR→LLM→TTS 回放冒烟）"),
    ("full_duplex_live.py", "全双工实时通话链路（WS 上行音频 ↔ 下行播报联调）"),
    ("duplex_latency.py", "双工链路分段延迟测量（VAD 打断 / 首包延迟）"),
    ("gen_test_audio.py", "生成本地测试音频样本（供 ASR/TTS 用例输入）"),
    ("analyze_silence.py", "分析音频静音段分布（辅助 VAD 阈值调参）"),
    ("capture_tts_audio_sample.py", "抓取 TTS 输出音频样本落盘（音质抽查）"),
    ("generate_edgetts_reference.py", "用 Edge-TTS 生成参考音频基准"),
    ("diag_asr_candidates.py", "诊断 ASR 多候选（candidates）返回行为"),
    ("diag_asr_direct.py", "直连 ASR 服务健康诊断"),
    ("diag_asr_latency.py", "ASR 分环节延迟诊断"),
    ("diag_tts_chunks.py", "TTS 流式分块（chunking）行为诊断"),
    ("diag_ws_dump.py", "WebSocket 报文全量转储排查"),
    ("diag_ws_final.py", "WebSocket 会话终态收尾时序诊断"),
    ("diag_ws_replicate.py", "WebSocket 会话复现（replicate）诊断"),
    ("_diag_halluc_filter.py", "幻觉过滤（hallucination filter）专项诊断"),
]


MAIN_HOST = "localhost"
# 第四轮体检修复：后端默认端口已统一为 8000（对齐 base.ts / start.bat / ConnectionSetup）
MAIN_PORT = 8000
MAIN_URL = f"http://{MAIN_HOST}:{MAIN_PORT}"


def _print(tag, msg):
    print(f"[{tag}] {msg}")


def _wait(predicate, timeout=10.0, interval=0.2, label=""):
    """简单轮询等待条件成立"""
    start = time.time()
    while time.time() - start < timeout:
        try:
            if predicate():
                return True
        except Exception:
            pass
        time.sleep(interval)
    return False


def test_cxfc_e2e():
    print("\n========== [1] CXFC 端到端测试 ==========")
    # 选取一个空闲端口，避免与运行中的 9000 冲突
    plugin_port = 9001
    preset_defs = get_preset_definitions()
    _print("setup", f"preset_tools count = {len(preset_defs)}")

    plugin = MockPluginServer(
        host="localhost",
        port=plugin_port,
        name="E2E-CXFC-Plugin",
        tools=preset_defs,
        capabilities=["tools"],
        main_system_url=MAIN_URL,
        heartbeat_interval=30.0,
    )
    plugin.start()
    if not _wait(lambda: plugin._server is not None and plugin._server.started,
                 timeout=8.0, label="plugin server start"):
        _print("error", "插件服务未能在 8s 内启动")
        plugin.stop()
        return False
    _print("1", f"Mock plugin started on port {plugin_port} with {len(preset_defs)} preset tools")

    plugin_id = plugin.register_to_main_system()
    _print("2", f"Registered to main system, plugin_id: {plugin_id}")
    if not plugin_id:
        _print("error", "插件注册失败")
        plugin.stop()
        return False

    client = MainSystemClient(base_url=MAIN_URL)
    try:
        # 调用 echo
        r_echo = client.cxfc_call_tool(plugin_id, "echo", {"message": "hello e2e"})
        _print("3", f"echo tool call result: {r_echo}")

        # 调用 calculator add 10 + 32 = 42
        r_calc = client.cxfc_call_tool(plugin_id, "calculator",
                                       {"operation": "add", "a": 10, "b": 32})
        _print("4", f"calculator add result: {r_calc}")

        # 调用 string_reverse
        r_rev = client.cxfc_call_tool(plugin_id, "string_reverse", {"text": "streamlit"})
        _print("5", f"string_reverse result: {r_rev}")

        _print("6", f"Plugin call logs count: {len(plugin.call_logs)}")
    finally:
        client.close()
        plugin.stop()

    # 校验结果
    echo_ok = r_echo.get("status") == "ok" and r_echo["result"].get("success") and r_echo["result"].get("result") == "hello e2e"
    calc_ok = r_calc.get("status") == "ok" and r_calc["result"].get("success") and r_calc["result"].get("result") == 42.0
    rev_ok = r_rev.get("status") == "ok" and r_rev["result"].get("success") and r_rev["result"].get("result") == "tilmaerts"
    passed = echo_ok and calc_ok and rev_ok
    print(f"=== CXFC E2E {'PASSED' if passed else 'FAILED'} ===")
    return passed


def test_acp_unidirectional():
    print("\n========== [2] ACP 单向测试（节点 → 主系统） ==========")
    node_port = 8541
    node = ACPNode(
        agent_id="e2e-acp-node",
        agent_name="E2E ACP Node",
        http_host="0.0.0.0",
        http_port=node_port,
        capabilities=["chat"],
        discovery_interval=30,
    )
    start_r = node.start()
    _print("1", f"ACP node start: {start_r.get('success')} agent_id: {node.agent_id}")
    if not start_r.get("success"):
        node.stop()
        return False

    reg = node.register_main_system(MAIN_HOST, MAIN_PORT)
    main_agent_id = reg["agent"]["id"]
    main_agent_name = reg["agent"]["name"]
    _print("2", f"main_agent_id: {main_agent_id}  main_agent_name: {main_agent_name}")

    r_send = node.send_to_main_system(
        main_system_host=MAIN_HOST,
        main_system_port=MAIN_PORT,
        main_system_agent_id=main_agent_id,
        content={"text": "Hello from E2E unidir node"},
    )
    _print("3", f"Send to main system: {r_send.get('success')}")
    _print("3b", f"Response: {r_send.get('response')}")

    # 从主系统 stats 验证消息已接收
    client = MainSystemClient(base_url=MAIN_URL)
    try:
        stats_resp = client.acp_get_stats()
    finally:
        client.close()
    stats = stats_resp.get("statistics", {}) if isinstance(stats_resp, dict) else {}
    _print("4", f"Stats: total_messages={stats.get('total_messages')}, "
                 f"total_agents={stats.get('total_agents')}, "
                 f"messages_sent={stats.get('messages_sent')}")

    node.stop()
    # H11: 断言不再硬编码具体 agent_id（曾写死 "cxhms-agent-001"，配置缺省为
    # cxo-agent-001，环境变化即误报 FAIL）——改为验证运行时注册 id 非空 + 发送成功。
    passed = bool(r_send.get("success")) and bool(main_agent_id)
    print(f"=== ACP E2E {'PASSED' if passed else 'FAILED'} ===")
    return passed


def test_acp_bidirectional():
    print("\n========== [3] ACP 双向测试（节点 ↔ 主系统） ==========")
    # 使用固定 agent_id 验证端口更新修复：即使主系统残留旧端口，新消息应更新为新端口
    fixed_id = "e2e-bidir-node"
    node_port = 8542
    node = ACPNode(
        agent_id=fixed_id,
        agent_name="E2E Bidir Node",
        http_host="0.0.0.0",
        http_port=node_port,
        capabilities=["chat"],
        discovery_interval=30,
    )
    start_r = node.start()
    _print("1", f"ACP node start: {start_r.get('success')} agent_id: {fixed_id} port: {node_port}")
    if not start_r.get("success"):
        node.stop()
        return False

    reg = node.register_main_system(MAIN_HOST, MAIN_PORT)
    main_agent_id = reg["agent"]["id"]
    _print("2", f"main_agent_id: {main_agent_id}")

    r_send = node.send_to_main_system(
        main_system_host=MAIN_HOST,
        main_system_port=MAIN_PORT,
        main_system_agent_id=main_agent_id,
        content={"text": "Hello from bidir node"},
    )
    _print("3", f"Send to main: {r_send.get('success')}")

    # 等主系统把节点注册（含 host:port）后，主系统 → 节点投递
    time.sleep(1.0)
    client = MainSystemClient(base_url=MAIN_URL)
    try:
        agents_resp = client.acp_list_agents()
    finally:
        client.close()
    agents = agents_resp.get("agents", []) if isinstance(agents_resp, dict) else []
    _print("4", f"Main agents count: {len(agents)}")
    node_agent = next((a for a in agents if a.get("id") == fixed_id), None)
    _print("4b", f"Node registered host= {node_agent.get('host') if node_agent else None} "
                  f"port= {node_agent.get('port') if node_agent else None} "
                  f"(expected port={node_port})")

    # 主系统 → 节点
    client = MainSystemClient(base_url=MAIN_URL)
    try:
        r_back = client.acp_send_message(
            to_agent_id=fixed_id,
            content={"text": "Hello back from main"},
        )
    finally:
        client.close()
    _print("5", f"Main send to node: {r_back}")

    # 等节点收到回送消息
    _wait(lambda: len(node.get_messages()) >= 2, timeout=5.0, label="node receive back")
    msgs = node.get_messages()
    _print("6", f"Node messages: {len(msgs)}")
    for m in msgs:
        direction = "SENT" if m.get("is_sent") else "RECV"
        text = (m.get("content") or {}).get("text", "")
        _print("6b", f"[{direction}] {m.get('from_agent_id')} -> {m.get('to_agent_id')}: {text}")

    node.stop()
    has_sent = any(m.get("is_sent") for m in msgs)
    has_recv = any(not m.get("is_sent") for m in msgs)
    r_back_ok = isinstance(r_back, dict) and r_back.get("status") == "success"
    # 额外校验：主系统注册的端口应等于节点实际端口（验证端口更新修复）
    port_updated = node_agent and node_agent.get("port") == node_port
    passed = bool(r_send.get("success")) and r_back_ok and has_sent and has_recv and port_updated
    print(f"=== ACP BIDIR E2E {'PASSED' if passed else 'FAILED'} ===")
    return passed


def _print_manual_scripts():
    """打印 tests/test_tools/e2e/ 下现存脚本的手动运行指引。

    这些脚本多为独立人工触发的链路验证/诊断工具（依赖 CX-O-SERVER 在线或真实
    音频设备），不由本聚合器自动调度，因此不存在"文件缺失即 FAIL"的假失败路径。
    """
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    e2e_dir = os.path.join(project_root, "tests", "test_tools", "e2e")
    print("\n========== e2e/ 现存脚本 · 手动运行指引 ==========")
    print("# 需要服务在场时先启动 CX-O-SERVER（默认 http://localhost:8000）")
    stale = False
    for name, desc in MANUAL_E2E_SCRIPTS:
        exists = os.path.isfile(os.path.join(e2e_dir, name))
        stale = stale or not exists
        mark = "*" if exists else "?"
        print(f"  [{mark}] {desc}")
        print(f"        python tests/test_tools/e2e/{name}")
    if stale:
        print("  [?] 标记表示清单过期：脚本已不在盘上，请校订 MANUAL_E2E_SCRIPTS")


def main():
    print("###############################################")
    print("# 测试工具独立服务化 — 端到端验证")
    print(f"# 主系统: {MAIN_URL}")
    print(f"# 时间:   {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("###############################################")

    results = {}
    # 3 组主系统集成测试（需 CX-O-SERVER 运行）
    results["cxfc"] = test_cxfc_e2e()
    results["acp_uni"] = test_acp_unidirectional()
    results["acp_bidir"] = test_acp_bidirectional()

    # e2e/ 目录下的其余脚本改为手动运行指引输出（不自动调度、不计入 PASS/FAIL 汇总）
    _print_manual_scripts()

    print("\n========== 汇总 ==========")
    pass_count = sum(1 for ok in results.values() if ok)
    fail_count = sum(1 for ok in results.values() if not ok)
    for name, ok in results.items():
        print(f"  {name}: {'PASS' if ok else 'FAIL'}")
    all_pass = all(results.values())
    print(f"\n>>> 总体结论: {'ALL PASSED' if all_pass else 'SOME FAILED'}  (PASS={pass_count}, FAIL={fail_count})")
    print(">>> 注：SKIP 视为 PASS 不阻断总体，但汇总行会标注 SKIP；详见各测试 [result] 行")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
