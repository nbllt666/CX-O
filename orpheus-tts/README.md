# Orpheus TTS vLLM 独立服务

为 CX-O 全双工实时语音模式提供独立的 Orpheus TTS 推理服务，基于 vLLM + SNAC 解码器，支持流式音频输出（首包延迟 < 300ms）。

## 架构

```
客户端 → FastAPI Bridge (:5060) → vLLM (:8000) → SNAC 解码 → 24kHz WAV
         │                        │
         │ OpenAI 兼容 TTS API     │ Llama-3B 生成 SNAC tokens
         │ /v1/audio/speech       │ FlashInfer 注意力后端
         │ /health                │ GPU 1（独立显卡）
         │                        │
         └── SNAC 解码器           └── canopylabs/orpheus-multilingual-research-release
             (cpu/cuda)
```

| 服务 | 端口 | 说明 |
|------|------|------|
| `orpheus-tts` (FastAPI Bridge) | 5060 | 对外暴露的 OpenAI 兼容 TTS API |
| `orpheus-vllm` (vLLM 后端) | 8000 | 容器内部，加载 Orpheus 3B 模型 |

### GPU 分配

| GPU | 用途 | 显存占用 |
|-----|------|----------|
| GPU 0 | LLM 推理（vLLM/TRT-LLM） | ~18GB |
| GPU 1 | Orpheus TTS（3B 模型 + vLLM） | ~8-10GB |

> 双 RTX 3080 20GB 环境下，Orpheus 3B 独占 GPU 1，与 LLM 不争抢显存。

## 前置准备

### 1. 下载模型

```bash
# 方式一: HuggingFace CLI（推荐）
pip install huggingface-hub
huggingface-cli download canopylabs/orpheus-multilingual-research-release

# 方式二: Docker 启动时自动下载（首次启动较慢，约 5-10 分钟）
# vLLM 会自动从 HuggingFace 下载模型到 HF_HOME 缓存目录
```

### 2. 配置环境变量

```bash
# 复制环境变量模板
cp .env.example .env

# 按需修改 .env 文件
# 关键配置:
#   ORPHEUS_GPU_ID=1          # 物理 GPU ID（默认第二张卡）
#   ORPHEUS_CUDA_VISIBLE=0    # 容器内 CUDA 设备编号
#   ORPHEUS_TTS_PORT=5060     # 对外端口
#   SNAC_DEVICE=cpu           # SNAC 解码设备（cpu 避免 GPU 争抢）
```

### 3. 环境变量说明

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `VLLM_ATTENTION_BACKEND` | `FLASHINFER` | vLLM 注意力后端（FlashInfer 高性能） |
| `ORPHEUS_GPU_ID` | `1` | 物理 GPU ID（NVIDIA device_ids） |
| `ORPHEUS_CUDA_VISIBLE` | `0` | 容器内 CUDA_VISIBLE_DEVICES |
| `ORPHEUS_MODEL` | `canopylabs/orpheus-multilingual-research-release` | 模型名称 |
| `ORPHEUS_TTS_PORT` | `5060` | FastAPI Bridge 对外端口 |
| `ORPHEUS_VLLM_PORT` | `8000` | vLLM 内部端口 |
| `ORPHEUS_MAX_MODEL_LEN` | `4096` | vLLM 最大上下文长度 |
| `ORPHEUS_GPU_MEM_UTIL` | `0.9` | vLLM GPU 显存利用率 |
| `ORPHEUS_MAX_NUM_SEQS` | `8` | vLLM 最大并发序列数 |
| `SNAC_DEVICE` | `cpu` | SNAC 解码器设备（cpu/cuda） |
| `ORPHEUS_TEMPERATURE` | `0.6` | 采样温度（Orpheus 推荐值） |
| `ORPHEUS_TOP_P` | `0.95` | Top-P 采样 |
| `ORPHEUS_MAX_TOKENS` | `8192` | 最大生成 token 数 |

## 启动服务

```bash
# 进入部署目录
cd orpheus-tts

# 启动 Orpheus TTS 服务（自动启动 vLLM 后端 + FastAPI Bridge）
docker compose up -d orpheus-tts

# 查看日志
docker compose logs -f orpheus-tts
docker compose logs -f orpheus-vllm

# 停止服务
docker compose down
```

> 首次启动时 vLLM 需下载模型（约 5-10 分钟），后续启动利用缓存约 30 秒。

## 健康检查

```bash
# 检查服务是否就绪（vLLM + SNAC 均就绪时返回 200）
curl http://localhost:5060/health

# 预期响应:
# {"status":"healthy","vllm":"ready","snac":"ready","model":"canopylabs/orpheus-multilingual-research-release"}
```

## API 调用

### POST /v1/audio/speech

OpenAI 兼容的 TTS 端点。

**请求体:**

```json
{
  "input": "tara: 你好 <laugh> 哈哈 </laugh>",
  "voice": "tara",
  "stream": false
}
```

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `input` | string | (必填) | 要合成的文本，可包含情感标签 |
| `voice` | string | `tara` | 语音名称 |
| `stream` | bool | `false` | 是否流式返回 |
| `response_format` | string | `wav` | 音频格式（目前仅支持 wav） |
| `speed` | float | `1.0` | 语速（保留兼容性，Orpheus 暂不支持） |

