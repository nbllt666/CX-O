# DistillationService 蒸馏服务 E2E 测试报告

> spec `migrate-cxhms-radix-acp-multimodal` Task D5.1 产出。
> 测试时间: 2026-07-19 22:46:40
> 服务地址: http://127.0.0.1:8001
> 蒸馏 API: http://127.0.0.1:8001/api/v1/distillation

## 服务状态

| 探测项 | 状态 | 详情 |
|--------|------|------|
| CX-O-SERVER (8001) | OK | HTTP 200 |
| Distillation API 路由 | OK | 路由已注册（返回 404 = session 不存在，符合契约） |

## 场景汇总

- 场景总数: 5
- 通过: 5
- 失败: 0

## 场景详情

### [PASS] happy_path

**描述**: 完整 7 状态推进至 S_FINALIZE（覆盖状态机主路径）
**耗时**: 2179.33 ms

**状态流转路径**:

```
S_PREREAD -> S_QUESTION -> S_REFLECT -> S_CROSSVALIDATE -> S_EXTRACT -> S_STORAGE_DECISION -> S_FINALIZE
```

**agent_action 序列**:

```
proceed -> proceed -> proceed -> proceed -> proceed -> extract -> decide
```

**断言详情**:

| # | 断言 | 结果 |
|---|------|------|
| 1 | start 应返回 200，实际 200 | PASS |
| 2 | session_id 非空 | PASS |
| 3 | initial_state 应为 S_PREREAD，实际 S_PREREAD | PASS |
| 4 | preread_summary 应为非空字符串 | PASS |
| 5 | [step2] advance 后状态应为 S_QUESTION，实际 S_QUESTION | PASS |
| 6 | [step2] advance 后 agent_action 应为 proceed，实际 proceed | PASS |
| 7 | [step2] agent_action 应在合法枚举内，实际 proceed | PASS |
| 8 | [step2] next_needed 应为 bool，实际 bool | PASS |
| 9 | [step3] advance 后状态应为 S_REFLECT，实际 S_REFLECT | PASS |
| 10 | [step3] advance 后 agent_action 应为 proceed，实际 proceed | PASS |
| 11 | [step3] agent_action 应在合法枚举内，实际 proceed | PASS |
| 12 | [step3] next_needed 应为 bool，实际 bool | PASS |
| 13 | [step4] advance 后状态应为 S_CROSSVALIDATE，实际 S_CROSSVALIDATE | PASS |
| 14 | [step4] advance 后 agent_action 应为 proceed，实际 proceed | PASS |
| 15 | [step4] agent_action 应在合法枚举内，实际 proceed | PASS |
| 16 | [step4] next_needed 应为 bool，实际 bool | PASS |
| 17 | [step5] advance 后状态应为 S_EXTRACT，实际 S_EXTRACT | PASS |
| 18 | [step5] agent_action 应在合法枚举内，实际 proceed | PASS |
| 19 | [step5] next_needed 应为 bool，实际 bool | PASS |
| 20 | [step6] advance 后状态应为 S_STORAGE_DECISION，实际 S_STORAGE_DECISION | PASS |
| 21 | [step6] advance 后 agent_action 应为 extract，实际 extract | PASS |
| 22 | [step6] agent_action 应在合法枚举内，实际 extract | PASS |
| 23 | [step6] next_needed 应为 bool，实际 bool | PASS |
| 24 | [step7] advance 后状态应为 S_FINALIZE，实际 S_FINALIZE | PASS |
| 25 | [step7] advance 后 agent_action 应为 decide，实际 decide | PASS |
| 26 | [step7] agent_action 应在合法枚举内，实际 decide | PASS |
| 27 | [step7] next_needed 应为 bool，实际 bool | PASS |
| 28 | finalize 应返回 200，实际 200 | PASS |
| 29 | stored 应为 True（已存储），实际 True | PASS |
| 30 | location 应为 memories/permanent_memories，实际 permanent_memories | PASS |
| 31 | get_session_status 应返回 200，实际 200 | PASS |
| 32 | is_finalized 应为 True，实际 True | PASS |
| 33 | state 应为 S_FINALIZE，实际 S_FINALIZE | PASS |
| 34 | finalized_at 应非空 | PASS |
| 35 | quality_score 应已计算 | PASS |

