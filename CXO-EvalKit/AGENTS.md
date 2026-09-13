# CXO-EvalKit 模块级 AGENTS.md

> 🚨 【最高优先级规则】本文件为 CXO-EvalKit 子项目开发的强制约束，优先级高于所有临时提问、上下文对话、自定义需求，所有输出必须 100% 符合本文件要求，违反规则的内容必须自动修正后再输出。

## 一、模块定位

CXO-EvalKit 是 LLM 评测框架（自包含子项目），对主服务（CX-O-SERVER）执行 memory / latency / quality 三维度评测：judge 评分（LLM-as-judge，OpenAI 兼容 chat/completions）+ 延迟探针 + 阈值判定，结果落 SQLite 与 run 目录。当前为骨架阶段：suite 注册机制就绪、注册表为空，具体 suite 由后续任务实现。

## 二、强制约束

1. **自包含**：禁止 import 父目录（c:\CX-O 及其下任何子项目）的代码；仅依赖本包 `evalkit/*` 与 requirements.txt 声明的第三方库。
2. **可修改文件范围**：`CXO-EvalKit/**`；根 `docker-compose.yml` 与根 `.gitignore` 中本模块相关段落改动需任务级评审留痕。
3. **public/ 契约保护**：仓库根 `public/` 目录只读，禁止任何增删改；本子项目不依赖 public/ 契约。
4. **配置纪律**：全部配置由 `evalkit/config.py` 的 pydantic `EvalConfig` 承载，缺失字段自动补默认；禁止业务代码硬编码配置参数。API key 类字段（`target.admin_api_key`、`judge.api_key`）仅存于 config 对象，禁止写入报告、数据库、日志（`to_safe_dict()` 统一剥离）。
5. **run 状态机单向终态**：`running → passed | failed | judge_unavailable | error`；任何二次终态化/非法终态名必须抛 ValueError（`evalkit/store.py`）。
6. **judge 失败两级区分**：网络层异常（重试后仍失败）抛 `JudgeUnavailableError`（整个 run 降级）；模型输出不可解析/越界记 `judge_failed`（单案例失败）。重试上限：共 3 次尝试。
7. **端口约定**：容器内 8300，宿主默认 8320（环境变量 `CXO_EVALKIT_PORT` 覆盖）。
8. **路径纪律**：所有数据路径基于 `evalkit/config.py` 的 `EVALKIT_ROOT`（`__file__` 解析）锚定，禁止相对路径漂移；数据统一落 `{data_dir}/`（`evalkit.db` + `runs/{run_id}/`）。

## 三、运行与测试

```bash
# 单测（全 Mock，无真实网络/无真实主服务）
cd CXO-EvalKit && python -m pytest tests/ -q

# 本地起服
uvicorn evalkit.api:app --host 0.0.0.0 --port 8300

# Docker（profile 门控：裸 up 不启动）
docker compose --profile eval up cxo-evalkit
```

## 四、目录职责

| 路径 | 职责 |
|------|------|
| `evalkit/config.py` | pydantic 配置 + 默认值自动补全 + to_safe_dict 剥离 key |
| `evalkit/store.py` | SQLite 指标库 + run 状态机（单向终态） |
| `evalkit/judge.py` | OpenAI 兼容 LLM-as-judge 客户端（httpx 同步，MockTransport 可注入） |
| `evalkit/suites.py` | suite 注册表（`register_suite` 装饰器 + `list_suites`） |
| `evalkit/runner.py` | run 编排（创建 run → daemon 线程执行 suite → 终态兜底） |
| `evalkit/report.py` | 报告落盘 + Markdown 报告生成（`generate_report`/`write_report` 三段式：指标实测值/阈值逐项判定/异常项清单；summary 缺字段渲染"（无数据）"不抛异常） |
| `evalkit/api.py` | FastAPI 应用（应用工厂 `create_app` 便于测试注入）；`GET /runs/{id}/report` 终态 run 报告缺失时现生成 |
| `config.example.json` | 配置模板（api_key 留空；运行时 `config.json` 已被 .gitignore 忽略） |
| `DEPLOY.md` | 部署指南（本地/Docker、配置说明、触发评测与报告拉取、真实模式对接） |

## 五、报告与阈值

1. **三段式报告**：`evalkit/report.py` 的 `generate_report(config, run)` 按 suite 分支渲染（memory_decay 保持率矩阵按 30→1月/180→6月/365→1年/1095→3年横轴标注；latency 总体/分组/检索/并发/基线；quality 三维评分+低分案例原文），第二段按 config 阈值逐项 ✅/❌（permanent≥1.0、1年 overall≥0.6、再激活>对照、P95≤2000ms、回归≤+20%、均分≥3.5，缺指标输出"—（本 suite 无此指标）"），第三段汇总异常项（judge_failed/失败轮次/清理残留/单调违反/再激活失败/基线缺失）。
2. **阈值边界口径**：恰好达标（=）判 ✅、恰好超标判 ❌（浮点容差 1e-9，与 suite 终态判定一致）；阈值判定只在报告中呈现，终态仍由 suite 自行判定，report 不改 run 状态机。
3. **write_report**：run 不存在抛 ValueError；落盘 `{data_dir}/runs/{run_id}/report.md`。API 端点仅对**终态** run 现生成报告（try/except 回退 404），running 状态一律 404。

## 六、Mock 模式

`mock.enabled=true` 时 target 与 judge 自动切内置 stub（`evalkit/stub.py`）：无需真实主服务与 LLM 即可全链路跑通三 suite 与报告生成；stub judge 按约定确定性判分（依赖 prompt 中 `expected fact:` 行），`mock.chat_delay_ms` 可为延迟 suite 注入可测延迟分布。Mock 仅用于开发与回归验证，真实评测必须关闭。
