# current-note — enhance-emotion-tts-and-action-presets

> 更新时间: 2026-09-12 22:35 | 变更ID: enhance-emotion-tts-and-action-presets | 阶段: 实现完成，交付前 GN-004 审查中

## 七字段交接状态

| 字段 | 内容 |
|------|------|
| 做到哪了 | Task 1-7 全部完成并勾选；checklist 全勾；三重闸门 PASSED；交付前 GN-004 审查警示放行（观察项已修正），待人类最终确认交付 |
| 为什么 | 用户需求：修复情感TTS（标签前置）+ 动作系统4痛点+PID + 工具注册快捷指令式预设（per-agent、服务端展开） |
| 未闭合项 | 人类最终交付确认（[V] 节点，GN-004 通过不豁免）；无其他未闭合任务项 |
| 接续入口 | 人类使用前需重启后端 + 重新打包前端；终端输出规范提示：重启后 LLM 对话即可验证标签前置情感与预设引用 |
| 人类裁决记录 | REQ-20260912-01（4项裁决）已闭合；Spec 批准（NotifyUser approved）已闭合 |
| 请示追踪 | 无悬空请示 |
| 审查状态 | 计划审查：警示放行（观察项已处理）；交付前审查：警示放行（agent c633cbba，无软阻断；R7 台账第二落点已修正；R1-R8 其余全 PASS） |

## 三段交接

### (1) 工程过程
1. 批次A [P1]：Task 1（服务端标签前置，agent 7b242704）+ Task 2（前端剥离/容错，agent 7810840d）——主线程抽查通过
2. 批次B [P2a]：Task 3（预设服务/工具/API，agent 941f7c49）+ Task 5（动作清单上报，agent 459ce6ba）——主线程抽查通过
3. 批次C+收口：Task 6（PID 平滑，agent a2433e46）+ Task 4（预设展开/注入，agent 7058e9b9）——主线程抽查通过（vrmEngine PID 接入点/preset_expand 防环/注入条件化）
4. Task 7（agent 51295d16）：s0402 三重闸门 PASSED，证据落盘 test_reports/frontend_gate_20260912_emotion_presets/
5. 留痕文档写入 .trae/documents/20260912_模块2_情感TTS前置与预设动作增强.md（status=已完成）

### (2) 交接状态
- Task 1-7：已完成（闭合，均有测试证据）
- checklist.md：全部勾选（24/24）
- 三重闸门：PASSED（已闭合）
- 交付前 GN-004 审查：进行中

### (3) 最终结果
- 验证结论：后端 pytest 5162 passed / 0 failed；前端 vitest 763 passed + tsc EXIT 0；playwright E2E 2 passed；Mock 核检 13/13；public/ 零改动（git 证实）
- 产出物清单：服务端 10+ 文件（预设服务/工具/路由/展开/注入/切片缓冲）、前端 7+ 文件（剥离/容错/PID/上报/接入）、新增测试 6 文件、闸门证据目录、留痕文档

---

# current-note — build-llm-eval-framework

> 更新时间: 2026-09-12 23:05 | 变更ID: build-llm-eval-framework | 阶段: 实现完成，交付前 GN-004 审查中
> 说明：本章节为并行会话追加（上一章节属 enhance-emotion-tts-and-action-presets 会话，归属独立互不混淆）

## 七字段交接状态

| 字段 | 内容 |
|------|------|
| 做到哪了 | Task 1-7 全部完成并勾选（tasks.md 台账 8 行真实 agent id 回填）；Mock 全链路 E2E 三 run 到达终态且三段式报告落盘；EvalKit 单测 77 passed；主服务定向回归 116 passed；留痕文档已落盘；交付前 GN-004 审查进行中 |
| 为什么 | 用户需求：设计一套基于 LLM 的测试框架（记忆劣化按年计算、延迟等），配套服务跑在 Docker；spec 经 GN-004 两轮审查+人类批准（修订复审 PASS） |
| 未闭合项 | 交付前 GN-004 审查结论待落盘；checklist.md 最终核验勾选；真实模式（对运行中主服务实测）由人类择机触发（需先在 CXO-EvalKit/config.json 配 target.admin_api_key） |
| 接续入口 | 部署：`docker compose --profile eval up cxo-evalkit`（宿主 8320）；触发：POST /api/v1/runs {"suite":"memory_decay"}；报告：GET /api/v1/runs/{id}/report；详见 CXO-EvalKit/DEPLOY.md 与留痕文档 |
| 人类裁决记录 | Spec 首次驳回（反馈"劣化要模拟长期（按年计算）"）→ 修订年轴后批准（NotifyUser approved）已闭合 |
| 请示追踪 | 无悬空请示（驳回-修订-批准链路闭合） |
| 审查状态 | spec 冻结前：警示放行（agent 8a8c23d4）；年轴修订复审：PASS（agent f86edd51）；交付前审查：已闭合（agent e03cca29，O-1 checklist 勾选与 O-2 本节三段交接已修正） |

## 三段交接

### (1) 工程过程
1. [P0] 并行：Task 1（主服务时间旅行端点，agent 2eefe944）∥ Task 2（EvalKit 骨架，agent 1e15efa2）——主线程复跑 16+23 passed 抽查通过
2. 主线程共享基建（防同文件并行冲突）：suites 包化 pkgutil 自动发现、target.py 客户端、stub.py Mock 仿真、config 增补
3. [P1] 两批：Task 3 latency（agent e2d116de）∥ Task 4 memory_decay+年轴场景库（agent eba1c6f7）→ Task 5 quality（agent cefdc640）
4. [P2]：Task 6 报告/阈值/文档四件（agent c9d210bf）→ Task 7 主线程全量验证（E2E 三 run 终态+报告三段式、主服务回归 116 passed、留痕+note）
5. 交付前 GN-004 审查（agent e03cca29）：警示放行，O-1/O-2 已修正

### (2) 交接状态
- Task 1-7 与全部 SubTask：已闭合（tasks.md 全勾选、台账真实 id 回填、闭合信号逐项满足）
- checklist.md：全部勾选（主线程逐项核验，GN-004 O-1 修正）
- 留痕文档：已完成（.trae/documents/20260912_模块0_LLM评测框架搭建.md）
- 交付前 GN-004 审查：已闭合（警示放行，2 观察项均修正）
- 待人类：真实模式实测择机触发（[V] 交付确认不因 GN-004 通过而豁免）

### (3) 最终结果
- 验证结论：EvalKit 单测 77 passed / 0 failed（GN-004 独立复跑一致）；主服务 test_eval_time_travel 16 passed + 定向回归合计 116 passed / 0 failed；Mock 全链路 E2E 三 run 终态（memory_decay=failed 确定性模拟衰减 1 年 0.25<0.6、latency=passed、quality=failed stub 确定性判分）、三报告 200 三段式齐全；docker compose（COMPOSE_PROFILES=eval）EXIT=0；public/ 与 .trae/rules/ 零改动（GN-004 git 证实）
- 产出物清单：CXO-EvalKit/ 全树（8 核心模块+3 suite+2 场景+8 测试文件+Dockerfile+DEPLOY+AGENTS+config.example+requirements）；主服务 eval_mixin.py+memory.py 端点+manager 注册+test_eval_time_travel.py；docker-compose.yml 服务段+.gitignore；根 AGENTS/README 补段；留痕文档+note 章节

---

# current-note — extract-neko-adapter（2026-09-12 文件末尾追加；首次追加条目被并行会话覆盖丢失，此为补写——GN-004 交付审查 SOFT_BLOCK 修复，修正方向沿用既有人类裁决：追加式、不覆盖任何既有条目）

## 做到哪了
- **交付完成（2026-09-12，[V] 人类裁决=批准交付）**。Task 1-9 全部完成并勾选：留痕/骨架/迁移/控制面/适配器单测(63)/Electron 瘦客户端/客户端单测(17)/三重闸门 PASSED（证据 `.trae/documents/test_reports/frontend_gate_20260912_121753/`）/变更文档回填+README/GN-004 交付审查闭合（首轮警示放行 → SOFT_BLOCK=本条目丢失已补写 → 复审闭合）。

## 为什么
- 适配器独立化消除 Electron 耦合、可被其他 agent 经控制面 API 管理；restart 修复语义与配置种子同步经人类裁决；IPC 契约 100% 兼容故渲染层零改动。

## 未闭合项
- 无阻断项。交付后遗留观察（不阻断，留待后续检查点）：tls.ts 损坏缓存无重建容错；打包依赖系统 Node（README 部署约束已明示）；适配器死亡时 neko:stop 返回 ok:false（更严格，渲染层优雅降级）。
- 风险提示：本文件被多并行会话共用且发生过覆盖丢失——后续会话写入前必须先读文件真正末尾再追加，禁止整文件重写。

## 接续入口
- 交付后接续点：`.trae/specs/extract-neko-adapter/`（spec 三段交接）+ `.trae/documents/20260912_模块0_抽取Neko适配器独立项目.md`（最终结果）；适配器日常管理见 `CXO-NekoAdapter/README.md` 控制面 API 表。

---

# current-note — remove-autonomy-stop-paths（2026-09-18 文件末尾追加；追加式、不覆盖任何既有条目）

> 更新时间: 2026-09-18 | 变更ID: remove-autonomy-stop-paths | 阶段: Spec 三件套完成，过 GN-004 计划审查（警示放行），待人类批准后实施

## 七字段交接状态

| 字段 | 内容 |
|------|------|
| 做到哪了 | 三件套已产出：`.trae/specs/remove-autonomy-stop-paths/{spec,tasks,checklist}.md`；GN-004 计划审查已执行（警示放行、无 [SOFT_BLOCK]），F1~F8 全部修正回填 |
| 为什么 | 用户指令「动机引擎删除 killswitch 与其它会导致关停的东西等」→ 4 问裁决（只删除急停 + 删除预算熔断硬阻断 + 保留 pause/sleeping/disable + 授权改两个 public 契约 + 前端一并移除停用按钮） |
| 未闭合项 | ① 人类批准三件套（待 NotifyUser）；② 实施未开始（S4）；③ public/ 契约改动虽已授权，实施时仍需 s0401 写前闸门证据；④ `admin_manifest`/`admin_control.schema.json` 仍宣告 `emergency_stop`（未授权改动）与 autonomy 域拒绝并存——已知不对称已登记 |
| 接续入口 | 先做 Task 0（`.trae/documents/20260918_模块0_删除急停与预算熔断硬阻断.md` 先行），再批 1 = T1（引擎）∥ T2（开关与管理面）；批 2 = T3（契约）∥ T4（前端）；批 3 = T5（测试）；批 4 = T6（文档+回归+GN-004 交付审查） |
| 人类裁决记录 | ASK-20260918-01（4 问 4 答）已闭合；裁决原文在会话上下文（非落盘），GN-004 已标注「基于执行者自述、未经独立验证」 |
| 请示追踪 | 无悬空请示（4 问均已获答并登记） |
| 审查状态 | 计划审查：警示放行（GN-004 agent `ba0b0b2a-6ce4-4e39-8d7d-f62764b00a96`；F1 types.ts 漏项 / F2 manager_state.json 迁移缺失 / F3 T1 假闭合信号 / F4~F8 观察项——全部已修正或登记）；交付前审查：未开始 |

## 三段交接

### (1) 工程过程
1. 代码勘察：`server/autonomy/{safety/killswitch.py, manager.py, models.py, core/loop/autonomy_engine.py}`、`api/routers/autonomy.py`、`core/admin/{control_plane.py, manifest.py, telemetry.py}`、前端 AutonomyPage + autonomy.ts + types.ts + i18n、`public/{schema/autonomy_state.schema.json, interface_stub/cxo_autonomy.pyi}`、tests、docs
2. 需求裁决：AskUserQuestion 4 问（ASK-20260918-01，已闭合）
3. 三件套产出 + GN-004 计划审查（警示放行）+ 修正回填（F1~F8）

### (2) 交接状态
- Spec 三件套：已完成（待人类批准）
- 实施（T0~T6）：未开始
- checklist：未勾选（规划态）
- 交付前 GN-004 审查：未开始

### (3) 最终结果
- 验证结论：规划态，无可执行产物；无测试证据
- 产出物清单：spec.md / tasks.md / checklist.md 三件（含 subagent 台账、7 条不变量用例落点、闭合判据表）

### (4) 实施完成更新（2026-09-18 21:20，追加式）

| 字段 | 内容 |
|------|------|
| 做到哪了 | Task 0~5 全部完成并勾选（tasks.md 全勾）；后端全量 pytest **5171 passed / 0 failed**；前端 AutonomyPage 6 passed + tsc EXIT 0 + 全量 vitest 769 passed；契约 Draft7 通过；变更文档回填至「已完成」（第五章含实际修改/测试结果/经验教训）；spec.md Handoff State 已更新；交付前 GN-004 审查进行中 |
| 为什么 | 人类裁决：只删除急停 + 删除预算熔断硬阻断，保留 paused/sleeping/用户在线休眠、enable/disable/pause/resume；授权改两个 public 契约；前端移除停用入口 |
| 未闭合项 | ① 人类 [V] 交付确认；② `admin_manifest`/`admin_control.schema.json` 仍宣告 `emergency_stop`（未授权改动）——已知不对称；③ 后端 disable/pause 保留 vs 前端无停用入口（裁决 3+5 显式结果）；④ 前端证据判定「无适用 autonomy E2E」（仓库仅 smoke.spec） |
| 接续入口 | 交付确认后：重启后端使新语义生效；如需回滚按 `.trae/specs/remove-autonomy-stop-paths/tasks.md` 逐任务逆向（public 契约回退须再经人类授权） |
| 执行方记录 | T1 agent 55789920-71aa-41d8-9b8e-77f3a6485137；T2 agent 7bfc9eaf-9d44-4f22-8bdb-428932a55edf；T3 agent e9b00f5b-cd58-458d-b695-54b7f6ce68b2；T4 agent 140e054c-d3aa-414a-bc3e-b2876711ab01；T5 agent 0aa035f1-0973-4036-be22-afef59a036e4 |
| 证据落点 | `.trae/documents/test_reports/backend_pytest_full_20260918_remove_autonomy_stop.txt`、`backend_pytest_20260918_remove_autonomy_stop.txt`、`frontend_gate_20260918_remove_autonomy_stop/`（vitest/tsc/gate_summary） |
| 审查状态 | 计划审查：警示放行（ba0b0b2a，F1~F8 已处理）；交付前审查：见本表下方追加行 |

### (5) GN-004 交付前审查记录与处理（2026-09-18，追加式）

- 结论：**警示放行**（无 [SOFT_BLOCK]），agent `dd87ed4d-3724-4100-b8b7-e7062f8e6c1b`；其独立复跑关键子集 = 142 passed / 0 failed。
- **F1** 台账未回填 → 已修正：tasks.md 台账 7 行填入真实 agent id 与状态（含 GN-004 计划/交付两次审查 id）。
- **F2** checklist 全未勾选 → 已修正：逐项勾选并附证据引用。
- **F3** 上文 (4) 表措辞「tasks.md 全勾」不准 → 更正为：「Task 0~5 已勾选；T6 于交付前完成并勾选」。
- **F4**「351 passed」缺落盘证据 → 已补 `backend_pytest_subset_20260918_remove_autonomy_stop.txt`（351 passed / 4820 deselected）。
- **F5** tsc 证据缺退出码 → 已补 `frontend_gate_20260918_remove_autonomy_stop/tsc_rerun.txt`（`EXITCODE=0`）。
- **F6** T4.1 措辞「删除 Ban 图标」与实现不符 → 已更正为「移除按钮对应图标；保留未启用提示块 `Ban` 图标」。
- **F7** 工作树含本任务外改动 → 已核验：`server/main.py`（LLM/TTS/Embedding 预热自愈循环）与 `server/autonomy/data/*.json`（运行态写入）、`CXO-EvalKit/data/runs/*` 均属既有用户工作 / 运行数据，非本次引入；提交时应按文件隔离。
- **F8** CX-A 管理接口文档 autonomy 动作矩阵含未实现的 `start`/`stop` → 已澄清为「未实现（返回 `unsupported`）」。
- **[V] 未闭合**：人类交付确认（GN-004 通过不豁免人类裁决）；确认后可重启后端使新语义生效。

---

# current-note — asr-streaming-contract-fix（2026-09-18 文件末尾追加；追加式、不覆盖任何既有条目）

> 更新时间: 2026-09-18 | 变更ID: asr-streaming-contract-fix | 阶段: 实现完成，复跑验证达标

## 七字段交接状态

| 字段 | 内容 |
|------|------|
| 做到哪了 | ASR 流式引擎契约修正 + 首 partial 提速均已完成并四次 run 验证。ASR 段：九轮 721.8~722.4ms → **三轮 361.9~391.8ms**（-48%）；真实链路逐帧探测首 partial 376~407ms、文本单调增长 |
| 为什么 | 人类指令「sensevoice 分明有流式 asr 功能为什么不用？并且只识别增量精度不行」→ 实测证明 SenseVoice 流式精度不可用（跨语言串字），人类裁决「混合：final 换 SenseVoice」；随后人类指令「我记得很久之前 asr 才 210ms」→ 核对历史 T2=190~340ms 属实，定位并修复 722ms 的真因 |
| 未闭合项 | ① 人类 [V] 交付确认；② 全双工首包 P95 已达标（645.5ms ≤ 800ms），但 `tts_first_audio`（985~1009ms）与 REST 文本链路 P95 16690ms 仍为独立瓶颈（下游 LLM/TTS，非 ASR 范畴）；③ 历史 210ms 已定性为 SenseVoice 幻觉碎片 `に`，非精度基线；④ ASR 首 partial 372ms ≈ 架构下限，进一步下压需把 ASR 容器挂 GPU1（资源分配决策，已移交人类裁决，未自行实施）；⑤ `test_config_router` 4 例存量失败（`FakeBox` 缺 `executor`，属 autonomy/config 在途改动） |
| 接续入口 | 重启主服务使新 ASR 语义生效（ASR 容器已重启并加载新引擎）；复跑命令：POST `http://127.0.0.1:8300/api/v1/runs` `{"suite":"latency"}` |
| 人类裁决记录 | ASK-20260918-02（方案分叉：混合 final 换 SenseVoice）已闭合 |
| 请示追踪 | 无悬空请示 |
| 审查状态 | 本轮为既有 spec（build-llm-eval-framework）之外的后续修复迭代，交付前 GN-004 审查：未开始 |

## 三段交接

