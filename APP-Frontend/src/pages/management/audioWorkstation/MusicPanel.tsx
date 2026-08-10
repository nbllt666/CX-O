/**
 * 作曲合成 Tab（SubTask 7.4 · 音频工作站）
 *
 * 消费 voiceworkstationApi 音乐域：
 * musicListSongs / musicSynthesize / musicGetTask / musicDeleteSong / musicValidateScore。
 * 简化版：展示歌曲列表（含状态/进度/可播放），新建合成（乐谱 JSON 可选，为空时仅提交标题占位）。
 */
import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2, Music4, RefreshCw, Trash2 } from 'lucide-react';
import { voiceworkstationApi, getVoiceWorkstationAudioUrl } from '@/api/clients/voiceworkstation';
import type { SongSummary } from '@/api/clients/voiceworkstation';

export default function MusicPanel() {
  const { t } = useTranslation();
  const [songs, setSongs] = useState<SongSummary[]>([]);
  const [title, setTitle] = useState('');
  const [scoreJson, setScoreJson] = useState('');
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const [failed, setFailed] = useState(false);

  const load = useCallback(() => {
    setLoadError(false);
    voiceworkstationApi
      .musicListSongs()
      .then((res) => setSongs(res.songs ?? []))
      .catch((error) => {
        console.error('[MusicPanel] list failed:', error);
        setLoadError(true);
      });
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const handleSynthesize = async () => {
    if (!title.trim()) return;
    setLoading(true);
    setFailed(false);
    let score: Record<string, unknown> | undefined;
    const trimmed = scoreJson.trim();
    if (trimmed) {
      try {
        score = JSON.parse(trimmed) as Record<string, unknown>;
        const v = await voiceworkstationApi.musicValidateScore(score);
        if (!v.valid) {
          setFailed(true);
          setLoading(false);
          return;
        }
      } catch {
        setFailed(true);
        setLoading(false);
        return;
      }
    }
    try {
      await voiceworkstationApi.musicSynthesize({ score: score ?? {} });
      setTitle('');
      setScoreJson('');
      await load();
    } catch (error) {
      console.error('[MusicPanel] synthesize failed:', error);
      setFailed(true);
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async (songId: string) => {
    setFailed(false);
    try {
      await voiceworkstationApi.musicDeleteSong(songId);
      await load();
    } catch (error) {
      console.error('[MusicPanel] delete failed:', error);
      setFailed(true);
    }
  };

  return (
    <section className="glass-panel space-y-6 p-5">
      {/* 新建合成 */}
      <div className="space-y-3">
        <h4 className="flex items-center gap-2 text-sm font-semibold">
          <Music4 className="h-4 w-4 text-primary" />
          {t('management.audioWorkstation.musicNewSong')}
        </h4>
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
          <Field label={t('management.audioWorkstation.musicTitleLabel')}>
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder={t('management.audioWorkstation.musicTitlePlaceholder')}
              className="w-full rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-3 py-2 text-sm focus:border-[rgba(255,183,225,0.4)] focus:outline-none"
            />
          </Field>
          <Field label={t('management.audioWorkstation.musicScoreLabel')}>
            <input
              value={scoreJson}
              onChange={(e) => setScoreJson(e.target.value)}
              placeholder={t('management.audioWorkstation.musicScorePlaceholder')}
              className="w-full rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-3 py-2 text-sm focus:border-[rgba(255,183,225,0.4)] focus:outline-none"
            />
          </Field>
        </div>
        <button
          type="button"
          onClick={() => void handleSynthesize()}
          disabled={loading || !title.trim()}
          className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-85 disabled:opacity-50"
        >
          {loading ? (
            <>
              <Loader2 className="mr-1 inline h-3.5 w-3.5 animate-spin" />
              {t('management.audioWorkstation.musicSynthesizing')}
            </>
          ) : (
            t('management.audioWorkstation.musicSynthesize')
          )}
        </button>
      </div>

      {failed && <p className="text-xs text-red-400">{t('management.audioWorkstation.musicSynthFailed')}</p>}

      {/* 歌曲列表 */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <h4 className="text-sm font-semibold">{t('management.audioWorkstation.musicSongs')}</h4>
          <button
            type="button"
            onClick={load}
            aria-label={t('management.audioWorkstation.musicRefresh')}
            className="rounded-lg p-1.5 text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.08)]"
          >
            <RefreshCw className="h-3.5 w-3.5" />
          </button>
        </div>

        {loadError ? (
          <p className="text-xs text-red-400">{t('management.audioWorkstation.musicLoadFailed')}</p>
        ) : songs.length === 0 ? (
          <p className="rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.04)] px-3 py-3 text-xs text-muted-foreground">
            {t('management.audioWorkstation.musicEmpty')}
          </p>
        ) : (
          <ul className="space-y-2">
            {songs.map((song) => (
              <li
                key={song.song_id}
                className="flex items-center gap-3 rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.04)] px-3 py-2"
              >
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm">{song.title}</p>
                  <p className="text-xs text-muted-foreground">
                    {song.status} · {t('management.audioWorkstation.musicStage')}: {song.stage} · {song.progress}%
                  </p>
                </div>
                {song.audio_url && (
                  <audio controls className="h-8 w-40" src={getVoiceWorkstationAudioUrl(song.audio_url)} />
                )}
                <button
                  type="button"
                  onClick={() => void handleDelete(song.song_id)}
                  aria-label={t('management.audioWorkstation.musicDelete')}
                  className="rounded-lg p-1.5 text-muted-foreground transition-colors hover:bg-red-500/10 hover:text-red-400"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

function Field(props: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <label className="text-sm text-muted-foreground">{props.label}</label>
      {props.children}
    </div>
  );
}
