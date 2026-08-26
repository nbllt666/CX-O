# CX-A 管理接口文档

> CX-A（CX-O Admin）是 CX-O 面向"另一智能体"开放的管理面（控制平面）。
> 它把整套后端运行时——语音、自主性、直播、配置、Agent、调优、实例、哨兵集群——统一成一个可编程的管理 API，供外部治理程序（另一 agent）编排、巡检与运维。**管理面刻意不放在前端里，只以 API 形态存在。**

本文档描述 CX-A 管理接口的全部端点、鉴权、权限分级、错误码与调用方式。

---

## 1. 概览

### 1.1 它解决什么

- **统一控制**：用同一种 `action + target` 语法下发控制指令到所有子系统，无需逐个对接内部实现。
- **静态可发现**：通过 `manifest` 拿到当前实例的能力清单、已注册 Agent、插件、模型与集群状态，外部治理程序据此决定该做什么。
- **幂等与安全**：`request_id` 防重放、多级令牌权限、限流、审计留痕，保证可安全远程操作。

### 1.2 两种接口形态

CX-A 管理面内实际存在两套端点，鉴权方式不同：

| 形态 | 鉴权 | 用途 |
|------|------|------|
| 基础管理端点 | 请求头 `X-API-Key`（环境变量 `ADMIN_API_KEY`） | 仪表盘、统计、健康、配置读写、日志、备份 |
| CX-A 控制平面端点 | 请求头 `Authorization: Bearer <token>`（分级令牌） | 自描述清单、状态、单条控制、批量编排、审计 |

下文分别说明。

---

## 2. 启用与配置

CX-A 默认关闭（`admin.enabled = false`），关闭时控制平面端点一律返回 `503`，且不装配运行时。

### 2.1 配置文件（`CX-O-SERVER/config.json`）

```json
{
  "admin": {
    "enabled": true,
    "bind": "127.0.0.1",
    "tls_enabled": false,
    "tokens": [
      { "token": "xxx-readonly",  "level": "readonly" },
      { "token": "xxx-operator",  "level": "operator" },
      { "token": "xxx-superadmin","level": "superadmin" }
    ],
    "request_id_ttl_sec": 300,
    "rate_limit_per_sec": 20,
    "cx_a_endpoint": "",
    "register_heartbeat_sec": 15
  }
}
```

| 字段 | 默认 | 说明 |
|------|------|------|
| `enabled` | `false` | 总开关。`true` 才装配 CX-A 运行时 |
| `bind` | `127.0.0.1` | 监听地址（仅作声明，实际由网关接入） |
| `tls_enabled` | `false` | 是否 TLS |
| `tokens` | `[]` | 分级令牌表（见 §3.2） |
| `request_id_ttl_sec` | `300` | 防重放缓存的有效期（秒） |
| `rate_limit_per_sec` | `20` | 令牌桶限流速率 |
| `cx_a_endpoint` | `""` | 主动注册目标：非空时本实例周期向该端点上报注册/心跳 |
| `register_heartbeat_sec` | `15` | 主动注册心跳间隔（秒） |

> 全部字段也可用 `CXO_ADMIN_*` 环境变量覆盖（如 `CXO_ADMIN_ENABLED`、`CXO_ADMIN_RATE_LIMIT_PER_SEC`、`CXO_ADMIN_CX_A_ENDPOINT`、`CXO_ADMIN_TLS_ENABLED`、`CXO_ADMIN_BIND`）。

### 2.2 装配条件

在服务启动阶段，当 `admin.enabled == true` 时才会：

1. 实例化 `AdminAuth`（认证/防重放/限流）。
2. 实例化 `InstanceRegistry`（多实例注册/心跳表，配置了 `cx_a_endpoint` 则周期主动上报）。
3. 实例化 `ClusterAdminBridge`（与哨兵集群的解耦适配层）。
4. 实例化 `AdminControlPlane`（统一控制入口）。
5. 组装 `AdminManifest`（运行时自描述能力清单）并注入路由运行时。

任一装配失败都会被隔离，**绝不影响主服务启动**。

---

## 3. 鉴权与安全

### 3.1 基础管理端点

- 请求头：`X-API-Key: <ADMIN_API_KEY>`
- 来源：环境变量 `ADMIN_API_KEY`。
- 未配置或校验失败：返回 `403`。

### 3.2 CX-A 控制平面端点

- 请求头：`Authorization: Bearer <token>`
- token 必须在 `admin.tokens` 中登记，匹配方式为常量时间比较（`compare_digest`），不区分大小写敏感之外的可观测差异。
- 令牌分级（能力递进）：

| 级别 | 权限 | 适合动作 |
|------|------|---------|
| `readonly` | 仅读取 | `manifest` / `status` / `audit` |
| `operator` | 读取 + 常规控制 | 单条/批量控制、启停、配置重载 |
| `superadmin` | 全部 | 重启/关停实例、集群故障转移、增删节点 |

### 3.3 三道防护（控制平面端点通用）

