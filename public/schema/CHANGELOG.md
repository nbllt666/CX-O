# 契约变更日志 (CHANGELOG)

> 遵循 AC 范式 v6 rules-3 §六 契约版本化规则。所有契约变更必须记录版本号、变更内容、变更原因、影响范围。

## [1.8.0] - 2026-08-29

### 变更内容

- **接口契约变更（MAJOR）**：`interface_stub/speech_orchestrator.pyi` v2.0.0 整份重写——原 `SpeechOrchestrator` 全库无实现（幽灵契约），删除并以 `server/services/tts_service.py` 的 `TTSService` 实际公开面重建契约（synthesize/synthesize_stream/synthesize_stream_fine/synthesize_with_emotions/synthesize_stream_with_emotions/split_text_streaming/get_voices/health_check/initialize/shutdown + `TTSServiceUnavailableError`；打断职能在语音管线会话层，非编排面）。配套：`tests/test_contracts_qwen3_tts.py::test_orchestrator_stub` 断言随改，全绿。
- **接口契约变更（MINOR）**：`interface_stub/ref_audio_store.pyi` v1.1.0 补齐 per-agent 绑定/快照/集群 emit hook 整层 13 个签名（set_for_agent/get_for_agent/clear_for_agent/list_bindings/asset_used_by_any_agent/set_emit_hook/build_snapshot/restore_snapshot/build_bindings/set_prompt_generator/get_audio_path + `AssetBoundError`/`GeneratedAudio`），`register_from_prompt` 补 async 标注。纯新增，不阻断既有下游。
- **接口契约变更（MAJOR）**：`interface_stub/multimodal_pipeline.pyi` v2.0.0 删除 3 个幽灵方法 `_ocr_worker/_vision_worker/_merge_ocr_vision`（实现中已内联下沉至 `workers.ImageWorker`），补 `__init__` 公开签名。无调用方可依赖（方法不存在于实现），等效无破坏。
- **接口契约变更（MINOR）**：`interface_stub/emotion_instruction_service.pyi` v1.1.0——`EmotionInstruction` 补 `raw/speed/volume` 字段，`generate_instruction` 补 async，新增 `strip_instruction/set_instruction_generator/get_supported_legacy_markers/validate_explicit_instruction` 超集函数。纯新增，不阻断。
- **接口契约变更（PATCH）**：`interface_stub/cx_cluster.pyi` v1.0.1——`confirm_dead` 补 async、`emit` 返回 `int`、`StateReplicator.sync_status` 返回 `Dict[str, Any]`。签名撒谎修正（实现自始如此），无存量调用方按旧存根调用。
- **接口契约变更（PATCH）**：`interface_stub/cx_admin.pyi` v1.0.1——`AdminBatchExecutor.execute` 补 async 与 `stop_on_error=True` 默认值、`AdminControlPlane.dispatch` 默认参数对齐。同上，不阻断。
- **接口契约变更（PATCH）**：`interface_stub/memory_manager_v2.pyi` v1.0.1——`get_rejected_content` 签名对齐实现（`session_id` 必填、`limit` 默认 50、空 session_id 抛 `KeyError`）。按字面属必填性反转（MAJOR），因实现自始必填、零存量调用方依赖旧可选形态，参照 v1.7.0 先例降级 PATCH 记账；配套 `pre_generated_mock/mock_memory_manager_v2.py` v1.2.0 签名同步。
- **配置契约变更（MINOR）**：`config_template/cluster_config.schema.json` 的 `sync_units` 补齐 `ref_audio` 备份单元（enum 与 default 同步为 `["memory", "persona", "config", "session", "ref_audio"]`，对齐 `server/config.py` ClusterConfig 默认值与 `server/core/cluster/units.py` UNIT_REGISTRY）。
- **配置契约变更（PATCH）**：`config_template/computer_control_config.schema.json` 三默认值对齐 Electron 插件实现：`host` `"0.0.0.0"`→`"127.0.0.1"`、`port` `18443`→`8443`（对齐 `APP-Frontend/electron/plugins/computerControl/index.ts`）、`backend_url` `https`→`http`（对齐 `electron/main.ts`）；properties 层与顶层 default 两处同步，字段名与 required 集合未变。
- **配置契约变更（MINOR）**：`config_template/radix_config.json` 契约面补齐实现既有字段——`distillation_service` 补 `quality_llm_enabled/quality_llm_model/quality_llm_timeout_seconds`（对齐 DistillationConfig）、`multimodal_pipeline` 补 `vision_base_url/vision_model/vision_timeout_seconds`（对齐 MultimodalPipelineConfig）；新增字段均带默认值，auto_fill 行为不变。
- **接口契约变更（注释级）**：`interface_stub/distillation_service.pyi` 头部补真实路由核对注释（`/api/v1/distillation/*` + 批量切分 5 端点），注明种子阶段契约；签名未动。

