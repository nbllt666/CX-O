# CX-O ASR 容器（流式 ASR + 声纹识别）

基于 FunASR 的**自包含**语音识别服务容器：真流式 ASR + 流式 VAD 分句 + 声纹（说话人）识别 + 在线聚类判"谁在说话"。镜像已内置全部模型，开箱即用、可离线运行，适合直接分享部署。

## 能力一览

| 能力 | 说明 |
|------|------|
| 流式 ASR | `paraformer-zh-streaming` 真流式增量解码（逐 0.15s 出 partial） |
| 流式 VAD 分句 | `fsmn-vad` 内置流式端点检测，把语音切成短句 |
| 声纹识别 | `cam++`（`speech_campplus_sv_zh-cn_16k-common`，192 维 embedding） |
| 说话人判定 | 在线聚类：注册说话人命中其名字；未注册新声音给会话内临时伪名 `spk_0`… |
| 并行识别 | 每个短句：文本识别 与 声纹提取 并行执行（互不阻塞） |
| 单次识别 | SenseVoice 富文本识别（含 emotion/event 标签），与旧接口完全兼容 |

> 模型接口说明：引擎使用**三个独立**的 FunASR AutoModel 实例（ASR / VAD / SPK）。FunASR 把 vad+punc 组合进同一 AutoModel 时，流式 `generate` 存在 chunk 类型 bug，因此必须是独立实例——这也是本容器设计如此的原因。

## 快速开始

### 方式 A：加载分发的镜像包

分发包：`release/cxo-asr-sensevoice-streaming-v1.tar`（`docker load` 直接加载）

```bash
docker load -i release/cxo-asr-sensevoice-streaming-v1.tar
docker run -d --name asr -p 8005:8005 cxo/asr-sensevoice:streaming-v1
curl http://127.0.0.1:8005/health        # → {"status":"healthy","model_loaded":true}
```

### 方式 B：Compose 一键启动（推荐）

```bash
docker compose -f docker/asr/docker-compose.yml up -d
curl http://127.0.0.1:8005/health
```

### 方式 C：本地重新构建

```bash
cd CX-O-SERVER && docker build -f ../docker/asr/Dockerfile -t cxo/asr-sensevoice:streaming-v1 .
```

> 镜像已内置模型（约 3GB 缓存层），无需联网下载。用 `docker save -o 名字.tar <镜像>` 即可再次分发。

## 接口总表（端口 8005）

| 接口 | 方法 | 用途 |
|------|------|------|
| `/health` | GET | 健康检查 |
| `/asr/recognize` | POST | 单次识别（base64 JSON，SenseVoice 富文本） |
| `/api/v1/asr` | POST | 单次识别（multipart，CX-O 主服务兼容） |
| `/ws/asr/stream` | WS | **流式识别**（推荐，见下） |
| `/api/v1/voiceprint/status` | GET | 声纹模型与画像状态 |
| `/api/v1/voiceprint/extract` | POST | 提取 192 维声纹 embedding（注册用） |
| `/api/v1/voiceprint/profiles/sync` | POST | 从挂载的 `speaker_profiles.json` 重载画像 |

## 流式 WS 协议 `/ws/asr/stream`

**上行**：二进制帧 = PCM 16k / mono / int16 LE 音频；文本帧 `{"action":"final"}` = 句结束信号（清空缓冲、产出最终结果）。

**下行**（JSON，字段向后兼容）：

```jsonc
// 说话中（增量）
{"text":"你好我是一", "is_final":false, "language":"", "emotion":"",
 "speaker_id":"", "speaker_registered":false, "speaker_conf":0.0}

// 句结束（final，带说话人判定）
{"text":"你好我是一个AI助手。", "is_final":true, "language":"", "emotion":"",
 "speaker_id":"小明", "speaker_registered":true, "speaker_conf":0.99}
```

- `speaker_id`：命中注册画像 → 注册名（如 `小明`）；未注册 → 会话内临时伪名 `spk_0`。
- `speaker_conf`：与所属簇质心的余弦相似度（0~1，阈值默认 0.65，env `SPK_SIM_THRESHOLD`）。
- 纯静默/噪声不会产生文本（无幻觉）。

最小客户端（Python）：

```python
import asyncio, json, wave
import websockets, numpy as np

async def main():
    async with websockets.connect("ws://127.0.0.1:8005/ws/asr/stream") as ws:
        with wave.open("voice.wav", "rb") as wf:            # 16k mono int16
            pcm = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
        for pos in range(0, len(pcm), 960):                  # 30ms 递推
            await ws.send(pcm[pos:pos+960].tobytes())
            await asyncio.sleep(0.03)
        await ws.send(json.dumps({"action": "final"}))
        async for msg in ws:
            m = json.loads(msg)
            print(m.get("is_final"), m.get("text"), m.get("speaker_id"))

asyncio.run(main())
```

