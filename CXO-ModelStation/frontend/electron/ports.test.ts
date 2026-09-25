// @vitest-environment node
/**
 * 端口顺延逻辑单测（纯函数 + 真实探针）。
 */
import * as net from "node:net";
import { describe, expect, it } from "vitest";

import {
  candidatePorts,
  createPortProbe,
  DEFAULT_PORT,
  DEFAULT_PORT_MAX_TRIES,
  isPortInUseError,
  nextCandidatePort,
  pickAvailablePort,
} from "./ports";

async function listenEphemeral(): Promise<{ server: net.Server; port: number }> {
  const server = net.createServer();
  await new Promise<void>((resolve) => server.listen({ host: "127.0.0.1", port: 0 }, () => resolve()));
  const address = server.address();
  const port = typeof address === "object" && address ? address.port : 0;
  return { server, port };
}

describe("ports", () => {
  it("默认常量符合冻结契约（3300 起、3300..3310）", () => {
    expect(DEFAULT_PORT).toBe(3300);
    expect(DEFAULT_PORT_MAX_TRIES).toBe(11);
    expect(candidatePorts(3300, 11)).toEqual([3300, 3301, 3302, 3303, 3304, 3305, 3306, 3307, 3308, 3309, 3310]);
  });

  it("nextCandidatePort 按序号递增", () => {
    expect(nextCandidatePort(3300, 0)).toBe(3300);
    expect(nextCandidatePort(3300, 3)).toBe(3303);
  });

  it("pickAvailablePort：跳过被占用端口返回首个空闲端口", async () => {
    const seen: number[] = [];
    const port = await pickAvailablePort(
      3300,
      async (candidate) => {
        seen.push(candidate);
        return candidate >= 3302;
      },
      3,
    );
    expect(port).toBe(3302);
    expect(seen).toEqual([3300, 3301, 3302]);
  });

  it("pickAvailablePort：全部占用时抛出可读错误", async () => {
    await expect(pickAvailablePort(3300, async () => false, 3)).rejects.toThrow(
      /3300-3302 均被占用/,
    );
  });

  it("createPortProbe：真实占用端口返回 false，空闲端口返回 true", async () => {
    const probe = createPortProbe("127.0.0.1");
    const { server, port } = await listenEphemeral();
    try {
      expect(await probe(port)).toBe(false);
    } finally {
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
    // 端口已释放，探针应判定为空闲
    expect(await probe(port)).toBe(true);
  });

  it("isPortInUseError 仅识别 EADDRINUSE", () => {
    expect(isPortInUseError({ code: "EADDRINUSE" })).toBe(true);
    expect(isPortInUseError({ code: "ECONNREFUSED" })).toBe(false);
    expect(isPortInUseError(new Error("boom"))).toBe(false);
  });
});