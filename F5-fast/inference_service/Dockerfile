FROM soar97/triton-f5-tts:24.12

ENV DEBIAN_FRONTEND=noninteractive
ENV CUDA_HOME=/usr/local/cuda

RUN pip3 install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple \
    fastapi \
    uvicorn \
    pypinyin \
    jieba \
    safetensors \
    python-multipart

WORKDIR /app

COPY inference_service /app/inference_service

EXPOSE 8000

CMD ["python3", "inference_service/main_pytorch.py"]
