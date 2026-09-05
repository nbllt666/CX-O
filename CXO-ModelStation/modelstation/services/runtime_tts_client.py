"""运行时 TTS HTTP 客户端（数据集生成引擎 cosyvoice3_zero / qwen3_voicedesign 的合成通道）。

协议真源 = CX-O-SERVER/server/qwen3_tts_provider.py 实码（change-id:
extend-modelstation-standalone-melotts-datasets Task 2.1 实施前逐行核对），对齐结论：

- 端点：OpenAI 兼容 ``POST {base_url}/v1/audio/speech``，非流式响应体即完整音频字节
  （response_format="wav" 时为含 44 字节头的完整 WAV 文件；provider 的
  ``_synthesize_once`` 直接消费 ``resp.content``）。
- voicedesign 运行时 payload（provider ``_build_vllm_request``）：
  ``model`` / ``input``（合成文本）/ ``response_format`` / ``stream`` +
  ``task_type="VoiceDesign"``（vLLM 私有参数）+ ``instructions``（音色描述文本，
  经 provider 的 tts_instruction → instructions 字段传递）。
  VoiceDesign 任务不消费参考音频，故本客户端 voicedesign 路径不发 ref 字段。
- cosyvoice 运行时 payload（provider ``_build_cosyvoice_request``）：
  ``model`` / ``input`` / ``response_format`` / ``stream`` / ``speed`` / ``volume`` +
  ``ref_audio``=**data URL 列表**（``"data:audio/wav;base64," + base64(音频字节)``，
  base64 内联而非路径引用）+ ``ref_text``=参考转写字符串列表。
- 流式：provider 流式路径对 wav 输出跳过前 44 字节 WAV 头（``WAV_HEADER_SIZE``），
  后续字节为裸 PCM int16 小端；本客户端流式累积后按配置采样率重包 WAV 容器落盘
  （``_wrap_pcm16_wav`` 与 provider 同构）。批量语料场景以非流式为主。
- 尾部静音裁剪：provider ``_trim_tail_silence`` 同算法同参数
  （阈值=块峰值×10^(-50/20)≈0.00316，最少保留 50ms 采样），保证语料质量一致；
  本客户端对非流式 WAV 帧数据同样应用（provider 仅对流式末块 PCM 应用，
  此处扩展到 WAV 容器内帧数据，算法与阈值不变）。

错误契约：超时 / 连接失败 / HTTP 非 2xx / 空音频 → :class:`RuntimeTTSError`，
异常信息含 base_url 与「检查 vLLM 运行时是否启动」可读指引。

编码规范：路径经 pathlib 解析；阻塞读盘/写盘经 asyncio.to_thread 下放线程池，
不阻塞事件循环；不读取 settings（构造参数由调用方注入，client 保持无配置依赖）。
"""
from __future__ import annotations

import asyncio
import base64
import io
import logging
import struct
import time
import wave
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# 流式 wav 输出时跳过的 WAV 头长度（与 provider WAV_HEADER_SIZE 一致）
WAV_HEADER_SIZE = 44
# voicedesign 运行时的 vLLM 私有 task_type（provider 默认值，不泄漏到数据面协议之外）
TASK_TYPE_VOICEDESIGN = "VoiceDesign"
# 尾部静音裁剪参数（与 provider 常量一致）
SILENCE_RATIO_THRESHOLD = 0.00316  # 相对峰值阈值，-50 dBFS ≈ 10^(-50/20)
TRIM_MIN_RETAIN_S = 0.05           # 至少保留 50ms 语音尾音，保护真实弱语音尾音


class RuntimeTTSError(Exception):
    """运行时 TTS 合成失败（超时/连接失败/HTTP 非 2xx/空响应/参考音频缺失）。

    Attributes:
        base_url: 合成运行时基础地址（错误信息与排查指引均携带）。
        status_code: HTTP 状态码（非 HTTP 类错误为 None）。
    """

    def __init__(self, message: str, *, base_url: str = "",
                 status_code: Optional[int] = None) -> None:
        self.message = message
        self.base_url = base_url
        self.status_code = status_code
        hint = (
            f"排查指引: 检查 vLLM 运行时是否启动（GET {base_url}/health 探活）"
            if base_url else "排查指引: 检查 vLLM 运行时是否启动"
        )
        super().__init__(f"{message} ({hint})")


