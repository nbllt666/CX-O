"""
So-VITS-SVC 推理服务（ModelStation 试听副本）

自 CX-O-VoiceWorkStation/workstation/services/sovits_svc_infer.py 迁移
（change-id: split-audio-workstation-cxfc-modelstation）。

按 spec「infer 双副本处置声明」：本副本与 VWS（翻唱）副本自此独立演化、互不同步、
不设同步义务；共享行为契约仅为「以子进程调用 engines/so-vits-svc-4.1-Stable/ 推理脚本」
（2026-09-05 起引擎位于 CXO-ModelStation/engines/）。

ModelStation 侧差异：
- 输出目录默认注入 audition_dir（试听产物，经 /api/audio-files/audition 播放）；
- infer 输入白名单根为可注入列表，默认 = 训练数据目录 ∪ data/input
  （使数据集音频可直接试听）；
- 模型路径校验根为 models_dir（训练产出目录）与上游 logs 目录。
"""
from __future__ import annotations

import asyncio
import json
import logging
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Optional, Union

from modelstation.config import get_settings

logger = logging.getLogger(__name__)

# 推理子进程超时（秒）。覆盖 So-VITS-SVC 默认较长的推理时间，但避免挂死。
_INFER_TIMEOUT_SECONDS = 300.0


async def _communicate_with_timeout(process: asyncio.subprocess.Process, timeout: float) -> tuple[bytes, bytes]:
    """对 process.communicate() 做超时包装；超时后先 terminate 再 kill 兜底。"""
    try:
        return await asyncio.wait_for(process.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        logger.error(
            f"Subprocess timeout after {timeout}s (pid={process.pid}); terminating..."
        )
        try:
            process.terminate()
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(process.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            logger.error(f"Subprocess did not exit after terminate, killing (pid={process.pid})")
            try:
                process.kill()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                pass
        raise


class SoVITSSVCInferer:
    def __init__(
        self,
        model_path: Optional[str] = None,
        output_dir: Optional[str] = None,
        so_vits_svc_dir: str = "",
        python_path: str = "",
        allowed_audio_roots: Optional[list[Union[str, Path]]] = None,
        models_dir: Optional[str] = None,
    ):
        """构造推理器。

        Args:
            model_path: 默认模型路径（也可在 infer() 调用时传入）
            output_dir: 试听输出目录；None 时取配置 audition_dir
            so_vits_svc_dir: 上游引擎仓库根；空串时取配置 so_vits_svc_dir
            python_path: 子进程 Python 解释器；空串时取配置 python_path
            allowed_audio_roots: 推理输入白名单根列表；None 时默认
                [training_data_dir, input_dir]（训练数据目录 ∪ data/input）
            models_dir: 模型路径校验根；None 时取配置 models_dir
        """
        settings = get_settings()
        self._model_path = model_path
        self._output_dir = Path(output_dir) if output_dir else Path(settings.sovits_svc.audition_dir)
        self._so_vits_svc_dir = (
            Path(so_vits_svc_dir) if so_vits_svc_dir else Path(settings.sovits_svc.so_vits_svc_dir)
        )
        self._python_path = python_path if python_path else settings.sovits_svc.python_path
        # 允许作为推理输入的根目录列表（任一命中即放行）。
        # 默认 = 训练数据目录 ∪ data/input，全部锚定配置绝对路径（对 CWD 免疫）。
        if allowed_audio_roots is None:
            allowed_audio_roots = [
                settings.sovits_svc.training_data_dir,
                settings.sovits_svc.input_dir,
            ]
        self._allowed_audio_roots = [Path(root).resolve() for root in allowed_audio_roots]
        # 模型路径校验根：训练产出模型目录（上游 logs 目录始终附带放行）
        self._models_dir = Path(models_dir).resolve() if models_dir else Path(settings.sovits_svc.models_dir).resolve()

    @property
    def allowed_audio_roots(self) -> list[Path]:
        """推理输入白名单根（只读副本，供测试/诊断）。"""
        return list(self._allowed_audio_roots)

    def _validate_audio_path(self, audio_path: str) -> Path:
        """校验 audio_path 解析后必须位于任一允许的根目录之内，防止任意文件传入子进程。"""
        audio = Path(audio_path)
        try:
            resolved = audio.resolve()
        except Exception as e:
            raise ValueError(f"Invalid audio path: {audio_path}: {e}")
        for root in self._allowed_audio_roots:
            if resolved.is_relative_to(root):
                return resolved
        raise ValueError(
            f"audio_path must be located under one of {self._allowed_audio_roots}, got: {resolved}"
        )

    def _validate_model_path(self, model_path: str) -> Path:
        """校验 model_path 解析后必须位于允许的模型根目录之内
        （models_dir 或 so-vits-svc/logs），防止任意本地文件传入子进程。"""
        path = Path(model_path)
        try:
            resolved = path.resolve()
        except Exception as e:
            raise ValueError(f"Invalid model path: {model_path}: {e}")
        allowed_roots = [
            self._models_dir,
            (self._so_vits_svc_dir / "logs").resolve(),
        ]
        for root in allowed_roots:
            if resolved.is_relative_to(root):
                return resolved
        raise ValueError(
            f"model_path must be located under one of {allowed_roots}, got: {resolved}"
        )

    def _resolve_config_path(self, model_path: Path) -> Path:
        """定位推理用 config.json。

        上游 utils.get_hparams 训练时会把 -c 指向的 config 复制到 logs/<model>/config.json，
        因此优先取模型同目录的 config.json；回退上游仓库 configs/config.json 与
        logs/44k/config.json（inference_main.py 的默认口径）。
        """
        base = model_path if model_path.is_dir() else model_path.parent
        candidates = [
            base / "config.json",
            self._so_vits_svc_dir / "configs" / "config.json",
            self._so_vits_svc_dir / "logs" / "44k" / "config.json",
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        raise FileNotFoundError(
            f"config.json not found for inference; tried: {[str(c) for c in candidates]}"
        )

    @staticmethod
    def _resolve_speaker_name(config_path: Path, speaker_id: int) -> str:
        """将 int speaker_id 反查为上游说话人名称。

        上游 config.json 的说话人结构是 {"spk": {名称: id}} 字典（实码为准，
        preprocess_flist_config.py 写入 spk_dict），并非名称列表。
        """
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        spk_map = config.get("spk")
        if not isinstance(spk_map, dict) or not spk_map:
            raise ValueError(f"config.json missing 'spk' mapping: {config_path}")
        for name, spk_id in spk_map.items():
            try:
                if int(spk_id) == int(speaker_id):
                    return str(name)
            except (TypeError, ValueError):
                continue
        raise ValueError(
            f"speaker_id {speaker_id} not found in config 'spk' mapping {spk_map} ({config_path})"
        )

    async def infer(
        self,
        audio_path: str,
        speaker_id: int = 0,
        transpose: int = 0,
        model_path: Optional[str] = None,
        cluster_model_path: Optional[str] = None,
    ) -> Path:
        audio = self._validate_audio_path(audio_path)
        if not audio.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        effective_model_path = model_path or self._model_path
        if not effective_model_path:
            raise ValueError("Model path must be provided either via constructor or infer() argument")
        validated_model_path = self._validate_model_path(effective_model_path)

        config_path = self._resolve_config_path(validated_model_path)
        speaker_name = self._resolve_speaker_name(config_path, speaker_id)

        self._output_dir.mkdir(parents=True, exist_ok=True)
        # 输出文件名并入 uuid 片段，并发同 stem 推理不再互相覆盖最终产物
        output_path = self._output_dir / f"converted_{audio.stem}_{uuid.uuid4().hex[:8]}.wav"

        # 上游 inference_main.py 真实 CLI（以实码为准）：
        #   -m 模型路径、-c config.json、-cm 聚类模型路径、-n raw/ 下文件名（含扩展名）、
        #   -s 说话人名称（非 id）、-t 移调半音数、-wf 输出格式；无 -i/-o 参数。
        # 输入必须位于 CWD（上游仓库根）下 raw/，输出固定写 results/。
        raw_dir = self._so_vits_svc_dir / "raw"
        results_dir = self._so_vits_svc_dir / "results"
        raw_dir.mkdir(parents=True, exist_ok=True)
        results_dir.mkdir(parents=True, exist_ok=True)

        # 复制输入音频到上游 raw/；文件名带 uuid 片段避免并发同名互覆
        raw_name = f"{audio.stem}_{uuid.uuid4().hex[:8]}{audio.suffix or '.wav'}"
        raw_copy = raw_dir / raw_name
        shutil.copyfile(audio, raw_copy)

        cluster_name = ""
        args = [
            self._python_path,
            "inference_main.py",
            "-m", str(validated_model_path),
            "-c", str(config_path),
            "-n", raw_name,
            "-s", speaker_name,
            "-t", str(transpose),
            "-wf", "wav",
        ]
        if cluster_model_path:
            validated_cluster_path = self._validate_model_path(cluster_model_path)
            # 上游实码：cluster_infer_ratio==0 时强制清空 cluster_model_path，
            # 因此 -cm 必须搭配非零 -cr 才生效（取 1.0 = 完全使用聚类/检索模型）
            args.extend(["-cm", str(validated_cluster_path), "-cr", "1.0"])
            cluster_name = "_1.0"

        expected_result = results_dir / (
            f"{raw_name}_{transpose}key_{speaker_name}{cluster_name}_sovits_pm.wav"
        )

        logger.info(
            f"So-VITS-SVC inference: {audio_path}, speaker={speaker_name} (id={speaker_id}), "
            f"transpose={transpose}, model={validated_model_path}"
        )

        try:
            process = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self._so_vits_svc_dir),
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
            )
            stdout, stderr = await _communicate_with_timeout(process, _INFER_TIMEOUT_SECONDS)

            if process.returncode != 0:
                error_msg = stderr.decode("utf-8", errors="replace")
                logger.error(f"Inference failed: {error_msg}")
                raise RuntimeError(f"Inference failed with return code {process.returncode}: {error_msg}")
        finally:
            # 清理临时 raw 副本（best-effort；format_wav 对非 wav 输入会额外落 .wav 副本）
            try:
                raw_copy.unlink(missing_ok=True)
            except OSError:
                pass
            if raw_copy.suffix != ".wav":
                try:
                    raw_copy.with_suffix(".wav").unlink(missing_ok=True)
                except OSError:
                    pass

        if not expected_result.exists():
            raise RuntimeError(
                f"Inference completed but expected result not found: {expected_result}"
            )

        # 从上游 results/ 取回产物，落到请求的 output_path（audition 目录）
        # （converted_<stem>_<uuid8>.wav 命名，调用方经返回值拿到实际路径）
        shutil.move(str(expected_result), str(output_path))
        logger.info(f"Inference completed: {output_path}")
        return output_path