**可用语音:** `tara`, `leah`, `leo`, `dan`, `mia`, `jess`, `lily`, `zoe`, `zac`, `river`, `charlotte`, `james`, `matthew`

**情感标签:** `<laugh>`, `</laugh>`, `<giggle>`, `<sigh>`, `<cough>`, `<yawn>`, `<gasp>`, `<groan>`

### curl 示例

```bash
# 非流式 — 返回完整 WAV
curl -X POST http://localhost:5060/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"input": "tara: 你好世界", "voice": "tara", "stream": false}' \
  --output speech.wav

# 流式 — 返回 chunked WAV 流（首包 < 300ms）
curl -X POST http://localhost:5060/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"input": "tara: 这是一段流式语音合成测试。", "voice": "tara", "stream": true}' \
  --output stream.wav

# 带情感标签
curl -X POST http://localhost:5060/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"input": "tara: 哈哈，这太有趣了 <giggle> 嘻嘻 </giggle>", "voice": "tara"}' \
  --output laugh.wav
```

### Python httpx 示例

```python
import httpx

# 非流式
async def synthesize(text: str, voice: str = "tara") -> bytes:
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:5060/v1/audio/speech",
            json={"input": f"{voice}: {text}", "voice": voice, "stream": False},
            timeout=120.0,
        )
        response.raise_for_status()
        return response.content  # WAV bytes

# 流式（边接收边播放）
async def synthesize_stream(text: str, voice: str = "tara"):
    async with httpx.AsyncClient() as client:
        async with client.stream(
            "POST",
            "http://localhost:5060/v1/audio/speech",
            json={"input": f"{voice}: {text}", "voice": voice, "stream": True},
            timeout=300.0,
        ) as response:
            # 首个 chunk 包含 44 字节 WAV 头部
            # 后续 chunk 为 raw 16-bit PCM 数据
            async for chunk in response.aiter_bytes():
                # 将 chunk 送入音频播放器
                yield chunk
```

## 性能调优

### 降低首包延迟（目标 < 300ms）

1. **KV-Cache + Prefix Caching**
   - vLLM 已启用 `--enable-prefix-caching`，voice 前缀（如 `tara: `）会被缓存
   - 重复使用同一 voice 时，首 token 生成延迟可降低 30-50%

2. **流式输入处理**
   - 将 LLM 输出流式送入 TTS（逐句/逐词），而非等待完整文本
   - 配合 CX-O-SERVER 的 `split_text_streaming`（字数阈值 4），首包可降至 25-50ms

3. **SNAC 解码设备**
   - `SNAC_DEVICE=cpu`: 不争抢 GPU，解码延迟约 5ms/100ms 音频（可接受）
   - `SNAC_DEVICE=cuda`: 解码延迟约 1ms/100ms 音频（更低，但占用 GPU）

4. **vLLM 参数调优**
   ```env
   # 减少 max-num-seqs 可降低显存碎片，提升单请求吞吐
   ORPHEUS_MAX_NUM_SEQS=4
   # 降低 gpu-memory-utilization 为其他进程预留显存
   ORPHEUS_GPU_MEM_UTIL=0.85
   ```

### 实时率（RTF）

| 配置 | RTF | 说明 |
|------|-----|------|
| GPU 1 (3080) + CPU SNAC | ~0.1-0.15 | 生成速度约为音频时长的 7-10 倍 |
| GPU 1 (3080) + CUDA SNAC | ~0.08-0.12 | SNAC 解码加速，整体略快 |

> RTF < 1.0 表示实时合成（生成速度快于播放速度），满足全双工对话需求。

## 故障排查

### vLLM 启动失败

```bash
# 查看 vLLM 日志
docker compose logs orpheus-vllm

# 常见问题:
# 1. 模型下载失败 → 检查网络或预下载模型
# 2. GPU 显存不足 → 降低 ORPHEUS_GPU_MEM_UTIL
# 3. FlashInfer 不可用 → vLLM 镜像版本过旧，更新到最新
```

### SNAC 解码器加载失败

```bash
# 查看 bridge 日志
docker compose logs orpheus-tts

# 常见问题:
# 1. snac 包未安装 → 检查 requirements.txt
# 2. 模型下载失败 → 检查网络，或预下载 hubertsiuzdak/snac_24khz
# 3. torch CUDA 版本不匹配 → 使用 SNAC_DEVICE=cpu 作为降级方案
```

### 健康检查返回 503

```bash
# 检查各组件状态
curl http://localhost:5060/health

# 分别检查:
# vLLM 后端: curl http://localhost:8000/health
# SNAC 解码器: 查看 orpheus-tts 容器日志
```

## 文件结构

```
orpheus-tts/
├── docker-compose.yml   # Docker Compose 编排（vLLM + Bridge）
├── Dockerfile           # FastAPI Bridge 镜像构建
├── api_server.py        # FastAPI Bridge 主程序（SNAC 解码 + OpenAI API）
├── start-vllm.sh        # vLLM 后端启动脚本
├── requirements.txt     # Bridge Python 依赖
├── .env.example         # 环境变量模板
└── README.md            # 本文档
```
