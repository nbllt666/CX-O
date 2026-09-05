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
    # 多模型槽位节（models.main/summary/memory，spec enhance-cxfc-admin-and-integrate-dream 三）：
    # apply_section 无对应热应用分支（ModelRouter 持多槽位客户端），保守登记需重启；
    # llm 节维持 False 不变
    "models": True,
    "vector": True,    # 向量库客户端持有持久连接，需重启
    "audio": False,
    "live": False,
    "system": False,
    "evolution": False,  # CXO-Tuner evolution 节：可热更新，仅记录，不重建组件
    # CX-A 管理面：可热更新（token/限流即时生效，重启才重建长连接组件）
    "admin": False,
    # 哨兵集群：拓扑类（cluster_secret/peers/bind/witness）需重启；心跳/快照参数可热更新。
    # 保守起见整段标记需重启（SentinelCluster 持有传输连接与会话，不热重建）。
    "cluster": True,
    "graph": True,           # 图配置在进程启动时装配为单例
    "vision_enhanced": True,  # 视觉管线在装配期读取 enabled
    "meeting": True,  # 互动协调器在装配期构建，需重启生效
    # 梦境/自主彻底集成（Task 6.2）：两节登记为需重启——引擎在启动装配期构建。
    # 运行时启停不经 apply_section，由 PUT /api/dream/config、/api/autonomy/config
    # 端点自身的引擎 start/stop 与 manager 同步逻辑承担（互不影响）。
    "autonomy": True,
    "dream": True,
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
            # M9 修复：热更新失败不得 fallthrough 谎报 applied=True，
            # 返回失败结果并标记需重启，由前端提示用户。
            logger.error(f"LLM 配置热更新失败: {e}")
            return {"applied": False, "requires_restart": True, "error": str(e)}

    if section == "evolution":
        # CXO-Tuner evolution 节：不强制重建 Tuner 客户端（客户端按需惰性重建），
        # 仅记录本次更新字段，标记 applied=True（requires_restart=False）。
        logger.info(f"CXO-Tuner evolution 配置节热更新（仅记录）: {list(section_data.keys())}")
        return {"applied": True, "requires_restart": False}

    if section == "live":
        # live 节（danmaku/firewall/firewall_v3/vad/sensevoice_streaming）即时生效：
        # UnifiedConfig 未为这些节声明专有 Pydantic 字段，仍需 object.__setattr__
        # 直写运行时 UnifiedConfig 对象，但改为原子应用流程：
        # 1) 先深拷贝组装完整新值集合并逐一做 dict 浅结构校验（与保存路径一致的
        #    宽松契约：子节必须为 dict；sensevoice_streaming 仅允许数值型
        #    chunk_size/hop_size/look_back 键，与 config.py 保存分支的键过滤一致）；
        # 2) 全部校验通过后一次性赋值给对应属性（任一失败则不产生部分写入）；
        # 3) 任何异常返回 applied=False 并标记 requires_restart，不再谎报成功。
        import copy as _copy

        _LIVE_KEYS = ("danmaku", "firewall", "firewall_v3", "vad", "sensevoice_streaming")
        _SV_ALLOWED = ("chunk_size", "hop_size", "look_back")
        try:
            from server.config import get_settings
            cfg = get_settings().config

            new_values: Dict[str, Any] = {}
            for key in _LIVE_KEYS:
                value = section_data.get(key)
                if value is None:
                    continue
                if not isinstance(value, dict):
                    raise ValueError(
                        f"live.{key} 必须为对象(dict)，实际为 {type(value).__name__}"
                    )
                if key == "sensevoice_streaming":
                    invalid = [
                        k for k, v in value.items()
                        if k not in _SV_ALLOWED or isinstance(v, bool)
                        or not isinstance(v, (int, float))
                    ]
                    if invalid:
                        raise ValueError(
                            f"live.sensevoice_streaming 含非法字段或非数值取值: {invalid}"
                        )
                new_values[key] = _copy.deepcopy(value)

            for key, value in new_values.items():
                object.__setattr__(cfg, key, value)
            logger.info(f"live 配置已同步到运行时: {list(new_values.keys())}")
            return {"applied": True, "requires_restart": False}
        except Exception as e:
            logger.error(f"live 配置写运行时失败: {e}")
            return {"applied": False, "requires_restart": True, "error": str(e)}

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
