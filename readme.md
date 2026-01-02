# 🌅 晨曦Origins Agent

晨曦Origins是一个人格化AI助手后端项目，支持长期记忆、多模态交互、弹幕互动等特性。

## ✨ 功能特性

### 🤖 核心能力
- **多模态对话**：支持文本、语音、图像等多种输入输出形式
- **双模型架构**：主模型负责对话，副模型负责记忆管理和内容审核
- **插件系统**：支持动态注册插件，扩展能力强
- **WebSocket实时通信**：支持流式响应和事件推送

### 🧠 记忆系统
- **SQLite持久化存储**：轻量级本地数据库
- **记忆类型管理**：永久记忆、长期记忆、短期记忆三级分类
- **重要性分级**：1-5级重要性评估
- **标签系统**：灵活的标签检索
- **审计日志**：完整的操作记录

### 📊 弹幕系统
- **RSocket协议**：高效的实时通信
- **弹幕监听**：支持礼物、弹幕等多种消息类型
- **内容审核**：内置AI审核机制
- **缓存管理**：本地弹幕数据缓存

### 🎤 语音功能
- **ASR语音识别**：支持SenseVoice和Whisper
- **TTS语音合成**：支持Edge TTS和F5-TTS
- **多角色切换**：多种语音角色可选

### 🎨 WebUI界面
- **Gradio构建**：现代化Web界面
- **聊天界面**：支持语音输入输出
- **设置页面**：灵活的配置管理
- **记忆管理**：可视化的记忆操作
- **弹幕监控**：实时弹幕流展示

## 🏗️ 项目架构

```
CX-O/
├── audio/                 # 音频处理模块
│   ├── asr.py            # 语音识别
│   ├── tts.py            # 语音合成
│   └── parser.py         # 音频解析
├── core/                  # 核心模块
│   ├── router.py         # FastAPI路由
│   ├── context.py        # 上下文管理
│   ├── websocket.py      # WebSocket处理
│   ├── danmaku_cache.py  # 弹幕缓存
│   └── memory/           # 记忆管理
│       └── manager.py    # 记忆管理器
├── llm/                   # LLM客户端
│   ├── client.py         # 客户端工厂
│   ├── vllm_client.py    # vLLM客户端
│   └── ollama_client.py  # Ollama客户端
├── plugins/               # 插件系统
│   └── danmaku.py        # 弹幕插件
├── webui/                 # Web界面
│   └── app.py            # Gradio应用
├── database/             # 数据库存储
├── data/                 # 数据文件
├── logs/                 # 日志文件
├── config.json           # 配置文件
├── main.py              # 主程序入口
└── requirements.txt     # 依赖列表
```

## 🚀 快速开始

### 环境要求
- Python 3.10+
- 4GB+ 内存
- 10GB+ 磁盘空间

### 安装依赖

```bash
# 克隆项目
git clone https://github.com/your-repo/CX-O.git
cd CX-O

# 创建虚拟环境（可选）
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 或
.\venv\Scripts\activate   # Windows

# 安装依赖
pip install -r requirements.txt
```

### 配置说明

编辑 `config.json`：

```json
{
  "system": {
    "llm_provider": "vllm",
    "vllm": {
      "host": "localhost",
      "port": 8000,
      "model": "Qwen2.5-7B-Instruct"
    },
    "assistant_vllm": {
      "host": "localhost",
      "port": 8001,
      "model": "Qwen2.5-1.5B-Instruct"
    }
  },
  "memory": {
    "archive_interval": 3600,
    "retrieval_limit": 10,
    "max_history_rounds": 20
  },
  "danmaku": {
    "enabled": true,
    "websocket_uri": "ws://localhost:9898"
  }
}
```

### 启动服务

**方式一：完整启动（推荐）**

```bash
python main.py
```

启动后访问：
- WebUI: http://localhost:7860
- API: http://localhost:8000

**方式二：仅启动后端**

```bash
python main.py --nui --port 8000
```

**方式三：指定端口**

```bash
python main.py --port 8000 --webui-port 7860
```

## 📡 API文档

### 聊天接口

```http
POST /api/v1/chat
Content-Type: application/json

{
  "text": "你好",
  "session_id": "sess_xxx"
}
```

### 多模态聊天

```http
POST /api/v1/chat/multimodal
Content-Type: multipart/form-data

- text: "描述图片内容"
- image: <图片文件>
- audio: <音频文件>
- session_id: "sess_xxx"
```

### 工具管理

```http
# 获取可用工具
GET /api/v1/tools

# 调用工具
POST /api/v1/tools/call
{
  "tool_name": "xxx",
  "arguments": {}
}
```

### 记忆管理

