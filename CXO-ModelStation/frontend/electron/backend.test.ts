// @vitest-environment node
/**
 * 后端生命周期 / 布局解析 / 配置组装 / 健康门 / 数据根种子 / 端口顺延 单测。
 */
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import type { ChildProcess, SpawnOptions } from "node:child_process";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  BACKEND_SERVICE_NAME,
  DATA_SEED_MARKER_FILENAME,
  DATA_SEED_VERSION,
  backendCandidatePorts,
  buildBackendConfig,
  buildBackendEnv,
  buildBackendBaseUrl,
  defaultBackendServer,
  isBackendHealthy,
  isDirectoryEmptySync,
  mergePythonPath,
  parseBackendBaseUrl,
  prepareDataRoot,
  resolveBackendEndpoint,
  resolveDataRoot,
  resolveLayout,
  serializeBackendConfig,
  spawnBackend,
  stopBackendProcessTree,
  waitHealthy,
  type DataRootFsLike,
  type FetchLike,
} from "./backend";

const tmpDirs: string[] = [];

function makeTmpDir(): string {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cxo-ms-dataroot-"));
  tmpDirs.push(dir);
  return dir;
}

afterEach(() => {
  while (tmpDirs.length > 0) {
    const dir = tmpDirs.pop();
    if (dir) fs.rmSync(dir, { recursive: true, force: true });
  }
});

// ======================== 路径解析（打包态 vs 开发态） ========================

describe("resolveLayout", () => {
  it("打包态：resources 下解析 backend/runtime/engines/data", () => {
    const resourcesPath = path.resolve("C:/Install/CXO-ModelStation/resources");
    const layout = resolveLayout({
      isPackaged: true,
      resourcesPath,
      moduleDir: path.join(resourcesPath, "app.asar", "dist-electron"),
    });

    expect(layout.mode).toBe("packaged");
    expect(layout.resourcesDir).toBe(resourcesPath);
    expect(layout.installRoot).toBe(path.dirname(resourcesPath));
    expect(layout.backendRoot).toBe(path.join(resourcesPath, "backend"));
    expect(layout.pythonExe).toBe(path.join(resourcesPath, "runtime", "python", "python.exe"));
    expect(layout.dataSeedDir).toBe(path.join(resourcesPath, "data"));
    expect(layout.soVitsSvcDir).toBe(path.join(resourcesPath, "engines", "so-vits-svc-4.1-Stable"));
    expect(layout.voxcpmWorkingDir).toBe(path.join(resourcesPath, "engines", "VoxCPM-main"));
    expect(layout.voxcpmSrcDir).toBe(path.join(resourcesPath, "engines", "VoxCPM-main", "src"));
    expect(layout.melottsEngineDir).toBe(path.join(resourcesPath, "engines", "MeloTTS"));
    expect(layout.frontendDistDir).toBe(path.join(resourcesPath, "app.asar", "dist"));
  });

  it("开发态：仓库根 = moduleDir 上溯两级，python 回退 ..\\py311", () => {
    const repoRoot = path.resolve("C:/CX-O/CXO-ModelStation");
    const layout = resolveLayout({
      isPackaged: false,
      moduleDir: path.join(repoRoot, "frontend", "electron"),
    });

    expect(layout.mode).toBe("dev");
    expect(layout.installRoot).toBe(repoRoot);
    expect(layout.backendRoot).toBe(repoRoot);
    expect(layout.pythonExe).toBe(path.resolve(repoRoot, "..", "py311", "Scripts", "python.exe"));
    expect(layout.frontendDistDir).toBe(path.join(repoRoot, "frontend", "dist"));
    expect(layout.voxcpmSrcDir).toBe(path.join(repoRoot, "engines", "VoxCPM-main", "src"));
  });

  it("开发态：dist-electron 产物目录同样上溯到仓库根", () => {
    const repoRoot = path.resolve("C:/CX-O/CXO-ModelStation");
    const layout = resolveLayout({
      isPackaged: false,
      moduleDir: path.join(repoRoot, "frontend", "dist-electron"),
    });
    expect(layout.backendRoot).toBe(repoRoot);
  });

  it("支持显式覆盖 pythonExe / frontendDistDir", () => {
    const layout = resolveLayout({
      isPackaged: true,
      resourcesPath: path.resolve("C:/Install/resources"),
      moduleDir: path.resolve("C:/Install/resources/app.asar/dist-electron"),
      pythonExe: path.resolve("C:/custom/python.exe"),
      frontendDistDir: path.resolve("C:/custom/dist"),
    });
    expect(layout.pythonExe).toBe(path.resolve("C:/custom/python.exe"));
    expect(layout.frontendDistDir).toBe(path.resolve("C:/custom/dist"));
  });
});

