"""
配置处理器
"""
import logging
import threading
from typing import TYPE_CHECKING

from pydantic import BaseModel, ValidationError

from server.protocol.message import create_response, create_error
from server.protocol.actions import ConfigActions

if TYPE_CHECKING:
    from server.core.websocket.manager import WebSocketManager

logger = logging.getLogger(__name__)

# 主配置 WS 写锁：config.set 的"内存改写 + save_config 落盘"全程持锁，
# 串行化同进程内的并发 WS 配置写请求。
# 与其他域锁的关系（分散锁，各锁覆盖域互不重叠）：
# - dream 域：server/autonomy/dream/config.py 的 CONFIG_WRITE_LOCK（RLock）
# - autonomy REST 域：server/api/routers/autonomy.py 的 _CONFIG_WRITE_LOCK（Lock）
# 本锁仅覆盖主配置（server/config.py）的 WS 写路径；跨进程互斥不在要求内，
# WS 与 REST 同进程场景下由本锁保证 config.set 读写一致。
_CONFIG_WRITE_LOCK = threading.Lock()

# 敏感 key 标记：key 名（大小写不敏感）含任一子串即视为敏感
_SENSITIVE_KEY_MARKERS = (
    "api_key", "apikey", "api-key", "secret", "token", "password", "credential",
)


def _is_sensitive_key(key) -> bool:
    """判断 key 名是否命中敏感标记（大小写不敏感子串匹配）。"""
    lowered = str(key).lower()
    return any(marker in lowered for marker in _SENSITIVE_KEY_MARKERS)


def _sanitize_config(obj):
    """递归脱敏配置数据：dict/list 逐层遍历，敏感 key 的值替换为 "***"。

    用于 WS config.get 回包——model_dump() 会带出 api_key/secret/token 等
    明文，回发前端前必须统一打码；按子串匹配可能过掩（宁过不漏），
    非容器值原样返回。
    """
    if isinstance(obj, dict):
        return {
            k: ("***" if _is_sensitive_key(k) else _sanitize_config(v))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_sanitize_config(v) for v in obj]
    return obj


def register_config_handlers(manager: "WebSocketManager"):
    """将配置读取/写入处理器注册到 WebSocket 管理器。"""

    async def handle_config_get(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})

        try:
            from server.config import get_config

            config = get_config()
            section = data.get("section")

            if section:
                parts = section.split(".")
                result = config
                for part in parts:
                    result = getattr(result, part, None)
                    if result is None:
                        break
                config_data = result.model_dump() if hasattr(result, "model_dump") else result
            else:
                config_data = config.model_dump()

            # 脱敏后再回发：避免 api_key/secret/token 等明文经 WS 下发前端
            config_data = _sanitize_config(config_data)

            await manager.send_message(client_id, create_response(
                request_id=request_id,
                action=ConfigActions.GET,
                data={"config": config_data}
            ))
        except Exception as e:
            logger.error(f"Config get error: {e}")
            await manager.send_message(client_id, create_error(
                request_id=request_id,
                action=ConfigActions.GET,
                code="CONFIG_ERROR",
                message=str(e)
            ))

    async def handle_config_set(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})

        try:
            from server.config import get_config, save_config

            config = get_config()
            section = data.get("section", "")
            section_data = data.get("data", {})

            if not section:
                # section 为空时返回明确错误，避免"静默成功"路径遮蔽
                await manager.send_message(client_id, create_error(
                    request_id=request_id,
                    action=ConfigActions.SET,
                    code="INVALID_REQUEST",
                    message="Section cannot be empty"
                ))
                return

            parts = section.split(".")
            target = config
            for part in parts[:-1]:
                target = getattr(target, part, None)
                if target is None:
                    break

            # 读改写全程持模块级写锁：内存 setattr 与 save_config 落盘原子化，
            # 防止并发 WS config.set 交错写主配置
            with _CONFIG_WRITE_LOCK:
                if target is not None:
                    last_part = parts[-1]
                    if hasattr(target, last_part):
                        sub_config = getattr(target, last_part)
                        if hasattr(sub_config, "model_dump"):
                            for key, value in section_data.items():
                                # 校验 key 类型，非字符串 key 返回明确错误
                                if not isinstance(key, str):
                                    await manager.send_message(client_id, create_error(
                                        request_id=request_id,
                                        action=ConfigActions.SET,
                                        code="INVALID_REQUEST",
                                        message=f"Config key must be string, got {type(key).__name__}"
                                    ))
                                    return
                                if hasattr(sub_config, key):
                                    # Pydantic 回验：setattr 会绕过字段校验，先构造
                                    # 候选实例并整体回验，失败回发错误响应且不落盘；
                                    # 非 pydantic 模型（测试替身/普通对象）跳过回验
                                    if isinstance(sub_config, BaseModel):
                                        try:
                                            candidate = sub_config.model_copy(update={key: value})
                                            # 注意：pydantic v2 默认 revalidate_instances='never'，
                                            # 对同类型实例直接 model_validate 会原样放行；
                                            # 必须先 model_dump 成 dict 再回验才能真校验
                                            type(sub_config).model_validate(candidate.model_dump())
                                        except ValidationError as ve:
                                            await manager.send_message(client_id, create_error(
                                                request_id=request_id,
                                                action=ConfigActions.SET,
                                                code="VALIDATION_ERROR",
                                                message=f"配置项 {key} 校验失败: {ve}"
                                            ))
                                            return
                                    setattr(sub_config, key, value)
                        else:
                            setattr(target, last_part, section_data)

                save_config(config)

            await manager.send_message(client_id, create_response(
                request_id=request_id,
                action=ConfigActions.SET,
                data={"saved": True}
            ))
        except Exception as e:
            logger.error(f"Config set error: {e}")
            await manager.send_message(client_id, create_error(
                request_id=request_id,
                action=ConfigActions.SET,
                code="CONFIG_ERROR",
                message=str(e)
            ))

    manager.register_handler(ConfigActions.GET, handle_config_get)
    manager.register_handler(ConfigActions.SET, handle_config_set)
