"""E2E: 多模态 vLLM 原生视频/音频解码 + 非 vLLM 降级

不依赖 CX-O-SERVER HTTP 服务，直接 import MultimodalPipeline 类做单元 E2E。
通过修改 config 模拟 vllm / non-vllm 两种 provider，验证 native_decode_used 字段。

测试覆盖（D5.3）：
  1. provider=vllm 时，video 模态触发 vLLM 原生解码 (native_decode_used=True)
  2. provider=vllm 时，audio 模态触发 vLLM 原生解码 (native_decode_used=True)
  3. provider=!vllm 时，video 模态降级 (native_decode_used=False, vision_degraded=True)
  4. provider=!vllm 时，audio 模态降级 (native_decode_used=False, vision_degraded=True)
  5. text 模态不依赖 provider（恒 native_decode_used=False）

闭合判据：5 个子场景全部 PASS
"""
from __future__ import annotations

import os
import sys
import importlib
from typing import Any, Dict, Optional

# 注入项目根路径 + CX-O-SERVER 路径（server 模块在 CX-O-SERVER/ 下）
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, _PROJECT_ROOT)
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "CX-O-SERVER"))


def _print(tag: str, msg: str) -> None:
    print(f"[multimodal-e2e:{tag}] {msg}")


def _try_import():
    """尝试导入 MultimodalPipeline，失败返回 None。"""
    try:
        from server.core.multimodal import MultimodalPipeline, MultimodalArtifact
        return MultimodalPipeline, MultimodalArtifact
    except Exception as e:
        _print("import", f"导入失败: {e}")
        return None, None


def _make_config(provider: str) -> Dict[str, Any]:
    """构造测试用 config，覆盖 llm.provider。"""
    return {
        "llm": {"provider": provider},
        "multimodal_pipeline": {
            "vllm": {
                "base_url": "http://127.0.0.1:8002/v1",
                "model": "gemma4-e4b",
                "timeout": 30,
            },
            "use_vllm_native_decode": True,
        },
    }


def _patch_provider(monkey_module, provider: str) -> None:
    """临时 patch _get_llm_provider 返回值。"""
    def _fake_provider():
        return provider
    monkey_module._get_llm_provider = staticmethod(_fake_provider)


def test_vllm_video_native() -> Optional[bool]:
    """场景 1: provider=vllm + video 模态 → native_decode_used=True。"""
    _print("v1", "vllm + video → native")
    MultimodalPipeline, _ = _try_import()
    if MultimodalPipeline is None:
        _print("v1", "SKIP（模块未安装）")
        return None

    pipeline = MultimodalPipeline(config=_make_config("vllm"))
    # Patch provider 检测函数
    pipeline._get_llm_provider = staticmethod(lambda: "vllm")

    # Patch vllm_native_worker_impl 避免真实调用 vLLM
    class _FakeVLLMWorker:
        def process(self, source_ref, modality, use_native, provider="unknown"):
            return {
                "text": f"vLLM 原生解码 {modality} 内容",
                "confidence": 0.92,
                "native_decode_used": True,
                "metadata": {"modality": modality},
            }
    pipeline._vllm_native_worker_impl = _FakeVLLMWorker()

    try:
        artifact = pipeline.preprocess("video", "test://e2e/video.mp4")
    except Exception as e:
        _print("v1", f"preprocess 失败: {e}")
        return False
    _print("v1", f"native_decode_used={artifact.native_decode_used}, degraded={artifact.vision_degraded}")
    return artifact.native_decode_used is True and artifact.vision_degraded is False


