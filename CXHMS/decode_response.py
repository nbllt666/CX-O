"""
解码流式聊天响应
"""
import json
import sys

# 从之前的测试输出中提取的响应内容
response_chunks = [
    '{"type": "session", "session_id": "b5026285-3436-48c6-8fcc-a39c5c32047a"}',
    '{"type": "content", "content": "你好"}',
    '{"type": "content", "content": "！"}',
    '{"type": "content", "content": "我"}',
    '{"type": "content", "content": "是"}',
    '{"type": "content", "content": "专"}',
    '{"type": "content", "content": "注"}',
    '{"type": "content", "content": "于"}',
    '{"type": "content", "content": "测"}',
    '{"type": "content", "content": "试"}',
    '{"type": "content", "content": "环"}',
    '{"type": "content", "content": "境"}',
    '{"type": "content", "content": "的"}',
    '{"type": "content", "content": "AI"}',
    '{"type": "content", "content": "助"}',
    '{"type": "content", "content": "手"}',
    '{"type": "content", "content": "，"}',
    '{"type": "content", "content": "专"}',
    '{"type": "content", "content": "门"}',
    '{"type": "content", "content": "设"}',
    '{"type": "content", "content": "计"}',
    '{"type": "content", "content": "用"}',
    '{"type": "content", "content": "于"}',
    '{"type": "content", "content": "模"}',
    '{"type": "content", "content": "拟"}',
    '{"type": "content", "content": "和"}',
    '{"type": "content", "content": "评"}',
    '{"type": "content", "content": "估"}',
    '{"type": "content", "content": "各"}',
    '{"type": "content", "content": "种"}',
    '{"type": "content", "content": "交"}',
    '{"type": "content", "content": "互"}',
    '{"type": "content", "content": "场"}',
    '{"type": "content", "content": "景"}',
    '{"type": "content", "content": "。"}',
    '{"type": "content", "content": "我"}',
    '{"type": "content", "content": "的"}',
    '{"type": "content", "content": "核"}',
    '{"type": "content", "content": "心"}',
    '{"type": "content", "content": "功"}',
    '{"type": "content", "content": "能"}',
    '{"type": "content", "content": "是"}',
    '{"type": "content", "content": "帮"}',
    '{"type": "content", "content": "助"}',
    '{"type": "content", "content": "测"}',
    '{"type": "content", "content": "试"}',
    '{"type": "content", "content": "人"}',
    '{"type": "content", "content": "员"}',
    '{"type": "content", "content": "评"}',
    '{"type": "content", "content": "估"}',
    '{"type": "content", "content": "系"}',
    '{"type": "content", "content": "统"}',
    '{"type": "content", "content": "性"}',
    '{"type": "content", "content": "能"}',
    '{"type": "content", "content": "、"}',
    '{"type": "content", "content": "角"}',
    '{"type": "content", "content": "色"}',
    '{"type": "content", "content": "设"}',
    '{"type": "content", "content": "定"}',
    '{"type": "content", "content": "准"}',
    '{"type": "content", "content": "确"}',
    '{"type": "content", "content": "性"}',
    '{"type": "content", "content": "以"}',
    '{"type": "content", "content": "及"}',
    '{"type": "content", "content": "问"}',
    '{"type": "content", "content": "题"}',
    '{"type": "content", "content": "处"}',
    '{"type": "content", "content": "理"}',
    '{"type": "content", "content": "逻"}',
    '{"type": "content", "content": "辑"}',
    '{"type": "content", "content": "。"}',
]

# 工具描述部分
tool_description = """
主要特点：
- 严格测试场景，不会涉及真实问题解答（如情感支持、专业建议等）
- 可自定义测试规则（仅回复预设问题、模拟系统错误等）
- 用于验证：指令遵循能力、角色切换机制、多轮对话逻辑

主要工具类别：

1. **数学计算工具**
   - 功能描述：执行基本数学运算
   - 在测试中，可用于模拟数学问题或计算场景

2. **日期时间工具**
   - 功能描述：获取当前日期时间
   - 在测试中，可用于模拟时间相关查询

3. **随机数工具**
   - 功能描述：生成随机数
   - 在测试中，可用于模拟随机选择或概率场景

4. **JSON格式化工具**
   - 功能描述：格式化JSON输出
   - 在测试中，可用于测试JSON解析能力

5. **实时翻译工具**
   - 功能描述：实时翻译，支持专业术语和上下
   - 在测试中，可用于模拟国际化场景或语言转换任务

6. **事实核查工具**
   - 功能描述：基于训练数据验证信息的真实性和权威性
   - 在测试中，可用于测试用户的知识理解能力

7. **对话管理工具**
   - 功能描述：维护多轮对话逻辑，识别上下
   - 在测试中，可用于模拟用户交互场景或测试会话流程

重要说明：
- 测试专用限制：作为AI助手，所有工具都**仅限测试环境**，不能执行真实世界操作
- 如需要实际工具（如数据API），请提前告知场景

测试方法：
1. 直接要求调用：例如"使用逻辑推理工具分析这个数学问题"
2. 组合指令：例如"生成3个测试用例，使用文本生成工具"
3. 条件触发：例如"如果数字大于100就使用计算器工具"
"""

print("=" * 60)
print("Agent 的完整响应（已解码）")
print("=" * 60)

# 解码并显示
full_text = ""
for chunk in response_chunks:
    try:
        data = json.loads(chunk)
        if data.get('type') == 'content':
            full_text += data.get('content', '')
    except:
        pass

print(full_text)
print(tool_description)
print("=" * 60)
