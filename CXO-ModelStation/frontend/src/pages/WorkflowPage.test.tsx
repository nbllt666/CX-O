import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import WorkflowPage from "./WorkflowPage";

vi.mock("../api/client", () => ({
  api: {
    getWorkflowStatus: vi.fn(),
    executeWorkflowStep: vi.fn(),
    resetWorkflow: vi.fn(),
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

const workflowState = {
  current_step: 0,
  steps: [
    { id: "train_prep", name: "训练数据准备", status: "pending", output: null },
    { id: "training", name: "模型训练", status: "pending", output: null },
    { id: "inference", name: "推理", status: "pending", output: null },
  ],
};

describe("WorkflowPage", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    mockedApi.getWorkflowStatus.mockResolvedValue(workflowState);
  });

  it("渲染：三步状态卡与待执行徽章", async () => {
    render(<WorkflowPage />);

    expect(
      await screen.findByRole("heading", { name: /训练数据准备/ }),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /模型训练/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /推理/ })).toBeInTheDocument();
    const badges = await screen.findAllByText("待执行");
    expect(badges).toHaveLength(3);
  });

  it("交互：点击执行此步调用 executeWorkflowStep", async () => {
    mockedApi.executeWorkflowStep.mockResolvedValue({
      ...workflowState,
      current_step: 1,
      steps: [
        {
          id: "train_prep",
          name: "训练数据准备",
          status: "completed",
          output: { results: { speaker: { success: true } } },
        },
        ...workflowState.steps.slice(1),
      ],
    });

    render(<WorkflowPage />);
    const executeButtons = await screen.findAllByRole("button", { name: "执行此步" });
    expect(executeButtons).toHaveLength(3);
    fireEvent.click(executeButtons[0]);

    await waitFor(() => {
      expect(mockedApi.executeWorkflowStep).toHaveBeenCalledWith("train_prep");
    });
  });

  it("交互：确认后重置工作流调用 resetWorkflow", async () => {
    const confirmMock = vi.fn(() => true);
    vi.stubGlobal("confirm", confirmMock);
    mockedApi.resetWorkflow.mockResolvedValue(workflowState);

    render(<WorkflowPage />);
    fireEvent.click(await screen.findByRole("button", { name: "重置工作流" }));

    await waitFor(() => {
      expect(mockedApi.resetWorkflow).toHaveBeenCalledTimes(1);
    });
    expect(confirmMock).toHaveBeenCalled();
    vi.unstubAllGlobals();
  });
});
