# CX-O 文档中心

## 文档索引

| 文档 | 说明 |
|------|------|
| [FEATURES.md](FEATURES.md) | **功能特性详细介绍** — 核心功能、技术架构、设计亮点 |
| [ARCHITECTURE.md](ARCHITECTURE.md) | **系统架构文档** — 子项目结构、模块依赖、数据流、通信架构 |
| [API.md](API.md) | **API 文档** — REST API 和 WebSocket API 完整参考 |
| [DEPLOYMENT.md](DEPLOYMENT.md) | **部署指南** — 系统要求、安装步骤、配置说明、问题排查 |
| [VOICE_SERVICES.md](VOICE_SERVICES.md) | **语音服务文档** — ASR/TTS/VAD/打断/情感解析/语音工作站 |

## 快速导航

### 新手入门

1. 阅读 [FEATURES.md](FEATURES.md) 了解项目核心特色
2. 查看 [ARCHITECTURE.md](ARCHITECTURE.md) 理解系统架构
3. 参考 [DEPLOYMENT.md](DEPLOYMENT.md) 进行部署

### API 开发

- REST API: 参考 [API.md](API.md)
- WebSocket: 参考 [API.md](API.md) 的 WebSocket 部分
- 语音工作站 API: 参考 [API.md](API.md) 的语音工作站章节

### 语音功能

- ASR/TTS/VAD 配置: 参考 [VOICE_SERVICES.md](VOICE_SERVICES.md)
- 全双工打断: 参考 [VOICE_SERVICES.md](VOICE_SERVICES.md) 的打断系统章节
- 语音克隆工作流: 参考 [VOICE_SERVICES.md](VOICE_SERVICES.md) 的语音工作站章节

### 架构理解

- 系统总览: 参考 [ARCHITECTURE.md](ARCHITECTURE.md) 的系统总览架构图
- 模块依赖: 参考 [ARCHITECTURE.md](ARCHITECTURE.md) 的后端核心模块依赖图
- 数据流: 参考 [ARCHITECTURE.md](ARCHITECTURE.md) 的数据流图

## 项目特色速览

| 特性 | 说明 | 详细文档 |
|------|------|---------|
| 🗣️ 端到端语音对话 | ASR → LLM → TTS 全流程，支持全双工打断 | [VOICE_SERVICES.md](VOICE_SERVICES.md) |
| 🧠 智能记忆系统 | 模拟人类遗忘曲线，三维评分，场景感知路由 | [FEATURES.md](FEATURES.md#11-智能记忆系统) |
| 🔗 知识图谱 | 四大图库、语义搜索、图算法、56 个 AI 工具 | [FEATURES.md](FEATURES.md#12-知识图谱集成) |
| 🛡️ 三档防火墙 | block/passive/reply 分级审核，LLM 智能决策 | [FEATURES.md](FEATURES.md#21-三档防火墙系统) |
| 🤝 ACP 协议 | Agent 互联、局域网发现、群组协同 | [FEATURES.md](FEATURES.md#51-acp-多智能体协作协议) |
| 🔌 CXFC 插件联邦 | 插件自动发现、心跳检测、Skill 注册 | [FEATURES.md](FEATURES.md#52-cxfc-插件联邦协议) |
| 🔧 MCP 工具生态 | 标准化工具协议，外部工具接入 | [FEATURES.md](FEATURES.md#54-工具注册与调用系统) |
| 🎭 虚拟形象驱动 | Live2D + VRM 双引擎，口型同步，表情混合 | [FEATURES.md](FEATURES.md#41-虚拟形象驱动系统) |
| 📺 直播 + OBS | 弹幕叠加、字幕显示、OBS 分层输出 | [FEATURES.md](FEATURES.md#42-直播舞台与-obs-分层输出) |
| 🎙️ 语音工作站 | VoxCPM/CosyVoice/IndexTTS/F5-TTS/So-VITS-SVC | [FEATURES.md](FEATURES.md#34-语音工作站) |
| 🔄 全双工打断 | 用户打断 Agent + Agent 打断用户 | [FEATURES.md](FEATURES.md#22-全双工打断系统) |
| 💬 情感与音效 | 15 种情感标记 + 音效标记，驱动 TTS 和表情 | [FEATURES.md](FEATURES.md#23-情感与音效解析引擎) |

## 子项目概览

| 子项目 | 技术栈 | 端口 | 说明 |
|--------|--------|------|------|
| CX-O-SERVER | Python / FastAPI | 8000 | 核心后端服务（LLM路由、记忆、图谱、工具、WebSocket） |
| CX-O-Gateway | Python / FastAPI | 8100 | 轻量网关（已整合进 CX-O-SERVER，可独立部署） |
| CX-O-VoiceWorkStation | Python / FastAPI | 8200 | 语音工作站（声音克隆、情感参考、模型训练） |
| CX-O-Frontend | React / TypeScript / Vite | 5173 | 前端界面（对话、直播、管理、虚拟形象） |

---

详细内容请查看 [FEATURES.md](FEATURES.md)
