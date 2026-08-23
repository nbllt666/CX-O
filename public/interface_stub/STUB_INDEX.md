# public/interface_stub/ — 接口契约存根索引

> 接口契约层，rules-3 §二定义。所有对外接口以 Python .pyi 存根文件定义，零实现逻辑，仅声明签名（方法名、参数类型、返回值类型、抛出异常）。

## 当前状态：种子阶段 + s0601 部分补全 + RADIX-Lite 迁移补全

- s0601 (Spec A) 已补全 `websocket.pyi`（7 消息模型 + 18 个独立 Action 类镜像 + 4 WS 端点签名 + 5 工厂函数签名）
- spec `migrate-cxhms-radix-acp-multimodal` 已补全 RADIX-Lite 6 个 .pyi（template_engine / multimodal_pipeline / distillation_service / decision_core / agent_tools_v2 / memory_manager_v2）—— 见下方「RADIX-Lite 迁移存根清单」
- 其余存根仍为种子阶段，待 s0201 完整补全

## 计划存根清单（19 个 FastAPI router + WS）

| 存根文件 | 源真理（router 文件） | 优先级 | 状态 |
|---------|---------------------|--------|------|
| `chat.pyi` | `c:/CX-O/CX-O-SERVER/server/api/routers/chat.py` | P0 | 🟡 种子已建 |
| `agents.pyi` | `c:/CX-O/CX-O-SERVER/server/api/routers/agents.py` | P0 | 🟡 种子已建 |
| `memory.pyi` | `c:/CX-O/CX-O-SERVER/server/api/routers/memory.py` | P0 | 🟡 种子已建 |
| `websocket.pyi` | `c:/CX-O/CX-O-SERVER/server/api/routers/websocket.py` + `server/protocol/` | P0 | ✅ s0601 补全 |
| `graph.pyi` | `c:/CX-O/CX-O-SERVER/server/api/routers/graph.py` | P1 | ⬜ 待 s0201 |
| `acp.pyi` | `c:/CX-O/CX-O-SERVER/server/api/routers/acp.py` | P1 | ⬜ 待 s0201 |
| `cxfc.pyi` | `c:/CX-O/CX-O-SERVER/server/api/routers/cxfc.py` | P1 | ⬜ 待 s0201 |
| `audio.pyi` | `c:/CX-O/CX-O-SERVER/server/api/routers/audio.py` | P1 | ⬜ 待 s0201 |
| `avatars.pyi` | `c:/CX-O/CX-O-SERVER/server/api/routers/avatars.py` | P1 | ⬜ 待 s0201 |
| `tools.pyi` | `c:/CX-O/CX-O-SERVER/server/api/routers/tools.py` | P1 | ⬜ 待 s0201 |
| `vector.pyi` | `c:/CX-O/CX-O-SERVER/server/api/routers/vector.py` | P1 | ⬜ 待 s0201 |
| `config.pyi` | `c:/CX-O/CX-O-SERVER/server/api/routers/config.py` | P2 | ⬜ 待 s0201 |
| `context.pyi` | `c:/CX-O/CX-O-SERVER/server/api/routers/context.py` | P2 | ⬜ 待 s0201 |
| `service.pyi` | `c:/CX-O/CX-O-SERVER/server/api/routers/service.py` | P2 | ⬜ 待 s0201 |
| `admin.pyi` | `c:/CX-O/CX-O-SERVER/server/api/routers/admin.py` | P2 | ⬜ 待 s0201 |
| `stats.pyi` | `c:/CX-O/CX-O-SERVER/server/api/routers/stats.py` | P2 | ⬜ 待 s0201 |
| `backup.pyi` | `c:/CX-O/CX-O-SERVER/server/api/routers/backup.py` | P2 | ⬜ 待 s0201 |
| `archive.pyi` | `c:/CX-O/CX-O-SERVER/server/api/routers/archive.py` | P2 | ⬜ 待 s0201 |
| `memory_chat.pyi` | `c:/CX-O/CX-O-SERVER/server/api/routers/memory_chat.py` | P2 | ⬜ 待 s0201 |
| `computer_control.pyi` | 电脑控制插件服务端/后端调用边界（spec `add-computer-control-cxfc` 冻结决策；源真理 `public/schema/computer_control_plugin.schema.json`） | P1 | ✅ s0201 补全（迁移自 contracts/plugin_interface.pyi） |
| `qwen3_tts_provider.pyi` | 统一 Qwen3 TTS Provider（spec `unify-qwen3-tts-migration` Task 1 冻结决策；源真理 `public/schema/speech_synthesis_request.schema.json` + `qwen3_tts_error_codes.json`） | P0 | ✅ s0201 补全 |
| `ref_audio_store.pyi` | 统一参考音频资产存储（spec `unify-qwen3-tts-migration` Task 1 冻结决策；源真理 `public/schema/ref_audio_asset.schema.json`） | P0 | ✅ s0201 补全 |
| `emotion_instruction_service.pyi` | LLM 自然语言情感指令服务（spec `unify-qwen3-tts-migration` Task 1 冻结决策；源真理 `public/schema/emotion_instruction.schema.json`） | P0 | ✅ s0201 补全 |
| `speech_orchestrator.pyi` | 统一 Qwen3 语音编排（spec `unify-qwen3-tts-migration` Task 1 冻结决策；源真理 `public/schema/speech_synthesis_request.schema.json` + `qwen3_tts_error_codes.json`） | P0 | ✅ s0201 补全 |
| `dream.pyi` | CX-O-Dream 梦境引擎（spec `add-dream-engine-embedded` 冻结决策；源真理 `c:/CX-O/CX-O-SERVER/server/autonomy/dream/`（config/engine/buffer/consolidator/purge）+ `server/core/memory/mixins/dream_mixin.py`（_DreamMixin）+ `public/schema/dream_config.schema.json` + `dream_status.schema.json`） | P0 | ✅ s0201 补全 |