控制平面端点默认全部启用以下三道防护：

1. **防重放**：`POST /control` 与 `POST /batch` 携带 `request_id`，服务端在 `request_id_ttl_sec` 内对重复 `request_id` 拒绝（返回 `ADMIN_REPLAYED`）。GET 类端点不强制。
2. **限流**：令牌桶，速率 `rate_limit_per_sec`。超限返回 `ADMIN_RATE_LIMITED`。
3. **权限分级**：token 级别不足目标所需级别时返回 `ADMIN_FORBIDDEN`。

---

## 4. 错误码

所有异常统一走 HTTP 状态码 + 错误码，调用方必须自行处理约定的异常：

| 错误码 | HTTP | 含义 |
|--------|------|------|
| `ADMIN_DISABLED` | 503 | 管理面未启用（`admin.enabled=false`）或未配置 token |
| `ADMIN_AUTH_FAILED` | 403 | 令牌无效 / 未携带 |
| `ADMIN_FORBIDDEN` | 403 | 级别不足 |
| `ADMIN_REPLAYED` | 403 | `request_id` 重复 |
| `ADMIN_RATE_LIMITED` | 429 | 触限流 |
| `ADMIN_UNKNOWN_ACTION` | 400 | 未知 `action` / `target` |
| `ADMIN_SERVICE_ERROR` | 400 | 控制动作执行失败 |

---

## 5. 基础管理端点

以下端点与 CX-O 常规后端共用 `/api` 前缀，鉴权用 `X-API-Key`。

### 5.1 GET `/api/admin/dashboard`
管理后台仪表盘统计（内存、上下文、ACP）。
- 鉴权：`X-API-Key`
- 返回：`{"status":"success","timestamp":"...","dashboard":{memory,context,acp}}`
- 单项失败不会整体报错，对应项为空对象。

### 5.2 GET `/api/admin/stats`
内存、上下文与工具注册统计。
- 返回：`{"status":"success","statistics":{memory,context,tools}}`

### 5.3 GET `/api/admin/health`
健康检查，**无需认证**。
- 返回：
```json
{
  "status": "healthy | degraded",
  "components": { "memory": "healthy|unhealthy", "context": "...", "acp": "..." }
}
```

### 5.4 GET `/api/admin/config`
读系统配置片段。
- 返回：`{"status":"success","config":{llm,vector,acp,system}}`

### 5.5 PUT `/api/admin/config`
更新系统配置片段（带 Pydantic schema 校验）。
- 请求体（任意可空子节；只更新出现的字段）：
```json
{
  "llm":    { "provider": "vllm|ollama", "model": "..." },
  "vector": { "enabled": true },
  "acp":    { "enabled": true, "agent_name": "..." },
  "system": { "debug": false }
}
```
- `llm.provider` 只允许 `ollama` / `vllm`，否则 400。
- 成功后持久化到配置文件。返回 `{"status":"success","message":"配置已更新"}`。

### 5.6 GET `/api/admin/logs?level=INFO&lines=50`
读取服务端后端日志尾部。
- `lines` 截断到 `[1, 1000]`（默认 50）；非法 level 回退 `INFO`。
- 返回：`{"status":"success","logs":[...],"total":N,"level":...,"lines":N}`

### 5.7 POST `/api/admin/backup`
创建数据目录的压缩备份。
- 排除 `data/backups` 自身，避免嵌套递归膨胀。
- 返回：`{"status":"success","path":"...","message":"备份已创建"}`

---

## 6. CX-A 控制平面端点

以下端点**必须**在 `admin.enabled=true` 才有意义；未启用一律 `503`。鉴权用 `Authorization: Bearer <token>`。

### 6.1 GET `/api/admin/manifest` — 自描述能力清单
- 所需级别：`readonly`
- 作用：外部治理程序读取"这台实例能干什么"，据此决策。
- 返回：
```json
{
  "instance_id": "...",
  "node_name": "cx-o-node",
  "version": "1.0.0",
  "capabilities": {
    "realtime_voice": true,
    "autonomy": true,
    "tuner": false,
    "live_stream": false,
    "computer_control": true,
    "vision": false
  },
  "control_actions": ["enable","disable","pause","resume",/*...*/"shutdown"],
  "agents": ["agent-id-1", "..."],
  "plugins": ["plugin-id-1", "..."],
  "models": { "main":"...", "summary":"...", "memory":"..." },
  "endpoints": { "ws":"/ws", "health":"/api/health", "cluster":"/api/cluster" },
  "cluster": { ... }
}
```
- 集群未启用时 `cluster` 为 `{"enabled":false}`。

### 6.2 GET `/api/admin/status` — 实例状态快照
- 所需级别：`readonly`
- 返回：`{"status":"success","snapshot":{models,capabilities,cluster}}`

### 6.3 POST `/api/admin/control` — 单条控制
- 所需级别：`operator`
- 请求体：
```json
{
  "action": "reload",
  "target": "config",
  "agent_id": "default",
  "request_id": "唯一ID",
  "params": {}
}
```
- `agent_id` / `params` 可省。
- 返回：`{"status":"success","result":{...}}`
- 未知 `action`/`target` 返回 400 + `ADMIN_UNKNOWN_ACTION`。