### [PASS] reflect_question_loop

**描述**: S_REFLECT → S_QUESTION 回环（D4_REDISTILL 决策驱动）
**耗时**: 440.29 ms

**状态流转路径**:

```
S_PREREAD -> S_QUESTION -> S_REFLECT -> S_QUESTION
```

**agent_action 序列**:

```
proceed -> proceed -> proceed -> reflect
```

**断言详情**:

| # | 断言 | 结果 |
|---|------|------|
| 1 | start 应返回 200，实际 200 | PASS |
| 2 | [to_question] advance 后状态应为 S_QUESTION，实际 S_QUESTION | PASS |
| 3 | [to_question] advance 后 agent_action 应为 proceed，实际 proceed | PASS |
| 4 | [to_question] agent_action 应在合法枚举内，实际 proceed | PASS |
| 5 | [to_question] next_needed 应为 bool，实际 bool | PASS |
| 6 | [to_reflect] advance 后状态应为 S_REFLECT，实际 S_REFLECT | PASS |
| 7 | [to_reflect] advance 后 agent_action 应为 proceed，实际 proceed | PASS |
| 8 | [to_reflect] agent_action 应在合法枚举内，实际 proceed | PASS |
| 9 | [to_reflect] next_needed 应为 bool，实际 bool | PASS |
| 10 | [loop_back] advance 后状态应为 S_QUESTION，实际 S_QUESTION | PASS |
| 11 | [loop_back] advance 后 agent_action 应为 reflect，实际 reflect | PASS |
| 12 | [loop_back] agent_action 应在合法枚举内，实际 reflect | PASS |
| 13 | [loop_back] next_needed 应为 bool，实际 bool | PASS |
| 14 | get_session_status 应返回 200，实际 200 | PASS |
| 15 | turns 中应至少有 1 条 reflect-action 的 S_QUESTION 记录，实际 1 | PASS |
| 16 | 回环后会话不应终结 | PASS |

### [PASS] reject_branch

**描述**: S_REJECT 分支（人类 override_decision=reject 强制拒绝存储）
**耗时**: 1593.71 ms

**状态流转路径**:

```
S_PREREAD -> S_QUESTION -> S_REFLECT -> S_CROSSVALIDATE -> S_EXTRACT -> S_STORAGE_DECISION
```

**agent_action 序列**:

```
proceed -> proceed -> proceed -> proceed -> proceed -> extract
```

**断言详情**:

