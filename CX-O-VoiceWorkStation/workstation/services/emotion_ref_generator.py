"""
情感参考音频生成器（基于 VoxCPM）

支持两种生成模式：
- clone（克隆模式）：以用户参考音频通过「可控声音克隆」生成情感参考音频，
  可选 ultimate_clone 高级选项（参考音频 + 文本续写）。
- design（提示词模式）：先用「音色设计」创建基础参考音频，
  再以它为参考通过「可控声音克隆」生成情感参考音频。

过渡音频统一通过「音色设计」(voxcpm 提示词控制) 生成。

产出结构（兼容 CX-O-SERVER load_emotion_voices 消费方）：
- {voice_refs}/emotions/{emotion}/ref.wav
- {voice_refs}/emotions/{emotion}/ref.txt
- {voice_refs}/emotions/emotion_mapping.json   （格式 A，优先）
- {voice_refs}/transitions/{from}_to_{to}.wav
- {voice_refs}/refs_meta.json                    （匹配前端 ImportEmotionRefsResponse.meta）
"""
from __future__ import annotations

import json
import logging
import os
import zipfile
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# 默认 8 情感列表（Ekman 基本情感扩展），过渡数为 8*(8-1)=56，合计 64 个参考音频。
_DEFAULT_EMOTIONS: dict[str, dict[str, str]] = {
    "neutral": {"text": "这是一个中性的陈述句。", "control": "平静、中性的语气，正常语速，无明显情绪起伏"},
    "happy": {"text": "今天真是太开心了，一切都刚刚好！", "control": "开心、愉快的语气，语速稍快，句尾上扬，充满活力"},
    "sad": {"text": "这件事让我感到很难过。", "control": "悲伤、低落的语气，语速稍慢，声音低沉，带有叹息感"},
    "angry": {"text": "我对这种行为感到非常愤怒！", "control": "愤怒、激动的语气，语速快，重音强烈，情绪激烈"},
    "fearful": {"text": "那个声音让我感到害怕。", "control": "恐惧、紧张的语气，语速不稳，声音颤抖，带有压迫感"},
    "disgusted": {"text": "这种做法真让人厌恶。", "control": "厌恶、不屑的语气，语速偏慢，带有嫌弃的腔调"},
    "surprised": {"text": "怎么会发生这种事！", "control": "惊讶、意外的语气，语速快，音调升高，带有惊叹感"},
    "calm": {"text": "让我们平静地思考一下。", "control": "沉稳、平静的语气，语速舒缓，气息均匀，放松自然"},
}

# 提示词模式下的基础音色描述（用于 design 创建基础参考音频）。
_DESIGN_BASE_CONTROL = "一个成年说话人的中性嗓音，音色温和清晰，发音标准，无明显地方口音"

# emotion_mapping.json 中 ref_audio 的相对路径前缀（与 CX-O-SERVER emotion_refs_dir 契约对齐）。
_EMOTION_REFS_REL_DIR = "data/voice_refs/emotions"

# design 模式中间基础参考音频落盘目录（必须位于 data/input 下，以满足
# VoxCPMClient._validate_audio_path 对 controllable_clone 参考音频的约束）。
_DESIGN_TMP_SUBDIR = ".emotion_ref_design"