### (1) 工程过程
1. 实测前置（容器内驱动模型）：SenseVoice 流式精度对照（不可用）→ paraformer 对齐块累积契约验证 → final 模型耗时对照（SenseVoice 581/306ms vs paraformer 2249/751ms）
2. 根因定位（容器内实测）：partial O(n²) 全量重喂（9.44s 音频累计 66.7s CPU，7.1x 实时）→ VAD 返回值单位误用（ms 当采样索引，句尾 final 切错音频）→ VAD 全量重喂 + dynamic silence 静默覆盖阈值（1850ms）+ chunk_size 未传
3. 修复 6 项（见 `.trae/documents/20260912_模块0_LLM评测框架搭建.md` 第十章）：对齐块累积 / SenseVoice final / VAD 契约 / VAD 增量+ms+事件配对 / 句起点能量对齐（`_pending_trim` + 末窗 + 10ms 子窗细化 + 未对齐跳过投机）/ 投机节流
4. 反例回退：首版「VAD 起点事件 rebase 句起点」实测失效（VAD 时间轴超前 300~500ms，事件推迟到句中，清空已累积状态，首 partial 0.6s→2.6s）→ 移除，改能量对齐
5. 人类「我记得很久之前 asr 才 210ms」→ 核对历史（T2=190~340ms 属实）+ 容器内实测定性：210ms 是 SenseVoice 150ms 处的幻觉碎片 `に`（累积为乱码）；722ms 真因是「投机出一次即停（`_spec_sent`）」使服务端必须干等到 600ms 首个对齐块才有第二个确认样本
6. 首 partial 提速修复：移除 `_spec_sent`（投机持续刷新至对齐块产出文本）+ 节拍 150ms→100ms（`SPEC_MIN_SAMPLES`/`SPEC_RETRY_STEP` 2400→1600）+ `_spec_text` 单调增长保护（防前端文本回退）
7. 人类"试试"（优化服务端确认节拍）→ 分解测量（同资产分别打容器 WS 与服务端 WS）：服务端确认**不增加 LLM 延迟**（拦下的是 1 字 `你`，触发需 ≥2 字，首推 `你好` 与 prefill 同刻）；真瓶颈是解码 ~120ms；降节拍至 50ms 为**反例**（间隔不变、首推反而退到 402~455ms），已回退并留注释
8. 人类裁决"试挂 GPU1"→ 已实施（compose 挂 `device_ids:['1']` + `ASR_DEVICE=cuda`，容器内 `torch.cuda.memory_allocated()=1785MB` 确认生效）→ **实测无收益并证伪**：10ms 音频在 GPU 上仍耗 116ms，证明 ~120ms 中约 116ms 是 funasr `AutoModel.generate` 固定开销（非算力）；600ms 音频 GPU 249ms 反而慢于 CPU → 已完整回退（compose 恢复 `devices: []`/`CUDA_VISIBLE_DEVICES=`/`ASR_DEVICE=cpu`；引擎保留 `DEVICE` 常量默认 cpu 供换机覆盖）
9. 人类"试试"（啃 116ms）→ profiling 定位：**修正上一轮错误归因**——funasr 自报 `load_data 0ms / extract_feat 3ms / forward 117ms`，116ms 全在模型前向，非包装层（generate 114.6ms vs inference 116.3ms vs 复用 cache 113.4ms，包装层≈0）；可调项全扫描（线程数/look_back/chunk_size/disable_pbar）均无效，仅 `torch.inference_mode` 省 6.5%（对端到端 2%，未采纳）→ **配置层已穷尽**，无代码改动
10. 验证：容器内直驱 4 轮 + 真实 WS 6 轮 + 真实链路逐帧探测 3 轮 + EvalKit latency 五次全量 run（66d4a7b5 / 28292401 / 70fcab13 / 7dcd61d8 / c7544570）

### (2) 交接状态
- 代码修复：已完成（`CX-O-SERVER/asr_container/streaming_engine.py` + `docker-compose.yml`，GPU 实验已回退至 CPU 基线）
- 单测：已完成（`tests/test_engine_nonblock.py` 同步新契约与 `_spec_text` 断言后 13 passed；定向语音子集 522 passed，4 例存量失败与本轮无关）
- 端到端验证：已完成（EvalKit 五次 run，全双工 15/15 成功、超时归零）
- 变更文档：已完成（第十章，含"追加修复"/"追加测量"/"追加实验"三节）
- 交付前 GN-004 审查：未开始

### (3) 最终结果
- 验证结论：`asr_first_partial` 722.0~722.4ms → **361.6 / 391.8 / 391.9ms（-47%）**；`prefill_started` 同步提前到 361.9~392.1ms；`tts_first_audio` 1330.7~1740.7ms → 991.1~1047.1ms；`first_partial_to_first_audio` P95 977.7ms → **652.6ms（passed ✅）**；timeouts 0 / errors 0；真实链路首 partial 376~407ms、文本单调增长无回退；final 全部正确（SenseVoice 离线）；第九章遗留的「ASR 静默不发 partial / keepalive ping timeout」未再复现
- 已证伪路线（留档防重试）：① 历史 210ms = SenseVoice 幻觉碎片 `に`，非精度基线；② 服务端首帧确认不增加 LLM 延迟，去掉只影响前端显示且使指标变差；③ 降节拍至 50ms 无效且更差；④ GPU 加速无效（瓶颈是模型前向计算，非算力/包装）；⑤ **116ms forward 配置层不可优化**（线程数/look_back/chunk_size/disable_pbar 全无效，inference_mode 仅省 6.5%）
- 未闭合（移交人类裁决）：首 partial 再下压只剩两条路——换量化/更小的流式解码器（需模型转换+精度回归），或放宽服务端首帧确认语义（省 ~130ms，削弱中文幻觉防护）
- 产出物清单：`asr_container/streaming_engine.py`（6 项契约修复 + 3 项提速修复 + DEVICE 参数化）、`docker-compose.yml`（GPU 实验与回退留痕）、`tests/test_engine_nonblock.py`、`.trae/documents/20260912_模块0_LLM评测框架搭建.md`（第十章）、EvalKit runs 66d4a7b5 / 28292401 / 70fcab13 / 7dcd61d8 / c7544570

---

# current-note — fix-empty-collection-memory-waste（2026-09-18 文件末尾追加；追加式、不覆盖任何既有条目）

> 更新时间: 2026-09-18 22:50 | 变更ID: fix-empty-collection-memory-waste | 阶段: 实现+验证完成，等待 [V] 人类裁决

## 七字段交接状态

| 字段 | 内容 |
|------|------|
| 做到哪了 | 首音频 ~1000ms 的最后一段空转已定位并修复：记忆检索在「per-agent 向量集合不存在」时白付 Embedding 63ms + Weaviate class-not-found 失败查询 155ms（合计 ~220ms/轮），已改为检索前先探集合存在性（~2ms）短路。预热态首音频 948~1015ms → **734.7~821.3ms**（收口复测 4 轮，partial→audio P50 413.0 / P95 427.3ms ≤ 阈值 800）；EvalKit 全双工判定 passed（P95 757.6 ≤ 800）。**人类已裁决：本单暂停收口，剩余三段明日继续** |
| 为什么 | 人类指令「先排查首音频的 1000ms 瓶颈」→「直到完全修复」。临时埋点逐点 wall 对表后确认：记忆段 220~239ms 是唯一未优化的大段；独立复现证明不存在集合上 `near_vector` 恒定 ~155ms 且必然无结果（存在的集合同参数仅 15ms），`collections.exists()` 仅 ~2ms → 用 2ms 判定替掉 220ms 空转，语义等价（集合不存在 ⇒ 该 agent 向量记忆数为 0） |
| 未闭合项 | ① **[阻塞·人类搁置（ASK-20260918-03）] 明日继续**：剩余 780ms 的两大段均属质量取舍 —— ASR 首 partial 362~392ms（放宽首帧确认语义可省 ~130ms，削弱中文幻觉防护；或换量化/更小流式解码器）与 TTS 首块 275~307ms（容器内 first audio ≈0.24s，需调模型/参数，有音质风险）；② **[阻塞·人类搁置] 明日继续**：冷启动轮（服务重启/前缀缓存被驱逐后首轮 TTFT 56ms→222~562ms）为既有现象、本单未处理，可选缓解=WS init 时按 agent 预热（每会话多一次 LLM 调用，EvalKit 立即送帧场景收益不确定）；③ 非阻塞记录：EvalKit run 终态 failed 系 REST 文本链路 P95 18902ms（既有独立瓶颈，阈值 2000ms），非本单范围 |
| 接续入口 | 主服务已重启并载入修复（无需再重启）。复跑：POST `http://127.0.0.1:8300/api/v1/runs` `{"suite":"latency"}`；单轮真实链路探测可用 `evalkit/ws_probe.py`（注意轮间隔需 >TTS 完成，否则虚高） |
| 人类裁决记录 | ASK-20260918-02（混合 final 换 SenseVoice）已闭合；**ASK-20260918-03（本单 [V] 首音频剩余项）→ 人类裁决：先暂停，明日继续（2026-09-18 23:0x）**，剩余三项据此标记为 **阻塞（人类搁置）**，非"已完成" |
| 请示追踪 | ASK-20260918-03 已闭合（响应=暂停/搁置，等待明日继续）；无悬空请示 |
| 审查状态 | 交付前 GN-004 审查：**警示放行**（无 SOFT_BLOCK，agent `1d3e102e-d4c0-40ce-84b9-9fb3cc42a5fb`）；已处理项见 (4) |

## 三段交接

### (1) 工程过程
1. 分段实测（临时埋点 + wall 时钟逐点对表，EvalKit ws_probe 多轮 + 服务端日志）：t0→ASR 首 partial 362~392ms / 记忆 220~239ms / LLM TTFT+切片 87~92ms / TTS Provider 首块 273~307ms / WS 下发 ≈1ms
2. 细分记忆段：`route recent=1.9ms search=219.5ms`、`hybrid vec=218.3ms kw=1.0ms`、`vector embed=63.3ms store=154.9ms`，且每轮带 1 条 `Weaviate 向量搜索失败: could not find class CXOMemory_agent_* in schema`
3. 独立复现（`_diag_weaviate.py`，已删除）：不存在集合的 `near_vector` 3 次实测 155.6/155.1/154.7ms；存在的 `CXOMemory` 同参数 15ms、limit=10 仅 4ms；`collections.exists()` 存在/不存在均 ~2ms
4. 修复（rules-6 先文后码）：`.trae/documents/20260918_模块0_修复记忆检索空转.md` → `WeaviateVectorStore.has_agent_collection()` + `HybridSearch._vector_search()` 前置短路
5. 临时埋点全部还原（最终 diff 仅 2 文件，其中 `audio.py`/`tts_service.py`/`llm/client.py`/`router.py` 与 HEAD 完全一致）
6. 单测：定向 4 文件 122 passed；`-k "memory or vector or router or hybrid"` 1201 passed / 0 failed
7. 真实链路验证：ws_probe 4 轮（776/782/776ms 预热态 vs 修复前 948/1000/1329ms）；EvalKit 全量 run f2ebdcc8（全双工 passed，P95 757.6；mean 628.3→565.2，min 600.3→365.7）
8. 反例留档：Provider 首块 → 客户端"~95ms 传输损耗"系此前 wall 对表错位，实测 `tts_first_chunk_sent` 与探测器 `tts_first_audio` 完全重合（≈1ms）

### (2) 交接状态
- 代码修复：已完成（`server/core/memory/weaviate_store.py` / `hybrid_search.py`；主服务已重启载入）
- 单测：已完成（1201 passed / 0 failed）
- 端到端验证：已完成（ws_probe 4 轮 + EvalKit latency 全量 run f2ebdcc8，全双工判定 passed）
- 变更文档：已完成（`.trae/documents/20260918_模块0_修复记忆检索空转.md`，含最终结果）
- 交付前 GN-004 审查：见下方追加行

### (3) 最终结果
- 验证结论：记忆检索段 220~239ms → **~2ms 探测 + 短路**；`Weaviate 向量搜索失败` 日志 每轮 1 条 → **0 条**；预热态首音频 **948~1015ms → 734.7~821.3ms（↓~200ms）**；收口复测 4 轮 `first_partial_to_first_audio` **P50 413.0 / P95 427.3 / mean 407.1 / min 372.7ms**（阈值 800ms）；EvalKit run f2ebdcc8 全双工判定 **passed（P95 757.6 ≤ 800）**（对照 run c7544570：P95 652.6 / mean 628.3 / min 600.3；本 run：P95 757.6 / mean 565.2 / min 365.7。P95 抬升仅因 turn 0 落在 780.8ms —— 该口径已相对 asr_first_partial 起算，与 turn 0 的 ASR 延迟（7982.1ms）**无关**，是 LLM/TTS 冷启动（TTFT 261.1ms vs turn 2 的 57.4ms）；mean/min/P50 均改善，本改动纯减法，非回归）
- 证据落盘：`.trae/documents/test_reports/ws_probe_20260918_fix_empty_collection.json` / `.log`（4 轮原始时序）、`.trae/documents/test_reports/backend_pytest_20260918_fix_empty_collection.txt`（1201 passed / 3970 deselected）、EvalKit run detail.json ×2（f2ebdcc8 / c7544570）
- 首音频剩余构成（预热态）：ASR 362~392ms + 记忆 ~5ms + LLM ~90ms + TTS 275~307ms + 下发 ~1ms
- 已证伪/已澄清路线（留档防重试）：① prefix cache 未命中与情感指令经 LLM 生成均非问题；② TTS 重试退避未触发；③ Provider→客户端无传输损耗
- 未闭合（移交人类裁决）：见七字段「未闭合项」①②③
- 产出物清单：`weaviate_store.py`（+`has_agent_collection()`）、`hybrid_search.py`（前置短路）、`.trae/documents/20260918_模块0_修复记忆检索空转.md`、EvalKit run f2ebdcc8054e46b3a02bd98cb57ee294

### (4) GN-004 交付前审查记录（追加式）

- 结论：**警示放行**（无 [SOFT_BLOCK]：无方向偏离 / 无假闭合证据 / 无批量模板化），agent `1d3e102e-d4c0-40ce-84b9-9fb3cc42a5fb`（2026-09-18 22:5x）。
- **独立核验通过项**：① 等价性成立（写路径 `add_memory_vector→_ensure_collection_for_agent→_collection_name_for_agent` 与探测同源，无"有向量而探测 False"反例）；② 陈旧风险已消除（不缓存 + 异常返 True 保守方向正确）；③ 核心指标属实（detail.json `ws_p95=757.6≤800 passed=true`、mean 565.2 / min 365.7 / P50 549 / max 780.8 与文档逐项一致）；④ 埋点已移除（diff 中无 audio.py / tts_service.py / llm/client.py / router.py）；⑤ note 七字段 + 三段交接齐备、未闭合项未沉默。
- **[警示] 先文后码时序无法独立验证** → 已处理：文档 frontmatter `timestamp` 恢复为创建时刻 22:30，新增「实施记录 → 时序」段说明 22:30 建文 / 22:33~22:40 改码 / 22:41 重启 / 22:42~22:58 验证收口。
- **[观察] SC-1 P95 归因措辞欠准** → 已更正（文档 + 本 note 的「最终结果」）：780.8ms 与 turn 0 的 ASR 延迟 7982.1ms **无关**（口径已相对 asr_first_partial 起算），主因是 LLM/TTS 冷启动（TTFT 261.1 vs 57.4ms）。
- **[观察] 改动范围表述** → 已澄清：本单 2 文件；工作树另有既有无关改动（`server/main.py` 预热自愈、`server/autonomy/*`、`CXO-EvalKit/data/runs/*`）。
- **[观察] 未独立验证项（ws_probe 输出与单测输出未落盘）** → 已补落盘：`.trae/documents/test_reports/ws_probe_20260918_fix_empty_collection.json` / `.log`（4 轮，P50 413.0 / P95 427.3）、`backend_pytest_20260918_fix_empty_collection.txt`（1201 passed）。
- **[V] 未闭合**：人类对剩余质量取舍项的裁决（见七字段「未闭合项」①②③）；GN-004 通过不豁免人类裁决。

---

# current-note — fix-autonomy-disable-and-loop-exit（2026-09-18 文件末尾追加；追加式、不覆盖任何既有条目）

> 更新时间: 2026-09-18 23:28 | 变更ID: fix-autonomy-disable-and-loop-exit | 阶段: 已完成（实现+验证+GN-004 复审警示放行+[V] 已由 ASK-20260918-04 闭合）

## 七字段交接状态

| 字段 | 内容 |
|------|------|
| 做到哪了 | 评审反馈的两条问题已核实并处理：**Issue1（禁用入口缺失）确认存在并修复**——重构把控制区改成了 `!active ? 启用 : (非running ? 恢复 : null)`，启用后 UI 无任何回退入口（后端 `CONTROL_ACTIONS` 仍含 disable、`manager.disable()` 仍在、前端类型仍含 `'disable'`，属前端单侧回归）；已恢复「禁用」按钮（active 恒显示）+ 文案键 + 修正被"改成断言按钮不存在"的用例。**Issue2（stop() 后死循环）实测不成立**——空闲态与轮内两场景 stop() 均 0.1ms 内终止（CancelledError 不被轮内 except Exception 吞），但按评审建议恢复了退出条件 `while self.running:`，使终止不再单点依赖 task.cancel()。**追加轮（ASK-20260918-04 人类裁定）**：再恢复「暂停」入口，控制区三入口（启用/禁用/暂停·恢复）与后端 CONTROL_ACTIONS 完全对齐 |
| 为什么 | 人类指令「验证问题的存在性并进行修复」+ 评审 Issue1/Issue2 原文。核实结论：Issue1 存在（用户启用后无法关闭自主系统）；Issue2 不复现但脆弱性成立（守卫被删后终止单点依赖取消），故按"恢复退出条件"加固而非回滚 killswitch 语义 |
| 未闭合项 | 无阻塞项。① **[V] 已闭合**：ASK-20260918-04 人类裁定「额外恢复『暂停』入口」→ 追加轮已实施并重跑三重闸门 PASSED；② 后端改动属代码级，主服务未重启（守卫下次启动生效，行为向后兼容） |
| 接续入口 | 前端：`cd c:/CX-O/APP-Frontend && npx vitest run && npx playwright test`；后端：`cd c:/CX-O/CX-O-SERVER && python -m pytest tests/ -q -k "autonomy or autonomy_engine or engine_nonblock"`。变更文档：`.trae/documents/20260918_模块0_禁用入口与循环退出.md` |
| 人类裁决记录 | ASK-20260918-02/03 已闭合；**ASK-20260918-04（本单 [V]）→ 人类裁定：额外恢复「暂停」入口**，已实施并验证（追加轮） |
| 请示追踪 | 无悬空请示 |
| 审查状态 | 交付前 GN-004 审查：**警示放行**（无 SOFT_BLOCK，agent `106ec20d-b382-404c-8a8d-b06b94f65fd8`）；5 条发现项已全部处理，见 (4) |

## 三段交接

### (1) 工程过程
1. 读提交 `4df605a` 相关 diff（AutonomyPage.tsx / autonomy_engine.py / killswitch.py / router / manager / 测试 / i18n）
2. Issue1 核实：控制区分支 `null` 分支存在 + 后端 disable 仍合法 + 前端类型仍含 disable + 用例被改为断言按钮不存在 → **确认存在**
3. Issue2 核实：临时用例实测（空闲态 / 轮内 / 对照 disable 不终止）→ **stop() 可终止，主张不成立**；判断依据补充：CancelledError 属 BaseException，轮内 `except Exception` 不吞；`server/autonomy` 全域无吞取消写法
4. 按 rules-6 先写变更文档（`.trae/documents/20260918_模块0_禁用入口与循环退出.md`），再改码
5. Issue1 修复：`AutonomyPage.tsx`（禁用按钮恒显示 + 非 running 追加恢复）、zh-CN/en-US `disable` 键、测试修正 + 新增禁用触发用例
6. Issue2 加固：`autonomy_engine.py` `_run_loop` 恢复 `while self.running:`（含 docstring/模块头注释同步）；`tests/test_autonomy_engine.py` 新增 `TestLoopTermination` 3 例
7. 测试：后端 `pytest tests/ -q -k "autonomy or autonomy_engine or engine_nonblock"` 347 passed；前端三重闸门（s0402）PASSED（单测 7/7 + Playwright E2E 2/2 + tsc exit 0 + 全量 vitest 770 passed），证据落盘 `.trae/documents/test_reports/frontend_gate_20260918_fix_autonomy_disable_btn/`
8. 交付前 GN-004 独立审查（警示放行）→ 5 条发现项处理：精确化后端复现命令、模块头与 `while self.running` 对齐、frontmatter 时间改创建时刻、运行态数据文件显式声明、本段改用三值状态标记

### (2) 交接状态

- Issue1 修复：**已闭合**（前端 4 文件；闸门一已锁定交互）
- Issue2 加固：**已闭合**（后端 1 文件 + 测试 1 文件；含"仅标志位退出"用例）
- 单测/E2E/Mock 回归：**已闭合**（后端 `pytest tests/ -q -k "autonomy or autonomy_engine or engine_nonblock"` 347 passed；前端三重闸门 PASSED：7/7 + 2/2 + tsc exit 0 + 770 passed）
- 变更文档：**已闭合**（`.trae/documents/20260918_模块0_禁用入口与循环退出.md`，含最终结果与未闭合项）
- 交付前 GN-004 审查：**已闭合**（警示放行，见 (4)）
- 运行态数据文件（`server/autonomy/data/audit_logs.jsonl` / `manager_state.json`）：**非本单改动**（运行中服务写入），提交时按文件隔离

