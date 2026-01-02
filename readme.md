# 晨曦Origins Agent 技术文档

## 项目概述

晨曦Origins是一个人格化AI助手后端系统，具备长期记忆、多模态交互、弹幕互动等能力。

**项目路径**: `d:\CX-O\CX-O\`

**版本**: 1.0.0

**作者**: ai猫娘晨曦团队

---

## 目录结构

```
CX-O/
├── main.py                 # 主程序入口
├── config.json             # 配置文件
├── requirements.txt        # Python依赖
├── README.md              # 项目说明
│
├── core/                   # 核心模块
│   ├── router.py          # FastAPI主控路由
│   ├── websocket.py       # WebSocket管理
│   ├── context.py         # 对话上下文管理器
│   ├── danmaku_cache.py   # 弹幕缓存系统
│   └── memory/
│       └── manager.py     # 记忆管理器
│
├── llm/                    # LLM服务模块
│   ├── client.py          # LLM客户端工厂
│   ├── vllm_client.py     # vLLM客户端
│   ├── ollama_client.py   # Ollama客户端
│   └── tools.py           # 工具定义
│
├── audio/                  # 音频处理模块
│   ├── parser.py          # 音效解析器
│   ├── asr.py            # 语音识别(ASR)
│   └── tts.py            # 语音合成(TTS)
│
├── plugins/                # 插件系统
│   └── danmaku.py         # 弹幕监听插件
│
└── webui/                  # Gradio WebUI
    └── app.py             # WebUI应用
```

---

## 核心功能模块

### 1. 主程序入口 (main.py)

**功能**:
- WebUI与后端服务分离启动
- 支持 `--nui` 参数只启动后端
- 后端服务管理器 (BackendManager)

**启动方式**:
```bash
# 默认启动：WebUI + 后端服务
python d:\CX-O\CX-O\main.py

# 只启动后端（无WebUI）
python d:\CX-O\CX-O\main.py --nui

# 自定义端口
python d:\CX-O\CX-O\main.py --port 8000 --webui-port 7860
```

**后端服务端口**: 8000

**WebUI端口**: 7860

---

### 2. FastAPI主控路由 (core/router.py)

**API端点**:

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/v1/chat` | POST | 发送用户消息 |
| `/api/v1/chat/multimodal` | POST | 发送多模态消息 |
| `/api/v1/register` | POST | 注册插件 |
| `/api/v1/heartbeat` | POST | 心跳上报 |
| `/api/v1/tools` | GET | 获取工具列表 |
| `/api/v1/event/push` | POST | 插件事件推送 |
| `/api/v1/tools/call` | POST | 手动调用工具 |
| `/api/v1/config` | GET/POST | 配置管理 |
| `/api/v1/memory` | GET/POST/DELETE | 记忆管理 |
| `/api/v1/danmaku` | GET | 弹幕管理 |

**使用示例**:
```python
import requests

# 发送消息
response = requests.post("http://localhost:8000/api/v1/chat", json={
    "text": "你好",
    "session_id": "test_session"
})

# 获取配置
response = requests.get("http://localhost:8000/api/v1/config")
config = response.json()
```

---

### 3. 对话上下文管理器 (core/context.py)

**功能**:
- 对话上下文持久化 (JSON文件)
- 会话管理
- Mono上下文管理 (临时信息保持)
- LRU内存缓存加速

**核心类**: `ContextManager`

**初始化参数**:
```python
ContextManager(
    context_dir="data/contexts",  # 上下文文件目录
    max_messages=40,              # 最大消息数量
    cache_ttl=3600,              # 缓存TTL(秒)
    max_cache_size=100           # 最大缓存会话数
)
```

**核心方法**:

| 方法 | 功能 |
|------|------|
| `save_context()` | 保存对话上下文 |
| `load_context()` | 加载对话上下文 |
| `append_message()` | 追加单条消息 |
| `get_recent_messages()` | 获取最近N条消息 |
| `clear_context()` | 清空会话 |
| `add_mono_context()` | 添加Mono上下文 |
| `get_mono_context()` | 获取有效Mono上下文 |
| `list_sessions()` | 列出所有会话 |

