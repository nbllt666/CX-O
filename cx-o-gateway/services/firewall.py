"""
防火墙服务 - 弹幕三档决策
"""
import json
import logging
from typing import Dict, Optional, Any

logger = logging.getLogger(__name__)


class FirewallService:
    _instance = None
    
    def __init__(self):
        self.blacklist = set()
        self.blacklist_enabled = True
        self.llm_config = {}
        self._cxhms_client = None
        self._context_manager = None
        self._session_id = None
        
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def set_cxhms_client(self, client):
        """设置 CXHMS 客户端用于 LLM 决策"""
        self._cxhms_client = client
    
    def set_context_manager(self, context_manager, session_id: str = None):
        """设置上下文管理器和会话 ID"""
        self._context_manager = context_manager
        self._session_id = session_id
    
    def _get_context(self) -> list:
        """获取当前会话的上下文"""
        if self._context_manager and self._session_id:
            return self._context_manager.get_context(self._session_id)
        return []
    
    def load_config(self, config: dict):
        """加载配置"""
        self.blacklist = set(config.get("blocking", {}).get("blacklist", []))
        self.blacklist_enabled = config.get("blocking", {}).get("blacklist_enabled", True)
        self.llm_config = config.get("llm", {})
    
    async def decide_danmaku(self, danmaku_data: Dict) -> Dict:
        """
        弹幕决策
        返回: {
            "decision": "block|passive|reply",
            "confidence": 0.0-1.0,
            "reason": "原因",
            "added_to_context": bool,
            "reply_triggered": bool
        }
        """
        content = danmaku_data.get("content", "")
        user = danmaku_data.get("user", {})
        user_id = user.get("uid", "")
        
        # 检查黑名单
        if self.blacklist_enabled and user_id in self.blacklist:
            logger.info(f"Danmaku blocked by blacklist: user={user_id}")
            return {
                "decision": "block",
                "confidence": 1.0,
                "reason": "用户在黑名单中",
                "added_to_context": False,
                "reply_triggered": False
            }
        
        # 调用 LLM 进行决策
        result = await self._llm_decide(content, user)
        
        return result
    
    async def _llm_decide(self, content: str, user: Dict) -> Dict:
        """调用 LLM 进行决策"""
        context = self._get_context()
        prompt = self._build_decision_prompt(content, user, context)
        
        try:
            if self._cxhms_client:
                messages = context + [{"role": "user", "content": prompt}]
                
                result = await self._cxhms_client.request("chat", {
                    "messages": messages,
                    "stream": False
                }, timeout=10.0)
                
                if result.get("success") and result.get("content"):
                    response_text = result.get("content", "")
                    json_start = response_text.find('{')
                    json_end = response_text.rfind('}') + 1
                    if json_start != -1 and json_end > json_start:
                        try:
                            decision_data = json.loads(response_text[json_start:json_end])
                            decision = decision_data.get("decision", "passive")
                            confidence = decision_data.get("confidence", 0.5)
                            reason = decision_data.get("reason", "LLM决策")

                            return {
                                "decision": decision,
                                "confidence": confidence,
                                "reason": reason,
                                "added_to_context": decision != "block",
                                "reply_triggered": decision == "reply"
                            }
                        except json.JSONDecodeError:
                            logger.warning(f"Failed to parse LLM decision JSON: {response_text[json_start:json_end]}")
            
            logger.warning("LLM decision unavailable, using default")
            return {
                "decision": "passive",
                "confidence": 0.5,
                "reason": "LLM不可用，默认放行",
                "added_to_context": True,
                "reply_triggered": False
            }
            
        except Exception as e:
            logger.error(f"LLM decision error: {e}")
            return {
                "decision": "passive",
                "confidence": 0.0,
                "reason": f"决策出错: {str(e)}",
                "added_to_context": True,
                "reply_triggered": False
            }
    
    def _build_decision_prompt(self, content: str, user: Dict, context: list = None) -> str:
        """构建决策 prompt"""
        return f"""你是一个直播弹幕安全审查助手。请根据以下规则判断弹幕内容：

【弹幕内容】
{content}

【用户信息】
- 用户名: {user.get('username', '')}
- 勋章等级: {user.get('badge_level', 0)}
- 舰队等级: {user.get('guard_level', 0)}

【判断规则】
1. BLOCK (阻断): 违规内容，包括但不限于：
   - 政治敏感内容
   - 色情低俗内容
   - 暴力血腥内容
   - 垃圾广告
   - 恶意刷屏
   - 人身攻击

2. PASSIVE (放行): 正常弹幕，直接通过，但不建议回复
   - 普通问候
   - 闲聊内容
   - 简单表情

3. REPLY (回复): 优质弹幕，值得回复互动，例如：
   - 有趣的提问
   - 感谢支持
   - 有意义的互动
   - 需要回答的问题

请以 JSON 格式返回结果：
{{"decision": "block|passive|reply", "confidence": 0.0-1.0, "reason": "简要原因"}}
"""
