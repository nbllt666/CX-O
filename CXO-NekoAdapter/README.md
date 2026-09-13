# CXO-NekoAdapter

Neko 插件适配器（独立项目）。负责把 N.E.K.O 的插件服务器（python sidecar）拉起在本机，并把插件注册的 LLM 工具通过 CXFC 协议桥接给 CX-O 后端。本项目自包含，不依赖任何父目录代码，可独立运行、独立测试，也可被其他 agent 经控制面 API 直接管理。

## 运行方式

```bash
cd CXO-NekoAdapter
npm install
npm run build
npm start            # 控制面默认监听 127.0.0.1:48920
npm start -- --port 48999   # 指定控制面端口
npm test             # vitest 单测
node tests/e2e-lifecycle.mjs # 生命周期 E2E（用桩 python，不依赖真实 neko 源码）
```

启动后输出机器可读行：`[adapter] control listening on 127.0.0.1:<port>`。

## 配置项（data/config.json，首次运行自动生成，缺失键自动补全）

| 键 | 默认值 | 说明 |
|----|--------|------|
| `python` | `"python"` | python 可执行路径（用于拉起插件服务器） |
| `sourceDir` | `"C:\\N.E.K.O-main"` | neko 源码目录（含 config/plugin/utils 包），只读不修改 |
| `port` | `48916` | 插件服务器期望端口，被占自动向后探测 |
| `backendUrl` | `"http://127.0.0.1:8000"` | CX-O 后端地址（CXFC 注册/心跳目标） |
| `controlPort` | `48920` | 控制面端口，被占自动递增（最多 +50） |
| `autoStart` | `false` | 预留 |

隔离用途：设置环境变量 `CXO_NEKO_ADAPTER_DATA_DIR` 可把 data 目录指到别处（测试/多实例）。

## 控制面 API（仅绑定 127.0.0.1，供 CX-O 桌面端与其他 agent 调用）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 存活探针，`{ok,status,service,port}` |
| GET | `/status` | 聚合状态：`{running,port,config,bridge:{registrarRunning,bridgeRunning,bridgePort,tools,cxfcRegistered}}` |
| POST | `/start` | 拉起完整运行时（注册接收器 → 插件服务器 → CXFC 桥并注册后端），幂等，`{ok,port,bridge}` |
| POST | `/stop` | 停止运行时（SIGTERM→3s 超时→SIGKILL），未运行也返回成功 |
| POST | `/restart` | **完整运行时重建**（桥端口同步刷新，无陈旧端口），`{ok,port,bridge}` |
| GET | `/config` | 全量配置 |
| PUT | `/config` | 部分更新并持久化（类型校验，非法键/类型返回 400） |
| GET | `/logs/recent?limit=N` | 近期日志（环形缓冲，上限 1000 条） |
| GET | `/logs/stream` | SSE 实时日志（先补发 recent，15s 心跳帧，断开自动清理） |

## 端口约定

| 端口 | 用途 |
|------|------|
| 48920+ | 控制面（默认，可配） |
| 48916+ | 插件服务器（python sidecar，被占自动探测） |
| 48911 | 工具注册接收器（模拟 neko 主服务器 /api/tools/*，捕获插件上报的工具定义） |
| 28443+ | CXFC HTTPS 工具桥（自签证书，TOFU 信任；被占自动 +1，最多 10 次） |

## 与 CX-O 桌面端的关系

桌面端（APP-Frontend Electron）不再内嵌适配器，而是：自动以子进程拉起本项目（`neko.adapterDir` 指向本项目目录），经控制面 API 管理生命周期，经 SSE 转发日志到界面；userData 中的旧 `neko.*` 配置会在首次启动时一次性种子同步到本项目的 data/config.json（`neko.seeded` 标记防重复覆盖）。渲染层与管理页零感知。

其他 agent 也可以不经桌面端直接管理：`npm start` 后直接调上面的控制面 API。

## 部署约束

- 运行依赖系统 Node.js（拉起方）与本机 Python（插件服务器 sidecar）。
- 需要本机存在 neko 源码目录（默认 `C:\N.E.K.O-main`，可通过 `/config` 修改），源码只读、不被修改。
- 真实插件加载/市场桥行为由 neko 侧决定；桥与注册接收器均为尽力而为，失败不阻断插件服务器。
- 生产打包（把适配器随 Electron 安装包分发）暂未集成，当前按「workspace 内目录 + 系统 Node」方式运行。