| # | 断言 | 结果 |
|---|------|------|
| 1 | start 应返回 200，实际 200 | PASS |
| 2 | [to_question] advance 后状态应为 S_QUESTION，实际 S_QUESTION | PASS |
| 3 | [to_question] advance 后 agent_action 应为 proceed，实际 proceed | PASS |
| 4 | [to_question] agent_action 应在合法枚举内，实际 proceed | PASS |
| 5 | [to_question] next_needed 应为 bool，实际 bool | PASS |
| 6 | [to_reflect] advance 后状态应为 S_REFLECT，实际 S_REFLECT | PASS |
| 7 | [to_reflect] advance 后 agent_action 应为 proceed，实际 proceed | PASS |
| 8 | [to_reflect] agent_action 应在合法枚举内，实际 proceed | PASS |
| 9 | [to_reflect] next_needed 应为 bool，实际 bool | PASS |
| 10 | [to_crossvalidate] advance 后状态应为 S_CROSSVALIDATE，实际 S_CROSSVALIDATE | PASS |
| 11 | [to_crossvalidate] advance 后 agent_action 应为 proceed，实际 proceed | PASS |
| 12 | [to_crossvalidate] agent_action 应在合法枚举内，实际 proceed | PASS |
| 13 | [to_crossvalidate] next_needed 应为 bool，实际 bool | PASS |
| 14 | [to_extract] advance 后状态应为 S_EXTRACT，实际 S_EXTRACT | PASS |
| 15 | [to_extract] agent_action 应在合法枚举内，实际 proceed | PASS |
| 16 | [to_extract] next_needed 应为 bool，实际 bool | PASS |
| 17 | [to_storage_decision] advance 后状态应为 S_STORAGE_DECISION，实际 S_STORAGE_DECISION | PASS |
| 18 | [to_storage_decision] advance 后 agent_action 应为 extract，实际 extract | PASS |
| 19 | [to_storage_decision] agent_action 应在合法枚举内，实际 extract | PASS |
| 20 | [to_storage_decision] next_needed 应为 bool，实际 bool | PASS |
| 21 | finalize(override=reject) 应返回 200，实际 200 | PASS |
| 22 | stored 应为 False（拒绝存储），实际 False | PASS |
| 23 | location 应为 'rejected'，实际 rejected | PASS |
| 24 | memory_id 应为 None（拒绝时不分配），实际 None | PASS |
| 25 | reason 应为非空字符串 | PASS |
| 26 | get_session_status 应返回 200，实际 200 | PASS |
| 27 | state 应为 S_REJECT，实际 S_REJECT | PASS |
| 28 | is_finalized 应为 True（S_REJECT 为终态），实际 True | PASS |
| 29 | finalized_at 应非空（已终结） | PASS |
| 30 | 已终结会话 advance 应返回 409，实际 409 | PASS |

### [PASS] natural_reject

**描述**: 自然 S_REJECT 触发（OBS-6 方案 C：LLM 质量评估低质内容）
**耗时**: 1522.51 ms

**状态流转路径**:

```
S_PREREAD -> S_QUESTION -> S_REFLECT -> S_CROSSVALIDATE -> S_EXTRACT -> S_STORAGE_DECISION -> S_REJECT
```

**agent_action 序列**:

```
proceed -> proceed -> proceed -> proceed -> proceed -> extract -> reject
```

**断言详情**:

| # | 断言 | 结果 |
|---|------|------|
| 1 | start 应返回 200，实际 200 | PASS |
| 2 | [to_question] advance 后状态应为 S_QUESTION，实际 S_QUESTION | PASS |
| 3 | [to_question] advance 后 agent_action 应为 proceed，实际 proceed | PASS |
| 4 | [to_question] agent_action 应在合法枚举内，实际 proceed | PASS |
| 5 | [to_question] next_needed 应为 bool，实际 bool | PASS |
| 6 | [to_reflect] advance 后状态应为 S_REFLECT，实际 S_REFLECT | PASS |
| 7 | [to_reflect] advance 后 agent_action 应为 proceed，实际 proceed | PASS |
| 8 | [to_reflect] agent_action 应在合法枚举内，实际 proceed | PASS |
| 9 | [to_reflect] next_needed 应为 bool，实际 bool | PASS |
| 10 | [to_crossvalidate] advance 后状态应为 S_CROSSVALIDATE，实际 S_CROSSVALIDATE | PASS |
| 11 | [to_crossvalidate] advance 后 agent_action 应为 proceed，实际 proceed | PASS |
| 12 | [to_crossvalidate] agent_action 应在合法枚举内，实际 proceed | PASS |
| 13 | [to_crossvalidate] next_needed 应为 bool，实际 bool | PASS |
| 14 | [to_extract] advance 后状态应为 S_EXTRACT，实际 S_EXTRACT | PASS |
| 15 | [to_extract] agent_action 应在合法枚举内，实际 proceed | PASS |
| 16 | [to_extract] next_needed 应为 bool，实际 bool | PASS |
| 17 | [to_storage_decision] advance 后状态应为 S_STORAGE_DECISION，实际 S_STORAGE_DECISION | PASS |
| 18 | [to_storage_decision] advance 后 agent_action 应为 extract，实际 extract | PASS |
| 19 | [to_storage_decision] agent_action 应在合法枚举内，实际 extract | PASS |
| 20 | [to_storage_decision] next_needed 应为 bool，实际 bool | PASS |
| 21 | advance 应返回 200，实际 200 | PASS |
| 22 | quality_score 应非 None（S_STORAGE_DECISION 后必填），实际 0.1 | PASS |
| 23 | quality_score 应为 float 0.0-1.0，实际 0.1（type=float） | PASS |
| 24 | 状态应转移至 S_REJECT 或 S_FINALIZE，实际 S_REJECT | PASS |
| 25 | S_REJECT 时 agent_action 应为 'reject'，实际 reject | PASS |
| 26 | S_REJECT 时 quality_score 应 < 0.3（reject_threshold 默认值），实际 0.1 | PASS |

