import os
os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "1")
hf_home = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hf_download")
os.environ.setdefault("HF_HOME", hf_home)

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
import tempfile
import numpy as np
import wave

app = FastAPI(
    title="F5-TTS Web API",
    description="A Web API for F5-TTS text-to-speech service",
    version="1.0.0"
)

MODEL_AVAILABLE = False
f5tts = None

try:
    from f5_tts.api import F5TTS
    print("Loading F5-TTS model...")
    print(f"HF_ENDPOINT: {os.environ.get('HF_ENDPOINT')}")
    print(f"HF_HOME: {os.environ.get('HF_HOME')}")
    try:
        f5tts = F5TTS()
        print("Model loaded successfully!")
        MODEL_AVAILABLE = True
    except Exception as e:
        print(f"Error loading model: {e}")
        MODEL_AVAILABLE = False
except ImportError as e:
    print(f"F5-TTS not available: {e}")
    MODEL_AVAILABLE = False


@app.get("/")
def read_root():
    return {"message": "Welcome to F5-TTS Web API", "status": "running", "model_available": MODEL_AVAILABLE}


@app.get("/health")
def health_check():
    return {"status": "healthy", "model_loaded": MODEL_AVAILABLE}


if MODEL_AVAILABLE:
    @app.post("/tts/")
    async def text_to_speech(
        ref_audio: UploadFile = File(...),
        ref_text: str = Form(...),
        gen_text: str = Form(...),
        tts_model: str = Form("F5-TTS"),
        remove_silence: bool = Form(False),
        cross_fade_duration: float = Form(0.15),
        speed: float = Form(1.0),
        nfe_step: int = Form(32),
        cfg_strength: int = Form(2),
        seed: int = Form(-1)
    ):
        try:
            if tts_model not in ["F5-TTS", "E2-TTS"]:
                raise HTTPException(status_code=400, detail="tts_model must be 'F5-TTS' or 'E2-TTS'")

            ref_path = None
            output_path = None

            try:
                ref_fd, ref_path = tempfile.mkstemp(suffix=os.path.splitext(ref_audio.filename)[1] if ref_audio.filename else ".wav")
                with os.fdopen(ref_fd, "wb") as tmp_file:
                    content = await ref_audio.read()
                    tmp_file.write(content)

                output_fd, output_path = tempfile.mkstemp(suffix=".wav")
                os.close(output_fd)

                wav, sr, spect = f5tts.infer(
                    ref_file=ref_path,
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
                    seed=seed
                )

                def iterfile():
                    try:
                        with open(output_path, mode="rb") as file_like:
                            yield from file_like
                    finally:
                        if output_path and os.path.exists(output_path):
                            os.unlink(output_path)
                        if ref_path and os.path.exists(ref_path):
                            os.unlink(ref_path)

                return StreamingResponse(
                    iterfile(),
                    media_type="audio/wav",
                    headers={
                        "Content-Disposition": "attachment; filename=generated.wav"
                    }
                )

            except Exception as e:
                if ref_path and os.path.exists(ref_path):
                    os.unlink(ref_path)
                if output_path and os.path.exists(output_path):
                    os.unlink(output_path)
                raise

        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error generating speech: {str(e)}")
else:
    @app.post("/tts/")
    async def text_to_speech_mock(
        ref_audio: UploadFile = File(...),
        ref_text: str = Form(...),
        gen_text: str = Form(...),
        tts_model: str = Form("F5-TTS"),
        remove_silence: bool = Form(False),
        cross_fade_duration: float = Form(0.15),
        speed: float = Form(1.0),
        nfe_step: int = Form(32),
        cfg_strength: int = Form(2),
        seed: int = Form(-1)
    ):
        return generate_mock_audio()


def generate_mock_audio():
    output_fd, output_path = tempfile.mkstemp(suffix=".wav")

    sample_rate = 24000
    duration = 2
    t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)

    start_freq = 200
    end_freq = 800
    freq_sweep = start_freq + (end_freq - start_freq) * t / duration

    audio_data = np.zeros_like(t)
    for i, freq in enumerate(freq_sweep):
        audio_data[i] = 0.3 * np.sin(2 * np.pi * freq * t[i])

    envelope = np.ones_like(t)
    attack_time = int(0.1 * sample_rate)
    release_time = int(0.2 * sample_rate)
    envelope[:attack_time] = np.linspace(0, 1, attack_time)
    envelope[-release_time:] = np.linspace(1, 0, release_time)
    audio_data *= envelope

    audio_data = (audio_data * 32767).astype(np.int16)

    with wave.open(os.fdopen(output_fd, 'wb'), 'wb') as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(audio_data.tobytes())

    def iterfile():
        try:
            with open(output_path, mode="rb") as file_like:
                yield from file_like
        finally:
            if os.path.exists(output_path):
                os.unlink(output_path)

    return StreamingResponse(
        iterfile(),
        media_type="audio/wav",
        headers={
            "Content-Disposition": "attachment; filename=generated.wav"
        }
    )


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8002))
    uvicorn.run(app, host="0.0.0.0", port=port)
