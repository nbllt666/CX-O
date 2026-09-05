import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import DatasetsPage from "./DatasetsPage";

vi.mock("../api/client", () => ({
  api: {
    listDatasets: vi.fn(),
    importDataset: vi.fn(),
    deleteDataset: vi.fn(),
  },
  ApiClientError: class ApiClientError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  },
}));

const mockedApi = vi.mocked(api, true);

const sampleDatasets = [
  {
    name: "speaker1",
    file_count: 3,
    total_size_bytes: 2048,
    created_at: "2026-09-05T10:00:00+08:00",
    has_manifest: true,
    manifest_version: 2,
    entry_count: 3,
    text_count: 3,
    text_ratio: 1,
  },
  {
    name: "speaker2",
    file_count: 0,
    total_size_bytes: 0,
    created_at: "2026-09-05T11:00:00+08:00",
    has_manifest: false,
    manifest_version: null,
    entry_count: 0,
    text_count: 0,
    text_ratio: null,
  },
];

describe("DatasetsPage", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    mockedApi.listDatasets.mockResolvedValue({
      status: "success",
      datasets: sampleDatasets,
    });
  });

  it("渲染：展示数据集列表（名称/音频数量/大小）", async () => {
    render(<DatasetsPage />);

    expect(await screen.findByText("speaker1")).toBeInTheDocument();
    expect(screen.getByText("speaker2")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText("2.0 KB")).toBeInTheDocument();
  });

  it("交互：确认后删除数据集并调用 DELETE 接口", async () => {
    const confirmMock = vi.fn(() => true);
    vi.stubGlobal("confirm", confirmMock);
    mockedApi.deleteDataset.mockResolvedValue({
      status: "success",
      message: "数据集 speaker1 已删除",
    });

    render(<DatasetsPage />);
    const deleteButtons = await screen.findAllByRole("button", { name: "删除" });
    fireEvent.click(deleteButtons[0]);

    await waitFor(() => {
      expect(mockedApi.deleteDataset).toHaveBeenCalledWith("speaker1");
    });
    expect(confirmMock).toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  it("交互：导入表单提交后调用 importDataset（multipart 文件）", async () => {
    mockedApi.importDataset.mockResolvedValue({
      status: "success",
      name: "sp9",
      imported: 1,
      files: ["a.wav"],
      skipped: [],
    });

    render(<DatasetsPage />);
    await screen.findByText("speaker1");

    fireEvent.change(screen.getByLabelText("speaker 名称"), {
      target: { value: "sp9" },
    });
    const file = new File(["audio-bytes"], "a.wav", { type: "audio/wav" });
    fireEvent.change(screen.getByLabelText(/音频文件/), {
      target: { files: [file] },
    });
    fireEvent.click(screen.getByRole("button", { name: "导入" }));

    await waitFor(() => {
      expect(mockedApi.importDataset).toHaveBeenCalledTimes(1);
    });
    const [nameArg, filesArg] = mockedApi.importDataset.mock.calls[0];
    expect(nameArg).toBe("sp9");
    expect(filesArg).toHaveLength(1);
    expect(filesArg[0]).toBe(file);
  });
});
