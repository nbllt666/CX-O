import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import type { BatchTaskStatus } from "../api/client";
import CorpusPage from "./CorpusPage";

vi.mock("../api/client", () => ({
  api: {
    previewDatasetReference: vi.fn(),
    continueDatasetGeneration: vi.fn(),
    getBatchTask: vi.fn(),
    getAudioFileUrl: vi.fn(
      (category: string, ...segments: string[]) =>
        `/api/audio-files/${category}/${segments.join("/")}`,
    ),
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

/** 阶段一终态：参考音频已生成，等待试听确认 */
const awaitingReviewTask: BatchTaskStatus = {
  task_id: "preview-1",
  speaker_name: "DS-001",
  dataset_dir: "/ms/data/training/sovits_svc/raw/DS-001",
  mode: "",
  engine: "pipeline",
  dataset_id: "DS-001",
  status: "awaiting_review",
  total: 1,
  done: 1,
  skipped: 0,
  failed: 0,
  current_text: null,
  error: null,
  failures: [],
  created_at: "2026-10-07T10:00:00+08:00",
  finished_at: null,
  phase: "reference",
  ref_file: "0001_abcd.wav",
};

/** 阶段二：续跑语料任务进行中 */
const runningTask: BatchTaskStatus = {
  ...awaitingReviewTask,
  task_id: "continue-1",
  status: "running",
  total: 3,
  done: 1,
  current_text: "第一句语料",
  phase: "corpus",
};

describe("CorpusPage", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    // resetAllMocks 会清空工厂里的实现，这里按需恢复音频 URL 构造
    mockedApi.getAudioFileUrl.mockImplementation(
      (category: string, ...segments: string[]) =>
        `/api/audio-files/${category}/${segments.join("/")}`,
    );
    mockedApi.getBatchTask.mockImplementation((taskId: string) =>
      Promise.resolve(taskId === "preview-1" ? awaitingReviewTask : runningTask),
    );
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

  it("交互：先只生成参考音频并试听，确认后再续跑其余语料", async () => {
    mockedApi.previewDatasetReference.mockResolvedValue({
      status: "success",
      task_id: "preview-1",
      dataset_id: "DS-001",
      name: "DS-001",
      dataset_dir: "/ms/data/training/sovits_svc/raw/DS-001",
      total: 1,
    });
    mockedApi.continueDatasetGeneration.mockResolvedValue({
      status: "success",
      task_id: "continue-1",
      dataset_id: "DS-001",
      name: "DS-001",
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
    fireEvent.click(screen.getByRole("button", { name: "生成参考音频（可试听）" }));

    await waitFor(() => {
      expect(mockedApi.previewDatasetReference).toHaveBeenCalledWith({
        voice_description: "年轻女性，声音清亮，语速适中",
        ref_text: "这是参考音频的播报内容",
      });
    });

    // 阶段一：试听区出现播放器与「继续生成其余语料」按钮
    expect(await screen.findByText(/初始参考音频已生成/)).toBeInTheDocument();
    expect(screen.getByText(/初始参考音频（试听）/)).toBeInTheDocument();
    const audio = document.querySelector("audio");
    expect(audio?.getAttribute("src")).toBe(
      "/api/audio-files/datasets/raw/DS-001/0001_abcd.wav",
    );

    fireEvent.click(screen.getByRole("button", { name: "继续生成其余语料" }));

    await waitFor(() => {
      expect(mockedApi.continueDatasetGeneration).toHaveBeenCalledWith("DS-001", {
        texts: [{ text: "第一句语料" }, { text: "第二句语料" }],
      });
    });

    // 阶段二进度：done/total 与阶段标识透出
    expect(await screen.findByText(/处理进度：\s*1\s*\/\s*3/)).toBeInTheDocument();
    expect(screen.getByText(/批量语料合成/)).toBeInTheDocument();
  });

  it("校验：未填音色描述不提交；未填语料文本不续跑", async () => {
    render(<CorpusPage />);

    fireEvent.click(screen.getByRole("button", { name: "生成参考音频（可试听）" }));
    expect(await screen.findByText(/请填写音色描述/)).toBeInTheDocument();
    expect(mockedApi.previewDatasetReference).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText(/音色描述/), {
      target: { value: "清亮女声" },
    });
    mockedApi.previewDatasetReference.mockResolvedValue({
      status: "success",
      task_id: "preview-1",
      dataset_id: "DS-001",
      name: "DS-001",
      dataset_dir: "/ms/data/training/sovits_svc/raw/DS-001",
      total: 1,
    });
    fireEvent.click(screen.getByRole("button", { name: "生成参考音频（可试听）" }));
    expect(await screen.findByText(/初始参考音频已生成/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "继续生成其余语料" }));
    expect(await screen.findByText(/请填写至少一条语料文本/)).toBeInTheDocument();
    expect(mockedApi.continueDatasetGeneration).not.toHaveBeenCalled();
  });
});
