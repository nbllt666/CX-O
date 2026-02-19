# CXHMS 部署指南

## 目录

1. [环境要求](#环境要求)
2. [安装步骤](#安装步骤)
3. [配置说明](#配置说明)
4. [启动服务](#启动服务)
5. [Docker部署](#docker部署)
6. [生产环境配置](#生产环境配置)
7. [故障排除](#故障排除)

---

## 环境要求

### 系统要求

- **操作系统**: Windows 10/11, Linux (Ubuntu 20.04+), macOS 12+
- **Python**: 3.10 或更高版本
- **内存**: 最少 4GB RAM，推荐 8GB+
- **磁盘**: 最少 10GB 可用空间

### 依赖服务

- **LLM服务**（可选）:
  - Ollama: http://localhost:11434
  - 或其他兼容OpenAI API的服务

- **向量存储**（可选）:
  - Milvus Lite: 嵌入式，无需额外服务
  - Qdrant: 需要独立部署

---

## 安装步骤

### 1. 克隆仓库

```bash
git clone <repository-url>
cd CXHMS
```

### 2. 创建虚拟环境

```bash
# Windows
python -m venv venv
venv\Scripts\activate

# Linux/macOS
python3 -m venv venv
source venv/bin/activate
```

### 3. 安装依赖

```bash
pip install -r requirements.txt
```

### 4. 创建数据目录

```bash
mkdir -p data
mkdir -p logs
```

---

## 配置说明

### 配置文件位置

主配置文件: `config/default.yaml`

### 核心配置项

#### 服务器配置

```yaml
server:
  host: "0.0.0.0"      # 监听地址，0.0.0.0表示所有接口
  port: 8000           # API服务端口
  debug: false         # 调试模式（生产环境设为false）
```

#### LLM配置

```yaml
llm:
  provider: "ollama"   # LLM提供商: ollama, vllm, openai
  host: "http://localhost:11434"  # LLM服务地址
  model: "llama3.2"    # 模型名称
  temperature: 0.7     # 温度参数
  max_tokens: 2048     # 最大token数
```

#### 记忆配置

```yaml
memory:
  enabled: true                    # 启用记忆功能
  vector_enabled: true             # 启用向量搜索
  vector_backend: "milvus_lite"    # 向量后端: milvus_lite, qdrant
  milvus_lite:
    db_path: "data/milvus_lite.db" # Milvus Lite数据库路径
    vector_size: 768               # 向量维度
  qdrant:
    host: "localhost"              # Qdrant主机
    port: 6333                     # Qdrant端口
    vector_size: 768
```

#### ACP配置

```yaml
acp:
  enabled: true                    # 启用ACP功能
  agent_id: "cxhms_agent_001"      # 本机Agent ID
  agent_name: "CXHMS Agent"        # 本机Agent名称
  discovery_enabled: true          # 启用局域网发现
  discovery_port: 9999             # 发现服务端口
  broadcast_port: 9998             # 广播端口
```

#### WebUI配置

```yaml
webui:
  enabled: true                    # 启用WebUI
  host: "0.0.0.0"
  port: 7860                       # WebUI端口
  share: false                     # 是否生成公开链接
```

#### 安全配置

```yaml
security:
  api_key_enabled: false           # 启用API密钥认证
  api_key: ""                      # API密钥
  rate_limit_enabled: false        # 启用速率限制
  rate_limit_requests: 100         # 每分钟请求数限制
  rate_limit_period: 60
```

#### CORS配置

```yaml
cors:
  enabled: true
  origins:                         # 允许的源（生产环境应限制）
    - "*"
  allow_credentials: true
```

---

## 启动服务

### 开发环境

```bash
python main.py
```

服务启动后访问:
- API文档: http://localhost:8000/docs
- WebUI: http://localhost:7860
- 健康检查: http://localhost:8000/health

### 生产环境

使用Gunicorn + Uvicorn:

```bash
gunicorn backend.api.app:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
```

参数说明:
- `-w 4`: 4个工作进程
- `-k uvicorn.workers.UvicornWorker`: 使用Uvicorn worker

---

## Docker部署

### 使用Docker Compose

#### 1. 构建镜像

```bash
docker-compose build
```

#### 2. 启动服务

```bash
docker-compose up -d
```

#### 3. 查看日志

```bash
docker-compose logs -f
```

#### 4. 停止服务

```bash
docker-compose down
```

### Dockerfile说明

```dockerfile
FROM python:3.10-slim

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制代码
COPY . .

# 创建数据目录
RUN mkdir -p data logs

# 暴露端口
EXPOSE 8000 7860

# 启动命令
CMD ["python", "main.py"]
```

### Docker Compose配置

```yaml
version: '3.8'

services:
  cxhms:
    build: .
    ports:
      - "8000:8000"
      - "7860:7860"
    volumes:
      - ./data:/app/data
      - ./logs:/app/logs
      - ./config:/app/config
    environment:
      - CXHMS_CONFIG_PATH=/app/config/default.yaml
    restart: unless-stopped
    
  # 可选: Qdrant向量数据库
  qdrant:
    image: qdrant/qdrant:latest
    ports:
      - "6333:6333"
    volumes:
      - qdrant_storage:/qdrant/storage
    restart: unless-stopped

volumes:
  qdrant_storage:
```

---

## 生产环境配置

### 1. 安全配置

#### 启用API密钥

```yaml
security:
  api_key_enabled: true
  api_key: "your-secure-api-key-here"
```

#### 限制CORS

```yaml
cors:
  enabled: true
  origins:
    - "https://yourdomain.com"
    - "https://app.yourdomain.com"
  allow_credentials: true
```

#### 启用速率限制

```yaml
security:
  rate_limit_enabled: true
  rate_limit_requests: 100
  rate_limit_period: 60
```

### 2. 日志配置

```yaml
logging:
  level: "INFO"
  file: "logs/app.log"
  max_bytes: 10485760    # 10MB
  backup_count: 5        # 保留5个备份
```

### 3. 数据库配置

生产环境建议使用PostgreSQL替代SQLite:

```yaml
database:
  type: "postgresql"
  host: "localhost"
  port: 5432
  name: "cxhms"
  user: "cxhms_user"
  password: "your-password"
```

### 4. 反向代理配置

#### Nginx配置示例

```nginx
server {
    listen 80;
    server_name yourdomain.com;
    
    # API服务
    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
    
    # WebUI
    location /webui/ {
        proxy_pass http://localhost:7860/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### 5. 系统服务配置

#### systemd服务文件

创建 `/etc/systemd/system/cxhms.service`:

```ini
[Unit]
Description=CXHMS AI Agent Service
After=network.target

[Service]
Type=simple
User=cxhms
Group=cxhms
WorkingDirectory=/opt/cxhms
Environment="PATH=/opt/cxhms/venv/bin"
Environment="CXHMS_CONFIG_PATH=/opt/cxhms/config/production.yaml"
ExecStart=/opt/cxhms/venv/bin/python main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

启用服务:

```bash
sudo systemctl enable cxhms
sudo systemctl start cxhms
sudo systemctl status cxhms
```

---

## 故障排除

### 常见问题

#### 1. 端口被占用

**错误信息**:
```
OSError: [Errno 98] Address already in use
```

**解决方案**:
```bash
# 查找占用端口的进程
lsof -i :8000

# 或修改配置文件使用其他端口
# config/default.yaml
server:
  port: 8001  # 修改为其他端口
```

#### 2. 数据库权限错误

**错误信息**:
```
sqlite3.OperationalError: unable to open database file
```

**解决方案**:
```bash
# 确保数据目录存在且有写权限
mkdir -p data
chmod 755 data
```

#### 3. LLM连接失败

**错误信息**:
```
无法连接到Ollama服务器
```

**解决方案**:
1. 检查Ollama是否运行:
   ```bash
   curl http://localhost:11434/api/tags
   ```

2. 检查配置中的host是否正确

3. 检查防火墙设置

#### 4. 向量搜索不可用

**错误信息**:
```
向量存储不可用
```

**解决方案**:
1. 检查向量存储依赖是否安装:
   ```bash
   pip install pymilvus>=2.3.0
   # 或
   pip install qdrant-client>=1.7.0
   ```

2. 检查配置文件中的向量存储设置

3. 如果使用Qdrant，确保Qdrant服务已启动

#### 5. MCP服务器启动失败

**错误信息**:
```
启动MCP服务器失败
```

**解决方案**:
1. 检查MCP服务器命令是否正确
2. 确保所需的npm包或Python包已安装
3. 检查端口是否被占用
4. 查看详细错误日志

### 日志分析

#### 查看应用日志

```bash
# 实时查看日志
tail -f logs/app.log

# 查看错误日志
grep ERROR logs/app.log

# 查看特定模块日志
grep "MCPManager" logs/app.log
```

#### 日志级别调整

开发环境:
```yaml
logging:
  level: "DEBUG"
```

生产环境:
```yaml
logging:
  level: "INFO"
```

### 性能优化

#### 1. 数据库优化

```sql
-- 为常用查询添加索引
CREATE INDEX IF NOT EXISTS idx_memories_type_created ON memories(type, created_at);
CREATE INDEX IF NOT EXISTS idx_memories_workspace ON memories(workspace_id);
```

#### 2. 内存优化

```yaml
memory:
  max_memories: 10000  # 限制最大记忆数
  
context:
  max_messages: 50     # 限制上下文消息数
```

#### 3. 连接池配置

```yaml
database:
  pool_size: 10
  max_overflow: 20
```

### 备份与恢复

#### 备份数据

```bash
# 备份SQLite数据库
cp data/memories.db backups/memories_$(date +%Y%m%d).db

# 备份向量存储
cp -r data/milvus_lite.db backups/

# 备份配置
cp config/default.yaml backups/config_$(date +%Y%m%d).yaml
```

#### 恢复数据

```bash
# 停止服务
sudo systemctl stop cxhms

# 恢复数据库
cp backups/memories_20240206.db data/memories.db

# 恢复配置
cp backups/config_20240206.yaml config/default.yaml

# 启动服务
sudo systemctl start cxhms
```

---

## 升级指南

### 升级步骤

1. **备份数据**
   ```bash
   ./scripts/backup.sh
   ```

2. **拉取最新代码**
   ```bash
   git pull origin main
   ```

3. **更新依赖**
   ```bash
   pip install -r requirements.txt --upgrade
   ```

4. **运行迁移脚本（如有）**
   ```bash
   python scripts/migrate.py
   ```

5. **重启服务**
   ```bash
   sudo systemctl restart cxhms
   ```

### 版本兼容性

- v1.0.0: 初始版本
- 升级前请查看CHANGELOG.md了解破坏性变更

---

## 获取帮助

### 文档资源

- [API文档](API.md)
- [架构文档](ARCHITECTURE.md)
- [开发文档](DEVELOPMENT.md)

### 社区支持

- GitHub Issues: 报告问题
- GitHub Discussions: 讨论功能

### 调试模式

启用详细日志:

```yaml
server:
  debug: true
  
logging:
  level: "DEBUG"
```

---

## 许可证

MIT License