### (3) 最终结果
- Issue1：running 态从"无任何按钮"恢复为「禁用」+「暂停」；paused/sleeping 态「禁用」+「恢复」；`control('disable'|'pause'|'resume')` 三入口与后端 `CONTROL_ACTIONS` 完全对齐
- Issue2：`stop()` 终止已实测（0.1ms，双场景）+ 退出条件已恢复（`while self.running:`），并以"仅置 running=False 不发取消"用例锁定守卫本身
- 未恢复项：急停（`emergency_stop` / `emergencyConfirm`，保持重构意图删除）
- 追加轮（ASK-20260918-04）：恢复「暂停」入口 + i18n + 用例；三重闸门重跑 PASSED（8/8 + 2/2 + tsc exit 0 + 771 passed），证据 `.trae/documents/test_reports/frontend_gate_20260918_fix_autonomy_pause_entry/`
- 产出物清单：`AutonomyPage.tsx`、`zh-CN.json`、`en-US.json`、`AutonomyPage.test.tsx`、`autonomy_engine.py`、`tests/test_autonomy_engine.py`、`.trae/documents/20260918_模块0_禁用入口与循环退出.md`、两个前端闸门证据目录

### (4) GN-004 交付前审查记录（追加式）

- 结论：**警示放行**（无 [SOFT_BLOCK]），agent `106ec20d-b382-404c-8a8d-b06b94f65fd8`（2026-09-18 23:2x）。GN-004 独立复跑：`pytest tests/test_autonomy_engine.py -q` → 17 passed；`pytest tests/ -k "autonomy"` → 340 passed / 0 failed。
- **独立核验通过项**：① Issue1 定性成立（`routers/autonomy.py` CONTROL_ACTIONS 含 disable、`manager.disable()` 在、前端类型含 `'disable'`，属前端单侧回归）；② `AutonomyPage.tsx` active 恒显「禁用」+ 非 running 追加「恢复」，复用 `handleControl` 无新 API；③ 旧"断言按钮不存在"两处已纠正、新增点击触发 disable 用例；④ Issue2 表述诚实（明写"实测不成立"另述"按建议加固"，未包装）；⑤ `autonomy_engine.py:197` 实为 `while self.running`、无 `while True`，`stop()` 先置 running=False 再 cancel，三例终止用例齐备（末例断言 `task.cancelled() is False`）；⑥ 闸门证据与日志一致（test1 7/7、test2 2/2 且显式声明不含 autonomy 语义、vitest 770、tsc exit 0）；⑦ 文档命名/frontmatter/状态机合规，文件创建时刻早于代码改动；⑧ `public/interface_stub`、`public/schema` 未被本单改动。
- **[警示] 后端通过数不可按原文命令复现** → 已处理：文档与 note 改为精确命令 `-k "autonomy or autonomy_engine or engine_nonblock"`（347 passed / 4827 deselected），并补更窄复核命令（`tests/test_autonomy_engine.py` → 17 passed）。
- **[观察] 模块头与实现表述相悖** → 已处理：`autonomy_engine.py` 第 21-24 行模块头改为"主循环以 `while self.running` 守卫周期运行……终止由 stop() 承担"，与 :197 一致。
- **[观察] frontmatter timestamp 与文件时间不符** → 已处理：改为创建时刻 `23:09:00`（文件 CreationTime 23:09:29），`completed_at` 改为 `23:15:00`（LastWriteTime 23:15:23）。
- **[观察] 工作树含运行态数据文件改动** → 已在文档/note 显式声明为非本单改动（运行中服务写入），提交时按文件隔离。
- **[观察] 交接状态用"已完成"而非三值** → 已处理：本 note (2) 段改用 `已闭合 / 未闭合 / 当前不可判定` 三值标记。
- **[观察] 前端类型仍含 `'pause'`** → 非越界：API 契约允许且无 UI 入口，符合"暂停入口保持移除"的既定范围。**（该观察项已被追加轮取代：人类裁定 ASK-20260918-04 恢复「暂停」UI 入口，`'pause'` 现为正式 UI 动作。）**
- **[V] 未闭合**：人类确认本单两条问题的处理口径（Issue1 已修复 / Issue2 实测不成立但按建议加固）；GN-004 通过不豁免人类裁决。

> **追加（复审后）**：上述 [V] 已由 **ASK-20260918-04** 闭合（人类裁定：额外恢复「暂停」入口），追加轮已实施并重跑三重闸门 PASSED；本条保留为审查历史（rules-5 只追加不修改）。复审（同一 GN-004 agent）结论：**警示放行**，3 条观察项（文档 completed_at、本 (4) 段 [V] 表述、note 头部阶段）已全部处理。

---

# current-note — 首音频三段排查（2026-09-19 追加；本文件被多并行会话共用，写入前已读真实末尾再追加）

> 更新时间: 2026-09-19 14:05 | 变更ID: first-audio-latency-triage | 阶段: 第1/3项已交付，第2项分析完成待裁决

## 七字段交接状态

| 字段 | 内容 |
|------|------|
| 做到哪了 | 四项均已闭合或达分析终点：① EvalKit 建连开销修复（已实现+验证）；② 第1项非默认助手前缀预热（已实现+验证+上线）；③ 第3项首 partial 被动埋点（已实施+上线，首个 run 即定位瞬态）；④ 第2项 TTS 首块归属拆分（分析完成，方案对比已出，**待人类选定方案**） |
| 为什么 | 用户需求「开工！」= 按风险递增推进首音频剩余三段；中途两次改向（先修 EvalKit 建连 → 先查 GPU 占用）均已闭环 |
| 未闭合项 | ① 第2项方案选型（方案C 削固定开销 / 方案A 量化 / 暂停）待人类裁决；② 首轮瞬态根因（已定位为 vLLM 后端波动，非代码可控）；③ `tests/test_config_router.py` **11 个**既有失败（测试夹具与实现漂移，需另单） |
| 接续入口 | 第2项若选方案C：`docker/llm/cosyvoice_server.py` 加逐段插桩 → 重建镜像（`docker build -f docker/llm/Dockerfile.cosyvoice-vllm -t cosyvoice-vllm:latest .`）→ 定位 ~120ms 固定开销 |
| 人类裁决记录 | ASK-20260919-01（第1项走 ①+② 组合）已闭合；ASK-20260919-02（第3项加被动埋点 / 第2项先拆归属出对比）已闭合；**ASK-20260919-03（第2项选型）已发出未闭合** |
| 请示追踪 | **存在 1 项悬空请示**：ASK-20260919-03（第2项 TTS 改造方案选型） |
| 审查状态 | **交付前 GN-004 审查：已闭合（警示放行，agent `9275f84e-d648-4367-b910-3004438e81c6`，无 [SOFT_BLOCK]）；3 项 [警示] 已全部修正，2 项 [观察] 已加固** |

## 三段交接

### (1) 工程过程
1. **EvalKit 建连开销**（承接 09-18 冷启动排查中的意外发现）：根因 = `httpx.HTTPTransport()` 在 Windows 默认 verify 路径构造 ~6.6s，而 `TargetClient._client()`（21 处）/`JudgeClient._request_chat()` 逐请求新建。改为持久共享连接 + `_SharedSession` 请求级 timeout 代理（21 处调用点零改动）。
2. **第1项·非默认助手前缀预热**：先短 prompt 误判"证伪" → 用生产同规模（2481 tokens）复测**更正为成立**（未预热 665ms vs 预热 36ms）→ 人类裁决 ①+② 组合 → 新增 `prefix_warmup.py`（预热唯一实现）+ `main.py` 委托全量预热 + `agents.py` 创建/更新非阻塞预热。
3. **第3项·首 partial 被动埋点**：先误判"重启后首个会话冷启动" → 隔离测试（重启后首会话 / 全新 agent / 直连容器共 10+ 会话）**全数未复现** → 更正为"间歇性跨阶段漂移" → 人类裁决加被动埋点 → 在 `DualStreamSession` 加候选/扣留累计 + `[DIAG-FIRST-PARTIAL]` 单行输出。
4. **第2项·TTS 首块归属拆分**：容器内日志逐 hop 拆解 + `--flow-steps` 1→3 扫描（每步 ~100ms）→ 归并为 flow ~100ms / hift ~40ms / **固定开销 ~120ms**；容器参数已还原并复测确认。

### (2) 交接状态
- EvalKit 建连开销：**已闭合**（REST min 9801→1848ms，-81%；82 passed）
- 第1项 前缀预热：**已闭合**（A/B 三测点本单预热≈天然预热；启动 19/19；103 passed）
- 第3项 首 partial 埋点：**已闭合**（埋点上线并定位瞬态；103 passed）
- 第2项 TTS 归属拆分：**已闭合（分析）**；**方案选型 = 未闭合**（ASK-20260919-03 待裁决）
- 首轮瞬态根因：**当前不可判定**（已定位为 vLLM 后端 TTFT 波动 58~908ms，非代码可控；连续 2 检查点无进展则依 rules-5 §2.4 上报）
- 交付前 GN-004 审查：**未开始**
- **三值标记说明**：本段状态使用 `已闭合 / 未闭合 / 当前不可判定` 三值

### (3) 最终结果
- 验证结论：
  - EvalKit：REST `overall.min` 9801→**1848ms**、p95 18902→9799ms；`pytest tests/ -q` → **82 passed**
  - 第1项：A/B 三测点（冷 / 天然预热 / 本单预热）C≈B（差 -4/-11ms）→ 预热有效；启动日志 `语音前缀预热完成：19/19 个 agent`；`test_agents_router + test_agent_tools` **87 passed**、`test_lifecycle + test_model_router + test_ref_audio_agent` **50 passed**
  - 第3项：埋点在首个 run 即定位瞬态（turn0 LLM TTFT **577.9ms** vs turn1/2 **58.1/57.9ms**，而 ASR 侧三段完全一致）→ 瞬态归属 LLM 后端；并否定两假设（tools 渲染位置差 5ms、预热形状覆盖差 26ms）
  - 第2项：flow(1步) ~100ms / hift ~40ms / 固定开销 ~120ms(47%)；`--flow-steps` 1→3 使 first audio 0.27→0.47s 中位（每步 ~100ms）
- 产出物清单：
  - `.trae/documents/20260919_模块0_修复评测客户端建连开销.md`
  - `.trae/documents/20260919_模块0_非默认助手前缀预热扩展.md`
  - `.trae/documents/20260919_模块0_语音首partial被动埋点.md`
  - `.trae/documents/20260919_模块0_TTS首块归属拆分与改造方案对比.md`
  - 代码：`CXO-EvalKit/evalkit/{target,judge}.py` + `suites/{latency,quality,memory_decay}.py`；`CX-O-SERVER/server/core/llm/prefix_warmup.py`（新）+ `server/main.py` + `server/api/routers/agents.py` + `server/handlers/audio.py`
  - EvalKit runs：`48f8cba2`（建连修复验证）/ `3fb9f4f4` / `ac76bea6` / `0dec8d0f` / `4617abf3`（瞬态捕获）
- 临时脚本已全部删除（`_t_ttft_series.py`/`_t_prefix_warm.py`/`_t_asr_first_partial.py`/`_t_ws_voice_probe.py`/`_t_tools_prefix.py`/`_t_prod_prefix_cover.py`/`_t_tts_first.py`）
- `public/` 与 `.trae/rules/` 零改动
- 既有问题（非本单）：`tests/test_config_router.py` **11 failed**（`FakeBox` 缺 `executor`，测试夹具与 `get_io_executor()` 实现漂移）

### (4) GN-004 交付前审查记录（追加式）

- 结论：**警示放行**（无 [阻断] / 无 [SOFT_BLOCK]），agent `9275f84e-d648-4367-b910-3004438e81c6`（2026-09-19 14:0x）。
- **独立核验通过项**（GN-004 自跑）：① EvalKit 全量 `pytest tests/ -q` → **82 passed**（与文档一致）；
  ② 主服务定向 4 文件 → **143 passed** 全绿；③ REST 指标 `48f8cba2` vs `f2ebdcc8` 逐项一致
  （min 1848.078↔9801.368、p50 6013.378↔12122.141、p95 9798.914↔18902.089）；
  ④ `audio.py` diff 为 `+39/-0` **纯增量**，未改任何分支判断/发送时序；⑤ `agents.py` 的响应体、
  同步语义、`except HTTPException / except Exception` 结构均未变；⑥ `public/` 零改动（97 tracked 文件无当日 mtime）、
  `.trae/rules/` 经 mtime 证实未改（该目录被 .gitignore:218 忽略，git 无法证实）；
  ⑦ 项目内零临时脚本残留；⑧ note 三段交接 + 三值标记齐备；
  ⑨ **两次错误结论的更正是否诚实** → 通过（doc#1 第五章、doc#2「补测」、doc#3「根因分析」均显式记录错误结论与致错原因，未抹去重写）。
- **[警示] F1 run `3fb9f4f4` 的 ws_p95 张冠李戴** → **已修正**：文档原记 1689.3（实为 run `48f8cba2` 的值），
  落盘 detail.json 实为 **1054.2**；doc#2「补测」表与 doc#3「问题现象」表两处均已更正。
- **[警示] F2 存量失败披露不足** → **已修正**：原记「4 例」为 `-k` 子集口径；该文件单独全跑为 **11 failed**
  （执行者独立复跑核实）。doc#3 已更正并注明两种口径，note 未闭合项同步更正。
- **[警示] F3 4 篇文档 frontmatter `status` 未随正文更新** → **已修正**：分别回填为
  `已完成`/`已完成`/`已完成`/`已完成`（第4篇为分析单，另加 `pending_decision` 字段显式登记 ASK-20260919-03）。
- **[观察] F4 doc#1 `related_files` 不完整** → **已修正**：补入 `suites/{latency,quality,memory_decay}.py`。
- **[观察] F5 `warm_agent_prefix_background` 无「无运行事件循环」守卫** + **[观察] F6 warm 抛错会造成半提交** → **已加固**：
  该两项为同一根因，在 `prefix_warmup.py` 内加 `get_running_loop()` 守卫 + 任务创建 try/except
  （无 loop → 静默跳过，不再可能冒泡为 HTTP 500）。加固后回归 **155 passed**。
- **[观察] F7 单测触发真实后台预热网络请求** → **已知悉未处理**：属测试隔离改进，非本单闭合范围；
  预热异常本即静默（零影响），留待后续测试治理批次。
- **[观察] F8 第2项归并含估算/残差口径** → **已修正**：doc#4 归并表增「口径」列并加口径声明
  （flow=首 hop 增量外推、hift=稳态等效**上界**、固定开销=**残差推断**），明写三者不可简单相加，
  精确定位须方案 C 插桩。
- **[观察] F9 EvalKit 建连修复超出原任务字面范围** → **已处理**：该单有独立留痕文档与用户改向确认，
  本 note「为什么」字段已记明改向闭环；GN-004 判定不构成方向偏离。
- **[观察] F10 本迭代无 spec 三件套 / 无 subagent 台账** → **非越界**：本单为主线程迭代
  （未调度 subagent），rules-0 §四-11 台账不适用；闭合信号定义于各变更文档「预期效果/验证方式」。
- **[V] 未闭合（须人类裁决，GN-004 通过不豁免）**：**ASK-20260919-03**（第2项 TTS 改造方案选型：
  方案C 削固定开销 / 方案A 量化 / 暂停）→ **本单不得标记「全部交付完成」**，
  口径保持「第1、3项及 EvalKit 建连修复已交付；第2项为分析态待人类裁决」。
- **未独立验证项**（GN-004 明确声明，须人类知悉）：服务端日志 `[DIAG-TTFT]`/`[DIAG-FIRST-PARTIAL]`、
  容器日志 `first audio at Xs`、第2项 `--flow-steps` 扫描与容器还原、启动 19/19 预热、GPU 现场归因
  —— GN-004 无运行态访问权限，均基于执行者自述。**不得据此声称已第三方证伪。**

---

## 追加轮：方案 C 步骤 1（TTS 首块固定开销定位）— 2026-09-19 18:30

> 人类裁决 ASK-20260919-03 的回复为「C试试」→ 选**方案 C（先削固定开销）**。
> 本轮为方案 C 的**步骤 1（插桩定位）**，结论**否定了方案 C 的原始假设**。

### 做到哪了

1. **插桩完成并实测**：新增 `_patch_first_hop_probe()`（`PROBE_FIRST_HOP` 环境变量门控，默认关闭）
   + `_stream_wav_pcm` 首次 next 打点，经**挂载覆盖**注入容器（不重建镜像），拿到稳态 4 次一致数据。
2. **定位结论（推翻原假设）**：首 hop 261~273 ms 的真实构成 =
   flow **110~118 ms** / hift **68~82 ms** / 等 token **恒 74 ms** / 准备（搬运+autocast+切片）**仅 1~3 ms**。
   → 原以为的"~120 ms 固定工程开销"**不存在**；「削 `.to(device)` 搬运 / autocast」无对象可削。
3. **附带修复既存缺陷**：`_active_count` 缺 `global` 声明（阻塞挂载；重建镜像必崩）→ 已修，
   独立成单 `20260919_模块0_修复cosyvoice脚本global缺失.md`。
4. **附带发现镜像漂移（重大）**：容器实际运行的是镜像内烘焙的**旧版** server.py（1181 行），
   与仓库 HEAD（1271 行）差约 90 行（含 GPU 保活引用计数、`asyncio.to_thread` 推理重构）→
   **仓库改动未在生产生效**。
5. **容器已恢复生产状态**（去挂载、无探针），冒烟通过（`first audio 0.30s`）。

### 未闭合项

- **方案 C 后续选型（新，须人类裁决）**：
  - **D1** 削「等 token 74 ms」——需改**第三方源码** `cosyvoice/cli/model.py` 的 `tts()`；
    降 token 门槛可能影响首块连贯性/音质 → 有取舍
  - **D2** 优化 hift 首 hop（78 ms，实测为前序估算两倍）——无质量取舍，但需再插桩定位 hift 内部
  - **D3** 量化 flow（114 ms）——需人耳验收音质
  - **D4** 不再投入
- **镜像是否重建（新，须人类裁决）**：重建可让仓库 ~90 行改动（含 GPU 保活引用计数 +
  推理线程化重构）在生产生效，但需一次完整回归验证成本。
- 前序遗留：首轮瞬态根因（vLLM 后端波动，非代码可控）；`tests/test_config_router.py` 11 个既有失败。

### 接续入口

- 若选 D2：在 `_patch_first_hop_probe` 基础上对 `hift.inference` 内部再插桩
  （`hift.decode` / `_istft` / CUDA graph 命中情况），沿用挂载覆盖方式迭代。
- 若选 D1：先读 `third_party/cosyvoice-official/cosyvoice/cli/model.py` 的 `tts()` 与
  `flow.pre_lookahead_len` 实际值，评估降门槛的音质影响后再动。
- 若选重建镜像：`docker build -f docker/llm/Dockerfile.cosyvoice-vllm -t cosyvoice-vllm:latest .`
  （注意：**必须先确认 `_active_count` 修复已含在内**，否则 TTS 全挂）。

### 请示追踪

- **ASK-20260919-03 已闭合**（人类回「C试试」→ 方案 C）。
- **新增悬空请示 ASK-20260919-04**：方案 C 后续选型（D1/D2/D3/D4）+ 镜像是否重建。

### 审查状态

- **本轮（方案 C 步骤 1）尚未过 GN-004**。待人类选定下一步后，与后续改动**一并**送审
  （避免对同一文件重复审查）；若人类决定「暂停/收口」，则**立即补做** GN-004 复审，
  审查对象为：`docker/llm/cosyvoice_server.py`（探针 + global 修复）+
  `20260919_模块0_TTS首块固定开销定位.md` + `20260919_模块0_修复cosyvoice脚本global缺失.md`。

---

## 追加轮：D2 实施完成 —— 修复 hift CUDA graph 从未命中（2026-09-24 23:2x）

> 人类指令「继续」→ 承接方案 C，选取**无质量取舍**的 D2（优化 hift 首 hop）推进。
> 已过 GN-004 交付前审查（**警示放行**，agent `bd407524-7857-49c1-a9d4-470c44a4108c`，
> 无 [阻断]/[SOFT_BLOCK]），其 4 项 [警示] 与 2 项 [观察] 已修正。

### (1) 工程过程

