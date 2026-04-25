import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket # type: ignore
from fastapi.exceptions import RequestValidationError # type: ignore
from fastapi.middleware.cors import CORSMiddleware # type: ignore
from fastapi.responses import JSONResponse # type: ignore

from backend.api.exceptions import (
    CXHMSError,
    cxhms_exception_handler,
    generic_exception_handler,
    http_exception_handler,
    validation_exception_handler,
)
from backend.api.middleware.performance import PerformanceMiddleware
from backend.api.response import APIResponse, HealthResponse
from backend.api.routers import (
    acp,
    admin,
    agents,
    archive,
    audio,
    backup,
    chat,
    config,
    context,
    graph,
    memory,
    memory_chat,
    service,
    stats,
    tools,
    vector,
    websocket,
)
from backend.core.websocket import get_websocket_manager, get_chat_handler
from backend.core.logging_config import LogContext, get_contextual_logger, setup_logging
from config.settings import settings

# 配置结构化日志
log_file_config = getattr(settings.config, "logging", {})
log_file = (
    log_file_config.get("file", "logs/app.log")
    if isinstance(log_file_config, dict)
    else "logs/app.log"
)

setup_logging(
    level=settings.config.system.log_level,
    log_file=log_file,
    max_bytes=(
        log_file_config.get("max_bytes", 10 * 1024 * 1024)
        if isinstance(log_file_config, dict)
        else 10 * 1024 * 1024
    ),
    backup_count=log_file_config.get("backup_count", 5) if isinstance(log_file_config, dict) else 5,
    structured=False,  # 可以设置为 True 启用 JSON 格式日志
    console_colors=True,
)

logger = get_contextual_logger(__name__)

memory_manager = None
async_memory_manager = None
context_manager = None
acp_manager = None
llm_client = None
secondary_router = None
decay_batch_processor = None
mcp_manager = None
model_router = None  # 新增：模型路由器


