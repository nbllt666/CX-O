"""
CX-O-SERVER 统一入口
整合 Gateway + Backend + ASR + TTS 为单体服务
"""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# ============================================================================
# httpx Windows 代理性能补丁（必须在任何 httpx 导入前执行）
# ============================================================================
# 问题：httpx 0.28.1 在 Windows 上默认读取系统代理（IE 注册表），
#   对 127.0.0.1 请求会走代理返回 502 且耗时 23s；
#   单独 trust_env=False 仍耗时 7.8s（httpx 内部代理检测残留）；
#   必须 trust_env=False + proxy=None 同时设置才能降到 14ms（与 requests 一致）。
# 修复：monkey-patch httpx.AsyncClient.__init__，强制注入两个参数。
# 影响：所有 httpx.AsyncClient 调用（model_router/llm/client/tts_service 等）
#   自动获得正确配置，无需逐处修改 13+ 处调用点。
# 验证：requests 35ms / httpx patched 14ms / httpx 默认 23553ms(502)
import httpx as _httpx_patch_target

_orig_async_client_init = _httpx_patch_target.AsyncClient.__init__


def _patched_async_client_init(self, *args, **kwargs):
    # 强制禁用 Windows 系统代理检测，仅对本地回环和内网服务有意义
    kwargs.setdefault("trust_env", False)
    # httpx 0.28+ 用 proxy（单数），旧版用 proxies（复数）
    if "proxy" not in kwargs and "proxies" not in kwargs:
        kwargs["proxy"] = None
    return _orig_async_client_init(self, *args, **kwargs)


_httpx_patch_target.AsyncClient.__init__ = _patched_async_client_init
# 同步客户端也补丁（httpx.Client）
_orig_client_init = _httpx_patch_target.Client.__init__


def _patched_client_init(self, *args, **kwargs):
    kwargs.setdefault("trust_env", False)
    if "proxy" not in kwargs and "proxies" not in kwargs:
        kwargs["proxy"] = None
    return _orig_client_init(self, *args, **kwargs)


