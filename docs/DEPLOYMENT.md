# CX-O 部署指南

## 系统要求

### 硬件要求

- **CPU**: AMD Ryzen 5 / Intel i5 或更高
- **内存**: 16GB RAM（推荐 32GB）
- **GPU**: NVIDIA GPU with 8GB+ VRAM（推荐 12GB+）
- **存储**: 50GB+ 可用空间

### 软件要求

- Windows 10/11
- Python 3.10+
- Node.js 18+
- CUDA 11.8+ / cuDNN 8.6+
- Miniconda3

## v4 单体架构部署

### 1. 克隆/更新代码

```batch
cd c:\CX-O\cx-o
git pull
```

### 2. 创建 Python 虚拟环境

```batch
cd c:\CX-O\cx-o
conda create -n cx-o python=3.10 -y
conda activate cx-o
```

### 3. 安装依赖

```batch
cd c:\CX-O\cx-o
pip install -r requirements.txt
```

### 4. 下载模型

```batch
# 下载 SenseVoice 模型
python download_sensevoice.py

# 下载 F5-TTS 模型
python download_f5tts.py
```

### 5. 配置

编辑 `cx-o/server/config.json`:

```json
{
  "server": {
    "host": "0.0.0.0",
    "port": 8100
  },
  "asr": {
    "model_dir": "SenseVoice",
    "device": "cuda",
    "enabled": true
  },
  "tts": {
    "model_dir": "F5-TTS",
    "device": "cuda",
    "enabled": true,
    "ref_audio": "data/voice_refs/default.wav",
    "ref_text": "你好，我是语音助手。"
  },
  "llm": {
    "provider": "ollama",
    "host": "http://localhost:11434",
    "model": "qwen3-vl:8b"
  }
}
```

### 6. 启动服务

```batch
cd c:\CX-O\cx-o\server
python main.py
```

### 7. 验证

访问 http://127.0.0.1:8100/health 确认服务健康。

## Docker 部署（可选）

### 构建镜像

```dockerfile
FROM nvidia/cuda:11.8-cudnn8-runtime-ubuntu22.04

WORKDIR /app
COPY . /app

RUN pip install -r requirements.txt

CMD ["python", "server/main.py"]
```

### 运行

```bash
docker build -t cx-o .
docker run --gpus all -p 8100:8100 cx-o
```

## 微服务 vs 单体对比

| 项目 | 微服务 (v3) | 单体 (v4) |
|------|-------------|-----------|
| 启动服务数 | 4+ | 1 |
| 端口数 | 4+ | 1 |
| 内存占用 | ~8GB | ~6GB |
| 延迟 | ~800ms | ~400ms |

## 故障排除

### 模型加载失败

1. 检查 CUDA 和 cuDNN 版本
2. 确认 GPU 显存充足
3. 验证模型文件完整性

### 端口占用

```batch
netstat -ano | findstr "8100"
```

### 日志位置

- 应用日志: `logs/app.log`
- 配置日志级别调整 `config.json` 中的 `logging.level`

## 备份与恢复

### 备份数据

```python
from server.core.backup import get_backup_manager

backup_mgr = get_backup_manager()
backup_path = backup_mgr.create_backup("data/memories.db")
```

### 恢复数据

```python
backup_mgr.restore_backup(backup_path, "data/memories.db")
```