**数据存储**:
- 位置: `data/contexts/sessions/`
- 格式: JSON文件 (`{session_id}.json`)

---

### 4. 记忆管理器 (core/memory/manager.py)

**功能**:
- 记忆的CRUD操作
- SQLite数据库存储
- 审计日志记录
- RAG检索

**核心类**: `MemoryManager`

**初始化参数**:
```python
MemoryManager(db_path="database/memories.db")
```

**记忆类型**:
- `permanent` - 永久记忆
- `long_term` - 长期记忆
- `short_term` - 短期记忆

**核心方法**:

| 方法 | 功能 |
|------|------|
| `write_memory()` | 写入记忆 |
| `get_memory()` | 获取记忆 |
| `search_memories()` | 搜索记忆 |
| `update_memory()` | 更新记忆 |
| `delete_memory()` | 删除记忆 |
| `restore_memory()` | 恢复记忆 |
| `get_statistics()` | 获取统计 |

**数据库结构**:
```sql
-- 记忆表
CREATE TABLE memories (
    id INTEGER PRIMARY KEY,
    type VARCHAR(20),           -- 记忆类型
    content TEXT,               -- 记忆内容
    importance INTEGER,         -- 重要性(1-5)
    tags TEXT,                  -- 标签(JSON数组)
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    archived_at TIMESTAMP,
    is_deleted BOOLEAN
)

-- 审计日志表
CREATE TABLE audit_logs (
    id INTEGER PRIMARY KEY,
    operation VARCHAR(50),      -- 操作类型
    memory_id INTEGER,
    operator VARCHAR(20),       -- 操作者
    details TEXT,               -- 详情(JSON)
    timestamp TIMESTAMP
)
```

---

### 5. 弹幕缓存系统 (core/danmaku_cache.py)

**功能**:
- 原始弹幕缓存
- 审核结果存储
- 弹幕检索
- 过期清理

**核心类**: `DanmakuCacheManager`

**初始化参数**:
```python
DanmakuCacheManager(
    cache_dir="data/danmaku_cache",  # 缓存目录
    retention_days=7,               # 保留天数
    max_count=10000                 # 最大缓存数量
)
```

**弹幕状态**:
- `pending` - 待审核
- `approved` - 已通过
- `rejected` - 已拒绝

**核心方法**:

| 方法 | 功能 |
|------|------|
| `add_raw_danmaku()` | 添加原始弹幕 |
| `add_audited_danmaku()` | 添加审核后弹幕 |
| `get_recent_danmaku()` | 获取最近弹幕 |
| `get_danmaku_by_id()` | 根据ID获取弹幕 |
| `update_audit_result()` | 更新审核结果 |
| `cleanup_old_danmaku()` | 清理过期弹幕 |
| `get_statistics()` | 获取统计信息 |

**数据存储**:
- 原始弹幕: `data/danmaku_cache/raw_danmaku.jsonl`
- 审核弹幕: `data/danmaku_cache/audited_danmaku.jsonl`

---

### 6. LLM客户端工厂 (llm/client.py)

**功能**:
- vLLM客户端管理
- Ollama客户端管理
- 统一调用接口

**核心类**: `LLMFactory`

**初始化**:
```python
LLMFactory(config)
```

**配置结构**:
```json
{
    "system": {
        "llm_provider": "vllm",
        "vllm": {
            "host": "localhost",
            "port": 8000,
            "model": "Qwen2.5-7B-Instruct"
        },
        "ollama": {
            "host": "http://localhost:11434",
            "model": "llama3.2"
        }
    }
}
```

**核心方法**:

| 方法 | 功能 |
|------|------|
| `get_client()` | 获取指定提供商客户端 |
| `chat()` | 发送聊天请求(流式) |
| `chat_simple()` | 发送聊天请求(非流式) |
| `is_available()` | 检查提供商是否可用 |
| `get_model_name()` | 获取模型名称 |

