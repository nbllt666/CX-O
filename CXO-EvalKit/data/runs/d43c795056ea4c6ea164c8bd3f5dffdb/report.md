# CXO-EvalKit 评测报告

| 字段 | 值 |
|------|-----|
| run_id | d43c795056ea4c6ea164c8bd3f5dffdb |
| suite | memory_decay |
| status | error |
| 开始时间 | 2026-09-12 12:00:50 UTC |
| 结束时间 | 2026-09-12 12:02:27 UTC |
| 时长 | 1m36s |

## 一、指标实测值

### 保持率矩阵（分层 × 时间间隔）

（无数据）

### 检索命中率

| 检索方式 |
|------|
| search |  |
| rag |  |

### 劣化曲线单调性

无单调性违反

## 二、阈值逐项判定

| 检查项 | 实测值 | 阈值 | 判定 |
|------|--------|------|------|
| 永久记忆保持率 | — | ≥ 1.0 | —（本 suite 无此指标） |
| 1年 overall 保持率 | — | ≥ 0.6 | —（本 suite 无此指标） |
| 再激活组保持率 > 对照组 | — | True | —（本 suite 无此指标） |
| 总体 P95 | — | ≤ 2000 ms | —（本 suite 无此指标） |
| 基线 P95 回归幅度 | — | ≤ +20% | —（本 suite 无此指标） |
| 首结果→首包 P95（全双工） | — | ≤ 800 ms | —（本 suite 无此指标） |
| 三维综合均分 | — | ≥ 3.5 | —（本 suite 无此指标） |

## 三、异常项清单

- run error：HTTP 403: {"success":false,"error":"Invalid API key","error_code":"HTTP_403","details":null,"timestamp":"2026-09-12T20:01:49.662273"}
Traceback (most recent call last):
  File "C:\CX-O\CXO-EvalKit\evalkit\suites\memory_decay.py", line 509, in run_memory_decay
    _run_scenario(
    ~~~~~~~~~~~~~^
        scenario, client, judge, agent_id, config, run_state, detail,
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
        retention_acc, retrieval_acc, react_acc,
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    )
    ^
  File "C:\CX-O\CXO-EvalKit\evalkit\suites\memory_decay.py", line 417, in _run_scenario
    _run_decay_flow(
    ~~~~~~~~~~~~~~~^
        client, judge, agent_id, config, run_state, record, seeds, seed_map, questions,
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
        retention_acc, retrieval_acc,
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    )
    ^
  File "C:\CX-O\CXO-EvalKit\evalkit\suites\memory_decay.py", line 296, in _run_decay_flow
    _time_travel_safe(client, agent_id, shift, record)
    ~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\CX-O\CXO-EvalKit\evalkit\suites\memory_decay.py", line 162, in _time_travel_safe
    client.time_travel(agent_id, shift_days)
    ~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^
  File "C:\CX-O\CXO-EvalKit\evalkit\target.py", line 248, in time_travel
    return self._unwrap(
           ~~~~~~~~~~~~^
        c.post(
        ^^^^^^^
            "/api/memories/eval/time-travel", json=body, headers=self._admin_headers()
            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
        )
        ^
    )
    ^
  File "C:\CX-O\CXO-EvalKit\evalkit\target.py", line 63, in _unwrap
    raise TargetHttpError(resp.status_code, str(detail))
evalkit.target.TargetHttpError: HTTP 403: {"success":false,"error":"Invalid API key","error_code":"HTTP_403","details":null,"timestamp":"2026-09-12T20:01:49.662273"}
