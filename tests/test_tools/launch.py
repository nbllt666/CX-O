# CXHMS 测试工具统一启动入口
import os
import sys
import shutil
import subprocess


def find_streamlit_python():
    """查找可用的 streamlit 运行方式。

    优先级：
    1. 当前 Python（如果已安装 streamlit）
    2. streamlit 命令（可能来自 Anaconda 或其他环境）
    3. Anaconda Python（常见路径）
    """
    # 1. 检查当前 Python 是否有 streamlit
    try:
        import streamlit  # noqa: F401

        return ("python_module", sys.executable)
    except ImportError:
        pass

    # 2. 检查 streamlit 命令是否在 PATH 中
    streamlit_cmd = shutil.which("streamlit")
    if streamlit_cmd:
        return ("command", streamlit_cmd)

    # 3. 检查常见 Anaconda 路径
    anaconda_paths = [
        r"C:\ProgramData\Anaconda3\python.exe",
        r"C:\Users\{}\Anaconda3\python.exe".format(os.environ.get("USERNAME", "")),
        r"C:\Anaconda3\python.exe",
    ]
    for path in anaconda_paths:
        if os.path.exists(path):
            try:
                result = subprocess.run(
                    [path, "-c", "import streamlit"],
                    capture_output=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    return ("python_module", path)
            except Exception:
                continue

    return (None, None)


def main() -> None:
    """根据命令行参数启动对应的 Streamlit 测试工具。"""
    script_dir = os.path.dirname(os.path.abspath(__file__))

    if len(sys.argv) < 2:
        print("使用说明：")
        print(f"  python {os.path.join(script_dir, 'launch.py')} <tool>")
        print("可用的 tool：")
        print("  cxfc  - 启动 CXFC 测试工具 (端口 8501)")
        print("  acp   - 启动 ACP 聊天测试工具 (端口 8502)")
        print("  mcp   - 启动 MCP 测试工具 (端口 8504)")
        return

    tool = sys.argv[1].lower()
    cxfc_app = os.path.join(script_dir, "cxfc", "app.py")
    acp_app = os.path.join(script_dir, "acp", "app.py")
    mcp_app = os.path.join(script_dir, "mcp", "app.py")

    if tool == "cxfc":
        app_path = cxfc_app
        port = 8501
    elif tool == "acp":
        app_path = acp_app
        port = 8502
    elif tool == "mcp":
        app_path = mcp_app
        port = 8504
    else:
        print(f"未知工具：{tool}")
        print("可用工具：cxfc | acp | mcp")
        sys.exit(1)

    run_mode, run_target = find_streamlit_python()

    if run_mode == "python_module":
        cmd = [run_target, "-m", "streamlit", "run", app_path, f"--server.port={port}", "--server.headless=true"]
    elif run_mode == "command":
        cmd = [run_target, "run", app_path, f"--server.port={port}", "--server.headless=true"]
    else:
        print("错误：未找到可用的 streamlit。")
        print("请安装 streamlit: pip install streamlit")
        print(f"已尝试的 Python: {sys.executable}")
        print("已尝试 PATH 中的 streamlit 命令和常见 Anaconda 路径")
        sys.exit(1)

    print(f"启动 {tool.upper()} 测试工具 (端口 {port})")
    print(f"  应用: {app_path}")
    print(f"  运行方式: {run_mode} -> {run_target}")
    print()

    subprocess.run(cmd, check=False)


if __name__ == "__main__":
    main()