### [PASS] multimodal_input

**描述**: 多模态 artifact 输入（character_card/image/video/audio）
**耗时**: 855.54 ms

**状态流转路径**:

```
character_card:S_PREREAD -> image:S_PREREAD -> video:S_PREREAD -> audio:S_PREREAD
```

**agent_action 序列**:

```
proceed -> proceed -> proceed -> proceed
```

**断言详情**:

| # | 断言 | 结果 |
|---|------|------|
| 1 | source_type=character_card start 应返回 200，实际 200 | PASS |
| 2 | character_card session_id 非空 | PASS |
| 3 | character_card initial_state 应为 S_PREREAD，实际 S_PREREAD | PASS |
| 4 | character_card preread_summary 应为非空字符串 | PASS |
| 5 | character_card preread_summary 应包含 source_type 标识 | PASS |
| 6 | character_card get_session_status 应返回 200，实际 200 | PASS |
| 7 | character_card ambiguity_questions 应非空 | PASS |
| 8 | character_card ambiguity_questions 应包含关键词 ['角色卡']，实际匹配 ['角色卡'] | PASS |
| 9 | source_type 字段应为 character_card | PASS |
| 10 | source_type=image start 应返回 200，实际 200 | PASS |
| 11 | image session_id 非空 | PASS |
| 12 | image initial_state 应为 S_PREREAD，实际 S_PREREAD | PASS |
| 13 | image preread_summary 应为非空字符串 | PASS |
| 14 | image preread_summary 应包含 source_type 标识 | PASS |
| 15 | image get_session_status 应返回 200，实际 200 | PASS |
| 16 | image ambiguity_questions 应非空 | PASS |
| 17 | image ambiguity_questions 应包含关键词 ['OCR', '视觉']，实际匹配 ['OCR', '视觉'] | PASS |
| 18 | source_type 字段应为 image | PASS |
| 19 | source_type=video start 应返回 200，实际 200 | PASS |
| 20 | video session_id 非空 | PASS |
| 21 | video initial_state 应为 S_PREREAD，实际 S_PREREAD | PASS |
| 22 | video preread_summary 应为非空字符串 | PASS |
| 23 | video preread_summary 应包含 source_type 标识 | PASS |
| 24 | video get_session_status 应返回 200，实际 200 | PASS |
| 25 | video ambiguity_questions 应非空 | PASS |
| 26 | video ambiguity_questions 应包含关键词 ['视频', '关键帧']，实际匹配 ['视频', '关键帧'] | PASS |
| 27 | source_type 字段应为 video | PASS |
| 28 | source_type=audio start 应返回 200，实际 200 | PASS |
| 29 | audio session_id 非空 | PASS |
| 30 | audio initial_state 应为 S_PREREAD，实际 S_PREREAD | PASS |
| 31 | audio preread_summary 应为非空字符串 | PASS |
| 32 | audio preread_summary 应包含 source_type 标识 | PASS |
| 33 | audio get_session_status 应返回 200，实际 200 | PASS |
| 34 | audio ambiguity_questions 应非空 | PASS |
| 35 | audio ambiguity_questions 应包含关键词 ['音频', '转录']，实际匹配 ['音频', '转录'] | PASS |
| 36 | source_type 字段应为 audio | PASS |

## 总体结论

所有场景通过，蒸馏服务 9 状态机推进符合契约预期。

---
**报告生成时间**: 2026-07-19 22:46:40
**退出码**: 0 (PASS)