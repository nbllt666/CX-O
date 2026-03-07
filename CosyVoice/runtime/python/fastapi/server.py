# Copyright (c) 2024 Alibaba Inc (authors: Xiang Lyu)
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import os
import sys
import argparse
import logging
import uuid
logging.getLogger('matplotlib').setLevel(logging.WARNING)
from fastapi import FastAPI, UploadFile, Form, File, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
import uvicorn
import numpy as np
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append('{}/../../..'.format(ROOT_DIR))
sys.path.append('{}/../../../third_party/Matcha-TTS'.format(ROOT_DIR))
from cosyvoice.cli.cosyvoice import AutoModel
from cosyvoice.utils.file_utils import load_wav

TEMP_DIR = os.path.join(os.environ.get('TEMP', '/tmp'), 'cosyvoice_uploads')
os.makedirs(TEMP_DIR, exist_ok=True)

app = FastAPI()
cosyvoice = None
model_dir = None
model_error = None

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"])


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logging.error(f"Global exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc)}
    )


def check_model_loaded():
    if model_error:
        raise HTTPException(status_code=503, detail=f"Model not loaded: {model_error}")
    if cosyvoice is None:
        raise HTTPException(status_code=503, detail="Model not loaded. Please check if model files exist.")


def generate_data(model_output):
    for i in model_output:
        tts_audio = (i['tts_speech'].numpy() * (2 ** 15)).astype(np.int16).tobytes()
        yield tts_audio


def generate_data_with_cleanup(model_output, tmp_path):
    try:
        for i in model_output:
            tts_audio = (i['tts_speech'].numpy() * (2 ** 15)).astype(np.int16).tobytes()
            yield tts_audio
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


@app.get("/inference_sft")
@app.post("/inference_sft")
async def inference_sft(tts_text: str = Form(), spk_id: str = Form()):
    check_model_loaded()
    model_output = cosyvoice.inference_sft(tts_text, spk_id)
    return StreamingResponse(generate_data(model_output))


@app.get("/inference_zero_shot")
@app.post("/inference_zero_shot")
async def inference_zero_shot(tts_text: str = Form(), prompt_text: str = Form(), prompt_wav: UploadFile = File()):
    check_model_loaded()
    tmp_path = os.path.join(TEMP_DIR, f"{uuid.uuid4()}.wav")
    with open(tmp_path, 'wb') as tmp:
        tmp.write(await prompt_wav.read())
    model_output = cosyvoice.inference_zero_shot(tts_text, prompt_text, tmp_path)
    return StreamingResponse(generate_data_with_cleanup(model_output, tmp_path))


@app.get("/inference_cross_lingual")
@app.post("/inference_cross_lingual")
async def inference_cross_lingual(tts_text: str = Form(), prompt_wav: UploadFile = File()):
    check_model_loaded()
    tmp_path = os.path.join(TEMP_DIR, f"{uuid.uuid4()}.wav")
    with open(tmp_path, 'wb') as tmp:
        tmp.write(await prompt_wav.read())
    model_output = cosyvoice.inference_cross_lingual(tts_text, tmp_path)
    return StreamingResponse(generate_data_with_cleanup(model_output, tmp_path))


@app.get("/inference_instruct")
@app.post("/inference_instruct")
async def inference_instruct(tts_text: str = Form(), spk_id: str = Form(), instruct_text: str = Form()):
    check_model_loaded()
    model_output = cosyvoice.inference_instruct(tts_text, spk_id, instruct_text)
    return StreamingResponse(generate_data(model_output))


@app.get("/inference_instruct2")
@app.post("/inference_instruct2")
async def inference_instruct2(tts_text: str = Form(), instruct_text: str = Form(), prompt_wav: UploadFile = File()):
    check_model_loaded()
    tmp_path = os.path.join(TEMP_DIR, f"{uuid.uuid4()}.wav")
    with open(tmp_path, 'wb') as tmp:
        tmp.write(await prompt_wav.read())
    model_output = cosyvoice.inference_instruct2(tts_text, instruct_text, tmp_path)
    return StreamingResponse(generate_data_with_cleanup(model_output, tmp_path))


@app.get("/health")
async def health_check():
    if model_error:
        return {"status": "error", "model": model_dir, "error": model_error}
    if cosyvoice is None:
        return {"status": "not_loaded", "model": model_dir}
    return {"status": "healthy", "model": model_dir}


def validate_model_dir(model_dir_path):
    if not os.path.exists(model_dir_path):
        return False, f"Model directory not found: {model_dir_path}"
    
    yaml_files = [f for f in os.listdir(model_dir_path) if f.endswith('.yaml')]
    if not yaml_files:
        return False, f"No model config yaml found in: {model_dir_path}"
    
    pt_files = [f for f in os.listdir(model_dir_path) if f.endswith('.pt')]
    if not pt_files:
        return False, f"No model weights (.pt files) found in: {model_dir_path}"
    
    return True, None


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port',
                        type=int,
                        default=50000)
    parser.add_argument('--model_dir',
                        type=str,
                        default='iic/CosyVoice2-0.5B',
                        help='local path or modelscope repo id')
    args = parser.parse_args()
    model_dir = args.model_dir
    
    is_valid, error_msg = validate_model_dir(model_dir)
    if not is_valid:
        logging.error(f"Model validation failed: {error_msg}")
        logging.error("Please download models first by running: python download_models.py")
        logging.error("Or run: download-cosyvoice-models.bat")
        model_error = error_msg
    else:
        try:
            cosyvoice = AutoModel(model_dir=model_dir)
            logging.info(f"Model loaded successfully from: {model_dir}")
        except Exception as e:
            logging.error(f"Failed to load model: {e}")
            model_error = str(e)
    
    uvicorn.run(app, host="0.0.0.0", port=args.port)
