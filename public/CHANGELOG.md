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

## [0.2.0] - 2026-08-30

### 契约修复批次（MINOR，含 PATCH 项）
- **变更内容**：第十五轮 G4 契约批次——①`interface_stub/template_engine.pyi` v1.0.2（PATCH）：清理 docstring 残留悬空 schema 引用改指实现位置（连带 `pre_generated_mock/mock_template_engine.py` 5 处注释与 `pre_generated_mock/README.md` 表格行同步）；②`config_template/settings_json.schema.json` 1.0.1（PATCH）：`_sourceOfTruth.primary` 改指实际加载点 `CX-O-SERVER/config/settings.json`，note 补 `adaptive_polling` 子段；③`config_template/default_yaml.schema.json` 1.0.1（PATCH）：指针改指实现 `server/config.py`（UnifiedConfig），加注源已并入、契约待 s0201 重建；④`config_template/radix_config.json` 1.2.0（MINOR）：`decision_core` 补 `rubric_path`/`audit_log_path`、根级补 `legacy_port`（对齐 `server/config.py` 默认值，纯新增带默认值不阻断）；⑤`interface_stub/memory.pyi` 1.1.1（PATCH）：update_memory/delete_memory/rag_search 三处签名对齐实现（修正 str 笔误）；⑥删除零代码引用孤儿副本 `CX-O-SERVER/server/config/settings.json`（删除前 SHA256 与真源一致）。
- **变更原因**：第十五轮质量评估 G4 批次修复，实现为源真理；public/ 修改与孤儿副本删除已获人类显式授权（AskUserQuestion 2026-08-30"四批全修+删除孤儿副本"）。
- **影响范围**：注释/指针级修正与纯新增可选字段，无字段删除/类型变更/必填性反转，不阻断既有下游；memory.pyi 签名修正无运行时影响（实现自始如此）。
- **变更来源**：人工（人类显式授权，AskUserQuestion 2026-08-30）

### 闭合判据
- [x] 7 份契约/Mock/README 实体修订 + 1 份孤儿副本删除（哈希核对通过）+ JSON/ast 语法自验通过
- [x] 详细记录见 `public/schema/CHANGELOG.md` [1.11.0] 同日条目

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