describe("resolveDataRoot", () => {
  it("显式 CXO_MODELSTATION_DATA_ROOT 优先", () => {
    const root = resolveDataRoot({
      CXO_MODELSTATION_DATA_ROOT: "D:/custom-data",
      LOCALAPPDATA: "C:/Users/x/AppData/Local",
    } as NodeJS.ProcessEnv);
    expect(root).toBe(path.resolve("D:/custom-data"));
  });

  it("默认 %LOCALAPPDATA%\\CXO-ModelStation\\data", () => {
    const root = resolveDataRoot({ LOCALAPPDATA: path.resolve("C:/Users/x/AppData/Local") } as NodeJS.ProcessEnv);
    expect(root).toBe(path.join(path.resolve("C:/Users/x/AppData/Local"), "CXO-ModelStation", "data"));
  });

  it("无 LOCALAPPDATA 时逐步回退仍返回绝对路径", () => {
    const root = resolveDataRoot({ APPDATA: path.resolve("C:/Users/x/AppData/Roaming") } as NodeJS.ProcessEnv);
    expect(path.isAbsolute(root)).toBe(true);
    expect(root).toContain("CXO-ModelStation");
  });
});

// ======================== 配置组装 ========================

describe("buildBackendConfig / serializeBackendConfig", () => {
  const layout = resolveLayout({
    isPackaged: true,
    resourcesPath: path.resolve("C:/Install/resources"),
    moduleDir: path.resolve("C:/Install/resources/app.asar/dist-electron"),
  });
  const dataRoot = path.resolve("C:/Users/x/AppData/Local/CXO-ModelStation/data");

  it("字段名与后端 config.py 对齐，路径指向包内引擎与数据根子目录", () => {
    const config = buildBackendConfig(layout, dataRoot);

    expect(config.server).toEqual({ host: "127.0.0.1", port: 8300 });
    expect(config.sovits_svc.python_path).toBe(layout.pythonExe);
    expect(config.sovits_svc.so_vits_svc_dir).toBe(layout.soVitsSvcDir);
    expect(config.sovits_svc.training_data_dir).toBe(path.join(dataRoot, "training", "sovits_svc"));
    expect(config.sovits_svc.models_dir).toBe(path.join(dataRoot, "models", "sovits_svc"));
    expect(config.sovits_svc.audition_dir).toBe(path.join(dataRoot, "audition"));
    expect(config.sovits_svc.input_dir).toBe(path.join(dataRoot, "input"));

    expect(config.voxcpm.working_dir).toBe(layout.voxcpmWorkingDir);

    expect(config.melotts.python_path).toBe(layout.pythonExe);
    expect(config.melotts.engine_dir).toBe(layout.melottsEngineDir);
    expect(config.melotts.training_data_dir).toBe(path.join(dataRoot, "training", "melotts"));
    expect(config.melotts.models_dir).toBe(path.join(dataRoot, "models", "melotts"));
  });

  it("serializeBackendConfig 产出可反序列化 JSON（Windows 反斜杠安全）", () => {
    const parsed = JSON.parse(serializeBackendConfig(layout, dataRoot)) as ReturnType<
      typeof buildBackendConfig
    >;
    expect(parsed.sovits_svc.python_path).toBe(layout.pythonExe);
    expect(Object.keys(parsed)).toEqual(["server", "sovits_svc", "voxcpm", "melotts"]);
  });

  it("顺延后注入实际 server 端点（host/port 覆盖默认 8300）", () => {
    const config = buildBackendConfig(layout, dataRoot, { host: "127.0.0.1", port: 8310 });
    expect(config.server).toEqual({ host: "127.0.0.1", port: 8310 });
    const env = buildBackendEnv(layout, dataRoot, {} as NodeJS.ProcessEnv, {
      host: "127.0.0.1",
      port: 8320,
    });
    expect(JSON.parse(env.CXO_MODELSTATION_CONFIG).server.port).toBe(8320);
  });

  it("mergePythonPath 保留既有 PYTHONPATH 并前置引擎 src", () => {
    expect(mergePythonPath("C:/engines/VoxCPM-main/src")).toBe("C:/engines/VoxCPM-main/src");
    expect(mergePythonPath("C:/engines/VoxCPM-main/src", "C:/other")).toBe(
      `C:/engines/VoxCPM-main/src${path.delimiter}C:/other`,
    );
  });

  it("buildBackendEnv 注入 CXO_MODELSTATION_CONFIG / PYTHONPATH / PYTHONUNBUFFERED", () => {
    const env = buildBackendEnv(layout, dataRoot, {
      PATH: "C:/Windows",
      PYTHONPATH: "C:/existing",
    } as NodeJS.ProcessEnv);

    expect(env.PATH).toBe("C:/Windows");
    expect(env.PYTHONPATH).toBe(`${layout.voxcpmSrcDir}${path.delimiter}C:/existing`);
    expect(env.PYTHONUNBUFFERED).toBe("1");
    const parsed = JSON.parse(env.CXO_MODELSTATION_CONFIG) as { melotts: { engine_dir: string } };
    expect(parsed.melotts.engine_dir).toBe(layout.melottsEngineDir);
  });
});

