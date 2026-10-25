import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import type { PipelineRunStatus } from "../api/client";
import AutoModelPage from "./AutoModelPage";

vi.mock("../api/client", () => ({
  api: {
    uploadReference: vi.fn(),
    startPipelineRun: vi.fn(),
    getPipelineRun: vi.fn(),
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

const runningRun: PipelineRunStatus = {
  run_id: "run-1",
  status: "running",
  model_type: "melotts",
  dataset_id: "DS-001",
  stages: [
    { id: "reference", status: "completed", detail: null },
    { id: "corpus", status: "running", detail: null },
    { id: "preprocess", status: "pending", detail: null },
    { id: "training", status: "pending", detail: null },
    { id: "collect", status: "pending", detail: null },
  ],
  corpus: { done: 2, total: 10 },
  training: {
    progress: 0,
    epoch: 0,
    total_epochs: 200,
    fitting_status: null,
    stop_reason: null,
  },
  result: null,
  error: null,
};

const completedRun: PipelineRunStatus = {
  run_id: "run-1",
  status: "completed",
  model_type: "melotts",
  dataset_id: "DS-001",
  stages: [
    { id: "reference", status: "completed", detail: "qwen3 生成初始参考音频" },
    { id: "corpus", status: "completed", detail: null },
    { id: "preprocess", status: "completed", detail: null },
    { id: "training", status: "completed", detail: null },
    { id: "collect", status: "completed", detail: null },
  ],
  corpus: { done: 10, total: 10 },
  training: {
    progress: 1,
    epoch: 12,
    total_epochs: 200,
    fitting_status: "converged",
    stop_reason: "连续 3 个 epoch 损失改善小于 1%",
  },
  result: {
    model_name: "auto_DS-001_melotts",
    model_dir: "models/melotts/auto_DS-001_melotts",
    files: ["model.pth", "config.json"],
  },
  error: null,
};

const skippedRefRun: PipelineRunStatus = {
  ...runningRun,
  stages: [
    { id: "reference", status: "skipped", detail: "使用上传的参考音频" },
    { id: "corpus", status: "running", detail: null },
    { id: "preprocess", status: "pending", detail: null },
    { id: "training", status: "pending", detail: null },
    { id: "collect", status: "pending", detail: null },
  ],
};

const failedRun: PipelineRunStatus = {
  run_id: "run-1",
  status: "failed",
  model_type: "melotts",
  dataset_id: "DS-001",
  stages: [
    { id: "reference", status: "completed", detail: null },
    { id: "corpus", status: "failed", detail: "cosyvoice 合成失败：引擎超时" },
    { id: "preprocess", status: "pending", detail: null },
    { id: "training", status: "pending", detail: null },
    { id: "collect", status: "pending", detail: null },
  ],
  corpus: { done: 3, total: 10 },
  training: {
    progress: 0,
    epoch: 0,
    total_epochs: 200,
    fitting_status: null,
    stop_reason: null,
  },
  result: null,
  error: "语料生成阶段失败",
};

describe("AutoModelPage", () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it("渲染：输入二选一控件、模型类型分段（默认 MeloTTS）与页面标题", () => {
    render(<AutoModelPage />);

    expect(screen.getByRole("heading", { level: 2, name: "一键成模" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "音色描述" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "上传参考音频" })).toBeInTheDocument();
    expect(screen.getByLabelText(/音色描述/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "MeloTTS" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "So-VITS-SVC" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "MeloTTS" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByLabelText(/语料文本覆盖/)).toBeInTheDocument();
  });

  it("校验：未填描述且未上传时不提交并提示", async () => {
    render(<AutoModelPage />);

    fireEvent.click(screen.getByRole("button", { name: "开始" }));
    expect(await screen.findByText(/请填写音色描述/)).toBeInTheDocument();
    expect(mockedApi.startPipelineRun).not.toHaveBeenCalled();

    // 切换到上传模式但未上传文件，同样不提交
    fireEvent.click(screen.getByRole("button", { name: "上传参考音频" }));
    fireEvent.click(screen.getByRole("button", { name: "开始" }));
    expect(await screen.findByText(/请先上传参考音频/)).toBeInTheDocument();
    expect(mockedApi.startPipelineRun).not.toHaveBeenCalled();
  });

  it("交互：填描述选 MeloTTS 提交，轮询至 completed 展示模型文件卡片", async () => {
    mockedApi.startPipelineRun.mockResolvedValue({
      status: "success",
      run_id: "run-1",
      stages: runningRun.stages,
    });
    mockedApi.getPipelineRun.mockResolvedValue(completedRun);

    render(<AutoModelPage />);

    fireEvent.change(screen.getByLabelText(/音色描述/), {
      target: { value: "年轻女性，声音清亮" },
    });
    fireEvent.click(screen.getByRole("button", { name: "MeloTTS" }));
    fireEvent.click(screen.getByRole("button", { name: "开始" }));

    await waitFor(() => {
      expect(mockedApi.startPipelineRun).toHaveBeenCalledWith({
        model_type: "melotts",
        voice_description: "年轻女性，声音清亮",
        max_epochs: 10000,
        corpus_target_clips: 50,
      });
    });
    expect(mockedApi.getPipelineRun).toHaveBeenCalledWith("run-1");

    // 模型文件卡片：模型名 / 产物文件 / 模型目录提示
    expect(await screen.findByText("auto_DS-001_melotts")).toBeInTheDocument();
    expect(screen.getByText("model.pth")).toBeInTheDocument();
    expect(screen.getByText("config.json")).toBeInTheDocument();
    expect(screen.getByText(/models\/melotts\/auto_DS-001_melotts/)).toBeInTheDocument();
    expect(await screen.findByText(/一键成模完成：模型 auto_DS-001_melotts/)).toBeInTheDocument();
    // Loss 自动判停：已拟合（自动停止）说明展示
    expect(screen.getByText(/已拟合（自动停止）/)).toBeInTheDocument();
  });

  it("交互：上传参考音频后提交携带 ref_audio_path，reference 阶段显示已跳过", async () => {
    mockedApi.uploadReference.mockResolvedValue({
      status: "success",
      ref_audio_path: "/ms/data/input/ref.wav",
    });
    mockedApi.startPipelineRun.mockResolvedValue({
      status: "success",
      run_id: "run-1",
      stages: runningRun.stages,
    });
    mockedApi.getPipelineRun.mockResolvedValue(skippedRefRun);

    render(<AutoModelPage />);

    fireEvent.click(screen.getByRole("button", { name: "上传参考音频" }));
    const fileInput = screen.getByLabelText(/参考音频文件/);
    fireEvent.change(fileInput, {
      target: { files: [new File(["audio"], "ref.wav", { type: "audio/wav" })] },
    });
    expect(await screen.findByText(/已上传：ref\.wav/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "开始" }));

    await waitFor(() => {
      expect(mockedApi.startPipelineRun).toHaveBeenCalledWith({
        model_type: "melotts",
        ref_audio_path: "/ms/data/input/ref.wav",
        max_epochs: 10000,
        corpus_target_clips: 50,
      });
    });

    // reference 阶段跳过：徽章显示「已跳过」
    expect(await screen.findByText("已跳过")).toBeInTheDocument();
    expect(screen.getByText(/使用上传的参考音频/)).toBeInTheDocument();
  });

  it("交互：本地数据集模式自动切到 So-VITS，提交携带 dataset_dir", async () => {
    mockedApi.startPipelineRun.mockResolvedValue({
      status: "success",
      run_id: "run-2",
      stages: runningRun.stages,
    });
    mockedApi.getPipelineRun.mockResolvedValue(runningRun);

    render(<AutoModelPage />);

    fireEvent.click(screen.getByRole("button", { name: "本地数据集" }));
    // 选中本地数据集时自动切到 So-VITS-SVC（该模式仅支持此引擎）
    expect(screen.getByRole("button", { name: "So-VITS-SVC" })).toHaveAttribute(
      "aria-pressed",
      "true"
    );
    fireEvent.change(screen.getByLabelText(/本地数据集文件夹路径/), {
      target: { value: "D:\\voice_data\\spk" },
    });
    fireEvent.click(screen.getByRole("button", { name: "开始" }));

    await waitFor(() => {
      expect(mockedApi.startPipelineRun).toHaveBeenCalledWith({
        model_type: "sovits",
        dataset_dir: "D:\\voice_data\\spk",
        max_epochs: 10000,
      });
    });
  });

  it("交互：语料规模随请求提交（MeloTTS 默认 50，可切 100）", async () => {
    mockedApi.startPipelineRun.mockResolvedValue({
      status: "success",
      run_id: "run-3",
      stages: runningRun.stages,
    });
    mockedApi.getPipelineRun.mockResolvedValue(runningRun);

    render(<AutoModelPage />);

    fireEvent.change(screen.getByLabelText(/音色描述/), {
      target: { value: "青年女声" },
    });
    fireEvent.change(screen.getByLabelText(/语料规模/), {
      target: { value: "100" },
    });
    fireEvent.click(screen.getByRole("button", { name: "开始" }));

    await waitFor(() => {
      expect(mockedApi.startPipelineRun).toHaveBeenCalledWith(
        expect.objectContaining({
          model_type: "melotts",
          voice_description: "青年女声",
          corpus_target_clips: 100,
          max_epochs: 10000,
        })
      );
    });
  });

  it("交互：切换 So-VITS 后语料档位联动为 300，最高可选 10000", async () => {
    render(<AutoModelPage />);

    fireEvent.click(screen.getByRole("button", { name: "So-VITS-SVC" }));

    expect(screen.getByLabelText(/语料规模/)).toHaveValue("300");
    expect(screen.getByRole("option", { name: /10000 片/ })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/语料规模/), {
      target: { value: "10000" },
    });
    expect(screen.getByLabelText(/语料规模/)).toHaveValue("10000");
  });

  it("失败路径：run failed 展示错误与失败阶段 detail", async () => {
    mockedApi.startPipelineRun.mockResolvedValue({
      status: "success",
      run_id: "run-1",
      stages: runningRun.stages,
    });
    mockedApi.getPipelineRun.mockResolvedValue(failedRun);

    render(<AutoModelPage />);

    fireEvent.change(screen.getByLabelText(/音色描述/), {
      target: { value: "低沉男声" },
    });
    fireEvent.click(screen.getByRole("button", { name: "开始" }));

    expect(
      await screen.findByText(
        /运行失败：语料生成阶段失败（阶段「语料生成」：cosyvoice 合成失败：引擎超时）/,
      ),
    ).toBeInTheDocument();
  });
});
