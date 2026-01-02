### 🌐 API调用指南（含流式输出）

vLLM服务启动后，会提供一个与OpenAI API兼容的接口，基础URL通常是 `http://localhost:8000/v1`（如果你映射了其他端口，如8010，则需相应更改）。

#### 普通非流式调用
使用Python客户端进行简单的聊天补全调用示例 ：
```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1", # 如果端口映射为8010，则改为8010
    api_key="EMPTY"  # vLLM默认不需要鉴权，但某些版本需要随便填个key
)

completion = client.chat.completions.create(
    model="Qwen2.5-7B-Instruct", # 与 --served-model-name 一致
    messages=[
        {"role": "user", "content": "请用一句话介绍人工智能。"}
    ],
    max_tokens=100,
    temperature=0.7
)
print(completion.choices[0].message.content)
```

#### 实现流式输出
流式输出对于实现类似ChatGPT的打字机效果至关重要，它能显著提升用户体验。vLLM原生支持此功能 。

在Python中，你只需要在调用时设置 `stream=True`，然后迭代返回的响应即可 ：
```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8000/v1", api_key="EMPTY")

stream = client.chat.completions.create(
    model="Qwen2.5-7B-Instruct",
    messages=[
        {"role": "user", "content": "给我讲一个关于坚持不懈的故事。"}
    ],
    max_tokens=500,
    temperature=0.7,
    stream=True  # 启用流式输出
)

for chunk in stream:
    # 检查是否有新的内容增量
    if chunk.choices[0].delta.content is not None:
        print(chunk.choices[0].delta.content, end="", flush=True) # 逐块打印
```
**流式输出的核心原理**是服务器端每生成一小段Token（例如4个）就立即发送给客户端，而不是等待整个响应完成 。这依赖于Server-Sent Events (SSE) 协议 。

#### 多模态调用示例
对于支持多模态的模型，API调用方式类似，但消息体中的 `content` 可以是一个包含图像和文本的列表。图像通常需要以Base64编码格式传入 。
```python
# 注意：这是一个简化的示例，实际使用时需要先进行图像编码等操作
completion = client.chat.completions.create(
    model="Qwen2-VL-7B-Instruct",
    messages=[
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}}, # 替换为你的图片base64数据
                {"type": "text", "text": "描述一下这张图片。"}
            ]
        }
    ],
    max_tokens=300
)
```


🛠️ 工具调用（Tool Calling）

vLLM 支持与 OpenAI API 兼容的工具调用功能，让您能够定义函数供大语言模型在对话过程中调用。这一功能对于构建能够与外部系统交互的智能应用至关重要。
🚀 快速入门
服务端配置

要启用工具调用功能，需在启动 vLLM 服务时添加特定参数。以下是使用 Llama 3.1 模型的示例：

bash
vllm serve meta-llama/Llama-3.1-8B-Instruct \
--enable-auto-tool-choice \
--tool-call-parser llama3_json \
--chat-template examples/tool_chat_template_llama3.1_json.jinja
客户端调用示例

python
from openai import OpenAI
import json

client = OpenAI(base_url="http://localhost:8000/v1", api_key="EMPTY")
定义工具函数
def get_weather(location: str, unit: str):
return f"正在获取 {location} 的天气，单位为 {unit}..."
定义工具 schema
tools = [{
"type": "function",
"function": {
"name": "get_weather",
"description": "获取指定地点的当前天气",
"parameters": {
"type": "object",
"properties": {
"location": {"type": "string", "description": "城市和州，例如 'San Francisco, CA'"},
"unit": {"type": "string", "enum": ["celsius", "fahrenheit"]}
},
"required": ["location", "unit"]
}
}
}]
发送请求
response = client.chat.completions.create(
model="meta-llama/Llama-3.1-8B-Instruct",
messages=[{"role": "user", "content": "旧金山的天气怎么样？"}],
tools=tools,
tool_choice="auto" # 可选: "auto", "none" 或指定特定函数
)
处理工具调用
if response.choices[0].message.tool_calls:
tool_call = response.choices[0].message.tool_calls[0].function
print(f"调用的函数: {tool_call.name}")
print(f"参数: {tool_call.arguments}")

