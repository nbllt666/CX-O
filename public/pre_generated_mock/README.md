# public/pre_generated_mock/ — 预生成 Mock

> Mock 机制三原则之一（rules-3 §四）：契约冻结后，工具自动根据接口存根生成所有模块的默认 Mock 实现，返回符合数据契约的模拟值。

## 当前状态：RADIX-Lite 6 Mock 已生成

本目录已生成 RADIX-Lite 6 个 Mock 文件（CX-O 迁移版 @version 1.1.0），基于 CXHMS v1.2.0 Mock 适配。

## RADIX-Lite 6 Mock 文件清单（CX-O 迁移版 @version 1.1.0）

基于 CXHMS v1.2.0 Mock 适配，严格匹配 `public/interface_stub/` 下 6 个 .pyi 存根签名，
返回符合 `public/schema/` 数据契约的模拟值。零外部依赖（不依赖 vLLM / Weaviate / SQLite / PaddleOCR）。

| 文件 | 对应 .pyi 存根 | 对应 schema | 方法数 | 说明 |
|------|---------------|-------------|--------|------|
| `mock_template_engine.py` | `template_engine.pyi` | —（无独立 schema，字段以实现 template_engine.py 为准，待 s0201 重建） | 7 | 模板渲染 + CRUD（YAML frontmatter + Jinja2） |
| `mock_multimodal_pipeline.py` | `multimodal_pipeline.pyi` | `multimodal_artifact.schema.json` | 8 | 5 模态预处理（CX-O 扩展：含 `_vllm_native_worker` + `native_decode_used` 字段） |
| `mock_distillation_service.py` | `distillation_service.pyi` | `distillation_session.schema.json` | 5 | 4 API + 1 内部方法（9 状态机多轮蒸馏） |
| `mock_decision_core.py` | `decision_core.pyi` | `storage_decision.schema.json` | 9 | 6 决策点 + 3 内部方法（rubric 驱动） |
| `mock_agent_tools_v2.py` | `agent_tools_v2.pyi` | `agent_config_v2.schema.json` | 8 | 8 工具方法（Agent CRUD + 蒸馏 + 模板 + 决策） |
| `mock_memory_manager_v2.py` | `memory_manager_v2.pyi` | `storage_decision.schema.json` | 3 | write_with_decision + rejected_content 管理 |

### CX-O 扩展点（mock_multimodal_pipeline.py）

- `MultimodalArtifact` 类新增 `native_decode_used: bool = False` 字段（与 `multimodal_artifact.schema.json` 一致）
- 新增 `_vllm_native_worker(source_ref, modality)` 方法：模拟 vLLM 原生视频/音频解码
  - vllm 场景（provider=vllm 且端点可用）：`native_decode_used=True, vision_degraded=False, confidence=0.88`
  - 降级场景（provider!=vllm 或端点不可达）：`native_decode_used=False, vision_degraded=True, confidence=0.5`
  - 稳定可重现：通过 `source_ref` 中是否包含 `degrade` 关键字决定路径，不使用 random
- `preprocess` 方法路由 `video`/`audio` 模态到 `_vllm_native_worker`
- `_SOURCE_TYPES` 扩展为 5 模态：text / character_card / image / video / audio

### 验证状态

- ✅ 6 个文件 Python 语法检查全部通过（`py_compile`）
- ✅ 所有方法签名严格匹配 .pyi 存根（参数名/类型/默认值/返回类型）
- ✅ Mock 返回值符合 schema 数据契约（必填字段齐全、类型正确、枚举值合法）
- ✅ `_vllm_native_worker` 两种场景（原生/降级）返回值验证通过
- ✅ 零外部依赖（全部内存态模拟）

## 生成前提

- ✅ public/schema/ 种子已建（待 s0201 补全完整 Schema）
- ✅ public/interface_stub/ 种子已建（待 s0201 补全完整存根）
- ⬜ 契约冻结（S2 阶段完成）
- ⬜ s0202 Skill 执行

## 生成范围

基于 `public/interface_stub/` 下 19 个 router 存根 + WS Actions，生成默认 Mock 实现，覆盖：
- HTTP 端点的 Mock 响应（符合 `schema/` 数据契约）
- WS Actions 的 Mock 响应
- 流式端点的 Mock SSE 数据流

## 前端 Mock 现状

APP-Frontend 以 vitest + jsdom 为主（api/clients 直连，见 `APP-Frontend/src/api/`），MSW 基础设施待扩展：
- `APP-Frontend/src/api/` 下的客户端直连测试（base.test.ts 等）
- Mock 回归测试由 s0402 前端三重闸门承接