### 变更原因

- 第十一轮质量修复 G4 批次（契约对齐实现，实现为源真理）：11 份契约与实现存在漂移（幽灵类/幽灵方法、缺层、签名撒谎、默认值漂移、契约面窄于实现），经 3 路独立交叉验证确认后，获人类显式授权修订。
- G4-A（schema/config 3 文件）与 G4-B（pyi 6 份修订 + mock 同步 + 测试同步）并行执行，定向测试 97 passed + 125 passed 全绿。

### 影响范围

- speech_orchestrator.pyi 与 multimodal_pipeline.pyi 为 MAJOR（幽灵契约修正），但被删声明在全库零实现零调用方，等效无破坏；memory_manager_v2.pyi 必填性反转已按 v1.7.0 先例降级记账。
- computer_control 三默认值修正影响 auto_fill 产物：新装环境 host 收敛为 127.0.0.1、端口 8443、后端 http——与插件实际监听行为一致；已落盘旧配置不受影响。
- 下游登记（未改动，待后续批次）：①`schema/cluster_backup_unit.schema.json` 的 `unit` 枚举缺 `ref_audio`（8 单元缺 1，数据契约侧同类缺口）；②`memory_manager_v2.pyi` 的 `write_with_decision` 存根与 `decision_mixin.py` 实现存在返回类型/参数漂移；③agents.pyi/chat.pyi 尚有真实端点未覆盖（default/ref-audio 绑定端点、summary-agent 流式端点），属 s0201 补全范围。

### 闭合判据

- [x] 11 份契约实体修订并通过 JSON/ast 语法校验
- [x] 定向测试全绿（test_contracts_computer_control + test_config + test_cluster_ref_audio：97 passed；test_contracts_qwen3_tts + test_narrative_memory + test_memory_mixins + test_ref_audio_assets_router：125 passed）
- [x] CHANGELOG v1.8.0 记录本条目（本文件）

## [1.7.0] - 2026-08-27

### 变更内容

- **数据契约变更（MINOR）**：`schema/memory.schema.json` 从空壳占位补全为完整 draft-07 契约（对齐 `async_manager.py` memories 表建表 L40-L91 与 `write_memory` L126-L176 签名）
  - 新增 17 个字段定义：id/content/memory_type(enum)/importance(1-5)/tags/metadata/permanent/emotion_score/workspace_id/agent_id/vector_id/created_at/updated_at/accessed_at/access_count/decay_score/is_deleted
  - required 按 memories 表 NOT NULL 列集划定；tags/metadata/vector_id 为可空列不入 required
  - `definitions.permanent_memory_record` 登记永久记忆表行结构（source=user|vision、verified）
  - 头部加 `@version` 注释（2.0.0），description 声明源真理与前后端字段映射（前端 type ↔ memory_type）
- **数据契约变更（MINOR）**：`schema/agent_config_v2.schema.json` 修正幽灵契约使与现实一致（对齐 `data/agents.json` 种子结构 + `routers/agents.py` AgentConfig 模型 L66-L86）
  - 必填反转收缩：`[agent_id, name, tools_config, decision_rubric, distillation_enabled]` → `[id, name]`
  - 键修正：`agent_id` → `id`（真实落盘键名）；RADIX 扩展段（tools_config/decision_rubric/distillation_enabled/legacy_parser_enabled）降级为可选
  - 新增现实字段：description/system_prompt/model/temperature/max_tokens/use_memory/use_tools/memory_scene/decay_model/vision_enabled/is_default/created_at/updated_at + 读透传字段 ref_audio_asset_id/tts_voice
  - `_dataAlignmentNotes` 登记对齐证据与旧版校验必败原因

### 变更原因

- 第3轮缺陷修复批次H（配置契约与一致性）：两份 schema 此前均为空壳/幽灵状态——memory.schema.json properties 为空对象；agent_config_v2.schema.json 的 required 与真实 agents.json 数据结构不符（任何真实数据按 draft-07 校验必然失败）。
- 已获人类显式授权修改 public/ 下这两份 schema（批次H 授权范围 H3/H4）。