// ======================== isBackendHealthy 判定 ========================

function fetchReturning(body: unknown, options: { ok?: boolean; delayMs?: number } = {}): FetchLike {
  return (async (_input: string, init?: { signal?: AbortSignal }) => {
    if (options.delayMs) {
      await new Promise<void>((resolve, reject) => {
        const timer = setTimeout(() => resolve(), options.delayMs);
        init?.signal?.addEventListener("abort", () => {
          clearTimeout(timer);
          reject(new Error("aborted"));
        });
      });
    }
    return { ok: options.ok ?? true, json: async () => body };
  }) as FetchLike;
}

describe("isBackendHealthy", () => {
  it("healthy + service 匹配 → true", async () => {
    const result = await isBackendHealthy({
      baseUrl: "http://127.0.0.1:8300/",
      fetchImpl: fetchReturning({ status: "healthy", service: BACKEND_SERVICE_NAME }),
    });
    expect(result).toBe(true);
  });

  it.each([
    ["status 非 healthy", { status: "degraded", service: BACKEND_SERVICE_NAME }],
    ["service 不匹配", { status: "healthy", service: "OtherService" }],
    ["字段缺失", { foo: "bar" }],
  ])("%s → false", async (_name, body) => {
    expect(await isBackendHealthy({ baseUrl: "http://127.0.0.1:8300", fetchImpl: fetchReturning(body) })).toBe(false);
  });

  it("HTTP 非 2xx → false", async () => {
    expect(
      await isBackendHealthy({
        baseUrl: "http://127.0.0.1:8300",
        fetchImpl: fetchReturning({ status: "healthy", service: BACKEND_SERVICE_NAME }, { ok: false }),
      }),
    ).toBe(false);
  });

  it("网络异常（后端不可达）→ false，不抛异常", async () => {
    const failing: FetchLike = async () => {
      throw new Error("ECONNREFUSED");
    };
    expect(await isBackendHealthy({ baseUrl: "http://127.0.0.1:8399", fetchImpl: failing })).toBe(false);
  });

  it("超时（短超时内未响应）→ false", async () => {
    const result = await isBackendHealthy({
      baseUrl: "http://127.0.0.1:8300",
      fetchImpl: fetchReturning({ status: "healthy", service: BACKEND_SERVICE_NAME }, { delayMs: 200 }),
      timeoutMs: 30,
    });
    expect(result).toBe(false);
  });
});

// ======================== 健康门（waitHealthy） ========================

describe("waitHealthy", () => {
  it("首次即健康 → healthy=true, attempts=1", async () => {
    const result = await waitHealthy({
      baseUrl: "http://127.0.0.1:8300",
      timeoutMs: 1000,
      intervalMs: 10,
      isHealthy: async () => true,
      sleep: async () => {},
    });
    expect(result.healthy).toBe(true);
    expect(result.attempts).toBe(1);
  });

  it("前两次失败后成功 → attempts=3", async () => {
    let calls = 0;
    const result = await waitHealthy({
      baseUrl: "http://127.0.0.1:8300",
      timeoutMs: 10_000,
      intervalMs: 10,
      isHealthy: async () => {
        calls += 1;
        return calls >= 3;
      },
      sleep: async () => {},
    });
    expect(result.healthy).toBe(true);
    expect(result.attempts).toBe(3);
  });

  it("始终失败且超时 → healthy=false 并给出可读原因", async () => {
    const result = await waitHealthy({
      baseUrl: "http://127.0.0.1:8400/",
      timeoutMs: 100,
      intervalMs: 20,
      isHealthy: async () => false,
      sleep: async () => {},
    });
    expect(result.healthy).toBe(false);
    expect(result.attempts).toBeGreaterThan(1);
    expect(result.reason).toContain("健康检查");
    expect(result.reason).toContain("http://127.0.0.1:8400/health");
  });

  it("timeoutMs=0 → 只尝试一次即失败", async () => {
    const result = await waitHealthy({
      baseUrl: "http://127.0.0.1:8300",
      timeoutMs: 0,
      intervalMs: 20,
      isHealthy: async () => false,
      sleep: async () => {},
    });
    expect(result.healthy).toBe(false);
    expect(result.attempts).toBe(1);
  });
});

