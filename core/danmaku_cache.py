#!/usr/bin/env python3
"""
弹幕缓存管理器

功能：
- 原始弹幕缓存
- 审核结果存储
- 弹幕检索
- 过期清理
"""

from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from dataclasses import asdict
import json
import logging
import threading

logger = logging.getLogger(__name__)


@dataclass
class DanmakuMessage:
    """弹幕消息数据类"""
    id: str
    platform: str
    room_id: str
    username: str
    uid: str
    content: str
    badge_level: int = 0
    badge_name: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    raw: bool = True
    audit_status: str = "pending"
    audit_result: Dict = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "platform": self.platform,
            "room_id": self.room_id,
            "username": self.username,
            "uid": self.uid,
            "content": self.content,
            "badge_level": self.badge_level,
            "badge_name": self.badge_name,
            "timestamp": self.timestamp,
            "raw": self.raw,
            "audit_status": self.audit_status,
            "audit_result": self.audit_result
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'DanmakuMessage':
        try:
            return cls(
                id=data.get("id", f"danmaku_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"),
                platform=data.get("platform", "live"),
                room_id=data.get("room_id", ""),
                username=data.get("username", "未知用户"),
                uid=data.get("uid", "0"),
                content=data.get("content", ""),
                badge_level=data.get("badge_level", 0),
                badge_name=data.get("badge_name", ""),
                timestamp=data.get("timestamp", datetime.now().isoformat()),
                raw=data.get("raw", True),
                audit_status=data.get("audit_status", "pending"),
                audit_result=data.get("audit_result", {})
            )
        except Exception as e:
            logger.error(f"创建DanmakuMessage失败: {e}")
            # 返回默认值
            return cls(
                id=f"danmaku_{datetime.now().strftime('%Y%m%d%H%M%S%f')}",
                platform="live",
                room_id="",
                username="未知用户",
                uid="0",
                content=str(data)
            )


