## F5-TTS TensorRT-LLM Triton 部署指南

本目录包含使用 TensorRT-LLM 和 Triton Inference Server 部署 F5-TTS 的完整配置。

### 性能基准

在单张 L20 GPU 上，使用 26 个不同的 prompt_audio 和 target_text 对，16 NFE：

| Model               | Concurrency    | Avg Latency | RTF    | Mode            |
|---------------------|----------------|-------------|--------|-----------------|
| F5-TTS Base (Vocos) | 2              | 253 ms      | 0.0394 | Client-Server   |
| F5-TTS Base (Vocos) | 1 (Batch_size) | -           | 0.0402 | Offline TRT-LLM |
| F5-TTS Base (Vocos) | 1 (Batch_size) | -           | 0.1467 | Offline Pytorch |

### 快速开始

#### 方式一：Docker Compose（推荐）

```bash
# 设置模型版本
export MODEL=F5TTS_v1_Base

# 启动服务（自动下载模型、转换引擎、启动Triton）
docker compose up
```

#### 方式二：从源码构建

```bash
# 构建 Docker 镜像
docker build . -f Dockerfile.server -t f5-triton-f5-tts:24.12

# 创建容器
docker run -it --name "f5-server" --gpus all --net host -v /mnt:/mnt --shm-size=2g f5-triton-f5-tts:24.12

# 容器内执行
cd F5-TTS-runtime
bash run.sh 0 4 F5TTS_v1_Base
```

### 运行阶段说明

`run.sh` 脚本支持分阶段执行：

```bash
# 完整流程：下载模型 -> 转换引擎 -> 导出Vocoder -> 配置Triton -> 启动服务
bash run.sh 0 4 F5TTS_v1_Base

# 仅启动服务（假设引擎已构建）
bash run.sh 4 4 F5TTS_v1_Base

# 测试 HTTP 客户端
bash run.sh 6 6 F5TTS_v1_Base
```

| 阶段 | 说明 |
|------|------|
| 0 | 从 HuggingFace 下载模型权重 |
| 1 | 转换 PyTorch checkpoint 为 TensorRT-LLM 格式 |
| 2 | 导出 Vocos Vocoder 为 ONNX 并构建 TensorRT 引擎 |
| 3 | 配置 Triton Model Repository |
| 4 | 启动 Triton Server |
| 5 | 测试 gRPC 客户端 |
| 6 | 测试 HTTP 客户端 |
| 7 | TRT-LLM 离线基准测试 |
| 8 | PyTorch 离线基准测试 |

### HTTP 客户端使用

```bash
# 基本用法
python3 client_http.py \
  --reference-audio your_ref.wav \
  --reference-text "Reference text here." \
  --target-text "Text to synthesize." \
  --output-audio output.wav

# 查看性能指标
python3 client_http.py --server-url localhost:8000
```

### 流式推理

Triton 支持流式响应，首包延迟可低于 100ms：

```python
# 流式客户端示例
import requests
import numpy as np

url = "http://localhost:8000/v2/models/f5_tts/infer"
# ... 准备请求数据 ...
response = requests.post(url, json=data, stream=True)
for chunk in response.iter_content(chunk_size=4096):
    # 处理音频块
    pass
```

### 自定义模型

如需使用自定义 checkpoint：

```bash
# 修改 run.sh 中的路径
ckpt_file=/path/to/your/model.pt
vocab_file=/path/to/your/vocab.txt

# 注意：使用匹配的模型版本
# F5TTS_v1_* 用于 v1 模型
# F5TTS_* 用于 v0 模型
```

### 目录结构

```
triton_trtllm/
├── Dockerfile.server          # Docker 镜像构建文件
├── docker-compose.yml         # Docker Compose 配置
├── run.sh                     # 主运行脚本
├── client_http.py             # HTTP 客户端
├── client_grpc.py             # gRPC 客户端
├── benchmark.py               # 性能基准测试
├── scripts/
│   ├── convert_checkpoint.py  # PyTorch -> TRT-LLM 转换
│   ├── export_vocoder_to_onnx.py
│   └── fill_template.py       # 配置模板填充
├── model_repo_f5_tts/
│   ├── f5_tts/
│   │   ├── config.pbtxt       # Triton 模型配置
│   │   └── 1/
│   │       ├── model.py       # Triton Python 后端
│   │       └── f5_tts_trtllm.py
│   └── vocoder/
│       └── config.pbtxt
└── patch/
    └── f5tts/                 # TensorRT-LLM F5TTS 模型定义
        ├── model.py
        └── modules.py
```

### 硬件要求

- NVIDIA GPU: 计算能力 7.0+（推荐 RTX 3090/4090, A100, L20）
- 显存: 最低 6GB，推荐 8GB+
- CUDA: 12.0+
- Docker: 20.10+
- NVIDIA Container Toolkit

### 故障排除

**引擎转换内存不足**
- 降低最大序列长度
- 启用激活值 checkpoint
- 使用更小的批处理大小

**音频质量问题**
- 检查 Vocoder 引擎路径配置
- 验证模型量化精度设置

**Credits**
1. [Yuekai Zhang](https://github.com/yuekaizhang)
2. [F5-TTS-TRTLLM](https://github.com/Bigfishering/f5-tts-trtllm)