### Qwen3 TTS 存根清单（spec `unify-qwen3-tts-migration`）

> 统一 Qwen3 TTS 三层契约的接口层，对应 Task 1 冻结。源真理为 `public/schema/` 下同名数据契约与 `qwen3_tts_error_codes.json`。

| 存根文件 | 源真理 schema | 异常契约 | 状态 |
|---------|--------------|---------|------|
| `qwen3_tts_provider.pyi` | `speech_synthesis_request.schema.json` + `qwen3_tts_error_codes.json` | 9 异常类（InvalidRequest/InvalidRefAudio/RefAudioNotFound/EmotionInstructionInvalid/RuntimeUnavailable/RuntimeUnsupported/StreamAborted/LegacyEngineRemoved/System） | ✅ 契约冻结 |
| `ref_audio_store.pyi` | `ref_audio_asset.schema.json` | InvalidRefAudioError / RefAudioNotFoundError | ✅ 契约冻结 |
| `emotion_instruction_service.pyi` | `emotion_instruction.schema.json` | EmotionInstructionInvalidError（生成路径回退 vs 显式校验抛错边界） | ✅ 契约冻结 |
| `speech_orchestrator.pyi` | `speech_synthesis_request.schema.json` + `qwen3_tts_error_codes.json` | 复用 Provider 异常类 | ✅ 契约冻结 |

## 契约可验证性（rules-3 §五）

- **测试套件**：未闭合，待 s0201 生成完整存根后补接口契约签名匹配用例；电脑控制部分已有 `tests/test_contracts_computer_control.py` 覆盖
- **合规 rubric**：未闭合，待 s0201 生成后补签名匹配判据
- **signature_match 校验**：模块实现必须严格匹配存根定义的签名，否则契约测试不通过

## 异常说明规范

- 接口契约必须包含异常说明（rules-3 §二）
- 调用方必须处理约定的异常
- 异常类型与错误码对应 `schema/error_codes.schema.json`

## RADIX-Lite 迁移存根清单（spec `migrate-cxhms-radix-acp-multimodal`）

> 从 CXHMS v1.2.0 迁移 6 个 .pyi，对应 RADIX-Lite 模块 7-10。CX-O 扩展：multimodal_pipeline.pyi 增加 `_vllm_native_worker` 方法支持 vLLM 原生视频/音频解码。

| 存根文件 | 源真理（CXHMS 源码） | 对应 schema | 状态 |
|---------|---------------------|------------|------|
| `template_engine.pyi` | `c:/CX-O/CXHMS/modules/模块7_模板引擎/template_engine.py` | `public/schema/distillation_session.schema.json`（template_id 关联） | ✅ 迁移完成（7 方法，原样复制） |
| `multimodal_pipeline.pyi` | `c:/CX-O/CXHMS/modules/模块8_多模态管线/multimodal_pipeline.py` | `public/schema/multimodal_artifact.schema.json` | ✅ 迁移完成（CX-O 扩展：5 模态 + `_vllm_native_worker`） |
| `distillation_service.pyi` | `c:/CX-O/CXHMS/modules/模块9_蒸馏服务/distillation_service.py` | `public/schema/distillation_session.schema.json` + `distillation_log.schema.json` | ✅ 迁移完成（OBS-3 修正：7→9 状态机；端口 8011→8000） |
| `decision_core.pyi` | `c:/CX-O/CXHMS/modules/模块10_管理Agent扩展/decision_core.py` | `public/schema/distillation_log.schema.json` + `storage_decision.schema.json` | ✅ 迁移完成（9 方法：6 决策点 + 3 内部方法，原样复制） |
| `agent_tools_v2.pyi` | `c:/CX-O/CXHMS/modules/模块10_管理Agent扩展/agent_tools.py` | `public/schema/agent_config_v2.schema.json` | ✅ 迁移完成（8 工具方法，原样复制） |
| `memory_manager_v2.pyi` | `c:/CX-O/CXHMS/backend/core/memory/manager.py`（V2 扩展部分） | `public/schema/storage_decision.schema.json` + `rejected_content.schema.json` | ✅ 迁移完成（3 方法：write_with_decision + get_rejected_content + cleanup_expired_rejected_content） |

### CX-O 扩展点

- **multimodal_pipeline.pyi**：新增 `_vllm_native_worker(source_ref, modality)` 方法
  - 检测 LLM provider 配置：若 `provider=vllm` 则通过 vLLM OpenAI 兼容 API 直接投递原生视频/音频文件
  - 若 `provider!=vllm` 或 vLLM 端点不可达：降级路径，返回占位文本 + `vision_degraded=True` + `native_decode_used=False`
  - `MultimodalArtifact` 模型新增 `native_decode_used: bool = False` 字段

### 契约可验证性（RADIX 部分）

- **测试套件**：未闭合，Task A2 将生成 6 份 Mock 后由 Task D5 补 E2E
- **signature_match 校验**：CX-O-SERVER 实现模块（B1/B2/B3/B4）必须严格匹配存根签名
- **CX-O 扩展验证**：`_vllm_native_worker` 在 provider=vllm 与 provider!=vllm 两种场景下行为需通过单测
