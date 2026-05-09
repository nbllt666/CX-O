"""
情感参考音频预生成工具
使用 CosyVoice 从基础参考音频生成 64 个情感和过渡参考音频
"""
import argparse
import asyncio
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def progress_callback(current: int, total: int, message: str) -> None:
    print(f"[{current}/{total}] {message}")


async def generate_refs(
    base_audio_path: str,
    output_base_dir: str,
    cosyvoice_url: str,
    sample_text: str,
    transition_text: str,
    skip_existing: bool = True
) -> dict:
    from workstation.services.cosyvoice_client import CosyVoiceClient

    base_audio = Path(base_audio_path)
    if not base_audio.exists():
        raise FileNotFoundError(f"Base audio file not found: {base_audio_path}")

    output_path = Path(output_base_dir)
    emotions_dir = output_path / "emotions"
    transitions_dir = output_path / "transitions"

    if skip_existing:
        existing_emotions = len(list(emotions_dir.glob("*.wav"))) if emotions_dir.exists() else 0
        existing_transitions = len(list(transitions_dir.glob("*.wav"))) if transitions_dir.exists() else 0
        if existing_emotions == 8 and existing_transitions == 56:
            logger.info("All 64 reference audio files already exist. Skipping generation.")
            return {
                "emotions": {"count": existing_emotions},
                "transitions": {"count": existing_transitions},
                "total": existing_emotions + existing_transitions,
                "skipped": True
            }

    client = CosyVoiceClient(base_url=cosyvoice_url)

    try:
        logger.info(f"Checking CosyVoice service at {cosyvoice_url}...")
        if not await client.health_check():
            raise ConnectionError(f"CosyVoice service not available at {cosyvoice_url}")
        logger.info("CosyVoice service is available")

        logger.info(f"Generating reference audio files from: {base_audio_path}")
        logger.info(f"Output directory: {output_base_dir}")

        results = await client.generate_all_refs(
            ref_audio=base_audio,
            emotions_dir=emotions_dir,
            transitions_dir=transitions_dir,
            sample_text=sample_text,
            transition_text=transition_text,
            progress_callback=progress_callback
        )

        logger.info(f"Generation complete!")
        logger.info(f"  Emotions: {len(results['emotions'])} files")
        logger.info(f"  Transitions: {len(results['transitions'])} files")
        logger.info(f"  Total: {results['total']} files")

        return results

    finally:
        await client.close()


def main():
    parser = argparse.ArgumentParser(
        description="Generate emotion and transition reference audio files using CosyVoice"
    )
    parser.add_argument(
        "--base-audio",
        type=str,
        required=True,
        help="Path to the base reference audio file (WAV format recommended)"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="data/voice_refs",
        help="Output directory for generated reference audio files (default: data/voice_refs)"
    )
    parser.add_argument(
        "--cosyvoice-url",
        type=str,
        default="http://127.0.0.1:50000",
        help="CosyVoice service URL (default: http://127.0.0.1:50000)"
    )
    parser.add_argument(
        "--sample-text",
        type=str,
        default="这是参考音频样本。",
        help="Sample text for emotion reference audio generation"
    )
    parser.add_argument(
        "--transition-text",
        type=str,
        default="嗯，",
        help="Sample text for transition reference audio generation"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force regeneration even if files exist"
    )

    args = parser.parse_args()

    try:
        results = asyncio.run(generate_refs(
            base_audio_path=args.base_audio,
            output_base_dir=args.output_dir,
            cosyvoice_url=args.cosyvoice_url,
            sample_text=args.sample_text,
            transition_text=args.transition_text,
            skip_existing=not args.force
        ))

        if results.get("skipped"):
            print("\nAll reference audio files already exist. Use --force to regenerate.")
        else:
            print(f"\nSuccessfully generated {results['total']} reference audio files.")

        return 0

    except FileNotFoundError as e:
        logger.error(f"File not found: {e}")
        return 1
    except ConnectionError as e:
        logger.error(f"Service unavailable: {e}")
        return 2
    except Exception as e:
        logger.error(f"Generation failed: {e}")
        return 3


if __name__ == "__main__":
    sys.exit(main())
