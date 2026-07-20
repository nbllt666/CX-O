# DistillationService 蒸馏服务 E2E 测试报告

> spec `migrate-cxhms-radix-acp-multimodal` Task D5.1 产出。
> 测试时间: 2026-07-19 22:35:06
> 服务地址: http://127.0.0.1:8001
> 蒸馏 API: http://127.0.0.1:8001/api/v1/distillation

## 服务状态

| 探测项 | 状态 | 详情 |
|--------|------|------|
| CX-O-SERVER (8001) | OK | HTTP 200 |
| Distillation API 路由 | OK | 路由已注册（返回 404 = session 不存在，符合契约） |

## 场景汇总

- 场景总数: 5
- 通过: 0
- 失败: 5

## 场景详情

### [FAIL] happy_path

**描述**: 完整 7 状态推进至 S_FINALIZE（覆盖状态机主路径）
**耗时**: 17.19 ms
**错误**: 断言失败: start 应返回 200，实际 422

**断言详情**:

| # | 断言 | 结果 |
|---|------|------|
| 1 | start 应返回 200，实际 422 | FAIL |

### [FAIL] reflect_question_loop

**描述**: S_REFLECT → S_QUESTION 回环（D4_REDISTILL 决策驱动）
**耗时**: 5.52 ms
**错误**: 断言失败: start 应返回 200，实际 422

**断言详情**:

| # | 断言 | 结果 |
|---|------|------|
| 1 | start 应返回 200，实际 422 | FAIL |

### [FAIL] reject_branch

**描述**: S_REJECT 分支（人类 override_decision=reject 强制拒绝存储）
**耗时**: 5.08 ms
**错误**: 断言失败: start 应返回 200，实际 422

**断言详情**:

| # | 断言 | 结果 |
|---|------|------|
| 1 | start 应返回 200，实际 422 | FAIL |

### [FAIL] natural_reject

**描述**: 自然 S_REJECT 触发（OBS-6 方案 C：LLM 质量评估低质内容）
**耗时**: 4.94 ms
**错误**: 断言失败: start 应返回 200，实际 422

**断言详情**:

| # | 断言 | 结果 |
|---|------|------|
| 1 | start 应返回 200，实际 422 | FAIL |

### [FAIL] multimodal_input

**描述**: 多模态 artifact 输入（character_card/image/video/audio）
**耗时**: 426.59 ms
**错误**: 断言失败: source_type=character_card start 应返回 200，实际 422; 断言失败: source_type=image start 应返回 200，实际 422; 断言失败: source_type=video start 应返回 200，实际 422; 断言失败: source_type=audio start 应返回 200，实际 422

**断言详情**:

| # | 断言 | 结果 |
|---|------|------|
| 1 | source_type=character_card start 应返回 200，实际 422 | FAIL |
| 2 | source_type=image start 应返回 200，实际 422 | FAIL |
| 3 | source_type=video start 应返回 200，实际 422 | FAIL |
| 4 | source_type=audio start 应返回 200，实际 422 | FAIL |

## 总体结论

存在 5 个失败场景，需排查被测模块实现或契约差异。

---
**报告生成时间**: 2026-07-19 22:35:06
**退出码**: 1 (FAIL)