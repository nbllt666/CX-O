import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from backend.core.logging_config import get_contextual_logger
from backend.core.utils import format_messages_for_summary

logger = get_contextual_logger(__name__)


class SecondaryCommand(Enum):
    """副模型可执行的指令"""

    SUMMARIZE_MEMORY = "summarize_memory"
    ARCHIVE_MEMORY = "archive_memory"
    CLEANUP_MEMORIES = "cleanup_memories"
    ANALYZE_IMPORTANCE = "analyze_importance"
    DECAY_MEMORIES = "decay_memories"
    GET_MEMORY_INSIGHTS = "get_memory_insights"
    BATCH_PROCESS = "batch_process"
    SUMMARIZE_CONVERSATION = "summarize_conversation"
    EXTRACT_KEY_POINTS = "extract_key_points"
    GENERATE_MEMORY_REPORT = "generate_memory_report"


@dataclass
class SecondaryInstruction:
    """副模型指令"""

    command: str
    target_id: Optional[str] = None
    target_type: Optional[str] = None
    parameters: Dict = field(default_factory=dict)
    context: Dict = field(default_factory=dict)
    priority: int = 0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class SecondaryResult:
    """副模型执行结果"""

    status: str
    command: str
    output: Dict
    execution_time_ms: float
    suggestions: List[str] = field(default_factory=list)


