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
