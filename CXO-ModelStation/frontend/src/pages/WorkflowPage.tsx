/*
 * 工作流总览页：三步（train_prep / training / inference）状态卡、
 * 逐步执行按钮、重置按钮、步骤输出展示。
 * 训练步骤由后端异步执行（start_training 立即返回），状态经轮询跟进。
 */
import { useCallback, useState } from "react";
import { api } from "../api/client";
import type { WorkflowState, WorkflowStep } from "../api/client";
import { ErrorBar, NoticeBar, StatusBadge } from "../components/ui";
import { usePolling } from "../hooks/usePolling";

function toMessage(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

export default function WorkflowPage() {
  const { data: state, error, stopped, refresh } = usePolling(
    useCallback(() => api.getWorkflowStatus(), []),
    { intervalMs: 3000 },
  );

  const [busyStep, setBusyStep] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const handleExecute = async (step: WorkflowStep) => {
    setActionError(null);
    setNotice(null);
    setBusyStep(step.id);
    try {
      const res: WorkflowState = await api.executeWorkflowStep(step.id);
      const updated = res.steps.find((s) => s.id === step.id);
      setNotice(
        updated?.status === "running"
          ? `步骤「${step.name}」执行中（训练在后台异步进行，进度见训练控制台）`
          : `步骤「${step.name}」已执行，当前状态：${updated?.status ?? "未知"}`,
      );
      refresh();
    } catch (e) {
      setActionError(`步骤「${step.name}」执行失败：${toMessage(e)}`);
      refresh();
    } finally {
      setBusyStep(null);
    }
  };

  const handleReset = async () => {
    setActionError(null);
    setNotice(null);
    if (!window.confirm("确认重置工作流？若有训练任务运行中将被停止。")) {
      return;
    }
    try {
      await api.resetWorkflow();
      setNotice("工作流已重置");
      refresh();
    } catch (e) {
      setActionError(toMessage(e));
    }
  };

  const steps = state?.steps ?? [];

  return (
    <div>
      <header className="page-header">
        <h2>工作流总览</h2>
        <p>训练三步编排：训练数据准备 → 模型训练 → 推理，状态每 3 秒自动刷新</p>
      </header>

      <ErrorBar message={error} stopped={stopped} onRetry={refresh} />
      <NoticeBar message={notice} variant="success" />
      <NoticeBar message={actionError} variant="error" />

      <div className="form-actions" style={{ marginBottom: 16 }}>
        <button type="button" className="btn btn-danger" onClick={handleReset}>
          重置工作流
        </button>
        <span className="hint">重置会停止运行中的训练子进程并清空全部步骤状态</span>
      </div>

      {steps.length > 0 ? (
        <div className="step-grid">
          {steps.map((step, index) => (
            <div className="step-card" key={step.id}>
              <div className="step-card-header">
                <h3>
                  第 {index + 1} 步 · {step.name}
                </h3>
                <StatusBadge status={step.status} />
              </div>
              <p className="muted mono">step_id: {step.id}</p>
              <div>
                <button
                  type="button"
                  className="btn btn-primary btn-small"
                  disabled={busyStep !== null}
                  onClick={() => handleExecute(step)}
                >
                  {busyStep === step.id ? "执行中…" : "执行此步"}
                </button>
              </div>
              <div>
                <p className="muted" style={{ margin: "0 0 4px" }}>
                  步骤输出：
                </p>
                <pre className="output-block">
                  {step.output == null ? "（暂无输出）" : JSON.stringify(step.output, null, 2)}
                </pre>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <p className="empty-tip">工作流状态加载中…</p>
      )}
    </div>
  );
}
