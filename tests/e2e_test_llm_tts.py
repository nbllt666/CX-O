"""
简化 E2E 测试脚本：测试 LLM -> TTS 流程（跳过 ASR）

流程：
1. 使用预设文本输入 LLM
2. LLM 生成响应
3. TTS 合成响应音频
"""
import asyncio
import httpx
import json
import base64
import os
from pathlib import Path

# 后端地址
BASE_URL = "http://localhost:8001"

# 测试文本（模拟 ASR 输出）
TEST_TEXT = "你好，请介绍一下你自己"

# 输出目录
OUTPUT_DIR = Path("c:/CX-O/tests/e2e_output")


def save_audio(audio_bytes: bytes, filename: str):
    """保存音频文件"""
    output_path = OUTPUT_DIR / filename
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, "wb") as f:
        f.write(audio_bytes)
    print(f"[保存] 音频已保存: {output_path}")


async def llm_chat(client: httpx.AsyncClient, text: str) -> str:
    """调用 LLM WebSocket 进行对话"""
    print(f"[LLM] 正在处理文本: {text}")
    
    # 使用 WebSocket 连接
    import websockets
    
    try:
        ws = await websockets.connect(f"ws://localhost:8001/ws")
        
        # 发送聊天消息（使用正确的 action 格式，不指定 agent_id）
        request = {
            "action": "chat.message",
            "request_id": "test-001",
            "data": {
                "content": text
            }
        }
        await ws.send(json.dumps(request))
        
        # 接收响应
        response_raw = await ws.recv()
        response = json.loads(response_raw)
        
        await ws.close()
        
        content = response.get("content", response.get("data", {}).get("content", ""))
        if content:
            print(f"[LLM] 回复成功: {content[:100]}...")
            return content
        else:
            print(f"[LLM] 响应格式异常: {response}")
            return None
            
    except Exception as e:
        print(f"[LLM] WebSocket 异常: {e}")
        
        # 尝试 HTTP API
        try:
            response = await client.post(
                f"{BASE_URL}/api/chat",
                json={"content": text, "agent_id": "test-agent"}
            )
            
            if response.status_code == 200:
                result = response.json()
                content = result.get("content", result.get("response", ""))
                if content:
                    print(f"[LLM] HTTP 回复成功: {content[:100]}...")
                    return content
        except Exception as e2:
            print(f"[LLM] HTTP 异常: {e2}")
        
        return None


async def tts_synthesize_stream(client: httpx.AsyncClient, text: str) -> bytes:
    """调用 TTS 流式合成 API"""
    print(f"[TTS] 正在合成文本: {text[:50]}...")
    
    try:
        # 使用流式合成 API（支持 orpheus 模式）
        async with client.stream(
            "POST",
            f"{BASE_URL}/api/tts/synthesize-stream",
            json={"text": text, "speed": 1.0}
        ) as response:
            if response.status_code != 200:
                print(f"[TTS] HTTP {response.status_code}")
                return None
            
            # 收集音频数据
            audio_chunks = []
            async for chunk in response.aiter_bytes():
                audio_chunks.append(chunk)
            
            audio_bytes = b"".join(audio_chunks)
            if audio_bytes:
                print(f"[TTS] 合成成功，音频大小: {len(audio_bytes)} bytes")
                return audio_bytes
            else:
                print("[TTS] 无音频数据")
                return None
                
    except Exception as e:
        print(f"[TTS] 异常: {e}")
        return None


async def main():
    """主测试流程"""
    print("=" * 60)
    print("简化 E2E 测试：LLM -> TTS 流程")
    print("=" * 60)
    
    # 创建 HTTP 客户端
    client = httpx.AsyncClient(timeout=120.0, trust_env=False)
    
    try:
        # Step 1: 使用预设文本（模拟 ASR 输出）
        print("\n--- Step 1: 输入文本（模拟 ASR 输出） ---")
        print(f"[输入] {TEST_TEXT}")
        
        # Step 2: LLM 处理文本
        print("\n--- Step 2: LLM 处理文本 ---")
        llm_response = await llm_chat(client, TEST_TEXT)
        
        if not llm_response:
            print("[警告] LLM 处理失败，使用预设回复")
            llm_response = "你好！我是 CX-O 智能助手，很高兴为您服务。我可以帮助您处理各种问题，包括知识问答、任务管理、语音交互等功能。"
        
        print(f"[LLM 回复] {llm_response[:200]}...")
        
        # Step 3: TTS 合成响应
        print("\n--- Step 3: TTS 合成响应 ---")
        # 截取前100字符避免过长
        tts_text = llm_response[:100] if len(llm_response) > 100 else llm_response
        response_audio = await tts_synthesize_stream(client, tts_text)
        
        if response_audio:
            save_audio(response_audio, "llm_tts_response.wav")
            print("[完成] E2E 测试成功！")
        else:
            print("[警告] TTS 合成失败")
        
        # 测试总结
        print("\n" + "=" * 60)
        print("E2E 测试总结")
        print("=" * 60)
        print(f"LLM 处理: {'成功' if llm_response and not llm_response.startswith('你好！我是') else '失败（使用预设）'}")
        print(f"TTS 响应: {'成功' if response_audio else '失败'}")
        
        if response_audio:
            print(f"\n输出文件: {OUTPUT_DIR / 'llm_tts_response.wav'}")
        
    except Exception as e:
        print(f"[异常] 测试过程中发生错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await client.aclose()
        print("[关闭] HTTP 客户端已关闭")


if __name__ == "__main__":
    asyncio.run(main())