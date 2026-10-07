import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiClientError } from "../api/client";
import type { DatasetInfo } from "../api/client";
import TrainPage from "./TrainPage";

vi.mock("../api/client", () => ({
  api: {
    getTrainStatus: vi.fn(),
    preprocess: vi.fn(),
    startTrain: vi.fn(),
    stopTrain: vi.fn(),
    getMelottsStatus: vi.fn(),
    melottsPreprocess: vi.fn(),
    startMelottsTrain: vi.fn(),
    stopMelottsTrain: vi.fn(),
    listDatasets: vi.fn(),
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

const idleStatus = {
  task_id: null,
  status: "idle",
  progress: 0,
  epoch: 0,
  total_epochs: 0,
  message: "",
  models: [],
};

const pipelineDataset: DatasetInfo = {
  name: "DS-001",
  dataset_id: "DS-001",
  file_count: 3,
  total_size_bytes: 1024,
  created_at: "2026-10-07T10:00:00+08:00",
  has_manifest: true,
  manifest_version: 2,
  entry_count: 3,
  text_count: 3,
  text_ratio: 1,
};

const importedDataset: DatasetInfo = {
  name: "imported_spk",
  dataset_id: null,
  file_count: 5,
  total_size_bytes: 2048,
  created_at: "2026-10-07T09:00:00+08:00",
  has_manifest: false,
  manifest_version: null,
  entry_count: 0,
  text_count: 0,
  text_ratio: null,
};

describe("TrainPage", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    mockedApi.getTrainStatus.mockResolvedValue(idleStatus);
    mockedApi.getMelottsStatus.mockResolvedValue(idleStatus);
    mockedApi.listDatasets.mockResolvedValue({
      status: "success",
      datasets: [pipelineDataset, importedDataset],
    });
  });

  it("渲染：数据集按编号选择（无路径输入框）与训练表单（默认 So-VITS-SVC）", async () => {
    render(<TrainPage />);

    expect(await screen.findByText("空闲")).toBeInTheDocument();
    expect(screen.getByText("训练状态（So-VITS-SVC）")).toBeInTheDocument();
    expect(screen.getByLabelText(/数据集（优先显示编号）/)).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /DS-001（DS-001）\s*·\s*3 条音频/ })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /imported_spk · 5 条音频/ })).toBeInTheDocument();
    // 路径式输入已移除（训练入口按编号/名称选择数据集）
    expect(screen.queryByLabelText("训练数据目录")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("数据集目录")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("speaker 名称")).not.toBeInTheDocument();
  });

  it("交互：未选择数据集时预处理/训练按钮不可用", async () => {
    render(<TrainPage />);
    await screen.findByText("空闲");

    expect(screen.getByRole("button", { name: "开始预处理" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "开始训练" })).toBeDisabled();
  });

  it("交互：选择编号数据集后，预处理与训练携带 dataset_id", async () => {
    mockedApi.preprocess.mockResolvedValue({
      status: "success",
      results: { resample: { success: true } },
    });
    mockedApi.startTrain.mockResolvedValue({
      status: "success",
      task_id: "task-abc123",
      message: "训练已启动",
    });

    render(<TrainPage />);
    await screen.findByText("空闲");

    fireEvent.change(screen.getByLabelText(/数据集（优先显示编号）/), {
      target: { value: "DS-001" },
    });

    fireEvent.click(screen.getByRole("button", { name: "开始预处理" }));
    await waitFor(() => {
      expect(mockedApi.preprocess).toHaveBeenCalledWith({ dataset_id: "DS-001" });
    });

    fireEvent.change(screen.getByLabelText("epochs"), { target: { value: "100" } });
    fireEvent.change(screen.getByLabelText("batch_size"), { target: { value: "2" } });
    fireEvent.change(screen.getByLabelText("learning_rate"), {
      target: { value: "0.001" },
    });
    fireEvent.change(screen.getByLabelText(/输出模型名/), {
      target: { value: "m1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "开始训练" }));

    await waitFor(() => {
      expect(mockedApi.startTrain).toHaveBeenCalledWith({
        epochs: 100,
        batch_size: 2,
        learning_rate: 0.001,
        output_name: "m1",
        dataset_id: "DS-001",
      });
    });
  });

  it("交互：导入数据集（无编号）回退显式路径提交", async () => {
    mockedApi.preprocess.mockResolvedValue({
      status: "success",
      results: { resample: { success: true } },
    });

    render(<TrainPage />);
    await screen.findByText("空闲");

    fireEvent.change(screen.getByLabelText(/数据集（优先显示编号）/), {
      target: { value: "imported_spk" },
    });
    fireEvent.click(screen.getByRole("button", { name: "开始预处理" }));

    await waitFor(() => {
      expect(mockedApi.preprocess).toHaveBeenCalledWith({
        training_data_dir: "data/training/sovits_svc",
        speaker_name: "imported_spk",
      });
    });
  });

  it("交互：切换到 MeloTTS 后按编号数据准备，训练提交带 language 默认 ZH", async () => {
    mockedApi.melottsPreprocess.mockResolvedValue({
      status: "success",
      results: { prep: { success: true } },
    });
    mockedApi.startMelottsTrain.mockResolvedValue({
      status: "success",
      task_id: "task-mel-01",
      message: "训练已启动",
    });

    render(<TrainPage />);
    await screen.findByText("空闲");

    fireEvent.click(screen.getByRole("button", { name: "MeloTTS" }));
    expect(await screen.findByText("训练状态（MeloTTS）")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(/数据集（优先显示编号）/), {
      target: { value: "DS-001" },
    });
    fireEvent.click(screen.getByRole("button", { name: "开始数据准备" }));
    await waitFor(() => {
      expect(mockedApi.melottsPreprocess).toHaveBeenCalledWith({ dataset_id: "DS-001" });
    });

    fireEvent.change(screen.getByLabelText("epochs"), { target: { value: "500" } });
    fireEvent.change(screen.getByLabelText("batch_size"), { target: { value: "8" } });
    fireEvent.change(screen.getByLabelText("learning_rate"), {
      target: { value: "0.0002" },
    });
    fireEvent.change(screen.getByLabelText(/输出模型名/), {
      target: { value: "mel1" },
    });
    // language 输入默认值即 ZH，不改动直接提交
    expect(screen.getByLabelText(/language/)).toHaveValue("ZH");
    fireEvent.click(screen.getByRole("button", { name: "开始训练" }));

    await waitFor(() => {
      expect(mockedApi.startMelottsTrain).toHaveBeenCalledWith({
        epochs: 500,
        batch_size: 8,
        learning_rate: 0.0002,
        output_name: "mel1",
        language: "ZH",
      });
    });
    expect(mockedApi.startTrain).not.toHaveBeenCalled();
  });

  it("交互：melotts 训练返回 409 时展示训练互斥冲突提示", async () => {
    mockedApi.startMelottsTrain.mockRejectedValue(
      new ApiClientError(409, "训练任务正在进行中（当前训练类型: So-VITS-SVC，task_id: abc123）"),
    );

    render(<TrainPage />);
    await screen.findByText("空闲");

    fireEvent.click(screen.getByRole("button", { name: "MeloTTS" }));
    await screen.findByText("训练状态（MeloTTS）");

    fireEvent.change(screen.getByLabelText("epochs"), { target: { value: "10" } });
    fireEvent.change(screen.getByLabelText("batch_size"), { target: { value: "2" } });
    fireEvent.change(screen.getByLabelText("learning_rate"), {
      target: { value: "0.0001" },
    });
    fireEvent.click(screen.getByRole("button", { name: "开始训练" }));

    expect(
      await screen.findByText(/训练互斥冲突（同一时间仅允许一个训练任务）.+So-VITS-SVC/),
    ).toBeInTheDocument();
  });
});
