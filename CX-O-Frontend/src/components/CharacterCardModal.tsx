/**
 * 角色卡创建 Agent 弹窗（RADIX-Lite v1.4.0）。
 *
 * 迁移自 CXHMS frontend/src/components/CharacterCardModal.tsx。
 * 适配点：
 * - 移除 i18n（useTranslation），改用硬编码中文
 * - `agentApi` → `api`（CX-O API client 实例），`agentApi.createAgent` 返回 Agent 对象（含 id/name）
 * - `distillationApi` 改从 `../api/clients/distillation` 导入（CX-O 路径）
 *
 * 用户输入酒馆角色卡 6 字段，直接调用 createAgent API 创建 agent（不经过蒸馏状态机）。
 */
import { useState, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { X, UserPlus, Loader2, CheckCircle2, AlertCircle, Upload, FileJson } from 'lucide-react';
import { api } from '../api/client';
import { distillationApi, type CharacterCardData } from '../api/clients/distillation';

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

  if (!isOpen) return null;

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
      // 尝试解析为对象，失败则传原始字符串（后端兜底）
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

  // 文件选择change处理
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

  return createPortal(
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/50 backdrop-blur-sm"
      onClick={handleClose}
    >
      <div
        className="bg-background border border-border rounded-2xl shadow-2xl w-full max-w-2xl max-h-[90vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-primary/10 flex items-center justify-center">
              <UserPlus className="w-5 h-5 text-primary" />
            </div>
            <div>
              <h2 className="text-lg font-semibold">创建角色卡 Agent</h2>
              <p className="text-xs text-muted-foreground">
                从酒馆角色卡直接创建 Agent，无需经过蒸馏状态机
              </p>
            </div>
          </div>
          <button
            onClick={handleClose}
            disabled={isSubmitting}
            className="text-muted-foreground hover:text-foreground hover:bg-muted rounded-lg p-1.5 transition-colors disabled:opacity-50"
            aria-label="关闭"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-4">
          {success ? (
            <div className="flex flex-col items-center justify-center py-10 text-center">
              <div className="w-16 h-16 rounded-full bg-green-500/10 flex items-center justify-center mb-4">
                <CheckCircle2 className="w-9 h-9 text-green-500" />
              </div>
              <h3 className="text-lg font-semibold mb-2">Agent 创建成功！</h3>
              <p className="text-sm text-muted-foreground mb-1">
                Agent 名称：<span className="font-medium text-foreground">{success.agentName}</span>
              </p>
              <p className="text-xs text-muted-foreground mt-4">
                你可以在 Agent 列表或聊天页面找到这个新角色
              </p>
            </div>
          ) : (
            <>
              {/* v1.4.0 从文件导入区 */}
              <div className="border border-dashed border-border rounded-lg p-3 bg-muted/20">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-medium text-muted-foreground">从文件导入</span>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={() => fileInputRef.current?.click()}
                      disabled={isParsing || isSubmitting}
                      className="flex items-center gap-1 px-2.5 py-1 text-xs rounded-md border border-border bg-background hover:bg-muted transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {isParsing ? (
                        <Loader2 className="w-3 h-3 animate-spin" />
                      ) : (
                        <Upload className="w-3 h-3" />
                      )}
                      上传 PNG
                    </button>
                    <button
                      type="button"
                      onClick={() => setJsonInputMode(!jsonInputMode)}
                      disabled={isParsing || isSubmitting}
                      className="flex items-center gap-1 px-2.5 py-1 text-xs rounded-md border border-border bg-background hover:bg-muted transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      <FileJson className="w-3 h-3" />
                      粘贴 JSON
                    </button>
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
                      className="w-full bg-background rounded-md px-2 py-1.5 text-xs font-mono focus:outline-none focus:ring-2 focus:ring-primary/50 min-h-[80px] resize-y"
                    />
                    <div className="flex justify-end gap-1">
                      <button
                        type="button"
                        onClick={() => {
                          setJsonInputMode(false);
                          setJsonInputText('');
                        }}
                        disabled={isParsing}
                        className="px-2 py-1 text-xs text-muted-foreground hover:text-foreground"
                      >
                        取消
                      </button>
                      <button
                        type="button"
                        onClick={handleParseFromJson}
                        disabled={isParsing || !jsonInputText.trim()}
                        className="px-2.5 py-1 text-xs bg-primary text-primary-foreground rounded-md hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1"
                      >
                        {isParsing && <Loader2 className="w-3 h-3 animate-spin" />}
                        解析 JSON
                      </button>
                    </div>
                  </div>
                )}
              </div>

              {/* 名称 */}
              <div>
                <label className="block text-sm font-medium mb-1.5">
                  姓名 <span className="text-red-500">*</span>
                </label>
                <input
                  type="text"
                  value={form.name}
                  onChange={(e) => handleFieldChange('name', e.target.value)}
                  placeholder="角色的姓名"
                  className="w-full bg-muted rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
                  maxLength={50}
                />
              </div>

              {/* 描述 */}
              <div>
                <label className="block text-sm font-medium mb-1.5">描述</label>
                <textarea
                  value={form.description}
                  onChange={(e) => handleFieldChange('description', e.target.value)}
                  placeholder="描述角色的外观、背景、设定等"
                  className="w-full bg-muted rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50 min-h-[60px] resize-y"
                  maxLength={500}
                />
              </div>

              {/* 性格 */}
              <div>
                <label className="block text-sm font-medium mb-1.5">性格</label>
                <textarea
                  value={form.personality}
                  onChange={(e) => handleFieldChange('personality', e.target.value)}
                  placeholder="描述角色的性格特征，如温柔、傲娇、冷淡等"
                  className="w-full bg-muted rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50 min-h-[60px] resize-y"
                  maxLength={500}
                />
              </div>

              {/* 场景 */}
              <div>
                <label className="block text-sm font-medium mb-1.5">场景</label>
                <textarea
                  value={form.scenario}
                  onChange={(e) => handleFieldChange('scenario', e.target.value)}
                  placeholder="描述对话场景和背景设定"
                  className="w-full bg-muted rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50 min-h-[80px] resize-y"
                  maxLength={1000}
                />
              </div>

              {/* 第一条消息 */}
              <div>
                <label className="block text-sm font-medium mb-1.5">第一条消息</label>
                <textarea
                  value={form.first_mes}
                  onChange={(e) => handleFieldChange('first_mes', e.target.value)}
                  placeholder="角色开场白，AI 第一次回复的内容"
                  className="w-full bg-muted rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50 min-h-[80px] resize-y"
                  maxLength={1000}
                />
              </div>

              {/* 对话示例 */}
              <div>
                <label className="block text-sm font-medium mb-1.5">对话示例</label>
                <textarea
                  value={form.mes_example}
                  onChange={(e) => handleFieldChange('mes_example', e.target.value)}
                  placeholder="对话示例，用 {{user}} 和 {{char}} 表示用户和角色"
                  className="w-full bg-muted rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50 min-h-[80px] resize-y font-mono"
                  maxLength={2000}
                />
              </div>

              {/* v1.4.0 额外字段只读展示区（仅 extraFields 非空时显示） */}
              {extraFields && Object.keys(extraFields).length > 0 && (
                <div className="border border-amber-500/30 bg-amber-500/5 rounded-lg p-3">
                  <div className="text-xs font-medium text-amber-600 mb-1">
                    额外字段（不会写入 Agent）
                  </div>
                  <div className="text-xs text-muted-foreground mb-2">
                    以下字段来自角色卡但不被 Agent 创建流程使用，仅供参考
                  </div>
                  <div className="space-y-1 max-h-40 overflow-y-auto">
                    {Object.entries(extraFields).map(([key, value]) => {
                      const displayValue =
                        typeof value === 'object' ? JSON.stringify(value) : String(value);
                      return (
                        <div key={key} className="text-xs flex gap-2 items-center min-w-0">
                          <span className="font-mono text-amber-600 flex-shrink-0">{key}:</span>
                          <span
                            className="text-muted-foreground truncate flex-1 min-w-0 cursor-help"
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
                <div className="flex items-start gap-2 p-3 bg-red-500/10 border border-red-500/30 rounded-lg text-sm text-red-600">
                  <AlertCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
                  <span>{error}</span>
                </div>
              )}
            </>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-border">
          {success ? (
            <button
              onClick={handleClose}
              className="px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors text-sm"
            >
              关闭
            </button>
          ) : (
            <>
              <button
                onClick={handleClose}
                disabled={isSubmitting}
                className="px-4 py-2 text-sm text-muted-foreground hover:text-foreground hover:bg-muted rounded-lg transition-colors disabled:opacity-50"
              >
                取消
              </button>
              <button
                onClick={handleSubmit}
                disabled={isSubmitting || !form.name.trim()}
                className="px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors text-sm flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {isSubmitting ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    创建中...
                  </>
                ) : (
                  <>
                    <UserPlus className="w-4 h-4" />
                    创建 Agent
                  </>
                )}
              </button>
            </>
          )}
        </div>
      </div>
    </div>,
    document.body
  );
}
