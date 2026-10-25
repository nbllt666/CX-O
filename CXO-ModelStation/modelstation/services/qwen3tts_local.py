"""本地 Qwen3-TTS 客户端（替代外部 vLLM 运行时，供统一语料生成使用）。

链路：DatasetBuilder → 本客户端（async）→ 引擎 python 子进程
``engines/Qwen3TTS/server.py``（模型常驻，stdin/stdout JSONL 协议）。

- design：VoiceDesign 模型，按音色描述合成；
- clone：Base 模型，参考音频 + 转写做 3 秒克隆；
- 模型目录：``CXO_QWEN3TTS_MODELS`` → 缺省 ``data/models/qwen3tts``；
  目录不存在时引擎侧回退 HuggingFace/ModelScope 仓库 ID（首次自动下载）。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Optional

from modelstation.config import get_settings

logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT = 600.0  # 首次加载模型/长句合成的宽松上限
_START_TIMEOUT = 30.0


class LocalQwen3TTSError(RuntimeError):
    """本地 Qwen3-TTS 合成失败（协议层 / 引擎异常）。"""


class LocalQwen3TTSClient:
    """进程内单例式的本地 Qwen3-TTS 客户端（懒启动服务子进程）。"""

    def __init__(self) -> None:
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._lock = asyncio.Lock()
        self._stderr_task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------
    # 引擎路径 / 模型目录
    # ------------------------------------------------------------------
    def _engine_dir(self) -> Path:
        settings = get_settings()
        return Path(settings.melotts.engine_dir).parent / "Qwen3TTS"

    def _model_root(self) -> Path:
        env = os.environ.get("CXO_QWEN3TTS_MODELS", "").strip()
        if env:
            return Path(env)
        models_dir = Path(get_settings().melotts.models_dir)
        return models_dir.parent / "qwen3tts"

    def _python_path(self) -> str:
        return get_settings().melotts.python_path

    # ------------------------------------------------------------------
    # 服务生命周期
    # ------------------------------------------------------------------
    async def _ensure_server(self) -> asyncio.subprocess.Process:
        if self._proc is not None and self._proc.returncode is None:
            return self._proc
        engine_dir = self._engine_dir()
        script = engine_dir / "server.py"
        if not script.is_file():
            raise LocalQwen3TTSError(f"Qwen3-TTS 引擎脚本缺失: {script}")
        env = {
            **os.environ,
            "PYTHONPATH": str(engine_dir / "pylibs"),
            "PYTHONIOENCODING": "utf-8",
            "HF_HUB_DISABLE_TELEMETRY": "1",
        }
        self._proc = await asyncio.create_subprocess_exec(
            self._python_path(),
            str(script),
            "--model-root", str(self._model_root()),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            cwd=str(engine_dir),
        )
        self._stderr_task = asyncio.create_task(self._drain_stderr(self._proc))
        logger.info("Qwen3-TTS 本地服务已启动（pid=%s）", self._proc.pid)
        return self._proc

    async def _drain_stderr(self, proc: asyncio.subprocess.Process) -> None:
        """持续消费 stderr，避免管道写满阻塞子进程；保留尾部便于排障。"""
        if proc.stderr is None:
            return
        tail: list[str] = []
        while True:
            line = await proc.stderr.readline()
            if not line:
                break
            tail.append(line.decode("utf-8", errors="replace").rstrip())
            if len(tail) > 40:
                tail.pop(0)
        if tail:
            logger.info("Qwen3-TTS 引擎 stderr 尾部: %s", " | ".join(tail[-5:]))

    async def _request(self, payload: dict) -> None:
        resp = await self._request_dict(payload)
        if not resp.get("ok"):
            raise LocalQwen3TTSError(str(resp.get("error") or "unknown engine error"))

    async def _request_dict(self, payload: dict) -> dict:
        async with self._lock:
            proc = await self._ensure_server()
            assert proc.stdin is not None and proc.stdout is not None
            proc.stdin.write((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
            await proc.stdin.drain()
            try:
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=_REQUEST_TIMEOUT)
            except asyncio.TimeoutError as exc:
                raise LocalQwen3TTSError(
                    f"Qwen3-TTS 合成超时（>{_REQUEST_TIMEOUT}s）"
                ) from exc
            if not line:
                raise LocalQwen3TTSError("Qwen3-TTS 服务进程已退出（无响应）")
            return json.loads(line.decode("utf-8", errors="replace"))

    async def synthesize_batch(
        self,
        engine: str,
        texts: list[str],
        engine_params: dict,
        output_paths: list,
    ) -> list[Optional[str]]:
        """批量合成（一次引擎调用多句），返回逐条错误（None=成功）。"""
        if not texts:
            return []
        params = engine_params or {}
        payload: dict = {
            "texts": [str(t) for t in texts],
            "outputs": [str(p) for p in output_paths],
            "language": "Chinese",
        }
        if engine == "qwen3_voicedesign":
            payload.update(
                mode="design", instruct=str(params.get("voice_description") or "")
            )
        elif engine == "cosyvoice3_zero":
            payload.update(
                mode="clone",
                ref_audio=str(params.get("ref_audio_path") or ""),
                ref_text=str(params.get("ref_text") or ""),
            )
        else:
            raise LocalQwen3TTSError(f"unsupported engine: {engine!r}")
        resp = await self._request_dict(payload)
        if not resp.get("ok"):
            raise LocalQwen3TTSError(str(resp.get("error") or "unknown engine error"))
        errors = resp.get("errors") or []
        if len(errors) != len(texts):
            return [None] * len(texts)
        return list(errors)

    async def aclose(self) -> None:
        if self._proc is not None and self._proc.returncode is None:
            try:
                self._proc.terminate()
            except ProcessLookupError:
                pass
        self._proc = None

    # ------------------------------------------------------------------
    # 与 RuntimeTTSClient 对齐的合成入口
    # ------------------------------------------------------------------
    async def synthesize_voicedesign(
        self, text: str, voice_description: str, output_path, *, stream: bool = False
    ) -> Path:
        out = Path(output_path)
        await self._request(
            {
                "mode": "design",
                "text": text,
                "instruct": voice_description,
                "language": "Chinese",
                "output": str(out),
            }
        )
        return out

    async def synthesize_cosyvoice_zero(
        self, text: str, ref_audio_path, ref_text: str, output_path, *, stream: bool = False
    ) -> Path:
        out = Path(output_path)
        await self._request(
            {
                "mode": "clone",
                "text": text,
                "ref_audio": str(ref_audio_path),
                "ref_text": str(ref_text or ""),
                "language": "Chinese",
                "output": str(out),
            }
        )
        return out


_CLIENT: Optional[LocalQwen3TTSClient] = None


def get_local_qwen3tts_client() -> LocalQwen3TTSClient:
    """进程级单例（模型常驻，避免每条语料重复加载权重）。"""
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = LocalQwen3TTSClient()
    return _CLIENT