1. **定位**：`_patch_hift_decode_cudagraph`（2026-08-18 上线）的 CUDA graph 是**单 shape 单例**
   （`state["graph"]` + 单个 `captured_key`），且「捕获仅在 `graph is None` 时进行」构成互斥死角 ——
   生产各 hop 的 shape 随 `token_hop_len` 递增与首 hop 长 `prompt_feat` 变化，与 warmup 捕获的
   shape 恒不同 → **既不命中也不重新捕获** → 该 patch 自上线起从未在生产生效（插桩实证全部 `命中=否`）。
2. **修复**：改为 `state["graphs"]` 多 shape 缓存（`OrderedDict` + LRU，上限 8），每个新 shape 各捕获一次；
   新增**捕获时一致性自检**；据 GN-004 W-2 追加**命中路径自检**（验证 replay 确实消费 `copy_` 的新输入）；
   据 O-2 将 entry 取值移入锁内（消除 LRU 淘汰竞态下的 `KeyError` 边缘）。
3. **验证**：稳态 3 次请求 + 两级自检日志（见下「最终结果」）。

### (2) 交接状态

- D2 代码修复：**已闭合**（实现 + 两级自检 + 性能实测）
- **第二阶段「消除首请求捕获成本」：已闭合**（人类 ASK-20260919-04 裁决后实施；
  新增 `_warmup_production_shapes`，首请求 `first audio` 0.72s → **0.23s**，与稳态持平）
- GN-004 交付前审查：**已闭合**（警示放行；W-1/W-2/W-3/O-2/O-3 **均已修正**；W-4 信号见「请示追踪」）
- **修复持久化：已闭合**（2026-09-25 镜像已重建并通过冒烟，见下「镜像重建」节）
- O-1（LRU 淘汰路径无运行证据）：**当前不可判定**（本轮仍未触发淘汰，仅静态审查通过）

### 镜像重建与冒烟（2026-09-25，人类裁决项执行完毕）

**镜像**：`docker build -f docker/llm/Dockerfile.cosyvoice-vllm -t cosyvoice-vllm:latest .` → 成功（exit 0）。
新镜像 `308544e37192`（29.9GB）；旧镜像已备份为 **`cosyvoice-vllm:pre-20260924-backup`**（`c3d6863235e9`，可回退）。

**冒烟（新镜像 + 无 server.py 挂载，即勾兑镜像内代码）**：

| 检查项 | 结果 |
|--------|------|
| 容器挂载 | 仅 `/workspace/ref_assets` + `/workspace/models`（**无 server.py**）→ 确证跑镜像内代码 |
| 容器健康 | healthy ✓（说明 `_active_count` global 修复生效，否则请求即 500） |
| 多 shape graph 捕获 | warmup 捕获 5 个（缓存 1/8~5/8）✓ |
| **生产 shape 预热** | 捕获 `(1,512,9)/(29)/(69)`（6/8~8/8），`Production-shape warmup complete in 3.8s` ✓ |
| 探针默认关闭 | 无 `[PROBE-*]` 输出 ✓（符合设计） |
| 主服务健康 | healthy（7 组件全 true）✓ |
| **TTS 端到端首块** | #0 = **290ms（首个请求）**、#1/#2 = 226ms → **首请求≈稳态，捕获成本已消除** ✓ |
| 容器内 `first audio` | **0.20~0.21s** ✓（与修复后挂载态一致） |
| 音频数据 | 185108 / 133128 / 119684 base64 字节，均正常 ✓ |

**未做**：EvalKit 全双工段回归（EvalKit 服务未启动）。

### (3) 最终结果

- **性能（三阶段，容器内 `first audio`）**：

  | 阶段 | 首个真实请求 | 稳态 |
  |------|-------------|------|
  | 修复前（单 shape 单例） | 0.72~0.77 s | 0.26~0.27 s |
  | 多 shape 缓存 + LRU | 0.29 s（含 70ms 诊断自检） | 0.20~0.21 s |
  | **+ 生产 shape 预热**（生产态） | **0.23 s** | **0.23 s** |

  首 hop 构成（稳态）：flow 108~125ms / 等 token 74~75ms / **hift 11~17ms**（修复前 76~79ms）/ 准备 1~3ms。
- **音频正确性**：捕获自检 8 个 shape + 命中自检 3 个 shape，**全部 `max|eager-replay| = 0.000e+00`**
  （逐位一致）；命中自检的输入与捕获输入不同 → 证明命中路径确实消费新输入。
  （命中自检已改为 `PROBE_FIRST_HOP` 门控，生产默认关闭以省去其 ~70ms 开销。）
- 产出物：`docker/llm/cosyvoice_server.py`（多 shape+LRU+两级自检+生产 shape 预热+global 修复+探针）；
  `docker/llm/start-cosyvoice-vllm.ps1`（`$RefAssetsPath` 只读挂载 + `--warmup-ref-assets`）；
  文档 `20260924_模块0_修复hift图缓存未命中.md`（含两阶段）等三份；临时脚本零残留。
- 合规：`public/` 与 `.trae/rules/` 零改动（GN-004 独立核实）。

### 实施中发现的必要条件（教训）

`tts()` 流式循环会把 `token_hop_len` 自增至 `token_max_hop_len`，故 streaming warmup 结束后
其值为 100。**生产 shape 预热前必须复位为 `args.stream_hop_len`**，否则预热产出的 shape
与生产请求不一致 → 预捕永不命中（首测即因此失效，日志表现为"预热完成但无新捕获"）。

### 未闭合项

- **⚠ 修复未持久化（最关键）**：当前仅靠 `-v docker/llm/cosyvoice_server.py:/workspace/server.py`
  **挂载覆盖**生效；容器镜像版（1181 行旧版，GN-004 已独立核实 `_active_count`=0 处、
  `state["graph"]`=4 处、无 `asyncio.to_thread`）**不含此修复**。
  **须人类裁决**：重建镜像 / 恢复生产（放弃修复）/ 继续挂载观察。
- **首个请求承担捕获成本**：首请求需捕获 5~8 个 shape，实测首请求 `first audio` 0.72~0.77s
  （稳态 0.20~0.21s）。属一次性成本；如需消除可在启动 warmup 阶段按生产参考音频预捕 shape（未实施）。
- 前序遗留：`ASK-20260919-03` 的第2项剩余候选（D1 等 token / D3 量化 flow / D4 停止）；
  首轮瞬态根因（vLLM 后端波动）；`tests/test_config_router.py` 11 个既有失败。

### 接续入口

- 若重建镜像：`docker build -f docker/llm/Dockerfile.cosyvoice-vllm -t cosyvoice-vllm:latest .`
  → 需完整回归（TTS 冒烟 + 音频抽听 + EvalKit 全双工段）；**构建前确认 `_active_count` 的
  global 修复已含在工作区**（否则 TTS 全挂）。
- 若继续 D1/D3：见 `20260919_模块0_TTS首块固定开销定位.md` 的候选表。
- **观测复用**：`PROBE_FIRST_HOP=true` 环境变量即可启用全部打点（默认关闭，生产零开销）。

### 请示追踪

- **⚠ ASK-20260919-04 仍未闭合，且范围已扩大**：
  ① **镜像是否重建（新增，最关键）** ② 第2项后续选型（D1/D3/D4）。
- **[GN-004 W-4 信号]**：本轮 D2 系人类「继续」指令下自行选定并实施，属「开放选择题被当作已裁决」的边缘。
  虽有披露与 `git checkout -- docker/llm/cosyvoice_server.py` 回退路径、且方向未偏离已批准的方案 C，
  但**信号必须送达人类**（本次报告已送达）。

### 审查状态

- **GN-004 交付前审查：已闭合**（警示放行，agent `bd407524-7857-49c1-a9d4-470c44a4108c`）。
  独立复现：容器日志性能数字逐项一致；镜像漂移经 `docker run --rm` 独立证实；`public/` 零改动经 git 核实；
  `_active_count` 缺陷经 `git diff` 证实为新增行（非误判）。
- **未独立验证项**（GN-004 明确声明，须人类知悉）：① 修复前「全部 `命中=否` / hift 76~79ms」的
  旧格式探针日志已被本次改动覆盖，**不可回溯复现**（基于执行者自述，佐证为 09-19 文档独立记录的 hift 68~82ms）；
  ② 真实生产中跨会话、跨参考音频的长时稳定性未验证（本次为同一参考音频、连续请求）；
  ③ LRU 淘汰行为无运行证据（本轮未触发）；④ 主服务 8000 侧全链路 TTFT 未复核（不在本单范围）。

---

# current-note — fix-memory-recall-zero-relevance（2026-09-25 文件末尾追加；追加式、不覆盖任何既有条目）

> 更新时间: 2026-09-25 | 变更ID: fix-memory-recall-zero-relevance | 阶段: **交付完成待 [V] 人类确认**（T0~T7 全部完成；GN-004 交付前审查警示放行 `0a04f905`；全量回归 5210 passed）

## 七字段交接状态

| 字段 | 内容 |
|------|------|
| 做到哪了 | T0~T7 全部完成并勾选；checklist 除 IX.4/IX.6（交付前审查记录/[V] 确认）外全部勾选（V.5 已勾：5210≥5187）；GN-004 交付前审查警示放行（`0a04f905`）；**追加修复 U1/U5/U6**（人类「修复剩余」指令）：定向 **181 passed**、真实链路验证通过、全量回归 **5215 passed**（≥ 基线 5187，+5）（留痕 `20260925_模块0_修复剩余观察项.md`）；**待人类 [V] 交付确认** |
| 为什么 | 用户指令「先修复一个严重问题：记忆召回3维评分可能会召回相关度为零的记忆（建议改为：相关性*（重要性+时间分数））」，指定 Skill：TRAE-code-review / TRAE-debugger；人类裁决 ASK-20260925-01/02 + [V] 三项（清理授权 / recent 保留 / T5b 修复） |
| 未闭合项 | ① **人类 [V] 交付确认（唯一阻断项）**；② 观察项 U2（阈值通过率，实测 inject 5→5 无下降）/ U3（NF5 覆盖极窄，已裁决保留）/ U4（延迟预算待嵌入服务 8101 在线复测）待放行；③ **U1/U5/U6 已修复（2026-09-25，人类「修复剩余」指令）**：3d 端点真实相关性映射注入（命中用真实分、不可用回退 0.5）、`_fill_missing_relevance` 失败短路（不重复嵌入）、回退分支 agent 隔离（留痕 `20260925_模块0_修复剩余观察项.md`；定向 181 passed、真实链路验证通过、全量回归 **5215 passed**）；④ 环境既有：weaviate 容器 unhealthy（8080 不可达）→ U1 命中路径真实链路验证受限（单测覆盖）；⑤ `.dbg/server_post_t5c_*.log` 为现行服务日志（T5b 遗留已随 16:14 重启清理） |
| 接续入口 | [V] 确认后交付完成；回滚按留痕文档第四章（还原 router/hybrid_search/advanced_mixin/decay 四文件 + 恢复测试断言）；U4 延迟预算待嵌入服务（8101）在线后复测 |
| 人类裁决记录 | ASK-20260925-01/02 已闭合；[V]（2026-09-25）三项已执行（T5 清理 / recent 并入保留评估 / T5b 修复） |
| 请示追踪 | 无悬空请示 |
| 审查状态 | 计划审查 4 轮（阻断→警示→阻断→警示放行）；检查点 `976ccf4f` 警示放行；代码变更后 `2c50ca36` 警示放行；**交付前 `0a04f905` 警示放行**（D1~D4；D1/D3 已修、D2/D4 已登记） |

## 三段交接

### (1) 工程过程
1. 勘察定位：`router.py` L308-312（加权和）、`advanced_mixin.py` L71-75（3d 同族）、`decay.py` L486（死代码无调用者）、`router.py` L302（缺省假相关性 0.5）、`config.py` L842（min_score_threshold=0.15）
2. AskUserQuestion 3 问（ASK-20260925-01）→ 三件套首版产出
3. GN-004 首轮计划审查：**阻断**（F1：recent 通道产出被 `all_memories` 死变量丢弃）→ 独立核实属实（git 证实 ≥`ec29e91`/2026-08-04）→ AskUserQuestion（ASK-20260925-02：**顺带修复并纳入**）→ 修正 F1~F10
4. GN-004 复审：**警示放行**（N1 Scenario 算术错误 / N2 recent 未按 agent_id 隔离 等）→ 修正 N1~N7
5. GN-004 三轮：**阻断**（agent `34c5a851`，SB-B 假闭合证据：**同文件并行编辑竞态致部分修正丢失**——spec.md 的 N1 Scenario/F9 行号/观察项登记表、tasks.md 的 T5 第二落点）→ 独立核实属实 → 三件套**整体重写回补**并处置 NF1~NF8（含 NF5 recent 通道可触发性登记、NF7 台账 [P2]、NF8 Impact 补列）
6. GN-004 四轮：**警示放行**（agent `e4a09a99`，无 [SOFT_BLOCK]；NF1~NF8 逐条与实体比对确认落地、三轮 SB-B 已消除）→ 观察项 NEW-1~NEW-4 处置（note 头部阶段/台账计数口径/标注归属）
7. **人类批准 Spec** → 实施 T0~T4：T0 留痕文档+基线（5187 passed）→ T1 debugger 插桩与证据（H1~H4 确认、NF5 覆盖极窄）→ T2a∥T2b 代码改造（死代码删除、docs 同步）→ T3 测试（1 断言更新 + 20 新增，173 passed）→ T4 pre/post 验证与观测（修复生效、触发线未触发、延迟归因嵌入服务离线）
8. GN-004 关键检查点审查：**警示放行**（agent `976ccf4f`，NF-A~NF-F；NF-A 三段交接刷新、NF-C 纳入 [V]、NF-F 登记）
9. **[V] 人类裁决（2026-09-25）**：① 确认修复有效、授权清理；② NF5"重新评估该并入"→ 评估结论"建议保留（成本≈0）"；③ 降级重复嵌入"本次一并修复"
10. **T5 清理**（`4b5421d6`：插桩 0 残留、Debug Server 停、debug 文件归档删除）→ **T5b 修复**（`dd885c03`：失败状态传递，真实链路失败次数 2→1、e2e −2324ms，176 passed）→ **GN-004 代码变更后复审：警示放行**（`2c50ca36`，N-1~N-6）
11. **T6 TRAE-code-review 完整流程**（主线程 + 2 独立验证 `1ccb62c0`/`2c300014` 交叉验证：2 问题 2/2、1 项 0/2 排除；用户裁决仅登记不修；报告落盘 `code_review_T6_20260925.md`）
12. **T7 收口**：全量回归 **5210 passed**（≥ 基线 5187）→ 留痕文档 status=已完成 + 第五章全回填 → note/spec 三段交接刷新 → **GN-004 交付前审查：警示放行**（`0a04f905`，D1~D4；D1/D3 已修、D2/D4 已登记）→ **待人类 [V] 交付确认**
13. **追加修复 U1/U5/U6（人类「修复剩余」指令，2026-09-25）**：留痕先行（`20260925_模块0_修复剩余观察项.md`）→ U5 失败短路 + U6 回退分支 agent 隔离 + U1 3d 端点真实相关性映射（`relevance_map`）→ 新增 5 测试（定向 181；全量 **5215** ≥ 基线 5187）→ 真实链路验证（3d 200 降级 / chat 无回归）→ **GN-004 复审查：警示放行**（`ccf260cb`，O1~O4 已处置）

### (2) 交接状态
- Spec 三件套：**已闭合**（人类批准 + 全回填）
- 实施 T0~T8（含 T5b/T8）：**已闭合**（全勾选、台账真实 agent id、证据落盘）
- checklist：**未闭合**（仅 IX.6 [V] 交付确认未勾；其余全勾）
- 交付前 GN-004 审查：**已闭合**（警示放行 `0a04f905`）+ 追加修复复审 **已闭合**（警示放行 `ccf260cb`）

### (3) 最终结果
- 验证结论（交付态）：全量 pytest **5215 passed / 0 failed**（≥ 基线 5187）；定向 181 passed（GN-004 复跑一致）；pre/post 修复生效（零相关 0.65→0 被过滤、弱相关 0.755→0.30、recent 由丢弃→纳入）；注入 30→30/5→5（触发线未触发）；T5b 失败 2→1、e2e −2324ms；**U1/U5/U6 追加修复落地**（3d 真实相关性 / 失败短路 / agent 隔离）；public/ 与 .trae/rules/ 零改动
- 产出物清单：代码 6 文件（含 memory.py 端点）+ 测试 5 文件（新增 28 条）+ 留痕文档 2 份 + 证据 9 份 + spec 三件套 + note 本章节
- 关键事实：**recent 通道产出被静默丢弃为既存缺陷**（已在 T2a 修复）；**NF5 覆盖极窄**（[V] 裁决保留）；**U1/U5/U6 经「修复剩余」指令补齐**
- 未闭合项（待 [V] 逐项放行）：人类 [V] 交付确认；U2 阈值通过率 / U3 NF5 覆盖极窄 / U4 延迟预算待复测 / O1 端点延迟退化 / O4 relevance_map 覆盖取舍
- [V] 裁决记录（2026-09-25）：① 确认有效授权清理；② NF5 重新评估 → 建议保留；③ 降级重复嵌入 → 本次一并修复（T5b）；④ 「修复剩余」→ U1/U5/U6 已修复；⑤ 交付确认（**未显式作出**，待人类一句话确认）

---

# current-note — package-modelstation-desktop-installer（2026-09-25 文件末尾追加；追加式、不覆盖任何既有条目）

> 更新时间: 2026-09-25 | 变更ID: package-modelstation-desktop-installer | 阶段: **Spec 三件套已写、GN-004 警示放行、待人类批准后进入实施**

## 七字段交接状态

- **任务**：把 `C:\CX-O\CXO-ModelStation` 独立打包 + 加独立前端（人类四项裁决：Electron 桌面安装包 / 全含 engines+data / 前端独立进程与端口 / 包内嵌便携 Python 环境）。
- **规格**：`.trae/specs/package-modelstation-desktop-installer/{spec,tasks,checklist}.md`（Task 0~5 + 台账 + 冻结的打包态目录契约）。
- **交接状态**：三件套 **已闭合**（GN-004 警示放行，观察项 O1~O8 已处置或已登记）；实施 **未开始**；人类批准 **[V] 未闭合**。
- **未闭合项**：人类 [V] 批准；实施期风险（见下「最终结果」未闭合项）。
- **接续入口**：人类批准 → Task 0（变更文档前置）→ P1 = Task 1（`frontend/*`）∥ Task 2（`tools/*`）→ Task 3 → Task 4 → Task 5。
- **回退锚点**：前一轮稳定点 = 纯浏览器站点形态的 `frontend/`（无 `electron/`）；实施失败按 tasks.md「回退锚点」章节回退，不得回滚工作树中与本 spec 无关的既有改动。

### (1) 工程过程

1. 需求收束：AskUserQuestion 四项裁决（产物形态 / 打包范围 / 前端形态 / Python 环境）已闭环。
2. 现状勘查（三路只读）：① APP-Frontend Electron 先例（electron 42 + builder 26 + vite-plugin-electron，NSIS，无 extraResources，主进程 `onHeadersReceived` 注入跨域头）；② ModelStation 引擎调用链（so-vits/MeloTTS 全走 config `python_path`，**VoxCPM 走 `sys.executable`**、CORS 白名单已含 3300、`_mount_frontend` 现状、engines 无权重、py311 实为 Anaconda 3.13.9 venv 且缺引擎依赖）；③ 姊妹项目 CX-A 的「Miniconda 现场装配 + PyInstaller onedir + Inno Setup」先例。
3. s0401 写前闸门：三件套=工程交接锚点（格式合规放行）、`frontend/`+`tools/`=免检通行区、根 `AGENTS.md`=保护资产（须人类批准）、无跨模块破坏性动作 → `ALLOWED`。
4. 三件套落盘 → GN-004 独立审查 → 观察项处置（见下）。

### (2) 交接状态

- 三件套：**已闭合**（spec/tasks/checklist 齐备；台账八字段齐、③⑤ 已按 rules-0 §四-11 填「待回填」）。
- GN-004（agent `676371ab`）：**警示放行**，无阻断、无 `[SOFT_BLOCK]`；11 项事实核对 PASS、1 项存疑（「CX-A 否决 NSIS」无记录佐证）。
- 实施与验证：**未开始**（Task 0~5 全未启动）。

