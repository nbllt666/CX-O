"""CXFC 技能注册表——插件技能的定义注册与查询。"""
from typing import List, Dict, Any

from .models import SkillDefinition


class SkillRegistry:
    """技能注册表——按插件注册/注销技能，并支持按关键词或事件检索技能。"""

    def __init__(self):
        self._skills: Dict[str, SkillDefinition] = {}

    def register_skill(self, skill: SkillDefinition):
        key = f"{skill.source_plugin_id}:{skill.name}"
        self._skills[key] = skill

    def unregister_skills(self, plugin_id: str):
        keys_to_remove = [k for k in self._skills if k.startswith(f"{plugin_id}:")]
        for key in keys_to_remove:
            del self._skills[key]

    def find_by_keywords(self, message: str) -> List[SkillDefinition]:
        message_lower = message.lower()
        matched = []
        for skill in self._skills.values():
            for keyword in skill.trigger_keywords:
                if keyword.lower() in message_lower:
                    matched.append(skill)
                    break
        return matched

    def find_by_event(self, event_type: str) -> List[SkillDefinition]:
        matched = []
        for skill in self._skills.values():
            if event_type in skill.trigger_events:
                matched.append(skill)
        return matched

    def get_all_skills(self) -> List[SkillDefinition]:
        return list(self._skills.values())

    def render_template(self, template: str, variables: Dict[str, Any]) -> str:
        result = template
        for key, value in variables.items():
            result = result.replace(f"{{{{{key}}}}}", str(value))
        return result
