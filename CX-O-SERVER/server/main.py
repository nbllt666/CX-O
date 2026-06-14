"""
CX-O-SERVER 统一入口
整合 Gateway + Backend + ASR + TTS 为单体服务
"""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from server.config import get_settings
from server.dependencies import ServiceState, set_service_state
from server.core.graph import GraphDatabase
from server.core.graph.config import get_graph_config
from server.core.lifecycle import init_service, shutdown_service

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger.info("正在启动CX-O服务...")

    services = ServiceState()
    app.state.services = services
    set_service_state(services)

    from server.core.logging_config import LogContext, get_contextual_logger, setup_logging

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
        structured=False,
        console_colors=True,
    )

    lifespan_logger = get_contextual_logger(__name__)

    from server.core.acp.manager import ACPManager
    from server.core.context.manager import ContextManager
    from server.core.llm.client import LLMFactory
    from server.core.memory.decay_batch import DecayBatchProcessor
    from server.core.memory.manager import MemoryManager
    from server.core.memory.async_manager import AsyncMemoryManager
    from server.core.memory.secondary_router import SecondaryModelRouter
    from server.core.model_router import model_router as mr
    from server.core.tools.mcp import MCPManager
    from server.core.tools.registry import tool_registry

    db_config = settings.config.database

    async def _init_model_router():
        services.model_router = mr
        await services.model_router.initialize()
        return services.model_router

    services.model_router = await init_service("模型路由器", _init_model_router, logger_=lifespan_logger)

    services.memory_manager = await init_service(
        "记忆管理器", lambda: MemoryManager(db_path=db_config.memories_db), logger_=lifespan_logger
    )

    async def _init_async_memory_manager():
        mgr = AsyncMemoryManager(db_path=db_config.memories_db)
        await mgr.initialize()
        return mgr

    services.async_memory_manager = await init_service("异步记忆管理器", _init_async_memory_manager, logger_=lifespan_logger)

    services.context_manager = await init_service(
        "上下文管理器", lambda: ContextManager(db_path=db_config.sessions_db), logger_=lifespan_logger
    )

    async def _init_acp_manager():
        mgr = ACPManager(data_dir=db_config.acp_db)
        mgr.initialize(
            agent_id=settings.config.acp.agent_id, agent_name=settings.config.acp.agent_name
        )
        await mgr.start()
        return mgr

    services.acp_manager = await init_service("ACP管理器", _init_acp_manager, logger_=lifespan_logger)

    def _init_llm_client():
        if services.model_router:
            client = services.model_router.get_client("main")
            if client:
                return client
        return LLMFactory.create_client(
            provider=settings.config.llm.provider,
            host=settings.config.llm.host,
            model=settings.config.llm.model,
            temperature=settings.config.llm.temperature,
            max_tokens=settings.config.llm.max_tokens,
        )

    services.llm_client = await init_service("LLM客户端", _init_llm_client, logger_=lifespan_logger)

    if services.memory_manager:
        services.secondary_router = await init_service(
            "副模型路由器",
            lambda: SecondaryModelRouter(
                services.memory_manager,
                services.llm_client,
                model_router=services.model_router,
                context_manager=services.context_manager,
            ),
            logger_=lifespan_logger,
        )

    def _init_mcp_manager():
        mgr = MCPManager()
        mgr.set_tool_registry(tool_registry)
        return mgr

    services.mcp_manager = await init_service("MCP管理器", _init_mcp_manager, logger_=lifespan_logger)

    def _init_graph_database():
        graph_config = get_graph_config()
        graph_db = GraphDatabase(config=graph_config)
        graph_db.initialize()
        return graph_db

    services.graph_database = await init_service("图数据库", _init_graph_database, logger_=lifespan_logger)

    if services.graph_database:
        def _init_graph_store():
            from server.core.memory.graph_store import SQLiteGraphStore
            return SQLiteGraphStore(services.graph_database)

        services.graph_store = await init_service("图存储桥接", _init_graph_store, logger_=lifespan_logger)

    if services.graph_store:
        def _register_graph_tools():
            from server.core.tools.graph_tools import set_graph_dependencies, register_graph_tools
            set_graph_dependencies(services.graph_store)
            register_graph_tools()

        await init_service("图工具", _register_graph_tools, logger_=lifespan_logger)

    def _register_builtin():
        from server.core.tools import register_builtin_tools
        register_builtin_tools()

    await init_service("内置工具", _register_builtin, logger_=lifespan_logger)

    def _register_master():
        from server.core.tools import register_master_tools, set_master_dependencies
        set_master_dependencies(
            memory_manager=services.memory_manager,
            secondary_router=services.secondary_router,
            context_manager=services.context_manager,
            acp_manager=services.acp_manager,
        )
        register_master_tools()

    master_tools_registered = await init_service("主模型工具", _register_master, logger_=lifespan_logger) is not None

    def _register_summary():
        from server.core.tools import register_summary_tools, set_summary_dependencies
        set_summary_dependencies(
            memory_manager=services.memory_manager,
            model_router=services.model_router,
            context_manager=services.context_manager,
        )
        register_summary_tools()

    summary_tools_registered = await init_service("摘要模型工具", _register_summary, logger_=lifespan_logger) is not None

    def _register_assistant():
        from server.core.tools import register_assistant_tools, set_assistant_dependencies
        set_assistant_dependencies(
            memory_manager=services.memory_manager,
            secondary_router=services.secondary_router,
            context_manager=services.context_manager,
        )
        register_assistant_tools()

    assistant_tools_registered = await init_service("记忆管理模型工具", _register_assistant, logger_=lifespan_logger) is not None

    from server.core.tools import tool_registry
    tools_stats = tool_registry.get_tool_stats()
    lifespan_logger.info(
        f"工具注册统计: 总计{tools_stats['total_tools']}个, "
        f"启用{tools_stats['enabled_tools']}个, "
        f"禁用{tools_stats['disabled_tools']}个"
    )

    if not (master_tools_registered and summary_tools_registered and assistant_tools_registered):
        lifespan_logger.warning("部分工具注册失败，系统可能无法正常工作")

    if services.memory_manager and services.llm_client and settings.config.memory.vector_enabled:
        async def _init_vector_search():
            vector_backend = settings.config.memory.vector_backend
            if vector_backend == "weaviate":
                services.memory_manager.enable_vector_search(
                    embedding_model=services.llm_client,
                    vector_backend="weaviate",
                    weaviate_host=settings.config.memory.weaviate.host,
                    weaviate_port=settings.config.memory.weaviate.port,
                    weaviate_grpc_port=settings.config.memory.weaviate.grpc_port,
                    vector_size=settings.config.memory.weaviate.vector_size,
                )
            elif vector_backend == "weaviate_embedded":
                services.memory_manager.enable_vector_search(
                    embedding_model=services.llm_client,
                    vector_backend="weaviate_embedded",
                    vector_size=settings.config.memory.weaviate.vector_size,
                )
            else:
                raise ValueError(f"不支持的向量存储后端: {vector_backend}，仅支持 weaviate 和 weaviate_embedded")
            lifespan_logger.info(f"向量搜索已启用: {vector_backend}")

            if services.memory_manager.is_vector_search_enabled():
                sync_result = await services.memory_manager._vector_store.sync_with_sqlite(
                    services.memory_manager, last_sync_time=services.memory_manager._last_sync_time
                )
                services.memory_manager._last_sync_time = datetime.now().isoformat()
                lifespan_logger.info(
                    f"启动时向量同步完成: checked={sync_result.total_checked}, synced={sync_result.synced}, errors={sync_result.errors}"
                )

        await init_service("向量搜索", _init_vector_search, logger_=lifespan_logger)

    async def _init_alarm_and_ws():
        from server.core.alarm import get_alarm_manager
        from server.core.websocket.handlers import push_alarm_to_agent
        from server.core.websocket.manager import get_websocket_manager

        alarm_manager = get_alarm_manager()
        main_loop = asyncio.get_running_loop()

        def on_alarm_trigger(agent_id: str, message: str):
            try:
                future = asyncio.run_coroutine_threadsafe(
                    push_alarm_to_agent(agent_id, message), main_loop
                )
                future.result(timeout=5)
            except Exception as e:
                logging.getLogger(__name__).error(f"推送提醒失败: {e}")

        alarm_manager.set_trigger_callback(on_alarm_trigger)
        # BUG-B06 修复: 在事件循环中通过 async 版本调用,避免同步 sqlite 阻塞
        await alarm_manager.arestore_pending_alarms()
        lifespan_logger.info("提醒管理器已启动")

        async def on_offline(agent_id: str):
            try:
                session_id = f"agent-{agent_id}"
                cm = services.context_manager

                if not cm:
                    return

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

                mm = services.memory_manager
                if mm:
                    mm.write_memory(
                        content=summary_content,
                        memory_type="long_term",
                        importance=2,
                        tags=["offline_save", "context", agent_id],
                    )

                for msg in messages_to_archive:
                    cm.delete_message(msg.get("id"))

                lifespan_logger.info(
                    f"离线保存上下文成功: agent={agent_id}, 归档 {len(messages_to_archive)} 条消息"
                )
            except Exception as e:
                lifespan_logger.error(f"离线保存上下文失败: {e}")

        ws_manager = get_websocket_manager()
        ws_manager.set_offline_callback(on_offline)
        await ws_manager.start_cleanup_task(interval_seconds=30)
        lifespan_logger.info("WebSocket 离线保存已启用")

    await init_service("提醒管理器", _init_alarm_and_ws, logger_=lifespan_logger)

    if services.memory_manager:
        async def _init_decay_batch():
            processor = DecayBatchProcessor(services.memory_manager, interval_hours=24)
            await processor.start()
            return processor

        services.decay_batch_processor = await init_service("批量衰减处理器", _init_decay_batch, logger_=lifespan_logger)

    async def _init_cxfc():
        from server.core.cxfc.manager import CXFCManager
        from server.core.cxfc.discovery import CXFCDiscovery

        cxfc_config = getattr(settings, 'cxfc', None)
        if not cxfc_config or not getattr(cxfc_config, 'enabled', True):
            return None

        cxfc_manager = CXFCManager(
            storage_path=getattr(cxfc_config, 'storage_path', 'data/cxfc_plugins.db'),
            heartbeat_timeout=getattr(cxfc_config, 'heartbeat_timeout', 30),
            heartbeat_check_interval=getattr(cxfc_config, 'heartbeat_check_interval', 10),
        )

        if hasattr(services, 'tool_registry') and services.tool_registry:
            cxfc_manager.set_tool_registry(services.tool_registry)

        await cxfc_manager.start()

        from server.core.websocket.manager import get_websocket_manager
        ws_mgr = get_websocket_manager()
        cxfc_manager.set_ws_manager(ws_mgr)

        async def on_cxfc_event(skill, event):
            try:
                if ws_mgr:
                    await ws_mgr.broadcast({
                        "type": "skill_triggered",
                        "data": {
                            "skill_name": skill.name,
                            "skill_description": skill.description,
                            "event_type": event.event_type,
                            "source_plugin": skill.source_plugin_id,
                            "prompt_template": skill.prompt_template,
                        },
                    })
            except Exception as e:
                lifespan_logger.warning(f"广播 Skill 触发事件失败: {e}")

        cxfc_manager.set_on_event_callback(on_cxfc_event)

        if getattr(cxfc_config, 'discovery_enabled', True):
            cxfc_discovery = CXFCDiscovery(
                broadcast_port=getattr(cxfc_config, 'broadcast_port', 9997),
                discovery_port=getattr(cxfc_config, 'discovery_port', 9996),
            )
            await cxfc_discovery.start_discovery(
                local_name="CX-O",
                local_port=getattr(settings, 'system', None) and getattr(settings.system, 'port', 8000) or 8000,
                capabilities=["chat", "memory", "tools", "asr", "tts"],
            )
            services.cxfc_discovery = cxfc_discovery

        return cxfc_manager

    services.cxfc_manager = await init_service("CXFC管理器", _init_cxfc, logger_=lifespan_logger)

    from server.services.asr_service import get_asr_service
    from server.services.tts_service import get_tts_service
    from server.gateway.health import health_checker

    app.state.asr_status = "uninitialized"
    app.state.tts_status = "uninitialized"
    app.state.asr_error = None
    app.state.tts_error = None

    asr_mode = getattr(settings, 'asr', None) and getattr(settings.asr, 'mode', 'remote')
    tts_mode = getattr(settings, 'tts', None) and getattr(settings.tts, 'mode', 'remote')

    if asr_mode == "embedded":
        try:
            asr_service = get_asr_service()
            await asr_service.initialize()
            services.asr_service = asr_service
            app.state.asr_status = "healthy"
            health_checker.update_status("asr", "healthy")
            lifespan_logger.info("Embedded ASR (SenseVoice) initialized successfully")
        except Exception as e:
            error_msg = f"Failed to initialize embedded ASR: {e}"
            lifespan_logger.error(error_msg)
            app.state.asr_status = "error"
            app.state.asr_error = str(e)
            health_checker.update_status("asr", "unhealthy", error=str(e))

            try:
                lifespan_logger.info("Attempting to fallback to remote ASR mode...")
                asr_service = get_asr_service()
                asr_service._mode = "remote"
                asr_service._initialized = True
                services.asr_service = asr_service
                app.state.asr_status = "degraded"
                health_checker.update_status("asr", "degraded", error="Fallback to remote mode")
                lifespan_logger.warning("ASR service degraded: using remote mode as fallback")
            except Exception as fallback_error:
                lifespan_logger.error(f"ASR fallback to remote mode failed: {fallback_error}")
                app.state.asr_status = "unavailable"
                health_checker.update_status("asr", "unavailable", error=str(fallback_error))
    else:
        try:
            asr_service = get_asr_service()
            services.asr_service = asr_service
        except Exception:
            logger.warning("初始化ASR远程模式服务失败，回退到空实例", exc_info=True)
        app.state.asr_status = "remote"
        health_checker.update_status("asr", "remote")

    if tts_mode == "embedded":
        try:
            tts_service = get_tts_service()
            await tts_service.initialize()
            services.tts_service = tts_service
            app.state.tts_status = "healthy"
            health_checker.update_status("tts", "healthy")
            lifespan_logger.info("Embedded TTS (F5-TTS) initialized successfully")
        except Exception as e:
            error_msg = f"Failed to initialize embedded TTS: {e}"
            lifespan_logger.error(error_msg)
            app.state.tts_status = "error"
            app.state.tts_error = str(e)
            health_checker.update_status("tts", "unhealthy", error=str(e))

            try:
                lifespan_logger.info("Attempting to fallback to remote TTS mode...")
                tts_service = get_tts_service()
                tts_service._mode = "remote"
                tts_service._initialized = True
                services.tts_service = tts_service
                app.state.tts_status = "degraded"
                health_checker.update_status("tts", "degraded", error="Fallback to remote mode")
                lifespan_logger.warning("TTS service degraded: using remote mode as fallback")
            except Exception as fallback_error:
                lifespan_logger.error(f"TTS fallback to remote mode failed: {fallback_error}")
                app.state.tts_status = "unavailable"
                health_checker.update_status("tts", "unavailable", error=str(fallback_error))
    else:
        try:
            tts_service = get_tts_service()
            services.tts_service = tts_service
        except Exception:
            logger.warning("初始化TTS远程模式服务失败，回退到空实例", exc_info=True)
        app.state.tts_status = "remote"
        health_checker.update_status("tts", "remote")

    lifespan_logger.info(f"CX-O-SERVER started successfully (ASR: {app.state.asr_status}, TTS: {app.state.tts_status})")

    yield

    lifespan_logger.info("正在关闭CX-O服务...")

    if hasattr(services, 'cxfc_manager') and services.cxfc_manager:
        await shutdown_service("CXFC管理器", services.cxfc_manager.shutdown, logger_=lifespan_logger)
    if hasattr(services, 'cxfc_discovery') and services.cxfc_discovery:
        await shutdown_service("CXFC发现服务", services.cxfc_discovery.stop_discovery, logger_=lifespan_logger)

    if services.graph_database:
        await shutdown_service("图数据库", services.graph_database.close, logger_=lifespan_logger)

    async def _shutdown_alarm():
        from server.core.alarm import get_alarm_manager
        get_alarm_manager().shutdown()

    await shutdown_service("AlarmManager", _shutdown_alarm, logger_=lifespan_logger)

    async def _shutdown_ws_cleanup():
        from server.core.websocket.manager import get_websocket_manager
        await get_websocket_manager().stop_cleanup_task()

    await shutdown_service("WebSocket管理器cleanup任务", _shutdown_ws_cleanup, logger_=lifespan_logger)

    if services.decay_batch_processor:
        await shutdown_service("批量衰减处理器", services.decay_batch_processor.stop, logger_=lifespan_logger)

    if services.acp_manager:
        await shutdown_service("ACP管理器", services.acp_manager.stop, logger_=lifespan_logger)

    if services.memory_manager:
        await shutdown_service("记忆管理器", services.memory_manager.shutdown, logger_=lifespan_logger)

    if services.async_memory_manager:
        await shutdown_service("异步记忆管理器", services.async_memory_manager.close, logger_=lifespan_logger)

    async def _shutdown_backup():
        from server.core.backup.manager import get_backup_manager
        get_backup_manager().shutdown()

    await shutdown_service("BackupManager", _shutdown_backup, logger_=lifespan_logger)

    async def _shutdown_plugins():
        from server.core.plugins.manager import get_plugin_manager
        await get_plugin_manager().shutdown()

    await shutdown_service("PluginManager", _shutdown_plugins, logger_=lifespan_logger)

    if services.model_router:
        await shutdown_service("模型路由器", services.model_router.close, logger_=lifespan_logger)

    asr_service = get_asr_service()
    await shutdown_service("ASR服务", asr_service.shutdown, logger_=lifespan_logger)

    tts_service = get_tts_service()
    await shutdown_service("TTS服务", tts_service.shutdown, logger_=lifespan_logger)

    async def _close_http_client():
        from server.core.utils import close_shared_http_client
        await close_shared_http_client()

    await shutdown_service("共享HTTP客户端", _close_http_client, logger_=lifespan_logger)

    lifespan_logger.info("CX-O服务已关闭")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="CX-O-SERVER",
        description="CX-O 统一服务端 - Gateway + Backend + ASR + TTS",
        version="1.0.0",
        lifespan=lifespan,
    )

    cors_config = getattr(settings, 'cors', None)
    cors_enabled = getattr(cors_config, 'enabled', True) if cors_config else True
    if cors_enabled:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=getattr(cors_config, 'origins', ['*']) if cors_config else ['*'],
            allow_credentials=getattr(cors_config, 'allow_credentials', True) if cors_config else True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    from server.api.app import register_api_routes
    register_api_routes(app)

    from server.gateway.server import register_gateway_routes
    register_gateway_routes(app)

    return app


app = create_app()


def main():
    settings = get_settings()
    host = getattr(settings.system, 'host', '0.0.0.0')
    port = getattr(settings.system, 'port', 8000)
    log_level = getattr(settings.system, 'log_level', 'info').lower()

    uvicorn.run(
        "server.main:app",
        host=host,
        port=port,
        log_level=log_level,
        reload=False,
    )


if __name__ == "__main__":
    main()