// ======================== spawn / stop ========================

describe("spawnBackend", () => {
  const layout = resolveLayout({
    isPackaged: true,
    resourcesPath: path.resolve("C:/Install/resources"),
    moduleDir: path.resolve("C:/Install/resources/app.asar/dist-electron"),
  });
  const dataRoot = path.resolve("C:/data-root");

  it("以 cwd=包内 backend 根、注入 env 拉起 `-m modelstation.main`", () => {
    const spawnImpl = vi.fn((_command: string, _args: string[], _options: SpawnOptions) => ({ pid: 123 }) as unknown as ChildProcess);
    spawnBackend({ layout, dataRoot, env: {} as NodeJS.ProcessEnv, spawnImpl });

    expect(spawnImpl).toHaveBeenCalledTimes(1);
    const [command, args, options] = spawnImpl.mock.calls[0];
    expect(command).toBe(layout.pythonExe);
    expect(args).toEqual(["-m", "modelstation.main"]);
    expect(options.cwd).toBe(layout.backendRoot);
    expect(options.windowsHide).toBe(true);
    const env = options.env as Record<string, string>;
    expect(JSON.parse(env.CXO_MODELSTATION_CONFIG).melotts.engine_dir).toBe(layout.melottsEngineDir);
    expect(env.PYTHONPATH).toBe(layout.voxcpmSrcDir);
  });

  it("顺延端点经 server 注入 CXO_MODELSTATION_CONFIG", () => {
    const spawnImpl = vi.fn((_command: string, _args: string[], _options: SpawnOptions) => ({ pid: 123 }) as unknown as ChildProcess);
    spawnBackend({ layout, dataRoot, env: {} as NodeJS.ProcessEnv, spawnImpl, server: { host: "127.0.0.1", port: 8310 } });

    const env = spawnImpl.mock.calls[0][2].env as Record<string, string>;
    expect(JSON.parse(env.CXO_MODELSTATION_CONFIG).server).toEqual({ host: "127.0.0.1", port: 8310 });
  });
});

describe("stopBackendProcessTree", () => {
  it("Windows 使用 taskkill /T /F 并成功返回 true", async () => {
    const execImpl = vi.fn((_file: string, _args: string[], _options: unknown, callback: (e: Error | null) => void) => {
      callback(null);
      return null;
    });
    const ok = await stopBackendProcessTree(4321, { platform: "win32", execImpl });
    expect(ok).toBe(true);
    expect(execImpl.mock.calls[0][0]).toBe("taskkill");
    expect(execImpl.mock.calls[0][1]).toEqual(["/PID", "4321", "/T", "/F"]);
  });

  it("Windows taskkill 失败（进程已退出）返回 false", async () => {
    const execImpl = vi.fn((_file: string, _args: string[], _options: unknown, callback: (e: Error | null) => void) => {
      callback(new Error("not found"));
      return null;
    });
    expect(await stopBackendProcessTree(4321, { platform: "win32", execImpl })).toBe(false);
  });

  it("非 Windows 走 SIGTERM", async () => {
    const killImpl = vi.fn();
    expect(await stopBackendProcessTree(99, { platform: "linux", killImpl })).toBe(true);
    expect(killImpl).toHaveBeenCalledWith(99, "SIGTERM");
  });

  it("非法 pid 直接返回 false（不执行任何杀死动作）", async () => {
    const execImpl = vi.fn();
    expect(await stopBackendProcessTree(0, { platform: "win32", execImpl })).toBe(false);
    expect(await stopBackendProcessTree(Number.NaN, { platform: "win32", execImpl })).toBe(false);
    expect(execImpl).not.toHaveBeenCalled();
  });
});

