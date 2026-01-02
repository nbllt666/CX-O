📚 CX-O 完整接口文档（ 多模态 + 流式 + 主动推送）
项目定位：本地运行、支持图文音输入、流式输出、插件可主动上报的 AI 智能体平台
协议：HTTP + WebSocket
架构：主控路由 + 插件热插拔 + 主动推送 + ACP 联网

🧭 总体架构

text
[客户端]
↓ ↑ (HTTP / WS)
[CX-O 主控 :8000] ←→ [插件A :8081]
↗ ↑ ↖ [插件B :8082]
[音频/图像上传] [ACP → 远程 Agent]
↓
[TTS 流式音频 + 文字 via WS]
↑
[QQ 消息推送 ← 插件QQ]
✅ 插件可主动推送事件（如 QQ 消息、日程提醒、传感器数据）

🔌 一、主控后端接口（默认端口 8000）
1. 发送用户消息 💬（支持文本 + 图像 + 音频）
方法一：纯文本（JSON）
路径：POST /chat
Content-Type: application/json
请求体：
json
{
"text": "昨天有人找我吗？"
}

方法二：图文/音混合输入（Multipart）
路径：POST /chat
Content-Type: multipart/form-data
字段说明：
text（可选）：附加描述
image（可选）：图片文件（.png, .jpg）
audio（可选）：语音文件（.wav, .mp3）
支持任意组合：仅图、图文、仅音频、音文、全都有！
响应：
json
{
"status": "accepted",
"session_id": "sess_xyz123",
"message": "已收到输入，正在处理..."
}
实际结果通过 WebSocket 推送

2. CXFC插件注册 🔗（支持多个工具）
路径：POST /register
请求体：
json
{
"port": 8081,
"name": "全能助手插件",
"tools": [
{
"name": "generate_image",
"description": "生成一张图片",
"parameters": { "type": "object", "properties": { "prompt": { "type": "string" } }, "required": ["prompt"] }
},
{
"name": "describe_image",
"description": "描述图片内容",
"parameters": { "type": "object", "properties": { "image_url": { "type": "string" } } }
}
],
"capabilities": ["event_push"] // 声明支持主动推送
}
成功响应：{ "status": "ok" }
✅ capabilities 字段用于声明插件能力，如：
event_push：可主动推送事件
realtime_tts：支持实时语音合成
background_service：后台常驻服务

3. CXFC心跳上报 🫀
路径：POST /heartbeat
请求体：
json
{ "port": 8081 }
响应：
json
{ "status": "alive" }
主控每 30 秒未收到心跳，则自动下线该插件所有工具

4. 获取可用工具列表 🔍
路径：GET /tools
响应：
json
[
{
"name": "generate_image",
"from_port": 8081,
"plugin_name": "全能助手插件"
},
{
"name": "tts_speak",
"from_port": 8082,
"plugin_name": "语音合成"
}
]

5. ACP Connect：连接其他 Agent 🤝
发起连接
路径：POST /acp/connect
请求体：
json
{
"target_url": "http://192.168.1.100:8000",
"alias": "roommate-agent"
}
响应：
json
{
"status": "connected",
"agent_info": {
"id": "agent_xyz",
"name": "室友的小助手",
"capabilities": ["greet", "play_music"]
}
}

断开连接
DELETE /acp/connect/{alias}

⚡ 二、插件主动推送接口

为了让插件能主动上报事件（如 QQ 消息、日程提醒、传感器报警），主控提供 事件接收端点。
1. 插件主动推送事件到 Agent
路径：POST /event/push
Content-Type: application/json
请求体：
json
{
"from_port": 8081,
"event_type": "notification",
"data": {
"title": "QQ 消息",
"from": "张三",
"content": "今晚一起吃饭吗？",
"timestamp": "2025-04-05T19:30:00Z"
}
}
响应：
json
{ "status": "received" }
主控收到后，立即通过 WebSocket 推送给所有连接的前端（如 Unity）

2. 前端接收主动事件格式（WebSocket）

json
{
"event": "external_event",
"data": {
"source": "QQ插件",
"type": "notification",
"title": "QQ 消息",
"body": "张三：今晚一起吃饭吗？"
}
}
前端可弹出通知、播放提示音、记录日志等

3. 典型场景：QQ 插件主动上报消息

python
qq_plugin.py
import requests
import time

def on_new_message(sender, msg):
# 主动推送给 Agent
try:
requests.post("http://localhost:8000/event/push", json={
"from_port": 8083,
"event_type": "notification",
"data": {
"title": "QQ 消息",
"from": sender,
"content": msg,
"timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ")
}
})
except:
pass # 忽略错误
模拟监听 QQ 消息
while True:
msg = listen_qq_message()
if msg:
on_new_message(msg.sender, msg.text)

🌀 三、流式响应接口（WebSocket）
1. WebSocket 连接地址
路径：ws://localhost:8000/ws/chat
参数（可选）：
session_id=sess_xyz123：绑定特定会话
2. 推送事件类型

event data 说明
------ ------ ------
thinking {} 开始思考
text_chunk {text, is_final} 流式文字
audio_stream_start {mime_type, speech_id} 音频流开始
action {type, url, ...} 动作指令
external_event {source, type, title, body} 外部事件（如 QQ 消息）
response_done {status} 响应结束

3. 典型交互流程（含主动推送）

text
用户 → 发送：“昨天有人找我吗？”
主控 → 返回 session_id → 前端开始监听 WS

← {"event": "thinking"}
← {"event": "text_chunk", data: {text: "有，张三昨天通过QQ问你"}}
← binary (TTS 音频)
← {"event": "response_done"}

同时 → QQ插件监听到新消息 → 主动 POST /event/push
← {"event": "external_event", data: {title: "QQ", body: "李四：在吗？"}}
→ 前端弹出通知

