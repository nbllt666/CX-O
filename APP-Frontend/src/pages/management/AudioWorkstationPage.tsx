/**
 * 作曲/翻唱CXFC 页（原「音频工作站」页，split-audio-workstation-cxfc-modelstation SubTask 4.3）
 *
 * 3 个 Tab：翻唱（CoverPanel）/ 作曲合成 / Qwen3 参考音频资产。
 * 支持 tab= 查询参数直达指定 Tab；非法值（含已移除的 tab=svc）回落默认 Tab cover。
 * 训练/数据集 UI 已整体迁至模型工作站独立前端（CXO-ModelStation/frontend）。
 *
 * 各 Tab 分别消费 voiceworkstationApi 客户端（翻唱/作曲）
 * 或 audioApi 客户端（参考音频资产）对应域接口，非占位页。
 */
import { useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { AudioWaveform, MicVocal, Music4 } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { cn } from '@/lib/utils';
import CoverPanel from './audioWorkstation/CoverPanel';
import { CompositionPanel } from './audioWorkstation/CompositionPanel';
import RefAudioAssetsPanel from './audioWorkstation/RefAudioAssetsPanel';

type TabId = 'cover' | 'music' | 'refaudio';
const VALID_TABS: TabId[] = ['cover', 'music', 'refaudio'];
const DEFAULT_TAB: TabId = 'cover';

const TAB_ICONS: Record<TabId, LucideIcon> = {
  cover: MicVocal,
  music: Music4,
  refaudio: AudioWaveform,
};

export default function AudioWorkstationPage() {
  const { t } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();

  const activeTab: TabId = useMemo(() => {
    const param = searchParams.get('tab');
    return param && VALID_TABS.includes(param as TabId) ? (param as TabId) : DEFAULT_TAB;
  }, [searchParams]);

  const handleTabChange = (tab: TabId) => {
    setSearchParams(tab === DEFAULT_TAB ? {} : { tab }, { replace: true });
  };

  return (
    <div className="mx-auto flex h-full max-w-6xl flex-col gap-5">
      <p className="shrink-0 text-sm text-muted-foreground">
        {t('management.audioWorkstation.subtitle')}
      </p>

      {/* Tab 切换 */}
      <div className="flex shrink-0 flex-wrap gap-2">
        {VALID_TABS.map((tab) => {
          const Icon = TAB_ICONS[tab];
          return (
            <button
              key={tab}
              type="button"
              onClick={() => handleTabChange(tab)}
              className={cn(
                'flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors',
                activeTab === tab
                  ? 'bg-primary text-primary-foreground'
                  : 'border border-[var(--glass-border)] text-muted-foreground hover:bg-[rgba(255,255,255,0.06)]',
              )}
            >
              <Icon className="h-4 w-4" />
              {t(`management.audioWorkstation.tab_${tab}`)}
            </button>
          );
        })}
      </div>

      <div className="min-h-0 flex-1 space-y-5 overflow-y-auto">
        {activeTab === 'cover' && <CoverPanel />}
        {activeTab === 'music' && <CompositionPanel />}
        {activeTab === 'refaudio' && <RefAudioAssetsPanel />}
      </div>
    </div>
  );
}