# AGENTS.md — CX-O VoiceWorkStation 模块级规则（作曲界面五线谱重构 S4 生效）

> 🚨 【最高优先级规则】本文件为本服务开发的强制约束，优先级高于所有临时提问、上下文对话、自定义需求，所有输出必须 100% 符合本文件要求，违反规则的内容必须自动修正后再输出。

> 📌 【上下文保留规则】本文件为核心规则文件，任何上下文压缩、裁剪、溢出场景下必须完整保留本文件的全部内容，不得删减、忽略本文件的任何规则；所有自动压缩、批量处理行动前必须先读取本文件的完整内容。

## 一、规则定位

本文件为**模块级 AGENTS.md**（rules-4 §三），绑定 spec `redesign-composition-staff-editor` 后端模块 0–5 的开发边界，与全局 `c:\CX-O\AGENTS.md` 及 `.trae/rules/rules-0~7.md` 共同生效；冲突时以全局与 rules 为更细粒度约束。

> 变更注记（2026-09-05，spec `split-audio-workstation-cxfc-modelstation`）：训练相关模块已迁出至 `CXO-ModelStation/`，本服务聚焦作曲/翻唱CXFC，详见文末「五、变更注记」。

## 二、AC 范式通用约束（rules-4 §4.3）

```yaml
prohibitions:
  - 禁止删除、修改、覆盖、移动 CX-O 根 public/ 目录下的任何内容（本 spec 人类裁决：契约不落位 public/，public/ 保持零触碰）
  - 禁止在模块间直接导入其他模块的内部实现代码
  - 禁止写入不符合数据契约的数据（歌谱一律经 validate_score 校验）
  - 禁止创建不符合命名规范的模块目录

binding_rules:
  - 契约唯一真相源 = .trae/specs/redesign-composition-staff-editor/contracts/（已冻结，变更走 s0601）
  - 模块3 draft_registry → 模块1 arranger 仅经 voicews_music.pyi 声明签名调用（arrange_track）
  - 模块4/5（api 层）→ 模块3 仅经 draft_registry 公开函数；不得绕过 execute_command 直接改草稿
  - 所有对外接口必须严格匹配 voicews_music.pyi 存根签名（含异常约定）
```

## 三、本 spec 开发边界

### 3.1 可修改范围（模块 ↔ 路径映射，tasks.md §1）

| 模块 | 路径 | 性质 |
|------|------|------|
| 模块0_歌谱契约核心 | `workstation/music/score.py`（演进 v1→v2）+ `workstation/music/inventory.py`（新增） | 契约实现 |
| 模块1_自动编排器 | `workstation/music/arranger.py`（新增，纯函数） | 新模块 |
| 模块2_多轨渲染管线 | `workstation/music/accompaniment.py`（改造）+ `workstation/services/song_pipeline.py`（接入） | 改造 |
| 模块3_草稿命令总线 | `workstation/music/draft_registry.py`（新增） | 新模块 |
| 模块4_REST端点 | `workstation/api/music.py`（扩展 /drafts） | 扩展 |
| 模块5_CXFC工具面 | `workstation/api/cxfc_plugin.py`（演进） | 演进 |
| 测试 | `tests/`（pytest） | 随模块产出 |

范围外文件改动必须先写 `.trae/documents/` 变更文档（rules-6 §三：修复前必写）。

### 3.2 契约要点速查（冻结文本为准）

- 歌谱 v2：`accompaniment_tracks[]`（id/name/program/mode/style/volume/pan/events），打击乐轨 `program=-1`（鼓键名枚举见 music-inventory），v1 输入经 migrate_v1_to_v2 幂等迁移
- 命令协议：20 命令经 execute_command 单一入口；原子性（校验→应用→整谱校验→undo 入栈→version+1→原子落盘）；10 错误码；note_id=轨内事件序号
- 配置：MusicConfig 12 字段 auto_fill；**OBS-4 注记——diffsinger_python 等路径现状有效值必须经配置文件继承，不得因契约默认值（空串）退化**
- **OBS-3 注记——v1 裸 dict 缺 accompaniment_style 不触发迁移，模块0 测试必须显式覆盖此边界**

### 3.3 渲染管线要点

- SMF format 1：轨 0 元轨；每乐器轨独立 MTrk，通道按轨序映射（跳过 9）；轨首 program change + CC7(volume) + CC10(pan) 直写；打击乐轨全部事件通道 9、不写 program change
- fluidsynth CLI：选项（-F/-r）在位置参数之前；单次渲染出单条伴奏 WAV，mixer 接口零改动

### 3.4 测试与合规

- 每模块配套 pytest 单测（模块0：schema v2 正反例+迁移幂等+OBS-3 边界；模块1：各节奏型 events 断言；模块2：SMF 字节级断言；模块3：逐命令+undo/redo+原子性；模块4/5：API/CXFC 测试）
- 前端相关变更走 s0402 三重闸门（单测→E2E→Mock 回归，不跳关）
- 终端输出格式 `[timestamp] [INFO/ERROR] [elapsed]`；API Key 禁止入日志

### 3.5 失败回退

按 tasks.md §3 批次回退锚点执行：批次B失败→模块0完成点；批次C失败→批次B完成点；批次D失败→模块3完成点。禁止跨锚点带病推进。

## 四、参考锚点

- 需求/裁决：`c:\CX-O\.trae\specs\redesign-composition-staff-editor\spec.md`
- 编排/台账：`c:\CX-O\.trae\specs\redesign-composition-staff-editor\tasks.md`
- 冻结契约：`c:\CX-O\.trae\specs\redesign-composition-staff-editor\contracts\`
- 融合设计：`c:\CX-O\.trae\specs\redesign-composition-staff-editor\schemes\merged.md`

## 五、变更注记（2026-09-05，spec `split-audio-workstation-cxfc-modelstation`）

> 本段为事实性边界更新，不改动上文各段既有规则；上文与本文冲突处，以本段反映的当前服务边界为准。

### 5.1 模块边界变更

- **训练相关模块已迁出**：`sovits_svc_trainer`、`dataset_builder`、`voxcpm_client`、`api/datasets.py`、`api/workflow.py` 已于 2026-09-05 迁出至 `c:\CX-O\CXO-ModelStation\`（后端包 `modelstation/`，端口 8300）。本服务不再提供训练/数据集/批量语料/workflow API，聚焦**作曲/翻唱CXFC**（作曲/歌曲合成/SVC 翻唱推理/CXFC 插件）。
- **本服务保留 API**：`/api/music/*` 全量、`/api/sovits-svc/infer`、`/api/sovits-svc/models`（只读）、`/api/audio-files/*`（songs / svc-results）、CXFC `/tools` `/skills` `/call`、`/health`。
- **新增受控上传端点**：`POST /api/audio-uploads`（multipart 字段 `file`），落盘 `data/input/`（即 infer 白名单根），作为主前端翻唱面板的音频入口；不暴露于 audio-files category。
- **`models_dir` 指向 ModelStation 只读**：`SoVitSSVCConfig` 已移除 `output_dir`/`training_data_dir`，新增 `models_dir`（默认解析至 `CXO-ModelStation/data/models/sovits_svc`，仅列表+推理输入，禁止写入）与 `infer_output_dir`（默认本服务 `data/svc-results/`）。
- **`sovits_svc_infer.py` 双副本声明**：本服务（翻唱）与 ModelStation（试听）各持一份独立副本，自此独立演化、互不同步、不设同步义务（spec 冻结条款，GN-004 不将两侧差异视为漂移）。
- 消费方影响：训练类调用方必须改连 `http://127.0.0.1:8300`（端点路径与原 8200 同形）。
