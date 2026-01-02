#!/usr/bin/env python3
"""
工具定义

功能：
- 主模型工具集（MASTER_TOOLS）
- 副模型工具集（ASSISTANT_TOOLS）
"""

MASTER_TOOLS = [
    # ========== 记忆相关工具 ==========
    
    {
        "name": "write_long_term_memory",
        "description": "将关键信息写入长期记忆库。这些信息会在后续对话中被检索和使用。",
        "parameters": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "要记忆的内容（用户的重要信息、偏好、事件等）"
                },
                "importance": {
                    "type": "integer",
                    "enum": [1, 2, 3, 4, 5],
                    "description": "重要性等级（1-5），5为最重要",
                    "default": 3
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "标签列表，用于后续检索",
                    "default": []
                }
            },
            "required": ["content"]
        }
    },
    
    {
        "name": "search_all_memories",
        "description": "跨所有记忆库进行语义检索，获取与当前话题相关的记忆。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索查询（描述你想要找的信息）"
                },
                "memory_type": {
                    "type": "string",
                    "enum": ["permanent", "long_term", "all"],
                    "description": "记忆类型筛选（permanent=永久记忆，long_term=长期记忆，all=全部）",
                    "default": "all"
                },
                "time_range": {
                    "type": "string",
                    "description": "时间范围筛选（如 'last_week', 'last_month', 'today'）",
                    "default": None
                },
                "limit": {
                    "type": "integer",
                    "description": "返回结果数量限制",
                    "default": 10
                }
            },
            "required": ["query"]
        }
    },
    
    {
        "name": "call_assistant",
        "description": "呼出副模型并下达指令。副模型负责记忆管理、弹幕审核等后台任务。",
        "parameters": {
            "type": "object",
            "properties": {
                "instruction": {
                    "type": "string",
                    "description": "给副模型的指令内容"
                },
                "priority": {
                    "type": "string",
                    "enum": ["high", "normal", "low"],
                    "description": "任务优先级",
                    "default": "normal"
                }
            },
            "required": ["instruction"]
        }
    },
    
    # ========== 提醒工具 ==========
    
    {
        "name": "set_alarm",
        "description": "设置一个定时提醒。在指定秒数后，系统会向自己发送一条消息。",
        "parameters": {
            "type": "object",
            "properties": {
                "seconds": {
                    "type": "integer",
                    "description": "多少秒后提醒（最小1秒，最大86400秒即24小时）"
                },
                "message": {
                    "type": "string",
                    "description": "提醒消息内容"
                }
            },
            "required": ["seconds", "message"]
        }
    },
    
    # ========== Mono上下文工具 ==========
    
    {
        "name": "mono",
        "description": "将某些信息保持在接下来的对话上下文中。这对于需要跨多轮记住的信息很有用。",
        "parameters": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "要保持在上下文中的信息"
                },
                "rounds": {
                    "type": "integer",
                    "description": "保持的对话轮数（默认1轮）",
                    "default": 1,
                    "minimum": 1,
                    "maximum": 10
                }
            },
            "required": ["content"]
        }
    },
    
    # ========== 弹幕工具（获取未审核版本） ==========
    
    {
        "name": "get_recent_danmaku",
        "description": (
            "获取最近的弹幕记录（未审核版本）。"
            "注意：这些弹幕尚未经过审核，可能包含不适当的内容，"
            "请在回复时注意筛选和判断。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "count": {
                    "type": "integer",
                    "description": "返回弹幕数量（默认10条，最大50条）",
                    "default": 10,
                    "minimum": 1,
                    "maximum": 50
                },
                "platform": {
                    "type": "string",
                    "description": "平台筛选（如 'live'）"
                },
                "since": {
                    "type": "string",
                    "description": "返回指定时间之后的弹幕（ISO 8601格式）"
                }
            }
        }
    },
    
    {
        "name": "get_danmaku_by_id",
        "description": "根据ID获取特定弹幕的详细信息（未审核版本）。",
        "parameters": {
            "type": "object",
            "properties": {
                "danmaku_id": {
                    "type": "string",
                    "description": "弹幕ID（格式如 'danmaku_20240101_120000_001'）"
                }
            },
            "required": ["danmaku_id"]
        }
    }
]


