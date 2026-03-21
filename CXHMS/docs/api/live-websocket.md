# Live WebSocket API 文档

## 概述

Live WebSocket API 提供直播客户端与 CX-O 网关之间的双向通信接口，用于接收音频/视频流和弹幕消息，并发送 TTS 音频流和前端标记。

## 连接信息

```
WebSocket 端点: ws://<gateway-host>:8100/ws/live
```

## 消息格式

### 客户端 → 网关消息

#### 1. 连接信息 (connect)

客户端连接时发送的初始消息，包含客户端类型和前端配置。

```json
{
    "type": "connect",
    "data": {
        "client_type": "web" | "mobile" | "bilibili" | "rdf",
        "room_id": "12345678",
        "audio_enabled": true,
        "video_enabled": false,
        "frontend_type": "web",
        "supported_markers": ["live2d", "emotion", "effect", "custom"],
        "marker_config": {
            "live2d": {
                "actions": ["wave", "jump", "dance", "idle", "wave_hand"],
                "default_duration": 2000
            },
            "emotion": {
                "types": ["happy", "sad", "angry", "surprised", "tender"],
                "default_intensity": 0.5
            },
            "effect": {
                "effects": ["fireworks", "hearts", "confetti"]
            },
            "custom": {
                "actions": ["custom_action_1", "custom_action_2"]
            }
        }
    }
}
```

**字段说明：**
| 字段 | 类型 | 说明 |
|------|------|------|
| client_type | string | 客户端类型 |
| room_id | string | 直播间 ID |
| audio_enabled | boolean | 是否启用音频 |
| video_enabled | boolean | 是否启用视频 |
| frontend_type | string | 前端类型 |
| supported_markers | array | 前端支持的标记类型 |
| marker_config | object | 标记配置详情 |

#### 2. 弹幕消息 (danmaku)

客户端发送的弹幕消息。

```json
{
    "type": "danmaku",
    "data": {
        "source": "bilibili",
        "room_id": "12345678",
        "user": {
            "uid": "123456",
            "username": "用户名",
            "badge_level": 0,
            "badge_name": "",
            "is_vip": false,
            "is_svip": false,
            "is_admin": false,
            "is_owner": false,
            "guard_level": 0
        },
        "content": "弹幕内容",
        "timestamp": 1234567890
    }
}
```

**字段说明：**
| 字段 | 类型 | 说明 |
|------|------|------|
| source | string | 弹幕来源 (bilibili/rdf) |
| room_id | string | 直播间 ID |
| user | object | 用户信息 |
| content | string | 弹幕内容 |
| timestamp | number | 时间戳 |

#### 3. 音频帧 (audio_frame)

二进制音频数据帧。

```
二进制数据帧
```

### 网关 → 客户端消息

#### 1. 连接确认 (ack)

网关对客户端连接的确认响应。

```json
{
    "type": "ack",
    "client_id": "abc123-def456",
    "status": "connected"
}
```

#### 2. 弹幕处理结果 (danmaku_result)

弹幕经过防火墙决策后的处理结果。

```json
{
    "type": "danmaku_result",
    "data": {
        "original_content": "弹幕内容",
        "decision": "block" | "passive" | "reply",
        "added_to_context": true | false,
        "reply_triggered": true | false,
        "user": {
            "uid": "123456",
            "username": "用户名"
        }
    }
}
```

**决策说明：**
| 决策 | 说明 |
|------|------|
| block | 违规弹幕，丢弃 |
| passive | 正常弹幕，加入上下文，不触发回复 |
| reply | 优质弹幕，加入上下文，触发回复 |

#### 3. TTS 音频流 (tts_audio)

TTS 合成的音频流数据。

```json
{
    "type": "tts_audio",
    "data": {
        "chunk_index": 0,
        "audio_data": "<base64 encoded audio>",
        "text_segment": "回复文本片段",
        "is_final": false
    }
}
```

#### 4. 文本流 (text)

LLM 回复的文本流。

```json
{
    "type": "text",
    "data": {
        "content": "LLM 回复文本",
        "chunk_index": 0,
        "is_final": false
    }
}
```

#### 5. 前端标记 (frontend_marker)

前端专供的标记，用于控制 live2D 虚拟形象等前端元素。

```json
{
    "type": "frontend_marker",
    "data": {
        "marker_type": "live2d" | "emotion" | "effect" | "custom",
        "marker_content": {
            "action": "wave",
            "duration": 2000,
            "params": {}
        },
        "split_index": 1
    }
}
```

**标记类型说明：**
| 类型 | 说明 | 参数 |
|------|------|------|
| live2d | 控制 Live2D 动作 | action, duration |
| emotion | 控制情感表情 | emotion, intensity |
| effect | 控制前端特效 | effect_name, duration |
| custom | 自定义动作 | action, params |

## 使用示例

### Python 示例

```python
import asyncio
import websockets
import json
import base64

async def connect_to_live():
    uri = "ws://localhost:8100/ws/live"
    async with websockets.connect(uri) as websocket:
        # 1. 发送连接信息
        await websocket.send(json.dumps({
            "type": "connect",
            "data": {
                "client_type": "web",
                "room_id": "12345678",
                "supported_markers": ["live2d", "emotion"],
                "marker_config": {
                    "live2d": {
                        "actions": ["wave", "jump"],
                        "default_duration": 2000
                    }
                }
            }
        }))
        
        # 2. 接收连接确认
        response = await websocket.recv()
        print(f"Connected: {response}")
        
        # 3. 接收消息
        while True:
            message = await websocket.recv()
            print(f"Received: {message}")

asyncio.run(connect_to_live())
```

### JavaScript 示例

```javascript
const ws = new WebSocket('ws://localhost:8100/ws/live');

ws.onopen = () => {
    // 1. 发送连接信息
    ws.send(JSON.stringify({
        type: 'connect',
        data: {
            client_type: 'web',
            room_id: '12345678',
            supported_markers: ['live2d', 'emotion'],
            marker_config: {
                live2d: {
                    actions: ['wave', 'jump'],
                    default_duration: 2000
                }
            }
        }
    }));
};

ws.onmessage = (event) => {
    const message = JSON.parse(event.data);
    console.log('Received:', message);
};
```

## 错误码

| 错误码 | 说明 |
|--------|------|
| 1000 | 正常关闭 |
| 1001 | 客户端离开 |
| 1002 | 协议错误 |
| 1006 | 异常关闭 |
| 1011 | 服务器错误 |