### (3) 最终结果

- **规格产出**：spec 含 6 条 ADDED + 2 条 MODIFIED Requirements、无 REMOVED、**BREAKING 无**；新增「打包态目录契约（冻结）」（`resources/backend|runtime|engines|data` + 固定端口语义 + `directories.output: release`），作为 P1 两并行分支的唯一接口。
- **GN-004 观察项处置**：O1 Inno 回退未落子任务 → **已补 Task 3.3**（`.iss` 消费 `win-unpacked` + `iscc` 检测与显式报错）；O2 路径契约仅文字冻结 → **已写进 spec 冻结契约并扩展 O4**（output=release）；O3 vite-plugin-electron 与 vite 5.4/TS 5.6 兼容性 → **已写入 Task 1.1 前置冒烟**；O5 反代透传 multipart/Range 未落细 → **已写入 Task 1.2 与 checklist A**；O7 data 种子口径 → **已要求产物报告列种子清单 + checklist D**；O8 checklist 三值口径 → **已在 checklist 头部声明**；O6 `--profile base` 略超裁决范围 → 保留（默认 full，不阻塞交付），登记为人类可裁剪项。
- **关键事实（供实施者免于重查）**：`sovits_svc.python_path` / `melotts.python_path` 默认 `"python"`，训练与预处理子进程全部跟随该配置；`voxcpm_client` 用 `sys.executable` 且未覆盖子进程 `env=`（故父进程 `PYTHONPATH` 可传递）；后端无 WebSocket 需求；桌面壳走「本地静态服务 + `/api` 反代」同源路线，故不依赖后端 CORS 改动。
- **未闭合项**：① 人类 [V] 批准（三件套 + 冻结契约）；② 实施期实测项——full profile 体积与安装包形态判据（NSIS/Inno）、CUDA 轮子档位、构建网络与磁盘可行性；③ 人工清单（真实装机 / GPU 实战训练 / 安装包实装 / 离线权重训练链路，见 checklist G）。
- **接续入口**：人类批准 → 实施；GN-004 结论为行为约束（警示放行 + 观察项已处置，无 SOFT_BLOCK，无需人类裁决观察项）。

---

# current-note — package-modelstation-desktop-installer（2026-09-26 交付完成，追加；追加式、不覆盖任何既有条目）

> 更新时间: 2026-09-26 | 变更ID: package-modelstation-desktop-installer | 阶段: **实施 + 验证 + full 档安装包编译全部完成；人工清单（G）待真机验收**

## 七字段交接状态

- **任务**：把 `C:\CX-O\CXO-ModelStation` 独立打包 + 加独立前端（人类四项裁决：Electron 桌面安装包 / 全含 engines+data / 前端独立进程与端口 / 包内嵌便携 Python 环境；追加裁决：现在装 Inno 编译 full 安装包 + 授权根 AGENTS.md 最小注记）。
- **规格**：`.trae/specs/package-modelstation-desktop-installer/{spec,tasks,checklist}.md`（Task 0~6 全勾选；台账 8 行全填真实 agent id）。
- **交接状态**：Task 0/1/2/3/4(+4.7~4.9)/5/6 **全部闭合**；checklist A~F 已核验勾选（安装包与文档两项随 Task 6 终值同步勾选）；G 人工清单与 H 本机不可判定项**保留未闭合**。
- **交付物**：`release\CXO-ModelStation-Setup-0.1.0.exe`（2,404,765,295 B）+ `release\win-unpacked`（34,216 文件 / 6,024,276,063 B）+ `release-nsis-trial`（base 档 NSIS 112.7 MiB）+ `build/runtime`（full/cuda 便携运行时，搬迁自检 PASS）。
- **未闭合项**：checklist G（真机实装 / GPU 实战训练 / CUDA 实测 / 离线权重训练链路 / 卸载残留策略）+ H（窗口崩溃路径回收、窗口聚焦断言、`voxcpm_cli` informational、签名与图标、`build_runtime.py --runtime-dir`）。
- **接续入口**：人类按 checklist G 在真实目标机验收；如需严格复现交付，命令为 `python CXO-ModelStation/tools/build_desktop.py --runtime-profile full --torch-index cuda --form inno`（前置：Inno Setup 6 + `iscc` 在 PATH 或默认/逐用户路径）。
- **回退锚点**：纯浏览器站点形态的 `frontend/`（无 `electron/`）+ 未打包的 `CXO-ModelStation`（引擎/数据全程只读，基线 engines 320 文件 / 28,987,533 B、data 46 文件 / 66,454 B 未被改动）。

### (1) 工程过程

1. Spec 三件套 → GN-004 规格审查（警示放行，`676371ab`，O1~O8 已处置）→ 人类批准。
2. Task 0 变更文档前置（主线程）→ P1 并行：Task 1 桌面壳（`dbbfea77`，78 passed）+ Task 2 便携运行时（`63291fd2`，base/full 两档 + 搬迁自检）。
3. Task 3 打包编排（`617da184`，base 命中 NSIS、full 降级 dir + 报告）→ Task 4 打包态注入与数据根（`49b00789`，11/11 断言、端口顺延 8300→8310、VoxCPM 入口修正）。
4. Task 4.7~4.9 补线（`5cede7d3`）：既有 12 项失败修复（149 passed）、打包器只读加固、健康门余量 180s。
5. Task 5.1~5.2 独立验证（`ba61f04f`）：三闸门 + 运行时搬迁自检复跑全 PASS。
6. Task 6（`9f6bd535`）：定位逐用户 Inno 6.7.3 → `--form inno` 重建 win-unpacked（含主线程 `PYTHONDONTWRITEBYTECODE` 注入）→ 编译 full 安装包（1010.3s）→ 静默安装/卸载抽验。
7. 主线程：`build_desktop.py` 补 iscc 逐用户候选路径（复现性）、DEPLOY §8 / README / AGENTS.md（已授权）/ `.gitignore`、变更文档五~八章回填、checklist 核验、本 note。

### (2) 交接状态

- 实施与验证：**全部闭合**（含补线与追加裁决项）；三闸门与运行时闸门均由独立子代理复跑 PASS。
- 交付前 GN-004：规格阶段已执行（警示放行）；**实施后 GN-004 独立复审未执行**（登记为待办，建议主线程/后续会话拉起）。
- 人类裁决记录：四项交付裁决 + full 安装包编译裁决 + AGENTS.md 授权（均已落 spec/tasks/变更文档）。

### (3) 最终结果（可验证证据链）

- **后端**：`pytest tests -q` → **149 passed / 0 failed**（含修复的 12 项既有失败：`TASK_TYPE_VOICEDESIGN` 常量名 + 陈旧端点同步）。
- **前端**：`tsc --noEmit` 双段退出码 0；`vitest run` **10 文件 / 95 passed**（含主进程单测）。
- **E2E（打包产物直启）**：`3300/` 200 HTML、`3300/health` healthy、后端由包内 `resources\runtime\python\python.exe -m modelstation.main` 持有、反代业务 API 200、二次启动单实例、优雅关闭零残留端口全释放、数据根两次启动 SHA-256 逐字节一致、产物目录 `*.pyc=0`。
- **运行时**：搬迁自检 PASS（副本导入 + 副本起后端 healthy + 绝对路径扫描 RELOCATABLE/0 阻断）；体积 base 46MB / full-cpu 1917MB / full-cuda 5636MB。
- **安装包**：full 档 Inno **2,404,765,295 B（2293.4 MiB）**、payload 5.897 GiB、压缩比 ≈0.38、静默安装/卸载通过且数据根未受影响；base 档 NSIS 112.7 MiB。报告 `installer_produced=true` / `degraded=false`。
- **留痕**：变更文档 `.trae/documents/20260925_模块7_模型工作站桌面安装包与便携运行时.md`（五~八章已回填，status=已完成）+ 证据 6 份（`test_reports/package-modelstation-desktop-installer/{task1_desktop_shell,task2_portable_runtime,task3_packaging,task4_injection_dataroot,task4b_fixes,task5_verification,task6_inno_installer}.md` + `task6_build.log`）。
- **未闭合项**：见七字段「未闭合项」（checklist G 人工清单 + H 本机不可判定项），不得视为已完成。
- **接续入口**：① 主线程对实施后产出拉起 GN-004 独立复审；② 人类按 checklist G 真机验收；③ 可选增强：为 `build_runtime.py` 加 `--runtime-dir`、加应用图标与签名。

### (4) GN-004 交付前复审（2026-09-26，agent `71f02f8e`）

- **结论：警示放行**（无阻断、无 `[SOFT_BLOCK]`）；独立复现 11 项 PASS（含实跑 pytest 149 passed、vitest 10 文件 95 passed、`release/` 产物体积精确相符、`app.asar` 含 `PYTHONDONTWRITEBYTECODE` 且健康门常量 `0x18e4`=180000、包内后端两点修复已生效、`git diff -- AGENTS.md` 仅授权一行、`public/` 与 `.trae/rules/` 零改动、engines/data 基线与 pyc=0 一致、台账 9 行与三段交接齐备、G/H 未闭合如实保留）。
- **已处置观察项**：
  - O1（真实缺陷，已修）：DEPLOY §8 原句「full 档安装包未产出，仅便携目录」与实产矛盾 → 改为 §8.1「两种用法（安装包 / 便携目录）」+ §8.4 实测终值表（full 安装包 2293.4 MB），并补安装包直用指引。
  - O2（已修）：§8.4 手工编译命令补齐 `/DPayloadDir /DOutputDir /DAppVersion` 与 cwd，对齐报告中的真实调用。
  - O5（已修）：种子计数口径统一为「清单 46 条（含 2 个 `.gitkeep`）+ 6 个可写子目录 + `.seed.json`」（变更文档第四章、checklist E 同步）。
- **登记为接续（非阻断）**：
  - O3：`tests/test_dataset_builder.py` 被根 `.gitignore` 的 `test_*.py` 规则忽略、未入版本控制 → 其端点/manifest v2 同步仅存运行态证据，clean checkout 会丢失；建议后续纳入白名单或存 diff 快照。
  - O4：产物报告 payload 估算把 `engines/MeloTTS/.git`（42 文件 / 6.4MB）计入，而 extraResources 实际排除 `.git` → 估算略高估（不影响判据结论，5.897 GiB 远超 2 GiB 上限）。
  - O6：`task5_verification.md` 记录的「运行期 240 个 `.pyc`」属旧构建（当时 main.js 尚无注入），Task 6 重建后已为 0（当前 `release\win-unpacked` 复核实测 pyc=0）。
  - O7：`release-nsis-trial/`（base 档 NSIS 试跑产物）在盘且已被 `.gitignore` 排除，非正式交付 → 交付后可删，DEPLOY §8.4 已标注「试跑产物，非正式交付，可删」。

---

# current-note — evalkit-full-duplex-regression（2026-09-25 文件末尾追加；追加式、不覆盖任何既有条目）

> 更新时间: 2026-09-25 20:15 | 变更ID: evalkit-full-duplex-regression | 阶段: 回归完成，交付前 GN-004 审查中

## 七字段交接状态

| 字段 | 内容 |
|------|------|
| 做到哪了 | 全双工段回归完成，**并已执行人类要求的补充验证**：环境恢复后 n=3 两轮曾达标（791.3 / 510.6 ms），但加大取样后**判定翻转为不达标且不稳健**——turns=9 一轮（run4 `1df27b8d`）8/9 轮 449.8~668.5 ms、第 7 轮 5152.7 ms → P95 **3359.0 ms ❌**；12 轮连续探测 2/12 离群（5375.8 / 5352.3 ms，均 asr_final 后 +4.0 s）。留痕已修订（第五章）+ 4 份证据落盘 |
| 为什么 | 用户指令「搞定EvalKit 全双工段回归」，追问后选择「要求补充验证」。首轮 run 复现 5557.8 ms 超标，根因锁定为两个容器停机（LLM 8002 / 嵌入 8101）致每轮检索 +2s；恢复后 n=3 达标，但补充验证揭示**间歇性后置停滞**（~10~17% 轮次 ~4~5.4 s），分层排除 ASR/LLM（440 请求无 TTFT>2.5s）/TTS（first audio 0.2-0.3s）/嵌入（169 请求 <0.5s）/weaviate（ready 4ms）引擎，指向主服务编排-检索客户端路径（`rag_search` 空闲后首调 ~2.2s，两次复现） |
| 未闭合项 | ① **全双工段 ~10~17% 轮次 ~4~5.4 s 后置停滞（离群），达标稳健性未建立**；成因指向主服务编排/检索客户端路径，需单独立项排查（涉主服务代码改动，须先写变更文档+人类裁决，本次未擅自改）；② REST 段 E2E P95 9.2~14.5s 超 2000ms（LLM 生成速度主导，9/19 各轮同样未达标，历史既有）；③ `weaviate` unhealthy 定性为 healthcheck 误报（功能正常，未处置）；④ 人类 [V] 交付确认 |
| 接续入口 | EvalKit 本地 8300（本会话后台 job-`dbe35bcf60cd470ebde2c7bd05cc75c2`）；重跑：`POST http://localhost:8300/api/v1/runs {"suite":"latency"}`；加大取样：加 `"config_overrides":{"latency":{"ws_full_duplex":{"turns":9}}}`；报告：`GET /api/v1/runs/{id}/report` |
| 人类裁决记录 | 人类「要求补充验证」（ASK-20260925-EvalKit-01）已闭合：补充验证已执行并回填（判定翻转）；新一轮 [V] 交付确认待裁决 |
| 请示追踪 | 无悬空请示（补充验证请示→执行→回填链路闭合） |
| 审查状态 | GN-004 交付前审查（首轮）：警示放行（agent `e528d4ed`，无 [SOFT_BLOCK]）；**补充验证后复审：警示放行、无 [SOFT_BLOCK]**（agent `c809913c`，A~E 全 PASS，含 runs 表 `config_snapshot.latency.ws_full_duplex.turns=9` 硬证据）；观察项：O-1 status 语义已按建议澄清（frontmatter 加范围声明 + residual/pending_defect）｜O-2/O-4/O-5 仅登记｜O-3 正线索未复现（间歇触发，非反证） |

## 三段交接

### (1) 工程过程

1. 运行态勘察：EvalKit 未运行、ASR(8005)/TTS(8094) 在线、**LLM(8002)/嵌入(8101) 停机 21h**、系统代理 7897（TargetClient 已 `trust_env=False`、WS 探测已 `proxy=None`，无需改）
2. `docker start vllm-gemma4`（126 s 就绪，GPU0/原配置复现）+ `docker start cxhms-vllm-embedding`（65 s 就绪，CUDA_VISIBLE_DEVICES=1/GPU1）
3. EvalKit 本地起 8300 → 冒烟 `POST /api/chat` 200 → run1 `aaf6a5f7`（report 口径 ≈300 s / 4m59s，ws_p95 5557.8 ms ❌ 复现）
4. 分层定位：WS 原始事件时间线（临时脚本，用后即删）+ vLLM Prometheus 指标差分 + TTS 容器日志 + 9/19 检索耗时对比
5. 恢复嵌入后复测：rag_search 2053→72 ms、单轮 partial→首包 4117→497 ms → run2 `ed3c34e2`（791.3 ✅）、run3 `a026f2c3`（510.6 ✅）
6. 留痕 `.trae/documents/20260925_模块0_EvalKit全双工段回归.md` + 证据 `.trae/documents/test_reports/evalkit_ws_full_duplex_20260925/`
7. GN-004 交付前审查（首轮，agent `e528d4ed`）：警示放行、无 [SOFT_BLOCK]，观察项 ①~④ 已处置/登记
8. **人类裁决「要求补充验证」→ 加大取样**：run4 `1df27b8d`（`config_overrides` turns=9，P95 **3359.0 ms ❌**，8/9 轮 449.8~668.5 ms、第 7 轮 5152.7 ms）+ 12 轮连续探测（**2/12 离群** 5375.8 / 5352.3 ms，均 asr_final 后 +4.0 s）
9. 离群分层排除：LLM 直方图（440 请求无 TTFT>2.5s、queue≤0.3s）／TTS（0.20~0.29s）／嵌入（169 请求≤0.5s）／weaviate（ready 4ms；unhealthy=healthcheck `curl` 误报）；线索 = `rag_search` 空闲后首调 ~2.2s（2197.8 / 2177.3 两次复现）；留痕修订第五章 + 证据 `ws_12turns_repeat_after_restore.txt`

### (2) 交接状态

- 全双工段回归：已完成，但**判定经补充验证翻转**——稳态 440~700 ms（4 轮 run 中 n=3 两轮曾判达标），
  但 ~10~17% 轮次存在 ~4~5.4 s 后置停滞（turns=9 的 P95 = 3359.0 ms ❌）→ **达标稳健性未建立**
- 补充验证（人类要求）：已完成并回填（run4 turns=9 + 12 轮连续探测；离群分层排除四引擎）
- 环境依赖恢复：已闭合（LLM 8002 / 嵌入 8101 容器运行中，`rag_search` 常态 72~90 ms）
- 留痕文档：已完成（status=已完成）
- REST 段阈值：未达标（历史既有观测项，未处置）
- GN-004 交付前审查：两轮均已闭合（首轮警示放行 `e528d4ed`；补充验证后复审警示放行 `c809913c`，均无 [SOFT_BLOCK]）
- 人类 [V] 交付确认：未开始

### (3) 最终结果

- 验证结论（**经补充验证修订**）：全双工段**稳态** partial→首包 440~700 ms（远优于 800 ms 阈值），
  但 **~10~17% 轮次出现 ~4~5.4 s 后置停滞**（asr_final 后 +3.97~4.0 s）——
  turns=9 一轮 P95 = **3359.0 ms ❌**、12 轮探测 2/12 离群（5375.8 / 5352.3 ms）→ **达标稳健性未建立**；
  n=3 的 run2/run3（791.3 / 510.6 ms ✅）属小样本未命中离群
- 离群归因（分层排除）：ASR 段正常（partial 362~423 / final 1742~1802 ms）；LLM 440 请求无 TTFT>2.5s 且 queue≤0.3s；
  TTS 逐段 first audio 0.20~0.29 s；嵌入 169 请求 ≤0.5 s；weaviate ready 200@4 ms（unhealthy 系 healthcheck `curl` 误报）
  → 指向**主服务编排/检索客户端路径**（旁证：`rag_search` 空闲后首调 ~2.2 s，两次复现；同族于当日"嵌入离线 +2 s/轮"）
- 产出物：四轮 run 报告（`CXO-EvalKit/data/runs/{aaf6a5f7,ed3c34e2,a026f2c3,1df27b8d}/report.md` + `detail.json`）、
  三份 WS 事件证据（前/后时间线 + 12 轮复测）、留痕文档（含第五章补充验证）
- 环境状态变更（用户须知）：`vllm-gemma4`(8002/GPU0)、`cxhms-vllm-embedding`(8101/GPU1) 已恢复运行；EvalKit 本地 8300 运行中（后台 job）

---

# current-note — fix-dual-stream-post-final-stall（2026-09-25 文件末尾追加；追加式、不覆盖任何既有条目）

> 更新时间: 2026-09-25 21:15 | 变更ID: fix-dual-stream-post-final-stall | 阶段: 分析中（定位已收敛，待人类授权重启/插桩）

## 七字段交接状态