```http
# 获取记忆
GET /api/v1/memory?session_id=xxx&limit=10

# 添加记忆
POST /api/v1/memory
{
  "content": "要记住的内容",
  "type": "long_term",
  "importance": 3,
  "tags": ["标签1", "标签2"]
}

# 删除记忆
DELETE /api/v1/memory/{id}
```

### 弹幕接口

```http
# 获取弹幕
GET /api/v1/danmaku?count=10

# 获取统计
GET /api/v1/danmaku/stats
```

### 插件接口

```http
# 注册插件
POST /api/v1/register
{
  "port": 9000,
  "name": "插件名",
  "tools": [{"name": "tool1", "description": "工具描述"}],
  "capabilities": ["danmaku"]
}

# 心跳上报
POST /api/v1/heartbeat
{
  "port": 9000
}
```

## ⚙️ 配置详解

### LLM配置

| 参数 | 说明 | 默认值 |
|------|------|--------|
| llm_provider | 主模型提供商 | vllm |
| vllm.host | vLLM服务器地址 | localhost |
| vllm.port | vLLM服务器端口 | 8000 |
| vllm.model | 模型名称 | Qwen2.5-7B-Instruct |
| ollama.host | Ollama服务器地址 | http://localhost:11434 |

### 记忆配置

| 参数 | 说明 | 默认值 |
|------|------|--------|
| archive_interval | 归档间隔（秒） | 3600 |
| retrieval_limit | 检索数量限制 | 10 |
| max_history_rounds | 最大历史轮数 | 20 |

### 弹幕配置

| 参数 | 说明 | 默认值 |
|------|------|--------|
| enabled | 是否启用 | true |
| websocket_uri | WebSocket地址 | ws://localhost:9898 |
| task_ids | 房间号列表 | [] |
| audit_enabled | 是否启用审核 | true |

### 语音配置

| 参数 | 说明 | 默认值 |
|------|------|--------|
| tts.provider | TTS提供商 | edge |
| tts.voice | 语音角色 | zh-CN-XiaoxiaoNeural |
| asr.provider | ASR提供商 | sensevoice |
| asr.use_gpu | 是否使用GPU | true |

## 🔧 插件开发

### 注册插件

```python
from core.router import router
from pydantic import BaseModel

class PluginRegisterRequest(BaseModel):
    port: int
    name: str
    tools: list
    capabilities: list = []

@router.post("/register")
async def register_plugin(request: PluginRegisterRequest):
    # 注册逻辑
    pass
```

### 心跳机制

插件需要至少每30（建议10s）秒发送一次心跳：

```python
import requests
import time

while True:
    requests.post("http://localhost:8000/api/v1/heartbeat", json={"port": YOUR_PORT})
    time.sleep(30)
```

## 🧪 测试

### 单元测试

```bash
# 待补充
```

### 集成测试

```bash
# 启动服务后测试API
curl http://localhost:8000/health
```

## 📁 数据存储

### 记忆数据库
- 位置：`database/memories.db`
- 格式：SQLite3
- 表结构：
  - `memories`：记忆存储
  - `audit_logs`：操作日志

### 弹幕缓存
- 位置：`data/danmaku_cache/`
- 保留天数：7天（可配置）

### 日志文件
- 位置：`logs/app.log`
- 级别：INFO（可配置）

## 🐛 常见问题

### Q: 后端无法启动？
A: 检查端口是否被占用，配置文件是否正确

### Q: LLM连接失败？
A: 确认LLM服务已启动，配置地址和端口正确

### Q: 弹幕无法连接？
A: 检查WebSocket地址，确认弹幕服务运行

### Q: 语音识别无响应？
A: 检查ASR服务配置，确认API地址正确

## 📝 更新日志

### v1.0.0 (2024)
- 初始版本发布
- 基础对话功能
- 记忆系统
- 弹幕监听
- 语音处理
- WebUI界面

## 🤝 贡献指南

我们欢迎所有形式的贡献，包括但不限于：

- 提交Bug报告
- 建议新功能
- 改进文档
- 提交代码变更

### 提交变更

1. Fork 项目
2. 创建分支：`git checkout -b feature/xxx`
3. 提交更改：`git commit -m 'Add xxx'`
4. 推送分支：`git push origin feature/xxx`
5. 提交PR

## 📄 许可证

MIT License

## 👥 作者

ai猫娘晨曦团队

## 🙏 鸣谢

- [vLLM](https://github.com/vllm-project/vllm) - 高性能LLM推理
- [Ollama](https://ollama.ai/) - 本地LLM运行
- [Gradio](https://gradio.app/) - Web界面框架
- [FastAPI](https://fastapi.tiangolo.com/) - Web框架
- [RSocket](https://rsocket.io/) - 响应式协议
