/**
 * E2E 生命周期验证（s0402 Test2 承载，重跑入口：node tests/e2e-lifecycle.mjs）
 * ============================================================================
 * 真实驱动适配器（node dist/index.js）全生命周期：
 *   health → config 预置 → start（桩插件服务器就绪）→ status/bridge 断言 →
 *   改端口配置 + restart（修复语义：/status.port 为新值且可连）→ stop →
 *   SIGTERM 退出 → 孤儿进程/端口残留检查。
 *
 * 隔离手段：
 *   - CXO_NEKO_ADAPTER_DATA_DIR 指向临时 data 目录（配置/证书不污染项目 data/）
 *   - sourceDir 指向临时目录内的 python 桩（tests/fixtures/plugin_server_stub.py）
 *   - 控制面/插件端口均从预设基址起动态探测空闲
 * ============================================================================
 */
import { spawn, execSync } from 'node:child_process';
import { mkdtempSync, mkdirSync, writeFileSync, copyFileSync, rmSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import * as path from 'node:path';
import * as net from 'node:net';
import { fileURLToPath } from 'node:url';

const TESTS_DIR = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(TESTS_DIR, '..');
const DIST_INDEX = path.join(ROOT, 'dist', 'index.js');
const STUB_SRC = path.join(TESTS_DIR, 'fixtures', 'plugin_server_stub.py');
const REGISTRAR_PORT = 48911; // 与 src/bridge/toolBridge.ts NEKO_MAIN_SERVER_REGISTER_PORT 一致
const BRIDGE_BASE_PORT = 28443; // 与 BRIDGE_BASE_PORT 一致

const results = [];
let assertSeq = 0;

function report(name, pass, detail) {
  assertSeq += 1;
  const line = `[ASSERT #${assertSeq}] ${name}: ${pass ? 'PASS' : 'FAIL'}${detail ? ` — ${detail}` : ''}`;
  console.log(line);
  results.push({ seq: assertSeq, name, pass, detail: detail ?? null });
}

function section(title) {
  console.log(`\n===== ${title} =====`);
}

/** 探测 host:port 是否可建立 TCP 连接（可连 = 端口被监听） */
function canConnect(port, timeoutMs = 800) {
  return new Promise((resolve) => {
    const sock = net.createConnection({ host: '127.0.0.1', port });
    const done = (v) => { sock.destroy(); resolve(v); };
    sock.once('connect', () => done(true));
    sock.once('error', () => done(false));
    sock.setTimeout(timeoutMs, () => done(false));
  });
}

/** 从 base 起找一个空闲端口（步进 10 避开相邻断言端口） */
async function pickFreePort(base) {
  for (let p = base; p < base + 200; p += 10) {
    if (await canConnect(p, 200) === false) return p;
  }
  throw new Error(`找不到空闲端口（base=${base}）`);
}

async function fetchJson(method, port, pathname, body, timeoutMs = 8000) {
  const res = await fetch(`http://127.0.0.1:${port}${pathname}`, {
    method,
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
    signal: AbortSignal.timeout(timeoutMs),
  });
  const text = await res.text();
  let json = null;
  try { json = JSON.parse(text); } catch { /* 非 JSON 保留 null */ }
  return { status: res.status, json, text };
}

/** netstat 检查端口是否仍有 LISTENING 残留 */
function isPortListened(port) {
  const out = execSync('netstat -ano -p tcp', { encoding: 'utf-8' });
  const re = new RegExp(`:\\s*${port}\\s+[^\\r\\n]*LISTENING`, 'i');
  return re.test(out);
}

/** tasklist 快照当前 python.exe 进程 PID 集合 */
function pythonPids() {
  try {
    const out = execSync('tasklist /FI "IMAGENAME eq python.exe" /FO CSV /NH', { encoding: 'utf-8' });
    const pids = [];
    for (const line of out.split(/\r?\n/)) {
      const m = /^"python\.exe","(\d+)"/i.exec(line.trim());
      if (m) pids.push(m[1]);
    }
    return pids;
  } catch {
    return [];
  }
}

async function main() {
  section('E2E 前置检查');
  if (!existsSync(DIST_INDEX)) throw new Error(`dist/index.js 不存在，请先 npm run build：${DIST_INDEX}`);
  if (!existsSync(STUB_SRC)) throw new Error(`桩脚本不存在：${STUB_SRC}`);
  console.log(`dist/index.js 与桩脚本就绪`);

  const controlBase = await pickFreePort(48921);
  const pluginP1 = await pickFreePort(48931);
  const pluginP2 = await pickFreePort(48941);
  const registrarFreeBefore = !(await canConnect(REGISTRAR_PORT, 200));
  console.log(`端口分配：控制面基址=${controlBase} 插件P1=${pluginP1} 插件P2=${pluginP2}`);
  console.log(`48911（注册接收器）启动前${registrarFreeBefore ? '空闲 → 将断言 registrarRunning=true' : '被占用 → 属环境问题，该项断言记录并跳过，不得伪造'}`);

  const pidsBefore = pythonPids();
  console.log(`python.exe 启动前快照 PID：[${pidsBefore.join(', ')}]`);

  // ── 临时环境 ──
  const tmp = mkdtempSync(path.join(tmpdir(), 'cxo-neko-e2e-'));
  const dataDir = path.join(tmp, 'data');
  const sourceDir = path.join(tmp, 'source');
  mkdirSync(path.join(dataDir, 'certs'), { recursive: true });
  mkdirSync(path.join(sourceDir, 'plugin'), { recursive: true });
  writeFileSync(path.join(sourceDir, 'plugin', '__init__.py'), '', 'utf-8');
  copyFileSync(STUB_SRC, path.join(sourceDir, 'plugin', 'user_plugin_server.py'));
  writeFileSync(
    path.join(dataDir, 'config.json'),
    JSON.stringify({ python: 'python', sourceDir, port: pluginP1, backendUrl: 'http://127.0.0.1:8000', controlPort: 48920, autoStart: false }, null, 2),
    'utf-8',
  );
  console.log(`临时目录：${tmp}`);

  // ── 启动适配器 ──
  section('启动适配器 node dist/index.js --port');
  const adapter = spawn(process.execPath, [DIST_INDEX, '--port', String(controlBase)], {
    cwd: ROOT,
    env: { ...process.env, CXO_NEKO_ADAPTER_DATA_DIR: dataDir },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  const adapterLog = [];
  adapter.stdout.on('data', (c) => adapterLog.push(String(c)));
  adapter.stderr.on('data', (c) => adapterLog.push(String(c)));

  let controlPort = null;
  for (let i = 0; i < 60; i++) {
    for (let p = controlBase; p < controlBase + 12; p++) {
      try {
        const r = await fetchJson('GET', p, '/health', undefined, 1000);
        if (r.status === 200 && r.json?.status === 'ok') { controlPort = p; break; }
      } catch { /* 未就绪，继续 */ }
    }
    if (controlPort) break;
    await new Promise((r) => setTimeout(r, 500));
  }
  if (!controlPort) {
    adapter.kill('SIGKILL');
    throw new Error(`适配器 /health 30s 内未就绪（基址 ${controlBase}）。\n适配器日志：\n${adapterLog.join('')}`);
  }
  console.log(`适配器控制面实际端口：${controlPort}`);
  console.log(`适配器启动日志：\n${adapterLog.join('')}`);

  try {
    // ── 阶段 1：health / start / status / bridge ──
    section('阶段1：health → config → start → 插件端口 → status/bridge');
    const h = await fetchJson('GET', controlPort, '/health');
    report('A1 GET /health 返回 ok 且 service=cxo-neko-adapter', h.status === 200 && h.json?.ok === true && h.json?.service === 'cxo-neko-adapter', JSON.stringify(h.json));

    const cfgPut = await fetchJson('PUT', controlPort, '/config', { python: 'python', sourceDir, port: pluginP1 }, 10000);
    report('A2 PUT /config 预置桩源码目录与插件端口 P1', cfgPut.status === 200 && cfgPut.json?.port === pluginP1, JSON.stringify(cfgPut.json));

    const start = await fetchJson('POST', controlPort, '/start', {}, 60000);
    report('A3 POST /start 返回 ok 且 port=P1 且 bridge=true', start.status === 200 && start.json?.ok === true && start.json?.port === pluginP1 && start.json?.bridge === true, JSON.stringify(start.json));

    const pluginUp = await canConnect(pluginP1);
    const pluginHttp = pluginUp ? await fetchJson('GET', pluginP1, '/') : null;
    report('A4 插件端口 P1 可连且桩响应 200（插件服务器就绪）', pluginHttp?.status === 200 && pluginHttp?.json?.ok === true, pluginHttp ? JSON.stringify(pluginHttp.json) : `TCP 不可连（port=${pluginP1}）`);

    const st1 = await fetchJson('GET', controlPort, '/status');
    const bridge = st1.json?.bridge;
    report('A5 GET /status running=true 且 port=P1', st1.status === 200 && st1.json?.running === true && st1.json?.port === pluginP1, JSON.stringify({ running: st1.json?.running, port: st1.json?.port }));

    const bridgeShapeOk = !!bridge && typeof bridge === 'object'
      && typeof bridge.registrarRunning === 'boolean'
      && typeof bridge.bridgeRunning === 'boolean'
      && (bridge.bridgePort === null || typeof bridge.bridgePort === 'number')
      && typeof bridge.tools === 'number'
      && typeof bridge.cxfcRegistered === 'boolean';
    report('A6 /status.bridge 字段存在且结构完整（registrarRunning/bridgeRunning/bridgePort/tools/cxfcRegistered）', bridgeShapeOk, JSON.stringify(bridge));

    report('A7 桥监听端口 ≥28443 且 bridgeRunning=true', bridge?.bridgeRunning === true && typeof bridge?.bridgePort === 'number' && bridge.bridgePort >= BRIDGE_BASE_PORT, JSON.stringify(bridge));

    if (registrarFreeBefore) {
      report('A8 注册接收器 48911 已监听（registrarRunning=true）', bridge?.registrarRunning === true, `registrarRunning=${bridge?.registrarRunning}`);
    } else {
      report('A8 注册接收器 48911（SKIP：启动前 48911 已被占用，属环境问题，不伪造断言）', true, 'SKIPPED — registrarFreeBefore=false');
      results[results.length - 1].skipped = true;
      results[results.length - 1].pass = true;
    }

    // ── 阶段 2：restart 端口刷新修复语义 ──
    section('阶段2：PUT /config 换端口 P2 → restart → /status.port 为新值且可连');
    const cfgPut2 = await fetchJson('PUT', controlPort, '/config', { port: pluginP2 }, 10000);
    report('A9 PUT /config 将插件端口改为 P2', cfgPut2.status === 200 && cfgPut2.json?.port === pluginP2, JSON.stringify(cfgPut2.json));

    const restart = await fetchJson('POST', controlPort, '/restart', {}, 60000);
    report('A10 POST /restart 返回 ok 且 port=P2（重启后端口刷新为新配置值）', restart.status === 200 && restart.json?.ok === true && restart.json?.port === pluginP2 && restart.json?.bridge === true, JSON.stringify(restart.json));

    const st2 = await fetchJson('GET', controlPort, '/status');
    report('A11 重启后 GET /status running=true 且 port=P2（新值）', st2.status === 200 && st2.json?.running === true && st2.json?.port === pluginP2, JSON.stringify({ running: st2.json?.running, port: st2.json?.port }));

    const st2Http = await fetchJson('GET', pluginP2, '/', undefined, 5000);
    report('A12 重启后 /status.port（P2）真实可连且桩响应 200（修复语义验证）', st2Http.status === 200 && st2Http.json?.ok === true, JSON.stringify(st2Http.json));

    // ── 阶段 3：stop / SIGTERM / 孤儿检查 ──
    section('阶段3：stop → running=false → SIGTERM 退出 → 孤儿与端口残留');
    const stop = await fetchJson('POST', controlPort, '/stop', {}, 30000);
    report('A13 POST /stop 返回 ok', stop.status === 200 && stop.json?.ok === true, JSON.stringify(stop.json));

    const st3 = await fetchJson('GET', controlPort, '/status');
    report('A14 停止后 GET /status running=false 且 port=null', st3.status === 200 && st3.json?.running === false && st3.json?.port === null, JSON.stringify({ running: st3.json?.running, port: st3.json?.port }));

    const pluginDown = !(await canConnect(pluginP2, 800));
    report('A15 停止后插件端口 P2 不再可连（桩进程已被终止）', pluginDown, `port=${pluginP2} 可连=${!pluginDown}`);

    const exited = new Promise((resolve) => adapter.once('exit', (code, signal) => resolve({ code, signal })));
    adapter.kill('SIGTERM');
    const exitInfo = await Promise.race([exited, new Promise((r) => setTimeout(() => r(null), 10000))]);
    report('A16 适配器进程 SIGTERM 后退出（Windows 下 SIGTERM 经 TerminateProcess 终止，exit code 记录实际值）', exitInfo !== null, exitInfo ? `exitCode=${exitInfo.code} signal=${exitInfo.signal}` : '10s 内未退出');

    const pidsAfter = pythonPids();
    const newPythons = pidsAfter.filter((p) => !pidsBefore.includes(p));
    report('A17 无新增 python.exe 孤儿进程', newPythons.length === 0, `before=[${pidsBefore.join(',')}] after=[${pidsAfter.join(',')}] 新增=[${newPythons.join(',')}]`);

    const residualPorts = [];
    for (const p of [controlPort, pluginP1, pluginP2]) {
      if (isPortListened(p)) residualPorts.push(p);
    }
    report('A18 控制面/插件端口（含中间 P1）无 LISTENING 残留', residualPorts.length === 0, residualPorts.length ? `残留端口：${residualPorts.join(', ')}` : `检查端口：${controlPort}, ${pluginP1}, ${pluginP2} 均已释放`);
  } finally {
    section('清理');
    if (adapter.exitCode === null && !adapter.killed) {
      adapter.kill('SIGKILL');
      console.log('兜底：适配器进程未退出，已 SIGKILL');
    }
    try { rmSync(tmp, { recursive: true, force: true }); console.log(`临时目录已清理：${tmp}`); } catch (e) { console.log(`临时目录清理失败（保留现场）：${e?.message ?? e}`); }
  }

  // ── 汇总 ──
  section('E2E 汇总');
  const failed = results.filter((r) => !r.pass);
  const skipped = results.filter((r) => r.skipped);
  for (const r of results) console.log(`${r.pass ? '✓' : '✗'}${r.skipped ? '(SKIP)' : ''} #${r.seq} ${r.name}${r.detail ? ` — ${r.detail}` : ''}`);
  console.log(`\n总计：${results.length} 项断言，通过 ${results.length - failed.length}（含跳过 ${skipped.length}），失败 ${failed.length}`);
  if (failed.length > 0) {
    console.log(`[E2E] RESULT: FAILED`);
    process.exit(1);
  }
  console.log(`[E2E] RESULT: PASSED`);
}

main().catch((err) => {
  console.error(`[E2E] 异常终止: ${err?.stack ?? err}`);
  console.log(`[E2E] RESULT: FAILED`);
  process.exit(1);
});
