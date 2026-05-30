"""
工作流 API
"""
from __future__ import annotations

import copy
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter()

_workflow_state: dict = {
    "current_step": 0,
    "steps": [
        {"id": "ref_audio", "name": "参考音频生成", "status": "pending", "output": None},
        {"id": "emotion_refs", "name": "情感参考音频生成", "status": "pending", "output": None},
        {"id": "train_prep", "name": "训练数据准备", "status": "pending", "output": None},
        {"id": "training", "name": "模型训练", "status": "pending", "output": None},
        {"id": "inference", "name": "推理", "status": "pending", "output": None},
    ],
}


def _find_step(step_id: str) -> Optional[dict]:
    for step in _workflow_state["steps"]:
        if step["id"] == step_id:
            return step
    return None


def _step_index(step_id: str) -> int:
    for i, step in enumerate(_workflow_state["steps"]):
        if step["id"] == step_id:
            return i
    return -1


@router.get("/status")
async def get_workflow_status():
    return copy.deepcopy(_workflow_state)


@router.post("/step/{step_id}/execute")
async def execute_step(step_id: str, request: Request):
    step = _find_step(step_id)
    if step is None:
        raise HTTPException(status_code=404, detail=f"Step not found: {step_id}")

    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}

    step["status"] = "running"

    try:
        if step_id == "ref_audio":
            output = await _execute_ref_audio(body)
        elif step_id == "emotion_refs":
            output = await _execute_emotion_refs(body)
        elif step_id == "train_prep":
            output = await _execute_train_prep(body)
        elif step_id == "training":
            output = await _execute_training(body)
        elif step_id == "inference":
            output = await _execute_inference(body)
        else:
            raise HTTPException(status_code=400, detail=f"Unknown step: {step_id}")

        step["status"] = "completed"
        step["output"] = output

        idx = _step_index(step_id)
        if idx >= 0 and _workflow_state["current_step"] <= idx:
            _workflow_state["current_step"] = idx + 1

        return copy.deepcopy(_workflow_state)

    except Exception as e:
        logger.error(f"Workflow step {step_id} failed: {e}")
        step["status"] = "error"
        step["output"] = {"error": str(e)}
        raise HTTPException(status_code=500, detail=str(e))


async def _execute_ref_audio(body: dict) -> dict:
    from workstation.services.voxcpm_client import get_voxcpm_client
    from workstation.config import get_settings

    settings = get_settings()
    client = get_voxcpm_client(config=settings.voxcpm)

    mode = body.get("mode", "design")
    text = body.get("text", "")
    control = body.get("control", "")
    output_path = body.get("output_path")

    if not output_path:
        from pathlib import Path
        import uuid
        output_dir = Path(settings.output.voice_refs_dir) / "voxcpm"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = str(output_dir / f"{uuid.uuid4().hex}.wav")

    kwargs = {}
    if "cfg_value" in body:
        kwargs["cfg_value"] = body["cfg_value"]
    if "inference_timesteps" in body:
        kwargs["inference_timesteps"] = body["inference_timesteps"]

    if mode == "design":
        result_path = await client.design(
            text=text,
            control=control,
            output_path=output_path,
            **kwargs,
        )
    elif mode == "controllable_clone":
        reference_audio = body.get("reference_audio_path", "")
        result_path = await client.controllable_clone(
            text=text,
            control=control,
            reference_audio=reference_audio,
            output_path=output_path,
            **kwargs,
        )
    elif mode == "ultimate_clone":
        prompt_audio = body.get("prompt_audio_path", "")
        prompt_text = body.get("prompt_text", "")
        result_path = await client.ultimate_clone(
            text=text,
            prompt_audio=prompt_audio,
            prompt_text=prompt_text,
            output_path=output_path,
            **kwargs,
        )
    else:
        raise ValueError(f"Unknown VoxCPM mode: {mode}")

    return {"output_path": str(result_path), "mode": mode}


