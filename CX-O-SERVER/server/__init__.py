"""
server — CX-O 后端服务包（FastAPI + WebSocket）。

分层架构概览（自外向内）：

- api/             FastAPI HTTP 层：app.py 组装应用、routers/ 下 19 个业务路由、
                   middleware/ 中间件、exceptions/response 统一异常与响应。
- handlers/        WebSocket 消息处理器（chat/audio/config/memory/tools/acp/mcp 等）。
- core/            核心业务域：
    chat/          流式聊天状态机与工具调用循环（单入口 core/chat/stream.py）。
    acp/           Agent Chat Protocol v3.1：manager/discover/group。
    memory/        记忆管理（向量存储、衰减、归档、混合检索）。
    context/       会话上下文管理（manager/agent_context_manager/summarizer）。
    session/       会话存储与清理。
    alarm/         定时提醒单例（数据落盘 data/alarms.db）。
    cxfc/          CXFC 技能注册与发现。
    tools/         工具注册中心 registry 与内置工具集 builtin。
    decision/      管理 Agent 决策核心（6 决策点）。
    distillation/  蒸馏服务（9 状态机 + 9 API 端点）。
    multimodal/    多模态管线（4 workers）。
    graph/         知识图谱（SQLite 图存储 + 语义检索）。
    llm/           LLM 客户端抽象。
    template_engine/  Jinja2 模板引擎。
    websocket/     WS 连接管理。
- services/        打断/语音/情感等横切服务（interrupt_llm 为打断模块公共基类）。
- protocol/        WS 协议：message.py 消息结构、actions.py action 枚举。
- gateway/         gateway 服务（health/server）。
- storage/         数据库连接与迁移。
- config.py        统一配置入口（Pydantic，config.json + CXO_ 环境变量覆盖）。
- prompt_builder.py 提示词组装**单一入口**（build_messages）。
- chat_helpers.py   聊天跨模块共享规范（get_agent_config/get_llm_client_for_agent/get_tools_for_agent）。
- dependencies.py   服务依赖注入与单例获取。
- main.py           进程入口。

收敛约束：所有聊天入口（HTTP /chat、WS chat handler、ACP 自动回复）必须经
prompt_builder.build_messages 组装消息、经 chat_helpers.get_tools_for_agent 收集工具；
流式管线统一走 core/chat/stream.py。新增聊天相关实现不得绕过上述单入口。
"""