### 影响范围

- **MINOR 兼容**：两份契约此前均无有效历史实例（空壳无法约束任何数据）、无下游校验依赖（tests 目录 grep 无引用），本次为首次实质生效发布，等效于纯新增，不阻断既有下游。
- 若严格按字段级差异口径（键重命名 agent_id→id、必填性反转）可视为 MAJOR；因零存量数据、零下游依赖，采用 MINOR 记账并在本节显式登记差异清单。
- 下游提醒：蒸馏管理 Agent 场景（decision_core 读 rubric）后续实现时按可选段读取；前端 Memory 展示层 type 字段即 memory_type 别名。

### 闭合判据

- [x] 两份契约实体更新并通过 json语法校验（python -m json.tool）
- [x] CHANGELOG 记录 v1.7.0 条目（本文件）
- [ ] STUB_INDEX.md 幽灵路径更正（agent_tools_v2.pyi 行源真理指向已不存在的 CXHMS 快照路径）待主线程终审后落盘

## [1.6.0] - 2026-08-24

### 变更内容

- **接口契约变更（MINOR）**：`interface_stub/cx_admin.pyi` 新增（管理面 CX-A 认证/能力清单/统一控制/批量/注册/集群桥，错误码 ADMIN_*）
- **接口契约变更（MINOR）**：`interface_stub/cx_cluster.pyi` 新增（哨兵集群身份/发现/传输/心跳/复制/接管/仲裁/总控，错误码 CLUSTER_*）
- **数据契约变更（MINOR）**：`schema/` 新增 10 份：`admin_manifest`、`admin_control`、`admin_batch`、`admin_audit`、`cluster_identity`、`cluster_node`、`cluster_heartbeat`、`cluster_backup_unit`、`cluster_transport`、`cluster_event`
- **配置契约变更（MINOR）**：`config_template/admin_config.schema.json`、`config_template/cluster_config.schema.json` 新增（管理面与哨兵集群两段，默认 enabled=false）

### 变更原因

- 《CX-O 改造文档 · 管理面（CX-A）与哨兵集群（多机互备）》落地：为 CX-A 提供自描述/强认证/可编排控制面，并为多机 CX-O 互为哨兵实时备份"灵魂"提供契约。

### 影响范围

- **MINOR 变更**：纯新增（新 schema/pyi/模板），无既有字段删除/类型变更/必填性反转，不阻断既有下游。
- 下游待实现：`server/core/admin/*`、`server/core/cluster/*`、`server/api/routers/cluster.py`、扩展 `router/admin.py`、`server/config.py`（admin/cluster 段）、`server/main.py`（装配）、前端 AdminPage/ClusterPage。

### 闭合判据

- [x] public/schema、public/interface_stub、public/config_template 契约落位
- [x] CHANGELOG v1.6.0 记录本条目
- [ ] 后端实现与前端页面经 spec `admin-plane-sentinel-cluster` 落地并回归

## [1.5.1] - 2026-08-16

### 变更内容

- **配置契约变更（PATCH）**：`config_template/qwen3_tts_config.schema.json` 的 `cosyvoice` 段默认模型名与描述同步 CosyVoice3（CosyVoice2-0.5B → Fun-CosyVoice3-0.5B-2512）
  - `cosyvoice.model` 默认值 `CosyVoice2-0.5B` → `Fun-CosyVoice3-0.5B-2512`
  - `cosyvoice` 段 description 与 `base_url` description 同步 CosyVoice3-0.5B
  - 顶层 description 同步「带参考音频的语音克隆由 CosyVoice2 → CosyVoice3 承接」
- **数据契约变更（PATCH）**：`schema/speech_synthesis_response.schema.json` 的 `runtime` 描述文本同步 cosyvoice（CosyVoice2-0.5B → CosyVoice3-0.5B）
- **数据契约变更（PATCH）**：`schema/qwen3_tts_error_codes.json` 的 `RUNTIME_UNSUPPORTED` message 同步「需 CosyVoice3 克隆运行时」
- **接口契约变更（PATCH）**：`interface_stub/qwen3_tts_provider.pyi` 职责注释同步 cosyvoice（CosyVoice2 → CosyVoice3）

### 变更原因

- 用户裁决将 CosyVoice 主运行时由 CosyVoice2-0.5B 升级为 CosyVoice3-0.5B（Fun-CosyVoice3-0.5B-2512，用户确认 QwenAudio/CosyVoice 来源），TTFT/RTF 更优。
- 通过 AskUserQuestion 显式授权「授权同步」public/ 契约描述与默认值（rules-0 §四-10 + rules-4 §4.3 + s0601）。