---

### 7. 工具定义 (llm/tools.py)

**主模型工具 (MASTER_TOOLS)**:

| 工具名称 | 功能 |
|----------|------|
| `write_long_term_memory` | 写入长期记忆 |
| `search_all_memories` | 跨库检索记忆 |
| `call_assistant` | 呼出副模型 |
| `set_alarm` | 设置定时提醒 |
| `mono` | 保持信息在上下文中 |
| `get_recent_danmaku` | 获取最近弹幕(未审核) |
| `get_danmaku_by_id` | 根据ID获取弹幕 |

**副模型工具 (ASSISTANT_TOOLS)**:

| 工具名称 | 功能 |
|----------|------|
| `create_daily_summary` | 生成每日摘要 |
| `archive_memories` | 归档记忆 |
| `update_memory_node` | 更新记忆 |
| `search_memories` | 检索记忆 |
| `delete_memory` | 删除记忆 |
| `merge_memories` | 合并相似记忆 |
| `clean_expired` | 清理过期记忆 |
| `export_memories` | 导出记忆 |
| `import_memories` | 导入记忆 |
| `review_danmaku` | 审核弹幕 |
| `verify_integrity` | 验证数据完整性 |

---

### 8. 音频处理模块 (audio/)

#### 8.1 音效解析器 (audio/parser.py)

**功能**:
- 扫描音效目录
- 解析文本中的音效标记
- 分割文本供TTS合成

**使用格式**: `文本内容（音效名）文本内容`

**示例**:
```python
parser = EffectParser("data/effects")

# 解析包含音效的文本
parts = parser.parse_text_with_effects("你好（ding）很高兴见到你")
# 返回: [
#     {"type": "text", "content": "你好"},
#     {"type": "sound", "file": "ding.wav", "name": "ding"},
#     {"type": "text", "content": "很高兴见到你"}
# ]
```

#### 8.2 语音识别 (audio/asr.py)

**支持的提供商**:

| 提供商 | 说明 |
|--------|------|
| `sensevoice` | SenseVoice API服务调用 |
| `whisper` | Whisper本地模型 |

**使用示例**:
```python
from audio.asr import recognize_audio

# 识别音频文件
result = asyncio.run(recognize_audio(
    audio_path="audio.wav",
    provider="sensevoice",
    config={"api_url": "http://localhost:50000/api/v1/asr"}
))
```

**注意**: SenseVoice需要单独启动API服务:
```bash
cd d:\CX-O\SenseVoice
python api.py  # 默认端口50000
```

#### 8.3 语音合成 (audio/tts.py)

**支持的提供商**:

| 提供商 | 说明 |
|--------|------|
| `edge` | 微软Edge TTS (无需额外安装) |
| `f5-tts` | F5-TTS开源语音克隆 |

**Edge TTS语音角色**:
- `zh-CN-XiaoxiaoNeural` - 女声(晓晓)
- `zh-CN-YunxiNeural` - 男声(云希)
- `zh-CN-XiaoyouNeural` - 女声(晓悠)

**使用示例**:
```python
from audio.tts import synthesize_speech

# 合成语音
audio = asyncio.run(synthesize_speech(
    text="你好，这是语音合成测试",
    provider="edge",
    config={"voice": "zh-CN-XiaoxiaoNeural"},
    output_path="output.wav"
))
```

---

### 9. 弹幕监听插件 (plugins/danmaku.py)

**功能**:
- 基于RSocket协议连接弹幕服务器
- 接收弹幕消息
- 自动缓存到数据库

**核心类**: `DanmakuPlugin`

**初始化**:
```python
plugin = DanmakuPlugin(
    cache_manager=DanmakuCacheManager(),
    config={}
)
```

**核心方法**:

| 方法 | 功能 |
|------|------|
| `connect()` | 连接弹幕服务器 |
| `disconnect()` | 断开连接 |
| `set_danmaku_callback()` | 设置弹幕回调 |
| `get_status()` | 获取状态 |

