"""Agent 配置存储统一入口（data/agents.json 唯一读写实现）。

E1 设计收敛（第六轮质量评估批次2-C）：此前 data/agents.json 存在 5 个读写入口、
两套路径口径（CWD 相对 vs _PROJECT_ROOT 拼接）与多种写入方式（open("w") 非原子、
mkstemp+os.replace 原子、无锁非原子），且 agent_tools 期望顶层 {\"agents\": [...]}
对象而其余入口按扁平 list 解析（格式口径分裂）。本模块将其收敛为唯一真相源：

    - 路径：AGENTS_PATH（基于 __file__ 的项目绝对路径解析，与 CWD 无关，
      参照 distillation/decision 的 _PROJECT_ROOT 模式）
    - 并发：模块级 threading.RLock（可重入，update_agents 锁内读改写）
    - 写入：同目录临时文件 + os.replace 原子替换，杜绝半截 JSON
    - 形状：磁盘规范形状为扁平 list（与 data/agents.json 实际内容一致）；
      读取兼容旧 {\"agents\": [...]} 顶层对象形状；写入一律归一为扁平 list

调用方（5 入口收敛）：
    - server/api/routers/agents.py（CRUD 端点；AGENTS_CONFIG_PATH 保留为
      模块属性引用本模块 AGENTS_PATH，供测试 monkeypatch 覆盖路径）
    - server/core/decision/agent_tools.py（RADIX agent CRUD，strict fail-fast 读语义）
    - server/core/distillation/distillation_service.py（蒸馏角色卡创建，宽松读语义）
    - server/core/acp/manager.py（本地 agent 注册读取）
    - server/core/decision/decision_core.py（默认路径锚点）
"""

import json
import os
import tempfile
import threading
from typing import Any, Callable, Dict, List, Optional

from server.core.logging_config import get_contextual_logger

logger = get_contextual_logger(__name__)

# 路径锚点（rules-0 §三：os.path.dirname(os.path.abspath(__file__))）
# _THIS_DIR = <CX-O-SERVER>/server/core → _PROJECT_ROOT = <CX-O-SERVER>（上 2 级）
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_THIS_DIR))
AGENTS_PATH = os.path.join(_PROJECT_ROOT, "data", "agents.json")

# 全局可重入锁：包住 load-modify-save 全程（update_agents / save_agents），
# 防止并发交叉读改写丢 agent。RLock 使 update_agents 锁内调用 load/save 可重入。
_STORE_LOCK = threading.RLock()


def _coerce_agents_list(data: Any) -> Optional[List[Dict[str, Any]]]:
    """把顶层 JSON 数据归一为扁平 list 形状；不可识别形状返回 None。

    - 顶层扁平 list 且元素全为 dict → 原样返回（磁盘规范形状）
    - 顶层 {\"agents\": [...]} 且 agents 为全 dict 列表 → 返回该列表（兼容旧形状）
    - 顶层 {\"agents\": []}（或缺 agents 键）→ 返回 []
    - 其余（list 含非 dict 记录、agents 非 list、str/int 等标量）→ None（结构损坏）
    """
    if isinstance(data, list):
        if all(isinstance(item, dict) for item in data):
            return list(data)
        return None
    if isinstance(data, dict):
        agents = data.get("agents", [])
        if isinstance(agents, list) and all(isinstance(item, dict) for item in agents):
            return list(agents)
        return None
    return None