# 执行函数并获取结果
args = json.loads(tool_call.arguments)
result = get_weather(*args)
print(f"结果: {result}")

# 将结果返回给模型（完整对话流程）
messages = [
{"role": "user", "content": "旧金山的天气怎么样？"},
{
"role": "assistant",
"tool_calls": [{
"id": response.choices[0].message.tool_calls[0].id,
"type": "function",
"function": {
"name": tool_call.name,
"arguments": tool_call.arguments
}
}]
},
{
"role": "tool",
"tool_call_id": response.choices[0].message.tool_calls[0].id,
"content": result
}
]

# 获取最终回复
final_response = client.chat.completions.create(
model="meta-llama/Llama-3.1-8B-Instruct",
messages=messages
)
print(f"最终回复: {final_response.choices[0].message.content}")
🔧 支持的模型与配置

vLLM 为不同模型提供专门的工具调用解析器，以下是常用配置：
Llama 3.1 系列
bash
--tool-call-parser llama3_json \
--chat-template examples/tool_chat_template_llama3_json.jinja

支持模型：meta-llama/Meta-Llama-3.1-8B/70B/405B-Instruct
Hermes 系列
bash
--tool-call-parser hermes

支持模型：NousResearch/Hermes-2-Pro-, NousResearch/Hermes-3-*
Mistral 系列
bash
--tool-call-parser mistral \
--chat-template examples/tool_chat_template_mistral_parallel.jinja

支持模型：mistralai/Mistral-7B-Instruct-v0.3 等
Python 风格工具调用
bash
--tool-call-parser pythonic \
--chat-template examples/tool_chat_template_llama3.2_pythonic.jinja

支持模型：meta-llama/Llama-3.2-1B/3B-Instruct, Team-ACE/ToolACE-8B
🤖 高级用法
指定特定工具

除了 tool_choice="auto"，您还可以强制模型使用特定工具：

python
tool_choice = {
"type": "function",
"function": {"name": "get_weather"}
}

response = client.chat.completions.create(
# 其他参数不变...
tool_choice=tool_choice
)
流式工具调用

流式响应同样支持工具调用，处理方式略有不同：

python
stream = client.chat.completions.create(
# 参数同上...
stream=True
)

full_response = ""
for chunk in stream:
if chunk.choices[0].delta.content:
print(chunk.choices[0].delta.content, end="", flush=True)
full_response += chunk.choices[0].delta.content
if chunk.choices[0].delta.tool_calls:
# 处理流式工具调用
print("\n[检测到工具调用]", flush=True)
自定义工具解析器

对于不支持的模型，您可以开发自定义工具解析器插件：

1. 创建插件文件 my_tool_parser.py:
python
from vllm.entrypoints.openai.tool_parsers import ToolParser
from vllm.entrypoints.openai.tool_parsers import ToolParserManager

@ToolParserManager.register_module(["my_parser"])
class MyCustomToolParser(ToolParser):
# 实现必要的方法
pass

2. 启动服务时指定插件：
bash
--enable-auto-tool-choice \
--tool-parser-plugin /path/to/my_tool_parser.py \
--tool-call-parser my_parser \
--chat-template /path/to/chat_template.jinja
⚠️ 注意事项

1. 工具调用流程：工具调用通常需要多轮对话完成，包括工具调用请求、工具执行和结果返回。
2. 命名限制：函数名应使用小写字母和下划线，避免特殊字符。
3. 参数验证：始终验证模型返回的参数，避免注入攻击。
4. 模型能力：较小的模型（如7B级别）在复杂工具调用场景中可能表现不佳。
5. 性能影响：首次使用命名函数调用时会有延迟，因为引导式解码后端需要编译有限状态机(FSM)。

工具调用功能为LLM应用打开了与外部世界交互的大门，正确使用它可以让您的应用更加智能和实用！