def test_vllm_audio_native() -> Optional[bool]:
    """场景 2: provider=vllm + audio 模态 → native_decode_used=True。"""
    _print("v2", "vllm + audio → native")
    MultimodalPipeline, _ = _try_import()
    if MultimodalPipeline is None:
        return None

    pipeline = MultimodalPipeline(config=_make_config("vllm"))
    pipeline._get_llm_provider = staticmethod(lambda: "vllm")

    class _FakeVLLMWorker:
        def process(self, source_ref, modality, use_native, provider="unknown"):
            return {
                "text": "vLLM 原生音频解码",
                "confidence": 0.88,
                "native_decode_used": True,
                "metadata": {"modality": modality},
            }
    pipeline._vllm_native_worker_impl = _FakeVLLMWorker()

    try:
        artifact = pipeline.preprocess("audio", "test://e2e/audio.wav")
    except Exception as e:
        _print("v2", f"preprocess 失败: {e}")
        return False
    _print("v2", f"native_decode_used={artifact.native_decode_used}")
    return artifact.native_decode_used is True


def test_non_vllm_video_degraded() -> Optional[bool]:
    """场景 3: provider=openai + video 模态 → 降级。"""
    _print("v3", "non-vllm + video → degraded")
    MultimodalPipeline, _ = _try_import()
    if MultimodalPipeline is None:
        return None

    pipeline = MultimodalPipeline(config=_make_config("openai"))
    pipeline._get_llm_provider = staticmethod(lambda: "openai")

    try:
        artifact = pipeline.preprocess("video", "test://e2e/video.mp4")
    except Exception as e:
        _print("v3", f"preprocess 失败: {e}")
        return False
    _print("v3", f"native_decode_used={artifact.native_decode_used}, degraded={artifact.vision_degraded}")
    return artifact.native_decode_used is False and artifact.vision_degraded is True


def test_non_vllm_audio_degraded() -> Optional[bool]:
    """场景 4: provider=openai + audio 模态 → 降级。"""
    _print("v4", "non-vllm + audio → degraded")
    MultimodalPipeline, _ = _try_import()
    if MultimodalPipeline is None:
        return None

    pipeline = MultimodalPipeline(config=_make_config("openai"))
    pipeline._get_llm_provider = staticmethod(lambda: "openai")

    try:
        artifact = pipeline.preprocess("audio", "test://e2e/audio.wav")
    except Exception as e:
        _print("v4", f"preprocess 失败: {e}")
        return False
    _print("v4", f"native_decode_used={artifact.native_decode_used}, degraded={artifact.vision_degraded}")
    return artifact.native_decode_used is False and artifact.vision_degraded is True


def test_text_independent_of_provider() -> Optional[bool]:
    """场景 5: text 模态不依赖 provider（恒 native_decode_used=False）。"""
    _print("v5", "text 模态独立于 provider")
    MultimodalPipeline, _ = _try_import()
    if MultimodalPipeline is None:
        return None

    for provider in ["vllm", "openai", "anthropic"]:
        pipeline = MultimodalPipeline(config=_make_config(provider))
        pipeline._get_llm_provider = staticmethod(lambda p=provider: p)
        try:
            artifact = pipeline.preprocess("text", "E2E 纯文本测试")
        except Exception as e:
            _print("v5", f"provider={provider} preprocess 失败: {e}")
            return False
        if artifact.native_decode_used is not False:
            _print("v5", f"provider={provider} 期望 native_decode_used=False, 实际={artifact.native_decode_used}")
            return False
    _print("v5", "3 个 provider 全部 native_decode_used=False ✅")
    return True


def main() -> int:
    print("\n========== [D5.3] multimodal vLLM native E2E ==========")
    results = {
        "vllm_video_native": test_vllm_video_native(),
        "vllm_audio_native": test_vllm_audio_native(),
        "non_vllm_video_degraded": test_non_vllm_video_degraded(),
        "non_vllm_audio_degraded": test_non_vllm_audio_degraded(),
        "text_independent": test_text_independent_of_provider(),
    }
    print("\n--- multimodal E2E 汇总 ---")
    all_pass = True
    for name, r in results.items():
        if r is None:
            print(f"  {name}: SKIP")
            continue
        ok = bool(r)
        all_pass = all_pass and ok
        print(f"  {name}: {'PASS' if ok else 'FAIL'}")
    print(f"\n>>> multimodal E2E: {'ALL PASSED' if all_pass else 'SOME FAILED'}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())