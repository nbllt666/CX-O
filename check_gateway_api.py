"""检查 Triton Gateway API"""
import httpx
import json

response = httpx.get("http://127.0.0.1:18081/openapi.json", timeout=10)
print(f"状态: {response.status_code}")

data = response.json()
print("可用端点:")
for path in list(data.get("paths", {}).keys())[:20]:
    print(f"  {path}")
