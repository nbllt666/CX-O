/**
 * 音频工作站页（SubTask 7.4）
 *
 * 功能口径对齐 CX-O-Frontend AudioWorkstationPage：5 个 Tab：
 * VoxCPM 生成 / SVC 训练推理 / 作曲合成 / Orpheus 合成 / 参考音频管理。
 * 支持 tab= 查询参数直达指定 Tab。
 *
 * 各 Tab 分别消费 voiceworkstationApi 客户端对应域接口，非占位页。
 */
import { useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { AudioWaveform, MicVocal, Music4, Sparkles, Wand2 } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { cn } from '@/lib/utils';
import VoxCPMPanel from './audioWorkstation/VoxCPMPanel';
import SVCPanel from './audioWorkstation/SVCPanel';
import { CompositionPanel } from './audioWorkstation/CompositionPanel';
import OrpheusPanel from './audioWorkstation/OrpheusPanel';
import RefAudioPanel from './audioWorkstation/RefAudioPanel';

type TabId = 'voxcpm' | 'svc' | 'music' | 'orpheus' | 'refaudio';
const VALID_TABS: TabId[] = ['voxcpm', 'svc', 'music', 'orpheus', 'refaudio'];

const TAB_ICONS: Record<TabId, LucideIcon> = {
  voxcpm: Sparkles,
  svc: MicVocal,
  music: Music4,
  orpheus: AudioWaveform,
  refaudio: Wand2,
};

export default function AudioWorkstationPage() {
  const { t } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();

  const activeTab: TabId = useMemo(() => {
    const param = searchParams.get('tab');
    return param && VALID_TABS.includes(param as TabId) ? (param as TabId) : 'voxcpm';
  }, [searchParams]);

  const handleTabChange = (tab: TabId) => {
    setSearchParams(tab === 'voxcpm' ? {} : { tab }, { replace: true });
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
        {activeTab === 'voxcpm' && <VoxCPMPanel />}
        {activeTab === 'svc' && <SVCPanel />}
        {activeTab === 'music' && <CompositionPanel />}
        {activeTab === 'orpheus' && <OrpheusPanel />}
        {activeTab === 'refaudio' && <RefAudioPanel />}
      </div>
    </div>
  );
}
