"""OpenAI 兼容 LLM-as-judge 客户端（httpx 同步）。

失败两级区分：
  - 网络层异常（连接/超时/HTTP 状态错误）：重试 ≤2 次（共最多 3 次尝试），
    全部失败抛 JudgeUnavailableError（整个 run 降级用）
  - 模型输出不可解析/字段缺失/分数越界：同样重试 ≤2 次，全部失败返回
    {"judge_failed": True, "error": ...}（单案例失败用）

约定 judge 模型输出 JSON: {"scores": {...}, "reason": "..."}，容忍 markdown 代码块包裹。
分数有效域 [0.0, 5.0]（对齐 thresholds.quality.avg_min 的 5 分制）。
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional, Tuple

import httpx

from evalkit.config import EvalConfig

SCORE_MIN = 0.0
SCORE_MAX = 5.0
_MAX_ATTEMPTS = 3  # 初次 + 重试 2 次


class JudgeUnavailableError(RuntimeError):
    """judge 服务网络层不可用（整个 run 降级用）。"""


class JudgeClient:
    """OpenAI 兼容 chat/completions 客户端。

    transport 参数供测试注入 httpx.MockTransport，生产环境保持 None。
    """

    def __init__(self, config: EvalConfig, transport: Optional[httpx.BaseTransport] = None):
        judge = config.judge
        base = (judge.api_base or config.target.base_url).rstrip("/")
        # api_base 已含 /v1 时直接拼 /chat/completions，否则补 /v1 前缀
        if base.endswith("/v1"):
            self.endpoint = f"{base}/chat/completions"
        else:
            self.endpoint = f"{base}/v1/chat/completions"
        self.model = judge.model
        self.api_key = judge.api_key
        self.timeout_seconds = judge.timeout_seconds
        self._transport = transport

    def score(self, prompt: str) -> Dict[str, Any]:
        """评分单条 prompt。成功返回 {"scores": {...}, "reason": ...}。"""
        last_error = ""
        last_is_network = False
        for _ in range(_MAX_ATTEMPTS):
            try:
                data = self._request_chat(prompt)
            except httpx.HTTPError as exc:
                last_error, last_is_network = f"网络/HTTP 失败: {exc}", True
                continue
            content = self._extract_content(data)
            if content is None:
                last_error = "响应缺少 choices[0].message.content"
                last_is_network = False
                continue
            ok, result = self._parse_output(content)
            if ok:
                return result
            last_error, last_is_network = result, False
        if last_is_network:
            raise JudgeUnavailableError(last_error)
        return {"judge_failed": True, "error": last_error}

    def _request_chat(self, prompt: str) -> Dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        }
        # trust_env=False：同 target.py，绕过 Windows 注册表系统代理（企业环境实测 502 教训）
        with httpx.Client(timeout=self.timeout_seconds, transport=self._transport,
                          trust_env=False) as client:
            resp = client.post(self.endpoint, json=payload, headers=headers)
            resp.raise_for_status()
            return resp.json()

    @staticmethod
    def _extract_content(data: Dict[str, Any]) -> Optional[str]:
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return None
        return content if isinstance(content, str) else None

    @staticmethod
    def _parse_output(content: str) -> Tuple[bool, Any]:
        """解析 judge 输出。成功返回 (True, {"scores":..., "reason":...})，失败 (False, 错误描述)。"""
        text = content.strip()
        if text.startswith("```"):
            text = re.sub(r"^```[A-Za-z0-9_-]*\s*", "", text)
            text = re.sub(r"\s*```\s*$", "", text).strip()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            return False, f"judge 输出 JSON 解析失败: {exc}"
        if not isinstance(parsed, dict):
            return False, "judge 输出不是 JSON 对象"
        scores = parsed.get("scores")
        reason = parsed.get("reason")
        if not isinstance(scores, dict) or not scores:
            return False, "缺少 scores 字段（非空对象）"
        if not isinstance(reason, str):
            return False, "缺少 reason 字段（字符串）"
        for key, value in scores.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return False, f"分数 {key!r} 非数值"
            if not (SCORE_MIN <= float(value) <= SCORE_MAX):
                return False, (
                    f"分数 {key!r}={value} 越界（有效域 [{SCORE_MIN}, {SCORE_MAX}]）"
                )
        return True, {"scores": scores, "reason": reason}


def build_judge(config: EvalConfig, transport: Optional[httpx.BaseTransport] = None) -> JudgeClient:
    """suite 统一入口：mock.enabled=true 时自动接入内置 stub transport（确定性判分）。"""
    if config.mock.enabled:
        from evalkit.stub import build_stub_transport

        transport = build_stub_transport(config.mock.chat_delay_ms)
    return JudgeClient(config, transport=transport)