@asynccontextmanager
async def lifespan(app: FastAPI):
    global memory_manager, async_memory_manager, context_manager, acp_manager, llm_client, secondary_router, decay_batch_processor, mcp_manager, model_router

    from backend.core.acp.manager import ACPManager
    from backend.core.context.manager import ContextManager
    from backend.core.llm.client import LLMFactory
    from backend.core.memory.decay_batch import DecayBatchProcessor
    from backend.core.memory.manager import MemoryManager
    from backend.core.memory.async_manager import AsyncMemoryManager
    from backend.core.memory.secondary_router import SecondaryModelRouter
    from backend.core.model_router import model_router as mr  # 导入模型路由器
    from backend.core.tools.mcp import MCPManager
    from backend.core.tools.registry import tool_registry

    logger.info("正在启动CXHMS服务...")

    db_config = settings.config.database

    # 1. 初始化模型路由器（最先初始化，其他组件可能依赖它）
    try:
        model_router = mr
        await model_router.initialize()
        logger.info("模型路由器已启动")
    except Exception as e:
        logger.warning(f"模型路由器启动失败: {e}")
        model_router = None

    try:
        memory_manager = MemoryManager(db_path=db_config.memories_db)
        logger.info("记忆管理器已启动")
    except Exception as e:
        logger.warning(f"记忆管理器启动失败: {e}")
        memory_manager = None

    try:
        async_memory_manager = AsyncMemoryManager(db_path=db_config.memories_db)
        await async_memory_manager.initialize()
        logger.info("异步记忆管理器已启动")
    except Exception as e:
        logger.warning(f"异步记忆管理器启动失败: {e}")
        async_memory_manager = None

    try:
        context_manager = ContextManager(db_path=db_config.sessions_db)
        logger.info("上下文管理器已启动")
    except Exception as e:
        logger.warning(f"上下文管理器启动失败: {e}")
        context_manager = None

    try:
        acp_manager = ACPManager(data_dir=db_config.acp_db)
        acp_manager.initialize(
            agent_id=settings.config.acp.agent_id, agent_name=settings.config.acp.agent_name
        )
        await acp_manager.start()
        logger.info("ACP管理器已启动")
    except Exception as e:
        logger.warning(f"ACP管理器启动失败: {e}")
        acp_manager = None

    # 使用模型路由器的主模型客户端作为默认LLM客户端（向后兼容）
    try:
        if model_router:
            llm_client = model_router.get_client("main")
            logger.info(f"LLM客户端已启动: {llm_client.model_name if llm_client else 'None'}")
        else:
            # 回退到旧方式
            llm_client = LLMFactory.create_client(
                provider=settings.config.llm.provider,
                host=settings.config.llm.host,
                model=settings.config.llm.model,
                temperature=settings.config.llm.temperature,
                max_tokens=settings.config.llm.max_tokens,
            )
            logger.info(f"LLM客户端已启动(回退模式): {llm_client.model_name}")
    except Exception as e:
        logger.warning(f"LLM客户端启动失败: {e}")
        llm_client = None

    try:
        if memory_manager:
            secondary_router = SecondaryModelRouter(
                memory_manager,
                llm_client,
                model_router=model_router,
                context_manager=context_manager,
            )
            logger.info("副模型路由器已启动")
    except Exception as e:
        logger.warning(f"副模型路由器启动失败: {e}")
        secondary_router = None

    try:
        mcp_manager = MCPManager()
        mcp_manager.set_tool_registry(tool_registry)
        logger.info("MCP管理器已启动")
    except Exception as e:
        logger.warning(f"MCP管理器启动失败: {e}")
        mcp_manager = None

    # 注册内置工具
    try:
        from backend.core.tools import register_builtin_tools

        register_builtin_tools()
        logger.info("内置工具已注册")
    except Exception as e:
        logger.warning(f"内置工具注册失败: {e}")

    # 注册主模型工具
    master_tools_registered = False
    try:
        from backend.core.tools import register_master_tools, set_master_dependencies

        set_master_dependencies(
            memory_manager=memory_manager,
            secondary_router=secondary_router,
            context_manager=context_manager,
            acp_manager=acp_manager,
        )
        register_master_tools()
        master_tools_registered = True
        logger.info("主模型工具已注册")
    except Exception as e:
        logger.warning(f"主模型工具注册失败: {e}")

    # 注册摘要模型工具
    summary_tools_registered = False
    try:
        from backend.core.tools import register_summary_tools, set_summary_dependencies

        set_summary_dependencies(
            memory_manager=memory_manager,
            model_router=model_router,
            context_manager=context_manager,
        )
        register_summary_tools()
        summary_tools_registered = True
        logger.info("摘要模型工具已注册")
    except Exception as e:
        logger.warning(f"摘要模型工具注册失败: {e}")

    # 注册记忆管理模型工具
    assistant_tools_registered = False
    try:
        from backend.core.tools import register_assistant_tools, set_assistant_dependencies

        set_assistant_dependencies(
            memory_manager=memory_manager,
            secondary_router=secondary_router,
            context_manager=context_manager,
        )
        register_assistant_tools()
        assistant_tools_registered = True
        logger.info("记忆管理模型工具已注册")
    except Exception as e:
        logger.warning(f"记忆管理模型工具注册失败: {e}")

    # 验证工具注册状态
    from backend.core.tools import tool_registry

    tools_stats = tool_registry.get_tool_stats()
    logger.info(
        f"工具注册统计: 总计{tools_stats['total_tools']}个, "
        f"启用{tools_stats['enabled_tools']}个, "
        f"禁用{tools_stats['disabled_tools']}个"
    )

    if not (master_tools_registered and summary_tools_registered and assistant_tools_registered):
        logger.warning("部分工具注册失败，系统可能无法正常工作")

    try:
        if memory_manager and llm_client and settings.config.memory.vector_enabled:
            vector_backend = settings.config.memory.vector_backend
            if vector_backend == "weaviate":
                memory_manager.enable_vector_search(
                    embedding_model=llm_client,
                    vector_backend="weaviate",
                    weaviate_host=settings.config.memory.weaviate.host,
                    weaviate_port=settings.config.memory.weaviate.port,
                    weaviate_grpc_port=settings.config.memory.weaviate.grpc_port,
                    vector_size=settings.config.memory.weaviate.vector_size,
                )
            elif vector_backend == "weaviate_embedded":
                memory_manager.enable_vector_search(
                    embedding_model=llm_client,
                    vector_backend="weaviate_embedded",
                    vector_size=settings.config.memory.weaviate.vector_size,
                )
            else:
                logger.warning(f"不支持的向量存储后端: {vector_backend}，仅支持 weaviate 和 weaviate_embedded")
            logger.info(f"向量搜索已启用: {vector_backend}")

            if memory_manager.is_vector_search_enabled():
                try:
                    sync_result = await memory_manager._vector_store.sync_with_sqlite(
                        memory_manager, last_sync_time=memory_manager._last_sync_time
                    )
                    memory_manager._last_sync_time = datetime.now().isoformat()
                    logger.info(
                        f"启动时向量同步完成: checked={sync_result.total_checked}, synced={sync_result.synced}, errors={sync_result.errors}"
                    )
                except Exception as e:
                    logger.warning(f"启动时向量同步失败: {e}")
    except Exception as e:
        logger.warning(f"向量搜索启动失败: {e}")

    try:
        from backend.core.alarm import get_alarm_manager
        from backend.core.websocket.handlers import push_alarm_to_agent
        from backend.core.websocket.manager import get_websocket_manager

        alarm_manager = get_alarm_manager()
        main_loop = asyncio.get_running_loop()

        def on_alarm_trigger(agent_id: str, message: str):
            try:
                future = asyncio.run_coroutine_threadsafe(
                    push_alarm_to_agent(agent_id, message), main_loop
                )
                future.result(timeout=5)
            except Exception as e:
                import logging

                logging.getLogger(__name__).error(f"推送提醒失败: {e}")

        alarm_manager.set_trigger_callback(on_alarm_trigger)
        alarm_manager.restore_pending_alarms()
        logger.info("提醒管理器已启动")

        async def on_offline(agent_id: str):
            """离线时保存上下文到长期记忆，并清理旧消息"""
            try:
                session_id = f"agent-{agent_id}"
                cm = get_context_manager()

                all_messages = cm.get_messages(session_id, limit=1000)

                if not all_messages or len(all_messages) <= 10:
                    return

                messages_to_archive = all_messages[:-10]
                context_text = "\n".join(
                    [
                        f"{msg.get('role', 'unknown')}: {msg.get('content', '')}"
                        for msg in messages_to_archive
                    ]
                )

                summary_content = f"[离线自动保存] Agent {agent_id} 的对话上下文摘要:\n\n"
                if len(context_text) > 1000:
                    summary_content += context_text[:1000] + "..."
                else:
                    summary_content += context_text

                mm = get_memory_manager()
                if mm:
                    mm.write_memory(
                        content=summary_content,
                        memory_type="long_term",
                        importance=2,
                        tags=["offline_save", "context", agent_id],
                    )

                for msg in messages_to_archive:
                    cm.delete_message(msg.get("id"))

                logger.info(
                    f"离线保存上下文成功: agent={agent_id}, 归档 {len(messages_to_archive)} 条消息"
                )
            except Exception as e:
                logger.error(f"离线保存上下文失败: {e}")

        ws_manager = get_websocket_manager()
        ws_manager.set_offline_callback(on_offline)
        await ws_manager.start_cleanup_task(interval_seconds=30)
        logger.info("WebSocket 离线保存已启用")
    except Exception as e:
        logger.warning(f"提醒管理器启动失败: {e}")

    try:
        if memory_manager:
            decay_batch_processor = DecayBatchProcessor(memory_manager, interval_hours=24)
            await decay_batch_processor.start()
            logger.info("批量衰减处理器已启动")
    except Exception as e:
        logger.warning(f"批量衰减处理器启动失败: {e}")
        decay_batch_processor = None

    yield

    logger.info("正在关闭CXHMS服务...")

    try:
        from backend.core.alarm import get_alarm_manager

        alarm_mgr = get_alarm_manager()
        alarm_mgr.shutdown()
    except Exception:
        pass

    try:
        from backend.core.websocket.manager import get_websocket_manager

        ws_mgr = get_websocket_manager()
        await ws_mgr.stop_cleanup_task()
    except Exception:
        pass

    if decay_batch_processor:
        await decay_batch_processor.stop()

    if acp_manager:
        await acp_manager.stop()

    if memory_manager:
        memory_manager.shutdown()

    if async_memory_manager:
        try:
            await async_memory_manager.close()
        except Exception:
            pass

    # 关闭备份管理器
    try:
        from backend.core.backup.manager import get_backup_manager

        backup_mgr = get_backup_manager()
        backup_mgr.shutdown()
    except Exception:
        pass

    # 关闭插件管理器
    try:
        from backend.core.plugins.manager import get_plugin_manager

        plugin_mgr = get_plugin_manager()
        await plugin_mgr.shutdown()
    except Exception:
        pass

    # 关闭模型路由器
    if model_router:
        await model_router.close()

    logger.info("CXHMS服务已关闭")