ASSISTANT_TOOLS = [
    # ========== 记忆管理工具 ==========
    
    {
        "name": "create_daily_summary",
        "description": "根据指定上下文生成每日摘要，并存入长期记忆库。",
        "parameters": {
            "type": "object",
            "properties": {
                "context": {
                    "type": "string",
                    "description": "需要摘要的对话上下文或事件列表"
                },
                "date": {
                    "type": "string",
                    "description": "日期（格式如 '2024-01-01'），用于标签"
                }
            },
            "required": ["context"]
        }
    },
    
    {
        "name": "archive_memories",
        "description": "执行记忆归档操作。将短期记忆整理后存入长期记忆库的相应时间分区。",
        "parameters": {
            "type": "object",
            "properties": {
                "period": {
                    "type": "string",
                    "enum": ["day", "week", "month", "year"],
                    "description": "归档周期"
                }
            },
            "required": ["period"]
        }
    },
    
    {
        "name": "update_memory_node",
        "description": "更新已存在的记忆节点内容。用于修正或补充记忆信息。",
        "parameters": {
            "type": "object",
            "properties": {
                "memory_id": {
                    "type": "string",
                    "description": "记忆ID"
                },
                "new_content": {
                    "type": "string",
                    "description": "新的记忆内容"
                }
            },
            "required": ["memory_id", "new_content"]
        }
    },
    
    {
        "name": "search_memories",
        "description": "检索记忆库中的相关内容，支持时间范围筛选。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索查询"
                },
                "time_range": {
                    "type": "string",
                    "description": "时间范围（如 'last_week', '2024-01'）"
                },
                "limit": {
                    "type": "integer",
                    "description": "返回数量限制",
                    "default": 10
                }
            },
            "required": ["query"]
        }
    },
    
    {
        "name": "delete_memory",
        "description": "删除指定记忆。执行前必须发起用户确认流程。",
        "parameters": {
            "type": "object",
            "properties": {
                "memory_id": {
                    "type": "string",
                    "description": "要删除的记忆ID"
                },
                "reason": {
                    "type": "string",
                    "description": "删除原因（必须提供）"
                }
            },
            "required": ["memory_id", "reason"]
        }
    },
    
    {
        "name": "merge_memories",
        "description": "合并相似度高的记忆节点，减少冗余。",
        "parameters": {
            "type": "object",
            "properties": {
                "similarity_threshold": {
                    "type": "number",
                    "description": "相似度阈值（0-1），默认0.85",
                    "default": 0.85
                }
            }
        }
    },
    
    # ========== 数据库管理工具 ==========
    
    {
        "name": "clean_expired",
        "description": "清理已软删除的记忆（超过7天未恢复的记忆）。"
    },
    
    {
        "name": "optimize_storage",
        "description": "优化存储空间，包括重建索引、清理碎片等。"
    },
    
    {
        "name": "export_memories",
        "description": "导出记忆数据为指定格式。",
        "parameters": {
            "type": "object",
            "properties": {
                "format": {
                    "type": "string",
                    "enum": ["json", "csv"],
                    "description": "导出格式"
                },
                "memory_type": {
                    "type": "string",
                    "enum": ["permanent", "long_term", "all"],
                    "description": "记忆类型"
                }
            },
            "required": ["format"]
        }
    },
    
    {
        "name": "import_memories",
        "description": "从文件导入记忆数据。",
        "parameters": {
            "type": "object",
            "properties": {
                "format": {
                    "type": "string",
                    "enum": ["json", "csv"],
                    "description": "导入格式"
                },
                "source": {
                    "type": "string",
                    "description": "源文件路径"
                }
            },
            "required": ["format", "source"]
        }
    },
    
    {
        "name": "get_memory_stats",
        "description": "获取记忆库统计信息，包括数量、大小、各类型分布等。"
    },
    
    {
        "name": "search_by_time",
        "description": "按时间范围检索记忆。",
        "parameters": {
            "type": "object",
            "properties": {
                "start_time": {
                    "type": "string",
                    "description": "开始时间（ISO格式）"
                },
                "end_time": {
                    "type": "string",
                    "description": "结束时间（ISO格式）"
                }
            },
            "required": ["start_time", "end_time"]
        }
    },
    
    {
        "name": "search_by_tag",
        "description": "按标签检索记忆。",
        "parameters": {
            "type": "object",
            "properties": {
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "标签列表"
                }
            },
            "required": ["tags"]
        }
    },
    
    {
        "name": "verify_integrity",
        "description": "验证记忆数据的完整性，检查向量和元数据的一致性。"
    },
    
    {
        "name": "bulk_delete",
        "description": "批量删除记忆（需用户确认）。",
        "parameters": {
            "type": "object",
            "properties": {
                "memory_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "要删除的记忆ID列表"
                },
                "reason": {
                    "type": "string",
                    "description": "删除原因"
                }
            },
            "required": ["memory_ids", "reason"]
        }
    },
    
    # ========== 弹幕审核工具 ==========
    
    {
        "name": "review_danmaku",
        "description": "审核弹幕内容，判断是否适合播出。返回审核结果和优先级。",
        "parameters": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "弹幕内容"
                },
                "username": {
                    "type": "string",
                    "description": "发送弹幕的用户名"
                },
                "platform": {
                    "type": "string",
                    "description": "平台标识"
                }
            },
            "required": ["content", "username"]
        }
    },
    
    # ========== 特殊操作工具 ==========
    
    {
        "name": "restore_memory",
        "description": "恢复软删除的记忆。",
        "parameters": {
            "type": "object",
            "properties": {
                "memory_id": {
                    "type": "string",
                    "description": "要恢复的记忆ID"
                }
            },
            "required": ["memory_id"]
        }
    },
    
    {
        "name": "permanent_delete",
        "description": "永久删除记忆（立即物理删除，不经过软删除期）。仅限管理员操作。",
        "parameters": {
            "type": "object",
            "properties": {
                "memory_id": {
                    "type": "string",
                    "description": "要永久删除的记忆ID"
                },
                "reason": {
                    "type": "string",
                    "description": "删除原因"
                }
            },
            "required": ["memory_id", "reason"]
        }
    }
]
