# 契约变更日志

> 本文件记录 `public/` 下三层契约的版本化变更（rules-3 §六）。

## 格式

```
## [版本号] - YYYY-MM-DD

### 变更类型（MAJOR/MINOR/PATCH）
- **变更内容**：具体描述
- **变更原因**：为什么变更
- **影响范围**：受影响的模块/服务
- **变更来源**：s0201/s0601/人工
```

---

## [0.1.1] - 2026-08-14

### 配置契约描述同步（PATCH）
- **变更内容**：`config_template/env.schema.json` 的 `_sourceOfTruth.note` 与 `config_template/README.md`（Schema 清单行 + 配置体系现状第 4 条）中 F5-TTS/Orpheus TTS 环境变量描述更新为当前真实状态（`.env.example` 现仅含 LLM 推理服务 + CX-O-SERVER 连接变量组）。种子阶段，无字段增删。
- **变更原因**：spec `unify-qwen3-tts-migration` Task 7 已移除 F5-TTS/Orpheus 运行时与配置（`.env.example` 同步删除旧组），但 `public/` 契约描述未随迁移同步，属过期描述。GN-004 交付前审查观察项 ③，走 s0601 契约变更适配流程，人类已显式授权更新（AskUserQuestion 2026-08-14）。
- **影响范围**：仅描述文本（PATCH），无字段/签名/默认值变化，不影响任何下游模块。env.schema.json 仍为种子占位（`_seedStage: true`、`properties` 空），完整 Schema 待 s0201 承接。
- **变更来源**：s0601

### 闭合判据
- [x] env.schema.json 与 README 描述已同步为当前真实状态
- [x] 全仓 grep 确认无旧引擎（F5-TTS/Orpheus）env 变量描述残留（public/ 内）

---

## [Unreleased]

### 初始化
- **版本**：0.1.0（种子阶段）
- **日期**：2026-07-02
- **变更内容**：public/ 三层契约骨架初始化，创建 7 子目录 + 种子文件
- **变更原因**：AC v6 治理层对齐（用户裁决 Option B），建立跨服务公共真相源
- **影响范围**：APP-Frontend / CX-O-SERVER / CX-O-VoiceWorkStation
- **当前状态**：种子文件仅含源真理指针，完整 Schema 待 s0201 承接
- **契约可验证性**：未闭合（测试套件 + rubric 待补）
