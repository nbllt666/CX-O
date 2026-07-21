"""
Orpheus TTS FastAPI Bridge
=========================
将 vLLM 生成的 SNAC tokens 解码为 24kHz 音频，提供 OpenAI 兼容的 TTS API。

架构:
    客户端 → FastAPI Bridge (:5060) → vLLM (:8000) → SNAC 解码 → WAV 音频

核心流程:
    1. 接收 /v1/audio/speech 请求（OpenAI 兼容格式）
    2. 使用 tokenizer 格式化 prompt（添加 start/end 特殊 token）
    3. 调用 vLLM /v1/completions 生成 SNAC tokens（skip_special_tokens=False）
    4. 解析 <custom_token_N> 并通过 SNAC 解码器转为 24kHz PCM
    5. 返回完整 WAV 或流式 WAV（首包延迟 < 300ms）

环境变量:
    VLLM_BASE_URL          vLLM 后端地址（默认 http://127.0.0.1:8000）
    VLLM_MODEL             模型名称（默认 /workspace/models）
    SNAC_MODEL_PATH        SNAC 解码器本地路径（默认 /workspace/snac）
    SNAC_DEVICE            SNAC 解码器设备（cpu/cuda，默认 cpu）
    ORPHEUS_TEMPERATURE    采样温度（默认 0.6）
    ORPHEUS_TOP_P          Top-P 采样（默认 0.8）
    ORPHEUS_MAX_TOKENS     最大生成 token 数（默认 1200）
    ORPHEUS_REP_PENALTY    重复惩罚（默认 1.3）
    TOKENIZER_PATH         tokenizer 路径（默认 /workspace/models）
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import re
import struct
import time
import wave
from typing import Any, AsyncGenerator, Optional

import httpx
import numpy as np
from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

# ============================================================
# 配置常量
# ============================================================

# vLLM 后端地址与模型
VLLM_BASE_URL: str = os.environ.get("VLLM_BASE_URL", "http://127.0.0.1:8000")
VLLM_MODEL: str = os.environ.get("VLLM_MODEL", "/workspace/models")

# Tokenizer 路径（与模型同目录）
TOKENIZER_PATH: str = os.environ.get("TOKENIZER_PATH", "/workspace/models")

# 音频参数（Orpheus 固定输出 24kHz 单声道）
SAMPLE_RATE: int = 24000
AUDIO_CHANNELS: int = 1
AUDIO_SAMPLE_WIDTH: int = 2  # 16-bit PCM = 2 bytes

# SNAC 解码参数
# Orpheus custom tokens 0-9 保留，10+ 映射到 SNAC 码
SNAC_TOKEN_OFFSET: int = 10
# SNAC 24kHz: 7 codebooks，每帧 7 个码，解码为 480 样本（20ms）
SNAC_CODES_PER_FRAME: int = 7
# 流式解码批量大小（帧数），1 帧 = 20ms 音频，激进首包延迟优化（C4 P50<400ms 三轮）
# 原 2 帧 = 40ms，降到 1 帧 = 20ms 可节省 ~30-50ms 首包延迟（vLLM 生成 7 个 tokens 的时间）
# 权衡：1 帧 batch SNAC 解码开销最大，但首块延迟最低
STREAM_BATCH_FRAMES: int = 1

# 静音过滤配置（解决 Orpheus 中文版生成大量段间静音 tokens 的问题）
# 检测到 PCM 振幅绝对值低于 SILENCE_AMPLITUDE_THRESHOLD 视为静音帧
# 连续静音帧数超过 MAX_CONSECUTIVE_SILENCE_FRAMES 时跳过 yield（不发送给客户端）
# 默认 10 帧 = 200ms，保留自然停顿，过滤 >200ms 的段间长静音
SILENCE_AMPLITUDE_THRESHOLD: int = int(os.environ.get("SILENCE_AMPLITUDE_THRESHOLD", "200"))
MAX_CONSECUTIVE_SILENCE_FRAMES: int = int(os.environ.get("MAX_CONSECUTIVE_SILENCE_FRAMES", "10"))

# Orpheus 生成参数（与官方 orpheus-speech 一致）
ORPHEUS_TEMPERATURE: float = float(os.environ.get("ORPHEUS_TEMPERATURE", "0.6"))
ORPHEUS_TOP_P: float = float(os.environ.get("ORPHEUS_TOP_P", "0.8"))
ORPHEUS_MAX_TOKENS: int = int(os.environ.get("ORPHEUS_MAX_TOKENS", "1200"))
ORPHEUS_REP_PENALTY: float = float(os.environ.get("ORPHEUS_REP_PENALTY", "1.3"))
ORPHEUS_STOP_TOKEN_IDS: list[int] = [128258, 49158]

# Orpheus prompt 格式化特殊 token ID
ORPHEUS_START_TOKEN_ID: int = 128259
ORPHEUS_END_TOKEN_IDS: list[int] = [128009, 128260, 128261, 128257]

# SNAC 解码器设备（cpu 避免 GPU 争抢；cuda 延迟更低）
SNAC_DEVICE: str = os.environ.get("SNAC_DEVICE", "cpu")

# HTTP 超时配置
HTTP_CONNECT_TIMEOUT: float = 10.0
HTTP_READ_TIMEOUT: float = 300.0  # TTS 生成长序列，需较长超时

# Orpheus 可用语音列表
# 英文音色（来自 canopylabs/orpheus-3b-0.1-ft 训练集）
# 中文音色（来自 canopylabs/orpheus-multilingual-research-release 多语言版）
#   - 长乐：女声，温柔自然，适合对话场景
#   - 白芷：女声，清晰明亮，适合播报场景
AVAILABLE_VOICES: list[str] = [
    # 英文音色
    "tara", "leah", "leo", "dan", "mia", "jess", "lily", "zoe",
    "zac", "river", "charlotte", "james", "matthew",
    # 中文音色（官方多语言版支持）
    "长乐", "白芷",
]

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("orpheus_tts")


# ============================================================
# Orpheus Prompt 格式化器 — 使用 tokenizer 添加特殊 token
# ============================================================

class OrpheusPromptFormatter:
    """
    Orpheus TTS prompt 格式化器。

    3B 模型需要特定的 token 序列才能生成 SNAC 音频 token：
    - Start Token: ID 128259（前置）
    - End Tokens: IDs [128009, 128260, 128261, 128257]（后置）

    格式化流程（与官方 orpheus-speech 一致）：
    1. 拼接 voice 前缀: "{voice}: {text}"
    2. 使用 tokenizer 编码为 token IDs
    3. 前置 128259，后置 [128009, 128260, 128261, 128257]
    4. 解码回字符串，作为 completions API 的 prompt
    """

    def __init__(self, tokenizer_path: str) -> None:
        from transformers import AutoTokenizer
        import torch

        self._torch = torch
        logger.info(f"正在加载 tokenizer: {tokenizer_path}")
        self._tokenizer = AutoTokenizer.from_pretrained(tokenizer_path)
        logger.info(f"Tokenizer 加载完成，词表大小: {self._tokenizer.vocab_size}")

    def format_prompt(self, text: str, voice: str = "tara") -> str:
        """
        格式化 Orpheus TTS prompt。

        参数:
            text: 要合成的文本（可包含情感标签如 <laugh>）
            voice: 语音名称

        返回:
            格式化后的 prompt 字符串，包含特殊 token
        """
        # 拼接 voice 前缀
        adapted_prompt = f"{voice}: {text}"

        # 使用 tokenizer 编码
        prompt_tokens = self._tokenizer(adapted_prompt, return_tensors="pt")

        # 构造特殊 token 张量
        start_token = self._torch.tensor([[ORPHEUS_START_TOKEN_ID]], dtype=self._torch.int64)
        end_tokens = self._torch.tensor([ORPHEUS_END_TOKEN_IDS], dtype=self._torch.int64)

        # 拼接: [start] + [prompt_tokens] + [end_tokens]
        all_input_ids = self._torch.cat(
            [start_token, prompt_tokens.input_ids, end_tokens], dim=1
        )

        # 解码回字符串
        prompt_string = self._tokenizer.decode(all_input_ids[0])
        return prompt_string


# ============================================================
# SNAC Token 解析器 — 从 vLLM 输出文本中提取 <custom_token_N>
# ============================================================

class SnacTokenParser:
    """
    流式解析 vLLM 输出中的 Orpheus custom tokens。

    vLLM 在 skip_special_tokens=False 时输出形如 <custom_token_42> 的特殊 token，
    本解析器从文本流中提取这些 token ID，供 SNAC 解码器使用。

    关键: Orpheus 的 SNAC 码映射公式为:
        code = token_id - 10 - ((index % 7) * 4096)
    其中 index 是 token 在序列中的位置（0-based）。
    不同位置的 token 映射到不同的 SNAC codebook 层级。

    支持流式输入：可跨 SSE chunk 缓冲不完整的 token 文本。
    """

    def __init__(self) -> None:
        self._buffer: str = ""
        self._pattern: re.Pattern[str] = re.compile(r"<custom_token_(\d+)>")
        self._index: int = 0  # 全局 token 计数器

    def feed(self, text: str) -> list[int]:
        """
        输入一段文本，返回其中包含的 SNAC 码列表。

        每个匹配的 <custom_token_N> 会根据其在序列中的位置应用偏移公式:
            code = N - 10 - ((index % 7) * 4096)

        不完整的 token（如被 SSE chunk 截断的 <custom_tok）会保留在内部缓冲区，
        等待后续 feed 补全后一并返回。
        """
        self._buffer += text
        codes: list[int] = []

        # 逐个匹配完整的 <custom_token_N> 模式
        pos = 0
        for match in self._pattern.finditer(self._buffer):
            token_id = int(match.group(1))
            # 应用 Orpheus SNAC 码映射公式
            code = token_id - SNAC_TOKEN_OFFSET - ((self._index % SNAC_CODES_PER_FRAME) * 4096)
            if 0 <= code <= 4096:
                codes.append(code)
            self._index += 1
            pos = match.end()

        # 保留最后一个匹配之后的内容（可能是不完整 token 的前缀）
        remaining = self._buffer[pos:]
        # 检查末尾是否有 '<' 开头的潜在不完整 token
        last_lt = remaining.rfind("<")
        if last_lt > 0:
            # 丢弃 '<' 之前的无关文本，保留可能的半截 token
            self._buffer = remaining[last_lt:]
        else:
            self._buffer = ""

        return codes


# ============================================================
# SNAC 解码器 — 将 SNAC 码转为 24kHz 音频
# ============================================================

class SnacDecoder:
    """
    SNAC 音频解码器，将 Orpheus 生成的 custom tokens 解码为 24kHz 音频波形。

    SNAC（Multi-Scale Neural Audio Codec）使用 7 层量化码本，
    每帧 7 个码 → 480 个音频样本（20ms @ 24kHz）。
    """

    def __init__(self, device: str = "cpu") -> None:
        self._device: str = device
        self._model: Any = None
        self._torch: Any = None

    def load(self) -> None:
        """加载 SNAC 模型（优先从本地路径，否则从 HuggingFace 下载）"""
        import torch
        from snac import SNAC

        self._torch = torch
        # 优先从本地路径加载（容器内 /workspace/snac 或宿主机挂载）
        local_snac_path = os.environ.get("SNAC_MODEL_PATH", "/workspace/snac")
        logger.info(f"正在加载 SNAC 解码器（设备: {self._device}）...")
        try:
            if os.path.isdir(local_snac_path) and os.listdir(local_snac_path):
                logger.info(f"从本地路径加载 SNAC: {local_snac_path}")
                self._model = SNAC.from_pretrained(local_snac_path).to(self._device)
            else:
                logger.info("从 HuggingFace 下载 SNAC: hubertsiuzdak/snac_24khz")
                self._model = SNAC.from_pretrained("hubertsiuzdak/snac_24khz").to(self._device)
        except Exception as e:
            logger.error(f"SNAC 解码器加载失败: {e}")
            logger.warning("服务将以降级模式运行（无 SNAC 解码），TTS 请求将返回 503")
            return
        self._model.eval()
        logger.info("SNAC 解码器加载完成")

    @property
    def is_ready(self) -> bool:
        return self._model is not None

    def decode_tokens(self, codes: list[int]) -> np.ndarray:
        """
        将 Orpheus SNAC 码列表解码为音频波形。

        参数:
            codes: 已应用偏移公式的 SNAC 码列表（范围 0-4096）

        返回:
            float32 numpy 数组，范围 [-1, 1]，采样率 24000Hz

        说明:
            - 每 7 个码为一帧
            - SNAC 24kHz 使用 3 层码本，需将 7 个码重组为 3 个张量:
              - codes_0: 位置 0（每帧 1 个码，粗粒度）
              - codes_1: 位置 1, 4（每帧 2 个码，中粒度）
              - codes_2: 位置 2, 3, 5, 6（每帧 4 个码，细粒度）
        """
        if not codes or self._model is None:
            return np.array([], dtype=np.float32)

        n_frames = len(codes) // SNAC_CODES_PER_FRAME
        if n_frames == 0:
            return np.array([], dtype=np.float32)

        # 截断到完整帧
        codes = codes[: n_frames * SNAC_CODES_PER_FRAME]

        torch = self._torch

        # 重组为 (n_frames, 7) 矩阵
        codes_tensor = torch.tensor(codes, dtype=torch.int32, device=self._device)
        codes_tensor = codes_tensor.reshape(n_frames, SNAC_CODES_PER_FRAME)

        # 按位置分离为 3 层码本
        # codes_0: 位置 0 → shape (1, n_frames)
        codes_0 = codes_tensor[:, 0].unsqueeze(0)
        # codes_1: 位置 1, 4 → 交错排列 → shape (1, 2*n_frames)
        codes_1 = torch.stack((codes_tensor[:, 1], codes_tensor[:, 4])).t().flatten().unsqueeze(0)
        # codes_2: 位置 2, 3, 5, 6 → 交错排列 → shape (1, 4*n_frames)
        codes_2 = (
            torch.stack((codes_tensor[:, 2], codes_tensor[:, 3], codes_tensor[:, 5], codes_tensor[:, 6]))
            .t()
            .flatten()
            .unsqueeze(0)
        )

        with torch.no_grad():
            audio = self._model.decode([codes_0, codes_1, codes_2])

        # (1, 1, samples) → (samples,)
        audio_np = audio.squeeze().cpu().numpy().astype(np.float32)
        return audio_np


# ============================================================
# WAV 编码工具
# ============================================================

def pcm_to_wav(pcm: np.ndarray, sample_rate: int = SAMPLE_RATE) -> bytes:
    """
    将 float32 PCM 波形编码为完整 WAV 字节（16-bit, mono）。

    参数:
        pcm: float32 数组，范围 [-1, 1]
        sample_rate: 采样率（默认 24000）

    返回:
        完整 WAV 文件字节（含 RIFF 头部）
    """
    if pcm.size == 0:
        pcm = np.zeros(1, dtype=np.float32)

    # float32 → int16
    pcm_int16 = (pcm * 32767.0).clip(-32768, 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(AUDIO_CHANNELS)
        wf.setsampwidth(AUDIO_SAMPLE_WIDTH)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_int16.tobytes())
    return buf.getvalue()


def wav_header_bytes(
    sample_rate: int = SAMPLE_RATE,
    num_channels: int = AUDIO_CHANNELS,
    sample_width: int = AUDIO_SAMPLE_WIDTH,
    data_size: int = 0,
) -> bytes:
    """
    生成 WAV 文件头部（44 字节），用于流式传输。

    data_size=0 表示未知长度（流式 WAV），客户端应持续读取直到连接关闭。
    """
    byte_rate: int = sample_rate * num_channels * sample_width
    block_align: int = num_channels * sample_width
    header = bytearray(44)
    header[0:4] = b"RIFF"
    header[4:8] = struct.pack("<I", 36 + data_size)
    header[8:12] = b"WAVE"
    header[12:16] = b"fmt "
    header[16:20] = struct.pack("<I", 16)  # fmt chunk 大小
    header[20:22] = struct.pack("<H", 1)   # PCM 格式
    header[22:24] = struct.pack("<H", num_channels)
    header[24:28] = struct.pack("<I", sample_rate)
    header[28:32] = struct.pack("<I", byte_rate)
    header[32:34] = struct.pack("<H", block_align)
    header[34:36] = struct.pack("<H", sample_width * 8)
    header[36:40] = b"data"
    header[40:44] = struct.pack("<I", data_size)
    return bytes(header)


def pcm_to_int16_bytes(pcm: np.ndarray) -> bytes:
    """将 float32 PCM 转为 int16 原始字节（无 WAV 头部，用于流式传输的数据块）"""
    if pcm.size == 0:
        return b""
    pcm_int16 = (pcm * 32767.0).clip(-32768, 32767).astype(np.int16)
    return pcm_int16.tobytes()


def is_silence_pcm(pcm_bytes: bytes, threshold: int = SILENCE_AMPLITUDE_THRESHOLD) -> bool:
    """检测 PCM bytes（16-bit signed LE）是否为静音帧。

    判据：所有样本的绝对值均低于 threshold（默认 200，约 0.6% 最大振幅）。

    用于过滤 Orpheus 中文版生成的段间长静音，避免播放时出现明显间隔。
    单帧 20ms，连续 10 帧 = 200ms 自然停顿已足够，超过则视为模型异常静音。
    """
    if len(pcm_bytes) < 4:
        return True
    # 用 numpy 批量计算，比 array.array + all() 快 5-10 倍
    arr = np.frombuffer(pcm_bytes, dtype=np.int16)
    if arr.size == 0:
        return True
    return bool(np.all(np.abs(arr) < threshold))


# ============================================================
# vLLM 客户端 — 调用 OpenAI 兼容 /v1/completions
# ============================================================

class VLLMClient:
    """
    异步 vLLM 客户端，调用 OpenAI 兼容的 /v1/completions 端点。

    关键: 必须设置 skip_special_tokens=False，否则 <custom_token_N> 会被
    vLLM 当作特殊 token 过滤掉，导致无法获取 SNAC 码。

    使用 completions API（非 chat completions），因为 Orpheus prompt 已包含
    特殊 token 格式化，不需要 chat template 处理。
    """

    def __init__(self, base_url: str, model: str) -> None:
        self._base_url: str = base_url.rstrip("/")
        self._model: str = model
        self._client: Optional[httpx.AsyncClient] = None

    async def start(self) -> None:
        """初始化 HTTP 连接池"""
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=HTTP_CONNECT_TIMEOUT,
                read=HTTP_READ_TIMEOUT,
                write=HTTP_CONNECT_TIMEOUT,
                pool=HTTP_CONNECT_TIMEOUT,
            ),
        )
        logger.info(f"vLLM 客户端就绪: {self._base_url}")

    async def close(self) -> None:
        """关闭 HTTP 连接池"""
        if self._client:
            await self._client.aclose()
            self._client = None

    def _build_payload(self, prompt: str, stream: bool) -> dict[str, Any]:
        """构造 vLLM completions 请求体"""
        return {
            "model": self._model,
            "prompt": prompt,
            "max_tokens": ORPHEUS_MAX_TOKENS,
            "temperature": ORPHEUS_TEMPERATURE,
            "top_p": ORPHEUS_TOP_P,
            "repetition_penalty": ORPHEUS_REP_PENALTY,
            "stop_token_ids": ORPHEUS_STOP_TOKEN_IDS,
            "stream": stream,
            # 关键: 保留特殊 token，否则 custom_token 会被过滤
            "skip_special_tokens": False,
        }

    async def complete(self, prompt: str) -> str:
        """
        非流式调用 vLLM，返回完整生成文本。

        用于 stream=false 模式，一次性获取所有 SNAC tokens 后解码。
        """
        if not self._client:
            raise RuntimeError("vLLM 客户端未初始化")

        payload = self._build_payload(prompt, stream=False)
        try:
            response = await self._client.post(
                f"{self._base_url}/v1/completions",
                json=payload,
            )
            response.raise_for_status()
        except httpx.ConnectError as e:
            raise HTTPException(
                status_code=503,
                detail=f"无法连接 vLLM 后端 ({self._base_url}): {e}",
            )
        except httpx.TimeoutException as e:
            raise HTTPException(
                status_code=504,
                detail=f"vLLM 请求超时: {e}",
            )

        result = response.json()
        return result["choices"][0].get("text", "")

    async def stream_complete(self, prompt: str) -> AsyncGenerator[str, None]:
        """
        流式调用 vLLM，逐 token yield 生成文本。

        用于 stream=true 模式，边接收边解码，降低首包延迟。
        vLLM 以 SSE（Server-Sent Events）格式推送，每行以 "data: " 前缀。
        """
        if not self._client:
            raise RuntimeError("vLLM 客户端未初始化")

        payload = self._build_payload(prompt, stream=True)
        try:
            async with self._client.stream(
                "POST",
                f"{self._base_url}/v1/completions",
                json=payload,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    data_str = line[len("data: "):]
                    if data_str.strip() == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    choices = chunk.get("choices", [])
                    if choices:
                        text = choices[0].get("text", "")
                        if text:
                            yield text
        except httpx.ConnectError as e:
            raise HTTPException(
                status_code=503,
                detail=f"无法连接 vLLM 后端 ({self._base_url}): {e}",
            )
        except httpx.TimeoutException as e:
            raise HTTPException(
                status_code=504,
                detail=f"vLLM 流式请求超时: {e}",
            )

    async def health_check(self) -> bool:
        """检查 vLLM 后端是否就绪"""
        if not self._client:
            # 客户端未初始化，尝试重新创建
            await self.start()
        try:
            resp = await self._client.get(
                f"{self._base_url}/health",
                timeout=httpx.Timeout(5.0),
            )
            logger.debug(f"vLLM health check: status={resp.status_code}")
            return resp.status_code == 200
        except Exception as e:
            logger.debug(f"vLLM health check failed: {e}, recreating client")
            # 连接失败时重建客户端，避免连接池缓存失败状态
            await self.start()
            return False


# ============================================================
# Prompt 构造
# ============================================================

def build_orpheus_prompt(text: str, voice: str) -> str:
    """
    构造 Orpheus TTS prompt（使用 tokenizer 格式化）。

    使用 OrpheusPromptFormatter 添加特殊 token（128259 start,
    [128009, 128260, 128261, 128257] end），使模型生成 SNAC 音频 token。

    若 input 已包含 voice 前缀（如 "tara: 你好"），则去除重复前缀。
    """
    text = text.strip()
    voice = voice.strip().lower()

    # 检查是否已包含 voice 前缀，避免重复
    prefix = f"{voice}:"
    if text.lower().startswith(prefix):
        text = text[len(prefix):].strip()

    return prompt_formatter.format_prompt(text, voice)


# ============================================================
# FastAPI 应用
# ============================================================

app = FastAPI(
    title="Orpheus TTS Bridge",
    description="OpenAI 兼容的 Orpheus TTS API，基于 vLLM + SNAC 解码",
    version="1.0.0",
)

# 全局实例
snac_decoder = SnacDecoder(device=SNAC_DEVICE)
vllm_client = VLLMClient(base_url=VLLM_BASE_URL, model=VLLM_MODEL)
prompt_formatter: OrpheusPromptFormatter = None  # type: ignore[assignment]


# ---- 请求/响应模型 ----

class SpeechRequest(BaseModel):
    """OpenAI 兼容的 TTS 请求体"""
    input: str = Field(..., description="要合成的文本，可包含情感标签（如 <laugh>）")
    voice: str = Field("tara", description="语音名称（tara/leah/leo/dan/mia 等）")
    stream: bool = Field(False, description="是否流式返回音频")
    response_format: str = Field("wav", description="音频格式（目前仅支持 wav）")
    speed: float = Field(1.0, description="语速（Orpheus 暂不支持，保留兼容性）")


class HealthResponse(BaseModel):
    """健康检查响应"""
    status: str
    vllm: str
    snac: str
    model: str


# ---- 生命周期事件 ----

@app.on_event("startup")
async def startup() -> None:
    """应用启动: 加载 tokenizer + SNAC 解码器 + 初始化 vLLM 客户端"""
    global prompt_formatter

    logger.info("=" * 60)
    logger.info("  Orpheus TTS Bridge 启动中")
    logger.info(f"  vLLM 后端: {VLLM_BASE_URL}")
    logger.info(f"  模型:      {VLLM_MODEL}")
    logger.info(f"  Tokenizer: {TOKENIZER_PATH}")
    logger.info(f"  SNAC 设备: {SNAC_DEVICE}")
    logger.info(f"  监听端口:  5060")
    logger.info("=" * 60)

    # 初始化 vLLM HTTP 客户端
    await vllm_client.start()

    # 加载 Orpheus prompt 格式化器（需要 tokenizer）
    try:
        prompt_formatter = await asyncio.to_thread(
            OrpheusPromptFormatter, TOKENIZER_PATH
        )
    except Exception as e:
        logger.error(f"Prompt 格式化器加载失败: {e}")
        logger.warning("TTS 请求将无法正常工作")

    # 异步加载 SNAC 解码器（在线程池中执行，避免阻塞事件循环）
    try:
        await asyncio.to_thread(snac_decoder.load)
    except Exception as e:
        logger.error(f"SNAC 解码器加载失败: {e}")
        logger.warning("服务将以降级模式运行（无 SNAC 解码），TTS 请求将返回 503")


@app.on_event("shutdown")
async def shutdown() -> None:
    """应用关闭: 释放资源"""
    logger.info("正在关闭 Orpheus TTS Bridge...")
    await vllm_client.close()
    logger.info("已关闭")


# ---- API 端点 ----

@app.get("/")
async def root() -> dict[str, str]:
    """根路径 — 服务信息"""
    return {
        "service": "Orpheus TTS Bridge",
        "version": "1.0.0",
        "model": VLLM_MODEL,
        "endpoints": "/health, /v1/audio/speech, /v1/models",
    }


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """
    健康检查端点。

    返回 200 表示 vLLM 后端就绪且 SNAC 解码器已加载；
    返回 503 表示服务不可用（vLLM 未就绪或 SNAC 未加载）。
    """
    vllm_ready = await vllm_client.health_check()
    snac_ready = snac_decoder.is_ready

    if not (vllm_ready and snac_ready):
        raise HTTPException(
            status_code=503,
            detail=HealthResponse(
                status="unhealthy",
                vllm="ready" if vllm_ready else "not_ready",
                snac="ready" if snac_ready else "not_ready",
                model=VLLM_MODEL,
            ).model_dump(),
        )

    return HealthResponse(
        status="healthy",
        vllm="ready",
        snac="ready",
        model=VLLM_MODEL,
    )


@app.get("/v1/models")
async def list_models() -> dict[str, Any]:
    """OpenAI 兼容模型列表端点"""
    return {
        "object": "list",
        "data": [
            {
                "id": VLLM_MODEL,
                "object": "model",
                "created": int(time.time()),
                "owned_by": "canopylabs",
            }
        ],
    }


@app.post("/v1/audio/speech")
async def create_speech(req: SpeechRequest) -> Response:
    """
    OpenAI 兼容 TTS 端点 — 文本转语音。

    请求体:
        {"input": "tara: 你好 <laugh> 哈哈 </laugh>", "voice": "tara", "stream": false}

    响应:
        - stream=false: 返回完整 audio/wav（24kHz, 16-bit PCM, mono）
        - stream=true:  返回 chunked audio/wav 流（首包 < 300ms）

    内部流程:
        1. 构造 Orpheus prompt（voice + text）
        2. 调用 vLLM /v1/completions 生成 SNAC tokens
        3. 解析 <custom_token_N> 并通过 SNAC 解码为 24kHz PCM
        4. 编码为 WAV 返回
    """
    # 校验 SNAC 解码器就绪
    if not snac_decoder.is_ready:
        raise HTTPException(
            status_code=503,
            detail="SNAC 解码器未就绪，请等待服务启动完成或检查日志",
        )

    # 校验语音名称
    if req.voice.lower() not in AVAILABLE_VOICES:
        logger.warning(f"未知语音 '{req.voice}'，将原样传递给模型（可能失败）")

    # 构造 prompt
    prompt = build_orpheus_prompt(req.input, req.voice)
    logger.info(
        f"TTS 请求: voice={req.voice}, stream={req.stream}, "
        f"prompt长度={len(prompt)}"
    )

    if req.stream:
        return await _handle_streaming_speech(prompt)
    else:
        return await _handle_sync_speech(prompt)


# ---- 内部处理函数 ----

async def _handle_sync_speech(prompt: str) -> Response:
    """
    非流式 TTS 处理: 一次性生成完整音频。

    流程: vLLM completions → 解析全部 SNAC tokens → 解码 → 完整 WAV
    """
    start_time = time.time()

    # 1. 调用 vLLM 获取完整生成文本
    text = await vllm_client.complete(prompt)
    vllm_time = time.time() - start_time
    logger.info(f"vLLM 生成完成: {len(text)} 字符, 耗时 {vllm_time:.3f}s")

    # 2. 解析 SNAC tokens（parser 已应用偏移公式，返回 SNAC 码）
    parser = SnacTokenParser()
    snac_codes = parser.feed(text)
    logger.info(f"解析到 {len(snac_codes)} 个 SNAC 码（{len(snac_codes) // SNAC_CODES_PER_FRAME} 帧）")

    if not snac_codes:
        raise HTTPException(
            status_code=500,
            detail="vLLM 未生成有效的 SNAC tokens，请检查模型配置",
        )

    # 3. SNAC 解码为音频（在线程池中执行，避免阻塞事件循环）
    pcm = await asyncio.to_thread(snac_decoder.decode_tokens, snac_codes)
    decode_time = time.time() - start_time - vllm_time
    logger.info(
        f"SNAC 解码完成: {len(pcm)} 样本 ({len(pcm) / SAMPLE_RATE:.2f}s 音频), "
        f"耗时 {decode_time:.3f}s"
    )

    # 4. 编码为 WAV
    wav_bytes = pcm_to_wav(pcm)
    total_time = time.time() - start_time
    logger.info(
        f"TTS 完成: {len(wav_bytes)} 字节 WAV, 总耗时 {total_time:.3f}s, "
        f"RTF={total_time / max(len(pcm) / SAMPLE_RATE, 0.001):.2f}"
    )

    return Response(
        content=wav_bytes,
        media_type="audio/wav",
        headers={
            "Content-Disposition": "inline; filename=speech.wav",
            "X-Audio-Duration": f"{len(pcm) / SAMPLE_RATE:.3f}",
            "X-Processing-Time": f"{total_time:.3f}",
        },
    )


async def _handle_streaming_speech(prompt: str) -> StreamingResponse:
    """
    流式 TTS 处理: 边生成边返回音频块。

    流程:
        1. 先发送 WAV 头部（44 字节，data_size=0 表示流式）
        2. 流式接收 vLLM 输出，解析 SNAC tokens
        3. 每累积 STREAM_BATCH_FRAMES 帧（100ms 音频）解码并返回 PCM 块
        4. 流结束后解码剩余 tokens 并返回

    目标: 首包延迟 < 300ms
    """

    async def audio_stream() -> AsyncGenerator[bytes, None]:
        start_time = time.time()
        first_chunk_sent = False

        # 静音过滤状态
        consecutive_silence = 0  # 连续静音帧计数
        total_silence_skipped = 0  # 跳过的静音帧总数（用于日志统计）
        total_frames = 0  # 总帧数（含静音）

        # 1. 发送 WAV 头部（data_size=0 表示流式，长度未知）
        yield wav_header_bytes(data_size=0)

        # 2. 流式接收 vLLM 输出
        parser = SnacTokenParser()
        code_buffer: list[int] = []
        batch_size = STREAM_BATCH_FRAMES * SNAC_CODES_PER_FRAME  # 7 tokens = 20ms
        total_codes = 0

        async for text in vllm_client.stream_complete(prompt):
            codes = parser.feed(text)
            if not codes:
                continue
            code_buffer.extend(codes)
            total_codes += len(codes)

            # 3. 累积足够帧数后解码并返回
            while len(code_buffer) >= batch_size:
                batch = code_buffer[:batch_size]
                code_buffer = code_buffer[batch_size:]

                pcm = await asyncio.to_thread(
                    snac_decoder.decode_tokens, batch
                )
                pcm_bytes = pcm_to_int16_bytes(pcm)
                if not pcm_bytes:
                    continue

                total_frames += 1

                # 静音过滤：检测当前帧是否为静音
                if is_silence_pcm(pcm_bytes):
                    consecutive_silence += 1
                    # 连续静音超过阈值则跳过（保留前 MAX_CONSECUTIVE_SILENCE_FRAMES 帧作为自然停顿）
                    if consecutive_silence > MAX_CONSECUTIVE_SILENCE_FRAMES:
                        total_silence_skipped += 1
                        continue
                else:
                    consecutive_silence = 0

                if not first_chunk_sent:
                    first_chunk_time = time.time() - start_time
                    logger.info(
                        f"首包发送: {first_chunk_time:.3f}s "
                        f"(目标 < 300ms)"
                    )
                    first_chunk_sent = True
                yield pcm_bytes

        # 4. 解码剩余 codes（不足一个 batch 的尾部）
        if code_buffer:
            n_frames = len(code_buffer) // SNAC_CODES_PER_FRAME
            if n_frames > 0:
                batch = code_buffer[: n_frames * SNAC_CODES_PER_FRAME]
                pcm = await asyncio.to_thread(
                    snac_decoder.decode_tokens, batch
                )
                pcm_bytes = pcm_to_int16_bytes(pcm)
                if pcm_bytes:
                    # 尾部也应用静音过滤
                    if not is_silence_pcm(pcm_bytes) or consecutive_silence <= MAX_CONSECUTIVE_SILENCE_FRAMES:
                        if not first_chunk_sent:
                            first_chunk_time = time.time() - start_time
                            logger.info(f"首包发送(尾部): {first_chunk_time:.3f}s")
                            first_chunk_sent = True
                        yield pcm_bytes

        total_time = time.time() - start_time
        audio_duration = total_codes / SNAC_CODES_PER_FRAME * 480 / SAMPLE_RATE
        silence_skipped_ms = total_silence_skipped * 20  # 每帧 20ms
        logger.info(
            f"流式 TTS 完成: {total_codes} SNAC 码, "
            f"总帧数 {total_frames}, 跳过静音 {total_silence_skipped} 帧 ({silence_skipped_ms}ms), "
            f"总耗时 {total_time:.3f}s"
        )

    return StreamingResponse(
        audio_stream(),
        media_type="audio/wav",
        headers={
            "Content-Disposition": "inline; filename=speech.wav",
            "X-Stream": "true",
            "Cache-Control": "no-cache",
        },
    )


# ============================================================
# 入口
# ============================================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "api_server:app",
        host="0.0.0.0",
        port=5060,
        workers=1,
        log_level="info",
    )
