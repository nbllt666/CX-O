# public/pre_generated_mock/ — 预生成 Mock

> Mock 机制三原则之一（rules-3 §四）：契约冻结后，工具自动根据接口存根生成所有模块的默认 Mock 实现，返回符合数据契约的模拟值。

## 当前状态：未生成

本目录当前为空，待 s0202 Skill 基于已冻结的 `public/schema/` + `public/interface_stub/` 生成稳定 Mock。

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

CX-O-Frontend 已有 MSW（Mock Service Worker）基础设施：
- `c:/CX-O/CX-O-Frontend/src/mocks/handlers.ts`（仅 5 个 handler，覆盖 /api/health、/api/live/client/status、/api/config、/api/agents 等极少端点）
- `c:/CX-O/CX-O-Frontend/src/mocks/mock-regression.test.ts`

s0202 阶段需大幅扩展 MSW handlers 以覆盖 12 个域 mixin 的全部端点。
