"""
E2E 测试脚本：测试 ASR-LLM-TTS 流程

流程：
1. 用 TTS 生成测试音频（"你好，请介绍一下你自己"）
2. 用 ASR 识别生成的音频
3. 用 LLM 处理识别的文本
4. 用 TTS 输出 LLM 的响应
"""
import asyncio
import websockets
import json
import base64
import wave
import os
import io
import time
from pathlib import Path

# 后端 WebSocket 地址
WS_URL = "ws://localhost:8001/ws"

# 参考音频路径（用于 TTS 克隆音色）
REF_AUDIO_PATH = r"c:\CX-O\CosyVoice-main\asset\zero_shot_prompt.wav"

# 测试文本
TEST_TEXT = "你好，请介绍一下你自己"

# 输出目录
OUTPUT_DIR = Path("c:/CX-O/tests/e2e_output")


async def tts_synthesize(ws, text: str, ref_audio_path: str = None) -> bytes:
    """调用 TTS 服务生成音频"""
    print(f"[TTS] 正在合成文本: {text}")
    
    # 读取参考音频（如果存在）
    ref_audio_base64 = None
    if ref_audio_path and os.path.exists(ref_audio_path):
        with open(ref_audio_path, "rb") as f:
            ref_audio_base64 = base64.b64encode(f.read()).decode("utf-8")
        print(f"[TTS] 使用参考音频: {ref_audio_path}")
    
    # 发送 TTS 合成请求
    request = {
        "action": "tts.synthesize",
        "request_id": "tts-001",
        "data": {
            "text": text,
            "engine": "orpheus",  # 使用 Orpheus TTS
            "voice": "tara",  # Orpheus 预设音色
        }
    }
    
    if ref_audio_base64:
        request["data"]["ref_audio_base64"] = ref_audio_base64
    
    await ws.send(json.dumps(request))
    
    # 接收响应
    response_raw = await ws.recv()
    response = json.loads(response_raw)
    
    if response.get("type") == "error":
        print(f"[TTS] 错误: {response}")
        return None
    
    # 提取音频数据
    audio_data = response.get("data", {}).get("audio_base64")
    if audio_data:
        audio_bytes = base64.b64decode(audio_data)
        print(f"[TTS] 合成成功，音频大小: {len(audio_bytes)} bytes")
        return audio_bytes
    else:
        print(f"[TTS] 响应格式异常: {response}")
        return None


async def asr_recognize(ws, audio_bytes: bytes) -> str:
    """调用 ASR 服务识别音频"""
    print(f"[ASR] 正在识别音频，大小: {len(audio_bytes)} bytes")
    
    # 发送 ASR 识别请求
    request = {
        "action": "asr.recognize_base64",
        "request_id": "asr-001",
        "data": {
            "audio_base64": base64.b64encode(audio_bytes).decode("utf-8"),
            "language": "auto"
        }
    }
    
    await ws.send(json.dumps(request))
    
    # 接收响应
    response_raw = await ws.recv()
    response = json.loads(response_raw)
    
    if response.get("type") == "error":
        print(f"[ASR] 错误: {response}")
        return None
    
    # 提取识别文本
    text = response.get("data", {}).get("text")
    if text:
        print(f"[ASR] 识别成功: {text}")
        return text
    else:
        print(f"[ASR] 响应格式异常: {response}")
        return None


async def llm_chat(ws, text: str) -> str:
    """调用 LLM 进行对话"""
    print(f"[LLM] 正在处理文本: {text}")
    
    # 发送聊天请求
    request = {
        "action": "chat.message",
        "request_id": "chat-001",
        "data": {
            "agent_id": "test-agent",
            "content": text,
            "stream": False
        }
    }
    
    await ws.send(json.dumps(request))
    
    # 接收响应
    response_raw = await ws.recv()
    response = json.loads(response_raw)
    
    if response.get("type") == "error":
        print(f"[LLM] 错误: {response}")
        return None
    
    # 提取回复文本
    content = response.get("data", {}).get("content")
    if content:
        print(f"[LLM] 回复成功: {content[:100]}...")
        return content
    else:
        print(f"[LLM] 响应格式异常: {response}")
        return None


def save_audio(audio_bytes: bytes, filename: str):
    """保存音频文件"""
    output_path = OUTPUT_DIR / filename
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, "wb") as f:
        f.write(audio_bytes)
    print(f"[保存] 音频已保存: {output_path}")


async def main():
    """主测试流程"""
    print("=" * 60)
    print("E2E 测试：ASR-LLM-TTS 流程")
    print("=" * 60)
    
    # 连接 WebSocket
    print(f"[连接] 正在连接: {WS_URL}")
    try:
        ws = await websockets.connect(WS_URL)
        print("[连接] 成功")
    except Exception as e:
        print(f"[连接] 失败: {e}")
        return
    
    try:
        # Step 1: 用 TTS 生成测试音频
        print("\n--- Step 1: TTS 合成测试音频 ---")
        test_audio = await tts_synthesize(ws, TEST_TEXT)
        
        if not test_audio:
            print("[错误] TTS 合成失败，尝试使用预设音频")
            # 使用预设参考音频作为测试输入
            if os.path.exists(REF_AUDIO_PATH):
                with open(REF_AUDIO_PATH, "rb") as f:
                    test_audio = f.read()
                print(f"[备用] 使用参考音频: {REF_AUDIO_PATH}")
            else:
                print("[错误] 无可用音频，测试终止")
                return
        
        save_audio(test_audio, "step1_tts_output.wav")
        
        # Step 2: 用 ASR 识别音频
        print("\n--- Step 2: ASR 识别音频 ---")
        recognized_text = await asr_recognize(ws, test_audio)
        
        if not recognized_text:
            print("[错误] ASR 识别失败，使用预设文本继续测试")
            recognized_text = TEST_TEXT
        
        print(f"[识别结果] {recognized_text}")
        
        # Step 3: 用 LLM 处理文本
        print("\n--- Step 3: LLM 处理文本 ---")
        llm_response = await llm_chat(ws, recognized_text)
        
        if not llm_response:
            print("[错误] LLM 处理失败")
            llm_response = "我是一个测试助手，很高兴为您服务。"
        
        print(f"[LLM 回复] {llm_response[:200]}...")
        
        # Step 4: 用 TTS 输出 LLM 响应
        print("\n--- Step 4: TTS 合成 LLM 响应 ---")
        response_audio = await tts_synthesize(ws, llm_response[:100])  # 截取前100字符避免过长
        
        if response_audio:
            save_audio(response_audio, "step4_tts_response.wav")
            print("[完成] E2E 测试成功！")
        else:
            print("[警告] TTS 合成响应失败")
        
        # 测试总结
        print("\n" + "=" * 60)
        print("E2E 测试总结")
        print("=" * 60)
        print(f"TTS 合成: {'成功' if test_audio else '失败'}")
        print(f"ASR 识别: {'成功' if recognized_text else '失败'}")
        print(f"LLM 处理: {'成功' if llm_response else '失败'}")
        print(f"TTS 响应: {'成功' if response_audio else '失败'}")
        print("\n输出文件:")
        print(f"  - {OUTPUT_DIR / 'step1_tts_output.wav'}")
        print(f"  - {OUTPUT_DIR / 'step4_tts_response.wav'}")
        
    except Exception as e:
        print(f"[异常] 测试过程中发生错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await ws.close()
        print("[关闭] WebSocket 连接已关闭")


if __name__ == "__main__":
    asyncio.run(main())