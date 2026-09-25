# Debug Session: dual-stream-post-final-stall

- **Status**: [OPEN]
- **Issue**: WS `voice.dual_stream` 全双工管线在 `asr_final` 之后间歇性多出 ~4~5.4 s 才产出首包 TTS 音频（~10~17% 轮次，随 uptime 上升到 42%）。已排除：ASR/LLM/TTS/嵌入/weaviate 引擎侧、全局事件循环阻塞（/health p95 5.3ms）、TTS 与 LLM 在停滞窗口均无请求。
- **Debug Server**: http://127.0.0.1:<port>/event （见 `.dbg/dual-stream-post-final-stall.env`）
- **Log File**: `.dbg/trae-debug-log-dual-stream-post-final-stall.ndjson`

## Reproduction Steps

1. 主服务在 8000（本次重启时分两种情况：pre-fix 带插桩重启）；
2. 用 EvalKit `FullDuplexProbe` 同口径连发 12 轮（每轮 9.45s 16k PCM，30ms 帧实时节奏）；
3. 记录每轮 `partial→首包` 耗时；停滞轮（>1500ms）与正常轮的同轮插桩日志对比；
4. 同步采 `/health`（判是否全局阻塞）与容器日志（判是否引擎侧）。

## Hypotheses & Verification

| ID | Hypothesis | Likelihood | Effort | Evidence |
|----|------------|------------|--------|----------|
| A | `retrieve_memory_context` 在部分轮等待 ~4s | High | Low | **Rejected**（37 轮插桩：检索 80~120ms，pre-LLM 阶段总计 ≤252ms，无一轮超过 260ms） |
| B | `build_messages` / `get_llm_client_for_agent` 阻塞 | Med | Low | **Rejected**（同上，build 段 ≤40ms） |
| C | `set_tts_playing` / `_build_tts_kwargs` / TTS 入口首步等待 | Med | Low | **Partially rejected**（P5 `pre_tts_loop` 稳定 ≤252ms） |
| D | 管线任务被"延迟启动/排队"（打断判定竞争） | Med | Low | **Rejected**（P1 进入即开始计时，P2 仅 3~83ms） |
| E | LLM 请求已创建但未真正发出/连接池等待 | Med | Med | **Partially confirmed**：全部变异落在 P5→P6 区间（gap 361.9~1858.7ms），即 LLM 首 token → 分句 → TTS 首块链 |
| **G（新）** | **LLM 引擎长步（超大 prefill）期间活体语音请求被拖住**：vLLM 日志出现 **20~180s 无 Engine 日志的间隔**，间隔后单条日志显示 `Avg prompt throughput 470 tok/s`（≈数万 prompt token 的单次 prefill）；主服务日志显示启动期 `prefix_warmup: 语音前缀预热 20/20 agent（最多 3 轮/agent，含 padding）` | High | Med | **Confirmed（间接）**：13:35–13:45 UTC 多次长间隔与两次服务重启后的前缀预热吻合；但**尚未把某一次具体轮次停滞与某一次长步在同一时刻对齐** |

### 插桩证据（runId=pre，37 轮 pipeline）

| 阶段 | 观测范围 | 结论 |
|------|----------|------|
| P1→P2 `get_agent_config` | 3.3~83.2 ms | 稳定 |
| P3 `retrieve_memory_context` | 80~120 ms（mem_before 6.4~99.4 → mem_after 86~217） | 稳定，**无停滞** |
| P4 `build_messages` | ≤40 ms | 稳定 |
| P5 `pre_tts_loop`（进入 TTS 前总耗时） | 93.2~251.7 ms | 稳定 |
| **P5→P6（gap，LLM→分句→TTS 首块）** | **361.9 ~ 1858.7 ms** | **全部变异在此** |

旗标轮（gap>1200ms）：`gap=1455.5`（第 8 轮）、`gap=1858.7`（第 29 轮）→ 均为"较慢但非 5.4s 停滞"。
插桩后重启的 37 轮内**未复现 5.4s 级停滞**（`partial→首包` 最大 2025.7ms），与"停滞率随 uptime 上升"（17%→25%→42%）一致。

### 关键旁证

- 插桩 run（`d76026f9…`，turns=9）：P95 = **981.6 ms**、max 1135.8 ms（fresh 服务，未达稳态 440~700ms 的低值区）；
- vLLM 引擎日志 25 分钟窗口内 **7 次 >12s 间隔**（最长 180s；间隔后单条 `prompt throughput 470.0 tok/s, Running: 1`）；
- 主服务启动日志：`语音前缀预热完成：20/20 个 agent（最多 3 轮/agent，含 prefix-cache padding）`
  → 20 agent × 3 轮的大 prefill 是目前最可疑的"引擎长步"来源（**待最终对齐**）。

## Verification Conclusion（post-fix）

修复内容 = 预热限流：活体让行 + 单轮上限 6 + 错峰 0.5 s + 单 agent 有界让行（`prefix_warmup.py`）。