### 影响范围

- **PATCH 变更**：仅默认值与描述文本更新，无字段增删/类型变更/枚举变更，不阻断下游。
- 下游已同步：`CX-O-SERVER/server/config.py`（Qwen3TTSCosyVoiceConfig.model=Fun-CosyVoice3-0.5B-2512）、`CX-O-SERVER/config.json`（cosyvoice.model）、`CX-O-SERVER/server/qwen3_tts_provider.py`（DEFAULT_COSYVOICE_MODEL）、`tests/test_qwen3_tts_provider.py`（35 passed）。

### 闭合判据

- [x] 4 份契约实体已按 s0601 流程经人类批准更新（PATCH，无结构变更）
- [x] 代码侧 config/provider/tests 已同步并通过定向回归（35 passed）
- [x] CHANGELOG 记录 v1.5.1 条目（本文件）

## [1.5.0] - 2026-08-16

### 变更内容

- **配置契约变更（MINOR）**：`config_template/qwen3_tts_config.schema.json` 落地 CosyVoice2 主 + Qwen3-TTS Base 降级架构（spec `cosyvoice2-primary-qwen3tts-base-fallback` + s0601 契约变更适配，人类显式批准）
  - 删除 `indextts` 段（IndexTTS-2.5 克隆运行时移除）
  - 新增 `cosyvoice` 段（base_url/model/timeout_seconds/sample_rate，承载带 refs 的语音克隆与情感合成，默认 8094/CosyVoice2-0.5B）
  - 新增 `qwen3_base` 段（base_url/model/timeout_seconds/sample_rate，承载全局降级，默认 8093/Qwen/Qwen3-TTS-12Hz-1.7B-Base）
  - `runtime` 保持 `["vllm"]`（配置层首选，内部映射 voicedesign 运行时）
  - `legacy_engine_removed` 描述移除 cosyvoice 旧引擎语义（cosyvoice 已恢复为一级运行时）
- **数据契约变更（MINOR）**：`schema/speech_synthesis_response.schema.json` 的 `runtime` 枚举 `[vllm, indextts]` → `[voicedesign, cosyvoice, qwen3_base]`
- **接口契约变更（PATCH）**：`interface_stub/qwen3_tts_provider.pyi` 职责注释同步 voicedesign（vLLM VoiceDesign）/ cosyvoice（CosyVoice2）/ qwen3_base（Qwen3-TTS Base），`ProviderHealth.runtime` 注释更新

### 变更原因

- 用户裁决替换 IndexTTS 加速方案：IndexTTS-2.5 三阶段流水线复杂、QwenEmotion 10s 固有瓶颈、torch.compile 编译成本高；改用 CosyVoice2-0.5B 作为带 refs 克隆/情感主运行时（极端优化），VoiceDesign 保留（无 refs 音频设计），Qwen3-TTS Base 作全局降级，移除 IndexTTS。
- 通过 AskUserQuestion 显式授权「批准落位 v1.5.0」public/ 契约（rules-0 §四-10 + rules-4 §4.3 + s0601）。

### 影响范围

- **MINOR 变更**：`runtime` 枚举值变化（vllm/indextts → voicedesign/cosyvoice/qwen3_base）通知依赖模块，不阻断；`indextts` 配置段不再合法，映射移除错误。
- 下游已同步：`CX-O-SERVER/server/config.py`（Qwen3TTSCosyVoiceConfig + Qwen3TTSBaseConfig 替换 Qwen3TTSIndexTTSConfig）、`CX-O-SERVER/config.json`（indextts 段 → cosyvoice + qwen3_base 段）、`CX-O-SERVER/server/qwen3_tts_provider.py`（cosyvoice 主 + qwen3_base 降级路由）、`tests/test_qwen3_tts_provider.py`（35 passed 含降级链测试）。

### 闭合判据

- [x] 3 份契约实体已按 s0601 流程经人类批准更新
- [x] 代码侧 config/provider/tests 已同步并通过定向回归
- [x] CHANGELOG 记录 v1.5.0 条目（本文件）

## [1.4.0] - 2026-08-14

### 变更内容

