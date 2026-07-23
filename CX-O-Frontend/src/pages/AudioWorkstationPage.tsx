/**
 * 音频工作站页（原「语音工作站」）。
 *
 * 5 个 Tab：VoxCPM 生成 / SVC 训练推理 / 作曲 / Orpheus 合成 / 参考音频管理。
 * 作曲 Tab 由原独立 /compose 路由合并而来。支持 ?tab= 查询参数直达指定 Tab。
 * Spec: refactor-audiostation-engine-consolidation Task 9.1 / 9.2
 */
import { useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { PageHeader } from '../components/layout';
import { useTranslation } from 'react-i18next';
import { VoxCPMPanel } from './audioWorkstation/VoxCPMPanel';
import { SVCPanel } from './audioWorkstation/SVCPanel';
import { CompositionPanel } from './audioWorkstation/CompositionPanel';
import { OrpheusPanel } from './audioWorkstation/OrpheusPanel';
import { RefAudioPanel } from './audioWorkstation/RefAudioPanel';
import { cn } from '../lib/utils';

type TabId = 'voxcpm' | 'svc' | 'compose' | 'orpheus' | 'refaudio';

const VALID_TABS: TabId[] = ['voxcpm', 'svc', 'compose', 'orpheus', 'refaudio'];

export function AudioWorkstationPage() {
  const { t } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();

  const activeTab: TabId = useMemo(() => {
    const param = searchParams.get('tab');
    return (param && VALID_TABS.includes(param as TabId)) ? (param as TabId) : 'voxcpm';
  }, [searchParams]);

  const tabs: { id: TabId; labelKey: string }[] = [
    { id: 'voxcpm', labelKey: 'tabVoxcpm' },
    { id: 'svc', labelKey: 'tabSvc' },
    { id: 'compose', labelKey: 'tabCompose' },
    { id: 'orpheus', labelKey: 'tabOrpheus' },
    { id: 'refaudio', labelKey: 'tabRefAudio' },
  ];

  const handleTabChange = (tab: TabId) => {
    setSearchParams(tab === 'voxcpm' ? {} : { tab }, { replace: true });
  };

  return (
    <div className="h-full flex flex-col">
      <div className="px-6 pt-6">
        <PageHeader title={t('audioWorkstation.title')} description={t('audioWorkstation.description')} />
      </div>

      <div className="px-6 pb-4">
        <div className="flex items-center gap-1 flex-wrap">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => handleTabChange(tab.id)}
              className={cn(
                'flex items-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium transition-colors',
                activeTab === tab.id
                  ? 'bg-[var(--color-accent)] text-white'
                  : 'bg-[var(--color-bg-tertiary)] text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-hover)]'
              )}
            >
              {t(`audioWorkstation.${tab.labelKey}`)}
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-6 pb-6">
        {activeTab === 'voxcpm' && <VoxCPMPanel />}
        {activeTab === 'svc' && <SVCPanel />}
        {activeTab === 'compose' && <CompositionPanel />}
        {activeTab === 'orpheus' && <OrpheusPanel />}
        {activeTab === 'refaudio' && <RefAudioPanel />}
      </div>
    </div>
  );
}
