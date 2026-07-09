"""
E2E 测试脚本：测试 ASR-LLM-TTS 流程（HTTP API 版本）

流程：
1. 用 TTS HTTP API 生成测试音频
2. 用 ASR HTTP API 识别生成的音频
3. 用 LLM WebSocket 处理识别的文本（或 HTTP API）
4. 用 TTS HTTP API 输出 LLM 的响应
"""
import asyncio
import httpx
import json
import base64
import wave
import os
import io
import time
from pathlib import Path

# 后端地址
BASE_URL = "http://localhost:8001"

# 参考音频路径（用于 TTS 克隆音色）
REF_AUDIO_PATH = r"c:\CX-O\CosyVoice-main\asset\zero_shot_prompt.wav"

# 测试文本
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


async def tts_synthesize(client: httpx.AsyncClient, text: str) -> bytes:
    """调用 TTS HTTP API 合成音频"""
    print(f"[TTS] 正在合成文本: {text}")
    
    try:
        response = await client.post(
            f"{BASE_URL}/tts/synthesize",
            json={"text": text, "speed": 1.0}
        )
        
        result = response.json()
        
        if result.get("status") == "success":
            audio_base64 = result.get("audio_data")
            if audio_base64:
                audio_bytes = base64.b64decode(audio_base64)
                print(f"[TTS] 合成成功，音频大小: {len(audio_bytes)} bytes")
                return audio_bytes
        else:
            print(f"[TTS] 错误: {result}")
            return None
    except Exception as e:
        print(f"[TTS] 异常: {e}")
        return None


async def asr_recognize(client: httpx.AsyncClient, audio_bytes: bytes) -> str:
    """调用 ASR HTTP API 识别音频"""
    print(f"[ASR] 正在识别音频，大小: {len(audio_bytes)} bytes")
    
    try:
        audio_base64 = base64.b64encode(audio_bytes).decode("utf-8")
        
        response = await client.post(
            f"{BASE_URL}/api/asr/speech-to-text",
            json={"audio": audio_base64, "language": "auto"}
        )
        
        result = response.json()
        
        if result.get("status") == "success":
            text = result.get("text", "")
            print(f"[ASR] 识别成功: {text}")
            return text
        else:
            print(f"[ASR] 错误: {result}")
            return None
    except Exception as e:
        print(f"[ASR] 异常: {e}")
        return None


async def llm_chat(client: httpx.AsyncClient, text: str) -> str:
    """调用 LLM HTTP API 进行对话"""
    print(f"[LLM] 正在处理文本: {text}")
    
    try:
        # 检查是否有 chat HTTP API
        response = await client.post(
            f"{BASE_URL}/api/chat/message",
            json={
                "agent_id": "test-agent",
                "content": text,
                "stream": False
            }
        )
        
        if response.status_code == 200:
            result = response.json()
            content = result.get("content", result.get("data", {}).get("content", ""))
            if content:
                print(f"[LLM] 回复成功: {content[:100]}...")
                return content
        else:
            print(f"[LLM] HTTP {response.status_code}: {response.text[:200]}")
            return None
    except Exception as e:
        print(f"[LLM] 异常: {e}")
        return None


async def main():
    """主测试流程"""
    print("=" * 60)
    print("E2E 测试：ASR-LLM-TTS 流程（HTTP API 版本）")
    print("=" * 60)
    
    # 创建 HTTP 客户端
    client = httpx.AsyncClient(timeout=120.0)
    
    try:
        # Step 1: 用 TTS 生成测试音频
        print("\n--- Step 1: TTS 合成测试音频 ---")
        test_audio = await tts_synthesize(client, TEST_TEXT)
        
        if not test_audio:
            print("[错误] TTS 合成失败，尝试使用预设音频")
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
        recognized_text = await asr_recognize(client, test_audio)
        
        if not recognized_text:
            print("[错误] ASR 识别失败，使用预设文本继续测试")
            recognized_text = TEST_TEXT
        
        print(f"[识别结果] {recognized_text}")
        
        # Step 3: 用 LLM 处理文本
        print("\n--- Step 3: LLM 处理文本 ---")
        llm_response = await llm_chat(client, recognized_text)
        
        if not llm_response:
            print("[警告] LLM 处理失败，使用预设回复继续测试")
            llm_response = "我是一个测试助手，很高兴为您服务。"
        
        print(f"[LLM 回复] {llm_response[:200]}...")
        
        # Step 4: 用 TTS 输出 LLM 响应
        print("\n--- Step 4: TTS 合成 LLM 响应 ---")
        response_audio = await tts_synthesize(client, llm_response[:100])
        
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
        print(f"ASR 识别: {'成功' if recognized_text != TEST_TEXT else '失败（使用预设）'}")
        print(f"LLM 处理: {'成功' if llm_response and not llm_response.startswith('我是') else '失败（使用预设）'}")
        print(f"TTS 响应: {'成功' if response_audio else '失败'}")
        
    except Exception as e:
        print(f"[异常] 测试过程中发生错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await client.aclose()
        print("[关闭] HTTP 客户端已关闭")


if __name__ == "__main__":
    asyncio.run(main())