| 指标 | pre | post | 结论 |
|------|-----|------|------|
| 预热期 vLLM 引擎长间隔 | 90~180 s | **≤30 s**（分批 6/20 → 12/20 → 18/20 → 20/20，共 4 轮） | ✅ 限流生效 |
| 预热完成语义 | 单次跑完 | 4 批走完 + `推理后端预热全部完成（共 4 轮）` | ✅ 游标推进无"永不完成"缺陷 |
| 插桩 gap（P5→P6） | n=37，max **1858.7** ms | n=9，max **951.9** ms（无 >1200 ms） | ✅ 尾部收窄约 2× |
| 正式 run（turns=9）ws P95 | 981.6 ms | **1109.8 ms**（阈值 800 ❌ / max 1121.4） | ⚠️ 仍未达标 |
| 连续探测停滞轮 | 5/12 级（旧服务） | **1/12（turn4 = 5181 ms）** | ⚠️ 5.4 s 级停滞仍可复现 |

### 新证据（post-fix 12 轮）

- `/health` 出现 **2 次 ~7.8~7.9 s 尖峰**（此前上限 2.05 s）→ 存在更长的全局事件循环阻塞；
- 同轮 turn8=1664.9 ms、turn9=1940.4 ms（"轻度变慢"档）。

### ⚠️ 插桩自身的测量扰动（必须记录）

插桩上报已由**同步 urlopen** 改为**队列 + 独立线程上报（非阻塞）**（debug-point P0，2026-09-25 22:1x 改造），
原因：原同步上报（timeout=0.5s ×≤7/轮）可注入 ~0.5~3.5 s 循环占用，
与 post-fix 观察到的部分尖峰/停滞可能自相关。

### 非阻塞化后的新测量（debug-point M：事件循环延迟监视，独立线程 + 线程栈快照）

| 测量 | 结果 |
|------|------|
| 12 轮连续探测（干净、无扰动） | **无停滞**（p→f 433.3 ~ 1096.2 ms，max 1096.2） |
| `/health` 并发 990 次 | 仅 1 次 2060 ms（turn0 窗口，监视器启动前，属 agent 创建窗口），其余 ≤8.6 ms |
| 循环监视 M 事件（lag>1s） | **0 次**（490 条插桩事件中无 M 命中） |
| 正式 run（turns=9，非阻塞插桩） | ws P95 = **1751.7 ms**（max 2004.1，P50 1035.1）❌ |

### 结论修订（截至 2026-09-25 22:3x）

1. **预热限流修复生效且无副作用**（引擎长间隔 90~180 s → ≤30 s；分批推进；在线让行）；
2. 移除同步上报扰动后，**12 轮干净探测内停滞未复现**、循环监视无 >1 s 阻塞命中
   → 早前 post-fix 的 1/12 停滞与 ~8 s 尖峰**至少部分归因于插桩自身扰动**；
3. 全双工 P95 仍随环境负载在 **1109.8 / 1751.7 ms** 间波动（阈值 800 ❌），
   稳定落在"LLM 首 token（prefill/TTFT）随混合负载抖动"这一档（EvalKit suite 自身的
   REST 阶段 21 次 4k-token 级 chat 与 WS 阶段相邻，属同机 GPU 竞争）；
   **该项非本次代码修复面（属 LLM 容量/调度特性），建议登记为独立观察项。**

## 结论（截至本记录）

### 🎯 根因（已定位并修复）：每次新建 httpx 客户端阻塞事件循环 ~8 s

| 证据 | 数值 |
|------|------|
| 循环监视 M 事件（独立线程 + 栈快照） | 捕获 4 次 lag **7.8~8.3 s**，栈中含 `ssl.create_default_context(cafile=certifi.where())` |
| 隔离实测（本机 py311） | `ssl.create_default_context` = **6074 ms**；`httpx.AsyncClient()` 构造 = **7979 ms** |
| 工程既有记录 | `server/core/utils.py:172-173` 注释已写明"仅 trust_env=False 仍耗时 7.8 s"；`api/routers/discovery.py:30` 已记录同类坑并改为共享客户端 |
| 触发源 | `RssFetcher.fetch()` **每次调用新建 `httpx.AsyncClient`**（自主系统/梦境引擎的新闻感知路径，循环 15 min 级 + 工具触发） |

**修复 2**：`rss_fetcher.py` 改为复用 `get_shared_http_client()`（构造一次、按事件循环隔离；超时/跟随重定向按请求传入）。

#### 修复 2 验证

| 测量 | 结果 |
|------|------|
| 子进程双次 fetch | fetch#1 = 7688 ms（一次性构造）；**fetch#2 = 2.7 ms**（不再每次构造） |
| 12 轮连续探测（修复后） | **无停滞**（p→f 441.2~1545.4 ms） |
| `/health` 并发 983 次 | max **2043.6 ms**（仅 agent 创建那次），**7.8~8.3 s 级尖峰消失**（修复前每轮 2 次） |
| LLM 每轮指标 | n=1~2 请求、2700~3200 prompt tokens、TTFT 70~505 ms、**前缀缓存命中 97.5~99.9%** |

### 累计交付

1. **修复 1（预热限流）**：`prefix_warmup.py` —— 引擎长间隔 90~180 s → ≤30 s、分批推进、在线让行；
2. **修复 2（新闻抓取客户端复用）**：`rss_fetcher.py` —— 消除每次抓取 ~8 s 事件循环阻塞（本轮停滞的**根因**）；
3. **未闭合**：agent 创建窗口仍有 1 次 ~2 s 循环占用（成因未定位，低频）；
   全双工 P95 在混合负载下仍可能 >800 ms（LLM 首 token 抖动，独立观察项）。

### 清理门（协议）

插桩（`audio.py` P0~P6 + M 监视器）、调试服务器、调试记录、`.dbg/` 的清理须经人类确认（当前 `[OPEN]`）。