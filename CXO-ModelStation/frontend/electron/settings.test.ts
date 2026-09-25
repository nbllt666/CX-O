// @vitest-environment node
/**
 * 桌面配置持久化单测（归一化 / 读写 / 原子补丁）。
 */
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { afterEach, describe, expect, it } from "vitest";

import {
  configFilePath,
  defaultAppConfig,
  normalizeAppConfig,
  patchAppConfig,
  readAppConfig,
  writeAppConfig,
  APP_CONFIG_FILENAME,
} from "./settings";

const tmpDirs: string[] = [];

function makeTmpDir(): string {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cxo-ms-settings-"));
  tmpDirs.push(dir);
  return dir;
}

afterEach(() => {
  while (tmpDirs.length > 0) {
    const dir = tmpDirs.pop();
    if (dir) fs.rmSync(dir, { recursive: true, force: true });
  }
});

const defaults = defaultAppConfig(path.resolve("C:/Users/x/AppData/Local/CXO-ModelStation/data"));

describe("settings", () => {
  it("defaultAppConfig：后端默认 8300、前端默认 3300", () => {
    expect(defaults.backendBaseUrl).toBe("http://127.0.0.1:8300");
    expect(defaults.preferredFrontendPort).toBe(3300);
  });

  it("normalizeAppConfig：非法输入回退默认、去掉尾斜杠、解析数据根", () => {
    const result = normalizeAppConfig(
      {
        backendBaseUrl: "http://127.0.0.1:9000/",
        dataRoot: "D:/my-data",
        preferredFrontendPort: 99999,
      },
      defaults,
    );
    expect(result.backendBaseUrl).toBe("http://127.0.0.1:9000");
    expect(result.dataRoot).toBe(path.resolve("D:/my-data"));
    expect(result.preferredFrontendPort).toBe(3300);

    const bad = normalizeAppConfig(
      { backendBaseUrl: "ftp://x", dataRoot: "   ", preferredFrontendPort: "abc" },
      defaults,
    );
    expect(bad.backendBaseUrl).toBe(defaults.backendBaseUrl);
    expect(bad.dataRoot).toBe(defaults.dataRoot);
    expect(bad.preferredFrontendPort).toBe(defaults.preferredFrontendPort);
  });

  it("configFilePath 使用 userData 目录 + 固定文件名", () => {
    expect(configFilePath(path.resolve("C:/userData"))).toBe(
      path.join(path.resolve("C:/userData"), APP_CONFIG_FILENAME),
    );
  });

  it("readAppConfig：文件缺失/损坏均回退默认（不抛异常）", () => {
    const dir = makeTmpDir();
    const file = configFilePath(dir);
    expect(readAppConfig(file, defaults)).toEqual(defaults);

    fs.writeFileSync(file, "{ not json", "utf8");
    expect(readAppConfig(file, defaults)).toEqual(defaults);
  });

  it("writeAppConfig + readAppConfig 往返一致", () => {
    const file = configFilePath(makeTmpDir());
    const written = writeAppConfig(file, {
      backendBaseUrl: "http://127.0.0.1:8301",
      dataRoot: path.resolve("D:/data"),
      preferredFrontendPort: 3310,
    });
    expect(readAppConfig(file, defaults)).toEqual(written);
  });

  it("patchAppConfig：局部补丁合并落盘，未提供字段保持原值", () => {
    const file = configFilePath(makeTmpDir());
    writeAppConfig(file, {
      backendBaseUrl: "http://127.0.0.1:8301",
      dataRoot: path.resolve("D:/data"),
      preferredFrontendPort: 3311,
    });
    const patched = patchAppConfig(file, defaults, { dataRoot: "D:/data2" });
    expect(patched.dataRoot).toBe(path.resolve("D:/data2"));
    expect(patched.backendBaseUrl).toBe("http://127.0.0.1:8301");
    expect(patched.preferredFrontendPort).toBe(3311);
    expect(readAppConfig(file, defaults).dataRoot).toBe(path.resolve("D:/data2"));
  });
});