def load_agents(path: Optional[str] = None, *, strict: bool = False) -> List[Dict[str, Any]]:
    """加载 agents.json（兼容读，统一入口）。

    形状兼容：顶层扁平 list 原样返回；顶层 {\"agents\": [...]} 返回其 agents 列表。

    Args:
        path: 目标路径，None 时使用 AGENTS_PATH。
        strict: fail-fast 模式（供 agent_tools 写路径防以空结构覆写损坏文件）。
            strict=False（宽松，默认）：缺失 / 读取失败 / 解析失败 / 结构损坏
                → 记 warning 返回 []（异常时返回空结构）。
            strict=True：读取失败 / 解析失败 / 结构损坏 → 抛 IOError 中断；
                文件不存在仍返回 []（缺失兜底由调用方决定）。

    Returns:
        List[dict]: agent 记录列表

    Raises:
        IOError: strict=True 且读取失败 / JSON 解析失败 / 结构损坏
            （IOError 是 OSError 子类，兼容既有 except (IOError, OSError) 调用方）
    """
    target = path or AGENTS_PATH
    with _STORE_LOCK:
        if not os.path.isfile(target):
            return []
        try:
            with open(target, "r", encoding="utf-8") as fh:
                raw = fh.read()
            data = json.loads(raw)
        except OSError as exc:
            if strict:
                raise IOError(f"agents.json 读取失败（500）: {exc}") from exc
            logger.warning("agents.json 读取失败（%s），按空配置处理: %s", target, exc)
            return []
        except json.JSONDecodeError as exc:
            if strict:
                # 损坏文件不得以空结构覆写，中断写路径（M-E 语义）
                raise IOError(f"agents.json 解析失败（500）: {exc}") from exc
            logger.warning("agents.json 解析失败（%s），按空配置处理: %s", target, exc)
            return []

        agents = _coerce_agents_list(data)
        if agents is None:
            if strict:
                raise IOError(
                    'agents.json 结构损坏（500）: 顶层既非扁平 list 也非 {"agents": [...]}'
                )
            logger.warning("agents.json 结构损坏（%s），按空配置处理", target)
            return []
        return agents


def save_agents(data: Any, path: Optional[str] = None) -> None:
    """保存 agents.json（锁内原子写，形状归一为扁平 list）。

    先写同目录临时文件（.agents-*.json.tmp）再 os.replace 原子替换，
    避免进程崩溃/断电留下半截 JSON。

    Args:
        data: 扁平 list（规范形状，原样写入）或 {\"agents\": [...]} 顶层对象
            （取其 agents 列表归一写入）。磁盘统一为扁平 list，杜绝两种
            顶层形状交替漂移。
        path: 目标路径，None 时使用 AGENTS_PATH。

    Raises:
        ValueError: 数据形状非法（顶层既非全 dict list 也非 {\"agents\": [...]}）
        OSError: 写入失败（由调用方按既有语义包装/捕获）
    """
    agents = _coerce_agents_list(data)
    if agents is None:
        raise ValueError(
            'agents.json 写入形状非法: 顶层需为扁平 list 或 {"agents": [...]}'
        )
    target = path or AGENTS_PATH
    with _STORE_LOCK:
        directory = os.path.dirname(target) or "."
        os.makedirs(directory, exist_ok=True)
        tmp_path: Optional[str] = None
        try:
            fd, tmp_path = tempfile.mkstemp(
                prefix=".agents-", suffix=".json.tmp", dir=directory,
            )
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(agents, fh, ensure_ascii=False, indent=2)
            os.replace(tmp_path, target)
            tmp_path = None  # 已被 replace 消费
        finally:
            if tmp_path is not None and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass


def update_agents(
    mutator: Callable[[List[Dict[str, Any]]], Any],
    path: Optional[str] = None,
    *,
    strict: bool = True,
) -> List[Dict[str, Any]]:
    """锁内读-改-写：load → mutator(agents 列表就地修改) → save。

    mutator 抛出的任何异常都会中止保存（文件保持原样不落盘）并向调用方传播——
    agent_tools 的 FileExistsError / KeyError / ValueError 语义由此保持；
    strict 读模式保证损坏文件在此阶段即抛 IOError，不会被空结构覆写。

    Args:
        mutator: 接收 agents 列表并就地修改的回调
        path: 目标路径，None 时使用 AGENTS_PATH
        strict: 读阶段是否 fail-fast（默认 True，写路径防覆写语义）

    Returns:
        保存后的 agents 列表
    """
    with _STORE_LOCK:
        agents = load_agents(path, strict=strict)
        mutator(agents)
        save_agents(agents, path)
        return agents
