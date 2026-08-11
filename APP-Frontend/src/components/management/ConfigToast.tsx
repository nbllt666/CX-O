/**
 * 配置变更通知 toast——管理界面右上角固定展示，4s 后自动收起。
 * 由 ManagementLayout 挂载，驱动自 useConfigReload 收到的 config_changed 事件。
 */
import { CheckCircle2, RotateCcw } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/utils';

export interface ConfigToastData {
  section: string;
  requiresRestart: boolean;
}

export function ConfigToast({ toast }: { toast: ConfigToastData | null }) {
  const { t } = useTranslation();

  if (!toast) return null;

  const title = toast.requiresRestart
    ? t('configReload.restartTitle', { section: toast.section })
    : t('configReload.appliedTitle', { section: toast.section });

  return (
    <div
      role="status"
      aria-live="polite"
      className={cn(
        'fixed right-4 top-4 z-50 flex items-center gap-2 rounded-lg border px-3 py-2 text-sm shadow-lg backdrop-blur-xl',
        toast.requiresRestart
          ? 'border-amber-400/40 bg-amber-500/10 text-amber-300'
          : 'border-emerald-400/40 bg-emerald-500/10 text-emerald-300',
      )}
    >
      {toast.requiresRestart ? (
        <RotateCcw className="h-4 w-4 shrink-0" />
      ) : (
        <CheckCircle2 className="h-4 w-4 shrink-0" />
      )}
      <span>{title}</span>
    </div>
  );
}

export default ConfigToast;