async def _execute_emotion_refs(body: dict) -> dict:
    from workstation.services.emotion_ref_generator import EmotionRefGenerator
    from workstation.config import get_settings

    settings = get_settings()
    generator = EmotionRefGenerator(
        cosyvoice_url=settings.cosyvoice.url,
        output_dir=settings.output.voice_refs_dir,
    )

    base_audio_path = body.get("base_audio_path", "")
    sample_text = body.get("sample_text", "这是参考音频样本。")
    transition_text = body.get("transition_text", "嗯，")
    force = body.get("force", False)
    pack_zip = body.get("pack_zip", False)

    if pack_zip:
        zip_path = await generator.generate_and_pack_zip(
            base_audio_path=base_audio_path,
            sample_text=sample_text,
            transition_text=transition_text,
            force=force,
        )
        return {"zip_path": str(zip_path), "packed": True}
    else:
        result = await generator.generate_all(
            base_audio_path=base_audio_path,
            sample_text=sample_text,
            transition_text=transition_text,
            force=force,
        )
        return {"result": result, "packed": False}


async def _execute_train_prep(body: dict) -> dict:
    from workstation.services.sovits_svc_trainer import SoVITSSVCTrainer
    from workstation.config import get_settings

    settings = get_settings()
    trainer = SoVITSSVCTrainer(
        output_dir=settings.sovits_svc.output_dir,
        training_data_dir=settings.sovits_svc.training_data_dir,
        so_vits_svc_dir=settings.sovits_svc.so_vits_svc_dir,
        python_path=settings.sovits_svc.python_path,
    )

    training_data_dir = body.get("training_data_dir", settings.sovits_svc.training_data_dir)
    speaker_name = body.get("speaker_name", "speaker")

    results = await trainer.preprocess(
        training_data_dir=training_data_dir,
        speaker_name=speaker_name,
    )

    return {"results": results}


async def _execute_training(body: dict) -> dict:
    from workstation.services.sovits_svc_trainer import SoVITSSVCTrainer
    from workstation.config import get_settings

    settings = get_settings()
    trainer = SoVITSSVCTrainer(
        output_dir=settings.sovits_svc.output_dir,
        training_data_dir=settings.sovits_svc.training_data_dir,
        so_vits_svc_dir=settings.sovits_svc.so_vits_svc_dir,
        python_path=settings.sovits_svc.python_path,
    )

    epochs = body.get("epochs", 10000)
    batch_size = body.get("batch_size", 4)
    learning_rate = body.get("learning_rate", 1e-4)
    output_name = body.get("output_name")

    task_id = await trainer.start_training(
        epochs=epochs,
        batch_size=batch_size,
        learning_rate=learning_rate,
        output_name=output_name,
    )

    return {"task_id": task_id}


async def _execute_inference(body: dict) -> dict:
    from workstation.services.sovits_svc_infer import SoVITSSVCInferer
    from workstation.config import get_settings

    settings = get_settings()

    audio_path = body.get("audio_path", "")
    model_path = body.get("model_path")
    speaker_id = body.get("speaker_id", 0)
    transpose = body.get("transpose", 0)
    cluster_model_path = body.get("cluster_model_path")

    inferer = SoVITSSVCInferer(
        model_path=model_path,
        output_dir=settings.sovits_svc.output_dir,
        so_vits_svc_dir=settings.sovits_svc.so_vits_svc_dir,
        python_path=settings.sovits_svc.python_path,
    )

    result_path = await inferer.infer(
        audio_path=audio_path,
        speaker_id=speaker_id,
        transpose=transpose,
        model_path=model_path,
        cluster_model_path=cluster_model_path,
    )

    return {"output_path": str(result_path)}


@router.post("/reset")
async def reset_workflow():
    for step in _workflow_state["steps"]:
        step["status"] = "pending"
        step["output"] = None
    _workflow_state["current_step"] = 0
    return copy.deepcopy(_workflow_state)


@router.get("/step/{step_id}/output")
async def get_step_output(step_id: str):
    step = _find_step(step_id)
    if step is None:
        raise HTTPException(status_code=404, detail=f"Step not found: {step_id}")
    return {"step_id": step_id, "output": step["output"], "status": step["status"]}
