"""
记忆管理对话引擎
支持通过自然语言与记忆管理模型交互
"""

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from backend.core.logging_config import get_contextual_logger

logger = get_contextual_logger(__name__)


@dataclass
class MemoryCommand:
    """记忆管理命令"""

    command_type: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    requires_confirmation: bool = False
    description: str = ""


@dataclass
class ConversationContext:
    """对话上下文"""

    session_id: str
    messages: List[Dict] = field(default_factory=list)
    pending_command: Optional[MemoryCommand] = None
    last_memory_search: List[int] = field(default_factory=list)
    user_preferences: Dict = field(default_factory=dict)


class MemoryConversationEngine:
    """记忆管理对话引擎"""

    # 命令类型定义
    COMMAND_TYPES = {
        "search": "搜索记忆",
        "archive": "归档记忆",
        "merge": "合并重复记忆",
        "delete": "删除记忆",
        "update": "更新记忆",
        "deduplicate": "检测重复",
        "stats": "查看统计",
        "help": "帮助信息",
        "unknown": "未知命令",
    }

    # 需要确认的命令
    DESTRUCTIVE_COMMANDS = ["delete", "merge", "archive"]

    def __init__(self, memory_manager, llm_client=None):
        self.memory_manager = memory_manager
        self.llm_client = llm_client
        self._sessions: Dict[str, ConversationContext] = {}
        self._command_handlers: Dict[str, Callable] = {
            "search": self._handle_search,
            "archive": self._handle_archive,
            "merge": self._handle_merge,
            "delete": self._handle_delete,
            "update": self._handle_update,
            "deduplicate": self._handle_deduplicate,
            "stats": self._handle_stats,
            "help": self._handle_help,
        }

    def get_or_create_session(self, session_id: str) -> ConversationContext:
        """获取或创建对话会话"""
        if session_id not in self._sessions:
            self._sessions[session_id] = ConversationContext(session_id=session_id)
        return self._sessions[session_id]

    async def process_message(
        self, user_message: str, session_id: str = "default"
    ) -> Dict[str, Any]:
        """处理用户消息"""
        context = self.get_or_create_session(session_id)

        # 添加用户消息到上下文
        context.messages.append(
            {"role": "user", "content": user_message, "timestamp": datetime.now().isoformat()}
        )

        # 检查是否有待确认的命令
        if context.pending_command:
            response = await self._handle_confirmation(user_message, context)
            return response

        # 解析命令
        command = await self._parse_command(user_message, context)

        # 执行命令
        if command.command_type in self._command_handlers:
            handler = self._command_handlers[command.command_type]
            response = await handler(command, context)
        else:
            # 使用 LLM 生成通用回复
            response = await self._generate_response(user_message, context)

        # 添加助手回复到上下文
        context.messages.append(
            {
                "role": "assistant",
                "content": response.get("message", ""),
                "timestamp": datetime.now().isoformat(),
            }
        )

        # 限制上下文长度
        if len(context.messages) > 20:
            context.messages = context.messages[-20:]

        return response

    async def _parse_command(
        self, user_message: str, context: ConversationContext
    ) -> MemoryCommand:
        """解析用户消息中的命令"""
        message_lower = user_message.lower()

        # 关键词匹配
        command_patterns = {
            "search": [r"搜索|查找|找一下|有没有|查询", r"search|find|look for"],
            "archive": [r"归档|存档|压缩", r"archive|compress"],
            "merge": [r"合并|整合|去重", r"merge|combine|dedup"],
            "delete": [r"删除|移除|清空", r"delete|remove|clear"],
            "update": [r"更新|修改|编辑", r"update|modify|edit"],
            "deduplicate": [r"检测重复|查重|相似", r"detect duplicate|similarity"],
            "stats": [r"统计|查看|状态", r"stats|status|count"],
            "help": [r"帮助|怎么用|说明", r"help|how to|guide"],
        }

        for cmd_type, patterns in command_patterns.items():
            for pattern in patterns:
                if re.search(pattern, message_lower):
                    parameters = self._extract_parameters(user_message, cmd_type)
                    return MemoryCommand(
                        command_type=cmd_type,
                        parameters=parameters,
                        confidence=0.8,
                        requires_confirmation=cmd_type in self.DESTRUCTIVE_COMMANDS,
                        description=self.COMMAND_TYPES.get(cmd_type, "未知命令"),
                    )

        # 如果没有匹配到命令，返回未知
        return MemoryCommand(
            command_type="unknown", parameters={"original_message": user_message}, confidence=0.0
        )

    def _extract_parameters(self, message: str, command_type: str) -> Dict[str, Any]:
        """提取命令参数"""
        parameters = {}

        if command_type == "search":
            # 提取搜索关键词
            # 移除命令词
            keywords = re.sub(
                r"搜索|查找|找一下|有没有|查询|search|find|look for",
                "",
                message,
                flags=re.IGNORECASE,
            ).strip()
            parameters["query"] = keywords if keywords else None

            # 提取记忆类型
            if re.search(r"永久|permanent", message, re.IGNORECASE):
                parameters["memory_type"] = "permanent"
            elif re.search(r"长期|long", message, re.IGNORECASE):
                parameters["memory_type"] = "long_term"
            elif re.search(r"短期|short", message, re.IGNORECASE):
                parameters["memory_type"] = "short_term"

            # 提取限制数量
            limit_match = re.search(r"(\d+)条|top\s*(\d+)", message, re.IGNORECASE)
            if limit_match:
                parameters["limit"] = int(limit_match.group(1) or limit_match.group(2))

        elif command_type == "archive":
            # 提取归档级别
            level_match = re.search(r"(\d+)级|level\s*(\d+)", message, re.IGNORECASE)
            if level_match:
                parameters["target_level"] = int(level_match.group(1) or level_match.group(2))
            else:
                parameters["target_level"] = 1

            # 提取记忆ID
            id_match = re.search(r"ID\s*(\d+)|记忆\s*(\d+)", message, re.IGNORECASE)
            if id_match:
                parameters["memory_id"] = int(id_match.group(1) or id_match.group(2))

        elif command_type == "merge":
            # 提取记忆ID列表
            ids = re.findall(r"ID\s*(\d+)|记忆\s*(\d+)", message, re.IGNORECASE)
            if ids:
                parameters["memory_ids"] = [int(id[0] or id[1]) for id in ids]

        elif command_type == "delete":
            # 提取记忆ID
            id_match = re.search(r"ID\s*(\d+)|记忆\s*(\d+)", message, re.IGNORECASE)
            if id_match:
                parameters["memory_id"] = int(id_match.group(1) or id_match.group(2))

        return parameters

    async def _handle_confirmation(
        self, user_message: str, context: ConversationContext
    ) -> Dict[str, Any]:
        """处理命令确认"""
        message_lower = user_message.lower()

        # 确认关键词
        confirm_patterns = [r"是|确认|确定|yes|confirm|ok|y"]
        # 取消关键词
        cancel_patterns = [r"否|取消|不|no|cancel|n"]

        is_confirm = any(re.search(p, message_lower) for p in confirm_patterns)
        is_cancel = any(re.search(p, message_lower) for p in cancel_patterns)

        if is_confirm:
            # 执行待确认的命令
            command = context.pending_command
            context.pending_command = None

            if command and command.command_type in self._command_handlers:
                # 临时禁用确认要求
                command.requires_confirmation = False
                handler = self._command_handlers[command.command_type]
                return await handler(command, context)

            return {"status": "error", "message": "待确认的命令已过期，请重新操作"}

        elif is_cancel:
            context.pending_command = None
            return {"status": "cancelled", "message": "操作已取消"}

        else:
            return {
                "status": "waiting_confirmation",
                "message": "请确认是否执行该操作（是/否）",
                "pending_command": {
                    "type": context.pending_command.command_type,
                    "description": context.pending_command.description,
                },
            }

    async def _handle_search(
        self, command: MemoryCommand, context: ConversationContext
    ) -> Dict[str, Any]:
        """处理搜索命令"""
        query = command.parameters.get("query")
        memory_type = command.parameters.get("memory_type")
        limit = command.parameters.get("limit", 10)

        try:
            if query:
                # 语义搜索
                results = self.memory_manager.search_memories(
                    query=query, memory_type=memory_type, limit=limit
                )
            else:
                # 列出所有记忆
                results = self.memory_manager.search_memories(memory_type=memory_type, limit=limit)

            # 保存搜索结果到上下文
            context.last_memory_search = [r["id"] for r in results]

            if not results:
                return {
                    "status": "success",
                    "message": f"未找到匹配的记忆" + (f"：{query}" if query else ""),
                    "results": [],
                }

            # 格式化结果
            result_text = f"找到 {len(results)} 条记忆：\n\n"
            for i, memory in enumerate(results, 1):
                result_text += f"{i}. ID: {memory['id']} | {memory['content'][:100]}...\n"
                result_text += f"   类型: {memory.get('type', 'unknown')} | 重要性: {memory.get('importance', 3)}\n\n"

            return {
                "status": "success",
                "message": result_text,
                "results": results,
                "count": len(results),
            }

        except Exception as e:
            logger.error(f"搜索记忆失败: {e}")
            return {"status": "error", "message": f"搜索失败: {str(e)}"}

    async def _handle_archive(
        self, command: MemoryCommand, context: ConversationContext
    ) -> Dict[str, Any]:
        """处理归档命令"""
        if command.requires_confirmation:
            context.pending_command = command
            return {
                "status": "waiting_confirmation",
                "message": f"确认归档记忆 ID {command.parameters.get('memory_id')} 到级别 {command.parameters.get('target_level', 1)} 吗？（是/否）",
                "pending_command": {"type": "archive", "description": "归档记忆"},
            }

        memory_id = command.parameters.get("memory_id")
        target_level = command.parameters.get("target_level", 1)

        if not memory_id:
            # 如果没有指定ID，归档搜索结果
            if context.last_memory_search:
                memory_id = context.last_memory_search[0]
            else:
                return {"status": "error", "message": "请指定要归档的记忆ID"}

        try:
            if hasattr(self.memory_manager, "archiver") and self.memory_manager.archiver:
                result = await self.memory_manager.archiver.archive_memory(
                    memory_id=memory_id, target_level=target_level
                )

                if result:
                    return {
                        "status": "success",
                        "message": f"记忆 ID {memory_id} 已成功归档到级别 {target_level}",
                        "archive": result.to_dict(),
                    }
                else:
                    return {"status": "error", "message": f"归档失败，记忆可能不存在"}
            else:
                return {"status": "error", "message": "归档功能未启用"}

        except Exception as e:
            logger.error(f"归档记忆失败: {e}")
            return {"status": "error", "message": f"归档失败: {str(e)}"}

    async def _handle_merge(
        self, command: MemoryCommand, context: ConversationContext
    ) -> Dict[str, Any]:
        """处理合并命令"""
        if command.requires_confirmation:
            context.pending_command = command
            return {
                "status": "waiting_confirmation",
                "message": f"确认合并 {len(command.parameters.get('memory_ids', []))} 个记忆吗？合并后将无法撤销。（是/否）",
                "pending_command": {"type": "merge", "description": "合并重复记忆"},
            }

        memory_ids = command.parameters.get("memory_ids", [])

        if len(memory_ids) < 2:
            # 尝试从去重组获取
            if hasattr(self.memory_manager, "deduplication_engine"):
                groups = await self.memory_manager.deduplication_engine.detect_duplicates_batch()
                if groups:
                    memory_ids = groups[0].memory_ids

        if len(memory_ids) < 2:
            return {"status": "error", "message": "至少需要两个记忆才能合并"}

        try:
            if hasattr(self.memory_manager, "archiver") and self.memory_manager.archiver:
                result = await self.memory_manager.archiver.merge_duplicate_memories(
                    memory_ids=memory_ids, strategy="smart"
                )

                return {
                    "status": "success" if result.success else "error",
                    "message": result.message,
                    "result": {
                        "merged_memory_id": result.merged_memory_id,
                        "merged_from": result.merged_from,
                    },
                }
            else:
                return {"status": "error", "message": "归档功能未启用"}

        except Exception as e:
            logger.error(f"合并记忆失败: {e}")
            return {"status": "error", "message": f"合并失败: {str(e)}"}

    async def _handle_delete(
        self, command: MemoryCommand, context: ConversationContext
    ) -> Dict[str, Any]:
        """处理删除命令"""
        if command.requires_confirmation:
            context.pending_command = command
            return {
                "status": "waiting_confirmation",
                "message": f"确认删除记忆 ID {command.parameters.get('memory_id')} 吗？删除后将无法恢复。（是/否）",
                "pending_command": {"type": "delete", "description": "删除记忆"},
            }

        memory_id = command.parameters.get("memory_id")

        if not memory_id:
            return {"status": "error", "message": "请指定要删除的记忆ID"}

        try:
            success = self.memory_manager.delete_memory(memory_id, soft_delete=True)

            if success:
                return {"status": "success", "message": f"记忆 ID {memory_id} 已删除"}
            else:
                return {"status": "error", "message": f"删除失败，记忆可能不存在"}

        except Exception as e:
            logger.error(f"删除记忆失败: {e}")
            return {"status": "error", "message": f"删除失败: {str(e)}"}

    async def _handle_update(
        self, command: MemoryCommand, context: ConversationContext
    ) -> Dict[str, Any]:
        """处理更新命令"""
        return {
            "status": "info",
            "message": "更新功能需要通过具体界面操作，请使用 WebUI 或 API 直接更新记忆内容",
        }

    async def _handle_deduplicate(
        self, command: MemoryCommand, context: ConversationContext
    ) -> Dict[str, Any]:
        """处理去重检测命令"""
        try:
            if hasattr(self.memory_manager, "deduplication_engine"):
                from config.settings import settings

                threshold = settings.config.memory.dedup_threshold

                groups = await self.memory_manager.deduplication_engine.detect_duplicates_batch(
                    threshold=threshold
                )

                if not groups:
                    return {"status": "success", "message": "未检测到重复记忆", "groups": []}

                message = f"检测到 {len(groups)} 组重复记忆：\n\n"
                for i, group in enumerate(groups, 1):
                    message += f"组 {i}: {len(group.memory_ids)} 个记忆\n"
                    message += f"  记忆IDs: {', '.join(map(str, group.memory_ids))}\n"
                    message += f"  代表记忆ID: {group.canonical_id}\n\n"

                message += "可以使用 '合并重复记忆' 命令来合并这些记忆"

                return {
                    "status": "success",
                    "message": message,
                    "groups": [g.to_dict() for g in groups],
                    "threshold": threshold,
                }
            else:
                return {"status": "error", "message": "去重功能未启用"}

        except Exception as e:
            logger.error(f"检测重复失败: {e}")
            return {"status": "error", "message": f"检测失败: {str(e)}"}

    async def _handle_stats(
        self, command: MemoryCommand, context: ConversationContext
    ) -> Dict[str, Any]:
        """处理统计命令"""
        try:
            # 获取记忆统计
            all_memories = self.memory_manager.search_memories(
                memory_type=None, limit=10000, include_deleted=False
            )

            total = len(all_memories)
            permanent = sum(1 for m in all_memories if m.get("permanent", False))
            archived = sum(1 for m in all_memories if m.get("is_archived", False))

            by_type = {}
            for m in all_memories:
                t = m.get("type", "unknown")
                by_type[t] = by_type.get(t, 0) + 1

            message = f"记忆统计：\n\n"
            message += f"总记忆数: {total}\n"
            message += f"永久记忆: {permanent}\n"
            message += f"已归档: {archived}\n\n"
            message += "按类型分布：\n"
            for t, count in by_type.items():
                message += f"  {t}: {count}\n"

            # 获取归档统计
            if hasattr(self.memory_manager, "archiver"):
                archive_stats = self.memory_manager.archiver.get_archive_stats()
                if archive_stats:
                    message += f"\n归档统计：\n"
                    message += f"  总归档数: {archive_stats.get('total_archived', 0)}\n"
                    message += f"  合并记录: {archive_stats.get('merge_count', 0)}\n"
                    message += f"  重复检测: {archive_stats.get('duplicate_count', 0)}\n"

            return {
                "status": "success",
                "message": message,
                "stats": {
                    "total": total,
                    "permanent": permanent,
                    "archived": archived,
                    "by_type": by_type,
                },
            }

        except Exception as e:
            logger.error(f"获取统计失败: {e}")
            return {"status": "error", "message": f"获取统计失败: {str(e)}"}

    async def _handle_help(
        self, command: MemoryCommand, context: ConversationContext
    ) -> Dict[str, Any]:
        """处理帮助命令"""
        help_text = """记忆管理助手使用指南：

可用命令：
1. 搜索记忆
   - "搜索关于人工智能的记忆"
   - "查找所有永久记忆"
   - "找一下最近的10条记忆"

2. 归档记忆
   - "归档记忆 ID 123"
   - "将记忆 456 归档到级别 2"

3. 合并重复记忆
   - "合并重复记忆"
   - "去重并合并"

4. 删除记忆
   - "删除记忆 ID 789"

5. 检测重复
   - "检测重复记忆"
   - "查重"

6. 查看统计
   - "查看统计"
   - "记忆状态"

7. 获取帮助
   - "帮助"
   - "怎么用"

注意事项：
- 删除、归档、合并操作需要确认
- 可以使用自然语言描述你的需求
- 支持中英文命令
"""

        return {"status": "success", "message": help_text}

    async def _generate_response(
        self, user_message: str, context: ConversationContext
    ) -> Dict[str, Any]:
        """使用 LLM 生成通用回复"""
        if not self.llm_client:
            return {
                "status": "unknown",
                "message": "抱歉，我没有理解您的指令。请尝试使用 '帮助' 查看可用命令。",
            }

        try:
            # 构建提示
            recent_messages = (
                context.messages[-6:] if len(context.messages) > 6 else context.messages
            )
            conversation_history = "\n".join(
                [
                    f"{'用户' if m['role'] == 'user' else '助手'}: {m['content']}"
                    for m in recent_messages[:-1]
                ]
            )

            prompt = f"""你是 CXHMS 记忆管理系统的智能助手。请根据对话历史回复用户。

对话历史：
{conversation_history}

用户当前消息：{user_message}

请用友好、简洁的语言回复。如果用户询问记忆管理相关的问题，请提供帮助。如果不确定如何回答，建议用户使用"帮助"命令查看可用功能。

回复："""

            response = await self.llm_client.generate(prompt)
            text = response.get("text", "").strip()

            return {
                "status": "success",
                "message": (
                    text if text else "抱歉，我没有理解您的指令。请尝试使用 '帮助' 查看可用命令。"
                ),
            }

        except Exception as e:
            logger.error(f"生成回复失败: {e}")
            return {"status": "error", "message": "抱歉，处理您的请求时出现了问题。请稍后重试。"}