// ======================== 数据根落地与种子（4.3） ========================

function makeSeedDir(): string {
  const seed = path.join(makeTmpDir(), "resources-data");
  fs.mkdirSync(path.join(seed, "training", "melotts", "spk_a"), { recursive: true });
  fs.writeFileSync(path.join(seed, "training", "melotts", "spk_a", "train.txt"), "hello", "utf8");
  fs.writeFileSync(path.join(seed, "training", "melotts", "manifest.json"), "{}", "utf8");
  return seed;
}

describe("isDirectoryEmptySync", () => {
  it("不存在/空目录 → true；有内容 → false", () => {
    const dir = makeTmpDir();
    expect(isDirectoryEmptySync(path.join(dir, "nope"))).toBe(true);
    expect(isDirectoryEmptySync(dir)).toBe(true);
    fs.writeFileSync(path.join(dir, "a.txt"), "x", "utf8");
    expect(isDirectoryEmptySync(dir)).toBe(false);
  });
});

describe("prepareDataRoot", () => {
  it("首次启动：拷贝包内种子（含子目录结构）并写幂等标记", () => {
    const seedDir = makeSeedDir();
    const dataRoot = path.join(makeTmpDir(), "data");

    const result = prepareDataRoot({ dataRoot, seedDir });

    expect(result.ok).toBe(true);
    expect(result.seeded).toBe(true);
    expect(result.skippedSeed).toBe(false);
    expect(result.copiedFrom).toBe(path.resolve(seedDir));
    expect(fs.readFileSync(path.join(dataRoot, "training", "melotts", "spk_a", "train.txt"), "utf8")).toBe("hello");
    expect(fs.existsSync(path.join(dataRoot, "training", "melotts", "manifest.json"))).toBe(true);
    // 注入给后端的 6 个可写子目录均已建立
    expect(result.createdDirs).toHaveLength(6);
    for (const rel of ["training/sovits_svc", "models/sovits_svc", "audition", "input", "training/melotts", "models/melotts"]) {
      expect(fs.statSync(path.join(dataRoot, rel)).isDirectory()).toBe(true);
    }
    const marker = JSON.parse(fs.readFileSync(path.join(dataRoot, DATA_SEED_MARKER_FILENAME), "utf8"));
    expect(marker.version).toBe(DATA_SEED_VERSION);
    expect(marker.seeded).toBe(true);
  });

  it("重复启动：标记存在 → 跳过种子拷贝且不覆盖用户数据（哨兵文件保留）", () => {
    const seedDir = makeSeedDir();
    const dataRoot = path.join(makeTmpDir(), "data");
    prepareDataRoot({ dataRoot, seedDir });

    const sentinel = path.join(dataRoot, "training", "melotts", "spk_a", "train.txt");
    fs.writeFileSync(sentinel, "USER-MODEL", "utf8");
    const userFile = path.join(dataRoot, "models", "sovits_svc", "my_model.pth");
    fs.writeFileSync(userFile, "weights", "utf8");

    const second = prepareDataRoot({ dataRoot, seedDir });

    expect(second.ok).toBe(true);
    expect(second.seeded).toBe(false);
    expect(second.skippedSeed).toBe(true);
    expect(second.reason).toContain("幂等");
    expect(fs.readFileSync(sentinel, "utf8")).toBe("USER-MODEL");
    expect(fs.readFileSync(userFile, "utf8")).toBe("weights");
  });

  it("数据根非空且无标记：尊重既有数据，不拷贝种子", () => {
    const seedDir = makeSeedDir();
    const dataRoot = makeTmpDir();
    fs.writeFileSync(path.join(dataRoot, "existing.txt"), "keep", "utf8");

    const result = prepareDataRoot({ dataRoot, seedDir });

    expect(result.ok).toBe(true);
    expect(result.seeded).toBe(false);
    expect(result.reason).toContain("非空");
    expect(fs.existsSync(path.join(dataRoot, "training", "melotts", "spk_a", "train.txt"))).toBe(false);
    expect(fs.readFileSync(path.join(dataRoot, "existing.txt"), "utf8")).toBe("keep");
  });

  it("只读/不可写：返回可读 error 而非崩溃", () => {
    const seedDir = makeSeedDir();
    const dataRoot = path.join(makeTmpDir(), "readonly");
    const fsImpl: DataRootFsLike = {
      existsSync: fs.existsSync,
      readdirSync: () => [],
      mkdirSync: (p, options) => {
        if (path.resolve(p) === path.resolve(dataRoot)) {
          const error = new Error("EPERM: operation not permitted") as Error & { code?: string };
          error.code = "EPERM";
          throw error;
        }
        return fs.mkdirSync(p, options);
      },
      cpSync: fs.cpSync,
      writeFileSync: fs.writeFileSync,
    };

    const result = prepareDataRoot({ dataRoot, seedDir, fsImpl });

    expect(result.ok).toBe(false);
    expect(result.seeded).toBe(false);
    expect(result.error).toContain("数据根不可写");
    expect(result.error).toContain("CXO_MODELSTATION_DATA_ROOT");
  });

  it("包内种子目录缺失：仅初始化空数据根（ok=true）", () => {
    const dataRoot = path.join(makeTmpDir(), "data");
    const result = prepareDataRoot({ dataRoot, seedDir: path.join(makeTmpDir(), "missing-seed") });
    expect(result.ok).toBe(true);
    expect(result.seeded).toBe(false);
    expect(result.reason).toContain("种子目录缺失");
  });
});

