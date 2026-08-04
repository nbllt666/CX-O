import { Button, Card, CardBody } from '@/components/ui-v2';
import { themeOptions, accentColors } from '../types';

export interface AppearanceCardProps {
  theme: string;
  onThemeChange: (theme: 'light' | 'dark' | 'system') => void;
  selectedAccent: string;
  onSelectedAccentChange: (accent: string) => void;
  cn: (...args: Array<string | undefined | null | false>) => string;
}

export function AppearanceCard(props: AppearanceCardProps) {
  const { theme, onThemeChange, selectedAccent, onSelectedAccentChange, cn } = props;

  return (
    <div className="space-y-8">
      <Card>
        <CardBody>
          <h3 className="text-lg font-semibold mb-4">主题设置</h3>
          <div className="grid grid-cols-3 gap-4">
            {themeOptions.map((option) => (
              <button
                key={option.value}
                onClick={() => onThemeChange(option.value as 'light' | 'dark' | 'system')}
                className={cn(
                  'p-4 rounded-[var(--card-radius)] border transition-all text-left glass-panel-interactive bg-white/[0.04]',
                  theme === option.value
                    ? 'border-[var(--color-accent)] ring-2 ring-[var(--color-accent)]/30 bg-[var(--color-accent)]/10'
                    : 'border-transparent hover:border-transparent hover:bg-white/[0.02]'
                )}
              >
                <div className="text-2xl mb-2">{option.icon}</div>
                <div className="font-medium">{option.label}</div>
                <div className="text-xs text-[var(--color-text-tertiary)]">
                  {option.description}
                </div>
              </button>
            ))}
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardBody>
          <h3 className="text-lg font-semibold mb-4">强调色</h3>
          <div className="flex gap-3">
            {accentColors.map((color) => (
              <button
                key={color.value}
                onClick={() => onSelectedAccentChange(color.value)}
                className={cn(
                  'w-10 h-10 rounded-full transition-all',
                  color.class,
                  selectedAccent === color.value
                    ? 'ring-2 ring-offset-2 ring-[var(--color-accent)] scale-110'
                    : 'hover:scale-105'
                )}
                title={color.label}
              />
            ))}
          </div>
          <p className="text-xs text-[var(--color-text-tertiary)] mt-3">
            强调色用于按钮、链接和高亮元素
          </p>
        </CardBody>
      </Card>

      <Card>
        <CardBody>
          <h3 className="text-lg font-semibold mb-4">连接设置</h3>
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium mb-2">离线超时时间</label>
              <p className="text-xs text-[var(--color-text-tertiary)] mb-3">
                当前端断开连接超过此时间后，系统将自动保存当前上下文到长期记忆
              </p>
              <select
                value={localStorage.getItem('cxhms-offline-timeout') || '60'}
                onChange={(e) => {
                  localStorage.setItem('cxhms-offline-timeout', e.target.value);
                  window.dispatchEvent(
                    new CustomEvent('offline-timeout-change', { detail: e.target.value })
                  );
                }}
                className="w-full px-3 py-2 bg-[var(--color-bg-tertiary)] border border-[var(--color-border)] rounded-[var(--radius-md)] text-sm focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)]"
              >
                <option value="30">30 秒</option>
                <option value="60">60 秒（默认）</option>
                <option value="120">2 分钟</option>
                <option value="300">5 分钟</option>
              </select>
            </div>
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardBody>
          <h3 className="text-lg font-semibold mb-4">界面预览</h3>
          <div className="p-4 bg-[var(--color-bg-tertiary)] rounded-[var(--radius-lg)]">
            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 rounded-full bg-[var(--color-accent)] flex items-center justify-center text-[var(--color-bg-primary)]">
                AI
              </div>
              <div>
                <div className="font-medium">示例标题</div>
                <div className="text-sm text-[var(--color-text-secondary)]">
                  这是一个预览文本
                </div>
              </div>
            </div>
            <div className="flex gap-2">
              <Button size="sm">主要按钮</Button>
              <Button variant="secondary" size="sm">
                次要按钮
              </Button>
              <Button variant="ghost" size="sm">
                幽灵按钮
              </Button>
            </div>
          </div>
        </CardBody>
      </Card>
    </div>
  );
}