class EmotionRefGenerator:
    """基于 VoxCPM 的情感参考音频生成器。"""

    def __init__(
        self,
        output_dir: str = "data/voice_refs",
        voxcpm_client: Any | None = None,
        emotions: dict[str, dict[str, str]] | None = None,
        emotion_refs_rel_dir: str = _EMOTION_REFS_REL_DIR,
    ):
        self._output_dir = Path(output_dir)
        # 允许作为输入基准音频的根目录，默认仅允许 data/input，防止任意本地文件读取。
        self._allowed_audio_root = Path("data/input").resolve()
        self._emotion_refs_rel_dir = emotion_refs_rel_dir.rstrip("/\\")
        self._emotions = emotions if emotions is not None else dict(_DEFAULT_EMOTIONS)
        # voxcpm 客户端延迟获取：若注入则直接使用，否则在首次生成时通过工厂获取。
        self._voxcpm_client = voxcpm_client

    # ── 路径与客户端辅助 ──────────────────────────────────────────────

    def _validate_audio_path(self, audio_path: str) -> Path:
        """校验 audio_path 解析后必须位于允许的根目录之内，防止任意文件读取。"""
        audio = Path(audio_path)
        try:
            resolved = audio.resolve()
        except Exception as e:
            raise ValueError(f"Invalid audio path: {audio_path}: {e}")
        try:
            resolved.relative_to(self._allowed_audio_root)
        except ValueError:
            raise ValueError(
                f"audio path must be located under {self._allowed_audio_root}, got: {resolved}"
            )
        return resolved

    def _get_client(self):
        """获取 VoxCPMClient 实例（注入优先，否则走工厂单例）。"""
        if self._voxcpm_client is not None:
            return self._voxcpm_client
        from workstation.services.voxcpm_client import get_voxcpm_client
        from workstation.config import get_settings

        settings = get_settings()
        self._voxcpm_client = get_voxcpm_client(config=settings.voxcpm)
        return self._voxcpm_client

    # ── 路径规划 ──────────────────────────────────────────────────────

    def _emotions_dir(self) -> Path:
        return self._output_dir / "emotions"

    def _transitions_dir(self) -> Path:
        return self._output_dir / "transitions"

    def _emotion_ref_wav(self, emotion: str) -> Path:
        return self._emotions_dir() / emotion / "ref.wav"

    def _emotion_ref_txt(self, emotion: str) -> Path:
        return self._emotions_dir() / emotion / "ref.txt"

    def _transition_wav(self, from_emotion: str, to_emotion: str) -> Path:
        return self._transitions_dir() / f"{from_emotion}_to_{to_emotion}.wav"

    def _design_base_audio_path(self) -> Path:
        """提示词模式中间基础参考音频路径（位于 data/input 下）。"""
        return self._allowed_audio_root / _DESIGN_TMP_SUBDIR / "base.wav"

    # ── 主生成流程 ────────────────────────────────────────────────────

    async def generate_all(
        self,
        base_audio_path: str,
        sample_text: str = "这是参考音频样本。",
        transition_text: str = "嗯，",
        force: bool = False,
        mode: str = "clone",
        ultimate_clone: bool = False,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> dict:
        """生成全部情感参考音频与过渡音频。

        Args:
            base_audio_path: 克隆模式下用户提供的参考音频路径（必须位于 data/input 下）。
                提示词模式下该参数被忽略（可为空字符串）。
            sample_text: 情感参考音频的目标文本（覆盖默认情感文本时使用）。
            transition_text: 过渡音频文本。
            force: 为 True 时强制重新生成已存在的参考音频。
            mode: 生成模式，``clone``（克隆）或 ``design``（提示词）。
            ultimate_clone: 克隆模式高级选项，启用极致克隆（参考音频 + 文本续写）。
            progress_callback: 进度回调 ``(current, total, message)``。

        Returns:
            生成结果摘要 dict，兼容前端 PregenerateRefsResult 结构。
        """
        if mode not in ("clone", "design"):
            raise ValueError(f"Invalid mode: {mode!r}, expected 'clone' or 'design'")
        if ultimate_clone and mode != "clone":
            raise ValueError("ultimate_clone 仅在 clone 模式下可用")

        client = self._get_client()

        # 准备参考音频来源：克隆模式校验用户路径，提示词模式先 design 生成基础音频。
        if mode == "clone":
            ref_audio_path = str(self._validate_audio_path(base_audio_path))
        else:
            ref_audio_path = str(await self._prepare_design_base_audio(client, sample_text, force))

        emotions = list(self._emotions.keys())
        # 过渡为每对 (from != to) 生成一个，共 len*(len-1) 个。
        transition_pairs = [(f, t) for f in emotions for t in emotions if f != t]
        total = len(emotions) + len(transition_pairs)
        current = 0

        emotions_meta: list[dict[str, str]] = []
        emotion_mapping: dict[str, dict[str, str]] = {}
        skipped_any = False

        # 1. 生成情感参考音频（均通过 controllable_clone / ultimate_clone 生成）。
        for emotion in emotions:
            current += 1
            spec = self._emotions[emotion]
            text = sample_text or spec["text"]
            control = spec["control"]
            ref_wav = self._emotion_ref_wav(emotion)
            ref_txt = self._emotion_ref_txt(emotion)

            if ref_wav.exists() and not force:
                logger.info(f"Skip existing emotion ref: {emotion} ({ref_wav})")
                skipped_any = True
            else:
                if progress_callback:
                    progress_callback(current, total, f"生成情感参考音频: {emotion}")
                ref_wav.parent.mkdir(parents=True, exist_ok=True)
                if ultimate_clone:
                    await client.ultimate_clone(
                        text=text,
                        prompt_audio=ref_audio_path,
                        prompt_text=text,
                        output_path=str(ref_wav),
                    )
                else:
                    await client.controllable_clone(
                        text=text,
                        control=control,
                        reference_audio=ref_audio_path,
                        output_path=str(ref_wav),
                    )

            # 写 ref.txt（情感文本，供 fallback 格式 B 消费）。
            ref_txt.parent.mkdir(parents=True, exist_ok=True)
            ref_txt.write_text(text, encoding="utf-8")

            rel_file = f"emotions/{emotion}/ref.wav"
            emotions_meta.append(
                {
                    "file": rel_file,
                    "emotion": emotion,
                    "text": text,
                    "instruct_text": control,
                }
            )
            emotion_mapping[emotion] = {
                "ref_audio": f"{self._emotion_refs_rel_dir}/{emotion}/ref.wav",
                "ref_text": text,
            }

        # 2. 生成过渡音频（统一通过 design 提示词控制生成）。
        transitions_meta: list[dict[str, str]] = []
        for from_emotion, to_emotion in transition_pairs:
            current += 1
            trans_wav = self._transition_wav(from_emotion, to_emotion)
            if trans_wav.exists() and not force:
                logger.info(f"Skip existing transition: {from_emotion}->{to_emotion}")
                skipped_any = True
            else:
                if progress_callback:
                    progress_callback(
                        current, total,
                        f"生成过渡音频: {from_emotion}->{to_emotion}",
                    )
                trans_wav.parent.mkdir(parents=True, exist_ok=True)
                trans_control = self._build_transition_control(from_emotion, to_emotion)
                await client.design(
                    text=transition_text,
                    control=trans_control,
                    output_path=str(trans_wav),
                )

            transitions_meta.append(
                {
                    "file": f"transitions/{from_emotion}_to_{to_emotion}.wav",
                    "from_emotion": from_emotion,
                    "to_emotion": to_emotion,
                    "text": transition_text,
                    "instruct_text": self._build_transition_control(from_emotion, to_emotion),
                }
            )

        # 3. 写 emotion_mapping.json（格式 A，CX-O-SERVER 优先读取）。
        self._emotions_dir().mkdir(parents=True, exist_ok=True)
        mapping_path = self._emotions_dir() / "emotion_mapping.json"
        with open(mapping_path, "w", encoding="utf-8") as f:
            json.dump(emotion_mapping, f, ensure_ascii=False, indent=2)

        # 4. 写 refs_meta.json（匹配前端 ImportEmotionRefsResponse.meta）。
        meta = {"emotions": emotions_meta, "transitions": transitions_meta}
        meta_path = self._output_dir / "refs_meta.json"
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

        result = {
            "emotions": len(emotions),
            "transitions": len(transition_pairs),
            "total": total,
            "skipped": skipped_any,
        }
        logger.info(
            f"Emotion refs generated: emotions={len(emotions)}, "
            f"transitions={len(transition_pairs)}, skipped={skipped_any}"
        )
        return result

    async def _prepare_design_base_audio(self, client: Any, sample_text: str, force: bool) -> Path:
        """提示词模式：先用 design 创建基础参考音频，返回其路径（位于 data/input 下）。"""
        base_path = self._design_base_audio_path()
        if base_path.exists() and not force:
            logger.info(f"Reuse existing design base audio: {base_path}")
            return base_path
        base_path.parent.mkdir(parents=True, exist_ok=True)
        await client.design(
            text=sample_text,
            control=_DESIGN_BASE_CONTROL,
            output_path=str(base_path),
        )
        return base_path

    def _build_transition_control(self, from_emotion: str, to_emotion: str) -> str:
        """构造过渡音频的自然语言音色控制描述。"""
        from_desc = self._emotions.get(from_emotion, {}).get("control", from_emotion)
        to_desc = self._emotions.get(to_emotion, {}).get("control", to_emotion)
        return f"从「{from_emotion}」情绪过渡到「{to_emotion}」情绪：起始{from_desc}，逐渐转为{to_desc}"

    async def generate_and_pack_zip(
        self,
        base_audio_path: str,
        sample_text: str = "这是参考音频样本。",
        transition_text: str = "嗯，",
        force: bool = False,
        mode: str = "clone",
        ultimate_clone: bool = False,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> Path:
        """生成全部参考音频并打包为 zip（含 refs_meta.json）。"""
        await self.generate_all(
            base_audio_path=base_audio_path,
            sample_text=sample_text,
            transition_text=transition_text,
            force=force,
            mode=mode,
            ultimate_clone=ultimate_clone,
            progress_callback=progress_callback,
        )

        zip_path = self._output_dir / "emotion_refs.zip"
        zip_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, _dirs, files in os.walk(self._output_dir):
                for name in files:
                    if name == "emotion_refs.zip":
                        continue
                    abs_path = Path(root) / name
                    arcname = abs_path.relative_to(self._output_dir)
                    zf.write(abs_path, arcname)
        logger.info(f"Packed emotion refs zip: {zip_path}")
        return zip_path

    # ── 导入（保留原实现） ────────────────────────────────────────────

    @staticmethod
    def _safe_extract_zip(zf: zipfile.ZipFile, output_dir: Path):
        for member in zf.infolist():
            member_path = os.path.normpath(member.filename)
            if member_path.startswith("..") or os.path.isabs(member_path):
                raise ValueError(f"Unsafe path in zip: {member.filename}")
            zf.extract(member, output_dir)

    @staticmethod
    def import_from_zip(zip_path: str, output_dir: str) -> dict:
        zip_file = Path(zip_path)
        if not zip_file.exists():
            raise FileNotFoundError(f"Zip file not found: {zip_path}")

        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(zip_path, "r") as zf:
            EmotionRefGenerator._safe_extract_zip(zf, out)

        meta_path = out / "refs_meta.json"
        if not meta_path.exists():
            raise FileNotFoundError("refs_meta.json not found in zip archive")

        with open(meta_path, "r", encoding="utf-8") as f:
            meta: dict = json.load(f)

        logger.info(f"Imported emotion refs zip to: {output_dir}")
        return meta
