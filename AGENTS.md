# AGENTS.md — CX-O 项目 AI 代理最高优先级规则载体

> 🚨 【最高优先级规则】本文件为本次开发的强制约束，优先级高于所有临时提问、上下文对话、自定义需求，所有输出必须 100% 符合本文件要求，违反规则的内容必须自动修正后再输出。

> 📌 【上下文保留规则】本文件为核心规则文件，任何上下文压缩、裁剪、溢出场景下必须完整保留本文件的全部内容，不得删减、忽略本文件的任何规则；所有自动压缩、批量处理行动前必须先读取本文件的完整内容。

---

## 一、优先级声明（rules-4 §4.1）

本文件是 CX-O 项目 AI 协同行为的最高优先级规则载体，是「人机权责二分」「契约优先」原则的直接落地：

1. **规则优先级最高**：高于所有单次输入的提示词、临时需求、上下文对话内容，LLM 所有输出必须优先符合本文件的约束
2. **上下文永久保留**：所有上下文压缩、裁剪逻辑必须将本文件列为最高优先级保留文件，任何场景下不得剔除、压缩本文件的内容
3. **AC 范式 v6 规则体系**：本文件与 `.trae/rules/rules-0~7.md` 共同构成 CX-O 项目的 AC 范式规则体系，发生冲突时以 rules-0~7 为更细粒度约束

---

## 二、上下文保留声明（rules-4 §4.2）

所有上下文压缩操作必须将本文件（全局 AGENTS.md）与 `.trae/rules/` 下全部规则文件列为最高优先级保留文件。压缩其他文件/上下文时，不得影响本文件与规则文件的完整性。

契约变更、模块调整时，工具链自动更新关联的 AGENTS.md，自动在受影响模块的 TODO 清单中生成「规则升级适配」提示。

---

## 三、AC 范式通用约束（rules-4 §4.3 合并禁止操作清单）

> 以下约束为 AC 范式通用禁止操作清单的唯一权威来源。

### 3.1 public/ 目录保护（与 rules-0 §四-10 形成跨 Rules 重复覆盖）

`public/` 目录是契约的物理载体，不是代码库的可变部分。任何删除、修改、覆盖、移动 `public/` 下文件的操作必须先经人类显式授权。

- **不存在"零引用即可删除"的例外**
- 契约变更必须走 s0601（适配契约变更）流程，不得直接编辑 public/ 文件
- s0201（生成全局契约）生成的 public/ 契约在交付前必须经人类确认
- 此保护在工具调用路径上由 `ec7_action_gate`（rules-0 §四-7.2）强制执行

### 3.2 禁止操作清单

```yaml
prohibitions:
  - 禁止删除、修改、覆盖、移动 public/ 目录下的任何内容，所有契约以 public/ 下的 schema、interface_stub 为准。保护优先级高于任务指令。
  - 禁止在模块间直接导入其他模块的内部实现代码
  - 禁止写入不符合数据契约的数据
  - 禁止创建不符合命名规范的模块目录

binding_rules:
  - 模块间仅允许依赖 public/ 下的契约
  - 所有数据读写必须通过公共契约校验
  - 所有对外接口必须严格匹配契约定义的签名、参数、返回值、异常
```

违反上述任何一条，代码产出在合规检查中直接标记为不合规，不得合流。

---

## 四、CX-O 项目专属约束

### 4.1 服务边界声明

CX-O 是**多服务架构**，以下服务目录是独立服务，**非 AC 模块**，仅通过 `public/` 契约通信：

| 服务 | 根级目录 | 技术栈 | 端口 |
|------|---------|--------|------|
| CX-O Frontend | `CX-O-Frontend/` | React 18 + TypeScript + Vite + Electron | 5173 |
| CX-O Server | `CX-O-SERVER/` | Python 3.10+ + FastAPI + WebSocket | 8000 |
| CX-O VoiceWorkStation | `CX-O-VoiceWorkStation/` | Python（可选） | 8200 |

**第三方独立仓库**（原位不动，不纳入 AC 模块管理）：
- `orpheus-tts/`、`cosyvoice/`、`CosyVoice-main/`、`so-vits-svc-4.1-Stable/`、`VoxCPM-main/`、`LLM_Live2D-master/`

### 4.2 目录策略