| 字段 | 内容 |
|------|------|
| 做到哪了 | **根因已定位并修复**：循环监视（独立线程+栈快照）捕获 4 次 lag 7.8~8.3 s，栈含 `ssl.create_default_context(cafile=certifi.where())`——本机实测该调用 **6074 ms**、`httpx.AsyncClient()` 构造 **7979 ms**；触发源 = `RssFetcher.fetch()` **每次调用新建客户端**（自主/梦境新闻路径）。**修复 2**（`rss_fetcher.py` 复用 `get_shared_http_client()`）验证：fetch#2 从 ~8 s 降到 **2.7 ms**、12 轮无停滞、`/health` 的 7.8~8.3 s 尖峰消失（原每轮 2 次）。**修复 1**（`prefix_warmup.py` 预热限流）此前已验证（引擎长间隔 90~180 s → ≤30 s） |
| 为什么 | 人类连续选择「立项修复 → A+B 插桩 → B 继续排查循环阻塞」；根因与两项修复均由实测证据支撑（含监视器栈快照 + 隔离计时 + 子进程双次 fetch 对比） |
| 未闭合项 | ① agent 创建窗口仍有 1 次 ~2 s 循环占用（成因未定位，低频）；② 混合负载下全双工 P95 仍可能 >800 ms（LLM 首 token 抖动，独立观察项）；③ **插桩/调试服务器/调试记录/`.dbg/` 待人类确认后清理**（调试记录 `[OPEN]`）；④ 修复仅 2 个文件（`prefix_warmup.py`、`rss_fetcher.py`），未触 `public/`/rules/入口文件 |
| 接续入口 | 人类确认修复 → 清理插桩（`audio.py` P0~P6+M，grep 验零残留）→ 停调试服务器（7778）→ 删 `debug-dual-stream-post-final-stall.md` 与 `.dbg/` → 变更文档置已完成 + GN-004 交付前审查 |
| 人类裁决记录 | ASK-20260925-EvalKit-02（后续处置）= **立项修复**，已闭合；新一轮授权（重启/插桩）**待裁决** |
| 请示追踪 | 待裁决请示 1 项（重启授权），未悬空 |
| 审查状态 | GN-004 交付前审查：未开始（status=分析中，未到交付） |

## 三段交接

### (1) 工程过程

1. s0401 写前闸门：`ALLOWED`（`.trae/documents/`=锚点；主服务业务代码=免检通行区；不涉 `public/`/`.trae/rules/`）
2. 只读代码勘察（Explore agent）：dual_stream 入口 `audio.py:1706`、管线 `_run_pipeline:614`；三入口共用 `retrieve_memory_context`+`build_messages`；`weaviate_store` `connect_to_local(Timeout(init=2))` 且 host=`localhost`；`db_mixin:221-258` 健康检查单次失败即 null+重建；`utils:168-210` 共享 httpx（keepalive_expiry=30 / pool=10）；`prefix_warmup` 与在线路径共享 client
3. 运行时实验（只读）：**A/B `use_memory=false` 停滞仍在（2/8）→ 排除记忆路径**；`/health` 并发采样 651+652+989 次 → **排除全局事件循环阻塞**（仅每脚本 1 次 ~2052 ms 尖峰，疑为 agent 创建触发的 prefix 预热）
4. 容器日志对齐：停滞窗口 TTS **空闲 89 s**、LLM **无请求** → 停滞在"LLM 调用之前"
5. 变更文档落盘（含附录证据 + 步骤 A/B 候选）

### (2) 交接状态

- 变更文档：已完成（status=分析中）
- 诊断定位：分析中（收敛：管线前段等待 + 随 uptime 退化）
- 修复实施：未开始（待授权）
- GN-004 审查：未开始

### (3) 最终结果

- 已确认结论：停滞**非** ASR/LLM/TTS/嵌入/weaviate 引擎侧、**非**记忆路径、**非**全局阻塞；位于 asr_final 之后 ~+4.0 s 的"LLM 调用前"编排等待；停滞率随服务运行时长上升（17%→25%→42%）
- 产出物：变更文档（模块0-20260925-04，含两轮运行时证据）
- 待人类授权：主服务重启（步骤 A 判定退化假设）或重启+插桩（步骤 B 确定等待点）

### (4) 更新（2026-09-26 14:35，追加式）：修复 3~6 交付完成，**全双工段 WS P95 达标（690.6 ms ✅）**

| 字段 | 内容 |
|------|------|
| 做到哪了 | 人类裁决「服务端继续定位并治本」→ 四轮修复落地并逐轮验证：**修复 3**（预热补齐 tools）→ **修复 4**（首包窗口判定门控，假设证伪但护栏保留）→ **修复 5**（标签预设优先，人类自定义指示）→ **修复 6a/6b**（缺失闭合标记兜底）；最终 run `61c0d61c` **WS P95 = 690.6 ms ✅ passed**（逐轮 535~758 ms）；定向 pytest **230 passed**（含新增畸形标签用例 2 例） |
| 为什么 | 定位链（P7a/P7b 插桩 + TTS 容器对齐 + P8 请求指纹）：① 预热请求缺 `tools` → vLLM 前缀块边界位移 → **预热永不命中**（turn0 首 token 639.9→79.7 ms）；② 残留抖动 = **情感标签生成**（30~40 token 全在首包之前，~11ms/token）；③ 模型偶发**漏闭合标记** → 标签 JSON 泄漏进 TTS（会被念出）+ 切片器整段缓冲（首包拖到流尾，+325 ms） |
| 未闭合项 | ① **插桩清理**（`audio.py` P0~P8 共 12 处 debug-point region + `utils.py` P8 region + `_dbg_first_chunk_seen` + 调试服务器 7778 + 调试记录 + `.dbg/`）——人类裁决"方案定案后再清理"，**现已定案待执行**；② 清理后干净基线复跑；③ GN-004 交付前审查；④ REST 段历史既存未达标（非本任务范围） |
| 接续入口 | 清理（`grep -c debug-point` 归零为验收）→ 停调试服务器 → 删 `debug-dual-stream-post-final-stall.md` 与 `.dbg/` → 重启主服务 → `turns=9` 干净复跑 → GN-004 交付前审查 → 变更文档 status 置"已完成" |
| 人类裁决记录 | ASK-20260926-01（主方向=服务端治本；附加=2a/2b/提高 turns；清理=定案后）已闭合；ASK-20260926-02（标签＝预设优先，自定义回答）已闭合 |
| 请示追踪 | 无悬空请示 |
| 审查状态 | 检查点 GN-004：警示放行（agent `8af92731`，附四 F1~F12 已按 F1/F2/F3/F4/F6/F10/F11 修正）；交付前审查：未开始 |

#### 关键产物（供接续者快速接手）

- 变更文档：`.trae/documents/20260925_模块0_全双工首包后置停滞修复.md`（附四~附十一：定位链 + 四轮修复 + 逐轮 run 对比）
- 调试记录：`debug-dual-stream-post-final-stall.md`（12 点插桩清单、离线复核、`[OPEN]` 清理门）
- run 证据：`CXO-EvalKit/data/runs/{53f2825b,3f8ae8c5,4a816168,97a62a8a,61c0d61c}/`
- 本轮修复文件：`prefix_warmup.py`(3)、`audio.py::_maybe_agent_interrupt`(4)、`prompt_builder.py::REALTIME_VOICE_PROMPT_PADDING`(5)、`emotion_instruction_service.py::strip_instruction`(6a)、`tts_service.py::split_text_streaming`(6b)、`tests/test_emotion_instruction_service.py`(+2 用例)
- 诊断脚本（临时，可删）：`%TEMP%\cxo_*`（agentcreate/warmup/coldprefix/attrib_probe/p7_analyze/tts_align/p8_*/gate_check/label_leak/tok_gap/strip_test）
- **注意**：运行期发现并行会话改动同一文件（`emotion_instruction_service.py` 的 6a 修复曾被回退一次）→ 清理阶段每步改完须立即 grep 复核

### (5) 更新（2026-09-26 15:1x，追加式）：清理完成 + 干净基线双跑达标，**交付已闭合**（GN-004 警示放行 + [V] 已批准）

| 字段 | 内容 |
|------|------|
| 做到哪了 | ① **插桩清理**：`audio.py` 11 处 region + 实例属性、`utils.py` P8 整块全部移除（CX-O-SERVER 全仓 `grep "debug-point\|_dbg\|p8_hook\|cxo_p8"` = **0**；`py_compile` OK；修复 1~6 逐项复核全部在位未回退）；② **调试环境清理**（人类裁决授权）：调试服务器 7778 停止；`debug-dual-stream-post-final-stall.md` + `.dbg/`（10 文件）+ `%TEMP%\cxo_p8_hits.log` 删除（前两项为 git 跟踪产物，可经 git 历史回溯）；③ **主服务重启**（14:45:48，detached，日志 `main_clean_stdout/stderr.log`；预热门控「20/20 + 推理后端预热全部完成（共 4 轮）」@14:50:11 后才触发 run）；④ **干净基线双跑达标**：`a90a789b` P95 = **763.2 ✅**、`16d9bafb` P95 = **698.4 ✅**；⑤ **修复 2 配套测试对齐**（清理后定向回归发现旧测试 patch `rss_fetcher.httpx` 失效 → 改 patch `server.core.utils.get_shared_http_client`，实现零改动）→ 定向 **354 passed / 0 failed**；⑥ 变更文档附十二/附十三回填、frontmatter status → **已完成** |
| 为什么 | 清理后需在无插桩扰动下重建达标证据（原 61c0d61c 690.6 ✅ 为含插桩口径）；追加第二次干净复跑用于支撑"稳定达标"表述（三次连续通过） |
| 未闭合项 | ① ~~人类 [V] 交付确认~~ **已批准（2026-09-26，ASK-20260926-03）**；② REST 段历史既存未达标（登记，非本任务范围）；③ GN-004 声明的 3 项"未独立验证"已登记（见审查状态行）；④ `%TEMP%` 本任务诊断脚本已清理（见临时文件清理行） |
| 接续入口 | **交付已完成**（变更文档 status=已关闭）；如后续复现，可参照附十四登记项与附六分析方法；REST 段历史项建议单独立项 |
| 人类裁决记录 | ASK-20260926-01/02 已闭合；**ASK-20260926-03（[V] 交付确认）= 批准交付**，已闭合 |
| 请示追踪 | 无悬空请示（[V] 请示 → 批准 → 闭合） |
| 审查状态 | 交付前审查：**警示放行**（agent `03bf0dc1`，无 [SOFT_BLOCK]）；3 项"未独立验证"声明已登记（会话裁决原文未落盘 / 运行态日志未复核 / `.dbg` 精确计数）；人类 [V] 已批准 → **交付闭合** |
| GN-004 观察项处置 | O-1 变更文档 frontmatter 的 related_files 已按"修改 / 已入库 / 净零 / 勘查引用 / 关联锚点"分类；O-2 REST p95 改为逐 run 列示（10348.4 / 10691.2 / 11294.5）；O-3 变更文档第二/三章加"已被附录取代"注记 + 步骤逐条勾选；O-4 父任务文档 frontmatter 置"已闭合"并补交叉引用 |
| 临时文件清理 | `%TEMP%` 本任务专属诊断脚本 **31 个已删除** + 空目录 `cxo_dumps`；保留 `cxo_evalkit_*.log`（在线服务）/`cxo_leader_*`/`cxo_task5`（他会话） |

#### 干净基线双跑证据（turns=9，同一口径）

| run | WS P95 | 阈值 | passed | 逐轮 p→f（ms） | timeouts/errors |
|-----|--------|------|--------|----------------|-----------------|
| `a90a789b`（干净 #1） | **763.2** | 800 | ✅ | [541.4, 781.2, 736.2, 558.5, 729.3, 734.8, 545.0, 543.8, 468.1] | 0/0 |
| `16d9bafb`（干净 #2） | **698.4** | 800 | ✅ | [554.6, 611.5, 756.3, 602.0, 536.9, 535.1, 517.5, 568.9, 576.2] | 0/0 |

- run 总体 status=failed 仅因 REST 段历史既存项（overall p95 约 10.3~11.3 s > 2000：三 run 分别为 10348.4 / 10691.2 / 11294.5，均 0 失败请求）；WS 判定以 `metrics_summary.ws_full_duplex.judgment.passed=true` 为准。
- 调试记录已删除（其证据蒸馏入变更文档附二~附十三）；新增 run 证据：`CXO-EvalKit/data/runs/{a90a789b,16d9bafb}/`。

---

# current-note — fix-dream-rest-attr-mismatch（2026-09-27 文件末尾追加；追加式、不覆盖任何既有条目）

> 更新时间: 2026-09-27 01:00 | 变更ID: fix-dream-rest-attr-mismatch | 阶段: **实现+验证完成，交付前 GN-004 审查中**

## 七字段交接状态

| 字段 | 内容 |
|------|------|
| 做到哪了 | 梦境 REST 端点属性错配（`engine.buffer/consolidator/purge_job` vs 真实私有 `_buffer/_consolidator/_purge_job`）已修复：路由 6 处访问改私有名 + 模块 docstring 补口径说明；三处测试替身（test_dream_router FakeEngine / test_pagination_clamp SimpleNamespace / last_reason 断言）同步改名；新增 `TestRealEngineAttributeAlignment`（真实 DreamEngine 驱动 list/confirm/purge） |
| 为什么 | 用户指令「检查一下自主生命功能和梦境功能，详细解释那两个的工作逻辑」→ 体检发现 P0（接口 500）/P1（动机退化为常量）/P2（梦境缓冲 0 条）；用户裁决：**修 P0 按 rules-6 流程走** + **P1 一起评估接线方案** |
| 未闭合项 | ① ~~人类 [V] 交付确认~~ **已闭合**（ASK-20260927-03，2026-09-30 批准交付，与后续变更单 remove-autonomy-budget-and-gates 一并交付）；② **P1 动机接线 = 仅方案态未实施**（方案见变更文档附录 A，待人类裁决后再开单）；③ P2 梦境缓冲 0 条属"能跑未跑起来"（physio.enabled=false 下仅睡眠窗口边沿一条触发路径），随 P1/配置另行评估；④ 本轮未改 `public/`、未改引擎实现 |
| 接续入口 | 交付确认后：重启后端使路由修复生效；`GET /api/dream/list` 即应返回 200；P1 若批准，按变更文档附录 A.2 的四处接线点（read_news/search → info_ingestion、write_post → interaction、start_live/stop_live → activity、感知素材非空 → material）在 `_run_round` 执行后挂钩 |
| 人类裁决记录 | ASK-20260927-01（P0 处置 + P1 是否并办）=「修 P0 按 rules-6 流程走」+「一起评估接线方案」，已闭合 |
| 请示追踪 | 无悬空请示 |
| 审查状态 | 交付前 GN-004 审查：**警示放行**（无 [SOFT_BLOCK]，agent `4065124b-f853-45de-b76b-a7b30d8dfe74`）；4 项 [观察] 已全部处置（见下方追加行） |

## 三段交接

### (1) 工程过程

1. 体检（只读）：读 `server/autonomy/main.py`（装配）、`core/loop/autonomy_engine.py`（五层流水线）、`core/motivation/state.py`、`core/scheduler/circadian.py`、`core/planner/action_planner.py`、`dream/engine.py` 与 dream 全子模块；核对运行时数据（`audit_logs.jsonl` / `manager_state.json` / `motivation_state.json` / `dream_buffer.db` / 两个 `*.migrated` 配置）。
2. 定位 P0：`routers/dream.py` 按公有名访问子组件；`hasattr` 实证真实 DreamEngine 只有私有名；比对冻结契约 `public/interface_stub/dream.pyi`（DreamEngine 仅声明 config + 4 方法，从未承诺公有子组件）→ 定性为路由越权访问，非契约允许面。
3. 定性 P1：`grep` 证明 `record_material/interaction/activity/info_ingestion` 全仓库零调用，动机退化为纯时间函数（落盘值 1.0/1.0/0.0/0.0 与推算一致）。
4. rules-6 先文后码：`.trae/documents/20260927_模块0_修复梦境接口属性错配.md`（四章 + 附录 A P1 方案）。
5. 实施 P0：路由 6 处 + 三处替身改名 + 新增真实引擎回归用例。
6. 验证：80 / 87 / 769 passed（见下）；并以"修复前该用例 FAILED、修复后 PASS"的对照锁死回归用例有效性。

### (2) 交接状态

- P0 修复：**已闭合**（1 生产文件 + 2 测试文件；含真实引擎回归用例）
- P1 动机接线评估：**已闭合（分析态）**；其实施 **未闭合**（待人类裁决）
- P2 梦境未产出候选：**未闭合**（现象已登记，属配置/触发路径问题，非本次范围）
- 变更文档：**已闭合**（status=已完成，含实际修改/测试结果/经验教训）
- 交付前 GN-004 审查：见下方追加行
- 人类 [V] 交付确认：**未闭合**

### (3) 最终结果

- 验证结论：`pytest tests/test_dream_router.py tests/test_dream_engine.py -q` → **80 passed**；
  加 `test_pagination_clamp.py` → **87 passed**；`-k "dream or autonomy or telemetry or physio"` → **769 passed / 0 failed**（4436 deselected）。
  回归用例有效性：修复前 `TestRealEngineAttributeAlignment` **FAILED**（`AttributeError: 'DreamEngine' object has no attribute 'consolidator'`），修复后 **PASS**。
- 产出物清单：`server/api/routers/dream.py`、`tests/test_dream_router.py`、`tests/test_pagination_clamp.py`、
  `.trae/documents/20260927_模块0_修复梦境接口属性错配.md`、本 note 章节。
- 合规：`public/`（含 `interface_stub/dream.pyi`）与 `.trae/rules/` 零改动；未改 `dream/engine.py`。
- 关键事实（供接续者免于重查）：① 路由改动**需重启后端**才在生产生效；② 同文件并行 Edit 存在写覆盖竞态（本轮 3 处修正被静默回退），同文件多次编辑必须串行且改后 grep 复核；③ 真实 DreamEngine 的子组件是私有属性，路由/handlers/main 三处统一按私有名访问。

### (4) GN-004 交付前审查记录与观察项处置（追加式）

- 结论：**警示放行**（无 [SOFT_BLOCK]），agent `4065124b-f853-45de-b76b-a7b30d8dfe74`。
- **独立核验通过项（GN-004 自跑/读码）**：契约原文确认 DreamEngine 未承诺公有子组件；源码确认私有属性与
  `consolidator.py:49` 的 `memory_manager` 链；全仓 grep 无公有名残留；**临时改回公有名 → 新用例 FAILED，
  恢复后 PASS**（判别力经独立复现）；独立复跑 80 / 87 / 769 三组数字逐项一致；`public/`、`.trae/rules/`、
  `dream/engine.py` 零改动；doc/note 合规。
- **观察项处置**：O1 `related_files` 未改动项 → 已按"修改 / 勘查引用"分类；O2 端点数措辞不一致 → 统一为"五端点"；
  O3 真实引擎用例覆盖不足 → 已扩至 5 端点（含 reject 的 decision/reason 与 session 回滚 `{"purged": 2}` 断言），
  扩后复跑 `test_dream_router.py` **39 passed**、两文件 **80 passed**、相关子集 **769 passed**；
  O4 测试文件头部清单未登记 → 已补 ⑪ 条目。
- **GN-004 声明的未独立验证项**（须人类知悉）：① "修复前 `hasattr` 实证"未落盘为文件；② "第一轮 list 200 /
  confirm 崩"的历史中间态不可回溯复现；③ "需重启后端方生效"属未执行事项。
- **[V] 未闭合**：人类交付确认（GN-004 通过不豁免）；P1 动机接线仍为方案态待裁决。

---

# current-note — remove-autonomy-budget-and-gates（2026-09-30 文件末尾追加；追加式、不覆盖任何既有条目）

> 更新时间: 2026-09-30 16:50 | 变更ID: remove-autonomy-budget-and-gates | 阶段: **实现+验证完成，交付前 GN-004 审查中**

## 七字段交接状态