app = FastAPI(
    title="CXHMS - CX-O History & Memory Service",
    description="AI代理中间层服务，提供记忆管理、工具调用、ACP互联等功能",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(PerformanceMiddleware)

if getattr(settings.config, "cors", None) and settings.config.cors.enabled:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.config.cors.origins,
        allow_credentials=settings.config.cors.allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(chat.router, prefix="/api")
app.include_router(config.router, prefix="/api")
app.include_router(memory.router, prefix="/api")
app.include_router(memory_chat.router, prefix="/api")
app.include_router(context.router, prefix="/api")
app.include_router(tools.router, prefix="/api")
app.include_router(acp.router, prefix="/api")
app.include_router(service.router, prefix="/api")
app.include_router(stats.router, prefix="/api")
app.include_router(websocket.router, prefix="/api")
app.include_router(graph.router, prefix="/api")
app.include_router(agents.router, prefix="/api")
app.include_router(archive.router, prefix="/api")
app.include_router(audio.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(backup.router, prefix="/api")
app.include_router(vector.router, prefix="/api")

app.add_exception_handler(CXHMSError, cxhms_exception_handler)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, generic_exception_handler)


@app.get("/health", response_model=HealthResponse)
async def health_check():
    components = {
        "memory_manager": memory_manager is not None,
        "context_manager": context_manager is not None,
        "acp_manager": acp_manager is not None,
        "llm_client": llm_client is not None,
        "model_router": model_router is not None,
    }
    return HealthResponse(
        status="healthy" if all(components.values()) else "degraded",
        version="1.0.0",
        components=components,
    )


@app.get("/")
async def root():
    return {
        "service": "CXHMS",
        "version": "1.0.0",
        "description": "CX-O History & Memory Service",
        "docs": "/docs",
        "redoc": "/redoc",
    }


def get_memory_manager():
    if memory_manager is None:
        raise HTTPException(status_code=503, detail="记忆服务不可用")
    return memory_manager


def get_async_memory_manager():
    if async_memory_manager is None:
        raise HTTPException(status_code=503, detail="异步记忆服务不可用")
    return async_memory_manager


def get_context_manager():
    if context_manager is None:
        raise HTTPException(status_code=503, detail="上下文服务不可用")
    return context_manager


def get_acp_manager():
    if acp_manager is None:
        raise HTTPException(status_code=503, detail="ACP服务不可用")
    return acp_manager


def get_llm_client():
    if llm_client is None:
        raise HTTPException(status_code=503, detail="LLM服务不可用")
    return llm_client


def get_secondary_router():
    if secondary_router is None:
        raise HTTPException(status_code=503, detail="副模型路由器不可用")
    return secondary_router


def get_decay_batch_processor():
    if decay_batch_processor is None:
        raise HTTPException(status_code=503, detail="批量衰减处理器不可用")
    return decay_batch_processor


def get_mcp_manager():
    if mcp_manager is None:
        raise HTTPException(status_code=503, detail="MCP管理器不可用")
    return mcp_manager


def get_model_router():
    if model_router is None:
        raise HTTPException(status_code=503, detail="模型路由器不可用")
    return model_router
