# CXFC 插件开发指南

> CXFC 是 CX-O 的插件化能力接入框架：你写一个独立小服务（插件），把它要提供的"工具/技能"注册到主后端 CX-O-SERVER，之后主系统的 AI Agent 就能调用它去操作电脑或做别的本机能力。本文从零教你怎么写一个**可用的、安全的**插件，并给出每一步的完整细节。

---

## 目录

- [1. 一句话原理](#1-一句话原理)
- [2. 插件必须实现的 4 个端点（含完整字段）](#2-插件必须实现的-4-个端点含完整字段)
- [3. 最小可用插件（完整可运行示例）](#3-最小可用插件完整可运行示例)
- [4. 注册、心跳、注销（让主后端认识你）](#4-注册心跳注销让主后端认识你)
- [5. 验证接入是否成功](#5-验证接入是否成功)
- [6. 加更多工具](#6-加更多工具)
- [7. 参考工具规格（屏幕 / 键盘 / 运行指令）](#7-参考工具规格屏幕--键盘--运行指令)
- [8. 安全模型（完整细节）](#8-安全模型完整细节)
- [9. 如何给插件加安全（分步）](#9-如何给插件加安全分步)
- [10. 配置项](#10-配置项)
- [11. 常见坑与要点](#11-常见坑与要点)
- [12. 一分钟自检清单](#12-一分钟自检清单)
- [参考现成实现](#参考现成实现)

---

## 1. 一句话原理

```
Agent 需要某个能力
   → 主后端把请求转发给你的插件（POST /call）
   → 你的插件执行本机动作并返回结果
```

你的插件只做三件事：

1. **起一个 HTTP/HTTPS 服务**，暴露固定路径的 4 个端点；
2. **声明**你提供哪些工具（`/tools`）、哪些技能（`/skills`），供后端抓取后给 Agent 用；
3. **实现** `POST /call`：真正执行动作、返回统一结果外壳。

注册、心跳保活、把工具登记给 Agent、转发调用——这些都由主后端处理，**你基本不用碰主后端代码**。

---

## 2. 插件必须实现的 4 个端点（含完整字段）

| 端点 | 方法 | 作用 | 返回 |
|------|------|------|------|
| `/health` | GET | 让主后端确认你在线、知道你叫什么 | `{name, version, status, authorized}` |
| `/tools` | GET | 声明你提供的工具 | `{tools: [ToolDescriptor]}` |
| `/skills` | GET | 声明你提供的技能 | `{skills: [SkillDefinition]}` |
| `/call` | POST | 收到一次工具调用，执行并返回 | `{success, result?, error?, ...}` |

### 2.1 `/health` 完整返回

```jsonc
{
  "name": "MyFirstPlugin",   // 插件显示名，后端 /cxfc/plugins 里展示
  "version": "1.0.0",        // 语义化版本
  "status": "ok",            // 一般为 "ok"
  "authorized": true         // 是否已授权（受控插件用，见第 8 章）
}
```

### 2.2 `/tools` —— 每个工具的完整结构

```jsonc
{
  "name": "greet",                                  // 必填：工具名，Agent 用这个名字调用你
  "description": "打个招呼，参数 name 是对方名字",    // 必填：告诉 Agent 这个工具干嘛、参数怎么填
  "parameters": {                                    // 必填：JSON Schema，声明参数的形状/取值范围/必填项
    "type": "object",
    "required": ["name"],
    "additionalProperties": false,                   // 建议 true，禁止多余参数，防误传
    "properties": { "name": { "type": "string", "minLength": 1 } }
  },
  "returns": {}                                      // 建议：描述返回结构（可以为空对象）
}
```

> `description` 写得好不好，直接决定 Agent 会不会正确调用——尽量写明"每个参数是什么、什么时候用"。

### 2.3 `/skills` —— 技能的完整结构

技能 = 告诉 Agent"收到什么话、按什么步骤做"。适合较复杂的流程（例如唱歌要"建草稿→加音符→校验→提交→轮询任务"）。

```jsonc
{
  "name": "compose-a-song",
  "description": "帮用户写歌：生成歌谱→校验→提交合成→返回成品音频",
  "prompt_template": "当用户让你写歌时，按以下命令流执行：\n1. 调用 music_edit_score(...)...",
  "trigger_keywords": ["唱歌", "写歌", "作词"],   // 命中这些词，后端就可能注入这个技能提示
  "trigger_events": [],                            // 命中这些事件触发（事件型插件才用）
  "auto_inject": true,                             // 是否自动注入到 Agent 上下文
  "source_plugin_id": ""                           // 后端自动填，你不用管
}
```

### 2.4 `/call` —— 请求与统一返回外壳

后端调用你时发：

```jsonc
{ "tool": "greet", "arguments": { "name": "小明" } }
```

**关键约定：HTTP 状态码永远返回 200**，业务成功/失败全靠 `success` 字段区分（这与仓库里 mock 插件的约定一致）：

```jsonc
// 成功
{ "success": true, "result": { "greeting": "你好，小明" } }
// 失败（未知工具、参数非法、任务不存在等）
{ "success": false, "error": "参数 name 缺失" }
```

---

## 3. 最小可用插件（完整可运行示例）

用 FastAPI + uvicorn 就能跑。把下面的代码存成 `plugin.py`：

```python
from fastapi import FastAPI, Request

app = FastAPI()

# 所有工具的唯一定义（加工具只改这里 + /call 的分发）
TOOLS = [{
    "name": "greet",
    "description": "打个招呼，参数 name 是对方名字",
    "parameters": {
        "type": "object",
        "required": ["name"],
        "additionalProperties": False,
        "properties": {"name": {"type": "string", "minLength": 1}},
    },
    "returns": {"type": "object", "properties": {"greeting": {"type": "string"}}},
}]

@app.get("/health")
async def health():
    return {"name": "MyFirstPlugin", "version": "1.0.0",
            "status": "ok", "authorized": True}

@app.get("/tools")
async def tools():
    return {"tools": TOOLS}

@app.get("/skills")
async def skills():
    return {"skills": []}

@app.post("/call")
async def call(req: Request):
    body = await req.json()
    tool, args = body.get("tool"), body.get("arguments", {})
    if tool != "greet":
        return {"success": False, "error": f"未知工具: {tool}"}
    name = args.get("name", "")
    if not name:
        return {"success": False, "error": "参数 name 缺失"}
    return {"success": True, "result": {"greeting": f"你好，{name}"}}
```

启动：

```powershell
pip install fastapi uvicorn
uvicorn plugin:app --host 127.0.0.1 --port 18444
```

现在用浏览器打开 `http://127.0.0.1:18444/health` 和 `/tools`，都能看到内容。你的插件已经是个真实服务了。

---

## 4. 注册、心跳、注销（让主后端认识你）

服务起来≠被主后端认得。你需要一个"注册客户端"周期运行：注册 → 心跳 →（退出时）注销。**这段代码放在你接入端里写**（Electron 主进程 或 Python 服务启动逻辑），而不是放在插件 HTTP 服务里。

两个可直接照抄的现成实现：

| 你要接入的端 | 照着参考 |
|--------------|----------|
| Electron（桌宠） | `APP-Frontend/electron/cxfc/client.ts`（类 `CxfcClient`） |
| Python 服务 | `CX-O-VoiceWorkStation/workstation/services/cxfc_registration.py`（类 `CXFCRegistrationService`） |

### 4.1 三个请求的完整形状

```text
① 注册    POST {后端}/cxfc/register
   请求体：
   {
     "host": "127.0.0.1",                 // 插件监听地址；0.0.0.0 要改回 127.0.0.1
     "port": 18444,                       // ★ 插件实际监听端口，后端靠它回连你的 /call
     "name": "MyFirstPlugin",
     "version": "1.0.0",
     "capabilities": ["greeting"],        // 能力标识，随便写，作归类
     "tools": [/* 和第 2.2 节同结构的工具数组 */],
     "skills": [/* 技能数组 */]
     // 下面三个只有"受控插件"才带，见第 8 章：
     // "token": "注册令牌",
     // "tls_cert_fingerprint": "证书指纹",
     // "tls_cert_pem": "证书PEM原文"
   }
   响应：{ "status": "ok", "plugin_id": "cxfc_127.0.0.1_18444" }

② 心跳    POST {后端}/cxfc/heartbeat      （周期调用，默认约 10s）
   请求体：{ "plugin_id": "cxfc_127.0.0.1_18444", "port": 18444 }
   响应：{ "status": "alive" }
   ★ 若返回 404 = 主后端重启、把它忘了 → 你要立刻回到"① 重新注册"

③ 注销    DELETE {后端}/cxfc/plugins/{plugin_id}   （应用退出时，尽力而为，失败别阻断退出）
```

### 4.2 注册客户端应有的行为（照做最稳）

- **启动**：先注册；注册成功前若后端没起，要**指数退避重试**（如 1s → 2s → 4s … 封顶 30s），后端起来后能自动连上。
- **保活**：注册成功后，按固定间隔（约 10s）发心跳。
- **被遗忘恢复**：心跳收到 `404`，立刻重置状态，下一轮重新注册。
- **退出**：注销一次，失败就忽略，别让注销拦住应用退出。
- **别开重复循环**：已经在跑的注册循环别重复 start（避免多开心跳任务）。

> 正确的 `plugin_id` 由后端按 `cxfc_{host}_{port}` 规则生成；如果你拿任意新端口/新地址，就得到一个新的 plugin_id（被当成新插件）。

---

## 5. 验证接入是否成功

1. **看插件列表**：浏览器打开 `GET {后端}/cxfc/plugins`，应能看到 `MyFirstPlugin`，且状态为 `connected`。
2. **触发一次调用**（验证全链路）：
   `POST {后端}/cxfc/plugins/cxfc_127.0.0.1_18444/call`
   请求体 `{"tool":"greet","arguments":{"name":"小明"}}`
   应返回 `{ "success": true, "result": { "greeting": "你好，小明" } }`
3. **看技能**：`GET {后端}/cxfc/skills`，应能看到你声明的技能（如果有）。
4. **让 AI 真的用**：回到管理界面聊天，说一句让它用这个工具的话，观察是否正常返回。

> 调试期或没写好真实插件时，仓库里 `tests/test_tools/cxfc/mock_plugin_server.py` 是一个形状与真实插件完全一致的 mock，先用它把链路跑通，再换成你的实现。

---

## 6. 加更多工具

每加一个工具只动两处，别改别处：

1. 在 `TOOLS` 列表追加一项（`name / description / parameters / returns`）；
2. 在 `/call` 里加一个 `elif tool == "新的工具名":` 分支写真实逻辑。

然后二选一让后端跟着变：

- 调 `POST {后端}/cxfc/plugins/{plugin_id}/refresh` 刷新该插件；
- 或重启你的插件让它重新走一遍注册（每次注册都会重新抓 `/tools`、`/skills`）。

---

## 7. 参考工具规格（屏幕 / 键盘 / 运行指令）

仓库里电脑控制插件已经做了一套"操作电脑"的完整工具，是做类似工具时的最佳模板。下面是三工具的**请求参数**规格（字段与 `public/schema/computer_control_plugin.schema.json` 一致），可直接抄。

### 7.1 屏幕控制 `computer_screen_control`

参数 `action` 必填：

| 字段 | 类型 | 说明 |
|------|------|------|
| `action` | enum | `capture` 采集 / `click` 点击 / `move` 移动 / `scroll` 滚动 |
| `x` / `y` | int | 目标坐标（点击/移动/滚动时用） |
| `width` / `height` | int | 采集区域（capture 时用，缺省=全屏） |
| `scroll_dx` / `scroll_dy` | int | 滚动增量（scroll 时用） |
| `button` | enum | `left/right/middle`（click 时用，默认 left） |

> 屏幕采集内容**不得写入日志**。

### 7.2 键盘控制 `computer_keyboard_control`

| 字段 | 类型 | 说明 |
|------|------|------|
| `action` | enum | `type` 输入文本 / `key` 单键 / `press` 按下释放 / `hotkey` 快捷键组合 |
| `text` | string | `type` 时输入的内容 |
| `key` | string | `key`/`press` 时的单键名 |
| `keys` | string[] | `hotkey` 时的组合序列 |
| `duration` | int | 按下持续时间（毫秒，可选） |

> 密码、密钥等敏感输入**不得由工具自动记录**。

### 7.3 运行指令 `computer_run_command`

| 字段 | 类型 | 说明 |
|------|------|------|
| `command` | string | 要执行的命令/脚本路径（必填） |
| `args` | string[] | 结构化参数，逐项透传，**禁止拼进命令字符串** |
| `cwd` | string | 工作目录（可选） |
| `timeout_ms` | int | 执行超时（毫秒，缺省用配置默认 30000） |
| `env` | object | 环境变量**白名单**，只透传名单内声明的变量 |

**返回**：`success / exit_code / stdout(截断) / stderr(截断) / timed_out / truncated / error`。
`success` 只代表"进程成功启动且未超时"，**不代表退出码为 0**——判断是否成功要看 `exit_code`。

> 运行指令这类工具，必须保留第 8 章 8.5 的完整护栏，否则一是危险、二是 GN 级审查不会放行。

---

## 8. 安全模型（完整细节）

安全按"你的工具会不会操作这台电脑"分两档。**会操作电脑（屏幕/键盘/运行命令/动文件）必须走完整安全**，参考 `APP-Frontend/electron/plugins/computerControl/`。四层叠加：

### 8.1 本地授权（Authorization）

- 语义：一次点击"授权"后**永久有效**，用户主动撤销即失效（撤销即关闭）。
- 未授权时，三个工具一律拒绝且**不执行任何本机动作**。
- 别把它和"认证"混：`NOT_AUTHORIZED` 是"认证过了但授权关着"，`UNAUTHORIZED` 是"认证就失败了"。

### 8.2 认证（Authentication）

- 注册时签发一个随机令牌（仓库做法：256-bit = 32 字节随机 hex），持久化在**主进程 userData**，权限 `0600`。
- 后端转发 `/call` 时带 `Authorization: Bearer <token>`；你收到后校验，令牌缺失/错误 → 返回 `UNAUTHORIZED`。
- 令牌**不要**经 `/tools`、`/health` 等元数据接口明文回传。

### 8.3 防重放（Anti-Replay）

- 每次 `/call` 带唯一 `request_id`（后端转发时用 `uuid4()` 生成）。
- 你记录最近收到的 `request_id`，当前时间窗内重复 → 返回 `REPLAY_DETECTED`（409），不执行动作。

### 8.4 TLS 首次信任 + 证书固定（TOFU）

- 插件生成自签名证书，注册时把**证书 PEM** 和它的 **SHA-256 指纹**都上报。
- 后端会校验"指纹与 PEM 算出来的一致"，一致才收；并把这个 PEM 当 CA 保存，之后访问你只用这把证书。**后端只信任注册时保存的那一份证书**，换了证书就得重新注册。
- 所以插件端要注意：`host` 最好用固定地址注册，`port` 若冲突自动换端口后要重新注册（绑定 Tls 证书也要跟着）。

### 8.5 `run_command` 的护栏（做运行命令工具必备）

| 护栏 | 默认值 | 作用 |
|------|--------|------|
| `timeout_ms` | 30000 | 超时后回收整个进程树 |
| `max_output_bytes` | 65536 | 输出捕获字节上限，达到即截断 |
| `max_output_chars` | 16384 | 返回的 stdout/stderr 摘要字符上限 |
| `redact_patterns` | 内置密码/密钥/令牌/Authorization/私钥正则 | 敏感内容在结果与日志中替换为掩码，**不落明文审计日志** |
| `kill_process_tree` | true | 超时/失败时是否回收进程树 |

另两条铁律：
- **结构化传参**：用 `command + args[]`，禁止把未校验输入拼接进 `shell` 命令行。
- **env 白名单**：只透传 `env` 里声明过的变量，其余不注入。

### 8.6 统一错误码

出错时在返回里带 `error_code`，取值固定（`public/schema/computer_control_error_codes.json`）：

| code | HTTP 映射 | 含义 |
|------|-----------|------|
| `UNAUTHORIZED` | 401 | 认证失败（令牌/指纹不匹配） |
| `NOT_AUTHORIZED` | 403 | 认证通过但本地授权未开启 |
| `REPLAY_DETECTED` | 409 | request_id 重复 |
| `INVALID_ARGUMENT` | 400 | 工具名或参数不合契约 |
| `EXECUTION_FAILED` | 500 | 进程启动失败 / 权限不足 |
| `TIMEOUT` | 504 | 执行超时，已回收进程树 |
| `SYSTEM_ERROR` | 500 | 插件内部/系统级错误 |
| `PLUGIN_OFFLINE` | 503 | 插件不可达（后端侧用） |

---

## 9. 如何给插件加安全（分步）

给一个会"操作电脑"的插件上完整安全的落地清单：

1. **令牌**：首次运行生成随机令牌并持久化；后端注册请求体带 `token`。
2. **TLS**：生成自签名证书 + 计算 SHA-256 指纹；注册请求体带 `tls_cert_fingerprint` 和 `tls_cert_pem`；HTTP 服务改用 HTTPS（`cert/key`）。
3. **认证中间件**：`/call` 入口校验 `Authorization: Bearer <token>`，失败返回 `UNAUTHORIZED`。
4. **防重放**：记录最近 `request_id`（带时间窗），重复返回 `REPLAY_DETECTED`。
5. **授权状态**：提供授权读写（放 IP 上的悬浮窗按钮 / 本地文件持久化），未授权返回 `NOT_AUTHORIZED`。
6. **执行顺序固定**：认证 → 防重放 → 授权 → 参数校验 → 执行，任一不过立刻返回、不执行。
7. **`run_command` 护栏**：如做运行命令，把 8.5 的五项护栏做进去。

认证、授权、TLS、三工具的完整实现可直接看/复用 `electron/plugins/computerControl/` 下的 `auth.ts`、`authorization.ts`、`tls.ts`、`runCommand.ts`。

---

## 10. 配置项

### 10.1 后端 CXFC 配置（`UnifiedConfig.cxfc`）

| 键 | 默认值 | 说明 |
|----|--------|------|
| `enabled` | true | 是否启用 CXFC 模块 |
| `heartbeat_timeout` | 30 | 心跳超时（秒），超过视为断开 |
| `heartbeat_check_interval` | 10 | 后端心跳巡检间隔（秒） |
| `discovery_enabled` | true | 是否启用 UDP 局域网发现 |
| `discovery_port` / `broadcast_port` | 9996 / 9997 | 发现监听 / 广播端口 |
| `auto_connect_on_startup` | true | 启动时自动连接已注册插件 |
| `storage_path` | data/cxfc_plugins.db | 插件持久化库路径 |

### 10.2 Electron 电脑控制插件配置

| 键 | 默认值 | 说明 |
|----|--------|------|
| `authorized` | false | 授权状态 |
| `token` | "" | 注册令牌 |
| `host` | 0.0.0.0 | HTTPS 监听地址 |
| `port` | 18443 | HTTPS 监听端口 |
| `tls_cert_path` / `tls_fingerprint` | "" | TLS 证书 / 指纹 |
| `run_command.*` | 见 8.5 | 运行指令护栏 |
| `auto_start` | false | Electron 随机启动（Windows 登录项） |
| `run_as_admin` | false | 管理员权限启动（Windows UAC） |
| `backend_url` | https://127.0.0.1:8000 | 主后端地址 |
| `enableNativeDrivers` | true | 是否启用真实输入驱动（无 GUI 可关，工具返 SYSTEM_ERROR） |

---

## 11. 常见坑与要点

- **`/call` 永远 200**：业务失败用 `success:false`，别用非 200 状态码表达业务错误。
- **心跳 404 = 后端忘了你**：立即重置状态、下轮重新注册。
- **`0.0.0.0`/`::` 别直接上报**：主后端连不上，统一改 `127.0.0.1`。
- **端口上报要准**：报的 port 必须是插件实际监听的端口，否则回连失败。
- **token/TLS 证书别经元数据接口泄**：`/tools`、`/health` 勿返回令牌。
- **敏感信息不进日志**：`run_command` 输出先 `redact_patterns` 脱敏再写日志。
- **证书固定意味着换证要重注册**：换了自签名证书，得重新走一遍注册让后端学新证书。
- **`_plugins` 并发**：这是后端内部的事，但你如果自己维护类似的内存表也记得加锁。
- **别多开注册循环**：Electron / Python 端注册服务要幂等，重复 start 会开多个心跳任务。

---

## 12. 一分钟自检清单

- [ ] 实现了 `/health /tools /skills /call` 四个端点（工具/技能可按需留空）
- [ ] `/call` 永远返回 HTTP 200，业务失败用 `success:false`
- [ ] 有注册 + 心跳循环，心跳遇 404 会重新注册，注册失败会退避重试
- [ ] 上报的 port 是实际监听端口，`0.0.0.0` 已改 `127.0.0.1`
- [ ] 在 `/cxfc/plugins` 能看到插件且状态 connected
- [ ] 一次 `/call` 端到端调用返回 `success:true`，`/cxfc/skills` 能看到技能
- [ ] 若操作本机 → 已做令牌 / TLS / 防重放 / 本地授权，且 run_command 有五项护栏
- [ ] 敏感信息（密码/密钥/令牌）不进日志

---

## 参考现成实现

- 受控插件完整版（含安全）：`APP-Frontend/electron/plugins/computerControl/`
- Electron 注册客户端：`APP-Frontend/electron/cxfc/client.ts`
- Python 插件 + 注册服务：`CX-O-VoiceWorkStation/workstation/api/cxfc_plugin.py`、`workstation/services/cxfc_registration.py`
- 联调 mock：`tests/test_tools/cxfc/mock_plugin_server.py`
- 三工具 / 错误码 / 配置契约：`public/schema/computer_control_plugin.schema.json`、`public/schema/computer_control_error_codes.json`、`public/config_template/computer_control_config.schema.json`