class DanmakuCacheManager:
    """弹幕缓存管理器"""
    
    def __init__(
        self,
        cache_dir: str = "data/danmaku_cache",
        retention_days: int = 7,
        max_count: int = 10000
    ):
        """
        初始化弹幕缓存管理器
        
        Args:
            cache_dir: 缓存目录路径
            retention_days: 数据保留天数
            max_count: 最大缓存数量
        """
        self.cache_dir = Path(cache_dir)
        self.raw_file = self.cache_dir / "raw_danmaku.jsonl"
        self.audited_file = self.cache_dir / "audited_danmaku.jsonl"
        self.retention_days = retention_days
        self.max_count = max_count
        
        # 线程锁
        self._lock = threading.Lock()
        
        # 创建目录
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"弹幕缓存管理器初始化完成: dir={cache_dir}, retention_days={retention_days}")
    
    def add_raw_danmaku(self, danmaku: DanmakuMessage):
        """
        添加原始弹幕
        
        Args:
            danmaku: 弹幕消息
        """
        with self._lock:
            danmaku.raw = True
            danmaku.audit_status = "pending"
            danmaku.audit_result = {}
            
            # 写入原始弹幕文件
            try:
                with open(self.raw_file, 'a', encoding='utf-8') as f:
                    f.write(json.dumps(danmaku.to_dict(), ensure_ascii=False) + '\n')
                
                logger.debug(f"原始弹幕已添加: id={danmaku.id}")
            
            except Exception as e:
                logger.error(f"写入原始弹幕失败: {e}")
    
    def add_audited_danmaku(self, danmaku: DanmakuMessage, audit_result: Dict):
        """
        添加审核后的弹幕
        
        Args:
            danmaku: 弹幕消息
            audit_result: 审核结果
        """
        with self._lock:
            danmaku.raw = False
            danmaku.audit_status = "approved" if audit_result.get("allowed") else "rejected"
            danmaku.audit_result = audit_result
            
            # 写入审核后弹幕文件
            try:
                with open(self.audited_file, 'a', encoding='utf-8') as f:
                    f.write(json.dumps(danmaku.to_dict(), ensure_ascii=False) + '\n')
                
                logger.debug(f"审核后弹幕已添加: id={danmaku.id}, status={danmaku.audit_status}")
            
            except Exception as e:
                logger.error(f"写入审核后弹幕失败: {e}")
    
    def get_recent_danmaku(
        self,
        count: int = 10,
        only_raw: bool = True,
        platform: str = None,
        since: str = None
    ) -> List[DanmakuMessage]:
        """
        获取最近的弹幕
        
        主模型调用此接口获取【未审核版本】的弹幕
        
        Args:
            count: 返回数量（默认10，最大100）
            only_raw: 是否只返回原始弹幕（主模型获取未审核版本）
            platform: 平台筛选（可选）
            since: 返回指定时间之后的弹幕（ISO格式，可选）
        
        Returns:
            弹幕消息列表（倒序，最新的在前）
        """
        # 限制数量
        count = min(count, 100)
        
        file_path = self.raw_file if only_raw else self.audited_file
        
        if not file_path.exists():
            logger.debug(f"弹幕文件不存在: {file_path}")
            return []
        
        danmaku_list = []
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                
                # 倒序遍历（最新的在前）
                for line in reversed(lines[-count * 2:]):  # 读取2倍数量以防过滤后不足
                    if line.strip():
                        danmaku_data = json.loads(line)
                        danmaku = DanmakuMessage.from_dict(danmaku_data)
                        
                        # 平台筛选
                        if platform and danmaku.platform != platform:
                            continue
                        
                        # 时间筛选
                        if since:
                            try:
                                danmaku_time = datetime.fromisoformat(danmaku.timestamp)
                                since_time = datetime.fromisoformat(since)
                                if danmaku_time < since_time:
                                    continue
                            except:
                                pass
                        
                        danmaku_list.append(danmaku)
                        
                        if len(danmaku_list) >= count:
                            break
        
        except Exception as e:
            logger.error(f"读取弹幕失败: {e}")
            return []
        
        # 保持倒序（最新的在前）
        return danmaku_list[::-1]
    
    def get_danmaku_by_id(
        self,
        danmaku_id: str,
        only_raw: bool = True
    ) -> Optional[DanmakuMessage]:
        """
        根据ID获取弹幕
        
        主模型可以通过此接口获取特定弹幕的未审核版本
        
        Args:
            danmaku_id: 弹幕ID
            only_raw: 是否只查找原始弹幕
        
        Returns:
            弹幕消息，未找到返回None
        """
        # 先查原始弹幕
        for danmaku in self.get_recent_danmaku(count=1000, only_raw=True):
            if danmaku.id == danmaku_id:
                return danmaku
        
        # 查审核后弹幕
        if not only_raw:
            for danmaku in self.get_recent_danmaku(count=1000, only_raw=False):
                if danmaku.id == danmaku_id:
                    return danmaku
        
        return None
    
    def get_audited_danmaku(
        self,
        count: int = 10,
        status: str = None
    ) -> List[DanmakuMessage]:
        """
        获取已审核的弹幕
        
        Args:
            count: 返回数量
            status: 状态筛选（approved/rejected）
        """
        danmaku_list = self.get_recent_danmaku(count=count, only_raw=False)
        
        if status:
            danmaku_list = [d for d in danmaku_list if d.audit_status == status]
        
        return danmaku_list
    
    def update_audit_result(
        self,
        danmaku_id: str,
        audit_result: Dict
    ):
        """
        更新弹幕审核结果
        
        Args:
            danmaku_id: 弹幕ID
            audit_result: 审核结果
        """
        # 从原始弹幕中查找
        danmaku = self.get_danmaku_by_id(danmaku_id, only_raw=True)
        
        if danmaku:
            # 移动到审核后文件
            self.add_audited_danmaku(danmaku, audit_result)
            
            logger.info(f"弹幕审核结果已更新: id={danmaku_id}, allowed={audit_result.get('allowed')}")
        else:
            logger.warning(f"未找到弹幕: id={danmaku_id}")
    
    def cleanup_old_danmaku(self, days: int = None):
        """
        清理过期弹幕
        
        Args:
            days: 保留天数（默认使用初始化时的值）
        """
        days = days or self.retention_days
        cutoff_time = datetime.now() - timedelta(days=days)
        
        with self._lock:
            # 清理原始弹幕
            self._cleanup_file(self.raw_file, cutoff_time)
            
            # 清理审核后弹幕
            self._cleanup_file(self.audited_file, cutoff_time)
        
        logger.info(f"过期弹幕已清理，保留{days}天内的数据")
    
    def _cleanup_file(self, file_path: Path, cutoff_time: datetime):
        """清理文件中的过期条目"""
        if not file_path.exists():
            return
        
        lines = []
        
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    danmaku_data = json.loads(line)
                    timestamp = danmaku_data.get('timestamp', '')
                    
                    try:
                        danmaku_time = datetime.fromisoformat(timestamp)
                        if danmaku_time > cutoff_time:
                            lines.append(line)
                    except:
                        # 时间解析失败，保留
                        lines.append(line)
        
        with open(file_path, 'w', encoding='utf-8') as f:
            f.writelines(lines)
    
    def get_statistics(self) -> Dict:
        """获取弹幕统计信息"""
        raw_count = 0
        audited_count = 0
        approved_count = 0
        rejected_count = 0
        pending_count = 0
        
        # 统计原始弹幕
        if self.raw_file.exists():
            with open(self.raw_file, 'r', encoding='utf-8') as f:
                raw_count = sum(1 for _ in f)
        
        # 统计审核后弹幕
        if self.audited_file.exists():
            with open(self.audited_file, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        audited_count += 1
                        data = json.loads(line)
                        status = data.get('audit_status', '')
                        if status == 'approved':
                            approved_count += 1
                        elif status == 'rejected':
                            rejected_count += 1
        
        pending_count = raw_count
        
        return {
            "raw_count": raw_count,
            "audited_count": audited_count,
            "approved_count": approved_count,
            "rejected_count": rejected_count,
            "pending_count": pending_count
        }
    
    def format_danmaku_for_llm(self, danmaku: DanmakuMessage) -> str:
        """
        格式化弹幕信息供LLM使用
        
        Args:
            danmaku: 弹幕消息
        
        Returns:
            格式化后的字符串
        """
        return f"[{danmaku.timestamp}] {danmaku.username}: {danmaku.content}"
    
    def format_recent_danmaku(self, danmaku_list: List[DanmakuMessage]) -> str:
        """
        格式化最近弹幕列表供LLM使用
        
        Args:
            danmaku_list: 弹幕列表
        
        Returns:
            格式化后的字符串
        """
        if not danmaku_list:
            return "暂无弹幕"
        
        lines = [f"共 {len(danmaku_list)} 条弹幕:\n"]
        for danmaku in danmaku_list:
            lines.append(self.format_danmaku_for_llm(danmaku))
        
        return "\n".join(lines)
