"""E2E 桩：模拟 neko 插件服务器。

读取 NEKO_USER_PLUGIN_SERVER_PORT 环境变量并在 127.0.0.1 上监听该端口，
对任意 GET 请求返回 200 JSON，用于模拟"插件服务器就绪"，避免依赖真实 neko 源码。
由适配器以 `python -m plugin.user_plugin_server` 方式拉起（cwd/PYTHONPATH 指向临时 sourceDir）。
"""
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = int(os.environ.get("NEKO_USER_PLUGIN_SERVER_PORT", "0"))
assert PORT > 0, "缺少环境变量 NEKO_USER_PLUGIN_SERVER_PORT"


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = ('{"ok": true, "service": "stub-plugin-server", "port": %d}' % PORT).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass  # 静默访问日志


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