- **配置契约变更（MINOR）**：`config_template/qwen3_tts_config.schema.json` 落地 VoiceDesign + IndexTTS 双运行时架构（spec `unify-qwen3-tts-migration` + s0601 契约变更适配，人类显式批准）
  - `vllm.model` 默认值 `Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice` → `Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign`
  - `vllm.task_type` 枚举/默认值收紧为 `VoiceDesign`（移除 CustomVoice/Base）
  - `runtime` 枚举收紧为 `["vllm"]`（唯一首选）
  - 删除 `official_runtime` 段（官方 Qwen3 Base 临时兜底，已被 IndexTTS 克隆运行时取代）
  - 新增 `indextts` 段（base_url/model/timeout_seconds/sample_rate，承载带 refs 的语音克隆）
- **数据契约变更（MINOR）**：`schema/speech_synthesis_response.schema.json` 的 `runtime` 枚举 `[vllm, official_qwen3]` → `[vllm, indextts]`
- **数据契约变更（PATCH）**：`schema/speech_synthesis_request.schema.json` 的 `voice` 描述「仅 CustomVoice 任务类型」→「仅 vLLM VoiceDesign 任务类型」
- **接口契约变更（PATCH）**：`interface_stub/qwen3_tts_provider.pyi` 职责注释同步 vllm（VoiceDesign）/ indextts（IndexTTS-2.5）

### 变更原因

- 用户裁决「同时需要情感语音克隆与 VoiceDesign，改用 qwen3tts 的 VoiceDesign + IndexTTS」：无参考音频的日常/情感合成由 vLLM VoiceDesign 承接，带参考音频的语音克隆由 IndexTTS-2.5 承接；CustomVoice/Base 模型及官方运行时临时兜底一并移除。
- 通过 AskUserQuestion 显式授权「批准写入」public/ 契约（rules-0 §四-10 + rules-4 §4.3 + s0601）。

### 影响范围

- **MINOR 变更**：`runtime` 枚举值变化（official_qwen3 → indextts）通知依赖模块，不阻断；`vllm.task_type` 收紧为 VoiceDesign，CustomVoice/Base 配置不再合法。
- 下游已同步：`CX-O-SERVER/server/config.py`（Qwen3TTSVLLMConfig 默认 VoiceDesign + 新增 Qwen3TTSIndexTTSConfig）、`CX-O-SERVER/config.json`、`CX-O-SERVER/server/qwen3_tts_provider.py`（indextts 运行时路由）、`tests/test_qwen3_tts_provider.py`（30 passed）、定向回归 144 passed。

### 闭合判据

- [x] 4 份契约实体已按 s0601 流程经人类批准更新
- [x] `python -m pytest tests/test_contracts_qwen3_tts.py` 通过（配置契约 jsonschema 自校验）
- [x] 代码侧 config/provider/tests 已同步并通过定向回归
- [x] CHANGELOG 记录 v1.4.0 条目（本文件）

## [1.3.0] - 2026-08-13

### 变更内容

- **数据契约新增（MINOR）**：统一 Qwen3 TTS 三层契约正式落位 `public/` 公共契约区（spec `unify-qwen3-tts-migration` Task 1 冻结决策，抽象层冻结，能力矩阵摘自 Qwen3-TTS/vLLM-Omni 官方协议，Task 0 探针验证待补）
  - `schema/speech_synthesis_request.schema.json`：归一合成请求（普通/流式/WS/工作站；text 必填；refs 引用资产 ID 禁止本地路径；输出采样率 const 24000）
  - `schema/speech_synthesis_response.schema.json`：非流式响应（audio base64 + runtime 标识 vllm/official_qwen3）
  - `schema/speech_audio_chunk.schema.json`：流式音频块（恰一个 start/一个 final，顺序稳定）
  - `schema/ref_audio_asset.schema.json`：统一参考音频资产（source=prompt/file 双来源，stable ID + checksum 去重，输入采样率 [8000,48000]）
  - `schema/emotion_instruction.schema.json`：LLM 自然语言情感指令（与 reply_text 分离，失败回退中性，禁止 [emotion:*]/Orpheus XML）
  - `schema/qwen3_tts_error_codes.json`：统一错误码枚举（9 码含 http_status，LEGACY_ENGINE_REMOVED 标记旧引擎移除）
- **接口契约新增（MINOR）**：4 份 .pyi 存根
  - `interface_stub/qwen3_tts_provider.pyi`：统一 Provider（synthesize/synthesize_stream/health_check/close + 9 异常类）
  - `interface_stub/ref_audio_store.pyi`：统一参考音频资产存储（register_from_prompt/register_from_file/resolve/list/delete 等）
  - `interface_stub/emotion_instruction_service.pyi`：LLM 情感指令服务（generate_instruction/convert_legacy_marker，含生成回退 vs 显式校验抛错边界）
  - `interface_stub/speech_orchestrator.pyi`：统一语音编排（synthesize_text/synthesize_stream_text/interrupt/close）
