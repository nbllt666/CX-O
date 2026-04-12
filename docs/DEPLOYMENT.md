# CX-O 部署指南

## 系统要求

### 硬件要求

- **CPU**: AMD Ryzen 5 / Intel i5 或更高
- **内存**: 16GB RAM（推荐 32GB）
- **GPU**: NVIDIA GPU with 8GB+ VRAM（推荐 12GB+）
- **存储**: 50GB+ 可用空间

### 软件要求

- Windows 10/11 或 Linux (Ubuntu 20.04+)
- Python 3.10+
- Node.js 18+
- CUDA 11.8+ / cuDNN 8.6+
- Miniconda3

---

## 服务架构

CX-O 采用分布式微服务架构，包含以下服务：

| 服务 | 端口 | 说明 |
|------|------|------|
| CXHMS Backend | 8000 | 核心 AI 服务 |
| CX-O Gateway | 8100 | WebSocket 网关 |
| CX-O Frontend | 5173 | Web 前端 |
| SenseVoice ASR | 8001 | 语音识别 |
| F5-TTS TTS | 8002 | 语音合成 |

---

## Windows 部署

### 一键启动

```batch
.\1-1.start-all.bat
```

### 手动部署

#### 1. 克隆/更新代码

```batch
cd c:\CX-O
git pull
```

#### 2. 安装 Miniconda 环境

项目已包含 Miniconda3，解压后创建环境：

```batch
cd c:\CX-O
# 创建 Python 3.10 环境
conda create -n cx-o python=3.10 -y
conda activate cx-o
```

#### 3. 安装 Python 依赖

```batch
# CXHMS 后端
cd CXHMS
pip install -r requirements.txt

# CX-O Gateway
cd ../cx-o-gateway
pip install -r requirements.txt
```

#### 4. 安装 Node.js 依赖

```batch
cd cx-o-frontend
npm install
```

#### 5. 下载模型

```batch
# SenseVoice 模型
cd ../SenseVoice
python download_sensevoice.py

# F5-TTS 模型
cd ../F5-TTS
python download_f5tts.py
```

#### 6. 配置

编辑配置文件：

**CXHMS 配置** (`CXHMS/config/default.yaml`):
```yaml
server:
  host: "0.0.0.0"
  port: 8000

llm:
  provider: "ollama"
  host: "http://localhost:11434"
  model: "qwen3-vl:8b"

memory:
  enabled: true
  vector_enabled: true
  vector_backend: "milvus_lite"
```

**Gateway 配置** (`cx-o-gateway/config.json`):
```json
{
  "server": {
    "host": "0.0.0.0",
    "port": 8100
  },
  "services": {
    "cxhms": {
      "url": "http://127.0.0.1:8000"
    },
    "sensevoice": {
      "url": "http://127.0.0.1:8001"
    },
    "f5tts": {
      "url": "http://127.0.0.1:8002"
    }
  }
}
```

#### 7. 启动 Ollama（LLM 服务）

```batch
# 安装 Ollama
# 下载地址: https://ollama.ai

# 拉取模型
ollama pull qwen3-vl:8b
ollama pull nomic-embed-text

# 启动 Ollama 服务
ollama serve
```

#### 8. 启动语音服务

```batch
# 启动 SenseVoice ASR
cd SenseVoice
python api.py

# 启动 F5-TTS TTS
cd ../F5-TTS
python webapi.py
```

#### 9. 启动 CXHMS 后端

```batch
cd CXHMS
python main.py
```

#### 10. 启动 Gateway

```batch
cd cx-o-gateway
python main.py
```

#### 11. 启动前端

```batch
cd cx-o-frontend
npm run dev
```

### 验证部署

- 前端界面: http://127.0.0.1:5173
- CXHMS API: http://127.0.0.1:8000/docs
- Gateway: http://127.0.0.1:8100

---

## Linux 部署

### 1. 安装系统依赖

```bash
sudo apt update
sudo apt install -y python3.10 python3-pip nodejs npm git
```

### 2. 安装 CUDA（GPU 支持）

参考 NVIDIA 官方文档安装 CUDA 11.8+ 和 cuDNN 8.6+。

### 3. 克隆代码

```bash
git clone <repository-url> /opt/cx-o
cd /opt/cx-o
```

### 4. 创建虚拟环境

```bash
python3.10 -m venv venv
source venv/bin/activate
```

### 5. 安装依赖

```bash
# CXHMS
cd CXHMS && pip install -r requirements.txt

# CX-O Gateway
cd ../cx-o-gateway && pip install -r requirements.txt

# 前端
cd ../cx-o-frontend && npm install
```

### 6. 配置服务

使用 systemd 管理服务，创建 `/etc/systemd/system/cx-o-gateway.service`:

```ini
[Unit]
Description=CX-O Gateway Service
After=network.target

[Service]
Type=simple
User=cx-o
WorkingDirectory=/opt/cx-o/cx-o-gateway
Environment="PATH=/opt/cx-o/venv/bin"
ExecStart=/opt/cx-o/venv/bin/python main.py
Restart=always

[Install]
WantedBy=multi-user.target
```

### 7. 启动服务

```bash
sudo systemctl enable cx-o-gateway
sudo systemctl start cx-o-gateway
```

---

## Docker 部署

### Dockerfile

**CXHMS** (`CXHMS/Dockerfile`):
```dockerfile
FROM python:3.10-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
EXPOSE 8000

CMD ["python", "main.py"]
```

**Gateway** (`cx-o-gateway/Dockerfile`):
```dockerfile
FROM python:3.10-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
EXPOSE 8100

CMD ["python", "main.py"]
```

### Docker Compose

创建 `docker-compose.yml`:

```yaml
version: '3.8'

services:
  cxhms:
    build: ./CXHMS
    ports:
      - "8000:8000"
    volumes:
      - ./CXHMS/data:/app/data
      - ./CXHMS/config:/app/config

  gateway:
    build: ./cx-o-gateway
    ports:
      - "8100:8100"
    volumes:
      - ./cx-o-gateway/data:/app/data
      - ./cx-o-gateway/config.json:/app/config.json
    depends_on:
      - cxhms

  frontend:
    image: node:18-alpine
    working_dir: /app
    command: npm run dev
    ports:
      - "5173:5173"
    volumes:
      - ./cx-o-frontend:/app
    depends_on:
      - gateway
```

### 启动

```bash
docker-compose up -d
```

---

## 生产环境配置

### 安全配置

#### 启用 API 密钥

在配置文件中启用认证：

```yaml
security:
  api_key_enabled: true
  api_key: "your-secure-api-key"
```

#### 限制 CORS

```json
{
  "cors": {
    "allow_origins": ["https://yourdomain.com"],
    "allow_credentials": true
  }
}
```

### 反向代理配置

#### Nginx 配置

```nginx
server {
    listen 80;
    server_name yourdomain.com;

    location / {
        proxy_pass http://localhost:5173;
        proxy_set_header Host $host;
    }

    location /api/ {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
    }

    location /ws {
        proxy_pass http://localhost:8100;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

### 日志配置

```yaml
logging:
  level: "INFO"
  file: "logs/app.log"
  max_bytes: 10485760
  backup_count: 5
```

### 备份策略

#### 自动备份脚本

创建 `backup.sh`:

```bash
#!/bin/bash
DATE=$(date +%Y%m%d)
BACKUP_DIR="/opt/backups/cx-o"

mkdir -p $BACKUP_DIR

# 备份数据库
cp /opt/cx-o/CXHMS/data/memories.db $BACKUP_DIR/memories_$DATE.db

# 备份配置
cp -r /opt/cx-o/CXHMS/config $BACKUP_DIR/config_$DATE

# 清理旧备份（保留30天）
find $BACKUP_DIR -mtime +30 -delete
```

添加 crontab:
```bash
0 2 * * * /opt/scripts/backup.sh
```

---

## 故障排除

### 常见问题

#### 1. 端口被占用

```bash
# Linux
lsof -i :8000

# Windows
netstat -ano | findstr "8000"
```

#### 2. GPU 不可用

```bash
# 检查 CUDA
nvidia-smi

# 验证 PyTorch GPU 支持
python -c "import torch; print(torch.cuda.is_available())"
```

#### 3. 模型加载失败

1. 检查模型文件是否完整
2. 确认 GPU 显存充足
3. 验证模型路径配置正确

#### 4. WebSocket 连接失败

1. 检查防火墙设置
2. 确认 Gateway 服务运行正常
3. 验证 CORS 配置

### 日志分析

#### CXHMS 日志

```bash
tail -f CXHMS/logs/app.log
```

#### Gateway 日志

```bash
tail -f cx-o-gateway/logs/gateway.log
```

---

## 性能优化

### 数据库优化

```sql
CREATE INDEX idx_memories_type_created ON memories(type, created_at);
CREATE INDEX idx_memories_workspace ON memories(workspace_id);
```

### 内存优化

```yaml
memory:
  max_memories: 10000

context:
  max_messages: 50
```

### 连接池配置

```yaml
database:
  pool_size: 10
  max_overflow: 20
```

---

## 升级指南

### 1. 备份数据

```bash
./backup.sh
```

### 2. 拉取新代码

```bash
git pull origin main
```

### 3. 更新依赖

```bash
pip install -r requirements.txt --upgrade
npm install
```

### 4. 运行迁移

```bash
python do_migrate.py
```

### 5. 重启服务

```bash
sudo systemctl restart cx-o-gateway
```
