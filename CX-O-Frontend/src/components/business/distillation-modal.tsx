/**
 * RADIX-Lite v1.3.0 多轮蒸馏弹窗组件。
 *
 * 迁移自 CXHMS frontend/src/components/DistillationModal.tsx。
 * 适配点：
 * - 移除 i18n（useTranslation），改用硬编码中文
 * - `agentApi` → `api`（CX-O API client 实例）；`api.getAgents()` 直接返回 Agent[]
 * - `distillationApi` 改从 `../api/clients/distillation` 导入（CX-O 路径）
 *
 * 功能：
 * - 超长上下文智能切分 + 多轮蒸馏对话 + 角色卡 agent 自动创建 + 外部内容复制粘贴导入
 * - 4 步流程：输入 → 切分预览 → 蒸馏对话 → 结果
 */
import { useState, useEffect, useCallback, useRef } from 'react';
import { createPortal } from 'react-dom';
import { motion, AnimatePresence, type Variants } from 'framer-motion';
import {
  buildGlassDataAttributes,
  injectGlassClassName,
  isValidGlassTier,
  getComponentSpringTransition,
} from '@/components/ui-v2';
import {
  X,
  Upload,
  Scissors,
  MessagesSquare,
  CheckCircle2,
  AlertCircle,
  Loader2,
  ChevronLeft,
  ChevronRight,
  User,
  Brain,
  Sparkles,
} from 'lucide-react';
import { api } from '@/api/client';
import {
  distillationApi,
  type DistillationSourceType,
  type DistillationGoal,
  type BatchStartResponse,
  type GroupStatusResponse,
  type FinalizeAgentResponse,
} from '@/api/clients/distillation';

type Step = 'input' | 'preview' | 'distill' | 'result';

interface DistillationModalProps {
  isOpen: boolean;
  onClose: () => void;
}

interface SessionDistillState {
  session_id: string;
  chunk_index: number;
  chunk_preview: string;
  current_state: string;
  agent_action: string;
  next_needed: boolean;
  preread_summary: string | null;
  ambiguity_questions: string[];
  extracted_content: string | null;
  quality_score: number | null;
  turn_count: number;
  message: string | null;
  is_finalized: boolean;
  finalize_result: FinalizeAgentResponse | null;
  is_finalizing: boolean;
  error: string | null;
}