// ======================== 后端端点解析与端口顺延（4.6） ========================

describe("parseBackendBaseUrl / buildBackendBaseUrl / backendCandidatePorts", () => {
  it("解析 host/port，非法回退默认 127.0.0.1:8300", () => {
    expect(parseBackendBaseUrl("http://127.0.0.1:8300")).toEqual({ host: "127.0.0.1", port: 8300 });
    expect(parseBackendBaseUrl("http://localhost:9000/")).toEqual({ host: "localhost", port: 9000 });
    expect(parseBackendBaseUrl("not-a-url")).toEqual(defaultBackendServer());
  });

  it("base 拼接与顺延序列（步长 10，含首选）", () => {
    expect(buildBackendBaseUrl("127.0.0.1", 8310)).toBe("http://127.0.0.1:8310");
    expect(backendCandidatePorts(8300, 5)).toEqual([8300, 8310, 8320, 8330, 8340]);
  });
});

describe("resolveBackendEndpoint", () => {
  it("目标空闲 → 使用默认端口（不换端口）", async () => {
    const resolved = await resolveBackendEndpoint({
      baseUrl: "http://127.0.0.1:8300",
      isHealthy: async () => false,
      isPortFree: async () => true,
    });
    expect(resolved.port).toBe(8300);
    expect(resolved.reused).toBe(false);
    expect(resolved.changed).toBe(false);
  });

  it("目标被非 ModelStation 占用 → 顺延到下一个空闲端口", async () => {
    const probed: number[] = [];
    const resolved = await resolveBackendEndpoint({
      baseUrl: "http://127.0.0.1:8300",
      isHealthy: async () => false,
      isPortFree: async (port: number) => {
        probed.push(port);
        return port !== 8300;
      },
    });
    expect(resolved.baseUrl).toBe("http://127.0.0.1:8310");
    expect(resolved.port).toBe(8310);
    expect(resolved.changed).toBe(true);
    expect(probed[0]).toBe(8300);
  });

  it("已有健康 ModelStation → 复用，不拉起（changed=false）", async () => {
    const resolved = await resolveBackendEndpoint({
      baseUrl: "http://127.0.0.1:8300",
      isHealthy: async () => true,
      isPortFree: async () => {
        throw new Error("不应探测端口");
      },
    });
    expect(resolved.reused).toBe(true);
    expect(resolved.changed).toBe(false);
    expect(resolved.baseUrl).toBe("http://127.0.0.1:8300");
  });

  it("顺延端口上已有健康 ModelStation → 复用该顺延端口", async () => {
    const resolved = await resolveBackendEndpoint({
      baseUrl: "http://127.0.0.1:8300",
      isHealthy: async (baseUrl: string) => baseUrl.endsWith(":8310"),
      isPortFree: async () => false,
    });
    expect(resolved.reused).toBe(true);
    expect(resolved.changed).toBe(true);
    expect(resolved.baseUrl).toBe("http://127.0.0.1:8310");
  });

  it("全部候选不可用 → 抛出可读错误（不空转）", async () => {
    await expect(
      resolveBackendEndpoint({
        baseUrl: "http://127.0.0.1:8300",
        isHealthy: async () => false,
        isPortFree: async () => false,
        maxTries: 3,
      }),
    ).rejects.toThrow(/8300-8320 均不可用/);
  });
});