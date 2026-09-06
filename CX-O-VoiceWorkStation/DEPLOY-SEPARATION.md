# DEPLOY — 分离引擎部署指引（demucs + AudioSep）

> change-id: `enhance-cover-pitch-analysis-duet`（Task 1）
> 适用服务：CX-O-VoiceWorkStation（作曲/翻唱CXFC，端口 8200）
> 引擎代码由 `python tools/setup_separation.py --clone` 克隆到 `CX-O-VoiceWorkStation/engines/`（已入根 .gitignore，不入库）

## 一、引擎与调用契约（以克隆实码为准）

| 引擎 | 仓库 | 职责 | 调用方式 |
|------|------|------|---------|
| demucs | facebookresearch/demucs | 人声/伴奏分离（htdemucs + --two-stems=vocals，两轨；注意 htdemucs_2s 非官方预训练名） | VWS 子进程：`python -m demucs --two-stems=vocals -n htdemucs -o <outdir> <audio>`（cwd=引擎根；产物 `<outdir>/<model>/<track>/vocals.wav` + `no_vocals.wav`） |
| AudioSep | Audio-AGI/AudioSep | 文本查询拆分双人声部 | VWS 子进程 wrapper：`tools/audiosep_runner.py`（cwd=引擎根），内部调 `pipeline.build_audiosep(config/audiosep_base.yaml, <.ckpt>, device)` + `pipeline.separate_audio(...)`（pipeline.py L10/L20；输出 32kHz 单声道 int16 wav） |

两引擎**依赖不共存单环境**：config `separation.demucs_python_path` 与 `separation.audiosep_python_path` 分设（各自 venv/conda 的 python 绝对路径即可）。

## 二、demucs 环境与权重

1. 依赖（独立环境，Python ≥3.9）：
   ```bash
   python -m venv .venv-demucs
   .venv-demucs/Scripts/pip install demucs          # 含 torch/dora/evaluate 等依赖
   ```
2. 模型权重 `htdemucs`：**首次运行自动下载**至 torch hub 缓存
   `~/.cache/torch/hub/checkpoints/`（Windows: `%USERPROFILE%\.cache\torch\hub\checkpoints\`）。
   离线部署：从 [HuggingFace facebook/htdemucs](https://huggingface.co/facebook/htdemucs) 取
   `htdemucs_th.pth` 放入上述缓存目录。
3. 验证：
   ```bash
   cd engines/demucs && <demucs_python> -m demucs --list-models
   ```

## 三、AudioSep 环境与权重

1. 依赖（独立环境；参考引擎内 `environment_win64.yaml` / `environment.yml`，核心 pip 集）：
   ```bash
   python -m venv .venv-audiosep
   .venv-audiosep/Scripts/pip install torch torchaudio librosa soundfile scipy pyyaml \
       transformers tokenizers timm laion_clap lightning
   ```
   注意：官方环境锚定 Python 3.10 + torch 2.1.2；如遇 `models/CLAP` 导入错误，按其报错补齐
   （CLAP 代码已 vendor 在 `engines/AudioSep/models/CLAP/`）。
2. 权重放置（`engines/AudioSep/checkpoint/`，缺一不可）：
   - `audiosep_base_4M_steps.ckpt` — AudioSep 主模型 checkpoint（.ckpt 格式）。
     下载：[HuggingFace Space Audio-AGI/AudioSep → checkpoint 目录](https://huggingface.co/spaces/Audio-AGI/AudioSep/tree/main/checkpoint)。
   - `music_speech_audioset_epoch_15_esc_89.98.pt` — CLAP 文本编码器权重
     （`models/clap_encoder.py` L7 默认路径，缺它 build_audiosep 即失败）。
     下载：[LAION CLAP 权重发布页](https://huggingface.co/lukewys/laion_clap)（文件名同上）。
   - 也可放自定义位置后配置 `separation.audiosep_checkpoint`（.ckpt 绝对路径）；
     CLAP 权重仍须在引擎 `checkpoint/` 下。
3. 首次推理还会经 HF 下载 `roberta-base` 分词器（自动缓存到 `~/.cache/huggingface/`）。

## 三-b、FFmpeg 共享 DLL（torchaudio ≥2.9 解码链必需）

torchaudio ≥2.9 的音频解码完全走 torchcodec，torchcodec 需要 **FFmpeg full-shared DLL**
（支持 FFmpeg 4–9）在进程 PATH 上——缺它 demucs/AudioSep 子进程在 `torchaudio.load`
即报 `Could not load libtorchcodec`（2026-09-06 实测）。

- **本仓自包含方案（已就位）**：FFmpeg master full-shared 构建已解压至
  `CX-O-VoiceWorkStation/tools/ffmpeg/bin/`（含 avcodec/avutil/avformat 等 DLL 与 ffmpeg.exe）；
  `vocal_separator.VocalSeparator._subprocess_env()` 会自动把该目录前置到子进程 PATH——
  换机部署时**随 CX-O-VoiceWorkStation 目录一起拷贝即可**，无需系统级安装。
- 若自建环境：从 [BtbN FFmpeg-Builds](https://github.com/BtbN/FFmpeg-Builds/releases)
  取 `ffmpeg-master-latest-win64-gpl-shared.zip`，解压后将其 `bin/` 置于子进程 PATH，
  或改用系统 conda `conda install -c conda-forge ffmpeg`。
- Python 3.14 + torch 2.11 实测组合：torchcodec 0.16.0+cpu + 上述 FFmpeg master 可用；
  torchcodec 与 torch 版本兼容表见其 README。

## 四、VWS 配置对接（workstation/config.py `separation` 段）

```python
separation.enabled = true                       # false 时分离端点直接报守卫错误
separation.demucs_engine_dir / audiosep_engine_dir   # 引擎目录（默认 engines/ 下）
separation.demucs_python_path = "<.venv-demucs 的 python>"
separation.audiosep_python_path = "<.venv-audiosep 的 python>"
separation.device = "auto"                      # auto|cuda|cpu
separation.demucs_model = "htdemucs"            # 两轨人声分离 = htdemucs + --two-stems=vocals
separation.audiosep_checkpoint = ""             # 空=引擎 checkpoint/ 目录扫描
separation.subprocess_timeout_seconds = 600     # 超时 terminate→kill
```

## 五、验证

```bash
python tools/setup_separation.py        # 退出码 0 = 两引擎代码+权重+依赖全部就绪
# 冒烟（引擎就绪后，任一 wav）：
#   调 POST /api/cover/duet（Task 3 提供端点）或直接单元测试 mock 链路
```

## 六、常见问题

- **AudioSep 输出为 32kHz 单声道**：由下游消费方（mixer/重采样）兜底对齐 44.1kHz。
- **CPU 推理慢**：demucs 一首歌 CPU 约数分钟量级；GPU（≥6GB 显存）推荐。
  device=auto 时 demucs 由引擎自判（cuda-if-available），AudioSep 由 wrapper 探测。
- **首次运行卡在下载**：权重自动下载可能超过 `subprocess_timeout_seconds`，
  可调大该值或按上文手动放置权重。
