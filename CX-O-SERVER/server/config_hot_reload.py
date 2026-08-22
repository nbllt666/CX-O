"""配置热更新服务——将持久化后的配置变更即时应用到运行中组件，并广播给前端。

各配置节声明是否可热更新（``REQUIRES_RESTART``）。可热更新的节在保存后
调用 ``apply_section`` 作用到对应运行时组件；不可热更新的节标记
``requires_restart=True``，由前端提示用户重启。
"""
from typing import Any, Dict, Optional

from server.core.logging_config import get_contextual_logger

logger = get_contextual_logger(__name__)

# 各配置节是否需重启才能生效（无法热更新）。
# True = 需重启；False = 可热更新，保存后即时生效。
REQUIRES_RESTART: Dict[str, bool] = {
    "llm": False,      # 可热更新：重建 LLM 客户端
    "vector": True,    # 向量库客户端持有持久连接，需重启
    "audio": False,
    "live": False,
    "system": False,
    "evolution": False,  # CXO-Tuner evolution 节：可热更新，仅记录，不重建组件
}


async def apply_section(
    section: str,
    section_data: Dict[str, Any],
    model_router: Optional[Any] = None,
) -> Dict[str, Any]:
    """将配置节作用到运行中组件。

    Args:
        section: 配置节名（llm / vector / audio / live / system 等）。
        section_data: 该节的完整提交数据。
        model_router: ModelRouter 实例（自 app.state.services 注入），
            LLM 节热更新时用于重建客户端。

    Returns:
        {"applied": bool, "requires_restart": bool}
    """
    requires_restart = REQUIRES_RESTART.get(section, False)

    if section == "llm" and not requires_restart and model_router is not None:
        try:
            await model_router.reload_clients()
        except Exception as e:
            logger.error(f"LLM 配置热更新失败: {e}")

    if section == "evolution":
        # CXO-Tuner evolution 节：不强制重建 Tuner 客户端（客户端按需惰性重建），
        # 仅记录本次更新字段，标记 applied=True（requires_restart=False）。
        logger.info(f"CXO-Tuner evolution 配置节热更新（仅记录）: {list(section_data.keys())}")
        return {"applied": True, "requires_restart": False}

    return {"applied": not requires_restart, "requires_restart": requires_restart}


async def broadcast_config_changed(
    ws_manager: Any,
    section: str,
    requires_restart: bool,
) -> None:
    """向所有 WebSocket 客户端广播配置变更事件。

    前端（管理界面 / 桌宠窗）订阅 ``/ws`` 后收到 ``event == "config_changed"``
    的事件，据此刷新 limits 与本地配置表单。
    """
    try:
        await ws_manager.broadcast(
            {
                "event": "config_changed",
                "data": {"section": section, "requires_restart": requires_restart},
            }
        )
    except Exception as e:
        logger.warning(f"广播配置变更事件失败: {e}")
