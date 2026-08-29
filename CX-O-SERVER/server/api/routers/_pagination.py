"""分页参数钳制辅助（T-07）。

收敛此前散落在 memory/admin/autonomy/dream/decision/tuner 六处路由中的
内联分页钳制 `max(1, min(int(limit), 200))` + `max(0, int(offset))`，
统一钳制口径，避免各处上限漂移。
"""

# 默认单页上限：与原 R9 内联口径一致（防恶意大 limit 拖库）
DEFAULT_MAX_LIMIT = 200


def clamp_pagination(limit: int, offset: int = 0, max_limit: int = DEFAULT_MAX_LIMIT) -> tuple[int, int]:
    """将分页参数钳制到安全边界。

    Args:
        limit: 请求的分页大小，钳制到 [1, max_limit] 区间。
        offset: 请求的偏移量，钳制到 >= 0。
        max_limit: 单页大小上限，默认 200；tuner 会话导出端点口径为 100。

    Returns:
        tuple[int, int]: (limit, offset)——
        limit = max(1, min(int(limit), max_limit))，offset = max(0, int(offset))。
    """
    return (max(1, min(int(limit), max_limit)), max(0, int(offset)))
