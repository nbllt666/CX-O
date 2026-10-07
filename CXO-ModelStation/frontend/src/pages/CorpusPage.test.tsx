import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import type { BatchTaskStatus } from "../api/client";
import CorpusPage from "./CorpusPage";

vi.mock("../api/client", () => ({
  api: {
    generateDataset: vi.fn(),
    getBatchTask: vi.fn(),
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

const runningTask: BatchTaskStatus = {
  task_id: "task-1",
  speaker_name: "DS-001",
  dataset_dir: "/ms/data/training/sovits_svc/raw/DS-001",
  mode: "",
  engine: "pipeline",
  dataset_id: "DS-001",
  status: "running",
  total: 3,
  done: 1,
  skipped: 0,
  failed: 0,
  current_text: "第一句语料",
  error: null,
  failures: [],
  created_at: "2026-10-07T10:00:00+08:00",
  finished_at: null,
};

describe("CorpusPage", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    mockedApi.getBatchTask.mockResolvedValue(runningTask);
  });

  it("渲染：一套流程表单（音色描述/参考文本/语料文本），无引擎选择", () => {
    render(<CorpusPage />);

    expect(screen.getByText("提交生成任务")).toBeInTheDocument();
    expect(screen.getByLabelText(/音色描述/)).toBeInTheDocument();
    expect(screen.getByLabelText(/参考文本/)).toBeInTheDocument();
    expect(screen.getByLabelText(/语料文本/)).toBeInTheDocument();
    // voxcpm 已停用：无引擎分段控件与旧 voxcpm 专属字段
    expect(screen.queryByRole("button", { name: "VoxCPM" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("speaker 名称")).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/生成模式/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText("参考音频路径（零样本克隆）")).not.toBeInTheDocument();
  });

  it("交互：提交调用统一流程 /api/datasets/generate 并轮询展示编号与进度", async () => {
    mockedApi.generateDataset.mockResolvedValue({
      status: "success",
      dataset_id: "DS-001",
      name: "DS-001",
      task_id: "task-1",
      dataset_dir: "/ms/data/training/sovits_svc/raw/DS-001",
      total: 3,
    });

    render(<CorpusPage />);

    fireEvent.change(screen.getByLabelText(/音色描述/), {
      target: { value: "年轻女性，声音清亮，语速适中" },
    });
    fireEvent.change(screen.getByLabelText(/参考文本/), {
      target: { value: "这是参考音频的播报内容" },
    });
    fireEvent.change(screen.getByLabelText(/语料文本/), {
      target: { value: "第一句语料\n第二句语料" },
    });
    fireEvent.click(screen.getByRole("button", { name: "开始生成" }));

    await waitFor(() => {
      expect(mockedApi.generateDataset).toHaveBeenCalledWith({
        voice_description: "年轻女性，声音清亮，语速适中",
        texts: [{ text: "第一句语料" }, { text: "第二句语料" }],
        ref_text: "这是参考音频的播报内容",
      });
    });

    // 提交反馈与任务进度卡展示编号
    expect(
      await screen.findByText(/数据集编号 DS-001，参考音频 1 条 \+ 语料 2 条/),
    ).toBeInTheDocument();
    expect(await screen.findByText(/处理进度：\s*1\s*\/\s*3/)).toBeInTheDocument();
    expect(screen.getByText("任务进度")).toBeInTheDocument();
  });

  it("校验：未填音色描述或语料文本时不提交并提示", async () => {
    render(<CorpusPage />);

    fireEvent.click(screen.getByRole("button", { name: "开始生成" }));
    expect(await screen.findByText(/请填写音色描述/)).toBeInTheDocument();
    expect(mockedApi.generateDataset).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText(/音色描述/), {
      target: { value: "清亮女声" },
    });
    fireEvent.click(screen.getByRole("button", { name: "开始生成" }));
    expect(await screen.findByText(/请填写至少一条语料文本/)).toBeInTheDocument();
    expect(mockedApi.generateDataset).not.toHaveBeenCalled();
  });
});
