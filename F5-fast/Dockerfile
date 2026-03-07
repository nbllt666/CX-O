FROM nvcr.io/nvidia/tritonserver:24.06-trtllm-python-py3

LABEL maintainer="F5-TTS TensorRT-LLM"
LABEL description="Production-ready F5-TTS deployment with TensorRT-LLM acceleration"

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libsndfile1 \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

RUN pip install --no-cache-dir \
    'tritonclient[all]' \
    fastapi \
    uvicorn \
    websockets \
    python-multipart \
    pydantic \
    numpy \
    torchaudio \
    jieba \
    pypinyin

COPY model_repo_f5_tts /models
COPY f5_trt_llm_engine /engines
COPY F5-TTS/F5TTS_Base /models/F5TTS_Base
COPY vocos_vocoder.plan /models/vocoder/vocos_vocoder.plan
COPY gateway /app/gateway
COPY text /app/text
COPY patch /app/patch

ENV MODEL_REPO_PATH=/models
ENV ENGINE_PATH=/engines
ENV F5TTS_MODEL_PATH=/models/F5TTS_Base
ENV VOCODER_PATH=/models/vocoder
ENV GATEWAY_PATH=/app/gateway
ENV TEXT_PATH=/app/text
ENV PATCH_PATH=/app/patch
ENV PYTHONPATH=/app:/app/gateway:/app/text:/app/patch:${PYTHONPATH}

EXPOSE 8000 8001 8002 8080

RUN echo '#!/bin/bash\n\
set -e\n\
\n\
echo "Starting Triton Server..."\n\
tritonserver --model-repository=/models \\\n\
    --http-port=8000 \\\n\
    --grpc-port=8001 \\\n\
    --metrics-port=8002 \\\n\
    --log-verbose=1 \\\n\
    --log-info=1 \\\n\
    --log-warning=1 \\\n\
    --log-error=1 &\n\
\n\
TRITON_PID=$!\n\
echo "Triton Server started with PID: $TRITON_PID"\n\
\n\
echo "Waiting for Triton Server to be ready..."\n\
for i in $(seq 1 60); do\n\
    if curl -s http://localhost:8000/v2/health/ready > /dev/null 2>&1; then\n\
        echo "Triton Server is ready!"\n\
        break\n\
    fi\n\
    if [ $i -eq 60 ]; then\n\
        echo "Timeout waiting for Triton Server"\n\
        exit 1\n\
    fi\n\
    sleep 2\n\
done\n\
\n\
echo "Starting FastAPI Gateway..."\n\
cd /app/gateway\n\
python main.py &\n\
\n\
GATEWAY_PID=$!\n\
echo "FastAPI Gateway started with PID: $GATEWAY_PID"\n\
\n\
wait $TRITON_PID $GATEWAY_PID\n\
' > /app/start.sh && chmod +x /app/start.sh

HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD curl -f http://localhost:8000/v2/health/ready && curl -f http://localhost:8080/health || exit 1

CMD ["/app/start.sh"]