class RuntimeTTSClient:
    """OpenAI 兼容 ``/v1/audio/speech`` 异步合成客户端（voicedesign / cosyvoice 两运行时）。

    构造参数全部由调用方注入（api 层从 settings.tts_runtime 冻结字段读取后传入），
    本类不读取任何配置单例，保证可测试性（测试经 http_client 注入 MockTransport）。

    Args:
        base_url: 运行时基础地址（如 ``http://127.0.0.1:8091``，去尾斜杠）。
        model: 模型名（payload ``model`` 字段）。
        timeout_seconds: 单次请求超时（秒）。
        sample_rate: 输出采样率（流式 PCM 重包 WAV 与尾部裁剪边界使用）。
        http_client: 可注入的 httpx.AsyncClient（测试用 MockTransport）；缺省自建。
        trim_tail_silence: 是否对合成结果裁剪尾部静音（默认开，与 provider 语料质量对齐）。
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        timeout_seconds: float = 120.0,
        sample_rate: int = 24000,
        *,
        http_client: Optional[httpx.AsyncClient] = None,
        trim_tail_silence: bool = True,
    ) -> None:
        if not base_url:
            raise ValueError("base_url must not be empty")
        if not model:
            raise ValueError("model must not be empty")
        self._base_url = str(base_url).rstrip("/")
        self._model = str(model)
        self._timeout = float(timeout_seconds)
        self._sample_rate = int(sample_rate)
        self._client = http_client
        self._owns_client = http_client is None
        self._trim = bool(trim_tail_silence)

    # ------------------------------------------------------------------
    # 公开合成入口
    # ------------------------------------------------------------------

    async def synthesize_voicedesign(
        self,
        text: str,
        voice_description: str,
        output_path,
        *,
        stream: bool = False,
    ) -> Path:
        """voicedesign 运行时合成（声音设计）：音色描述文本 → WAV 落盘。

        Args:
            text: 合成文本。
            voice_description: 音色描述（自然语言，经 payload ``instructions`` 传递）。
            output_path: WAV 输出路径（父目录不存在时自动创建）。
            stream: 是否走流式路径（批量语料默认非流式）。

        Returns:
            落盘后的输出路径。

        Raises:
            RuntimeTTSError: 超时/连接失败/HTTP 非 2xx/空音频。
        """
        if not text or not str(text).strip():
            raise ValueError("text must not be empty")
        if not voice_description or not str(voice_description).strip():
            raise ValueError("voice_description must not be empty")
        body = {
            "model": self._model,
            "input": str(text),
            "response_format": "wav",
            "stream": bool(stream),
            # vLLM 私有参数（协议真源：provider _build_vllm_request）
            "task_type": TASK_TYPE_VOICEDESIGN,
            "instructions": str(voice_description),
        }
        return await self._synthesize(body, output_path, stream=stream)

    async def synthesize_cosyvoice_zero(
        self,
        text: str,
        ref_audio_path,
        ref_text: str,
        output_path,
        *,
        stream: bool = False,
    ) -> Path:
        """cosyvoice 运行时零样本克隆合成：参考音频 + 文本 → WAV 落盘。

        参考音频以 base64 data URL 内联传递（协议真源：provider
        ``_build_cosyvoice_request`` 的 ``ref_audio`` 为 ``data:audio/wav;base64,<b64>``
        列表，非路径引用）。调用方（dataset_builder）负责白名单校验，
        本方法仅做存在性防御校验。

        Args:
            text: 合成文本。
            ref_audio_path: 参考音频文件路径（白名单内，调用方已校验）。
            ref_text: 参考音频转写文本（可空串，payload ``ref_text`` 列表）。
            output_path: WAV 输出路径。
            stream: 是否走流式路径。

        Returns:
            落盘后的输出路径。

        Raises:
            RuntimeTTSError: 参考音频缺失 / 超时 / 连接失败 / HTTP 非 2xx / 空音频。
        """
        if not text or not str(text).strip():
            raise ValueError("text must not be empty")
        ref = Path(ref_audio_path)
        if not ref.is_file():
            raise RuntimeTTSError(f"参考音频不存在: {ref_audio_path}")
        # 阻塞读盘下放线程池（参考音频可达数十 MB，避免阻塞事件循环）
        ref_bytes = await asyncio.to_thread(ref.read_bytes)
        ref_b64 = base64.b64encode(ref_bytes).decode("ascii")
        body = {
            "model": self._model,
            "input": str(text),
            "response_format": "wav",
            "stream": bool(stream),
            # provider 对 cosyvoice 请求恒带 speed/volume（默认 1.0）
            "speed": 1.0,
            "volume": 1.0,
            # base64 data URL 内联（前缀与 provider 实码逐字一致）
            "ref_audio": [f"data:audio/wav;base64,{ref_b64}"],
            "ref_text": [str(ref_text or "")],
        }
        return await self._synthesize(body, output_path, stream=stream)

    async def aclose(self) -> None:
        """关闭自建 HTTP 客户端（注入客户端交由调用方管理，不代关）。"""
        if self._owns_client and self._client is not None:
            try:
                await self._client.aclose()
            finally:
                self._client = None

    # ------------------------------------------------------------------
    # 内部合成主流程
    # ------------------------------------------------------------------

    def _get_client(self) -> httpx.AsyncClient:
        """获取底层 HTTP 客户端（注入优先，缺省惰性自建）。"""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
            self._owns_client = True
        return self._client

    async def _synthesize(self, body: dict, output_path, *, stream: bool) -> Path:
        """请求运行时 → 音频字节 → （裁剪）→ 落盘；错误统一映射 RuntimeTTSError。"""
        out = Path(output_path)
        client = self._get_client()
        t0 = time.monotonic()
        try:
            if stream:
                audio = await self._stream_audio(client, body)
            else:
                resp = await client.post(
                    f"{self._base_url}/v1/audio/speech", json=body, timeout=self._timeout
                )
                resp.raise_for_status()
                audio = resp.content
        except asyncio.CancelledError:
            raise
        except httpx.TimeoutException as exc:
            self._log_error("synthesize", f"运行时合成超时: {exc}", t0)
            raise RuntimeTTSError(f"运行时合成超时: {exc}", base_url=self._base_url) from exc
        except httpx.ConnectError as exc:
            self._log_error("synthesize", f"运行时不可达: {exc}", t0)
            raise RuntimeTTSError(f"运行时不可达: {exc}", base_url=self._base_url) from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response is not None else None
            self._log_error("synthesize", f"运行时 HTTP 错误: {status}", t0)
            raise RuntimeTTSError(
                f"运行时 HTTP 错误 (HTTP {status}): {exc}",
                base_url=self._base_url,
                status_code=status,
            ) from exc
        except httpx.HTTPError as exc:
            self._log_error("synthesize", f"运行时请求失败: {exc}", t0)
            raise RuntimeTTSError(f"运行时请求失败: {exc}", base_url=self._base_url) from exc

        if not audio:
            self._log_error("synthesize", "运行时返回空音频", t0)
            raise RuntimeTTSError("运行时返回空音频", base_url=self._base_url)

        if self._trim:
            audio = await asyncio.to_thread(
                trim_wav_tail_silence, audio, self._sample_rate
            )

        # 写盘下放线程池；父目录由 builder 保证，此处兜底创建
        await asyncio.to_thread(self._write_output, out, audio)
        elapsed = (time.monotonic() - t0) * 1000
        logger.info(
            "运行时合成成功: base_url=%s model=%s bytes=%d elapsed=%.1fms stream=%s",
            self._base_url, self._model, len(audio), elapsed, stream,
        )
        return out

    @staticmethod
    def _write_output(out: Path, audio: bytes) -> None:
        """落盘（父目录兜底创建）。"""
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(audio)

    async def _stream_audio(self, client: httpx.AsyncClient, body: dict) -> bytes:
        """流式合成：对齐 provider 流式处理——wav 输出跳过前 44 字节 WAV 头，
        累积裸 PCM 后按配置采样率重包 WAV 容器。"""
        skip = WAV_HEADER_SIZE if body.get("response_format") == "wav" else 0
        consumed_header = 0
        chunks: list[bytes] = []
        async with client.stream(
            "POST", f"{self._base_url}/v1/audio/speech", json=body, timeout=self._timeout
        ) as resp:
            resp.raise_for_status()
            async for raw in resp.aiter_bytes():
                if consumed_header < skip:
                    cut = min(skip - consumed_header, len(raw))
                    consumed_header += cut
                    raw = raw[cut:]
                    if not raw:
                        continue
                chunks.append(raw)
        pcm = b"".join(chunks)
        if not pcm:
            return b""
        return _wrap_pcm16_wav(pcm, self._sample_rate, 1)

    @staticmethod
    def _log_error(op: str, msg: str, t0: float) -> None:
        """统一错误日志（terminal 带 timestamp/level/elapsed）。"""
        elapsed = (time.monotonic() - t0) * 1000
        logger.error("[运行时TTS] %s: %s (elapsed=%.1fms)", op, msg, elapsed)


# ---------------------------------------------------------------------------
# 音频处理工具（与 provider 实现同构）
# ---------------------------------------------------------------------------


def trim_wav_tail_silence(wav_bytes: bytes, sample_rate: int) -> bytes:
    """裁剪 WAV 音频尾部静音（与 provider ``_trim_tail_silence`` 同算法同参数）。

    阈值=块峰值×0.00316（-50 dBFS），最少保留 50ms；仅在尾部实际有可裁内容时
    重写容器，否则原样返回（避免无损重编码引入字节漂移）。WAV 解析失败时
    原样返回（不因裁剪失败丢语料）。

    Args:
        wav_bytes: 完整 WAV 文件字节。
        sample_rate: 采样率（最小保留时长换算用；解析头失败时亦作为回退）。

    Returns:
        裁剪后的 WAV 字节（无尾部静音可裁时返回原字节）。
    """
    if not wav_bytes:
        return wav_bytes
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            n_channels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            framerate = wf.getframerate()
            frames = wf.readframes(wf.getnframes())
    except Exception:  # noqa: BLE001 - 非 WAV/损坏文件不裁剪，原样保留
        return wav_bytes

    rate = framerate or sample_rate
    trimmed = _trim_pcm_tail_silence(
        frames, rate, channels=max(1, n_channels),
        silence_ratio=SILENCE_RATIO_THRESHOLD, min_retain_s=TRIM_MIN_RETAIN_S,
    )
    if len(trimmed) == len(frames):
        return wav_bytes
    buf = io.BytesIO()
    with wave.open(buf, "wb") as out:
        out.setnchannels(n_channels)
        out.setsampwidth(sampwidth)
        out.setframerate(framerate)
        out.writeframes(trimmed)
    return buf.getvalue()


def _trim_pcm_tail_silence(
    pcm: bytes,
    sample_rate: int,
    *,
    channels: int = 1,
    silence_ratio: float = SILENCE_RATIO_THRESHOLD,
    min_retain_s: float = TRIM_MIN_RETAIN_S,
) -> bytes:
    """裁剪 PCM（16-bit 小端）尾部静音（provider ``_trim_tail_silence`` 同构实现）。

    - 奇数字节输入：尾字节截断（仅消费前 n*2 字节）；
    - 全静音（峰值==0）：原样返回；
    - 自尾部回溯最多 min_retain_s×sample_rate 个样本，命中首个超阈值样本后
      在其后截断；整段回溯区间全静音则退到最小保留边界（多声道按整帧对齐）。
    """
    if not pcm:
        return pcm
    step = 2  # int16 2 字节
    n = len(pcm) // step
    if n == 0:
        return pcm

    samples = struct.unpack(f"<{n}h", pcm[: n * step])
    peak = max(map(abs, samples))
    if peak == 0:
        return pcm  # 全静音，原样返回

    thr = peak * silence_ratio
    min_retain = max(int(sample_rate * min_retain_s) * max(1, channels), channels)
    stop = max(n - min_retain, 0)
    keep = n
    for i in range(n - 1, stop - 1, -1):
        if abs(samples[i]) > thr:
            keep = i + 1
            break
    else:
        keep = stop  # 回溯区间全为尾部静音，退到最小保留边界
    # 多声道按整帧对齐（避免截在帧中间造成声道错位）
    ch = max(1, channels)
    keep = (keep // ch) * ch
    return pcm[: keep * step]


def _wrap_pcm16_wav(pcm: bytes, sample_rate: int, channels: int = 1) -> bytes:
    """将裸 16-bit PCM 包裹为合法 WAV 容器（provider ``_wrap_pcm16_wav`` 同构）。"""
    n_channels = max(1, int(channels))
    rate = max(1, int(sample_rate))
    block_align = n_channels * 2
    byte_rate = rate * block_align
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + len(pcm), b"WAVE",
        b"fmt ", 16, 1, n_channels,
        rate, byte_rate, block_align, 16,
        b"data", len(pcm),
    )
    return header + pcm