**RSocket消息格式**:
```json
{
    "type": "DANMU",
    "roomId": "12345",
    "msg": {
        "username": "用户",
        "uid": "123456",
        "content": "弹幕内容",
        "badgeLevel": 10,
        "badgeName": "粉丝牌"
    }
}
```

---

### 10. Gradio WebUI (webui/app.py)

**功能**:
- 聊天界面
- 设置页面
- 记忆管理
- 弹幕监控
- 后端服务控制

**页面结构**:

| 页面 | 功能 |
|------|------|
| 💬 聊天 | 与AI对话，支持语音输入 |
| ⚙️ 设置 | 配置LLM、记忆、弹幕、语音 |
| 🧠 记忆管理 | 查看和管理记忆 |
| 📊 弹幕监控 | 监控实时弹幕 |

**配置项**:

```json
{
    "system": {
        "llm_provider": "vllm",
        "vllm": {...},
        "assistant_provider": "vllm",
        "assistant_vllm": {...}
    },
    "memory": {
        "archive_interval": 3600,
        "retrieval_limit": 10,
        "max_history_rounds": 20
    },
    "danmaku": {
        "enabled": true,
        "websocket_uri": "ws://localhost:9898",
        "audit_enabled": true
    },
    "tts": {
        "provider": "edge",
        "voice": "zh-CN-XiaoxiaoNeural"
    },
    "asr": {
        "provider": "sensevoice",
        "use_gpu": true
    }
}
```

---

## 依赖安装

```bash
cd d:\CX-O\CX-O
pip install -r requirements.txt
```

**主要依赖**:
```
fastapi>=0.100.0
uvicorn>=0.23.0
gradio>=4.0.0
python-dotenv>=1.0.0
httpx>=0.24.0
rsocket>=0.4.0
aiohttp>=3.8.0
edge-tts>=6.0.0
openai-whisper>=20231117
```

---

## 快速开始

### 1. 启动后端服务

```bash
python d:\CX-O\CX-O\main.py
```

### 2. 启动WebUI

访问: http://localhost:7860

### 3. (可选) 启动SenseVoice服务

```bash
cd d:\CX-O\SenseVoice
python api.py
```

---

## 配置说明

### 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `SENSEVOICE_DEVICE` | SenseVoice运行设备 | `cuda:0` |
| `SENSEVOICE_PORT` | SenseVoice服务端口 | `50000` |

### 配置文件

位置: `config.json`

修改后需重启服务生效。

---

## 数据目录

| 目录 | 用途 |
|------|------|
| `data/contexts/` | 对话上下文 |
| `data/danmaku_cache/` | 弹幕缓存 |
| `data/effects/` | 音效文件(.wav) |
| `database/` | SQLite数据库 |
| `logs/` | 日志文件 |

---

## 日志配置

**日志位置**: `logs/app.log`

**日志格式**:
```
2026-01-02 09:00:00,000 - __main__ - INFO - 消息内容
```

**日志级别**: INFO

---

## 扩展开发

### 添加新插件

1. 在 `plugins/` 目录创建新文件
2. 继承基础功能类
3. 实现 `register()`, `heartbeat()` 等接口
4. 在WebUI中添加配置页面

### 添加新LLM提供商

1. 在 `llm/` 目录创建新客户端
2. 实现 `chat()`, `chat_simple()` 接口
3. 在 `llm/client.py` 的工厂中注册
4. 在WebUI设置中添加配置选项

---

## 常见问题

### 1. WebUI无法启动

检查端口是否被占用:
```bash
netstat -ano | findstr :7860
```

### 2. LLM连接失败

检查LLM服务是否启动:
```bash
# vLLM
curl http://localhost:8000/health

# Ollama
curl http://localhost:11434/api/tags
```

### 3. 弹幕连接失败

确认RSocket服务器地址正确，检查网络连接。

---

## 更新日志

**v1.0.0** (2026-01-02)
- 初始版本发布
- 基础功能完成
- WebUI界面完善

---

## 许可证

MIT License