**`target` 与 `action` 组合（匹配矩阵）**

| target | 合法 action | 说明 |
|--------|------------|------|
| `autonomy` | `enable` `disable` `pause` `resume` `emergency_stop` `start` `stop` | 依 `autonomy_manager` 上同名方法调用 |
| `voice` | 同上类通用动作 | 依 `tts` / `audio` 服务上同名方法调用 |
| `live` | 通用动作 | 依 `live` 服务 |
| `config` | `reload` `reload_config` `reset` | 触发配置热重载 |
| `agent` | `create` `update` `delete` `restart` | 依 `acp_manager` 对应方法 |
| `tuner` | `start` `stop` | 调参服务启停 |
| `instance` | `restart` `shutdown` | 返回触发信号（进程级重启由进程管理承接） |
| `cluster` | 见 §6.5 | 转发 `ClusterAdminBridge` |

> 当目标域服务的方法不存在时，返回 `{"available":..., "unsupported":true}`，调用方应据此优雅降级。

### 6.4 POST `/api/admin/batch` — 批量编排
- 所需级别：`operator`
- 请求体：
```json
{
  "request_id": "唯一ID",
  "mode": "sequential",        // sequential | parallel
  "stop_on_error": true,       // 仅 sequential 生效
  "steps": [
    { "target": "autonomy", "action": "enable" },
    { "target": "config",   "action": "reload" }
  ]
}
```
- `mode=sequential` 按序执行；`stop_on_error=true` 时一旦某步失败立即中止。
- `mode=parallel` 并发执行全部步骤，互不阻塞。
- 返回：
```json
{
  "status": "success",
  "mode": "sequential",
  "steps": [
    { "step": 0, "ok": true,  "result": {...}, "duration_ms": 12.3 },
    { "step": 1, "ok": false, "result": {"error":"..."}, "duration_ms": 3.1 }
  ]
}
```
- `steps` 为空返回 400；每步非对象也返回 400。

### 6.5 集群控制（`target=cluster`）
- 读操作所需级别 `readonly`，写操作 `operator`（故障转移类建议用 `superadmin`）。
- **读**：`topology` / `state` / `sync_status` → 集群拓扑、当前状态、同步状态。
- **写**：`trigger_failover` / `set_role` / `add_peer` / `remove_peer`，变体参数放 `params`（如 `from_node`/`to_node`）。
- 集群未启用（`cluster_manager` 为 None）时，读写统一返回 `{"status":"cluster_disabled"}`。

### 6.6 GET `/api/admin/audit?limit=50&offset=0` — 管理审计日志
- 所需级别：`readonly`
- 分页读取管理面审计（JSONL，倒序，最新在前）。
- 返回：`{"status":"success","items":[...]}`

---

## 7. 内部端点

- `POST /api/admin/register`：本机作为被注册方时记录注册，主动注册由 `InstanceRegistry` 对接 `cx_a_endpoint` 完成。计作内部端点，一般不直接调用。

---

## 8. 调用示例

### 8.1 读取能力清单（只读令牌）

```bash
curl -H "Authorization: Bearer xxx-readonly" \
     http://127.0.0.1:8000/api/admin/manifest
```

### 8.2 下发一条控制指令

```bash
curl -X POST http://127.0.0.1:8000/api/admin/control \
  -H "Authorization: Bearer xxx-operator" \
  -H "Content-Type: application/json" \
  -d '{
        "target": "config",
        "action": "reload",
        "request_id": "op-20260826-0001"
      }'
```

### 8.3 批量编排（先开自主性，再重载配置）

```bash
curl -X POST http://127.0.0.1:8000/api/admin/batch \
  -H "Authorization: Bearer xxx-operator" \
  -H "Content-Type: application/json" \
  -d '{
        "request_id": "op-20260826-0002",
        "mode": "sequential",
        "steps": [
          { "target": "autonomy", "action": "enable" },
          { "target": "config",   "action": "reload" }
        ]
      }'
```

### 8.4 基础端点（X-API-Key）

```bash
curl -H "X-API-Key: $ADMIN_API_KEY" \
     http://127.0.0.1:8000/api/admin/config
```

---

## 9. 契约配套

- TS 客户端：[admin.ts](../APP-Frontend/src/api/clients/admin.ts)（封装 manifest/status/control/batch/audit）
- 接口存根：[cx_admin.pyi](../public/interface_stub/cx_admin.pyi)（`AdminAuth` / `AdminManifest` / `AdminControlPlane` / `AdminBatchExecutor` / `InstanceRegistry` / `ClusterAdminBridge`）
- 数据契约：[admin_control.schema.json](../public/schema/admin_control.schema.json)、[admin_batch.schema.json](../public/schema/admin_batch.schema.json)、[admin_audit.schema.json](../public/schema/admin_audit.schema.json)