| 字段 | 内容 |
|------|------|
| 做到哪了 | 用户指令「预算记账 → manager 门控 → killswitch 需要删除（对于这个纯本地项目不需要）」已全链落地：**契约（4 份 public/）→ 在盘 config.json → 后端（引擎/manager/models/safety 删除/config/路由/admin）→ 后端测试 → 前端（预算卡/cost alert/types/i18n/toast）**四批串行完成。前端三重闸门（s0402）**PASSED**；GN-004 首次审查报 `[SOFT_BLOCK]`（引擎侧 `config.py` 残留 `BudgetConfig`）→ 人类裁决"要求修正"→ 已修正并复跑（全量 **5162 passed**、定向 1119 passed），等复审 |
| 为什么 | 纯本地单用户项目，三套管控设施（每轮记账+告警、轮级门控、killswitch）无收益却把"是否行动"的决定权从动机/规划移交给管控层。经 AskUserQuestion 三项裁决（ASK-20260927-02）：① 删除深度＝连组件与死代码一起删（**该选项显式授权修改 `public/`**）；② 前端「启用/禁用/暂停」入口保留、语义改为**任务级启停**；③「用户在线休眠」行为保留、改由**引擎内标志** `_user_online_sleeping` 承载 |
| 未闭合项 | ① ~~人类 [V] 交付确认~~ **已闭合**（ASK-20260927-03，2026-09-30 批准交付）；② 需**重启后端**才在生产生效；③ 登记项：孤儿运行态数据（`killswitch.json`/`token_ledger.json`/`manager_state.json` 预算键）、`docs/` 与 `README.md` 未同步、`status` 枚举保留不可达的 `sleeping`、`toastStore.GlobalToastKind` 单值 union、无 autonomy 专项 E2E（Test2 仅全域冒烟）；④ 本单**同时**完成了前序 P0 单（fix-dream-rest-attr-mismatch）的遗留项处置，两单已一并交付 |
| 接续入口 | 交付确认后重启后端；验证点：`GET /api/autonomy/status` 不再含预算字段且仍通过 `autonomy_state.schema.json`；`POST /api/autonomy/control {"action":"pause"}` 后后台任务真正停止（`engine._task` 取消）而非轮级空转；用户在线的轮次审计 `reason=user_online_sleep`。变更文档：`.trae/documents/20260927_模块0_删除自主预算与门控闸门.md`（第零章= s0601 影响面分析，含回退锚点） |
| 人类裁决记录 | **ASK-20260927-02（三问）= 连组件一起删 + 按钮改任务级启停 + 保留在线休眠改引擎内标志**，已闭合；`public/` 修改授权随该选项一并给出 |
| 请示追踪 | 无悬空请示 |
| 审查状态 | 交付前 GN-004 **首轮**：警示放行 + `[SOFT_BLOCK]`（SB-B 假闭合，agent `13284a30-1cd5-42e8-b06d-5240e420aa80`）——报出引擎侧 `server/autonomy/config.py` 仍留 `BudgetConfig`/`budget`；人类裁决"要求修正"→ 已修正（含 `test_autonomy_skeleton.py` 连带漏改）→ **复审（同 agent）：警示放行、无 `[SOFT_BLOCK]`**，2 项观察项（CHANGELOG 判据未勾选 / note 数字口径）已处置；**[V] 已闭合**（ASK-20260927-03 批准交付） |

## 三段交接

### (1) 工程过程

1. **写前闸门（s0401）**：判定 `public/` 属核心真相源 → **BLOCKED**（人类授权不替代闸门），改走 s0601；`server/`、`tests/`、`APP-Frontend/` 为免检通行区放行。
2. **契约变更适配（s0601）**：产出差异摘要（3 份契约为 MAJOR 字段/接口删除）+ 影响面分级（S1~S10）+ 阻断项（无）+ 同步顺序（契约→后端→测试→前端→锚点）+ 回退锚点。
3. **批 1 契约冻结**：`autonomy_state.schema.json` 删两属性、`autonomy_config.schema.json` 删 `budget` 节、`cxo_autonomy.pyi` 删 `AutonomyBudgetExceededError`、`CHANGELOG [1.14.0]`；**额外发现**：`config.json` 的在盘 `autonomy.budget` 块必须同批删除（`extra="forbid"` 否则服务起不来）。
4. **批 2 后端适配**：引擎删 5 方法 + 3 入参、门控链收敛为「在线休眠→动机→感知/规划/执行」、在线休眠落点改引擎标志；删除 `killswitch.py` + `safety/budget/`；manager/models/config/路由/admin 同步；路由 `control` 改任务级启停。
5. **批 3 测试适配**：删 `test_autonomy_budget_gate.py`；8 份测试文件 + admin 白名单用例同步；被删能力改为**反断言**锁定。
6. **批 4 前端适配 + s0402 三重闸门**：删预算卡/cost alert 全链；闸门证据落盘 `test_reports/frontend_gate_20260930_163635/`（四件齐）。
7. **残留检查**：以**代码形态模式**（而非关键词）复核，捞出并补删 `models.py::AutonomyState` 的两个预算字段。
8. **验证**：后端全量 + 定向、前端 vitest + tsc + E2E + Mock 13 项。

### (2) 交接状态

- 批 1 契约冻结：**已闭合**（4 份 public/ + config.json，语法校验通过）
- 批 2 后端适配：**已闭合**（含 `models.py` 补删）
- 批 3 后端测试适配：**已闭合**（GN-004 首轮时态定向 1120 passed；**修正轮后**定向 1119 passed——少 1 例＝随 `BudgetConfig` 删除而移除的枚举用例）
- 批 4 前端适配 + 三重闸门：**已闭合**（PASSED，证据四件齐）
- 交付前 GN-004 审查：见下方追加行
- 人类 [V] 交付确认：**未闭合**

### (3) 最终结果

- **后端**：全量 `pytest tests -q` → **5162 passed / 0 failed**（228.49s，最终证据 `test_reports/backend_pytest_20260930_final2.txt`；GN-004 首轮时态为 5163，差 1 例＝随 `BudgetConfig` 删除而移除的 `test_invalid_overspend_mode_raises_valueerror`）；定向 `-k "autonomy or admin or config or dream"` → **1119 passed**。
- **前端**：`npx vitest run` → 92 files / **771 passed**；`npx tsc --noEmit` → **EXITCODE=0**；`npx playwright test` → **2 passed**；Mock 回归 **13/13 PASS**。
- **残留引用**：`public/` 与 `server/` 的 `killswitch` / `token_ledger` / 预算字段**代码引用清零**（余下为说明性注释、反断言与运行态历史数据）；**修正轮后** `BudgetConfig` 类名形态亦清零。
- **产出物清单**：4 份 public/ 契约 + `config.json`；后端 **10** 文件（含 2 处删除：`killswitch.py`、`safety/budget/`）；测试 **10** 文件（含 1 份删除 `test_autonomy_budget_gate.py`）；前端 9 文件；变更文档 `.trae/documents/20260927_模块0_删除自主预算与门控闸门.md`；闸门证据目录；后端回归证据 4 份。
- **关键事实（供接续者免于重查）**：① `public/` 三份契约为 **MAJOR 删除**，第三方若依赖需按 `CHANGELOG [1.14.0]` 适配；② 删除类变更必须扫**三层易漏面**：在盘实体配置（`config.json`）、模型层字段（`models.py` / `server/autonomy/config.py` 双份定义）、以及**因漂移而仍然通过的测试断言**（`test_autonomy_skeleton.py`）；③ 启停语义已从「轮级空转」变为「任务级 stop/start」，`manager.status` 仍只写 running/paused。
- **经验教训**：① 契约删除要连带扫在盘配置；② **残留检查必须同时覆盖四类形态**——import / 属性访问 / **类与字段定义** / 测试正向构造（本轮两次漏网分别栽在"关键词被注释淹没"与"未含类名形态"上）；③ 删除能力应改写为反断言锁定，误恢复即红；④ 被删除能力的旧测试若仍通过，**往往意味着生产侧未删干净**，应作为漂移信号反向排查。

---

# current-note — fix-motivation-feedback-and-focus（2026-09-30 文件末尾追加；追加式、不覆盖任何既有条目）

> 更新时间: 2026-10-02 11:20 | 变更ID: fix-motivation-feedback-and-focus | 阶段: **实现 + 验证 + 交付全部闭合（2026-10-02）**

## 七字段交接状态