- **配置契约新增（MINOR）**：`config_template/qwen3_tts_config.schema.json`（runtime vllm 首选 + official_qwen3 临时兜底、默认值/范围/auto_fill、旧引擎配置映射 LEGACY_ENGINE_REMOVED）
- **索引与 README 更新（PATCH）**：`STUB_INDEX.md`、`schema/README.md`、`config_template/README.md` 追加对应契约行

### 变更原因

- 用户通过 AskUserQuestion 显式授权「批准落位」——统一 Qwen3 TTS 三层契约从规格目录正式落位为跨角色公共真相源（rules-0 §四-10 + rules-4 §4.3）。GN-004 审查为警示放行（CAUTION-PASS），1 SOFT_BLOCK（§五 一致性自检与正文两处矛盾）+ 6 观察已全部修正并获人类确认接受。
- 需求：放弃 F5-TTS/Orpheus、全面改用 Qwen3 TTS、情感改 LLM 自然语言指令、移除工作站参考音频生成、双来源参考音频（提示词生成 + 外部文件）。

### 影响范围

- **MINOR 新增**：11 份契约文件均为新增，不影响 CX-O 现有契约。
- 下游实现待启动：Task 2（Provider）/ Task 3（资产存储）/ Task 4（情感指令）/ Task 5（语音编排）须严格匹配本契约签名。
- 能力假设：`task_type`/`speed`/VoiceDesign/Base 能力基于官方协议，Task 0 部署探针验证后复核，未验证前不视为已部署证实。

### 闭合判据

- [x] 11 份契约实体落位 `public/` 对应目录（6 schema + 4 interface_stub + 1 config_template）
- [ ] 契约测试（jsonschema 自校验 + .pyi 签名匹配）待 Task 1 后续补测试
- [x] 各 README 与 STUB_INDEX 已同步登记

## [1.2.0] - 2026-08-13

### 变更内容

- **数据契约新增（MINOR）**：电脑控制插件三层契约正式落位 `public/` 公共契约区（spec `add-computer-control-cxfc` 冻结决策，迁移自 `.trae/specs/add-computer-control-cxfc/contracts/`）
  - `schema/computer_control_plugin.schema.json`：插件注册数据契约（插件信息 + 三个工具 屏幕/键盘/运行指令 的请求/响应结构 + 统一错误码字段 + 授权状态）
  - `schema/computer_control_error_codes.json`：电脑控制插件统一错误码枚举（8 个错误码，含 http_status 映射）
  - `interface_stub/computer_control.pyi`：插件服务端/后端调用接口存根（health / list_tools / list_skills / call_tool + 8 异常类）
  - `config_template/computer_control_config.schema.json`：插件配置契约（授权/令牌/TLS/run_command 护栏/自启动/管理员权限/后端地址，含默认值与 auto_fill）
- **接口存根索引更新（PATCH）**：`public/interface_stub/STUB_INDEX.md` 追加 `computer_control.pyi` 登记
- **README 更新（PATCH）**：`public/schema/README.md` 与 `public/config_template/README.md` 追加对应契约清单行

### 变更原因

- 用户通过 AskUserQuestion 显式授权「迁移到 public/ 公共区」——电脑控制三层契约从规格目录正式落位为跨角色公共真相源（rules-0 §四-10 + rules-4 §4.3 + s0601 契约变更适配）。
- 测试入口 `tests/test_contracts_computer_control.py` 与 `errors.ts` 引用同步改为 public/ 路径。

### 影响范围

- **MINOR 新增**：4 份契约文件均为新增，不影响 CX-O 现有契约（chat/agents/memory/websocket/RADIX-Lite 等）。
- 下游已同步：`tests/test_contracts_computer_control.py`（CONTRACTS_DIR → public/）、`APP-Frontend/electron/plugins/computerControl/errors.ts`（注释引用）。
- 原 `.trae/specs/add-computer-control-cxfc/contracts/` 下 4 份旧契约文件已随迁移删除，避免双真相源。

### 闭合判据

