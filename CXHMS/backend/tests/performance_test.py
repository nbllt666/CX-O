"""
性能测试脚本
测试关键 API 端点的响应时间（不含 LLM 和向量数据库延迟）
"""
import asyncio
import time
from statistics import mean, stdev

import httpx


class PerformanceTester:
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.results = {}

    async def test_endpoint(
        self, client: httpx.AsyncClient, method: str, path: str, json_data=None, iterations: int = 10
    ):
        """测试单个端点的响应时间"""
        times = []
        url = f"{self.base_url}{path}"

        for _ in range(iterations):
            start = time.perf_counter()
            try:
                if method == "GET":
                    response = await client.get(url)
                elif method == "POST":
                    response = await client.post(url, json=json_data)
                else:
                    continue
                elapsed = (time.perf_counter() - start) * 1000  # ms
                if response.status_code < 500:
                    times.append(elapsed)
            except Exception as e:
                print(f"Error testing {path}: {e}")

        if times:
            return {
                "mean": mean(times),
                "min": min(times),
                "max": max(times),
                "stdev": stdev(times) if len(times) > 1 else 0,
                "samples": len(times),
            }
        return None

    async def run_tests(self):
        """运行所有性能测试"""
        async with httpx.AsyncClient(timeout=30.0) as client:
            # 健康检查 - 应该非常快
            print("Testing /api/health...")
            result = await self.test_endpoint(client, "GET", "/api/health")
            if result:
                self.results["health"] = result
                print(f"  Mean: {result['mean']:.2f}ms, Min: {result['min']:.2f}ms, Max: {result['max']:.2f}ms")

            # Agent 列表 - 数据库查询
            print("Testing /api/agents...")
            result = await self.test_endpoint(client, "GET", "/api/agents")
            if result:
                self.results["agents_list"] = result
                print(f"  Mean: {result['mean']:.2f}ms, Min: {result['min']:.2f}ms, Max: {result['max']:.2f}ms")

            # 记忆列表 - 数据库查询
            print("Testing /api/memories...")
            result = await self.test_endpoint(client, "GET", "/api/memories?limit=10")
            if result:
                self.results["memories_list"] = result
                print(f"  Mean: {result['mean']:.2f}ms, Min: {result['min']:.2f}ms, Max: {result['max']:.2f}ms")

            # 工具列表 - 内存操作
            print("Testing /api/tools...")
            result = await self.test_endpoint(client, "GET", "/api/tools")
            if result:
                self.results["tools_list"] = result
                print(f"  Mean: {result['mean']:.2f}ms, Min: {result['min']:.2f}ms, Max: {result['max']:.2f}ms")

            # 会话列表 - 数据库查询
            print("Testing /api/context/sessions...")
            result = await self.test_endpoint(client, "GET", "/api/context/sessions")
            if result:
                self.results["sessions_list"] = result
                print(f"  Mean: {result['mean']:.2f}ms, Min: {result['min']:.2f}ms, Max: {result['max']:.2f}ms")

    def print_summary(self):
        """打印性能摘要"""
        print("\n" + "=" * 60)
        print("Performance Summary (Target: < 120ms, Recommended: < 80ms)")
        print("=" * 60)

        for name, result in self.results.items():
            status = "✅ PASS" if result["mean"] < 120 else "❌ FAIL"
            print(f"{name:20s}: {result['mean']:6.2f}ms {status}")

        print("=" * 60)


async def main():
    tester = PerformanceTester()
    await tester.run_tests()
    tester.print_summary()


if __name__ == "__main__":
    asyncio.run(main())
