import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiClientError } from "../api/client";
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

const melottsIdleStatus = {
  task_id: null,
  status: "idle",
  progress: 0,
  epoch: 0,
  total_epochs: 0,
  message: "",
  models: [],
};

describe("TrainPage", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    mockedApi.getTrainStatus.mockResolvedValue(idleStatus);
    mockedApi.getMelottsStatus.mockResolvedValue(melottsIdleStatus);
  });

  it("渲染：训练状态卡与预处理/训练表单（默认 So-VITS-SVC）", async () => {
    render(<TrainPage />);

    expect(await screen.findByText("空闲")).toBeInTheDocument();
    expect(screen.getByText("训练状态（So-VITS-SVC）")).toBeInTheDocument();
    expect(screen.getByLabelText("训练数据目录")).toBeInTheDocument();
    expect(screen.getByLabelText("epochs")).toBeInTheDocument();
    expect(screen.getByLabelText("batch_size")).toBeInTheDocument();
    expect(screen.getByLabelText("learning_rate")).toBeInTheDocument();
    // 默认 sovits：melotts 专属表单不渲染
    expect(screen.queryByLabelText("数据集目录")).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/language/)).not.toBeInTheDocument();
  });

  it("交互：点击开始训练调用 startTrain 并携带数值参数", async () => {
    mockedApi.startTrain.mockResolvedValue({
      status: "success",
      task_id: "task-abc123",
      message: "训练已启动",
    });

    render(<TrainPage />);
    await screen.findByText("空闲");

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
      });
    });
  });

  it("交互：切换到 MeloTTS 渲染专属表单，提交调用 startMelottsTrain（language 默认 ZH）", async () => {
    mockedApi.startMelottsTrain.mockResolvedValue({
      status: "success",
      task_id: "task-mel-01",
      message: "训练已启动",
    });

    render(<TrainPage />);
    await screen.findByText("空闲");

    fireEvent.click(screen.getByRole("button", { name: "MeloTTS" }));

    // 类型切换：melotts 表单渲染，sovits 表单卸载，状态卡标题跟随类型
    expect(await screen.findByText("训练状态（MeloTTS）")).toBeInTheDocument();
    expect(screen.getByLabelText("数据集目录")).toBeInTheDocument();
    expect(screen.getByLabelText("speaker 名称")).toBeInTheDocument();
    expect(screen.queryByLabelText("训练数据目录")).not.toBeInTheDocument();

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