| 字段 | 内容 |
|------|------|
| 做到哪了 | 用户指令「修复，并且 curiosity 到底是"越高越想探索"才正确（并且应该是针对某个事物的）」→ 后续「先修复 O-19/O-20 翻译不对称」→ 最终「**处理 focus 展示问题，修复语言不对称，然后交付**」**已全部完成并交付（2026-10-02）**：契约 → 模型/管理器 → 动机层 → 规划器 → 引擎 → 测试五批 + **v1~v4 四轮修正**（创作消费配对 → 比例式消费 → 单维正下限 → 四维统一下限 + curiosity/social 比例式）+ **三轮遗留项清理**（4+4 处"预算"陈旧内容、`motivation_min` 护栏、i18n 守卫）+ **交付轮**（前端 focus 展示 + 删 en 孤儿键使两语言键结构完全对称 1350/1350）。后端全量 **5206 passed / 0 failed**；前端三重闸门 **PASSED**（有效证据 `test_reports/frontend_gate_20261002_110021/`：93 文件 / 776 用例 + tsc 0 + E2E 2 + Mock 10/10） |
| 为什么 | 缺陷＝`MotivationState` 的 4 个行为反馈入口**生产零调用**，引擎 `_motivate()` 只调 `tick()` → 动机退化为纯时间函数并饱和（落盘实测 `1.0/1.0/0.0/0.0`）。叠加语义缺陷：规划器只喂裸动机 JSON、从不声明方向 → `curiosity=1.0` 被 LLM 误读为"信息已足够→wait"，与正确语义（**越高越想探索**）相反。再叠加维度缺失：动机只有无指向标量，无法表达"在探索什么" |
| 未闭合项 | **无阻断性未闭合项**（交付已闭合）。**已登记待办（非阻断）**：① 生产生效需**重启后端**后方可观察动机/焦点实况；② **未做真实浏览器人工视觉走查**（focus 区块观感未经人眼确认，闸门 `unclosed_items` 自认，本仓库既有口径）；③ ~~前端 focus 展示~~ **已完成（交付轮）**；④ ~~O-19/O-20 语言不对称与无覆盖~~ **已修复**；⑤ ~~SB-B 四处"预算"陈旧内容~~ **已全清**；⑥ ~~`pyi:80`"预算"措辞~~ **已清且授权已追认**；⑦ 残留（诚实登记）：四维 0 侧全路径不可达、1.0 侧可达但无锁；`motivation_min` 护栏覆盖"下限==上限"矛盾（≤0.99）；每日定时日记路径不计入创作消费；⑧ **N-5**：CHANGELOG [1.15.0] 在多轮中持续刷新（现状态＝已交付）；⑨ **O-13**：curiosity/social 回落语义由固定改比例（ASK-05 授权，登记备查）；⑩ locale 键对称**已完全达成**（例外白名单清空为 `[]`，后续新增不对称会被守卫拦下） |
| 接续入口 | **本单已交付、无待办接续**。如需继续：生产侧 **重启后端** 使动机接线与 focus 语义生效；验证点：`GET /api/autonomy/status` 应含 `focus={topic,level}` 且过 `autonomy_state.schema.json`；Agent 生活页应显示「当前焦点」区块（topic + 兴趣强度 + 进度条，空焦点显示占位）；`motivation_state.json` 四维恒 ≥ 0.02；五个反馈入口见 `autonomy_engine.py:416/418/420/422/424`。回滚：按变更文档 §0.5 按文件隔离，禁整树 `git checkout` |
| 人类裁决记录 | **ASK-20260928-01（三问，已闭合）**：① curiosity 保持标量 + `motivations` 旁新增 `focus={topic,level}`（该选项显式授权改 `autonomy_state.schema.json`）；② 语义落地＝提示词 + **软阈值收敛候选**（非只改提示词）；③ 对象来源＝**LLM 每轮自报**。**ASK-20260930-01（已闭合）**：规划器输出受 `autonomy_action.schema.json`（`additionalProperties:false`）约束而上轮授权只覆盖 state 契约 → 人类选「**授权同批改 action 契约**」。**ASK-20260930-02（已闭合）**：「**修正后交付：消除边界锁风险**」→ v1（创作消费配对）。**ASK-20260930-03（已闭合）**：「**要求修正：消除 0 侧可达**」→ v2（比例式消费）。**ASK-20260930-04（已闭合）**：「**要求修正：彻底消除全部 0 路径**」→ v3（`creative_min` 正下限 + ratio 上界 0.99）。**ASK-20260930-05（已闭合）**：口径确认题中人类选「**要求修正：扩展到其他三维**」→ v4（四维统一 `motivation_min` + curiosity/social 改比例式）。**N-5（CHANGELOG 属 public/ 刷新）人类尚未单独裁定**，已登记为交付前知悉项。**ASK-20260930-06（已闭合）**：人类选「**暂停并搁置**」→ 本单不交付，工作树保持现状（产出物全部在盘）。**ASK-20260930-07（已闭合）**：人类选「**解除搁置，先清遗留项**」（未交付、先清登记项）→ 清理轮：`public/interface_stub/cxo_autonomy.pyi:80` docstring"预算"→"焦点"（**该项为人类对该单文件单行的显式授权**，经 s0401 BLOCKED → s0601 判定 PATCH 级零影响）+ `main.py:92`/`main.py:238`/`docs/CXFC开发文档.md:130` 镜像措辞 + `motivation_min` 护栏（≤0.99）；**前端项（`focus` 展示 + `AutonomyPage.tsx:72` 注释）仍待人类裁决**。**ASK-20260930-08（已闭合，两问）**：① SB-B 处置＝「**四处全清（含前端闸门）**」→ 清理轮 v2：`docs/technical.md` §20.3 整节改写（删除指向已删 `safety/budget/token_ledger.py` 的描述）+ `technical.md:943` 去"日预算用量" + `features.html` 两处预算表述 + `zh-CN.json:633` 副标题"预算"→"焦点"；前端三重闸门 **PASSED**（证据 `test_reports/frontend_gate_20261001_131252/`）；② **授权追认**＝「追认：该选项即授权」→ ASK-07 对 `pyi:80` 的 public/ 修改**授权闭合**（GN-004 第七轮裁定①的程序歧义消解）。**人类指令（对应清理轮 v3）**：「先修复 O-19 和 O-20 的翻译不对称问题」→ en-US 副标题补 `focus` 与 zh 对齐 + 新增 `src/i18n/i18n.test.ts` 3 条守卫（键结构对称 / 副标题两语言声明焦点 / 无预算残留）；前端三重闸门重跑 **PASSED**（证据 `test_reports/frontend_gate_20261001_152258/`，含判别力实验）。**人类指令（交付轮，对应 ASK-20261002-01）**：「**处理 focus 展示问题，修复语言不对称，然后交付**」→ ① focus 展示落地（`AutonomyPage` 新增「当前焦点」区块 + `types.ts` 加 `AutonomyFocus` + zh/en 各 3 词条）② 删除 en 孤儿键 `audioPanel.clientsOnline` 并把 `KNOWN_EN_ONLY_KEYS` 清空（两语言键结构 **1350/1350 完全对称**）③ **交付闭合**（CHANGELOG [1.15.0] 注记改为"已交付 2026-10-02"、note 与变更文档 §5.10 同步、变更文档 status→已关闭）；有效闸门证据 `test_reports/frontend_gate_20261002_110021/`。**ASK-20261002-02（已闭合）**：交付闭包中自查发现 `public/schema/CHANGELOG.md` [1.15.0] §影响范围"前端不改（已知未闭合项）"与同条目末尾"已交付（含前端 focus 展示）"并存冲突（即 O-25 要求避免的"已交付／未交付并存"）→ 该文件属 `public/` 受保护路径（rules-0 §四-10），**拉起 AskUserQuestion 请求授权** → 人类选「**授权修正**」→ 已把该行改写为「前端同步（原计划不改，后经交付轮落地并闭合）」，保留历史说明与授权出处 |
| 请示追踪 | ASK-20260928-01 / ASK-20260930-01 ~ -08 / ASK-20261002-01（交付指令）/ **ASK-20261002-02（CHANGELOG 第 25 行修正授权，已闭合）** **均已闭合**；**无悬空请示、无待裁决项**（原"前端是否展示 focus"已在交付轮由人类指令直接闭合；交付闭包中发现的 `public/schema/CHANGELOG.md` [1.15.0] §影响范围"前端不改"与交付注记并存冲突，已获人类显式授权修正并落地） |
| 审查状态 | **首轮** GN-004（agent `613f87b7-d688-4a81-a05a-bed779d0c9aa`）= 警示放行（无 `[SOFT_BLOCK]`），独立复现定向 1151 / 全量 5194 并做两处破坏性判别力实验；4 项观察 + 1 项锚点表述不实**已逐项处置**（O-1 `AutonomyAction` 补 `focus` + 前移 `AutonomyFocus` 定义 / O-2 登记不改 / O-3 note 补"终态处理" / O-4 顺序笔误统一 / E7 回退锚点改写为按文件隔离）。**第二轮复审（同 agent）**= 警示放行（无 `[SOFT_BLOCK]`），实测全量 5195 / 定向 1152，O-1/O-3/O-4/E7 真闭合、O-2 判为"经授权的合规延后"；N-1/N-2 已回填。**第三轮复审（同 agent，核验修正轮）**= 警示放行（无 `[SOFT_BLOCK]`），实测全量 **5200** / 定向 **1157**，破坏性实验（移除消费分派或 `creative_consume_drop=0` → 4 failed）证实判别力；判定「核心目标达成（单向 1.0 结构锁已真消除）」；新观察 N-3（行号）/N-4（范围表述 + creative_drive 0 侧补登）/N-5（CHANGELOG 属 public/ 的表述）**均已回填修正**。**三轮均无阻断**。**第四轮复审（同 agent，核验 v2 比例式消费）**= 警示放行（无 `[SOFT_BLOCK]`），实测全量 **5202** / 定向 **1159**，独立复算交替稳态 0.10 > 0（自 0.5 与 1.0 各 200 轮均收敛），破坏实验（改回固定扣减 → 6 failed）证实判别力；判定「v2 定义范围内达成消除 0 侧可达」；新观察 O-5（行号指代，已修正）/O-6（ratio 端点 1.0 等价清空，默认 0.5 **生产不可达**，护栏登记为后续单）/**O-7（严格剩余 0 路径＝既有时间衰减，严重性 LOW，非消费所致）**。**四轮均无阻断**。**第五轮复审（同 agent，核验 v3 正下限 + ratio 上界）**= 警示放行，实测全量 **5205** / 定向 **1162**；独立随机穷举（`creative_min`/初值/ratio 全端点 × 300 操作）**0 违规**；破坏实验（`_clamp_creative` 改回 `_clamp` → 6 failed）证实判别力；新观察 O-8（note 三段交接滞后，已修正）/O-9（"全部 0 路径"口径须人类确认）/O-10（`creative_min=1.0` 极端注入）/O-11（`tick` docstring，已修正）。**第六轮复审（同 agent，核验 v4 四维统一下限）**= 警示放行，实测全量 **5205** / 定向 **1162**；独立随机穷举（`motivation_min`/初值/三 ratio 端点，1008 组合 × 200 操作）**0 违规**；破坏实验（`_clamp_motivation` 改回 `_clamp` → 9 failed）证实判别力；判定「字面'全部 0 路径'（四维）已闭合，无未闭合 0 侧边界锁」；新观察 O-12（note 与 §4.3 锚点滞后，已修正）/O-13（语义变更范围，已登记供知悉）/O-14（§5.5.3 "1.0 侧"措辞，已修正）/O-15（测试 docstring 旧名，已修正）。**六轮均无阻断**。**第七轮复审（同 agent，核验清理轮 v1）**= **警示放行 + `[SOFT_BLOCK] SB-B`（假闭合证据）**：实测全量 **5206** / 定向 **1163**；破坏实验（`motivation_min` 收拢改回 `min(1.0,…)` → 新用例 FAILED）证实判别力；**驳回**我"全仓'预算'遗留仅剩前端一处"的穷尽性声明（反证：`technical.md`×2、`features.html`×2、`zh-CN.json`）→ 已按人类 ASK-08 于清理轮 v2 **四处全清**并经前端三重闸门 PASSED；同轮裁定 public/ 授权实质成立但建议人类追认 → **人类已追认（ASK-08 ②）→ 授权闭合**；另报 O-16（章节物理顺序）/O-17（CHANGELOG 与 note 数字滞后）/O-18（note 时间戳未更新）——**均已在本轮回填修正**。**第八轮复审（同 agent，核验清理轮 v2 + 闸门）**= **警示放行（无 `[SOFT_BLOCK]`；上轮 SB-B 已消解）**：GN-004 独立复跑后端全量 **5206 passed**、前端 `tsc --noEmit` **EXIT=0**、AutonomyPage 用例 **8 passed**，并独立枚举全仓 37 个"预算"命中逐类复核，确认**除有意保留的 `AutonomyPage.tsx:72` 外无"把已删预算描述为现存"的遗漏**；三问裁定＝① public/ 授权链条**已闭合**（人类追认生效）② 清理轮 v2 **满足**"四处全清"③ 交付态表述**一致保持未交付/挂起**；新观察 **O-19**（zh 副标题含"焦点"而 en 未含，属**既有**翻译不对称）/ **O-20**（该文案无自动化覆盖）——均登记为低severity后续候选；**两观察已按人类指令于清理轮 v3 修复**（en 补 focus + 新增 `i18n.test.ts` 守卫，判别力实验证明改回即红）。**第九轮复审（同 agent，核验清理轮 v3）**= **警示放行（无 `[SOFT_BLOCK]`）**：GN-004 独立复跑前端 `tsc --noEmit` **EXIT=0**、`vitest run` **93 文件 / 774 passed**、`i18n.test.ts` **3 passed**；**O-19/O-20 判定为真闭合**（自建三类破坏点：en 去 focus / 注入新 en-only 键 / 往 zh 注入"预算"词条 → 三条守卫逐条转红 3 failed，复原后 3 passed）；并裁定 `KNOWN_EN_ONLY_KEYS` 白名单**不属掩盖问题**（`toEqual` 精确等值断言，注入新键即红）；交付态一致保持"未交付/挂起"。新观察 **O-21**（note 抬头时间戳/"两轮"滞后）/**O-22**（§5.10 快照值 5205 与"后续"仅提 §6.1）——**均已回填修正**。**第十轮复审（同 agent，＝交付前审查）**= **警示放行（无 `[SOFT_BLOCK]`）＋判定"可交付、无阻断"**：独立复跑后端 **5206 passed**、前端 `tsc` **EXIT=0** / `vitest run` **93 文件 / 776 passed** / `i18n.test.ts` **3 passed** / `AutonomyPage.test.tsx` **10 passed**；独立复算语言对称 = **zh 1350 / en 1350（两侧差集均空）**；**三路破坏实验**（`focusTopic=''` / 改坏 zh `focusLevel` 词条 / 往 en 注入新键）→ 焦点用例与 i18n 守卫分别转红（隔离验证表明焦点断言不弱），复原后 13 passed；裁定"删除孤儿键更合适、不升级"；新观察 **O-23**（§6.5 曾引用不存在的 §8）/ **O-24**（§5.10 与 §6.x 顺序）/ **O-25**（交付态锚点待回填）——**三项均已在交付闭包中处理**（改引 §5.10、补阅读顺序说明并重排 §6.5/§6.6、回填交付态）；交付闭包自查另发现 `CHANGELOG.md` §影响范围第 25 行"前端不改（已知未闭合项）"与同条目"已交付（含前端 focus 展示）"并存（同属 O-25 类），已获人类授权（**ASK-20261002-02**）修正并落地。 |

## 三段交接

### (1) 工程过程

1. **写前闸门（s0401）**：判定 `public/schema/**` 属核心真相源 → **BLOCKED**（人类授权不替代闸门），改走 s0601；`server/autonomy/**` 与 `tests/**` 属免检通行区放行；`.trae/documents/**` 属工程交接锚点（格式校验后放行）。
2. **契约变更适配（s0601）**：产出差异摘要（2 份 MINOR 纯新增 + audit 契约零改动）+ 影响面分级（必须同步 6 项 / 可延后 1 项＝前端 / 需重审 1 项＝审计面隔离）+ 阻断项（无）+ 同步顺序 + 回退锚点；遇"focus 由哪条契约承载"的真实分叉 → **L3 AskUserQuestion（ASK-20260930-01）**，人类授权同批改 action 契约。
3. **先文后码（rules-6）**：先写 `.trae/documents/20260930_模块0_修复动机接线与焦点语义.md`（第零章 s0601 影响面 + 四章模板），再动代码。
4. **批 1 契约**：`autonomy_state.schema.json` 顶层新增 `focus`、`autonomy_action.schema.json` 新增可选 `focus`、`CHANGELOG [1.15.0]`。
5. **批 2 后端基座**：`models.py` 新增 `AutonomyFocus` + `AutonomyState.focus`；`manager.py` 新增 `focus` 属性与 `get_status()["focus"]`；`core/motivation/state.py` 新增 `focus_topic/focus_level`、`set_focus()`、`to_focus_dict()`、`_persist_dict()`（`to_dict()` 保持四标量，审计面不受污染）。
6. **批 3 规划器**：system prompt 增动机方向语义段 + focus 自报要求；新增 `_build_candidates()` 软阈值候选（>=0.6）并注入 user 消息；`_validate_action` 增 `_normalize_focus` 透传（缺失/非法则省略键）。
7. **批 4 引擎**：`_plan()` 上下文注入 `focus`；`_run_round` 执行后新增 `_apply_motivation_feedback()`（只认 `result=="success"`）与 `_apply_plan_focus()`；动机落盘从 `_motivate()` 移到轮末统一（`_save_motivation()`），保证反馈/焦点不因重启丢一轮；新增 `_focus_dict()` / `_sync_manager_focus()`。
8. **批 5 测试**：首轮新增 33 例（契约 7 / 动机 6 / 规划器 10 / 引擎 10）；修正轮 v1 再 +5、v2 再 +2（动机 `TestCreationConsume` 由 3 例扩为 5 例），合计 **+40 例**。
9. **验证**：契约 `json.load` ×2、`py_compile` ×5、残留 grep；回归最终值见 (3)（中间态 1151/5194 → 1152/5195 → 1157/5200 → **1159/5202**）。
10. **交付前 GN-004（首轮）**：警示放行，无 `[SOFT_BLOCK]`；4 观察 + 1 锚点表述不实 → 已逐项处置（含 `models.py::AutonomyAction` 补 `focus` 以消除声明级漂移、0.5 节回退锚点改写为"按文件隔离"、note 补"终态处理"）；处置后复跑全量并拉起**复审**。
11. **GN-004 复审（同 agent）**：警示放行（无 `[SOFT_BLOCK]`），实测全量 5195 / 定向 1152；O-1/O-3/O-4/E7 真闭合、O-2 判为"经授权的合规延后"；新增 N-1/N-2（数字与步骤滞后）已回填。**审查不豁免人类裁决** → 拉起 [V] 交付确认选择题。
12. **[V] 裁决（ASK-20260930-02）**：人类选「**修正后交付：消除边界锁风险**」→ 追加**修正轮 v1**：动机层新增 `record_creation()`（固定扣减 −0.30）+ 引擎 `write_memory`/`write_diary` 成功分派 + 配对测试；契约面零变更（schema）。复跑全绿并拉起 **GN-004 第三轮复审** → 警示放行；其 N-3/N-4/N-5 已回填（N-4 指出 v1 把边界锁从 1.0 侧搬到了 0 侧）。
13. **[V] 裁决（ASK-20260930-03）**：人类选「**要求修正：消除 0 侧可达**」→ 追加**修正轮 v2**：`creative_consume_drop: 0.30`（固定扣减）→ `creative_consume_ratio: 0.5`（**比例式**），`record_creation` 改为 `creative_drive *= (1−ratio)`；测试扩为 5 例。复跑全绿并拉起 **GN-004 第四轮复审** → 警示放行；其 O-5（行号指代）已修正，O-6/O-7 登记。
14. **[V] 裁决（ASK-20260930-04）**：人类选「**要求修正：彻底消除全部 0 路径**」→ 追加**修正轮 v3**：新增 `creative_min=0.02` 正下限（`_clamp_creative` 覆盖构造/load/tick/素材/消费五路径）+ `_MAX_CONSUME_RATIO=0.99` + `TestCreativeNonZeroFloor` 3 例；复跑全绿并拉 **GN-004 第五轮复审** → 警示放行；其 O-8/O-11 已修正，O-9（口径）提请人类裁决。
15. **[V] 裁决（ASK-20260930-05）**：口径题中人类选「**要求修正：扩展到其他三维**」→ 追加**修正轮 v4**：`creative_min` → **`motivation_min`（四维统一 0.02）**、`_clamp_creative` → `_clamp_motivation`（覆盖四维全路径）、curiosity/social 的行为扣减由固定 −0.30 改**比例式**（`info_ingestion_ratio` / `social_interaction_ratio` = 0.30，`_MAX_RATIO=0.99`）、测试改名扩维；复跑全绿并拉 **GN-004 第六轮复审** → 警示放行（1008 组合 × 200 操作穷举 0 违规）；其 O-12/O-14/O-15 已修正，O-13（语义变更范围）登记供知悉。
16. **[V] 最终裁决（ASK-20260930-06）= 暂停并搁置** → **本单不交付**；锚点回填为"实现+验证闭合、交付阻塞"态，产出物全部留在工作树。
17. **遗留项清理轮 v1（ASK-20260930-07 = 解除搁置，先清遗留项）**：过 s0401 写前闸门（`public/interface_stub/**` → BLOCKED）→ 走 s0601（PATCH 级、无必须阻断/同步项、全仓 grep 确认无下游按该 docstring 断言）→ 落地 4 处"预算"遗留措辞修正（pyi:80 / main.py:92 / main.py:238 / docs:CXFC开发文档.md:130）+ `motivation_min` 护栏（收拢 ≤0.99）+ 1 例护栏测试；**前端项未做**，登记为待裁决项。
18. **遗留项清理轮 v2（ASK-20260930-08 = 四处全清（含前端闸门）+ 授权追认）**：GN-004 第七轮 `[SOFT_BLOCK] SB-B` 驳回了 v1 的"仅剩一处"穷尽声明 → 人类裁定四处全清：`docs/technical.md` §20.3 整节改写（删去把已删 `safety/budget/token_ledger.py` 描述为现存设施的内容）+ `:943` 去"日预算用量" + `features.html` 两处 + `zh-CN.json:633` 副标题；i18n 属前端可见文案 → 走 **s0402 三重闸门**（Test1 vitest 92 文件/771 用例 + tsc EXIT=0；Test2 playwright 2 passed；Test3 Mock 7/7）→ **PASSED**，证据落 `.trae/documents/test_reports/frontend_gate_20261001_131252/`（四件齐备）；同轮人类**追认** public/ 授权 → ASK-07 的 pyi 修改授权闭合。

19. **遗留项清理轮 v3（人类指令「先修复 O-19 和 O-20 的翻译不对称问题」）**：`en-US.json:633` 副标题补 `focus` 与 zh 对齐（O-19）；新增 `APP-Frontend/src/i18n/i18n.test.ts` 3 条守卫断言（键结构对称 / 副标题两语言声明焦点 / 无预算残留），把原先仅靠人工 checklist 的校验变为可执行（O-20）；前端三重闸门重跑 → **PASSED**，新证据目录 `test_reports/frontend_gate_20261001_152258/`（四件齐备 + 判别力实验 `discrimination_experiment.txt`：改回即红）；**上一轮证据 `…131252` 已声明失效（仅作历史留痕）**。

20. **交付轮（人类指令 ASK-20261002-01：「处理 focus 展示问题，修复语言不对称，然后交付」）**：① focus 展示落地（`AutonomyPage` 新增「当前焦点」区块 + `types.ts` 加 `AutonomyFocus{topic,level}`/`focus?` + zh/en 各 3 词条 + 2 例测试；顺带修正 AutonomyPage.tsx:72 陈旧注释）；② 语言不对称修复（删 en 孤儿键 `audioPanel.clientsOnline`、`KNOWN_EN_ONLY_KEYS` 清空 → zh/en 各 1350 键完全对称）；③ 前端三重闸门重跑 **PASSED**（新证据 `frontend_gate_20261002_110021`，四件齐备）＋后端交付回归 **5206 passed**；④ GN-004 第十轮＝交付前审查 → 警示放行、判定"可交付、无阻断"；⑤ **交付闭合**：CHANGELOG [1.15.0] 交付注记 → 已交付（2026-10-02）、变更文档 §5.10 改写为交付记录并新增 §6.5/§6.7、变更文档 status → 已关闭、note 抬头/七字段/三段交接同步；⑥ **交付闭包自查**：发现 `CHANGELOG.md` §影响范围"前端不改（已知未闭合项）"与同条目"已交付（含前端 focus 展示）"并存（即 O-25 类冲突）→ 该文件属 `public/` 保护路径，**拉起 AskUserQuestion 请授权** → 人类选「授权修正」（ASK-20261002-02）→ 已改写为「前端同步（原计划不改，后经交付轮落地并闭合）」。

### (2) 交接状态

- 批 1 契约：**已闭合**（2 份 schema + CHANGELOG；`json.load` 通过）
- 批 2 后端基座：**已闭合**（models/manager/motivation state；含 O-1 修正的 `AutonomyAction.focus` + `AutonomyFocus` 定义前移）
- 批 3 规划器：**已闭合**（提示词语义 + 软候选 + focus 透传）
- 批 4 引擎：**已闭合**（反馈接线 + 焦点回写 + 轮末统一落盘）
- 批 5 测试 + 回归：**已闭合**（后端累计新增用例 **+44**；后端全量 **5206 passed / 0 failed**）
- 修正轮 v1~v4：**已闭合**（详见 §5.5.x 与第三~六轮复审）
- 遗留项清理轮 v1/v2/v3：**均已闭合**（措辞 4+4 处 + `motivation_min` 护栏 + 授权追认 + O-19/O-20 修复与 i18n 守卫）
- **交付轮（focus 展示 + 语言对称）**：**已闭合**
- 交付前 GN-004 审查：**十轮全部闭合**（第七轮含 `[SOFT_BLOCK] SB-B`，已消解；第十轮＝交付前审查，判定可交付）
- 前端三重闸门（s0402）：**已闭合 / PASSED**（有效证据＝`frontend_gate_20261002_110021`：93 文件 / 776 用例 + tsc 0 + E2E 2 + Mock 10/10）
- 人类 [V] 交付确认：**已闭合 —— 2026-10-02 交付完成**

### (3) 最终结果

- **后端（最终，清理轮 v1 后·v2 未改后端）**：全量 `python -m pytest tests -q` → **5206 passed / 0 failed**（248.56s；上一单基线 5162，**+44 恰为本单新增用例数**＝契约 7 + 动机 15 + 规划器 10 + 引擎 12）；定向 `-k "autonomy or planner or admin or config or dream"` → **1163 passed / 0 failed**（43.35s；基线 1119）。编译与契约语法校验（含 pyi AST）均通过。（清理轮 v2 仅改 docs/ + i18n 文案，不在后端测试范围，故未重跑）
- **前端（有效证据＝交付轮闸门 `frontend_gate_20261002_110021`）**：`npx vitest run` → **93 文件 / 776 passed**（较清理轮 v3 +2 用例＝`AutonomyPage` 焦点展示 2 例）；`npx tsc --noEmit` → **EXIT=0**；`npx playwright test` → **2 passed**；Test3 Mock 回归 **10/10**。证据目录四件齐备（`test1_streamlit.log` / `test2_playwright.log` / `test3_mock_checklist.md` / `summary.json`）+ `tsc.txt` + `vitest_autonomy_page.txt`。**上一轮 `frontend_gate_20261001_152258`（93 文件 / 774 用例，清理轮 v3）已因焦点展示 + 语言对称改动失效，仅作历史留痕。**
- **残留复核**：`record_info_ingestion/interaction/activity/material` + `record_creation` 在 `server/` 的生产调用点＝`autonomy_engine.py:416/418/420/422/424`（**修复前四入口为零调用**；行号经 GN-004 N-3 更正）；`focus` 全仓检索无遗留冲突（其余命中为视觉 focus_mode、CSS `:focus`、`focusSpeed` 等无关项）。
- **关键事实（供接续者免于重查）**：① `focus` 落在 **state 契约顶层**（非 `motivations` 内部）——`test_autonomy_skeleton.py` 断言 `st["motivations"] == {四标量}` 且审计面 `additionalProperties:false`，放内部会双重违约；② 规划器输出必须合 `autonomy_action.schema.json`（`additionalProperties:false`），故 focus 必须进 action 契约，不能"借道 payload"；③ `record_material` **刻意改绑"探索行动取回非空内容"** 而非"感知层非空"（附录 A 原案）——后者几乎每轮成立而 creative_drive 每小时只衰减 0.02，等价于把创意欲钉在 1.0，正是本单要修的同一类"退化为常量"缺陷。
- **产出物清单**：契约 3 份（2 schema + CHANGELOG）；后端 6 文件（models/manager/motivation state/planner/engine/`__init__`）；后端测试 4 文件；文档 2 份（technical.md / features.html）+ CXFC开发文档.md 措辞；前端 5 文件（`zh-CN.json` / `en-US.json` / **新增 `i18n.test.ts`** / `types.ts` / `AutonomyPage.tsx` + `AutonomyPage.test.tsx`）；前端闸门证据（有效＝`frontend_gate_20261002_110021`）；变更文档 `.trae/documents/20260930_模块0_修复动机接线与焦点语义.md`；本 note 章节。
- **经验教训**：① 修"退化为常量"类缺陷时，**任何"每轮必然成立"的判据都不能直接当反馈触发源**（会把另一个维度钉死）——触发源必须绑定真实行为；② 状态类字段只有"有指向"才有意义：标量 + 焦点对象（topic/level）分离，避免把方向信息塞进标量语义里；③ 裸数值喂 LLM 必然被误读，**方向语义必须写进提示词**（否则反馈回路闭合了，规划侧仍会自我锁死）；④ **每个维度都必须有"升侧 + 降侧"配对**——`creative_drive` 原只有升侧（素材 +0.10）与 0.02/h 弱衰减，等价于把该维度钉在 1.0（GN-004 Q5 实测：6 轮只读即到 1.0，需 50h 才回落）；⑤ **降侧必须比例式，且"无自愈维度"须设正下限**——v1 的固定扣减（−0.30）在不对称下把边界锁从 1.0 侧搬到 0 侧；v2 改 `× (1−ratio)` 后交替收敛到正不动点，但**仍无法拦住"初始值恰为 0"**（旧盘饱和态即 0）与固定扣减的时间衰减 → v3 用 `creative_min=0.02` 正下限把构造/load/tick/素材/消费五路径一次性闭合；**v4 进一步把下限推广到四维（`motivation_min`）、并把 curiosity/social 的行为扣减也改比例式**，GN-004 六轮复审以 1008 组合 × 200 操作随机穷举验证四维 0 违规。**经验：边界锁与"自愈"无关——凡"贴死边界后该维度不再提供信号"都属锁；四维统一非零下限 + 比例式回落是最小自洽解。**

### 终态处理（rules-5 §3.2）

- **当前状态**：本 note 章节为**活跃交接锚点**，交付态＝**已交付（2026-10-02）**（ASK-20260930-06「暂停并搁置」已于本日解除并经人类 [V] 裁决批准交付；实现 + 验证 + 交付全部闭合）。产出物全部在盘，可吸收 / 归档。
- **吸收去向**：交付已完成，无需回滚；本单产出物（契约 / 后端 / 前端 / 测试 / 闸门证据）永久留存。变更留痕与 GN-004 十轮审查记录归 `.trae/documents/20260930_模块0_修复动机接线与焦点语义.md`（status 已关闭）。若未来需回滚，按文件隔离执行（详见变更文档 §0.5：禁止整树 `git checkout`，会连带丢失上一单未提交成果）。
- **登记不改项（后续单候选）**：① ~~O-2 `pyi:80`"预算"措辞~~ **已清（清理轮 v1）且人类已追认授权**；② `motivation_min` 极端注入护栏**已加**（≤0.99），更低值仍属"语义异常但定义明确"；③ ~~前端 `focus` 是否在管理页展示~~ **已落地（交付轮：`AutonomyPage.tsx` 焦点区块 + 2 例测试 + s0402 闸门 PASSED）**；④ curiosity/social 回落幅度由固定改比例属**既有默认语义变更**（ASK-05 选项授权，登记备查）；⑤ ~~O-6 / O-7 / O-9 / O-19 / O-20~~ **均已消除**（v3/v4 解决 0 路径；清理轮 v3 修复语言不对称并补守卫测试）；⑥ ~~`management.audioPanel.clientsOnline` 仅 en-US 有~~ **已清（交付轮：删除 en 孤儿键 + 清空守卫例外白名单 → zh 1350 / en 1350 完全对称）**。
- **删除条件**：已交付闭合，本 note 章节可吸收或归档（保留历史留痕即可）。
