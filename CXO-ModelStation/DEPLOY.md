# CXO-ModelStation 独立部署指引

> CXO-ModelStation 是自包含部署单元：除 Python 环境与 GPU 驱动外，运行所需引擎代码全部位于
> `CXO-ModelStation/` 内部（`engines/` 目录）。本文档描述把本目录整体拷贝到另一台同构机器后
> 的完整部署步骤。

## 1. 环境要求

| 项 | 要求 |
|----|------|
| Python | 3.10+（建议 3.11；主开发机使用项目根 `py311` 虚拟环境） |
| GPU | 训练需 NVIDIA GPU + CUDA 驱动；仅语料生成/推理可低配 |
| git | MeloTTS 缺失时用于 `--clone-melotts` 克隆 |
| Node.js 18+ | 仅前端 dev 模式需要（生产模式由后端托管 dist，无需 Node） |

## 2. 安装 ModelStation 自身依赖

```bat
cd CXO-ModelStation
pip install -r requirements.txt
```

依赖含 fastapi / uvicorn / pydantic / httpx（及 pytest / pytest-asyncio 测试依赖）。
引擎各自的 Python 依赖不在本 requirements 范围，见下文各引擎说明。

## 3. 三引擎就位（CXO-ModelStation/engines/）

目录结构（整体拷贝时应已随目录带过去）：

```
CXO-ModelStation/
  engines/
    so-vits-svc-4.1-Stable/   # SVC 训练 + VWS 翻唱推理共用
    VoxCPM-main/              # 批量语料生成引擎
    MeloTTS/                  # MeloTTS 微调训练引擎
```

若 `engines/MeloTTS` 缺失，从 GitHub 克隆官方仓库：

```bat
cd CXO-ModelStation
python tools/setup_engines.py --clone-melotts
```

引擎完整性检查（全部通过退出码 0，缺失项逐条报告并给修复指引）：

```bat
python tools/setup_engines.py
```

MeloTTS 训练依赖（torch / librosa 等）在其自身环境安装；本机校验已通过
（`python -c "import melo"` OK）。换机后若导入失败，`setup_engines.py` 会输出
依赖安装指引（在 `engines/MeloTTS` 内 `pip install -e .` 或单独 conda 环境）。

## 4. 模型权重放置

### 4.1 So-VITS-SVC

- **预训练底模**（训练用）：按 so-vits 惯例放入 `engines/so-vits-svc-4.1-Stable/pretrain/`
  （`G_0.pth` / `D_0.pth` / DNS48k 底模等），训练子进程按上游惯例读取；
- **可推理模型**：来自 ModelStation 训练产物，落盘 `data/models/sovits_svc/<model_name>/`
  （`G_*.pth` + `config.json`）。VWS 翻唱推理与 ModelStation 试听均消费此目录。

### 4.2 VoxCPM

`config.voxcpm.model_path` 默认 `openbmb/VoxCPM2`（HuggingFace 仓库 id，首次使用自动下载）；
离线部署时把权重放到本地目录（如 `CXO-ModelStation/models/VoxCPM2/`，`models/` 已被 git 忽略），
再在配置中把 `model_path` 指向该本地路径：

```json
{"voxcpm": {"model_path": "C:/部署路径/CXO-ModelStation/models/VoxCPM2"}}
```

### 4.3 MeloTTS

`config.melotts.base_checkpoint` 留空时由 MeloTTS 管线使用官方默认预训练模型（自动下载）；
离线部署时指定本地权重路径即可。

## 5. vLLM 合成运行时依赖（数据集生成，可选）

**仅 cosyvoice3_zero / qwen3_voicedesign 两引擎的数据集生成需要**；voxcpm 引擎与
So-VITS-SVC / MeloTTS 训练不依赖。运行时由主仓库 CX-O-SERVER 侧 vLLM 服务提供
（OpenAI 兼容 `POST /v1/audio/speech` 协议）：

| 端点 | 默认地址 | 模型 |
|------|---------|------|
| Qwen3 TTS 声音设计 | `http://127.0.0.1:8091` | `Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign` |
| CosyVoice3 零样本克隆 | `http://127.0.0.1:8094` | `Fun-CosyVoice3-0.5B-2512` |

**同机部署**：启动 CX-O-SERVER 的 vLLM 运行时后无需任何配置（默认回环地址）。
**跨机部署**：通过环境变量 `CXO_MODELSTATION_CONFIG`（JSON 字符串）指向远端：

```bat
set CXO_MODELSTATION_CONFIG={"tts_runtime":{"voicedesign_base_url":"http://192.168.1.10:8091","cosyvoice_base_url":"http://192.168.1.10:8094"}}
```

运行时不可达时数据集任务逐条失败并汇总含 base_url 的明确错误，不影响服务其他功能。

## 6. 启动与验证

```bat
cd CXO-ModelStation
start.bat
```

`start.bat` 行为：
1. 启动前检查 `engines/` 目录存在性（缺失时提示运行 `tools/setup_engines.py`）；
2. 优先使用项目根 `py311` 虚拟环境，缺失时回退全局 python；
3. 单 worker 启动后端（**勿改多 worker / reload**：训练状态为进程内缓存）；
4. `start.bat dev` 额外启动前端 dev（3300 端口，`/api` 代理到 8300）；
5. 生产模式前端：`frontend/` 下 `npm run build`，产物 `dist/` 由后端自动托管。

启动后验证：

```
curl http://127.0.0.1:8300/health
```

返回 healthy 即部署成功。训练 API 可用性可通过 `GET /api/sovits-svc/status`
与 `GET /api/melotts/status`（ModelStation 服务开放后）进一步确认。

## 7. 目录整体拷贝核对清单

- [ ] `CXO-ModelStation/` 整目录（含 `engines/` 三引擎、`data/` 数据目录）
- [ ] Python 3.10+ 环境已建，`pip install -r requirements.txt` 已执行
- [ ] `python tools/setup_engines.py` 全项 OK（退出码 0）
- [ ] 权重按 §4 放置（so-vits pretrain / VoxCPM 本地或 HF / MeloTTS checkpoint）
- [ ] vLLM 运行时同机已启动，或跨机已配 `CXO_MODELSTATION_CONFIG`
- [ ] `start.bat` 启动后 `/health` 返回 healthy
