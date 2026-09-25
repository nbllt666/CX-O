/*
 * 连接设置页测试（浏览器降级形态）：单次健康检查、无轮询风暴、不可达引导文案。
 */
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ConnectionPage from "./ConnectionPage";

function healthyFetch() {
  return vi.fn(async (_input: string) => ({
    ok: true,
    json: async () => ({ status: "healthy", service: "CXO-ModelStation" }),
  }));
}

describe("ConnectionPage（浏览器降级形态）", () => {
  beforeEach(() => {
    delete window.modelstationDesktop;
    window.localStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("渲染：展示默认后端地址与浏览器形态提示", async () => {
    vi.stubGlobal("fetch", healthyFetch());

    render(<ConnectionPage />);

    expect(screen.getByLabelText("后端地址")).toHaveValue("http://127.0.0.1:8300");
    expect(screen.getByLabelText("数据根")).toHaveAttribute("readonly");
    expect(
      screen.getByText(/当前为浏览器形态：仅可配置后端地址/),
    ).toBeInTheDocument();
    // 浏览器态不提供后端进程控制动作
    expect(screen.queryByRole("button", { name: "重启后端" })).toBeNull();
    expect(screen.queryByRole("button", { name: "停止后端" })).toBeNull();

    // 等待挂载期异步状态收敛，避免 act 警告
    expect(await screen.findByText(/后端可达且健康/)).toBeInTheDocument();
  });

  it("健康检查：进入页面仅检查一次并展示健康状态", async () => {
    const fetchMock = healthyFetch();
    vi.stubGlobal("fetch", fetchMock);

    render(<ConnectionPage />);

    expect(await screen.findByText(/后端可达且健康/)).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[0][0])).toBe("http://127.0.0.1:8300/health");
  });

  it("后端不可达：给出 start.bat 引导且不发起重复请求", async () => {
    const fetchMock = vi.fn(async () => {
      throw new Error("Failed to fetch");
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ConnectionPage />);

    expect(await screen.findByText(/start\.bat/)).toBeInTheDocument();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

    // 静置 100ms 后仍只请求一次（无轮询）
    await new Promise((resolve) => setTimeout(resolve, 100));
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});