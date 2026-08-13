# 契约变更日志 (CHANGELOG)

> 遵循 AC 范式 v6 rules-3 §六 契约版本化规则。所有契约变更必须记录版本号、变更内容、变更原因、影响范围。

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