- [x] 4 份契约实体落位 `public/` 对应目录（schema / interface_stub / config_template）
- [x] `python -m pytest tests/test_contracts_computer_control.py` 通过（21 passed）
- [x] 旧 `contracts/` 目录文件删除，无残留引用（仅保留「迁移自」溯源注释）
- [x] 各 README 与 STUB_INDEX 已同步登记

## [1.1.0] - 2026-07-18

### 变更内容

- **数据契约新增（MINOR）**：从 CXHMS v1.2.0 迁移 5 份 JSON Schema (draft-07+) + 扩展 1 份
  - `distillation_session.schema.json`：蒸馏会话状态机契约（9 状态 + turns 数组 + final_decision）
    - 修正描述「7 状态机」→「9 状态机」（OBS-3 修复，对齐 CXHMS 源码实际状态枚举）
    - `source_type` 枚举扩展 `video` / `audio`（CX-O 多模态扩展）
  - `distillation_log.schema.json`：决策审计日志契约（6 决策点 D1_LOCATION/D2_METADATA/D3_ASK_USER/D4_REDISTILL/D5_CROSS_VALIDATE/D6_REJECT + llm_reasoning + final_decision）
  - `storage_decision.schema.json`：存储决策契约（3 location 枚举 memories/permanent_memories/rejected + rubric_snapshot + override_decision）
  - `agent_config_v2.schema.json`：管理 Agent 配置契约（tools_config 8 工具 + decision_rubric 4 必填阈值 + 3 可选 + distillation_enabled + legacy_parser_enabled）
    - 注：源真理文件名为 `agent_config_v2.schema.json`（非 spec 中误写的 `agent_tools_v2.schema.json`），与 CXHMS 源码 + `agent_tools_v2.pyi` 的 `@see` 引用保持一致
  - `rejected_content.schema.json`：拒绝内容契约（CX-O 新建，CXHMS 无此文件）
    - 字段：`rejected_id` / `session_id` / `original_content` / `quality_score` / `reject_reason` / `rubric_snapshot` / `created_at` / `expires_at` / `is_purged` / `human_overridden`
    - 用于 D6_REJECT 决策时存储质量评分低于 `rubric.quality_reject_threshold` 的内容，保留 `rubric.rejected_content_retention_days` 天（默认 30 天）
  - `multimodal_artifact.schema.json`：多模态预处理产出契约扩展（**MODIFIED**）
    - type 枚举扩展：`text` / `character_card` / `image` + `video` / `audio`（CX-O 扩展）
    - 新增 `native_decode_used` 字段：标记是否使用 vLLM 原生解码（仅对 video/audio 模态有意义）
    - 错误码新增：`VLLM_NATIVE_UNAVAILABLE` (503) / `VIDEO_DECODE_FAILED` (422) / `AUDIO_DECODE_FAILED` (422)
    - 异常契约 `RuntimeError_500.trigger_methods` 加入 `_vllm_native_worker`
    - 异常契约 `ConnectionError_503.trigger_methods` 加入 `_vllm_native_worker`
- **接口契约新增（MINOR）**：新增 6 份 .pyi 存根
  - `template_engine.pyi`：7 方法（`render_template` + CRUD `create_template`/`get_template`/`update_template`/`delete_template`/`list_templates` + `_parse_frontmatter`）
  - `multimodal_pipeline.pyi`：CX-O 扩展版（5 模态：text/character_card/image/video/audio）
    - 包含 CXHMS 原有方法：`preprocess` / `_text_worker` / `_character_card_worker` / `_image_worker` / `_ocr_worker` / `_vision_worker` / `_merge_ocr_vision`
    - 新增 `_vllm_native_worker`：vLLM 原生视频/音频解码 worker，检测 LLM provider，若为 vllm 走 vLLM API 直接投递，否则降级
  - `distillation_service.pyi`：4 API 端点 + 1 内部方法（`start_distillation` / `advance_distillation` / `finalize_distillation` / `get_session_status` / `_transition_state`）
    - 端口说明更新：原 CXHMS「独立 FastAPI 子服务（端口 8011）」→「CX-O-SERVER 路由（端口 8000），作为主路由注册」
    - 状态机描述修正：「7 状态机」→「9 状态机」
  - `decision_core.pyi`：9 方法（6 决策点 `_decide_location` / `_decide_metadata` / `_decide_ask_user` / `_decide_redistill` / `_decide_cross_validate` / `_decide_reject` + `_load_rubric` + `_llm_decide` + `_write_audit_log`）
  - `memory_manager_v2.pyi`：3 方法（`write_with_decision` + `get_rejected_content` + `cleanup_expired_rejected_content`）
  - `agent_tools_v2.pyi`：8 工具方法（`create_memory_tool` / `search_memory_tool` / `update_memory_tool` / `delete_memory_tool` / `render_template_tool` / `list_templates_tool` / `preprocess_multimodal_tool` / `distill_content_tool`）
