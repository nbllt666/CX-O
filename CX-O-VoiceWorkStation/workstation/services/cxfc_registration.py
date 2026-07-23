"""
CXFC 插件注册与心跳服务：启动时向 CX-O-SERVER 注册，周期心跳保活，关闭时注销

对应 spec：add-voicews-music-cxfc-suite（Task 7.2）。

协议形状（以 CX-O-SERVER server/api/routers/cxfc.py 与 core/cxfc/models.py
的实际代码为准，路由挂载前缀 /api）：
- 注册：POST {server_url}/api/cxfc/register
  请求 {"host", "port", "name", "tools", "capabilities", "skills"}
  响应 {"status": "ok", "plugin_id": "cxfc_<host>_<port>"}
- 心跳：POST {server_url}/api/cxfc/heartbeat
  请求 {"plugin_id", "port"}；响应 {"status": "alive"}；
  插件不存在 → 404（主系统重启/丢失注册信息，本服务自动重新注册）
- 注销：DELETE {server_url}/api/cxfc/plugins/{plugin_id}（shutdown 尽力而为）

行为约束：
- cxfc.enabled=false 或 cxfc.auto_register=false 时 start() 完全空转，
  不注册、不心跳、零网络请求、零副作用；
- 注册/心跳失败不影响 VoiceWorkStation 自身服务：后台任务按间隔重试，
  连续失败按指数退避（以 heartbeat_interval 为基数，封顶 8 倍），成功后复位；
- 心跳循环用 asyncio.create_task + asyncio.sleep（禁止子线程），
  HTTP 客户端为 httpx.AsyncClient（与项目既有 client 用法一致）。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

import httpx

from workstation.config import WorkstationSettings, get_settings

logger = logging.getLogger(__name__)

# HTTP 超时（秒）：注册/心跳为轻量请求，10s 足够且避免长时间占用事件循环
_REQUEST_TIMEOUT = 10.0
# 指数退避上限倍数：delay = min(interval * 2^(failures-1), interval * 8)
_MAX_BACKOFF_MULTIPLIER = 8
# 心跳间隔下限（秒）：防止配置为 0/负值造成忙等；测试可设为 0.05 级小值
_MIN_INTERVAL = 0.05


class CXFCRegistrationService:
    """
    CXFC 注册与心跳后台服务。

    生命周期由 main.py lifespan 管理：启动时 start()，关闭时 stop()。
    部署要求与项目整体一致：单 worker 运行（uvicorn --workers 1），
    模块级单例不跨进程共享。
    """

    def __init__(self, settings: Optional[WorkstationSettings] = None):
        self._settings = settings if settings is not None else get_settings()
        self._client: Optional[httpx.AsyncClient] = None
        self._task: Optional[asyncio.Task] = None
        self._plugin_id: Optional[str] = None

    # ------------------------------------------------------------------
    # 状态查询（供测试与健康检查）
    # ------------------------------------------------------------------

    @property
    def plugin_id(self) -> Optional[str]:
        """已注册成功时的 plugin_id；未注册/注册失败/被主系统丢失时为 None"""
        return self._plugin_id

    @property
    def running(self) -> bool:
        """注册/心跳后台任务是否存活"""
        return self._task is not None and not self._task.done()

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    async def start(self) -> bool:
        """
        启动注册+心跳后台任务。

        Returns:
            True 表示后台任务已启动；False 表示配置禁用（完全空转，零副作用）
        """
        cfg = self._settings.cxfc
        if not cfg.enabled or not cfg.auto_register:
            logger.info(
                "CXFC 插件注册已禁用（enabled=%s auto_register=%s），跳过注册与心跳",
                cfg.enabled,
                cfg.auto_register,
            )
            return False
        if self.running:
            logger.warning("CXFC 注册服务已在运行，忽略重复 start")
            return True
        self._task = asyncio.create_task(self._run_loop(), name="cxfc-registration")
        logger.info(
            "CXFC 注册服务已启动: server=%s plugin=%s interval=%ss",
            cfg.server_url,
            cfg.plugin_name,
            cfg.heartbeat_interval,
        )
        return True

    async def stop(self) -> None:
        """
        停止心跳任务并尽力向主系统注销，随后关闭 HTTP 客户端。

        可安全重复调用；注销失败仅告警不抛出（shutdown 路径不允许阻塞）。
        """
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.warning("CXFC 心跳任务停止时异常: %s", exc)
            finally:
                self._task = None
        if self._plugin_id is not None:
            await self._unregister()
            self._plugin_id = None
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # 主循环：注册 → 心跳 →（失败重试 / 丢失重注册）
    # ------------------------------------------------------------------

    async def _run_loop(self) -> None:
        interval = max(_MIN_INTERVAL, float(self._settings.cxfc.heartbeat_interval))
        failures = 0
        while True:
            try:
                if self._plugin_id is None:
                    await self._register()
                else:
                    alive = await self._heartbeat()
                    if not alive:
                        # 心跳 404：主系统已丢失本插件，清空 id 下一轮重新注册
                        self._plugin_id = None
                failures = 0
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                failures += 1
                delay = min(
                    interval * (2 ** (failures - 1)),
                    interval * _MAX_BACKOFF_MULTIPLIER,
                )
                logger.warning(
                    "CXFC 注册/心跳失败（第 %d 次）: %s；%.1fs 后重试",
                    failures,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)

    # ------------------------------------------------------------------
    # 协议请求
    # ------------------------------------------------------------------

    async def _register(self) -> None:
        """
        向主系统注册插件：host/port/name + 工具/技能/能力清单。

        工具与技能定义复用 api.cxfc_plugin 的唯一定义源，
        保证注册内容与 /tools、/skills 端点响应一致。
        """
        # 延迟导入避免模块加载期循环依赖（api 层 imports services 层）
        from workstation.api.cxfc_plugin import get_skill_definitions, get_tool_definitions

        cfg = self._settings.cxfc
        host = self._register_host()
        port = int(self._settings.server.port)
        payload = {
            "host": host,
            "port": port,
            "name": cfg.plugin_name,
            "tools": get_tool_definitions(),
            "capabilities": ["music", "compose", "sing"],
            "skills": get_skill_definitions(),
        }
        client = await self._get_client()
        resp = await client.post(f"{cfg.server_url}/api/cxfc/register", json=payload)
        resp.raise_for_status()
        body = resp.json()
        # 主系统 plugin_id 规则为 cxfc_<host>_<port>；响应缺失时按规则兜底
        self._plugin_id = body.get("plugin_id") or f"cxfc_{host}_{port}"
        logger.info("CXFC 插件注册成功: plugin_id=%s server=%s", self._plugin_id, cfg.server_url)

    async def _heartbeat(self) -> bool:
        """
        发送一次心跳。

        Returns:
            True 心跳正常；False 主系统返回 404（插件已丢失，需重新注册）

        Raises:
            httpx.HTTPError: 网络错误或非 404 的 HTTP 错误状态（由主循环退避重试）
        """
        cfg = self._settings.cxfc
        client = await self._get_client()
        resp = await client.post(
            f"{cfg.server_url}/api/cxfc/heartbeat",
            json={"plugin_id": self._plugin_id, "port": int(self._settings.server.port)},
        )
        if resp.status_code == 404:
            logger.warning("CXFC 心跳 404：主系统已丢失插件 %s，将重新注册", self._plugin_id)
            return False
        resp.raise_for_status()
        logger.debug("CXFC 心跳成功: plugin_id=%s", self._plugin_id)
        return True

    async def _unregister(self) -> None:
        """向主系统注销插件（DELETE /api/cxfc/plugins/{plugin_id}）；失败仅告警"""
        cfg = self._settings.cxfc
        try:
            client = await self._get_client()
            resp = await client.delete(f"{cfg.server_url}/api/cxfc/plugins/{self._plugin_id}")
            resp.raise_for_status()
            logger.info("CXFC 插件已注销: plugin_id=%s", self._plugin_id)
        except Exception as exc:
            logger.warning("CXFC 注销失败（忽略，不影响关闭）: %s", exc)

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    def _register_host(self) -> str:
        """
        注册用主机地址：0.0.0.0/:: 为监听地址，主系统无法回连，
        统一注册为回环地址 127.0.0.1（与主系统同机部署的既有约定一致）。
        """
        host = (self._settings.server.host or "").strip()
        if host in ("", "0.0.0.0", "::"):
            return "127.0.0.1"
        return host

    async def _get_client(self) -> httpx.AsyncClient:
        """惰性创建 httpx 异步客户端（单例模式）"""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=_REQUEST_TIMEOUT)
        return self._client


# ---------------------------------------------------------------------------
# 模块级单例与 lifespan 集成入口（与 song_pipeline.get_song_pipeline 模式一致）
# ---------------------------------------------------------------------------

_service_instance: Optional[CXFCRegistrationService] = None


def get_cxfc_registration() -> CXFCRegistrationService:
    """获取 CXFCRegistrationService 稳定单例"""
    global _service_instance
    if _service_instance is None:
        _service_instance = CXFCRegistrationService(get_settings())
    return _service_instance


async def start_registration() -> bool:
    """lifespan 启动入口：配置禁用时内部空转（返回 False），零副作用"""
    return await get_cxfc_registration().start()


async def stop_registration() -> None:
    """lifespan 关闭入口：停止心跳、尽力注销、关闭 HTTP 客户端；未启动时为空操作"""
    global _service_instance
    if _service_instance is not None:
        await _service_instance.stop()
        _service_instance = None