_httpx_patch_target.Client.__init__ = _patched_client_init
# ============================================================================

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from server.config import get_settings
from server.dependencies import ServiceState, set_service_state
from server.core.lifecycle import init_service, shutdown_service

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger.info("正在启动CX-O服务...")

    services = ServiceState()
    app.state.services = services
    set_service_state(services)

    from server.core.logging_config import get_contextual_logger, setup_logging

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

    # DistillationService 初始化（B3 产物，RADIX-Lite 模块9 蒸馏服务）
    # 路由从 app.state.distillation_service 获取实例（见 api/routes.py::_get_service）
    def _init_distillation_service():
        from server.core.distillation.distillation_service import DistillationService
        return DistillationService()

    distillation_service = await init_service(
        "蒸馏服务", _init_distillation_service, logger_=lifespan_logger
    )
    if distillation_service is not None:
        app.state.distillation_service = distillation_service

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

    # 图数据库改为按需创建（lazy init）：
    # - 启动时不预创建 default 数据库文件
    # - graph_tools 内部 _check_graph_store 按需创建 default GraphDatabase + SQLiteGraphStore
    # - API 路由经 dependencies._get_or_create_graph_database 按需创建
    # 详见 .trae/documents/20260720_模块0_图数据库按需创建.md
    def _register_graph_tools():
        # graph_tools 启动时注册工具签名，内部 _check_graph_store 按需初始化 graph_store。
        # 不调用 set_graph_dependencies(None)，让 _check_graph_store 在首次调用时创建实例。
        from server.core.tools.graph_tools import register_graph_tools
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
        return True

    master_tools_registered = await init_service("主模型工具", _register_master, logger_=lifespan_logger) is not None

    def _register_summary():
        from server.core.memory.emotion import set_emotion_llm_client
        from server.core.tools import register_summary_tools, set_summary_dependencies
        set_summary_dependencies(
            memory_manager=services.memory_manager,
            model_router=services.model_router,
            context_manager=services.context_manager,
        )
        # 情感分析统一使用摘要模型
        if services.model_router:
            set_emotion_llm_client(services.model_router.get_client("summary"))
        register_summary_tools()
        return True

    summary_tools_registered = await init_service("摘要模型工具", _register_summary, logger_=lifespan_logger) is not None

    def _register_assistant():
        from server.core.tools import register_assistant_tools, set_assistant_dependencies
        set_assistant_dependencies(
            memory_manager=services.memory_manager,
            secondary_router=services.secondary_router,
            context_manager=services.context_manager,
        )
        register_assistant_tools()
        return True

    assistant_tools_registered = await init_service("记忆管理模型工具", _register_assistant, logger_=lifespan_logger) is not None

    def _register_task_tools():
        from server.core.tools import register_task_tools
        register_task_tools()

    await init_service("任务辅助工具", _register_task_tools, logger_=lifespan_logger)

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
            from server.core.memory import EmbeddingFactory

            embedding_provider = getattr(settings.config.memory, "embedding_provider", "ollama")
            if embedding_provider == "vllm":
                embedding_model = EmbeddingFactory.create(
                    provider="vllm",
                    model=settings.config.memory.embedding_model,
                    api_base=settings.config.memory.embedding_api_base,
                    api_key=settings.config.memory.embedding_api_key or "",
                    dimension=settings.config.memory.weaviate.vector_size,
                )
                lifespan_logger.info(f"使用 vLLM 嵌入模型: {settings.config.memory.embedding_model}")
            else:
                embedding_model = services.llm_client

            vector_backend = settings.config.memory.vector_backend
            if vector_backend == "weaviate":
                services.memory_manager.enable_vector_search(
                    embedding_model=embedding_model,
                    vector_backend="weaviate",
                    weaviate_host=settings.config.memory.weaviate.host,
                    weaviate_port=settings.config.memory.weaviate.port,
                    weaviate_grpc_port=settings.config.memory.weaviate.grpc_port,
                    vector_size=settings.config.memory.weaviate.vector_size,
                )
            elif vector_backend == "weaviate_embedded":
                services.memory_manager.enable_vector_search(
                    embedding_model=embedding_model,
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
                    await mm.write_memory_async(
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

    async def _init_task_services():
        from server.core.tasks import get_task_manager, TaskScheduler

        task_manager = get_task_manager()
        scheduler = TaskScheduler(task_manager, interval_seconds=60)
        await scheduler.start()
        services.task_scheduler = scheduler
        lifespan_logger.info("任务调度服务已启动 (间隔 60s)")
        return scheduler

    services.task_scheduler = await init_service("任务调度服务", _init_task_services, logger_=lifespan_logger)

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

        # 注入到路由模块全局变量（修复 cxfc_manager 未注入 bug，20260719_模块0_CXFC路由注入修复）
        from server.api.routers import cxfc as cxfc_router
        cxfc_router.set_cxfc_manager(cxfc_manager)
        if hasattr(services, 'cxfc_discovery') and services.cxfc_discovery:
            cxfc_router.set_cxfc_discovery(services.cxfc_discovery)

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
            # 远程模式无需加载本地模型，直接标记 _initialized=True
            # 否则 send_audio_chunk 会因 _initialized=False 直接 return False，
            # 导致 vad_processor.AudioStreamProcessor 拿不到 ASR 结果，
            # 双流式 voice.dual_stream 流水线无法启动（WS 端到端测试超时）
            # 与上方 embedded fallback 分支（line 503-506）保持一致的初始化方式
            asr_service._mode = "remote"
            asr_service._initialized = True
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
            lifespan_logger.info("Embedded TTS initialized successfully")
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

    # 预热 shared HTTP client：httpx.AsyncClient 在 Windows 上首次构造可能耗时 ~8s
    # （系统代理检测残留，即使 trust_env=False+proxy=None 仍可能慢）。
    # 在启动时预热，避免首次 WS voice.dual_stream 请求承受 8s 延迟（端到端测试超时）。
    import time as _warmup_t
    _warmup_t0 = _warmup_t.monotonic()
    from server.core.utils import get_shared_http_client as _warmup_get_client
    _warmup_client = _warmup_get_client()
    _warmup_dt = (_warmup_t.monotonic() - _warmup_t0) * 1000
    lifespan_logger.info(f"Shared HTTP client 预热完成 ({_warmup_dt:.1f}ms)")

    # LLM / Embedding 推理预热（后台任务，不阻塞启动完成）：
    # vLLM 冷启动后首个推理请求需完成 CUDA graph 捕获与张量分配，
    # 实测 LLM 冷 TTFT 7.6s、Embedding 冷请求 1.6s；启动时后台预热消除首请求惩罚。
    # 预热使用与生产一致的请求路径与模型名；失败仅告警不影响运行。
    async def _warmup_inference_backends() -> None:
        import asyncio as _asyncio

        from server.config import get_settings as _bk_get_settings

        _bk_settings = _bk_get_settings()
        _llm_url = _bk_settings.config.llm.host.rstrip("/")
        _llm_model = _bk_settings.config.llm.model
        _emb_url = _bk_settings.config.memory.embedding_api_base.rstrip("/")
        _emb_model = _bk_settings.config.memory.embedding_model

        async def _warm_llm() -> None:
            for _attempt in range(60):  # vLLM(BNB) 加载约 2-3 分钟，最长等 ~5 分钟
                try:
                    _resp = await _warmup_client.post(
                        f"{_llm_url}/v1/chat/completions",
                        json={
                            "model": _llm_model,
                            "messages": [{"role": "user", "content": "你好"}],
                            "max_tokens": 1,
                            "stream": False,
                        },
                        timeout=30.0,
                    )
                    if _resp.status_code == 200:
                        lifespan_logger.info(f"LLM 推理预热完成 (第 {_attempt + 1} 次尝试)")
                        return
                except Exception:
                    pass
                await _asyncio.sleep(5)
            lifespan_logger.warning("LLM 推理预热超时（不影响运行）")

        async def _warm_embedding() -> None:
            for _attempt in range(60):
                try:
                    _resp = await _warmup_client.post(
                        f"{_emb_url}/v1/embeddings",
                        json={"model": _emb_model, "input": "预热"},
                        timeout=30.0,
                    )
                    if _resp.status_code == 200:
                        lifespan_logger.info(f"Embedding 推理预热完成 (第 {_attempt + 1} 次尝试)")
                        return
                except Exception:
                    pass
                await _asyncio.sleep(5)
            lifespan_logger.warning("Embedding 推理预热超时（不影响运行）")

        await _asyncio.gather(_warm_llm(), _warm_embedding())

    try:
        import asyncio as _asyncio

        _asyncio.create_task(_warmup_inference_backends())
        lifespan_logger.info("LLM/Embedding 推理预热任务已启动（后台执行）")
    except Exception as _bk_warmup_e:
        lifespan_logger.warning(f"LLM/Embedding 预热任务启动失败（不阻塞启动）: {_bk_warmup_e}")

    lifespan_logger.info(f"CX-O-SERVER started successfully (ASR: {app.state.asr_status}, TTS: {app.state.tts_status})")

    # DocumentMemoryManager 初始化（迁移自 CXHMS Phase 2：AnythingLLM Document API 兼容端点）
    # 依赖 memory_manager，因此放在所有服务初始化完成之后
    if services.memory_manager:
        try:
            from server.core.document.memory import DocumentMemoryManager
            services.document_memory_manager = DocumentMemoryManager(
                memory_manager=services.memory_manager
            )
            lifespan_logger.info("DocumentMemoryManager 已初始化（AnythingLLM Document API 兼容）")
        except Exception as e:
            lifespan_logger.error(f"DocumentMemoryManager 初始化失败: {e}", exc_info=True)
            services.document_memory_manager = None
    else:
        lifespan_logger.warning("memory_manager 不可用，跳过 DocumentMemoryManager 初始化")

    yield

    lifespan_logger.info("正在关闭CX-O服务...")

    # DocumentMemoryManager 关闭（迁移自 CXHMS）
    if services.document_memory_manager:
        try:
            services.document_memory_manager.close()
            lifespan_logger.info("DocumentMemoryManager 已关闭")
        except Exception as e:
            lifespan_logger.warning(f"DocumentMemoryManager 关闭失败: {e}")

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

    if hasattr(services, 'task_scheduler') and services.task_scheduler:
        await shutdown_service("任务调度服务", services.task_scheduler.stop, logger_=lifespan_logger)

    if services.acp_manager:
        await shutdown_service("ACP管理器", services.acp_manager.stop, logger_=lifespan_logger)

    if services.memory_manager:
        await shutdown_service("记忆管理器", services.memory_manager.shutdown, logger_=lifespan_logger)

    if services.async_memory_manager:
        await shutdown_service("异步记忆管理器", services.async_memory_manager.close, logger_=lifespan_logger)

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
    """创建并配置 FastAPI 应用，注册 API 路由与网关路由，返回应用实例。"""
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
    """读取配置并以 uvicorn 启动 CX-O-SERVER 服务（命令行入口）。"""
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
