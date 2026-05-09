"""
F5-TTS 推理接口封装
提供内嵌 TTS 推理能力
"""
from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_f5tts_instance = None


def get_f5tts() -> Optional[object]:
    """获取 F5TTS 实例"""
    global _f5tts_instance
    return _f5tts_instance


def load_model() -> bool:
    """加载 F5-TTS 模型"""
    global _f5tts_instance
    if _f5tts_instance is not None:
        return True

    try:
        from f5_tts.api import F5TTS
        logger.info("Loading F5-TTS model...")
        _f5tts_instance = F5TTS()
        logger.info("F5-TTS model loaded successfully!")
        return True
    except ImportError as e:
        logger.error(f"F5-TTS not available: {e}")
        return False
    except Exception as e:
        logger.error(f"Error loading F5-TTS model: {e}")
        return False


def infer(
    ref_file: str,
    ref_text: str,
    gen_text: str,
    output_path: Optional[str] = None,
    speed: float = 1.0,
    cross_fade_duration: float = 0.15,
    nfe_step: int = 32,
    cfg_strength: int = 2,
    seed: int = -1,
    remove_silence: bool = False,
) -> tuple:
    """
    使用 F5-TTS 进行推理

    Returns:
        tuple: (wav, sr, spect) 或 (None, None, None)
    """
    if _f5tts_instance is None:
        if not load_model():
            raise RuntimeError("F5-TTS model not available")

    try:
        result = _f5tts_instance.infer(
            ref_file=ref_file,
            ref_text=ref_text,
            gen_text=gen_text,
            show_info=print,
            target_rms=0.1,
            cross_fade_duration=cross_fade_duration,
            sway_sampling_coef=-1,
            cfg_strength=cfg_strength,
            nfe_step=nfe_step,
            speed=speed,
            remove_silence=remove_silence,
            file_wave=output_path,
            seed=seed,
        )
        return result
    except Exception as e:
        logger.error(f"F5-TTS inference error: {e}")
        raise


def is_available() -> bool:
    """检查 F5-TTS 是否可用"""
    try:
        from f5_tts.api import F5TTS
        return True
    except ImportError:
        return False
