import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import type { BatchTaskStatus } from "../api/client";
import CorpusPage from "./CorpusPage";

vi.mock("../api/client", () => ({
  api: {
    submitBatchDataset: vi.fn(),
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
  speaker_name: "sp",
  dataset_dir: "/ms/data/training/sovits_svc/raw/sp",
  mode: "design",
  engine: "voxcpm",
  status: "running",
  total: 2,
  done: 1,
  skipped: 0,
  failed: 0,
  current_text: "第二句语料",
  error: null,
  failures: [],
  created_at: "2026-09-05T10:00:00+08:00",
  finished_at: null,
};

describe("CorpusPage", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    mockedApi.getBatchTask.mockResolvedValue(runningTask);
  });

  it("渲染：提交表单（引擎选择/speaker/模式/语料文本）", () => {
    render(<CorpusPage />);

    expect(screen.getByText("提交批量任务")).toBeInTheDocument();
    expect(screen.getByLabelText("speaker 名称")).toBeInTheDocument();
    expect(screen.getByLabelText(/生成模式/)).toBeInTheDocument();
    expect(screen.getByLabelText(/语料文本/)).toBeInTheDocument();
    // 引擎分段控件：三选项默认 voxcpm
    expect(screen.getByRole("button", { name: "VoxCPM" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "CosyVoice3 零样本克隆" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    expect(screen.getByRole("button", { name: "Qwen3 声音设计" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("交互：多行文本提交后调用 batch-generate（默认 voxcpm）并轮询展示进度", async () => {
    mockedApi.submitBatchDataset.mockResolvedValue({
      status: "success",
      task_id: "task-1",
      total: 2,
    });

    render(<CorpusPage />);

    fireEvent.change(screen.getByLabelText("speaker 名称"), {
      target: { value: "sp" },
    });
    fireEvent.change(screen.getByLabelText(/语料文本/), {
      target: { value: "第一句语料\n第二句语料" },
    });
    fireEvent.click(screen.getByRole("button", { name: "提交批量生成" }));

    await waitFor(() => {
      expect(mockedApi.submitBatchDataset).toHaveBeenCalledWith(
        expect.objectContaining({
          speaker_name: "sp",
          texts: [{ text: "第一句语料" }, { text: "第二句语料" }],
          engine: "voxcpm",
          mode: "design",
        }),
      );
    });

    // 任务进度卡出现并展示 done/total 与 current_text
    expect(await screen.findByText(/处理进度：\s*1\s*\/\s*2/)).toBeInTheDocument();
    expect(screen.getByText("任务进度")).toBeInTheDocument();
  });

  it("交互：切换引擎为 cosyvoice3_zero 出现参考音频字段，提交携带 engine_params", async () => {
    mockedApi.submitBatchDataset.mockResolvedValue({
      status: "success",
      task_id: "task-2",
      total: 1,
    });

    render(<CorpusPage />);

    // 默认 voxcpm：无零样本克隆参考音频字段
    expect(
      screen.queryByLabelText("参考音频路径（零样本克隆）"),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "CosyVoice3 零样本克隆" }));
    const refAudioInput = screen.getByLabelText("参考音频路径（零样本克隆）");
    expect(refAudioInput).toBeInTheDocument();
    // voxcpm 专属的生成模式字段随引擎切换隐藏
    expect(screen.queryByLabelText(/生成模式/)).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("speaker 名称"), { target: { value: "sp2" } });
    fireEvent.change(refAudioInput, { target: { value: "data/input/ref.wav" } });
    fireEvent.change(screen.getByLabelText(/参考文本/), {
      target: { value: "参考转写内容" },
    });
    fireEvent.change(screen.getByLabelText(/语料文本/), {
      target: { value: "克隆语料一句" },
    });
    fireEvent.click(screen.getByRole("button", { name: "提交批量生成" }));

    await waitFor(() => {
      expect(mockedApi.submitBatchDataset).toHaveBeenCalledWith(
        expect.objectContaining({
          speaker_name: "sp2",
          texts: [{ text: "克隆语料一句" }],
          engine: "cosyvoice3_zero",
          engine_params: {
            ref_audio_path: "data/input/ref.wav",
            ref_text: "参考转写内容",
          },
        }),
      );
    });
  });

  it("交互：切换引擎为 qwen3_voicedesign 出现音色描述，提交携带 voice_description", async () => {
    mockedApi.submitBatchDataset.mockResolvedValue({
      status: "success",
      task_id: "task-3",
      total: 1,
    });

    render(<CorpusPage />);

    fireEvent.click(screen.getByRole("button", { name: "Qwen3 声音设计" }));
    const descInput = screen.getByLabelText(/音色描述/);
    expect(descInput).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("speaker 名称"), { target: { value: "sp3" } });
    fireEvent.change(descInput, {
      target: { value: "年轻女性，声音清亮，语速适中" },
    });
    fireEvent.change(screen.getByLabelText(/语料文本/), {
      target: { value: "声音设计语料" },
    });
    fireEvent.click(screen.getByRole("button", { name: "提交批量生成" }));

    await waitFor(() => {
      expect(mockedApi.submitBatchDataset).toHaveBeenCalledWith(
        expect.objectContaining({
          engine: "qwen3_voicedesign",
          engine_params: { voice_description: "年轻女性，声音清亮，语速适中" },
        }),
      );
    });
  });
});
