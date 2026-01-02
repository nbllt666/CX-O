#!/usr/bin/env python3
"""
FastAPI主控路由

功能：
- 消息发送接口
- 插件注册接口
- 心跳上报接口
- 工具列表接口
- 事件推送接口
- 配置管理接口
"""

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime
import logging
import json
import base64

logger = logging.getLogger(__name__)

router = APIRouter()

# 存储插件信息
plugins: Dict[str, Dict] = {}

# 存储工具列表
tools_registry: List[Dict] = []


class ChatRequest(BaseModel):
    """聊天请求"""
    text: Optional[str] = None
    session_id: Optional[str] = None


class ChatResponse(BaseModel):
    """聊天响应"""
    status: str
    session_id: str
    message: str


class PluginRegisterRequest(BaseModel):
    """插件注册请求"""
    port: int
    name: str
    tools: List[Dict]
    capabilities: List[str] = []


class HeartbeatRequest(BaseModel):
    """心跳请求"""
    port: int


class EventPushRequest(BaseModel):
    """事件推送请求"""
    from_port: int
    event_type: str
    data: Dict[str, Any]


class ToolCallRequest(BaseModel):
    """工具调用请求"""
    tool_name: str
    arguments: Dict[str, Any]


@router.post("/chat", response_model=ChatResponse)
async def send_message(request: ChatRequest):
    """
    发送用户消息
    
    支持：
    - 纯文本消息
    - 多模态消息（文本+图像+音频）
    """
    try:
        # 生成session_id
        session_id = request.session_id or f"sess_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
        
        logger.info(f"收到消息: session_id={session_id}, text={request.text}")
        
        # TODO: 实际处理消息（调用主模型）
        # 这里先返回接收确认
        
        return ChatResponse(
            status="accepted",
            session_id=session_id,
            message="消息已收到，正在处理..."
        )
    
    except Exception as e:
        logger.error(f"处理消息失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat/multimodal")
async def send_multimodal(
    text: Optional[str] = Form(None),
    image: Optional[UploadFile] = File(None),
    audio: Optional[UploadFile] = File(None),
    session_id: Optional[str] = Form(None)
):
    """
    发送多模态消息（支持文本+图像+音频）
    
    Form fields:
    - text: 文本描述（可选）
    - image: 图片文件（可选）
    - audio: 音频文件（可选）
    - session_id: 会话ID（可选）
    """
    try:
        session_id = session_id or f"sess_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
        
        # 处理图像
        image_data = None
        if image and image.filename:
            image_content = await image.read()
            image_data = base64.b64encode(image_content).decode()
            logger.info(f"收到图片: {image.filename}, 大小: {len(image_content)} bytes")
        
        # 处理音频
        audio_data = None
        if audio and audio.filename:
            audio_content = await audio.read()
            audio_data = base64.b64encode(audio_content).decode()
            logger.info(f"收到音频: {audio.filename}, 大小: {len(audio_content)} bytes")
        
        # TODO: 调用主模型处理多模态输入
        
        return {
            "status": "accepted",
            "session_id": session_id,
            "message": "多模态消息已收到，正在处理...",
            "received": {
                "text": text is not None,
                "has_image": image_data is not None,
                "has_audio": audio_data is not None
            }
        }
    
    except Exception as e:
        logger.error(f"处理多模态消息失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/register")
async def register_plugin(request: PluginRegisterRequest):
    """
    注册插件
    
    注册成功后，插件的工具会被添加到tools列表中
    """
    try:
        plugin_key = str(request.port)
        
        plugins[plugin_key] = {
            "name": request.name,
            "port": request.port,
            "tools": request.tools,
            "capabilities": request.capabilities,
            "registered_at": datetime.now().isoformat()
        }
        
        # 更新全局工具列表
        for tool in request.tools:
            tools_registry.append({
                "name": tool["name"],
                "from_port": request.port,
                "plugin_name": request.name,
                **tool
            })
        
        logger.info(f"插件注册成功: {request.name}, port={request.port}, tools={len(request.tools)}")
        
        return {"status": "ok", "message": f"插件 {request.name} 注册成功"}
    
    except Exception as e:
        logger.error(f"插件注册失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/heartbeat")
async def heartbeat(request: HeartbeatRequest):
    """
    心跳上报
    
    主控每30秒未收到心跳，则自动下线该插件所有工具
    """
    try:
        plugin_key = str(request.port)
        
        if plugin_key in plugins:
            plugins[plugin_key]["last_heartbeat"] = datetime.now().isoformat()
            logger.debug(f"收到心跳: port={request.port}")
            return {"status": "alive"}
        else:
            logger.warning(f"未知插件心跳: port={request.port}")
            return {"status": "unknown", "message": "插件未注册"}
    
    except Exception as e:
        logger.error(f"处理心跳失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tools")
async def get_tools():
    """
    获取可用工具列表
    """
    return tools_registry


@router.post("/event/push")
async def push_event(request: EventPushRequest):
    """
    插件主动推送事件
    
    例如：QQ消息、日程提醒、传感器数据等
    """
    try:
        logger.info(f"收到事件推送: from_port={request.from_port}, type={request.event_type}")
        
        # TODO: 通过WebSocket推送给所有连接的客户端
        
        return {"status": "received"}
    
    except Exception as e:
        logger.error(f"处理事件推送失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tools/call")
async def call_tool(request: ToolCallRequest):
    """
    手动调用工具
    """
    try:
        logger.info(f"工具调用: {request.tool_name}, 参数: {request.arguments}")
        
        # TODO: 查找并调用工具
        
        return {
            "status": "success",
            "tool": request.tool_name,
            "result": {}
        }
    
    except Exception as e:
        logger.error(f"工具调用失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ========== 配置管理接口 ==========

@router.get("/config")
async def get_config():
    """获取当前配置"""
    try:
        with open("config.json", 'r', encoding='utf-8') as f:
            config = json.load(f)
        return config
    except Exception as e:
        logger.error(f"读取配置失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/config")
async def save_config(config: Dict[str, Any]):
    """保存配置"""
    try:
        with open("config.json", 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        logger.info("配置已保存")
        return {"status": "success", "message": "配置已保存"}
    except Exception as e:
        logger.error(f"保存配置失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ========== 记忆管理接口 ==========

@router.get("/memory")
async def get_memories(session_id: str = None, limit: int = 10):
    """获取记忆列表"""
    # TODO: 调用记忆管理器
    return {"memories": []}


@router.post("/memory")
async def add_memory(data: Dict[str, Any]):
    """添加记忆"""
    # TODO: 调用记忆管理器
    return {"status": "success", "message": "记忆已添加"}


@router.delete("/memory/{memory_id}")
async def delete_memory(memory_id: str):
    """删除记忆"""
    # TODO: 调用记忆管理器
    return {"status": "success", "message": f"记忆 {memory_id} 已删除"}


# ========== 弹幕管理接口 ==========

@router.get("/danmaku")
async def get_danmaku(count: int = 10, only_raw: bool = True):
    """获取弹幕"""
    # TODO: 调用弹幕缓存管理器
    return {"danmaku": []}


@router.get("/danmaku/stats")
async def get_danmaku_stats():
    """获取弹幕统计"""
    # TODO: 调用弹幕缓存管理器
    return {
        "raw_count": 0,
        "audited_count": 0,
        "approved_count": 0,
        "rejected_count": 0
    }
