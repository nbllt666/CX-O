#!/usr/bin/env python3
"""
文本音效解析器

功能：
- 扫描音效目录
- 解析文本中的音效标记
- 分割文本供TTS合成
"""

from pathlib import Path
from typing import List, Dict
import re
import logging

logger = logging.getLogger(__name__)


class EffectParser:
    """文本音效解析器"""
    
    # 匹配音效标记的正则表达式（全角括号）
    EFFECT_PATTERN = re.compile(r'（([^）]+)）')
    
    def __init__(self, effects_dir: str = "data/effects"):
        """
        初始化音效解析器
        
        Args:
            effects_dir: 音效文件目录
        """
        self.effects_dir = Path(effects_dir)
        self.available_effects = self._scan_effects()
        
        logger.info(f"音效解析器初始化完成: dir={effects_dir}, effects={len(self.available_effects)}")
    
    def _scan_effects(self) -> List[str]:
        """扫描音效目录，获取可用的音效文件列表"""
        effects = []
        
        if self.effects_dir.exists():
            for f in self.effects_dir.glob("*.wav"):
                # 去掉扩展名作为音效名
                effects.append(f.stem)
        
        if effects:
            logger.info(f"扫描到 {len(effects)} 个音效文件: {effects}")
        
        return effects
    
    def parse_text_with_effects(self, text: str) -> List[Dict]:
        """
        解析包含音效标记的文本
        
        格式：文本内容（音效名）文本内容（音效名2）...
        
        Args:
            text: 输入文本
        
        Returns:
            解析后的片段列表，每个片段包含:
            - type: "text" 或 "sound"
            - content: 文本内容 或 音效文件名
        """
        parts = []
        last_end = 0
        
        for match in self.EFFECT_PATTERN.finditer(text):
            # 1. 添加音效标记前的文本片段
            text_before = text[last_end:match.start()]
            if text_before.strip():
                parts.append({
                    "type": "text",
                    "content": text_before.strip()
                })
            
            # 2. 添加音效片段
            effect_name = match.group(1)
            effect_file = f"{effect_name}.wav"
            
            # 验证音效是否存在
            if effect_name in self.available_effects:
                parts.append({
                    "type": "sound",
                    "file": effect_file,
                    "name": effect_name
                })
            else:
                # 音效不存在，作为普通文本处理
                parts.append({
                    "type": "text",
                    "content": f"（{effect_name}）"
                })
            
            last_end = match.end()
        
        # 3. 添加最后的文本片段
        if last_end < len(text):
            text_after = text[last_end:]
            if text_after.strip():
                parts.append({
                    "type": "text",
                    "content": text_after.strip()
                })
        
        return parts
    
    def split_text_for_tts(self, text: str) -> List[str]:
        """
        仅为TTS提取需要合成的文本片段
        
        Args:
            text: 输入文本
        
        Returns:
            需要TTS合成的文本列表（按顺序）
        """
        parts = self.parse_text_with_effects(text)
        
        text_parts = []
        for part in parts:
            if part["type"] == "text":
                text_parts.append(part["content"])
        
        return text_parts
    
    def get_effect_file_path(self, effect_name: str) -> str:
        """
        获取音效文件路径
        
        Args:
            effect_name: 音效名称
        
        Returns:
            音效文件路径，不存在返回None
        """
        effect_file = self.effects_dir / f"{effect_name}.wav"
        
        if effect_file.exists():
            return str(effect_file)
        
        return None
    
    def generate_system_prompt(self) -> str:
        """生成音效相关的系统提示词片段"""
        if not self.available_effects:
            return ""
        
        effect_list = "\n".join(
            f"- （{effect}）: {effect}.wav"
            for effect in self.available_effects
        )
        
        return f"""
## 可用音效
系统支持在回复中嵌入音效，使用以下格式：
- （音效文件名）：在回复中嵌入音效

例如：你好（ding）很高兴见到你！

可用的音效文件：
{effect_list}

注意：音效文件位于 data/effects/ 目录，文件名不包含扩展名。
使用音效时，使用全角括号：xxx（effect_name）yyy
"""
    
    def extract_effect_names(self, text: str) -> List[str]:
        """
        从文本中提取所有音效名称
        
        Args:
            text: 输入文本
        
        Returns:
            音效名称列表
        """
        effects = []
        
        for match in self.EFFECT_PATTERN.finditer(text):
            effect_name = match.group(1)
            if effect_name in self.available_effects:
                effects.append(effect_name)
        
        return effects
    
    def has_effects(self, text: str) -> bool:
        """
        检查文本是否包含有效音效标记
        
        Args:
            text: 输入文本
        
        Returns:
            是否包含有效音效
        """
        for match in self.EFFECT_PATTERN.finditer(text):
            effect_name = match.group(1)
            if effect_name in self.available_effects:
                return True
        
        return False
    
    def render_effects_to_html(self, text: str) -> str:
        """
        将音效标记渲染为HTML（用于WebUI显示）
        
        Args:
            text: 输入文本
        
        Returns:
            渲染后的HTML
        """
        parts = self.parse_text_with_effects(text)
        
        html_parts = []
        
        for part in parts:
            if part["type"] == "text":
                # 转义HTML特殊字符
                content = part["content"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                html_parts.append(content)
            else:
                # 音效标记
                html_parts.append(f'<span class="effect-tag" data-effect="{part["name"]}">（{part["name"]}）</span>')
        
        return "".join(html_parts)