class SecondaryModelRouter:
    """副模型指令路由器"""

    COMMAND_DESCRIPTIONS = {
        SecondaryCommand.SUMMARIZE_MEMORY.value: {
            "description": "将长记忆内容摘要为简洁版本",
            "parameters": {
                "memory_id": {"type": "int", "required": True, "description": "记忆ID"},
                "max_length": {
                    "type": "int",
                    "required": False,
                    "default": 200,
                    "description": "摘要最大长度",
                },
            },
            "example": {"memory_id": 123, "max_length": 150},
        },
        SecondaryCommand.ARCHIVE_MEMORY.value: {
            "description": "将记忆标记为归档",
            "parameters": {
                "memory_id": {"type": "int", "required": True, "description": "记忆ID"},
                "reason": {"type": "str", "required": False, "description": "归档原因"},
            },
            "example": {"memory_id": 123, "reason": "内容已过时"},
        },
        SecondaryCommand.CLEANUP_MEMORIES.value: {
            "description": "清理低价值或过期的记忆",
            "parameters": {
                "threshold": {
                    "type": "float",
                    "required": False,
                    "default": 0.1,
                    "description": "重要性阈值",
                },
                "max_count": {
                    "type": "int",
                    "required": False,
                    "default": 100,
                    "description": "最大清理数量",
                },
            },
            "example": {"threshold": 0.05, "max_count": 50},
        },
        SecondaryCommand.ANALYZE_IMPORTANCE.value: {
            "description": "分析记忆的重要性并给出评分",
            "parameters": {
                "memory_id": {"type": "int", "required": True, "description": "记忆ID"},
                "context": {"type": "str", "required": False, "description": "分析上下文"},
            },
            "example": {"memory_id": 123, "context": "用户多次提及"},
        },
        SecondaryCommand.DECAY_MEMORIES.value: {
            "description": "对所有记忆执行衰减计算",
            "parameters": {
                "dry_run": {
                    "type": "bool",
                    "required": False,
                    "default": True,
                    "description": "仅预览不实际执行",
                }
            },
            "example": {"dry_run": False},
        },
        SecondaryCommand.GET_MEMORY_INSIGHTS.value: {
            "description": "获取记忆系统的统计和洞察",
            "parameters": {
                "time_range": {
                    "type": "str",
                    "required": False,
                    "description": "时间范围 (7d, 30d, 90d)",
                },
                "metrics": {"type": "list", "required": False, "description": "需要的指标列表"},
            },
            "example": {"time_range": "30d", "metrics": ["importance_distribution", "decay_rate"]},
        },
        SecondaryCommand.BATCH_PROCESS.value: {
            "description": "批量处理多个记忆",
            "parameters": {
                "action": {
                    "type": "str",
                    "required": True,
                    "description": "操作 (summarize, archive, delete)",
                },
                "memory_ids": {"type": "list", "required": True, "description": "记忆ID列表"},
                "criteria": {"type": "str", "required": False, "description": "选择标准"},
            },
            "example": {"action": "archive", "memory_ids": [1, 2, 3]},
        },
        SecondaryCommand.SUMMARIZE_CONVERSATION.value: {
            "description": "将对话历史摘要为记忆，生成关键要点和完整报告",
            "parameters": {
                "conversation_id": {
                    "type": "str",
                    "required": True,
                    "description": "对话ID/会话ID",
                },
                "max_points": {
                    "type": "int",
                    "required": False,
                    "default": 5,
                    "description": "最大要点数",
                },
                "save_as_memory": {
                    "type": "bool",
                    "required": False,
                    "default": True,
                    "description": "是否保存为记忆",
                },
            },
            "example": {"conversation_id": "session_123", "max_points": 5, "save_as_memory": True},
        },
        SecondaryCommand.EXTRACT_KEY_POINTS.value: {
            "description": "从文本中提取关键信息点",
            "parameters": {
                "text": {"type": "str", "required": True, "description": "输入文本"},
                "max_points": {
                    "type": "int",
                    "required": False,
                    "default": 5,
                    "description": "最大要点数",
                },
            },
            "example": {"text": "用户说...", "max_points": 5},
        },
        SecondaryCommand.GENERATE_MEMORY_REPORT.value: {
            "description": "生成记忆系统报告",
            "parameters": {
                "report_type": {
                    "type": "str",
                    "required": False,
                    "default": "summary",
                    "description": "报告类型 (summary, detailed, trends)",
                },
                "time_range": {"type": "str", "required": False, "description": "时间范围"},
            },
            "example": {"report_type": "trends", "time_range": "30d"},
        },
    }

    PROHIBITED_COMMANDS = [
        "add_permanent_memory",
        "delete_permanent_memory",
        "update_permanent_memory",
        "get_permanent_memories",
    ]

    def __init__(self, memory_manager, llm_client=None, model_router=None, context_manager=None):
        self.memory_manager = memory_manager
        self.llm_client = llm_client
        self.model_router = model_router
        self.context_manager = context_manager
        self._execution_history = []

    def set_llm_client(self, llm_client):
        """设置LLM客户端（用于生成摘要、分析等）"""
        self.llm_client = llm_client

    def set_model_router(self, model_router):
        """设置模型路由器"""
        self.model_router = model_router

    def set_context_manager(self, context_manager):
        """设置上下文管理器"""
        self.context_manager = context_manager

    def get_available_commands(self) -> Dict[str, Dict]:
        """获取所有可用命令的描述"""
        return self.COMMAND_DESCRIPTIONS

    def validate_permission(self, command: str, is_from_main: bool = True) -> bool:
        """验证命令权限"""
        if is_from_main:
            return True

        if command in self.PROHIBITED_COMMANDS:
            logger.warning(f"副模型无权执行命令: {command}")
            return False

        return True

    async def execute_command(
        self, instruction: SecondaryInstruction, is_from_main: bool = True
    ) -> SecondaryResult:
        """执行副模型指令"""
        start_time = datetime.now()

        if not self.validate_permission(instruction.command, is_from_main):
            return SecondaryResult(
                status="error",
                command=instruction.command,
                output={"error": "Permission denied"},
                execution_time_ms=0.0,
                suggestions=["请使用主模型执行此操作"],
            )

        try:
            result = await self._execute_command_impl(instruction)
            execution_time = (datetime.now() - start_time).total_seconds() * 1000

            self._execution_history.append(
                {
                    "command": instruction.command,
                    "status": result.status,
                    "execution_time_ms": execution_time,
                    "timestamp": datetime.now().isoformat(),
                }
            )

            result.execution_time_ms = execution_time
            return result
        except Exception as e:
            execution_time = (datetime.now() - start_time).total_seconds() * 1000
            logger.error(f"执行命令失败: {instruction.command}, 错误: {e}")

            return SecondaryResult(
                status="error",
                command=instruction.command,
                output={"error": str(e)},
                execution_time_ms=execution_time,
                suggestions=["检查参数是否正确", "查看命令文档"],
            )

    async def _execute_command_impl(self, instruction: SecondaryInstruction) -> SecondaryResult:
        """实现具体的命令执行逻辑"""
        command = instruction.command
        params = instruction.parameters

        if command == SecondaryCommand.SUMMARIZE_MEMORY.value:
            return await self._summarize_memory(params)
        elif command == SecondaryCommand.ARCHIVE_MEMORY.value:
            return await self._archive_memory(params)
        elif command == SecondaryCommand.CLEANUP_MEMORIES.value:
            return await self._cleanup_memories(params)
        elif command == SecondaryCommand.ANALYZE_IMPORTANCE.value:
            return await self._analyze_importance(params)
        elif command == SecondaryCommand.DECAY_MEMORIES.value:
            return await self._decay_memories(params)
        elif command == SecondaryCommand.GET_MEMORY_INSIGHTS.value:
            return await self._get_memory_insights(params)
        elif command == SecondaryCommand.BATCH_PROCESS.value:
            return await self._batch_process(params)
        elif command == SecondaryCommand.SUMMARIZE_CONVERSATION.value:
            return await self._summarize_conversation(params)
        elif command == SecondaryCommand.EXTRACT_KEY_POINTS.value:
            return await self._extract_key_points(params)
        elif command == SecondaryCommand.GENERATE_MEMORY_REPORT.value:
            return await self._generate_memory_report(params)
        elif command == "custom":
            return await self._custom_command(params)
        else:
            return SecondaryResult(
                status="error",
                command=command,
                output={"error": f"Unknown command: {command}"},
                execution_time_ms=0.0,
            )

    def _get_summary_client(self):
        """获取摘要模型客户端"""
        if self.model_router:
            client = self.model_router.get_client("summary")
            if client:
                return client
        return self.llm_client

    async def _summarize_memory(self, params: Dict) -> SecondaryResult:
        """使用摘要模型对记忆进行智能摘要"""
        memory_id = params.get("memory_id")
        max_length = params.get("max_length", 200)

        memory = self.memory_manager.get_memory(memory_id)
        if not memory:
            return SecondaryResult(
                status="error",
                command="summarize_memory",
                output={"error": "Memory not found"},
                execution_time_ms=0.0,
            )

        content = memory.get("content", "")
        if not content:
            return SecondaryResult(
                status="error",
                command="summarize_memory",
                output={"error": "Memory content is empty"},
                execution_time_ms=0.0,
            )

        # 使用摘要模型生成智能摘要
        summary_client = self._get_summary_client()
        if summary_client:
            try:
                prompt = f"""请对以下内容进行摘要，长度不超过{max_length}字：

{content}

要求：
1. 保留核心信息
2. 语言简洁明了
3. 直接返回摘要文本，不要添加额外说明"""

                response = await summary_client.chat(
                    messages=[{"role": "user", "content": prompt}], stream=False
                )

                if hasattr(response, "content") and response.content:
                    summary = response.content.strip()
                elif isinstance(response, dict) and response.get("content"):
                    summary = response["content"].strip()
                else:
                    summary = content[:max_length] + "..." if len(content) > max_length else content
            except Exception as e:
                logger.error(f"摘要模型调用失败: {e}")
                summary = content[:max_length] + "..." if len(content) > max_length else content
        else:
            summary = content[:max_length] + "..." if len(content) > max_length else content

        # 更新记忆的摘要
        self.memory_manager.update_memory(
            memory_id=memory_id,
            new_metadata={"summary": summary, "summarized_at": datetime.now().isoformat()},
        )

        return SecondaryResult(
            status="success",
            command="summarize_memory",
            output={
                "memory_id": memory_id,
                "original_length": len(content),
                "summary": summary,
                "summary_length": len(summary),
            },
            execution_time_ms=0.0,
        )

    async def _archive_memory(self, params: Dict) -> SecondaryResult:
        """归档记忆"""
        memory_id = params.get("memory_id")
        reason = params.get("reason", "")

        success = self.memory_manager.update_memory(
            memory_id=memory_id,
            new_metadata={
                "archived": True,
                "archive_reason": reason,
                "archived_at": datetime.now().isoformat(),
            },
        )

        if success:
            return SecondaryResult(
                status="success",
                command="archive_memory",
                output={"memory_id": memory_id, "archived": True},
                execution_time_ms=0.0,
            )
        else:
            return SecondaryResult(
                status="error",
                command="archive_memory",
                output={"error": "Failed to archive memory"},
                execution_time_ms=0.0,
            )

    async def _cleanup_memories(self, params: Dict) -> SecondaryResult:
        """清理低价值记忆"""
        threshold = params.get("threshold", 0.1)
        max_count = params.get("max_count", 100)

        memories = self.memory_manager.search_memories(limit=max_count)
        low_value_ids = [m["id"] for m in memories if m.get("importance_score", 0.0) < threshold]

        result = self.memory_manager.batch_delete_memories(
            memory_ids=low_value_ids, soft_delete=True
        )

        return SecondaryResult(
            status="success",
            command="cleanup_memories",
            output={
                "threshold": threshold,
                "deleted_count": result["success"],
                "failed_count": result["failed"],
            },
            execution_time_ms=0.0,
        )

    async def _analyze_importance(self, params: Dict) -> SecondaryResult:
        """使用模型分析记忆重要性"""
        memory_id = params.get("memory_id")
        context = params.get("context", "")

        memory = self.memory_manager.get_memory(memory_id)
        if not memory:
            return SecondaryResult(
                status="error",
                command="analyze_importance",
                output={"error": "Memory not found"},
                execution_time_ms=0.0,
            )

        content = memory.get("content", "")
        current_importance = memory.get("importance_score", 0.0)
        current_importance_level = memory.get("importance", 3)

        # 使用模型分析重要性
        summary_client = self._get_summary_client()
        if summary_client:
            try:
                prompt = f"""请分析以下内容的重要性，并给出1-5的评分：

内容：{content[:500]}

上下文：{context}

请从以下维度分析：
1. 信息价值（是否包含独特/重要信息）
2. 时效性（是否长期有效）
3. 情感强度（是否承载情感）
4. 实用性（是否能解决实际问题）

请以JSON格式返回：
{{
    "score": 评分(1-5),
    "reason": "评分理由",
    "suggested_tags": ["建议标签1", "建议标签2"]
}}"""

                response = await summary_client.chat(
                    messages=[{"role": "user", "content": prompt}], stream=False
                )

                try:
                    if hasattr(response, "content"):
                        result_text = response.content
                    elif isinstance(response, dict):
                        result_text = response.get("content", "")
                    else:
                        result_text = str(response)

                    result = json.loads(result_text)
                    suggested_score = result.get("score", current_importance_level)
                    reason = result.get("reason", "")
                    suggested_tags = result.get("suggested_tags", [])
                except (json.JSONDecodeError, KeyError, TypeError):
                    logger.warning("解析模型响应失败，使用默认评分")
                    suggested_score = current_importance_level
                    reason = "解析失败，使用当前评分"
                    suggested_tags = []
            except Exception as e:
                logger.error(f"重要性分析模型调用失败: {e}")
                suggested_score = current_importance_level
                reason = "模型调用失败"
                suggested_tags = []
        else:
            suggested_score = current_importance_level
            reason = "无可用模型"
            suggested_tags = []

        analysis = {
            "memory_id": memory_id,
            "current_importance": current_importance,
            "current_level": current_importance_level,
            "suggested_level": suggested_score,
            "reason": reason,
            "suggested_tags": suggested_tags,
            "context": context,
        }

        return SecondaryResult(
            status="success", command="analyze_importance", output=analysis, execution_time_ms=0.0
        )

    async def _decay_memories(self, params: Dict) -> SecondaryResult:
        """执行衰减计算"""
        dry_run = params.get("dry_run", True)

        if dry_run:
            stats = self.memory_manager.get_decay_statistics()
            return SecondaryResult(
                status="success",
                command="decay_memories",
                output={"dry_run": True, "statistics": stats, "message": "预览模式，未实际更新"},
                execution_time_ms=0.0,
            )
        else:
            result = self.memory_manager.sync_decay_values()
            return SecondaryResult(
                status="success",
                command="decay_memories",
                output={
                    "dry_run": False,
                    "updated": result["updated"],
                    "failed": result["failed"],
                    "total": result["total"],
                },
                execution_time_ms=0.0,
            )

    async def _get_memory_insights(self, params: Dict) -> SecondaryResult:
        """获取记忆洞察"""
        time_range = params.get("time_range", "30d")
        metrics = params.get("metrics", [])

        stats = self.memory_manager.get_decay_statistics()
        basic_stats = self.memory_manager.get_statistics()

        insights = {
            "time_range": time_range,
            "basic_statistics": basic_stats,
            "decay_statistics": stats,
        }

        if "importance_distribution" in metrics:
            insights["importance_distribution"] = stats.get("importance_distribution", {})
        if "reactivation_stats" in metrics:
            insights["reactivation_stats"] = stats.get("reactivation_stats", {})

        return SecondaryResult(
            status="success", command="get_memory_insights", output=insights, execution_time_ms=0.0
        )

    async def _batch_process(self, params: Dict) -> SecondaryResult:
        """批量处理记忆"""
        action = params.get("action")
        memory_ids = params.get("memory_ids", [])

        if action == "delete":
            result = self.memory_manager.batch_delete_memories(
                memory_ids=memory_ids, soft_delete=True
            )
            return SecondaryResult(
                status="success",
                command="batch_process",
                output={
                    "action": action,
                    "deleted_count": result["success"],
                    "failed_count": result["failed"],
                },
                execution_time_ms=0.0,
            )
        elif action == "summarize":
            # 批量摘要
            summarized_count = 0
            for memory_id in memory_ids:
                try:
                    await self._summarize_memory({"memory_id": memory_id})
                    summarized_count += 1
                except Exception as e:
                    logger.error(f"批量摘要失败 memory_id={memory_id}: {e}")
            return SecondaryResult(
                status="success",
                command="batch_process",
                output={
                    "action": action,
                    "summarized_count": summarized_count,
                    "total": len(memory_ids),
                },
                execution_time_ms=0.0,
            )
        else:
            return SecondaryResult(
                status="error",
                command="batch_process",
                output={"error": f"Unsupported action: {action}"},
                execution_time_ms=0.0,
            )

    async def _summarize_conversation(self, params: Dict) -> SecondaryResult:
        """使用摘要模型对对话进行深度分析，生成关键要点和完整报告"""
        conversation_id = params.get("conversation_id")
        max_points = params.get("max_points", 5)
        save_as_memory = params.get("save_as_memory", True)

        if not self.context_manager:
            return SecondaryResult(
                status="error",
                command="summarize_conversation",
                output={"error": "Context manager not available"},
                execution_time_ms=0.0,
            )

        # 获取对话消息
        messages = self.context_manager.get_messages(conversation_id, limit=100)
        if not messages:
            return SecondaryResult(
                status="error",
                command="summarize_conversation",
                output={"error": "Conversation not found or empty"},
                execution_time_ms=0.0,
            )

        # 格式化对话内容
        conversation_text = format_messages_for_summary(messages)
        message_count = len(messages)

        # 使用摘要模型生成深度分析
        summary_client = self._get_summary_client()
        if not summary_client:
            return SecondaryResult(
                status="error",
                command="summarize_conversation",
                output={"error": "Summary model not available"},
                execution_time_ms=0.0,
            )

        try:
            prompt = f"""你是一位专业的对话分析专家。请对以下对话进行深度分析，生成结构化摘要报告。

## 对话内容
{conversation_text}

## 分析要求

### 1. 关键要点 (key_points)
提取{max_points}个核心要点，每个要点包含：
- content: 要点内容（简洁描述，不超过50字）
- importance: 重要性（high/medium/low）
- participants: 涉及角色（["user"]/["assistant"]/["user", "assistant"]）

### 2. 完整报告 (report)
- topic: 对话主题（一句话概括，不超过30字）
- participants: 参与者列表（如["user", "assistant"]）
- message_count: 消息总数（{message_count}）
- main_discussion: 主要讨论内容摘要（200-300字，分段描述关键讨论点）
- key_decisions: 关键决策/结论列表（字符串数组）
- action_items: 行动项列表（如有，每项包含任务描述）
- open_questions: 未解决问题列表（如有）
- sentiment: 整体情感倾向（positive/neutral/negative）
- sentiment_analysis: 情感分析说明（50字内，解释情感倾向的原因）
- timeline: 对话时间线（关键节点数组，每个节点包含time和event）

请以严格的JSON格式返回，确保可以被解析：
{{
    "key_points": [
        {{"content": "...", "importance": "high", "participants": ["user"]}},
        ...
    ],
    "report": {{
        "topic": "...",
        "participants": ["user", "assistant"],
        "message_count": {message_count},
        "main_discussion": "...",
        "key_decisions": ["..."],
        "action_items": ["..."],
        "open_questions": ["..."],
        "sentiment": "positive",
        "sentiment_analysis": "...",
        "timeline": [{{"time": "开始", "event": "..."}}]
    }}
}}"""

            response = await summary_client.chat(
                messages=[{"role": "user", "content": prompt}], stream=False, max_tokens=2048
            )

            # 解析模型响应
            try:
                if hasattr(response, "content"):
                    result_text = response.content
                elif isinstance(response, dict):
                    result_text = response.get("content", "")
                else:
                    result_text = str(response)

                # 尝试提取JSON部分
                json_start = result_text.find("{")
                json_end = result_text.rfind("}")
                if json_start != -1 and json_end != -1:
                    result_text = result_text[json_start : json_end + 1]

                result = json.loads(result_text)
                key_points = result.get("key_points", [])
                report = result.get("report", {})
            except Exception as e:
                logger.error(f"解析模型响应失败: {e}")
                key_points = []
                report = {
                    "topic": "对话摘要",
                    "participants": ["user", "assistant"],
                    "message_count": message_count,
                    "main_discussion": conversation_text[:300],
                    "sentiment": "neutral",
                }

        except Exception as e:
            logger.error(f"对话摘要模型调用失败: {e}")
            return SecondaryResult(
                status="error",
                command="summarize_conversation",
                output={"error": f"Model call failed: {str(e)}"},
                execution_time_ms=0.0,
            )

        # 生成摘要文本
        summary_text = report.get("topic", "") + "\n\n"
        summary_text += "关键要点：\n"
        for i, point in enumerate(key_points[:max_points], 1):
            summary_text += f"{i}. {point.get('content', '')}\n"

        # 保存为记忆
        summary_memory_id = None
        if save_as_memory:
            try:
                summary_memory_id = self.memory_manager.write_memory(
                    content=summary_text,
                    memory_type="conversation_summary",
                    importance=4,
                    tags=["conversation_summary", conversation_id],
                    metadata={
                        "conversation_id": conversation_id,
                        "key_points": key_points,
                        "report": report,
                        "message_count": message_count,
                        "summarized_at": datetime.now().isoformat(),
                    },
                )
            except Exception as e:
                logger.error(f"保存摘要记忆失败: {e}")

        # 更新会话摘要
        try:
            self.context_manager.update_session(conversation_id, summary=summary_text[:500])
        except Exception as e:
            logger.error(f"更新会话摘要失败: {e}")

        return SecondaryResult(
            status="success",
            command="summarize_conversation",
            output={
                "conversation_id": conversation_id,
                "summary_memory_id": summary_memory_id,
                "key_points": key_points,
                "report": report,
                "metadata": {
                    "original_message_count": message_count,
                    "summary_generated_at": datetime.now().isoformat(),
                    "model_used": "summary",
                },
            },
            execution_time_ms=0.0,
        )

    async def _extract_key_points(self, params: Dict) -> SecondaryResult:
        """使用模型智能提取关键点"""
        text = params.get("text", "")
        max_points = params.get("max_points", 5)

        if not text:
            return SecondaryResult(
                status="error",
                command="extract_key_points",
                output={"error": "Text is empty"},
                execution_time_ms=0.0,
            )

        summary_client = self._get_summary_client()
        if summary_client:
            try:
                prompt = f"""请从以下文本中提取{max_points}个关键信息点：

{text[:2000]}

要求：
1. 每个要点简洁明了（不超过50字）
2. 要点之间不重复
3. 按重要性排序

请以JSON数组格式返回：
["要点1", "要点2", "要点3"]"""

                response = await summary_client.chat(
                    messages=[{"role": "user", "content": prompt}], stream=False
                )

                try:
                    if hasattr(response, "content"):
                        result_text = response.content
                    elif isinstance(response, dict):
                        result_text = response.get("content", "")
                    else:
                        result_text = str(response)

                    # 尝试提取JSON数组
                    json_start = result_text.find("[")
                    json_end = result_text.rfind("]")
                    if json_start != -1 and json_end != -1:
                        result_text = result_text[json_start : json_end + 1]

                    key_points = json.loads(result_text)
                    if not isinstance(key_points, list):
                        key_points = []
                except (json.JSONDecodeError, TypeError):
                    key_points = []
            except Exception as e:
                logger.error(f"关键点提取模型调用失败: {e}")
                key_points = []
        else:
            # 回退到简单分割
            sentences = text.split("。")
            key_points = [s.strip() for s in sentences[:max_points] if s.strip()]

        return SecondaryResult(
            status="success",
            command="extract_key_points",
            output={
                "text_length": len(text),
                "key_points": key_points,
                "point_count": len(key_points),
            },
            execution_time_ms=0.0,
        )

    async def _generate_memory_report(self, params: Dict) -> SecondaryResult:
        """生成记忆系统报告"""
        report_type = params.get("report_type", "summary")
        time_range = params.get("time_range", "30d")

        stats = self.memory_manager.get_decay_statistics()
        basic_stats = self.memory_manager.get_statistics()

        report = {
            "report_type": report_type,
            "time_range": time_range,
            "generated_at": datetime.now().isoformat(),
            "statistics": {
                "total_memories": basic_stats.get("total", 0),
                "by_type": basic_stats.get("by_type", {}),
                "decay_stats": stats,
            },
        }

        # 使用模型生成分析报告
        summary_client = self._get_summary_client()
        if summary_client and report_type == "detailed":
            try:
                prompt = f"""基于以下记忆系统统计数据，生成一份分析报告：

总记忆数: {basic_stats.get("total", 0)}
类型分布: {basic_stats.get("by_type", {})}
平均时间分: {stats.get("avg_time_score", 0)}
平均重要性分: {stats.get("avg_importance_score", 0)}

请生成：
1. 数据解读（100字内）
2. 趋势分析
3. 优化建议

以JSON格式返回：
{{
    "interpretation": "...",
    "trends": ["..."],
    "suggestions": ["..."]
}}"""

                response = await summary_client.chat(
                    messages=[{"role": "user", "content": prompt}], stream=False
                )

                try:
                    if hasattr(response, "content"):
                        result_text = response.content
                    elif isinstance(response, dict):
                        result_text = response.get("content", "")
                    else:
                        result_text = str(response)

                    json_start = result_text.find("{")
                    json_end = result_text.rfind("}")
                    if json_start != -1 and json_end != -1:
                        result_text = result_text[json_start : json_end + 1]

                    analysis = json.loads(result_text)
                    report["analysis"] = analysis
                except (json.JSONDecodeError, KeyError, TypeError):
                    pass
            except Exception as e:
                logger.error(f"报告生成模型调用失败: {e}")

        return SecondaryResult(
            status="success", command="generate_memory_report", output=report, execution_time_ms=0.0
        )

    def get_execution_history(self, limit: int = 10) -> List[Dict]:
        """获取执行历史"""
        return self._execution_history[-limit:]

    async def _custom_command(self, params: Dict) -> SecondaryResult:
        """处理自定义命令，将用户消息转发给记忆管理模型"""
        user_message = params.get("user_message", "")

        if not user_message:
            return SecondaryResult(
                status="error",
                command="custom",
                output={"error": "user_message is required"},
                execution_time_ms=0.0,
            )

        # 使用记忆管理模型处理用户消息
        memory_client = (
            self.model_router.get_client("memory") if self.model_router else self.llm_client
        )

        if not memory_client:
            return SecondaryResult(
                status="error",
                command="custom",
                output={"error": "Memory model not available"},
                execution_time_ms=0.0,
            )

        try:
            # 构建系统提示词
            system_prompt = """你是记忆管理助手，专门负责帮助用户管理和维护记忆库。你可以通过自然语言理解用户的需求，并调用相应的工具来执行记忆管理操作。

你可以使用以下16个记忆管理工具：

1. update_memory_node - 更新记忆节点内容
2. search_memories - 搜索记忆（关键词搜索）
3. delete_memory - 删除记忆（软删除，7天后自动清理）
4. merge_memories - 合并多个相似记忆
5. clean_expired - 清理已软删除超过7天的记忆
6. export_memories - 导出记忆数据（JSON/CSV格式）
7. get_memory_stats - 获取记忆库统计信息
8. search_by_time - 按时间范围搜索记忆
9. search_by_tag - 按标签搜索记忆
10. bulk_delete - 批量删除记忆
11. restore_memory - 恢复软删除的记忆
12. search_similar_memories - 搜索与指定记忆相似的其他记忆
13. get_chat_history - 获取指定会话的聊天历史
14. get_similar_memories - 获取与给定内容相似的记忆
15. get_memory_logs - 获取记忆管理操作日志
16. get_available_commands - 获取所有可用命令列表

当用户需要管理记忆时，请主动使用这些工具。用中文回答用户的问题。"""

            response = await memory_client.chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                stream=False,
            )

            if hasattr(response, "content"):
                response_text = response.content
            elif isinstance(response, dict):
                response_text = response.get("content", "")
            else:
                response_text = str(response)

            return SecondaryResult(
                status="success",
                command="custom",
                output={"response": response_text},
                execution_time_ms=0.0,
            )
        except Exception as e:
            logger.error(f"自定义命令执行失败: {e}")
            return SecondaryResult(
                status="error", command="custom", output={"error": str(e)}, execution_time_ms=0.0
            )
