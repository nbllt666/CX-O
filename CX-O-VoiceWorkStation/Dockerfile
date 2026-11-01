# CX-O VoiceWorkStation 作曲/翻唱CXFC 服务镜像
# change-id: organize-per-service-docker-deploy（Task 3）
#
# 容器入口说明（为何绕开 workstation.main 的 main()）：
#   workstation/main.py 的 main() 从 settings.server.host 取监听地址，ServerConfig 默认
#   127.0.0.1，且当前代码没有该字段的环境变量覆盖路径。若用 `python -m workstation.main`
#   进入容器（触发 main()），uvicorn 只绑定容器内回环地址，
#   宿主机映射端口不可达。因此 CMD 直接使用 uvicorn CLI 指定 0.0.0.0:8200，
#   不修改服务源码（config.py 的 127.0.0.1 默认保持，裸机启动行为不变）。
#
# 平台相关依赖边界：
#   - Windows 专用 tools/ffmpeg/（自包含 FFmpeg full-shared DLL，约 178MB）**不进镜像**：
#     本镜像只 COPY workstation/，且 .dockerignore 排除 tools/ffmpeg/。
#     vocal_separator._subprocess_env() 在 tools/ffmpeg/bin 不存在时原样继承环境变量，
#     因此 Linux 容器自动改用下方 apt 安装的系统 ffmpeg。
#   - SoundFont（music.soundfont_path）不在镜像内，需外部挂载 .sf2 并在配置中指向它；
#     缺失时伴奏渲染抛出 AccompanimentError（fluidsynth 已随镜像安装）。
#   - 分离引擎（engines/demucs、engines/AudioSep 第三方仓库与权重）与 DiffSinger
#     均为外部依赖，不随镜像分发；缺失时相关端点按现码返回错误/503。
#
# 备注：requirements.txt 含测试依赖（pytest），此处按清单全量安装以保证与 CI 解释器一致，
#       镜像体积与攻击面属已知项。

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

# ffmpeg：vocal_separator / 音频解码的系统依赖（容器内替代 Windows tools/ffmpeg）
# fluidsynth：伴奏渲染子进程（accompaniment.py 依赖其在 PATH 中）
# libsndfile1：soundfile（librosa 读写音频）的底层库
# curl：HEALTHCHECK 与 compose 健康探针使用
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        fluidsynth \
        libsndfile1 \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install -r requirements.txt

COPY workstation /app/workstation

# data/ 为运行时数据根（songs / svc-results / input / separation / voice_profiles）；
# compose 以宿主目录挂载覆盖，此处预建保证无卷时服务也能启动。
RUN mkdir -p /app/data

EXPOSE 8200

HEALTHCHECK --interval=30s --timeout=10s --retries=5 --start-period=120s \
    CMD curl -fsS http://127.0.0.1:8200/health || exit 1

CMD ["uvicorn", "workstation.main:app", "--host", "0.0.0.0", "--port", "8200"]