- **配置契约新增（MINOR）**：新增 `radix_config.json`（CX-O 适配版，5 段）
  - `distillation_service`：端口 8001 → 8000（CX-O-SERVER 主路由），main_backend_url 同步更新
  - `multimodal_pipeline`：3 模态 → 5 模态（text/character_card/image/video/audio），新增 `vllm_native_enabled` 字段（默认 true）
  - `template_engine`：模板路径与 CXHMS 一致（`data/templates/presets` / `data/templates/custom`）
  - `decision_core`：6 决策点 rubric 默认值（含 `rejected_content_retention_days` 默认 30）
  - `vllm`：base_url / vision_base_url 端口 8002 → 8080（CX-O docker/llm/）
- **接口存根索引更新（PATCH）**：`public/interface_stub/STUB_INDEX.md` 追加 6 个 RADIX .pyi 文件登记

### 变更原因

- spec `migrate-cxhms-radix-acp-multimodal` 实施：迁移 CXHMS RADIX-Lite v1.2.0（模块 7-10）+ ACP v3.1.0 到 CX-O-SERVER，并加强多模态蒸馏（视频/音频使用 vLLM 原生解码，仅当 LLM provider=vllm 时启用）。
- spec 三件套已通过 GN-004 第二次独立审查，结论为「警示放行」（CAUTION-PASS），3 阻断 + 4 SOFT_BLOCK 全部修复，7 ADDED + 2 MODIFIED + 1 REMOVED Requirements 已收口。
- [V] 双重闸门已闭合：GN-004 警示放行 + 人类批准交付（2026-07-18）。
- public/ 文件已获人类显式授权（rules-0 §四-10 + rules-4 §4.3）：用户通过 AskUserQuestion 显式选择「全部 RADIX-Lite(7-10) + ACP」迁移范围 + 「全部放 CX-O-SERVER/server/」目标位置 + 「删除现有 e2e + 复制 test_tools 模式」测试策略。

### 影响范围

- **MINOR 变更**（新增可选字段、新增 schema、扩展枚举）：通知依赖模块，不阻断。
- 新增的 5 schema + 6 .pyi + 1 config 独立于 CX-O 现有契约（chat/agents/memory/websocket 等），不影响现有模块。
- `multimodal_artifact.schema.json` 的 type 枚举扩展为 **MINOR 兼容**：现有 type=text/character_card/image 的数据仍合法，新增 video/audio 仅在 CX-O 多模态蒸馏场景使用。
- 下游影响：
  - `CX-O-SERVER/server/core/template_engine/`（B1）必须严格匹配 `template_engine.pyi` 7 方法签名
  - `CX-O-SERVER/server/core/multimodal/`（B2）必须实现扩展后的 `multimodal_pipeline.pyi`，含 `_vllm_native_worker`
  - `CX-O-SERVER/server/core/decision/`（B4）必须实现 6 决策点 + `write_with_decision` + `rejected_content` 表
  - `CX-O-SERVER/server/core/distillation/`（B3，串行依赖 B2+B4）必须实现 9 状态机 + 4 API 端点
  - `CX-O-SERVER/server/core/acp/manager.py`（B5）升级到 v3.1.0 per-agent 隔离
  - `CX-O-SERVER/server/config.py`（B6）新增 4 配置节，默认值与本契约一致
  - 模块间通过 try-except fallback 到 Mock（rules-0 §三），不硬依赖真实实现

### 闭合判据

- [x] 5 份新数据契约存在且通过 jsonschema 自校验
- [x] 1 份扩展数据契约（multimodal_artifact）保留原字段 + 新增 video/audio/native_decode_used
- [x] 6 份接口存根存在且仅含签名（零实现）
- [x] 1 份配置契约存在且含默认值（5 段，CX-O 端口适配）
- [x] CHANGELOG 含 v1.1.0 条目（本文件）
- [x] STUB_INDEX.md 追加 6 个新 .pyi 登记
- [ ] 6 份预生成 Mock 存在且签名匹配 .pyi（Task A2 闭合后勾选）
- [ ] 测试套件可自主执行（Task D5 闭合后勾选）
- [x] GN-004 第二次审查警示放行，[V] 双重闸