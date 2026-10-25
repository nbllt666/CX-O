import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import ModelsPage from "./ModelsPage";

vi.mock("../api/client", () => ({
  api: {
    listModels: vi.fn(),
    listDatasets: vi.fn(),
    infer: vi.fn(),
    listMelottsModels: vi.fn(),
    inferMelotts: vi.fn(),
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

const sampleModels = [
  {
    name: "sp1_48k",
    path: "C:\\ms\\data\\models\\sovits_svc\\sp1_48k",
    created: 1757000000,
    g_model: "C:\\ms\\data\\models\\sovits_svc\\sp1_48k\\G_1000.pth",
    d_model: null,
  },
];

const sampleMelottsModels = [
  {
    name: "melotts_zh_sp1",
    path: "C:\\ms\\data\\models\\melotts\\melotts_zh_sp1",
    created: 1757000000,
    g_model: "C:\\ms\\data\\models\\melotts\\melotts_zh_sp1\\G_1800.pth",
    checkpoints: ["G_252.pth", "G_1800.pth"],
  },
];

describe("ModelsPage", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    mockedApi.listModels.mockResolvedValue({
      status: "success",
      models: sampleModels,
    });
    mockedApi.listDatasets.mockResolvedValue({
      status: "success",
      datasets: [],
    });
    mockedApi.listMelottsModels.mockResolvedValue({
      status: "success",
      models: [],
    });
  });

  it("渲染：sovits 模型列表展示名称与 G 模型，melotts 组空列表提示", async () => {
    render(<ModelsPage />);

    expect(await screen.findByText("sp1_48k")).toBeInTheDocument();
    expect(screen.getByText("G_1000.pth")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "选择" })).toBeInTheDocument();
    // 按类型分组：两组标题各自出现
    expect(screen.getByText("模型列表（So-VITS-SVC）")).toBeInTheDocument();
    expect(screen.getByText("模型列表（MeloTTS）")).toBeInTheDocument();
    expect(screen.getByText(/暂无 MeloTTS 模型/)).toBeInTheDocument();
  });

  it("渲染：melotts 组展示模型列表与检查点数量", async () => {
    mockedApi.listMelottsModels.mockResolvedValue({
      status: "success",
      models: sampleMelottsModels,
    });

    render(<ModelsPage />);

    expect(await screen.findByText("melotts_zh_sp1")).toBeInTheDocument();
    expect(screen.getByText("2 个")).toBeInTheDocument();
    // sovits 与 melotts 各有一个「选择」按钮
    expect(screen.getAllByRole("button", { name: "选择" })).toHaveLength(2);
  });

  it("降级：melotts 接口失败时本组提示未就绪，sovits 组不受影响", async () => {
    mockedApi.listMelottsModels.mockRejectedValue(
      new Error("500 melotts API not available"),
    );

    render(<ModelsPage />);

    expect(await screen.findByText(/MeloTTS 模型接口未就绪/)).toBeInTheDocument();
    // sovits 组仍正常展示与可选择
    expect(screen.getByText("sp1_48k")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "选择" }));
    expect(screen.getByText(/已选：sp1_48k/)).toBeInTheDocument();
  });

  it("交互：选择 melotts 模型后输入文本试听，调用 inferMelotts 并展示结果", async () => {
    mockedApi.listMelottsModels.mockResolvedValue({
      status: "success",
      models: sampleMelottsModels,
    });
    mockedApi.inferMelotts.mockResolvedValue({
      status: "success",
      output_filename: "melotts_G_1800_abc12345.wav",
      audio_url: "/api/audio-files/audition/melotts_G_1800_abc12345.wav",
      checkpoint: "G_1800.pth",
    });

    render(<ModelsPage />);

    await screen.findByText("melotts_zh_sp1");
    // 第 2 个「选择」属于 melotts 行（sovits 在前）
    fireEvent.click(screen.getAllByRole("button", { name: "选择" })[1]);
    expect(screen.getByText(/已选：melotts_zh_sp1/)).toBeInTheDocument();
    // 默认选中最新检查点
    expect(screen.getByLabelText("检查点")).toHaveValue("G_1800.pth");

    fireEvent.change(screen.getByLabelText("合成文本"), {
      target: { value: "你好呀，很高兴认识你。" },
    });
    fireEvent.click(screen.getByRole("button", { name: "开始试听" }));

    await waitFor(() => {
      expect(mockedApi.inferMelotts).toHaveBeenCalledWith({
        model_path: sampleMelottsModels[0].path,
        text: "你好呀，很高兴认识你。",
        checkpoint: "G_1800.pth",
      });
    });
    expect(
      await screen.findByText("melotts_G_1800_abc12345.wav"),
    ).toBeInTheDocument();
  });

  it("交互：选择模型后点击试听推理调用 infer 并展示结果", async () => {
    mockedApi.infer.mockResolvedValue({
      status: "success",
      output_filename: "converted_a_abc12345.wav",
      audio_url: "/api/audio-files/audition/converted_a_abc12345.wav",
    });

    render(<ModelsPage />);

    fireEvent.click(await screen.findByRole("button", { name: "选择" }));
    fireEvent.change(screen.getByLabelText("音频路径（服务端路径）"), {
      target: { value: "data/training/sovits_svc/raw/sp1/0001.wav" },
    });
    fireEvent.click(screen.getByRole("button", { name: "开始试听推理" }));

    await waitFor(() => {
      expect(mockedApi.infer).toHaveBeenCalledWith(
        expect.objectContaining({
          audio_path: "data/training/sovits_svc/raw/sp1/0001.wav",
          model_path: sampleModels[0].g_model,
          speaker_id: 0,
          transpose: 0,
        }),
      );
    });
    expect(
      await screen.findByText("converted_a_abc12345.wav"),
    ).toBeInTheDocument();
  });
});
