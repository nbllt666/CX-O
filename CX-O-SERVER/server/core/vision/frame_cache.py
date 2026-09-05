"""最近视觉帧单槽内存缓存（spec add-vlm-frame-filter-face-match T3/T4 共享挂点）。

隐私红线：帧数据仅存于进程内存、用完即弃，严禁落盘/写文件/写日志——
注册帧与筛选帧不得以任何形式持久化。

读写两侧通过本模块函数交互，与 frame_filter.py / vision 路由零代码交集：
  - 写入侧（T4 视觉帧链路，camera 源每帧覆盖写入）：set_recent_frame(data_url)
  - 读取侧（T3 face_tool LLM 工具，注册"眼前的人"）：get_recent_frame()

模块级单例 + threading.Lock 保证线程安全；单槽语义为"永远只保留最近一帧"，
新帧覆盖旧帧，不做队列不做历史。
"""
from __future__ import annotations

import threading
from typing import Optional

_lock = threading.Lock()
_recent_frame: Optional[str] = None  # 最近一帧（dataURL 或 base64 原串），None=尚无帧


def set_recent_frame(data_url: str) -> None:
    """覆盖写入最近一帧；空串/None 忽略（不产生空槽）。线程安全。"""
    global _recent_frame
    if not data_url:
        return
    with _lock:
        _recent_frame = data_url


def get_recent_frame() -> Optional[str]:
    """读取最近一帧（dataURL/base64 原串），尚无帧时返回 None。线程安全。"""
    with _lock:
        return _recent_frame


def clear() -> None:
    """清空缓存（隐私即时清除/测试复位用）。线程安全。"""
    global _recent_frame
    with _lock:
        _recent_frame = None