export function DistillationModal({ isOpen, onClose }: DistillationModalProps) {
  const [step, setStep] = useState<Step>('input');
  const [isProcessing, setIsProcessing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 步骤 1：输入
  const [sourceType, setSourceType] = useState<DistillationSourceType>('text');
  const [sourceRef, setSourceRef] = useState('');
  const [templateId] = useState('default');
  const [maxTurns, setMaxTurns] = useState(2);
  const [chunkSize, setChunkSize] = useState(4000);
  const [distillationGoal, setDistillationGoal] = useState<DistillationGoal>('memory_and_agent');
  const [askUserOnAmbiguity] = useState(false);
  const [targetAgentId, setTargetAgentId] = useState('');
  const [agentsList, setAgentsList] = useState<Array<{ id: string; name: string }>>([]);

  // 加载 agent 列表（用于记忆蒸馏注入目标选择）
  useEffect(() => {
    const loadAgents = async () => {
      try {
        const agents = await api.getAgents();
        setAgentsList(agents.map((a) => ({ id: a.id, name: a.name })));
      } catch (e) {
        console.error('加载 agent 列表失败:', e);
      }
    };
    void loadAgents();
  }, []);

  // 步骤 2：切分预览
  const [batchResult, setBatchResult] = useState<BatchStartResponse | null>(null);

  // 步骤 3：蒸馏对话
  const [sessions, setSessions] = useState<SessionDistillState[]>([]);
  const [activeSessionIdx, setActiveSessionIdx] = useState(0);
  const [userResponse, setUserResponse] = useState('');
  const [, setGroupRefreshKey] = useState(0);
  const pollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // sessions 的最新值引用，避免 setTimeout 闭包陷阱
  const sessionsRef = useRef(sessions);
  sessionsRef.current = sessions;
  // 自动推进计数（防死循环）
  const autoAdvanceCountRef = useRef(0);

  // 步骤 4：结果汇总
  const [groupStatus, setGroupStatus] = useState<GroupStatusResponse | null>(null);

  // 重置状态
  const resetState = useCallback(() => {
    setStep('input');
    setIsProcessing(false);
    setError(null);
    setSourceType('text');
    setSourceRef('');
    setMaxTurns(2);
    setChunkSize(4000);
    setDistillationGoal('memory_and_agent');
    setBatchResult(null);
    setSessions([]);
    setActiveSessionIdx(0);
    setUserResponse('');
    setGroupStatus(null);
    if (pollTimerRef.current) {
      clearTimeout(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  }, []);

  useEffect(() => {
    if (!isOpen) {
      resetState();
    }
  }, [isOpen, resetState]);

  // ESC 关闭
  useEffect(() => {
    if (!isOpen) return;
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handleEscape);
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', handleEscape);
      document.body.style.overflow = '';
    };
  }, [isOpen, onClose]);

  // 清理定时器
  useEffect(() => {
    return () => {
      if (pollTimerRef.current) {
        clearTimeout(pollTimerRef.current);
      }
    };
  }, []);

  // ========== 步骤 1 → 步骤 2：启动批量切分 ==========
  const handleStartBatch = async () => {
    if (!sourceRef.trim()) {
      setError('请输入要蒸馏的内容');
      return;
    }
    // 仅 memory 蒸馏需要用户选择目标 agent
    // memory_and_agent 时记忆会自动注入到新创建的 agent，无需用户选择
    if (distillationGoal === 'memory' && !targetAgentId) {
      setError('记忆蒸馏需要选择目标 Agent');
      return;
    }
    setIsProcessing(true);
    setError(null);
    try {
      const result = await distillationApi.startBatchDistillation({
        source_type: sourceType,
        source_ref: sourceRef,
        template_id: templateId,
        max_turns: maxTurns,
        ask_user_on_ambiguity: askUserOnAmbiguity,
        chunk_size: chunkSize,
        distillation_goal: distillationGoal,
        // 仅 memory 蒸馏传 target_agent_id；memory_and_agent 时后端会注入到新创建的 agent
        target_agent_id: distillationGoal === 'memory' ? targetAgentId || undefined : undefined,
      });
      setBatchResult(result);
      // 初始化 sessions 状态
      setSessions(
        result.sessions.map((s) => ({
          session_id: s.session_id,
          chunk_index: s.chunk_index,
          chunk_preview: s.chunk_preview,
          current_state: s.initial_state,
          agent_action: 'proceed',
          next_needed: true,
          preread_summary: null,
          ambiguity_questions: [],
          extracted_content: null,
          quality_score: null,
          turn_count: 0,
          message: null,
          is_finalized: false,
          finalize_result: null,
          is_finalizing: false,
          error: null,
        }))
      );
      setActiveSessionIdx(0);
      setStep('preview');
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setError(`启动批量切分失败：${message}`);
    } finally {
      setIsProcessing(false);
    }
  };

  // ========== 步骤 2 → 步骤 3：进入蒸馏对话 ==========
  const handleEnterDistill = () => {
    setStep('distill');
    // 自动推进第一个 session
    if (sessions.length > 0 && !sessions[0].is_finalized) {
      void handleAdvance(0, undefined);
    }
  };

  // ========== 步骤 3：推进状态机 ==========
  const handleAdvance = async (idx: number, userResp?: string) => {
    // 从 ref 读取最新 session，避免闭包陷阱
    const session = sessionsRef.current[idx];
    if (!session || session.is_finalized || session.is_finalizing) return;

    setSessions((prev) =>
      prev.map((s, i) => (i === idx ? { ...s, is_finalizing: true, error: null } : s))
    );

    try {
      const resp = await distillationApi.advanceDistillation(session.session_id, {
        user_response: userResp,
      });

      setSessions((prev) =>
        prev.map((s, i) =>
          i === idx
            ? {
                ...s,
                current_state: resp.current_state,
                agent_action: resp.agent_action,
                next_needed: resp.next_needed,
                preread_summary: resp.preread_summary ?? s.preread_summary,
                ambiguity_questions: resp.ambiguity_questions ?? s.ambiguity_questions,
                extracted_content: resp.extracted_content ?? s.extracted_content,
                quality_score: resp.quality_score ?? s.quality_score,
                turn_count: resp.turn_count ?? s.turn_count + 1,
                message: resp.message ?? null,
                is_finalizing: false,
              }
            : s
        )
      );

      // 仅在真正到达终态时自动终结
      if (resp.current_state === 'S_FINALIZE' || resp.current_state === 'S_REJECT') {
        autoAdvanceCountRef.current = 0;
        await handleFinalize(idx);
        return;
      }

      // 非终态但不需要用户输入，自动继续推进状态机
      if (!resp.next_needed) {
        autoAdvanceCountRef.current += 1;
        if (autoAdvanceCountRef.current > 10) {
          // 超过最大自动推进次数，强制终结防死循环
          autoAdvanceCountRef.current = 0;
          await handleFinalize(idx);
          return;
        }
        setTimeout(() => {
          void handleAdvance(idx, undefined);
        }, 800);
      } else {
        // next_needed=true，等待用户输入，重置自动推进计数
        autoAdvanceCountRef.current = 0;
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setSessions((prev) =>
        prev.map((s, i) => (i === idx ? { ...s, is_finalizing: false, error: message } : s))
      );
    }
  };

  // ========== 步骤 3：终结（根据 goal 选择 finalize 或 finalize-agent） ==========
  const handleFinalize = async (idx: number) => {
    // 从 ref 读取最新 session，避免闭包陷阱
    const session = sessionsRef.current[idx];
    if (!session || session.is_finalized) return;

    setSessions((prev) =>
      prev.map((s, i) => (i === idx ? { ...s, is_finalizing: true, error: null } : s))
    );

    try {
      let result: FinalizeAgentResponse;
      if (distillationGoal === 'agent' || distillationGoal === 'memory_and_agent') {
        result = await distillationApi.finalizeWithAgentCreation(session.session_id);
      } else {
        // 仅记忆蒸馏，调用普通 finalize 并包装为 FinalizeAgentResponse
        const r = await distillationApi.finalizeDistillation(session.session_id);
        result = {
          stored: r.stored,
          location: r.location,
          memory_id: r.memory_id,
          metadata: r.metadata,
          reason: r.reason,
          agent_creation_result: { success: false, error: 'Not requested' },
        };
      }

      setSessions((prev) =>
        prev.map((s, i) =>
          i === idx
            ? {
                ...s,
                is_finalized: true,
                is_finalizing: false,
                finalize_result: result,
              }
            : s
        )
      );

      // 切换到下一个未完成的 session
      setTimeout(() => {
        void moveToNextSession(idx);
      }, 500);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setSessions((prev) =>
        prev.map((s, i) => (i === idx ? { ...s, is_finalizing: false, error: message } : s))
      );
    }
  };

  // 切换到下一个未完成的 session
  const moveToNextSession = (currentIdx: number) => {
    // 从 ref 读取最新 sessions，避免闭包陷阱
    const latestSessions = sessionsRef.current;
    for (let i = 0; i < latestSessions.length; i++) {
      const nextIdx = (currentIdx + 1 + i) % latestSessions.length;
      const s = latestSessions[nextIdx];
      if (!s.is_finalized && !s.is_finalizing) {
        setActiveSessionIdx(nextIdx);
        if (!s.is_finalized) {
          void handleAdvance(nextIdx, undefined);
        }
        return;
      }
    }
    // 所有 session 都已完成，进入结果步骤
    void refreshGroupStatus();
    setStep('result');
  };

  // 刷新组状态
  const refreshGroupStatus = async () => {
    if (!batchResult) return;
    try {
      const status = await distillationApi.getGroupStatus(batchResult.session_group_id);
      setGroupStatus(status);
    } catch (err) {
      console.error('刷新组状态失败:', err);
    }
  };

  // 自动轮询组状态（蒸馏过程中）
  useEffect(() => {
    if (step !== 'distill' || !batchResult) return;
    const timer = setInterval(() => {
      void refreshGroupStatus();
      setGroupRefreshKey((k) => k + 1);
    }, 5000);
    return () => clearInterval(timer);
  }, [step, batchResult]);

  // 用户回复提交
  const handleSubmitUserResponse = () => {
    if (!userResponse.trim()) return;
    void handleAdvance(activeSessionIdx, userResponse);
    setUserResponse('');
  };

  // 跳过当前 session 的追问
  const handleSkipSession = () => {
    void handleFinalize(activeSessionIdx);
  };

  if (!isOpen) return null;

  // ========== 渲染步骤指示器 ==========
  const renderStepIndicator = () => {
    const steps: Array<{ key: Step; label: string; icon: typeof Upload }> = [
      { key: 'input', label: '输入', icon: Upload },
      { key: 'preview', label: '切分预览', icon: Scissors },
      { key: 'distill', label: '蒸馏对话', icon: MessagesSquare },
      { key: 'result', label: '结果', icon: CheckCircle2 },
    ];
    const currentIdx = steps.findIndex((s) => s.key === step);
    return (
      <div className="flex items-center justify-between mb-6 px-2">
        {steps.map((s, i) => {
          const Icon = s.icon;
          const isActive = i === currentIdx;
          const isCompleted = i < currentIdx;
          return (
            <div key={s.key} className="flex items-center flex-1">
              <div className="flex items-center gap-2">
                <div
                  className={`w-8 h-8 rounded-full flex items-center justify-center transition-colors ${
                    isActive
                      ? 'bg-primary text-primary-foreground'
                      : isCompleted
                      ? 'bg-primary/20 text-primary'
                      : 'bg-muted text-muted-foreground'
                  }`}
                >
                  {isCompleted ? <CheckCircle2 className="w-4 h-4" /> : <Icon className="w-4 h-4" />}
                </div>
                <span
                  className={`text-xs ${
                    isActive ? 'text-primary font-medium' : 'text-muted-foreground'
                  }`}
                >
                  {s.label}
                </span>
              </div>
              {i < steps.length - 1 && (
                <div
                  className={`flex-1 h-0.5 mx-2 ${isCompleted ? 'bg-primary/40' : 'bg-muted'}`}
                />
              )}
            </div>
          );
        })}
      </div>
    );
  };

  // ========== 步骤 1：输入 ==========
  const renderInputStep = () => (
    <div className="space-y-4">
      <div>
        <label className="block text-sm font-medium mb-2">源类型</label>
        <div className="grid grid-cols-2 gap-2">
          {(['text', 'conversation_log'] as const).map((st) => (
            <button
              key={st}
              onClick={() => setSourceType(st)}
              className={`px-3 py-2 rounded-lg text-sm border transition-colors ${
                sourceType === st
                  ? 'border-primary bg-primary/10 text-primary'
                  : 'border-border bg-muted/30 hover:bg-muted/50'
              }`}
            >
              {st === 'text' ? '文本' : '对话日志'}
            </button>
          ))}
        </div>
      </div>

      <div>
        <label className="block text-sm font-medium mb-2">
          内容
          <span className="text-xs text-muted-foreground ml-2">
            （支持超长上下文，自动切分多段蒸馏）
          </span>
        </label>
        <textarea
          value={sourceRef}
          onChange={(e) => setSourceRef(e.target.value)}
          placeholder="在此粘贴需要蒸馏的文本内容..."
          className="w-full h-48 resize-y bg-muted rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
        />
        <div className="text-xs text-muted-foreground mt-1">长度：{sourceRef.length} 字</div>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-sm font-medium mb-2">蒸馏目标</label>
          <div className="space-y-1">
            {(['memory', 'agent', 'memory_and_agent'] as const).map((g) => (
              <button
                key={g}
                onClick={() => setDistillationGoal(g)}
                className={`w-full px-3 py-1.5 rounded-lg text-sm border text-left transition-colors ${
                  distillationGoal === g
                    ? 'border-primary bg-primary/10 text-primary'
                    : 'border-border bg-muted/30 hover:bg-muted/50'
                }`}
              >
                {g === 'memory'
                  ? '仅记忆（注入到指定 agent）'
                  : g === 'agent'
                  ? '仅 Agent（生成角色卡 agent）'
                  : '记忆 + Agent（先记忆，再创建 agent）'}
              </button>
            ))}
          </div>
        </div>

        <div className="space-y-3">
          {/* 记忆蒸馏目标 agent 选择器（仅 memory 时显示；memory_and_agent 会自动注入到新创建的 agent） */}
          {distillationGoal === 'memory' && (
            <div>
              <label className="block text-sm font-medium mb-1">
                目标 Agent
                <span className="text-xs text-red-500 ml-1">*</span>
              </label>
              <select
                value={targetAgentId}
                onChange={(e) => setTargetAgentId(e.target.value)}
                className="w-full bg-muted rounded-lg px-3 py-1.5 text-sm border border-border focus:outline-none focus:ring-2 focus:ring-primary/50"
              >
                <option value="">请选择 Agent</option>
                {agentsList.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name} ({a.id})
                  </option>
                ))}
              </select>
            </div>
          )}

          <div>
            <label className="block text-sm font-medium mb-1">最大轮数：{maxTurns}</label>
            <input
              type="range"
              min={1}
              max={6}
              value={maxTurns}
              onChange={(e) => setMaxTurns(Number(e.target.value))}
              className="w-full"
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">切分大小：{chunkSize}</label>
            <input
              type="range"
              min={500}
              max={8000}
              step={500}
              value={chunkSize}
              onChange={(e) => setChunkSize(Number(e.target.value))}
              className="w-full"
            />
            <div className="text-xs text-muted-foreground mt-1">
              超过此大小的文本会被切分为多段蒸馏
            </div>
          </div>
        </div>
      </div>

      {error && (
        <div className="flex items-start gap-2 p-3 bg-destructive/10 text-destructive rounded-lg text-sm">
          <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      <div className="flex justify-end gap-2 pt-2">
        <button
          onClick={onClose}
          className="px-4 py-2 text-sm border border-border rounded-lg hover:bg-muted/50"
        >
          取消
        </button>
        <button
          onClick={handleStartBatch}
          disabled={!sourceRef.trim() || isProcessing}
          className="px-4 py-2 text-sm bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
        >
          {isProcessing && <Loader2 className="w-4 h-4 animate-spin" />}
          启动批量蒸馏
        </button>
      </div>
    </div>
  );

  // ========== 步骤 2：切分预览 ==========
  const renderPreviewStep = () => {
    if (!batchResult) return null;
    return (
      <div className="space-y-4">
        <div className="bg-primary/5 border border-primary/20 rounded-lg p-3">
          <div className="flex items-center gap-2 text-sm">
            <Scissors className="w-4 h-4 text-primary" />
            <span className="font-medium">共 {batchResult.total_chunks} 段</span>
            <span className="text-muted-foreground">·</span>
            <span className="text-muted-foreground">
              目标：
              {batchResult.distillation_goal === 'memory'
                ? '仅记忆'
                : batchResult.distillation_goal === 'agent'
                ? '仅 Agent'
                : '记忆 + Agent'}
            </span>
          </div>
        </div>

        <div className="space-y-2 max-h-[40vh] overflow-y-auto">
          {batchResult.sessions.map((s) => (
            <div
              key={s.session_id}
              className="border border-border rounded-lg p-3 bg-muted/20"
            >
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs font-medium text-primary">
                  #{s.chunk_index + 1} / {batchResult.total_chunks}
                </span>
                <span className="text-xs text-muted-foreground font-mono">
                  {s.session_id.slice(0, 8)}...
                </span>
              </div>
              <div className="text-xs text-muted-foreground line-clamp-3 whitespace-pre-wrap">
                {s.chunk_preview || '（无预览）'}
              </div>
            </div>
          ))}
        </div>

        <div className="flex justify-between gap-2 pt-2">
          <button
            onClick={() => setStep('input')}
            className="px-4 py-2 text-sm border border-border rounded-lg hover:bg-muted/50 flex items-center gap-1"
          >
            <ChevronLeft className="w-4 h-4" />
            返回
          </button>
          <button
            onClick={handleEnterDistill}
            className="px-4 py-2 text-sm bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 flex items-center gap-1"
          >
            开始蒸馏
            <ChevronRight className="w-4 h-4" />
          </button>
        </div>
      </div>
    );
  };

  // ========== 步骤 3：蒸馏对话 ==========
  const renderDistillStep = () => {
    const session = sessions[activeSessionIdx];
    if (!session) return null;

    return (
      <div className="space-y-4">
        {/* Session 选择器 */}
        <div className="flex items-center gap-2 overflow-x-auto pb-2">
          {sessions.map((s, i) => (
            <button
              key={s.session_id}
              onClick={() => setActiveSessionIdx(i)}
              className={`flex-shrink-0 px-3 py-1.5 text-xs rounded-full border transition-colors ${
                i === activeSessionIdx
                  ? 'border-primary bg-primary/10 text-primary'
                  : s.is_finalized
                  ? 'border-primary/30 bg-primary/5 text-primary/70'
                  : 'border-border bg-muted/30 hover:bg-muted/50'
              }`}
            >
              {s.is_finalized && <CheckCircle2 className="w-3 h-3 inline mr-1" />}
              #{s.chunk_index + 1}
              {s.is_finalizing && <Loader2 className="w-3 h-3 inline ml-1 animate-spin" />}
            </button>
          ))}
        </div>

        {/* 当前 session 状态 */}
        <div className="border border-border rounded-lg p-3 space-y-2">
          <div className="flex items-center justify-between text-xs">
            <span className="font-mono text-muted-foreground">
              {session.session_id.slice(0, 8)}...
            </span>
            <div className="flex items-center gap-2">
              <span className="px-2 py-0.5 bg-primary/10 text-primary rounded-full">
                {session.current_state}
              </span>
              <span className="px-2 py-0.5 bg-muted text-muted-foreground rounded-full">
                轮：{session.turn_count}
              </span>
              {session.quality_score !== null && (
                <span className="px-2 py-0.5 bg-amber-500/10 text-amber-600 rounded-full">
                  Q: {session.quality_score.toFixed(2)}
                </span>
              )}
            </div>
          </div>

          {/* chunk 预览 */}
          <div className="text-xs text-muted-foreground bg-muted/30 rounded p-2 max-h-24 overflow-y-auto whitespace-pre-wrap">
            {session.chunk_preview || '（无预览）'}
          </div>

          {/* preread_summary */}
          {session.preread_summary && (
            <div className="text-xs bg-blue-500/5 border border-blue-500/20 rounded p-2">
              <div className="font-medium text-blue-600 mb-1 flex items-center gap-1">
                <Brain className="w-3 h-3" />
                预读摘要
              </div>
              <div className="whitespace-pre-wrap">{session.preread_summary}</div>
            </div>
          )}

          {/* message */}
          {session.message && (
            <div className="text-xs bg-muted/30 rounded p-2">
              <div className="whitespace-pre-wrap">{session.message}</div>
            </div>
          )}

          {/* ambiguity_questions */}
          {session.ambiguity_questions.length > 0 && (
            <div className="text-xs bg-amber-500/5 border border-amber-500/20 rounded p-2 space-y-1">
              <div className="font-medium text-amber-600 flex items-center gap-1">
                <AlertCircle className="w-3 h-3" />
                需要澄清的问题
              </div>
              {session.ambiguity_questions.map((q, i) => (
                <div key={i} className="whitespace-pre-wrap">
                  Q{i + 1}: {q}
                </div>
              ))}
            </div>
          )}

          {/* extracted_content */}
          {session.extracted_content && (
            <div className="text-xs bg-green-500/5 border border-green-500/20 rounded p-2">
              <div className="font-medium text-green-600 mb-1 flex items-center gap-1">
                <Sparkles className="w-3 h-3" />
                提取内容
              </div>
              <div className="whitespace-pre-wrap max-h-40 overflow-y-auto">
                {session.extracted_content}
              </div>
            </div>
          )}

          {/* error */}
          {session.error && (
            <div className="text-xs bg-destructive/10 text-destructive rounded p-2 flex items-start gap-1">
              <AlertCircle className="w-3 h-3 flex-shrink-0 mt-0.5" />
              <span className="whitespace-pre-wrap">{session.error}</span>
            </div>
          )}

          {/* finalize_result */}
          {session.finalize_result && (
            <div className="text-xs bg-primary/5 border border-primary/20 rounded p-2 space-y-1">
              <div className="font-medium text-primary flex items-center gap-1">
                <CheckCircle2 className="w-3 h-3" />
                终结结果
              </div>
              <div>
                已存储：{session.finalize_result.stored ? '✓' : '✗'} · 位置：
                {session.finalize_result.location}
              </div>
              {session.finalize_result.memory_id !== null && (
                <div>记忆 ID：{session.finalize_result.memory_id}</div>
              )}
              <div className="text-muted-foreground">{session.finalize_result.reason}</div>
              {session.finalize_result.agent_creation_result.success && (
                <div className="mt-2 pt-2 border-t border-primary/20 space-y-1">
                  <div className="font-medium text-primary flex items-center gap-1">
                    <User className="w-3 h-3" />
                    已创建 Agent
                  </div>
                  <div>
                    Agent ID：{session.finalize_result.agent_creation_result.agent_id}
                  </div>
                  {session.finalize_result.agent_creation_result.agent_name && (
                    <div>
                      Agent 名称：{session.finalize_result.agent_creation_result.agent_name}
                    </div>
                  )}
                  {session.finalize_result.agent_creation_result.character_card && (
                    <div className="mt-1 bg-muted/30 rounded p-2 space-y-1">
                      <div className="font-medium">
                        {session.finalize_result.agent_creation_result.character_card.name}
                      </div>
                      <div className="text-muted-foreground">
                        {session.finalize_result.agent_creation_result.character_card.description}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>

        {/* 用户输入区 */}
        {!session.is_finalized && session.next_needed && !session.is_finalizing && (
          <div className="space-y-2">
            <textarea
              value={userResponse}
              onChange={(e) => setUserResponse(e.target.value)}
              placeholder="在此输入你的回复（Ctrl+Enter 发送）..."
              className="w-full h-20 resize-y bg-muted rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
              onKeyDown={(e) => {
                if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                  handleSubmitUserResponse();
                }
              }}
            />
            <div className="flex justify-between items-center">
              <span className="text-xs text-muted-foreground">Ctrl+Enter 发送</span>
              <div className="flex gap-2">
                <button
                  onClick={handleSkipSession}
                  className="px-3 py-1.5 text-xs border border-border rounded-lg hover:bg-muted/50"
                >
                  跳过并终结
                </button>
                <button
                  onClick={handleSubmitUserResponse}
                  disabled={!userResponse.trim()}
                  className="px-3 py-1.5 text-xs bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 disabled:opacity-50"
                >
                  发送
                </button>
              </div>
            </div>
          </div>
        )}

        {/* 导航按钮 */}
        <div className="flex justify-between gap-2 pt-2">
          <button
            onClick={() => setStep('preview')}
            className="px-4 py-2 text-sm border border-border rounded-lg hover:bg-muted/50 flex items-center gap-1"
          >
            <ChevronLeft className="w-4 h-4" />
            返回
          </button>
          <button
            onClick={() => {
              void refreshGroupStatus();
              setStep('result');
            }}
            className="px-4 py-2 text-sm border border-primary text-primary rounded-lg hover:bg-primary/10"
          >
            查看结果
          </button>
        </div>
      </div>
    );
  };

  // ========== 步骤 4：结果汇总 ==========
  const renderResultStep = () => {
    const completedCount = sessions.filter((s) => s.is_finalized).length;
    const agentCreatedCount = sessions.filter(
      (s) => s.finalize_result?.agent_creation_result.success
    ).length;
    const memoryStoredCount = sessions.filter((s) => s.finalize_result?.stored).length;

    return (
      <div className="space-y-4">
        <div className="grid grid-cols-3 gap-3">
          <div className="bg-primary/5 border border-primary/20 rounded-lg p-3 text-center">
            <div className="text-2xl font-bold text-primary">
              {completedCount}/{sessions.length}
            </div>
            <div className="text-xs text-muted-foreground">已完成会话</div>
          </div>
          <div className="bg-green-500/5 border border-green-500/20 rounded-lg p-3 text-center">
            <div className="text-2xl font-bold text-green-600">{memoryStoredCount}</div>
            <div className="text-xs text-muted-foreground">记忆已存储</div>
          </div>
          <div className="bg-amber-500/5 border border-amber-500/20 rounded-lg p-3 text-center">
            <div className="text-2xl font-bold text-amber-600">{agentCreatedCount}</div>
            <div className="text-xs text-muted-foreground">Agent 已创建</div>
          </div>
        </div>

        {groupStatus && (
          <div className="text-xs text-muted-foreground bg-muted/30 rounded p-2">
            组 ID：<span className="font-mono">{groupStatus.group_id}</span>
          </div>
        )}

        <div className="space-y-2 max-h-[40vh] overflow-y-auto">
          {sessions.map((s) => (
            <div
              key={s.session_id}
              className={`border rounded-lg p-3 ${
                s.is_finalized
                  ? 'border-primary/30 bg-primary/5'
                  : 'border-border bg-muted/20'
              }`}
            >
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs font-medium">
                  #{s.chunk_index + 1} ·{' '}
                  {s.is_finalized ? (
                    <CheckCircle2 className="w-3 h-3 inline text-primary" />
                  ) : (
                    <Loader2 className="w-3 h-3 inline animate-spin" />
                  )}
                </span>
                {s.finalize_result?.agent_creation_result.success && (
                  <span className="text-xs px-2 py-0.5 bg-amber-500/10 text-amber-600 rounded-full flex items-center gap-1">
                    <User className="w-3 h-3" />
                    {s.finalize_result.agent_creation_result.agent_name || 'Agent'}
                  </span>
                )}
              </div>
              {s.extracted_content && (
                <div className="text-xs text-muted-foreground line-clamp-2 whitespace-pre-wrap">
                  {s.extracted_content}
                </div>
              )}
            </div>
          ))}
        </div>

        <div className="flex justify-end gap-2 pt-2">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 flex items-center gap-1"
          >
            <CheckCircle2 className="w-4 h-4" />
            完成
          </button>
        </div>
      </div>
    );
  };

  // Liquid Glass: data-glass + motion variants（Dialog gentle spring）
  const glassTier = 'tier-2';
  const validTier = isValidGlassTier(glassTier) ? glassTier : undefined;
  const glassAttributes = buildGlassDataAttributes(true, validTier);
  const springTransition = getComponentSpringTransition('gentle');
  const contentVariants: Variants = {
    initial: { opacity: 0, scale: 0.96, y: 8 },
    animate: { opacity: 1, scale: 1, y: 0, transition: springTransition },
    exit: { opacity: 0, scale: 0.96, y: 8, transition: springTransition },
  };
  const overlayVariants: Variants = {
    initial: { opacity: 0 },
    animate: { opacity: 1, transition: springTransition },
    exit: { opacity: 0, transition: springTransition },
  };
  const contentBaseClassName =
    'relative w-full max-w-4xl mx-4 bg-[var(--dialog-bg)] rounded-[var(--dialog-radius)] shadow-[var(--dialog-shadow)] max-h-[90vh] flex flex-col transition-none';
  const composedContentClassName = validTier
    ? injectGlassClassName(contentBaseClassName, validTier)
    : contentBaseClassName;

  return createPortal(
    <AnimatePresence>
      <motion.div className="fixed inset-0 z-50 flex items-center justify-center">
        <motion.div
          className="absolute inset-0 bg-[var(--dialog-overlay)] backdrop-blur-[var(--dialog-backdrop-blur)]"
          variants={overlayVariants}
          initial="initial"
          animate="animate"
          exit="exit"
          onClick={onClose}
          aria-hidden="true"
        />
        <motion.div
          className={composedContentClassName}
          data-glass={glassAttributes['data-glass'] ?? undefined}
          data-glass-tier={glassAttributes['data-glass-tier'] ?? undefined}
          variants={contentVariants}
          initial="initial"
          animate="animate"
          exit="exit"
          role="dialog"
          aria-modal="true"
        >
          {/* Header */}
          <div className="px-6 py-4 border-b border-[var(--dialog-border)] flex items-center justify-between flex-shrink-0">
            <div className="flex items-center gap-2">
              <Sparkles className="w-5 h-5 text-[var(--color-accent)]" />
              <h2 className="text-lg font-semibold text-[var(--color-text-primary)]">RADIX-Lite 蒸馏</h2>
            </div>
            <button
              onClick={onClose}
              className="p-1 rounded-[var(--radius-sm)] text-[var(--color-text-tertiary)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text-primary)] transition-none"
              aria-label="关闭"
            >
              <X className="w-5 h-5" />
            </button>
          </div>

          {/* Body */}
          <div className="px-6 py-4 overflow-y-auto flex-1">
            {renderStepIndicator()}
            {step === 'input' && renderInputStep()}
            {step === 'preview' && renderPreviewStep()}
            {step === 'distill' && renderDistillStep()}
            {step === 'result' && renderResultStep()}
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>,
    document.body
  );
}
