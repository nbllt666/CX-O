---
session_id: project-health-audit
status: CLOSED
closed_at: 2026-08-27
final_evidence: "后端 pytest 4240 passed / 0 failed (168.38s, audit_backend_pytest.log)；前端 vitest 606/606 + typecheck 0 错误"
---

# 项目健康审计调试记录

## 工程过程
1. 已建立运行时调试会话，提出 5 个可证伪假设（见下）。
2. 并行三向探查：架构/入口/测试配置子代理 ×2 + 技术债扫描（s0602）。
3. 主线程对全部高危候选做代码级复核与交叉验证（否决误报 B3）。
4. 按 rules-6 先写变更文档 → 分批修复 A1-A5/B1/B2/B4/B5/C1-C3/D1/D2/E1（详见 `.trae/documents/20260827_模块0_全项目体检问题修复.md`）。
5. 回归验证：前端 vitest 606/606 PASS + typecheck 0 错误（含既有 electron/main.ts 类型错误修复）；后端全量 pytest 执行中。

## 交接状态
- 当前 Task/Check：后端全量回归收尾 → GN-004 审查 → [V] 人类裁决
- 状态：进行中

## 初始假设 vs 裁定
| # | 假设 | 裁定 |
|---|------|------|
| 1 | 测试入口/依赖漂移致假通过 | ✅ **坐实**：py311 venv 缺 pytest-asyncio（requirements.txt 从未声明），14 个 asyncio 用例静默失败；CI 指向已删除目录；E2E 端口约定漂移(8000/8001)。已修 requirements/CI/start.bat |
| 2 | 核心路径边界/异常/状态缺陷可复现 | ✅ 坐实并修复：stop_service 自杀开关、config 非原子写、坏 env 变量炸启动、异常信息外泄、SSE 不可停、alarm 定时器错乱、轮询泄漏、SSRF fail-open 等 |
| 3 | 重复实现/废弃入口/隐式耦合 | ⚠️ 部分坐实（chroma/milvus 死文件+永不生效分支、useConfigReload 平行实现、ConnectionSetup 双入口）；破坏性删除留 [V] 裁决；B3"任务未追踪"为**误报**被交叉验证否决 |
| 4 | 路径/配置/Mock 不符契约 | 部分：ASR 容器 Linux 绝对路径硬编码、settings.json 漂移键（留 backlog）；主链 config.json 已收敛原子写 |
| 5 | 文档与代码不一致 | ✅ 坐实：README 一键启动引用缺失 start.bat；dispatch.ts 过时代理注释；此前多轮修复文档声称已闭合的若干点与当前代码不符（以本轮代码为准） |

## 教训（复用价值）
- 子代理静态结论必须逐条复核后再动刀——本轮 B3 整批候选均为误报。
- 同批次并行编辑同一文件存在互相覆盖风险——该文件后续一律串行编辑。
- venv 与依赖清单必须双向核对，"collect 成功 ≠ 用例真执行"。

## 未闭合项
- ~~后端全量 pytest 终值待落盘~~ → 已落盘：4240 passed / 0 failed（audit_backend_pytest.log，E3 挂点修复后全量收敛）
- 待裁决观察项见变更文档（死代码删除 / discovery 鉴权 / CORS 收紧 / backlog 设计债）——已随 [V] 提交人类裁决

## 接续入口
- GN-004 审查已完成：**警示放行（无 SOFT_BLOCK，O1 已顺手修复/O2 口径偏差不影响结论/O3 间接佐证披露）**
- [V] AskUserQuestion 已提交：终局裁决 + 观察项治理意向