## 声纹注册（让系统"认识"新说话人）

1. 把某人音频（wav/16k 更佳）提取为 embedding：

```bash
curl -X POST http://127.0.0.1:8005/api/v1/voiceprint/extract \
  -F file=@speaker_a.wav        # → {"embedding":[192 个 float],"dim":192}
```

2. 把画像写入 `speaker_profiles.json`（与容器挂载一致），并重载：

```json
{ "version": 1, "profiles": [
  { "name": "小明", "embeddings": [ [0.01, -0.02, ... 192 个 float] ] }
] }
```

```bash
curl -X POST http://127.0.0.1:8005/api/v1/voiceprint/profiles/sync   # → {"ok":true,"count":1}
```

此后该说话人再说话，流式结果 `speaker_id` 即为 `小明`。

> 与 CX-O 主服务对接时，画像的**权威写入方是主服务**（`/api/voiceprint/*` REST），容器只读消费挂载文件并经 `/profiles/sync` 重载——两者通过同一挂载文件/目录同步，避免双写冲突。

## 配置项

| 环境变量 | 默认 | 说明 |
|---------|------|------|
| `SPK_SIM_THRESHOLD` | `0.65` | 说话人归簇余弦阈值（注册命中判定） |
| `CUDA_VISIBLE_DEVICES` | 空（CPU） | 有 GPU 时填设备号（如 `0`）加速 |
| `ASR_PORT`（compose） | `8005` | 宿主机端口映射 |
| `VOICEPRINT_DIR`（compose） | `./data/voiceprint` | 声纹画像挂载目录（可选） |

## 与 CX-O 主服务对接（给开发者）

主服务 `CX-O-SERVER/config.json` 的 `asr` 节指向本容器即可：

```jsonc
"asr": {
  "mode": "remote",
  "remote_url": "http://127.0.0.1:8005",
  "ws_url": "ws://127.0.0.1:8005/ws/asr/stream",
  "voiceprint_enabled": true,     // 主服务侧声纹开关（CXO_ASR_VOICEPRINT_ENABLED 亦可）
  "spk_sim_threshold": 0.65,
  "spk_model": "iic/speech_campplus_sv_zh-cn_16k-common"
}
```

主服务侧说话人信息贯通链路：`StreamingASRResult.speaker_*` → `vad_processor` → `handlers/audio.py` → `voice.partial`/`asr_result`（仅注册命中带名字，伪名不外发）。

## 内置模型清单

| 模型 | 用途 |
|------|------|
| `speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-online` | 流式 ASR（`paraformer-zh-streaming` 别名） |
| `speech_fsmn_vad_zh-cn-16k-common-pytorch` | 流式 VAD 分句 |
| `punc_ct-transformer_cn-en-common-vocab471067-large` | 标点（单次识别用） |
| `SenseVoiceSmall` | 单次富文本识别（emotion/event） |
| `speech_campplus_sv_zh-cn_16k-common` | 声纹 embedding（192 维） |

> 镜像内置缓存约 3GB。首次请求需等引擎懒加载（流式 ASR ~10-60s），之后常驻。

## 已知事项 / FAQ

- **为什么首条识别要等一会儿？** 三个模型在首个 WS 连接时懒加载（共享内存，之后不再重复加载）。
- **短句（<0.5s）没 partial？** 引擎有"投机 partial"兜底：句长 ≥0.15s 即做一次性预判破发，短句也能驱动下游 LLM（已在 CX-O 全双工链路验证）。
- **静音/噪声会出乱码吗？** 不会——流式引擎对纯静默/噪声输出空文本（实测无幻觉）。
- **多个客户端可以同时用吗？** 可以。每个 WS 连接独立持有 VAD/ASR 缓存与说话人临时簇；声纹模型任务走 4 线程执行器，并发不串扰。
- **延迟预算**：容器内首 partial ≈ 0.3s；全链（ASR→LLM→TTS）还取决于下游 LLM/TTS 栈，与 CX-O 全双工对接时由主服务路径主导。
- **GPU**：默认 CPU 推理即可用（已实测）；有 GPU 时设置 `CUDA_VISIBLE_DEVICES=0` 可显著加速大模型解码。

## 变更与维护

- 引擎代码：`asr_container/`（`streaming_engine.py` 流式编排、`speaker_cluster.py` 在线聚类）
- 服务入口：`api_server.py`
- 编排：`docker/asr/Dockerfile`、`docker/asr/docker-compose.yml`
- 主项目对接与验证记录：`.trae/documents/20260825_模块0_ASR容器流式与声纹识别整合.md`