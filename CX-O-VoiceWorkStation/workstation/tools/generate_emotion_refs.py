"""
情感参考音频预生成工具
# TODO(Task 5): 重构为基于 voxcpm 的参考音频生成
"""
import argparse
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(
        description="Generate emotion and transition reference audio files"
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

    parser.parse_args()

    # TODO(Task 5): 重构为基于 voxcpm 的参考音频生成
    logger.error("参考音频生成重构中：Task 5 将重构为 voxcpm")
    return 1


if __name__ == "__main__":
    sys.exit(main())
