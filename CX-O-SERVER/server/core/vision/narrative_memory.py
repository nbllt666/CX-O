"""NarrativeVisionMemory —— 叙事性视觉记忆沉淀（Task8 核心链路）。

把 ``VideoUnderstanding`` 产出的 ``NarrativeSummary`` 沉淀为「有过程的叙事记忆」，
复用既有记忆基建：经 ``DecisionCore.decide_location``（D1）裁决位置，再由
``MemoryManager.write_with_decision`` 写入 ``memories`` / ``permanent_memories`` /
``rejected_content``，供 ``MemoryRouter`` 召回、衰减、三维打分、再激活复用。
不做散打，完全复用现有记忆系统。

【source 标记路径（Task 8.3，GN-004 修正项）—— 已裁决】
────────────────────────────────────────────────────────────
经调查 ``crud_mixin.write_memory`` 的 INSERT 列清单与建表 DDL
（``memory/mixins/db_mixin.py::_init_db``）：``memories`` 表与
``permanent_memories`` 表**均已有 ``source`` 列**（``source VARCHAR(50) DEFAULT 'user'``，
Agent 专属表同样含该列）。但原 ``write_memory`` 的 INSERT **不含 source 列**，导致
视觉记忆的 source 恒落 DDL 默认值 ``'user'``；``write_with_decision`` 的 permanent
分支更是硬编码 ``source="radix_decision"``。

**本实现采用「路径 A（列级 source）」**，理由：
1. 表结构已具备 source 列，无需 DDL 迁移（路径 B 仅在表结构不稳时才需退避）；
2. 落列使 MemoryRouter / 前端 Task9 可直接按 ``source='vision'`` 做列级过滤，
   检索可靠、无 JSON 解析开销；metadata 仅为便于检索的冗余承载，不构成第二口径。

为此对既有写入路径做了**最小侵入**增强（保持向后兼容，默认值不变）：
- ``crud_mixin.write_memory``：新增 ``source: str = "user"`` 参数并写入 source 列；
- ``decision_mixin.write_with_decision``：新增 ``source: Optional[str] = None``
  透传参数，memories 分支默认 ``"user"``，permanent 分支缺省维持原硬编码
  ``"radix_decision"``。

本模块以 ``source="vision"`` 传入，使视觉记忆 source 落列；同时 metadata 仍携带
source/event_type/clip_ts/emotion/tags 以便检索。**禁止 A/B 两套口径并存**：此处
以列为唯一权威标记，metadata 仅作检索冗余。
"""

from __future__ import annotations

import logging
import re
from typing import Any, Callable, Dict, List, Optional

from server.config import get_settings

from server.core.decision.decision_core import (
    DecisionCore,
    DecisionInput,
    RubricSnapshot,
    _default_rubric_dict,
)
from server.core.vision.video_understanding import NarrativeSummary

logger = logging.getLogger(__name__)

#: sediment 时传入的固定来源标记（落 memories/permanent_memories 的 source 列）
VISION_SOURCE = "vision"
#: D1 决策输入默认会话状态
_VISION_SESSION_STATE = "S_VISION_SEDIMENT"
#: 内容分句分隔符（中文/英文标点）
_CLAUSE_SEP = re.compile(r"[，。；;！？!?、\n]")
#: 轻量动作词表（中文动词），用于启发式「主体→动作→对象」抽取
_ACTION_VERBS = [
    "打开", "关闭", "拿起", "放下", "点击", "滑动", "输入", "观看", "阅读",
    "写出", "记录", "创建", "删除", "保存", "播放", "暂停", "停止", "触发",
    "发现", "看到", "观察", "判断", "使用", "操作", "移动", "站起", "坐下",
    "走出", "进入", "离开", "走到", "走到", "拿出", "放入", "发送", "拨打",
    "收到", "看到屏幕",
]
#: 摘要正文中需要剥离的叙事前缀（分词前钳除，避免被误判为主体）
_PREFIX_STRIPS = ("片段过程", "屏幕文字", "触发事件", "单帧快照", "降级",
                  "基于占位信息节略", "识别屏幕文字")


