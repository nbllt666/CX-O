# 通用测试用例种子

> 通用测试用例目录，rules-2 §1.2 定义。本文件为测试类目计划，待 s0201/s0202 阶段补全具体用例。

## 测试类目计划

### 1. 数据契约校验用例（rules-3 §五）

| 用例类目 | 覆盖 Schema | 优先级 | 状态 |
|---------|------------|--------|------|
| Agent 数据校验 | `schema/agent.schema.json` | P0 | ⬜ 待 s0201 |
| ChatMessage 校验 | `schema/chat_message.schema.json` | P0 | ⬜ 待 s0201 |
| Memory 校验 | `schema/memory.schema.json` | P1 | ⬜ 待 s0201 |
| GraphEntity 校验 | `schema/graph_entity.schema.json` | P1 | ⬜ 待 s0201 |
| Tool 校验 | `schema/tool.schema.json` | P1 | ⬜ 待 s0201 |
| ErrorCode 校验 | `schema/error_codes.schema.json` | P2 | ⬜ 待 s0201 |

### 2. 接口契约签名匹配用例（rules-3 §五）

| 用例类目 | 覆盖存根 | 优先级 | 状态 |
|---------|---------|--------|------|
| Chat router 签名匹配 | `interface_stub/chat.pyi` | P0 | ⬜ 待 s0201 |
| Agents router 签名匹配 | `interface_stub/agents.pyi` | P0 | ⬜ 待 s0201 |
| Memory router 签名匹配 | `interface_stub/memory.pyi` | P0 | ⬜ 待 s0201 |
| WebSocket 签名匹配 | `interface_stub/websocket.pyi` | P0 | ⬜ 待 s0201 |
| 其余 15 router 签名匹配 | `interface_stub/*.pyi` | P1-P2 | ⬜ 待 s0201 |

### 3. 配置契约默认值填充用例（rules-3 §五）

| 用例类目 | 覆盖 Schema | 优先级 | 状态 |
|---------|------------|--------|------|
| UnifiedConfig 默认值填充 | `config_template/unified_config.schema.json` | P0 | ⬜ 待 s0201 |
| default.yaml 默认值填充 | `config_template/default_yaml.schema.json` | P0 | ⬜ 待 s0201 |
| settings.json 默认值填充 | `config_template/settings_json.schema.json` | P1 | ⬜ 待 s0201 |
| env 默认值填充 | `config_template/env.schema.json` | P1 | ⬜ 待 s0201 |

### 4. 前端三重测试闸门（s0402 承接）

前端变更需通过三重闸门（单测→E2E→Mock 回归），详见 `.trae/rules/rules-4.md` §6 与 s0402 Skill。

| 关卡 | 测试框架 | 覆盖范围 | 状态 |
|------|---------|---------|------|
| Test 1 | streamlit-testing 单元测试 | 组件级功能验证 | ⬜ CX-O 为 React 前端，需适配为 React Testing Library |
| Test 2 | Playwright E2E | 全流程功能验证 | ⬜ APP-Frontend 待补 playwright 配置 |
| Test 3 | Mock 回归 | INPUT→MONITOR→REVIEW | ⬜ APP-Frontend 以 vitest/jsdom + api/clients 直连测试为主，MSW 待扩展 |

## 契约可验证性状态

- **整体状态**：未闭合
- **阻塞项**：s0201 未生成完整 Schema/存根，测试用例无法编写
- **接续入口**：s0201 完成契约生成后，按本计划逐类目编写用例

## CXO-Tuner 契约登记（2026-08-22）

CXO-Tuner 自适应微调服务三层契约，已生成的契约测试见
`CX-O-SERVER/tests/test_contracts_cxo_tuner.py`。

| 层 | 契约文件 | 状态 |
|----|---------|------|
| 数据契约 | `public/schema/cxo_tuner_feedback.schema.json`（偏好反馈） | ✅ 已登记 |
| 数据契约 | `public/schema/cxo_tuner_dpo_dataset.schema.json`（DPO 数据集记录） | ✅ 已登记 |
| 配置契约 | `public/schema/cxo_tuner_config.schema.json`（主 schema） | ✅ 已登记 |
| 配置契约 | `public/config_template/cxo_tuner_config.schema.json`（config 模板镜像） | ✅ 已登记 |
| 接口契约 | `public/interface_stub/cxo_tuner.pyi` | ✅ 已登记 |
| 契约测试 | `CX-O-SERVER/tests/test_contracts_cxo_tuner.py` | ✅ 已登记 |