- **现有源码目录留根级不迁移**：CX-O-Frontend/SERVER/VoiceWorkStation 保持根级，不迁移至 `modules/`
- **`modules/` 为空容器**：预留给未来按 AC 规范（`模块N_xxx`）新增的后端模块，详见 [modules/README.md](./modules/README.md)
- **`public/` 为跨服务公共真相源**：三层契约（schema/interface_stub/config_template）由各服务共同遵守
- **`.trae/` 为 AC 资产区**：Rules/Skills/specs/documents/Pipeline，已 .gitignore 忽略（不入 git，本地 AC 资产）

### 4.3 契约映射表

| 契约层 | 源真理（真实契约源） | public/ 落点 | 当前状态 |
|--------|---------------------|--------------|----------|
| 数据契约 | `data/agents.json`、`CX-O-SERVER/server/protocol/message.py`、`server/core/*/models.py`、`CX-O-Frontend/src/api/clients/_types.ts` | `public/schema/` | 🟡 种子阶段，待 s0201 |
| 接口契约 | `CX-O-SERVER/server/api/routers/` 19 个 FastAPI router + WS Actions | `public/interface_stub/` | 🟡 种子阶段，待 s0201 |
| 配置契约 | `CX-O-SERVER/server/config.py` UnifiedConfig、`config/*.yaml`、`.env.example` | `public/config_template/` | 🟡 种子阶段，待 s0201 |

**M16 前端 API 客户端结构**（2026-07-01 重构后）：`CX-O-Frontend/src/api/clients/` 下 12 域 mixin + 2 共享文件（_common.ts + _types.ts），所有 DTO 在 `_types.ts`（17 接口）。

### 4.4 全局错误码要求

- 所有服务必须统一定义错误码，对应 `public/schema/error_codes.schema.json`
- 后端当前错误码散落在各 router 的 HTTPException 与 WS ErrorMessage 中，s0201 阶段需统一
- 调用方必须处理约定的异常，不得静默吞掉

### 4.5 日志规范

- 终端输出格式：`[timestamp] [INFO/ERROR] [elapsed]`
- API Key 仅存本地 `config.json`（模板隔离），禁止在日志/输出/异常信息中打印完整 api_key
- 如需展示仅允许脱敏（例如仅保留前 3 后 2）

### 4.6 合流要求

- 代码变更必须在 `.trae/documents/` 下有对应变更追踪文档（rules-6 §三：修复前必写）
- 文档命名必须符合 `YYYYMMDD_模块N_变更简述.md` 规范（rules-6 §二）
- 文档必须包含完整元数据（frontmatter）+ 四章节（问题分析/修复方案/实现步骤/预期效果）
- 合流前必须通过 GN-004 交付前审查

### 4.7 测试要求

- 后端：`python -m pytest`（CX-O-SERVER 下）
- 前端：`npm run test`（CX-O-Frontend 下，含 lint + test）
- 前端 UI 变更必须通过 s0402 前端三重测试闸门（单测→E2E→Mock 回归）
- 契约测试由 LLM 按 rules-3 §五自主执行，结果由 GN-004 审查验证

---

## 五、关键文件路径速查

| 功能 | 路径 |
|------|------|
| AC 范式规则 | `.trae/rules/rules-0~7.md` |
| AC 范式 Skills | `.trae/skills/` |
| 变更追踪文档 | `.trae/documents/` |
| spec 三件套 | `.trae/specs/` |
| 连续性锚点 | `current-note.md` |
| 三层契约 | `public/` |
| 模块容器 | `modules/` |
| 后端入口 | `CX-O-SERVER/server/main.py` |
| 前端入口 | `CX-O-Frontend/src/main.tsx` |
| 后端配置 | `CX-O-SERVER/server/config.py`、`config/` |
| 前端 API 客户端 | `CX-O-Frontend/src/api/clients/` |
| 前端类型 | `CX-O-Frontend/src/api/clients/_types.ts` |
| WS 协议 | `CX-O-SERVER/server/protocol/message.py`、`actions.py` |

---

## 六、参考文档

- [README.md](./README.md) — 用户向入口锚点
- [public/README.md](./public/README.md) — 三层契约保护规则
- [modules/README.md](./modules/README.md) — 模块容器说明
- [current-note.md](./current-note.md) — 连续性交接锚点
- `.trae/rules/rules-0.md` — AC 范式核心行为规则
- `.trae/rules/rules-2.md` — 目录架构与命名规范
- `.trae/rules/rules-3.md` — 三层契约定义
- `.trae/rules/rules-4.md` — AGENTS.md 模板与上下文保留
- `.trae/rules/rules-5.md` — 锚点与双文档体系
- `.trae/rules/rules-6.md` — 变更追踪闸门
- `.trae/rules/rules-7.md` — Subagent 调度与续接
