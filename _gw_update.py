# -*- coding: utf-8 -*-
p = "server/gateway/server.py"
s = open(p, encoding="utf-8").read()

# 1. 顶部导入共享连接池
imp_anch = "from server.core.websocket.manager import get_websocket_manager"
assert imp_anch in s
s = s.replace(imp_anch, imp_anch + "\nfrom server.core.utils import get_shared_http_client", 1)

# 2. 代理块改为复用共享 keep-alive 客户端（保留逐请求 timeout=30.0）
old = """        async with httpx.AsyncClient(timeout=30.0) as client:
                try:
                    response = await client.request(
                        method=request.method,
                        url=target_url,
                        headers=headers,
                        content=body if body else None,
                    )
"""
new = """        client = get_shared_http_client()
                try:
                    response = await client.request(
                        method=request.method,
                        url=target_url,
                        headers=headers,
                        content=body if body else None,
                        timeout=30.0,
                    )
"""
assert old in s, "proxy block not found"
s = s.replace(old, new, 1)

open(p, "w", encoding="utf-8").write(s)
print("done")