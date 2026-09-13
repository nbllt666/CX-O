# CXO-EvalKit 部署指南

> CXO-EvalKit 是 CX-O 的 LLM 评测框架：对主服务（CX-O-SERVER）执行记忆衰减 / 延迟 / 对话质量三维度自动化评测，产出带阈值判定的 Markdown 报告。

## 一、环境要求

- Python 3.11+（本地运行）；或 Docker + Docker Compose（容器部署）
- 被测主服务 CX-O-SERVER 已启动（默认 `http://localhost:8000`）；Mock 模式可脱离主服务跑通全链路

## 二、本地运行

```bash
cd CXO-EvalKit
pip install -r requirements.txt
uvicorn evalkit.api:app --host 0.0.0.0 --port 8300
```

## 三、Docker 部署

```bash
# 在仓库根目录执行（profile 门控，裸 up 不会启动）
docker compose --profile eval up cxo-evalkit
```

- 宿主端口默认 **8320**（环境变量 `CXO_EVALKIT_PORT` 可覆盖），容器内 8300
- 数据卷挂载 `./data/evalkit → /app/data`（SQLite 库 + run 目录均落于此）

## 四、配置说明（config.json）

复制 `config.example.json` 为 `config.json` 后按需修改（config.json 已被 .gitignore 忽略，API key 只存本地）：

| 配置节 | 关键字段 | 说明 |
|--------|---------|------|
| `target` | `base_url` | 被测主服务地址；Docker 内默认 `http://host.docker.internal:8000` |
| `target` | `admin_api_key` | 调主服务 admin 端点用；从主服务 `config.json` 获取；不入报告不入库 |
| `judge` | `api_base` / `model` / `api_key` | LLM-as-judge（OpenAI 兼容 chat/completions）；`api_base` 留空跟随 target 同源 |
| `mock` | `enabled` | `true` 时接内置 stub target + stub judge，无需真实主服务与 LLM 即可跑通 |
| `thresholds.memory` | `retention_1y_min=0.6` / `permanent_retention=1.0` / `reactivation_must_beat_control=true` | 记忆维度通过阈值 |
| `thresholds.latency` | `p95_ms=2000` / `regression_pct=20` / `ws_p95_ms=800` | 延迟维度通过阈值（ws_p95_ms 为全双工主指标阈值） |
| `thresholds.quality` | `avg_min=3.5` | 质量均分通过阈值 |
| `memory_decay` | `interval_days=[30,180,365,1095]` | 衰减探针时间轴（1月/6月/1年/3年） |
| `latency` | `rounds` / `concurrency_levels` / `baseline_run_id` / `ws_full_duplex` | 探针轮数、并发档位、基线 run（对比回归）、全双工语音探测（`enabled`/`turns`/`utterance_wav`/`frame_ms`/`turn_timeout_seconds`/`real_time_pacing`） |

## 五、触发评测

```bash
# 记忆衰减（默认 8320 宿主端口；本地 uvicorn 模式换成 8300）
curl -X POST http://localhost:8320/api/v1/runs \
  -H "Content-Type: application/json" \
  -d '{"suite": "memory_decay"}'

# 延迟评测
curl -X POST http://localhost:8320/api/v1/runs -H "Content-Type: application/json" -d '{"suite": "latency"}'

# 质量评测
curl -X POST http://localhost:8320/api/v1/runs -H "Content-Type: application/json" -d '{"suite": "quality"}'

# 查看 run 列表 / 详情
curl http://localhost:8320/api/v1/runs
curl http://localhost:8320/api/v1/runs/{run_id}
```

三个 suite 一句话说明：

- **memory_decay**：种入记忆后沿 1月→6月→1年→3年时间轴回拨时钟，检验长期记忆保持率、检索命中率、单调性与"按月重访再激活"是否优于自然衰减
- **latency**：固定探针集测 E2E 对话 / 记忆检索 / 并发档位延迟分位数，可与历史基线 run 对比回归幅度；**全双工模式（默认开启）**经 WS `voice.dual_stream` 实时节奏发送 16k PCM 语音帧，探测音频流→ASR→LLM→TTS 全链路，主指标 = 容器流式分句定稿（asr_final）→ 首包 TTS 音频的 P95（阈值 800ms，服务端 VAD 不参与判定）。真实模式需主服务、ASR 容器（8005）与 TTS 运行时（CosyVoice3 8094）在线
- **quality**：回放陪伴语境对话脚本，judge 从记忆准确、人设一致、连贯性三维打 1-5 分

## 六、拉取报告

```bash
curl http://localhost:8320/api/v1/runs/{run_id}/report
```

run 到达终态（passed / failed / judge_unavailable / error）即可拉取 `text/markdown` 报告；报告为三段式：指标实测值 → 阈值逐项判定（✅/❌）→ 异常项清单。也可直接打开文件 `{data_dir}/runs/{run_id}/report.md`。

## 七、真实模式对接步骤

1. 启动主服务 CX-O-SERVER（端口 8000）
2. 在 `CXO-EvalKit/config.json` 填入 `target.base_url` 与 `admin_api_key`（从主服务 config 获取）、`judge` 三项
3. 确认 `mock.enabled=false`，触发 run（见第五节）
4. 轮询 `GET /api/v1/runs/{run_id}` 至终态，拉取报告（见第六节）

## 八、时间旅行端点安全提示

memory_decay suite 依赖主服务的 time travel（时间回拨）端点，该端点受 **admin api key 门控**，仅供评测专用 agent（`eval-agent-{run_id}`，suite 自动创建与清理）使用——它会真实改写目标 agent 的记忆时间轴，**严禁对日常使用中的 agent 调用**。评测 agent 在 run 结束后会被物理清理，不影响其他数据。
