/**
 * @file character-card-modal.tsx — CharacterCardModal 业务组件重组（模块7）
 * ============================================================================
 * 模块: 模块7 业务组件重组层 — B 组弹窗类
 * 落点: C:\CX-O\CX-O-Frontend\src\components\business\character-card-modal.tsx
 * 原组件: src/components/CharacterCardModal.tsx
 *
 * 重组策略（MODULE-7 AGENTS.md §2.4）:
 *   - 保留现有业务逻辑（表单提交、PNG/JSON 解析、Agent 创建）
 *   - UI 层换用模块6 ui-v2 Button + glass 工具函数
 *   - 注入 Liquid Glass + data-glass + motion variants（Dialog gentle spring）
 *   - 通过 className 消费 token，不硬编码颜色
 *
 * 二次元资产保留:
 *   - 原组件为角色卡创建表单弹窗（表单字段 + 文件解析逻辑完整保留）
 *
 * 跨模块导入约束:
 *   - 仅 import 模块6 ui-v2 + 业务逻辑依赖（@/api, @/api/clients/distillation）
 *   - 禁止 import 模块8/9 内部实现 + 旧 @/components/ 下组件
 * ============================================================================
 */

import { useState, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { motion, AnimatePresence, type Variants } from 'framer-motion';
import { UserPlus, Loader2, CheckCircle2, AlertCircle, Upload, FileJson } from 'lucide-react';
import {
  Button,
  buildGlassDataAttributes,
  injectGlassClassName,
  isValidGlassTier,
  getComponentSpringTransition,
} from '@/components/ui-v2';
import { api } from '@/api/client';
import { distillationApi, type CharacterCardData } from '@/api/clients/distillation';

interface CharacterCardModalProps {
  isOpen: boolean;
  onClose: () => void;
  onCreated?: (agentId: string, agentName: string) => void;
}

interface CharacterCardForm {
  name: string;
  description: string;
  personality: string;
  scenario: string;
  first_mes: string;
  mes_example: string;
}

const EMPTY_FORM: CharacterCardForm = {
  name: '',
  description: '',
  personality: '',
  scenario: '',
  first_mes: '',
  mes_example: '',
};

export function CharacterCardModal({ isOpen, onClose, onCreated }: CharacterCardModalProps) {
  const [form, setForm] = useState<CharacterCardForm>(EMPTY_FORM);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<{ agentId: string; agentName: string } | null>(null);

  // v1.4.0 角色卡导入状态
  const [isParsing, setIsParsing] = useState(false);
  const [extraFields, setExtraFields] = useState<Record<string, unknown> | null>(null);
  const [jsonInputMode, setJsonInputMode] = useState(false);
  const [jsonInputText, setJsonInputText] = useState('');
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!isOpen) {
      setForm(EMPTY_FORM);
      setError(null);
      setSuccess(null);
      setIsSubmitting(false);
      setIsParsing(false);
      setExtraFields(null);
      setJsonInputMode(false);
      setJsonInputText('');
    }
  }, [isOpen]);

  // ESC 关闭
  useEffect(() => {
    if (!isOpen) return;
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !isSubmitting) onClose();
    };
    document.addEventListener('keydown', handleEscape);
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', handleEscape);
      document.body.style.overflow = '';
    };
  }, [isOpen, onClose, isSubmitting]);

  const handleFieldChange = (field: keyof CharacterCardForm, value: string) => {
    setForm((prev) => ({ ...prev, [field]: value }));
  };

  // v1.4.0 从角色卡数据填充表单
  const fillFormFromCard = (card: CharacterCardData) => {
    setForm({
      name: card.name || '',
      description: card.description || '',
      personality: card.personality || '',
      scenario: card.scenario || '',
      first_mes: card.first_mes || '',
      mes_example: card.mes_example || '',
    });
    setExtraFields(card.extra_fields || null);
  };

  // v1.4.0 PNG 文件上传导入
  const handleParseFromFile = async (file: File) => {
    setIsParsing(true);
    setError(null);
    try {
      const resp = await distillationApi.parseCharacterCardFromFile(file);
      fillFormFromCard(resp.character_card_data);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setError(`解析失败：${message}`);
    } finally {
      setIsParsing(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  // v1.4.0 JSON 内容粘贴导入
  const handleParseFromJson = async () => {
    if (!jsonInputText.trim()) return;
    setIsParsing(true);
    setError(null);
    try {
      let jsonContent: string | object = jsonInputText;
      try {
        jsonContent = JSON.parse(jsonInputText);
      } catch {
        // 保持原始字符串，后端会处理
      }
      const resp = await distillationApi.parseCharacterCardFromJson(jsonContent);
      fillFormFromCard(resp.character_card_data);
      setJsonInputMode(false);
      setJsonInputText('');
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setError(`解析失败：${message}`);
    } finally {
      setIsParsing(false);
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) void handleParseFromFile(file);
  };

  const buildSystemPrompt = (card: CharacterCardForm): string => {
    const sections: string[] = [];
    sections.push(`# 角色设定`);
    sections.push(`姓名：${card.name || '（未设置）'}`);
    if (card.description) {
      sections.push(`\n## 角色描述\n${card.description}`);
    }
    if (card.personality) {
      sections.push(`\n## 性格特征\n${card.personality}`);
    }
    if (card.scenario) {
      sections.push(`\n## 场景设定\n${card.scenario}`);
    }
    if (card.mes_example) {
      sections.push(`\n## 对话示例\n${card.mes_example}`);
    }
    sections.push(
      `\n## 行为要求\n- 严格保持角色设定，不要跳出角色\n- 使用符合角色性格的语气和表达方式\n- 主动推进对话，不要等待用户引导`
    );
    return sections.join('\n');
  };

  const handleSubmit = async () => {
    if (!form.name.trim()) {
      setError('姓名为必填项');
      return;
    }
    setIsSubmitting(true);
    setError(null);
    try {
      const systemPrompt = buildSystemPrompt(form);
      const agent = await api.createAgent({
        name: form.name.trim(),
        description: form.description.trim() || `角色卡 Agent: ${form.name.trim()}`,
        system_prompt: systemPrompt,
        model: 'gemma4-e4b',
        temperature: 0.8,
        use_memory: true,
        use_tools: true,
        memory_scene: 'default',
      });
      const agentId = agent?.id || '';
      const agentName = agent?.name || form.name.trim();
      setSuccess({ agentId, agentName });
      if (onCreated && agentId) {
        onCreated(agentId, agentName);
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setError(`创建 Agent 失败：${message}`);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleClose = () => {
    if (isSubmitting) return;
    onClose();
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
    'bg-[var(--dialog-bg)] border border-[var(--dialog-border)] rounded-[var(--dialog-radius)] shadow-[var(--dialog-shadow)] w-full max-w-2xl max-h-[90vh] flex flex-col transition-none';
  const composedContentClassName = validTier
    ? injectGlassClassName(contentBaseClassName, validTier)
    : contentBaseClassName;

  if (typeof document === 'undefined') return null;

  return createPortal(
    <AnimatePresence>
      {isOpen && (
        <motion.div
          className="fixed inset-0 z-[100] flex items-center justify-center"
          initial="initial"
          animate="animate"
          exit="exit"
        >
          <motion.div
            className="absolute inset-0 bg-[var(--dialog-overlay)] backdrop-blur-[var(--dialog-backdrop-blur)]"
            variants={overlayVariants}
            initial="initial"
            animate="animate"
            exit="exit"
            onClick={handleClose}
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
            aria-labelledby="ccm-title"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Header */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--dialog-border)]">
              <div className="flex items-center gap-3">
                <div className="w-9 h-9 rounded-[var(--radius-md)] bg-[var(--color-accent-light)] flex items-center justify-center">
                  <UserPlus className="w-5 h-5 text-[var(--color-accent)]" />
                </div>
                <div>
                  <h2 id="ccm-title" className="text-lg font-semibold text-[var(--color-text-primary)]">
                    创建角色卡 Agent
                  </h2>
                  <p className="text-xs text-[var(--color-text-tertiary)]">
                    从酒馆角色卡直接创建 Agent，无需经过蒸馏状态机
                  </p>
                </div>
              </div>
              <button
                onClick={handleClose}
                disabled={isSubmitting}
                className="p-1.5 rounded-[var(--radius-sm)] text-[var(--color-text-tertiary)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text-primary)] disabled:opacity-50 transition-none"
                aria-label="关闭"
              >
                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            {/* Body */}
            <div className="flex-1 overflow-y-auto px-6 py-5 space-y-4">
              {success ? (
                <div className="flex flex-col items-center justify-center py-10 text-center">
                  <div className="w-16 h-16 rounded-full bg-[var(--color-success-bg)] flex items-center justify-center mb-4">
                    <CheckCircle2 className="w-9 h-9 text-[var(--color-success)]" />
                  </div>
                  <h3 className="text-lg font-semibold mb-2 text-[var(--color-text-primary)]">Agent 创建成功！</h3>
                  <p className="text-sm text-[var(--color-text-tertiary)] mb-1">
                    Agent 名称：<span className="font-medium text-[var(--color-text-primary)]">{success.agentName}</span>
                  </p>
                  <p className="text-xs text-[var(--color-text-tertiary)] mt-4">
                    你可以在 Agent 列表或聊天页面找到这个新角色
                  </p>
                </div>
              ) : (
                <>
                  {/* v1.4.0 从文件导入区 */}
                  <div className="border border-dashed border-[var(--dialog-border)] rounded-[var(--radius-md)] p-3 bg-[var(--color-bg-secondary)]">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-xs font-medium text-[var(--color-text-tertiary)]">从文件导入</span>
                      <div className="flex gap-2">
                        <Button
                          variant="secondary"
                          size="sm"
                          onClick={() => fileInputRef.current?.click()}
                          disabled={isParsing || isSubmitting}
                        >
                          {isParsing ? <Loader2 className="w-3 h-3 animate-spin" /> : <Upload className="w-3 h-3" />}
                          上传 PNG
                        </Button>
                        <Button
                          variant="secondary"
                          size="sm"
                          onClick={() => setJsonInputMode(!jsonInputMode)}
                          disabled={isParsing || isSubmitting}
                        >
                          <FileJson className="w-3 h-3" />
                          粘贴 JSON
                        </Button>
                      </div>
                      <input
                        ref={fileInputRef}
                        type="file"
                        accept=".png,image/png"
                        onChange={handleFileChange}
                        className="hidden"
                      />
                    </div>
                    {jsonInputMode && (
                      <div className="space-y-2 mt-2">
                        <textarea
                          value={jsonInputText}
                          onChange={(e) => setJsonInputText(e.target.value)}
                          placeholder="在此粘贴角色卡 JSON 内容..."
                          className="w-full bg-[var(--color-bg-primary)] rounded-[var(--radius-sm)] px-2 py-1.5 text-xs font-mono focus:outline-none focus:ring-2 focus:ring-[var(--color-accent-light)] min-h-[80px] resize-y text-[var(--color-text-primary)]"
                        />
                        <div className="flex justify-end gap-1">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => {
                              setJsonInputMode(false);
                              setJsonInputText('');
                            }}
                            disabled={isParsing}
                          >
                            取消
                          </Button>
                          <Button
                            variant="primary"
                            size="sm"
                            onClick={handleParseFromJson}
                            disabled={isParsing || !jsonInputText.trim()}
                          >
                            {isParsing && <Loader2 className="w-3 h-3 animate-spin" />}
                            解析 JSON
                          </Button>
                        </div>
                      </div>
                    )}
                  </div>

                  {/* 名称 */}
                  <div>
                    <label className="block text-sm font-medium mb-1.5 text-[var(--color-text-primary)]">
                      姓名 <span className="text-[var(--color-error)]">*</span>
                    </label>
                    <input
                      type="text"
                      value={form.name}
                      onChange={(e) => handleFieldChange('name', e.target.value)}
                      placeholder="角色的姓名"
                      className="w-full bg-[var(--color-bg-secondary)] rounded-[var(--radius-md)] px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[var(--color-accent-light)] text-[var(--color-text-primary)]"
                      maxLength={50}
                    />
                  </div>

                  {/* 描述 */}
                  <div>
                    <label className="block text-sm font-medium mb-1.5 text-[var(--color-text-primary)]">描述</label>
                    <textarea
                      value={form.description}
                      onChange={(e) => handleFieldChange('description', e.target.value)}
                      placeholder="描述角色的外观、背景、设定等"
                      className="w-full bg-[var(--color-bg-secondary)] rounded-[var(--radius-md)] px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[var(--color-accent-light)] min-h-[60px] resize-y text-[var(--color-text-primary)]"
                      maxLength={500}
                    />
                  </div>

                  {/* 性格 */}
                  <div>
                    <label className="block text-sm font-medium mb-1.5 text-[var(--color-text-primary)]">性格</label>
                    <textarea
                      value={form.personality}
                      onChange={(e) => handleFieldChange('personality', e.target.value)}
                      placeholder="描述角色的性格特征，如温柔、傲娇、冷淡等"
                      className="w-full bg-[var(--color-bg-secondary)] rounded-[var(--radius-md)] px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[var(--color-accent-light)] min-h-[60px] resize-y text-[var(--color-text-primary)]"
                      maxLength={500}
                    />
                  </div>

                  {/* 场景 */}
                  <div>
                    <label className="block text-sm font-medium mb-1.5 text-[var(--color-text-primary)]">场景</label>
                    <textarea
                      value={form.scenario}
                      onChange={(e) => handleFieldChange('scenario', e.target.value)}
                      placeholder="描述对话场景和背景设定"
                      className="w-full bg-[var(--color-bg-secondary)] rounded-[var(--radius-md)] px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[var(--color-accent-light)] min-h-[80px] resize-y text-[var(--color-text-primary)]"
                      maxLength={1000}
                    />
                  </div>

                  {/* 第一条消息 */}
                  <div>
                    <label className="block text-sm font-medium mb-1.5 text-[var(--color-text-primary)]">第一条消息</label>
                    <textarea
                      value={form.first_mes}
                      onChange={(e) => handleFieldChange('first_mes', e.target.value)}
                      placeholder="角色开场白，AI 第一次回复的内容"
                      className="w-full bg-[var(--color-bg-secondary)] rounded-[var(--radius-md)] px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[var(--color-accent-light)] min-h-[80px] resize-y text-[var(--color-text-primary)]"
                      maxLength={1000}
                    />
                  </div>

                  {/* 对话示例 */}
                  <div>
                    <label className="block text-sm font-medium mb-1.5 text-[var(--color-text-primary)]">对话示例</label>
                    <textarea
                      value={form.mes_example}
                      onChange={(e) => handleFieldChange('mes_example', e.target.value)}
                      placeholder="对话示例，用 {{user}} 和 {{char}} 表示用户和角色"
                      className="w-full bg-[var(--color-bg-secondary)] rounded-[var(--radius-md)] px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[var(--color-accent-light)] min-h-[80px] resize-y font-mono text-[var(--color-text-primary)]"
                      maxLength={2000}
                    />
                  </div>

                  {/* v1.4.0 额外字段只读展示区 */}
                  {extraFields && Object.keys(extraFields).length > 0 && (
                    <div className="border border-[var(--color-warning-border)] bg-[var(--color-warning-bg)] rounded-[var(--radius-md)] p-3">
                      <div className="text-xs font-medium text-[var(--color-warning)] mb-1">
                        额外字段（不会写入 Agent）
                      </div>
                      <div className="text-xs text-[var(--color-text-tertiary)] mb-2">
                        以下字段来自角色卡但不被 Agent 创建流程使用，仅供参考
                      </div>
                      <div className="space-y-1 max-h-40 overflow-y-auto">
                        {Object.entries(extraFields).map(([key, value]) => {
                          const displayValue =
                            typeof value === 'object' ? JSON.stringify(value) : String(value);
                          return (
                            <div key={key} className="text-xs flex gap-2 items-center min-w-0">
                              <span className="font-mono text-[var(--color-warning)] flex-shrink-0">{key}:</span>
                              <span
                                className="text-[var(--color-text-tertiary)] truncate flex-1 min-w-0 cursor-help"
                                title={displayValue}
                              >
                                {displayValue}
                              </span>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}

                  {error && (
                    <div className="flex items-start gap-2 p-3 bg-[var(--color-error-bg)] border border-[var(--color-error-border)] rounded-[var(--radius-md)] text-sm text-[var(--color-error)]">
                      <AlertCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
                      <span>{error}</span>
                    </div>
                  )}
                </>
              )}
            </div>

            {/* Footer */}
            <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-[var(--dialog-border)]">
              {success ? (
                <Button variant="primary" size="md" onClick={handleClose}>
                  关闭
                </Button>
              ) : (
                <>
                  <Button variant="ghost" size="md" onClick={handleClose} disabled={isSubmitting}>
                    取消
                  </Button>
                  <Button
                    variant="primary"
                    size="md"
                    onClick={handleSubmit}
                    disabled={isSubmitting || !form.name.trim()}
                    loading={isSubmitting}
                  >
                    {!isSubmitting && <UserPlus className="w-4 h-4" />}
                    {isSubmitting ? '创建中...' : '创建 Agent'}
                  </Button>
                </>
              )}
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>,
    document.body,
  );
}