class NarrativeVisionMemory:
    """叙事性视觉记忆沉淀器。

    把叙事摘要写入记忆系统（source='vision'），并在尽力而为的前提下把
    「用户→动作→对象」结构化后映射到图数据库，关联 ``memory_id``。

    Args:
        manager: 可选 ``MemoryManager`` 实例；缺省懒加载单例 ``MemoryManager()``。
        decision_core: 可选 ``DecisionCore`` 实例；缺省懒建
            ``DecisionCore(llm_available=False)``（走 system_prompt 规则回退，
            避免沉淀阶段发起网络 LLM 调用）。
        rubric: 可选 ``RubricSnapshot``；缺省由默认 rubric 构造。
        enabled: 可选手动开关；None 时读取
            ``config.vision_enhanced.narrative_memory_enabled``。
        entity_linkers: 可选的图落库闭包注入（测试/自定义用），形如
            ``{"create_entity": callable, "create_relation": callable}``；
            None 时本模块在首次调用时懒加载 ``graph_tools`` 的事件图闭包。
    """

    def __init__(
        self,
        manager: Any = None,
        decision_core: Optional[DecisionCore] = None,
        rubric: Optional[RubricSnapshot] = None,
        enabled: Optional[bool] = None,
        entity_linkers: Optional[Dict[str, Callable[..., Any]]] = None,
    ) -> None:
        self._manager = manager
        self._decision_core = decision_core
        self._rubric = rubric
        self._enabled = enabled
        self._entity_linkers: Optional[Dict[str, Callable[..., Any]]] = entity_linkers
        self._linkers_loaded = False

    # ------------------------------------------------------------------ #
    # 依赖懒加载
    # ------------------------------------------------------------------ #
    @property
    def manager(self) -> Any:
        """懒加载 MemoryManager 单例。"""
        if self._manager is None:
            from server.core.memory.manager import MemoryManager

            self._manager = MemoryManager()
        return self._manager

    @property
    def decision_core(self) -> DecisionCore:
        """懒建 DecisionCore（默认关闭 LLM，走 system_prompt 规则回退）。"""
        if self._decision_core is None:
            self._decision_core = DecisionCore(llm_available=False)
        return self._decision_core

    @property
    def rubric(self) -> RubricSnapshot:
        """懒建默认 RubricSnapshot。"""
        if self._rubric is None:
            self._rubric = RubricSnapshot(**_default_rubric_dict())
        return self._rubric

    def _narrative_memory_enabled(self) -> bool:
        """读取叙事记忆开关：优先注入值，否则读 config.vision_enhanced。

        读取失败时回退 True（与 ``VideoUnderstanding`` 的默认行为一致）。
        """
        if self._enabled is not None:
            return bool(self._enabled)
        try:
            ve = get_settings().config.vision_enhanced
            return bool(getattr(ve, "narrative_memory_enabled", True))
        except Exception as exc:  # noqa: BLE001
            logger.warning("NarrativeVisionMemory: 读取 narrative_memory_enabled 失败（%s），默认开启", exc)
            return True

    # ------------------------------------------------------------------ #
    # 核心：sediment
    # ------------------------------------------------------------------ #
    def sediment(
        self,
        narrative: NarrativeSummary,
        session_id: str,
        decision_input_callback: Optional[Callable[[NarrativeSummary, str], DecisionInput]] = None,
        rubric: Optional[RubricSnapshot] = None,
    ) -> Optional[Dict[str, Any]]:
        """把叙事摘要沉淀为记忆。开关关闭则直接返回 None。

        流程：
        1. 读 ``vision_enhanced.narrative_memory_enabled``，False 直接返回 None；
        2. 构 ``DecisionInput``（缺省由本方法构造，可经 ``decision_input_callback`` 定制）；
        3. 调 ``DecisionCore.decide_location(session_id, decision_input, rubric)`` 产出 D1 决策；
        4. 调 ``MemoryManager.write_with_decision(content, decision, metadata, source="vision")``，
           ``metadata`` 携带 source/event_type/clip_ts/emotion/tags；
        5. 若判定写入主库（memories/permanent_memories）则尽力而为抽取实体入图，关联 memory_id。

        Args:
            narrative: ``VideoUnderstanding`` 产出的 ``NarrativeSummary``。
            session_id: 会话 ID。
            decision_input_callback: 可选，``(narrative, session_id) -> DecisionInput``
                自定义决策输入。
            rubric: 可选 RubricSnapshot，覆盖懒建默认值。

        Returns:
            未开启 → None；否则返回
            ``{"written": bool, "location": str, "memory_id": Optional[int],
                "rejected_id": Optional[str], "decision_point": str, "metadata": dict}``。
        """
        if not self._narrative_memory_enabled():
            logger.info("NarrativeVisionMemory: narrative_memory_enabled=False，跳过沉淀")
            return None

        content = (narrative.content or "").strip()
        if not content:
            logger.warning("NarrativeVisionMemory: 叙事摘要为空，跳过沉淀")
            return None

        metadata = {
            "source": VISION_SOURCE,
            "event_type": narrative.event_type or "",
            "clip_ts": float(narrative.clip_ts or 0.0),
            "emotion": narrative.emotion or "中性",
            "tags": ["visual", "narrative", narrative.event_type or "video_clip"],
        }

        if decision_input_callback is not None:
            decision_input = decision_input_callback(narrative, session_id)
        else:
            decision_input = DecisionInput(
                session_state=_VISION_SESSION_STATE,
                artifact_summary=content,
                extracted_content=content,
                quality_score=float(narrative.confidence or 0.82),
            )

        active_rubric = rubric or self.rubric
        decision = self.decision_core.decide_location(session_id, decision_input, active_rubric)
        location = getattr(decision, "location", None)
        written = location in ("memories", "permanent_memories")

        result = self.manager.write_with_decision(
            content=content,
            decision=decision,
            metadata=metadata,
            source=VISION_SOURCE,
        )
        memory_id = result.get("memory_id")
        if written and memory_id is not None:
            self._extract_and_link_entities(narrative, memory_id)

        return {
            "written": written,
            "location": location,
            "memory_id": memory_id,
            "rejected_id": result.get("rejected_id"),
            "decision_point": getattr(decision, "decision_point", "D1_LOCATION"),
            "metadata": metadata,
        }

    # ------------------------------------------------------------------ #
    # 实体抽取（尽力而为，静默降级，绝不阻塞记忆写入）
    # ------------------------------------------------------------------ #
    def _extract_and_link_entities(
        self,
        narrative: NarrativeSummary,
        memory_id: int,
    ) -> None:
        """把叙事内容抽取为「用户→动作→对象」三元组并映射入图，关联 memory_id。

        边界与降级策略：
        - 图落库依赖外部 ``graph_tools`` 闭包（生产需先 ``set_graph_dependencies``）。
          若不可程序化调用 / 未初始化 / 任意异常，本方法一律记录并静默返回，
          **不得** 抛出而阻断记忆写入。
        - 默认链接器 lazy 导入事件图闭包；测试可注入 ``entity_linkers`` 以便隔离验证。
        - 抽取为轻量启发式（中文分句 + 动作词表），准确率有限，属尽力而为。

        Args:
            narrative: 叙事摘要。
            memory_id: 已写入的记忆 ID（整数）。
        """
        if memory_id is None:
            return
        linkers = self._get_linkers()
        if not linkers:
            logger.debug("NarrativeVisionMemory: 无可用图链接器，跳过实体入图")
            return

        try:
            triples = self._extract_action_triples(narrative)
            create_entity = linkers.get("create_entity")
            create_relation = linkers.get("create_relation")

            for triple in triples:
                subject, action, obj = triple["subject"], triple["action"], triple["object"]
                if subject and create_entity:
                    create_entity(
                        name=subject, entity_type="concept",
                        properties={"source": "vision"}, memory_ids=[str(memory_id)],
                    )
                if obj and create_entity:
                    create_entity(
                        name=obj, entity_type="concept",
                        properties={"source": "vision"}, memory_ids=[str(memory_id)],
                    )
                if subject and obj and action and create_relation:
                    create_relation(
                        from_entity=subject, to_entity=obj, relation_type=action,
                        strength=1.0, evidence_memory_ids=[str(memory_id)],
                    )

            # 额外把触发事件本身也作为事件图实体落库，关联 memory_id
            event_name = narrative.event_type or "video_clip"
            if create_entity and event_name:
                create_entity(
                    name=event_name, entity_type="event",
                    properties={"source": "vision"}, memory_ids=[str(memory_id)],
                )
        except Exception as exc:  # noqa: BLE001 —— 实体入图尽力而为，异常静默降级
            logger.warning(
                "NarrativeVisionMemory: 实体抽取/入图失败，降级跳过（不阻断记忆写入）: %s",
                exc,
            )

    def _get_linkers(self) -> Optional[Dict[str, Callable[..., Any]]]:
        """返回图链接器；注入优先，否则懒加载 graph_tools 事件图闭包。

        懒加载失败（import 不可用/未初始化）返回 None，调用方据此跳过入图。
        """
        if self._entity_linkers is not None:
            return self._entity_linkers
        if self._linkers_loaded:
            return {}
        self._linkers_loaded = True
        try:
            from server.core.tools import graph_tools

            return {
                "create_entity": graph_tools.event_graph_create_entity,
                "create_relation": graph_tools.event_graph_create_relation,
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("NarrativeVisionMemory: 加载图链接器失败，跳过实体入图: %s", exc)
            return {}

    @staticmethod
    def _extract_action_triples(
        narrative: NarrativeSummary,
    ) -> List[Dict[str, str]]:
        """轻量启发式抽取「用户→动作→对象」三元组。

        对叙事正文（content + events）分句，逐句寻找动作词，动作前为主体、动作后为对象。
        找不到动作词的句子跳过。输出 ``[{"subject", "action", "object"}, ...]``。
        """
        text = (narrative.content or "") or " ".join(narrative.events or [])
        triples: List[Dict[str, str]] = []
        seen: set = set()

        for clause in _CLAUSE_SEP.split(text):
            clause = clause.strip()
            if not clause:
                continue
            for prefix in _PREFIX_STRIPS:
                clause = clause.replace(prefix, "").replace("：", "").strip()
            if len(clause) < 2:
                continue

            subject: str = ""
            action: str = ""
            obj: str = ""
            for verb in _ACTION_VERBS:
                idx = clause.find(verb)
                if idx == -1:
                    continue
                pre = clause[:idx].strip(" 的：")
                post = clause[idx + len(verb):].strip(" 的：")
                if not pre:
                    pre = "用户"  # 缺省主体归为用户
                if not post:
                    post = ""
                subject, action, obj = pre, verb, post
                break

            if not action or not subject:
                continue
            key = (subject, action, obj)
            if key in seen:
                continue
            seen.add(key)
            triples.append({"subject": subject, "action": action, "object": obj})

        return triples

    # ------------------------------------------------------------------ #
    # 队列 consumer 便捷接线
    # ------------------------------------------------------------------ #
    def sediment_from_consumer(
        self,
        item: Dict[str, Any],
        summary: NarrativeSummary,
    ) -> Optional[Dict[str, Any]]:
        """从 ``VisionClipQueue`` 条目 + 已产出的摘要直接沉淀。

        接线示例（在 ``VideoUnderstanding`` 的 consumer 内部或队列外层调用）::

            nvm = NarrativeVisionMemory()
            summary = await video_understanding.understand(...)
            nvm.sediment_from_consumer(item, summary)

        Args:
            item: 队列条目 dict（至少含 volitional ``session_id``/``event_meta``）。
            summary: ``VideoUnderstanding`` 产出的 ``NarrativeSummary``。
        """
        session_id = str(
            item.get("session_id")
            or (item.get("event_meta") or {}).get("session_id")
            or "vision_default"
        )
        return self.sediment(summary, session_id)


__all__ = [
    "NarrativeVisionMemory",
    "VISION_SOURCE",
]