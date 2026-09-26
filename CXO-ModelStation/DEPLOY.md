# CXO-ModelStation 独立部署指引

> CXO-ModelStation 是自包含部署单元：除 Python 环境与 GPU 驱动外，运行所需引擎代码全部位于
> `CXO-ModelStation/` 内部（`engines/` 目录）。本文档描述把本目录整体拷贝到另一台同构机器后
> 的完整部署步骤。
>
> 若目标机**不想装 Python、也不想手动敲命令**，直接看 **§8 桌面安装包 / 便携版**：Electron 应用
> 自带便携 Python 运行时与三引擎，双击即用（本文 §1–§7 的手工部署方式仍然可用）。

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

## 8. 桌面安装包 / 便携版（装机即用形态，2026-09-26 新增）

不想让目标机装 Python、也不想手动敲命令时，用桌面形态交付：**Electron 应用 + 包内便携 Python 运行时 + 三引擎 + 数据随包**，双击即用。

### 8.1 两种用法（安装包 / 便携目录）

**A. 桌面安装包（推荐）**：`release\CXO-ModelStation-Setup-0.1.0.exe`（2293.4 MB，full 档含引擎依赖与便携运行时）——拷到目标机双击安装即可，安装目录默认 `%LOCALAPPDATA%\CXO-ModelStation`（逐用户，无需管理员），自带桌面快捷方式；卸载不删数据根。

**B. 便携目录（免安装）**：`CXO-ModelStation/release/win-unpacked/`，整目录拷到目标机后双击 `CXO-ModelStation.exe` 即可。

两种用法的运行行为一致：

- 应用自己拉起包内后端：`resources\runtime\python\python.exe -m modelstation.main`（单 worker，训练状态进程内缓存，勿改并行）
- 前端不是后端托管的页面：主进程另起本地站点 `http://127.0.0.1:3300`（被占用自动顺延）并把 `/api`、`/health` 反代到后端
- 若默认端口 8300 上不是健康的 ModelStation（例如本机同时按 README 起了 CXO-EvalKit 的 8300），应用会**自动顺延**到空闲端口（如 8310），实际后端地址显示在应用内「连接设置」页
- 删除安装（或整个目录）即可，用户数据不在这里（见 8.2）

### 8.2 数据根（用户数据放哪）

- 默认数据根：`%LOCALAPPDATA%\CXO-ModelStation\data`
- **首次启动**从包内 `resources\data` 种子拷贝并写幂等标记 `.seed.json`；之后启动不再覆盖（训练出的模型、数据集都在这里保留）
- 可覆盖：环境变量 `CXO_MODELSTATION_DATA_ROOT`；应用内「连接设置」页可查看
- 安装目录只读也不会影响训练写盘（所有写入都落在数据根）

### 8.3 体积档位与运行时构建

便携 Python 运行时由 `tools/build_runtime.py` 构建（CPython 3.10.11 嵌入式 + 非可编辑安装，可整体搬迁，无绝对路径绑定）：

| 档位 | 命令 | 实测体积 |
|------|------|---------|
| base（仅后端，训练不可用） | `python tools/build_runtime.py --profile base --torch-index cpu` | 46 MB |
| full + CPU 轮子 | `python tools/build_runtime.py --profile full --torch-index cpu` | 1917 MB |
| full + CUDA 轮子（默认交付档） | `python tools/build_runtime.py --profile full --torch-index cuda` | 5636 MB |

就绪自检：`python tools/runtime_relocation_check.py`（把运行时拷到临时路径后跑导入自检 + 用副本起后端 `/health` + 绝对路径扫描）。

### 8.4 一条命令出包

```bat
cd CXO-ModelStation
python tools/build_desktop.py --runtime-profile full --torch-index cuda
```

流程：前端构建 → 运行时就绪（幂等复用）→ 三引擎校验 → electron-builder（`dir` 便携目录 + 安装包）→ 产物报告（`build/reports/desktop_build_report.json`）。常用参数：`--form dir|nsis|inno|auto`、`--out-dir`、`--skip-runtime`、`--skip-frontend`。

**安装包形态判据**：payload ≤ 2 GB 走 NSIS；超过（full 档必然超过）改用 Inno Setup。推荐直接由编排器自动选择与编译：`python tools\build_desktop.py --form inno --skip-runtime`；手工编译的等价命令（需先安装 Inno Setup 6，`iscc` 在 PATH 或 `%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe`）：

```bat
cd CXO-ModelStation\tools\inno_setup
iscc /DPayloadDir=<绝对路径>\release\win-unpacked /DOutputDir=<绝对路径>\release /DAppVersion=0.1.0 modelstation.iss
```

**本机实测终值（2026-09-26）**：

| 档位 | 产物 | 体积 |
|------|------|------|
| full（含引擎依赖 + 便携运行时） | `release\CXO-ModelStation-Setup-0.1.0.exe`（Inno Setup 6.7.3 编译，payload 5.897 GB） | **2293.4 MB** |
| full 便携目录 | `release\win-unpacked\`（34,216 文件） | 5745 MB |
| base（仅后端依赖，训练不可用） | `release-nsis-trial\CXO-ModelStation Setup 0.1.0.exe`（NSIS 试跑产物，非正式交付，可删） | 112.7 MB |

### 8.5 离线与权重

- 运行时构建需要联网下载 CPython 嵌入式包与轮子；重复构建走 `build/cache/` 缓存，不重下
- **权重仍不进包**（`engines/` 只有引擎代码）：so-vits pretrain、VoxCPM 权重、MeloTTS checkpoint 按 §4 放置；VoxCPM/MeloTTS 也可联网自动拉取
- vLLM 合成运行时（8091 / 8094）仍按 §5 配置，跨机时用 `CXO_MODELSTATION_CONFIG` 指向远端

### 8.6 桌面版核对清单

- [ ] 便携目录（或安装包）已到目标机，`CXO-ModelStation.exe` 可启动
- [ ] 应用内站点可打开，`连接设置` 页显示的后端地址 `/health` 为 healthy
- [ ] 数据根已创建（`%LOCALAPPDATA%\CXO-ModelStation\data`）且含种子内容
- [ ] 二次启动不覆盖既有数据；退出后无残留 python 进程
- [ ] `engines/` 三引擎就绪；权重按 §4 就位后训练可跑通（真实 GPU 训练需在目标机实测）
