/**
 * 作曲面板：歌谱编辑器 + 合成面板 + 任务进度 + 歌曲历史。
 *
 * 提取自原 CompositionPage（独立 /compose 路由已移除），作为音频工作站「作曲」Tab 内容。
 * Spec: refactor-audiostation-engine-consolidation Task 9.2
 */
import { useState, useEffect, useRef, useCallback } from 'react';
import { api, getVoiceWorkstationAudioUrl } from '@/api/client';
import type { SVCModel, SongSummary, SongTask } from '@/api/client';
import { cn } from '@/lib/utils';
import { Button, Card, CardBody, Input, Textarea, Badge, Slider } from '@/components/ui';
import { useTranslation } from 'react-i18next';

// ── 编辑器本地状态类型（与后端歌谱契约字段对齐） ──

interface MelodyNote {
  pitch: string;
  beats: number;
  lyric: string;
}

interface ChordRow {
  chord: string;
  beats: number;
}

type EditorMode = 'form' | 'json';

const DEFAULT_MELODY: MelodyNote[] = [{ pitch: 'C4', beats: 1, lyric: '' }];

export function CompositionPanel() {
  const { t } = useTranslation();

  // ── 歌谱编辑器状态 ──
  const [title, setTitle] = useState('');
  const [bpm, setBpm] = useState(120);
  const [timeSignature, setTimeSignature] = useState('4/4');
  const [keySignature, setKeySignature] = useState('C');
  const [accompanimentStyle, setAccompanimentStyle] = useState('piano');
  const [melody, setMelody] = useState<MelodyNote[]>(DEFAULT_MELODY);
  const [chords, setChords] = useState<ChordRow[]>([]);
  const [editorMode, setEditorMode] = useState<EditorMode>('form');
  const [jsonText, setJsonText] = useState('');

  // ── 校验状态 ──
  const [validating, setValidating] = useState(false);
  const [validateErrors, setValidateErrors] = useState<string[] | null>(null);
  const [validateOk, setValidateOk] = useState(false);

  // ── MusicXML 导入 ──
  const [importing, setImporting] = useState(false);
  const musicXmlFileRef = useRef<HTMLInputElement>(null);

  // ── 合成面板 ──
  const [voiceBank, setVoiceBank] = useState('');
  const [svcModel, setSvcModel] = useState('');
  const [svcModels, setSvcModels] = useState<SVCModel[]>([]);
  const [transpose, setTranspose] = useState(0);
  const [vocalGain, setVocalGain] = useState(1.0);
  const [accompanimentGain, setAccompanimentGain] = useState(0.8);
  const [submitting, setSubmitting] = useState(false);

  // ── 任务进度 ──
  const [currentSongId, setCurrentSongId] = useState<string | null>(null);
  const [currentTask, setCurrentTask] = useState<SongTask | null>(null);

  // ── 歌曲历史 ──
  const [songs, setSongs] = useState<SongSummary[]>([]);
  const [playingUrl, setPlayingUrl] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement>(null);

  // ── 数据加载 ──

  const refreshSongs = useCallback(() => {
    api.musicListSongs().then((r) => setSongs(r.songs)).catch(() => {});
  }, []);

  useEffect(() => {
    refreshSongs();
    api.getSoVITSSVCStatus().then((s) => setSvcModels(s.models || [])).catch(() => {});
  }, [refreshSongs]);

  // 任务进度轮询：完成后刷新历史并停止
  useEffect(() => {
    if (!currentSongId) return;
    let stopped = false;
    const poll = async () => {
      try {
        const task = await api.musicGetTask(currentSongId);
        if (stopped) return;
        setCurrentTask(task);
        if (task.status === 'completed' || task.status === 'failed') {
          stopped = true;
          clearInterval(timer);
          if (task.status === 'completed') refreshSongs();
        }
      } catch {
        // 任务查询失败（如服务暂不可达）时静默，下一轮继续
      }
    };
    poll();
    const timer = setInterval(poll, 3000);
    return () => {
      stopped = true;
      clearInterval(timer);
    };
  }, [currentSongId, refreshSongs]);

  // ── 歌谱构造 / 双模式同步 ──

  const buildScore = useCallback((): Record<string, unknown> => {
    return {
      title,
      bpm,
      time_signature: timeSignature,
      key: keySignature,
      melody: melody.map((n) => ({ pitch: n.pitch, beats: n.beats, lyric: n.lyric })),
      chords: chords.map((c) => ({ chord: c.chord, beats: c.beats })),
      accompaniment_style: accompanimentStyle,
    };
  }, [title, bpm, timeSignature, keySignature, melody, chords, accompanimentStyle]);

  const fillFormFromScore = useCallback((score: Record<string, unknown>) => {
    const s = score as {
      title?: string;
      bpm?: number;
      time_signature?: string;
      key?: string;
      melody?: { pitch?: string; beats?: number; lyric?: string }[];
      chords?: { chord?: string; beats?: number }[];
      accompaniment_style?: string;
    };
    setTitle(typeof s.title === 'string' ? s.title : '');
    setBpm(typeof s.bpm === 'number' ? s.bpm : 120);
    setTimeSignature(typeof s.time_signature === 'string' ? s.time_signature : '4/4');
    setKeySignature(typeof s.key === 'string' ? s.key : 'C');
    setAccompanimentStyle(typeof s.accompaniment_style === 'string' ? s.accompaniment_style : 'piano');
    setMelody(
      Array.isArray(s.melody) && s.melody.length > 0
        ? s.melody.map((n) => ({
            pitch: typeof n.pitch === 'string' ? n.pitch : 'C4',
            beats: typeof n.beats === 'number' ? n.beats : 1,
            lyric: typeof n.lyric === 'string' ? n.lyric : '',
          }))
        : DEFAULT_MELODY
    );
    setChords(
      Array.isArray(s.chords)
        ? s.chords.map((c) => ({
            chord: typeof c.chord === 'string' ? c.chord : 'C',
            beats: typeof c.beats === 'number' ? c.beats : 4,
          }))
        : []
    );
  }, []);

  // 获取当前模式下的歌谱对象；JSON 解析失败时提示并返回 null
  const getCurrentScore = (): Record<string, unknown> | null => {
    if (editorMode === 'json') {
      try {
        return JSON.parse(jsonText) as Record<string, unknown>;
      } catch {
        alert(t('composition.jsonParseError'));
        return null;
      }
    }
    return buildScore();
  };

  const switchMode = (mode: EditorMode) => {
    if (mode === editorMode) return;
    if (mode === 'json') {
      // 表单 → JSON：序列化当前表单
      setJsonText(JSON.stringify(buildScore(), null, 2));
      setEditorMode('json');
    } else {
      // JSON → 表单：解析成功才切换，失败停留 JSON 模式
      try {
        const parsed = JSON.parse(jsonText) as Record<string, unknown>;
        fillFormFromScore(parsed);
        setEditorMode('form');
      } catch {
        alert(t('composition.jsonParseError'));
      }
    }
  };

  // ── 旋律 / 和弦编辑 ──

  const updateNote = (idx: number, patch: Partial<MelodyNote>) => {
    setMelody((prev) => prev.map((n, i) => (i === idx ? { ...n, ...patch } : n)));
  };

  const removeNote = (idx: number) => {
    setMelody((prev) => (prev.length > 1 ? prev.filter((_, i) => i !== idx) : prev));
  };

  const addNote = () => {
    setMelody((prev) => [...prev, { pitch: 'C4', beats: 1, lyric: '' }]);
  };

  const updateChord = (idx: number, patch: Partial<ChordRow>) => {
    setChords((prev) => prev.map((c, i) => (i === idx ? { ...c, ...patch } : c)));
  };

  const removeChord = (idx: number) => {
    setChords((prev) => prev.filter((_, i) => i !== idx));
  };

  const addChord = () => {
    setChords((prev) => [...prev, { chord: 'C', beats: 4 }]);
  };

  // ── 操作处理 ──

  const handleImportMusicXml = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setImporting(true);
    try {
      const score = await api.musicImportMusicXML(file);
      fillFormFromScore(score);
      setEditorMode('form');
      setValidateErrors(null);
      setValidateOk(false);
    } catch (err) {
      alert(err instanceof Error ? err.message : String(err));
    } finally {
      setImporting(false);
      if (musicXmlFileRef.current) musicXmlFileRef.current.value = '';
    }
  };

  const handleValidate = async () => {
    const score = getCurrentScore();
    if (!score) return;
    setValidating(true);
    setValidateErrors(null);
    setValidateOk(false);
    try {
      const result = await api.musicValidateScore(score);
      if (result.valid) {
        setValidateOk(true);
        setValidateErrors([]);
      } else {
        setValidateErrors(result.errors);
      }
    } catch (err) {
      setValidateErrors([err instanceof Error ? err.message : String(err)]);
    } finally {
      setValidating(false);
    }
  };

  const handleSynthesize = async () => {
    const score = getCurrentScore();
    if (!score) return;
    setSubmitting(true);
    setCurrentTask(null);
    try {
      const result = await api.musicSynthesize({
        score,
        voice_bank: voiceBank.trim() || undefined,
        svc_model: svcModel || undefined,
        transpose,
        vocal_gain: vocalGain,
        accompaniment_gain: accompanimentGain,
      });
      setCurrentSongId(result.song_id);
    } catch (err) {
      alert(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  const handlePlaySong = (audioUrl: string) => {
    const full = getVoiceWorkstationAudioUrl(audioUrl);
    setPlayingUrl(full);
    // 等待 audio 元素 src 更新后播放
    setTimeout(() => audioRef.current?.play().catch(() => {}), 0);
  };

  const handleDeleteSong = async (songId: string) => {
    if (!window.confirm(t('composition.confirmDeleteSong'))) return;
    try {
      await api.musicDeleteSong(songId);
      if (currentSongId === songId) {
        setCurrentSongId(null);
        setCurrentTask(null);
      }
      refreshSongs();
    } catch (err) {
      alert(err instanceof Error ? err.message : String(err));
    }
  };

  const taskBadgeVariant = (status: string) =>
    status === 'completed' ? 'success' : status === 'failed' ? 'error' : status === 'running' ? 'warning' : 'default';

  const selectClassName =
    'w-full px-4 py-2.5 text-sm rounded-[var(--radius-md)] bg-[var(--color-bg-primary)] text-[var(--color-text-primary)] border border-[var(--color-border)] focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)] focus:border-transparent';

  return (
    <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
      {/* ── 左栏：歌谱编辑器 ── */}
      <div className="xl:col-span-2 space-y-6">
        <Card>
          <CardBody className="space-y-5">
            {/* 模式切换 + MusicXML 导入 */}
            <div className="flex items-center justify-between flex-wrap gap-3">
              <div className="flex gap-2">
                <button
                  onClick={() => switchMode('form')}
                  className={cn(
                    'px-4 py-2 rounded-lg text-sm font-medium transition-colors border',
                    editorMode === 'form'
                      ? 'bg-[var(--color-accent)] text-white border-[var(--color-accent)]'
                      : 'bg-[var(--color-bg-primary)] text-[var(--color-text-secondary)] border-[var(--color-border)] hover:border-[var(--color-accent)]'
                  )}
                >
                  {t('composition.formMode')}
                </button>
                <button
                  onClick={() => switchMode('json')}
                  className={cn(
                    'px-4 py-2 rounded-lg text-sm font-medium transition-colors border',
                    editorMode === 'json'
                      ? 'bg-[var(--color-accent)] text-white border-[var(--color-accent)]'
                      : 'bg-[var(--color-bg-primary)] text-[var(--color-text-secondary)] border-[var(--color-border)] hover:border-[var(--color-accent)]'
                  )}
                >
                  {t('composition.jsonMode')}
                </button>
              </div>
              <div className="flex items-center gap-3">
                <Button
                  variant="secondary"
                  onClick={() => musicXmlFileRef.current?.click()}
                  loading={importing}
                >
                  {t('composition.importMusicXml')}
                </Button>
                <input
                  ref={musicXmlFileRef}
                  type="file"
                  accept=".xml,.musicxml,.mxl"
                  className="hidden"
                  onChange={handleImportMusicXml}
                />
                <Button variant="secondary" onClick={handleValidate} loading={validating}>
                  {t('composition.validate')}
                </Button>
              </div>
            </div>

            {editorMode === 'form' ? (
              <>
                {/* 基本信息 */}
                <div className="grid grid-cols-2 gap-4">
                  <Input
                    label={t('composition.scoreTitle')}
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    placeholder={t('composition.scoreTitlePlaceholder')}
                  />
                  <Input
                    label={t('composition.bpm')}
                    type="number"
                    value={bpm}
                    onChange={(e) => setBpm(Number(e.target.value))}
                  />
                  <Input
                    label={t('composition.timeSignature')}
                    value={timeSignature}
                    onChange={(e) => setTimeSignature(e.target.value)}
                    placeholder="4/4"
                  />
                  <Input
                    label={t('composition.keySignature')}
                    value={keySignature}
                    onChange={(e) => setKeySignature(e.target.value)}
                    placeholder="C"
                  />
                  <Input
                    label={t('composition.accompanimentStyle')}
                    value={accompanimentStyle}
                    onChange={(e) => setAccompanimentStyle(e.target.value)}
                    placeholder="piano"
                  />
                </div>

                {/* 旋律轨 */}
                <div>
                  <div className="flex items-center justify-between mb-2">
                    <label className="block text-sm font-medium text-[var(--color-text-secondary)]">
                      {t('composition.melodyTrack')}
                    </label>
                    <Button variant="secondary" size="sm" onClick={addNote}>
                      {t('composition.addNote')}
                    </Button>
                  </div>
                  <div className="space-y-2">
                    {melody.map((note, idx) => (
                      <div key={idx} className="flex items-center gap-2">
                        <span className="w-8 text-xs text-[var(--color-text-tertiary)] text-right">
                          {idx + 1}
                        </span>
                        <Input
                          value={note.pitch}
                          onChange={(e) => updateNote(idx, { pitch: e.target.value })}
                          placeholder={t('composition.pitchPlaceholder')}
                        />
                        <Input
                          type="number"
                          step="0.25"
                          value={note.beats}
                          onChange={(e) => updateNote(idx, { beats: Number(e.target.value) })}
                          placeholder={t('composition.beats')}
                        />
                        <Input
                          value={note.lyric}
                          onChange={(e) => updateNote(idx, { lyric: e.target.value })}
                          placeholder={t('composition.lyricPlaceholder')}
                        />
                        <Button
                          variant="danger"
                          size="sm"
                          onClick={() => removeNote(idx)}
                          disabled={melody.length <= 1}
                        >
                          {t('composition.removeRow')}
                        </Button>
                      </div>
                    ))}
                  </div>
                  <div className="grid grid-cols-[2rem_1fr_1fr_1fr_auto] gap-2 mt-1 px-0 text-xs text-[var(--color-text-tertiary)]">
                    <span />
                    <span>{t('composition.pitch')}</span>
                    <span>{t('composition.beats')}</span>
                    <span>{t('composition.lyric')}</span>
                    <span />
                  </div>
                </div>

                {/* 和弦轨 */}
                <div>
                  <div className="flex items-center justify-between mb-2">
                    <label className="block text-sm font-medium text-[var(--color-text-secondary)]">
                      {t('composition.chordsTrack')}
                    </label>
                    <Button variant="secondary" size="sm" onClick={addChord}>
                      {t('composition.addChord')}
                    </Button>
                  </div>
                  {chords.length === 0 ? (
                    <p className="text-sm text-[var(--color-text-tertiary)]">
                      {t('composition.noChords')}
                    </p>
                  ) : (
                    <div className="space-y-2">
                      {chords.map((row, idx) => (
                        <div key={idx} className="flex items-center gap-2">
                          <span className="w-8 text-xs text-[var(--color-text-tertiary)] text-right">
                            {idx + 1}
                          </span>
                          <Input
                            value={row.chord}
                            onChange={(e) => updateChord(idx, { chord: e.target.value })}
                            placeholder={t('composition.chordPlaceholder')}
                          />
                          <Input
                            type="number"
                            step="0.5"
                            value={row.beats}
                            onChange={(e) => updateChord(idx, { beats: Number(e.target.value) })}
                            placeholder={t('composition.beats')}
                          />
                          <Button variant="danger" size="sm" onClick={() => removeChord(idx)}>
                            {t('composition.removeRow')}
                          </Button>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </>
            ) : (
              <Textarea
                label={t('composition.jsonEditor')}
                value={jsonText}
                onChange={(e) => setJsonText(e.target.value)}
                rows={22}
              />
            )}

            {/* 校验结果 */}
            {validateOk && (
              <Badge variant="success">{t('composition.validateSuccess')}</Badge>
            )}
            {validateErrors && validateErrors.length > 0 && (
              <div className="p-3 rounded-lg bg-[var(--color-bg-tertiary)] space-y-1">
                <span className="text-sm font-medium text-[var(--color-text-secondary)]">
                  {t('composition.validateFailed')}
                </span>
                <ul className="list-disc pl-5 space-y-0.5">
                  {validateErrors.map((err, idx) => (
                    <li key={idx} className="text-sm font-mono text-red-500">
                      {err}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </CardBody>
        </Card>
      </div>

      {/* ── 右栏：合成面板 + 任务进度 + 歌曲历史 ── */}
      <div className="space-y-6">
        <Card>
          <CardBody className="space-y-5">
            <h3 className="text-sm font-medium text-[var(--color-text-primary)]">
              {t('composition.synthPanel')}
            </h3>

            <Input
              label={t('composition.voiceBank')}
              value={voiceBank}
              onChange={(e) => setVoiceBank(e.target.value)}
              placeholder={t('composition.voiceBankPlaceholder')}
            />

            <div>
              <label className="block text-sm font-medium text-[var(--color-text-secondary)] mb-1.5">
                {t('composition.svcModel')}
              </label>
              <select
                value={svcModel}
                onChange={(e) => setSvcModel(e.target.value)}
                className={selectClassName}
              >
                <option value="">{t('composition.noVoiceConversion')}</option>
                {svcModels.map((model) => (
                  <option key={model.path} value={model.path}>
                    {model.name}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-sm font-medium text-[var(--color-text-secondary)] mb-1.5">
                {t('composition.transpose')}: {transpose}
              </label>
              <input
                type="range"
                min="-12"
                max="12"
                value={transpose}
                onChange={(e) => setTranspose(Number(e.target.value))}
                className="w-full"
              />
              <div className="flex justify-between text-xs text-[var(--color-text-tertiary)]">
                <span>-12</span>
                <span>0</span>
                <span>+12</span>
              </div>
            </div>

            <Slider
              label={t('composition.vocalGain')}
              value={vocalGain}
              min={0}
              max={2}
              step={0.05}
              onChange={setVocalGain}
            />
            <Slider
              label={t('composition.accompanimentGain')}
              value={accompanimentGain}
              min={0}
              max={2}
              step={0.05}
              onChange={setAccompanimentGain}
            />

            <Button onClick={handleSynthesize} loading={submitting} disabled={submitting}>
              {t('composition.synthesize')}
            </Button>
          </CardBody>
        </Card>

        {/* 任务进度 */}
        {currentTask && (
          <Card>
            <CardBody className="space-y-3">
              <div className="flex items-center gap-2">
                <h3 className="text-sm font-medium text-[var(--color-text-primary)]">
                  {t('composition.taskProgress')}
                </h3>
                <Badge variant={taskBadgeVariant(currentTask.status)}>{currentTask.status}</Badge>
              </div>
              <p className="text-sm text-[var(--color-text-secondary)]">
                {currentTask.title} · {currentTask.stage}
              </p>
              <div>
                <div className="w-full bg-[var(--color-bg-tertiary)] rounded-full h-2">
                  <div
                    className="bg-[var(--color-accent)] h-2 rounded-full transition-all"
                    style={{ width: `${Math.round(currentTask.progress * 100)}%` }}
                  />
                </div>
                <span className="text-xs text-[var(--color-text-tertiary)]">
                  {Math.round(currentTask.progress * 100)}%
                </span>
              </div>
              {currentTask.steps && currentTask.steps.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {currentTask.steps.map((step) => (
                    <Badge key={step.name} variant={taskBadgeVariant(step.status)}>
                      {step.name}: {step.status}
                    </Badge>
                  ))}
                </div>
              )}
              {currentTask.error && (
                <p className="text-sm text-red-500">{currentTask.error}</p>
              )}
              {currentTask.status === 'completed' && currentTask.audio_url && (
                <audio
                  controls
                  className="w-full"
                  src={getVoiceWorkstationAudioUrl(currentTask.audio_url)}
                />
              )}
            </CardBody>
          </Card>
        )}

        {/* 歌曲历史 */}
        <Card>
          <CardBody className="space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-medium text-[var(--color-text-primary)]">
                {t('composition.history')}
              </h3>
              <Button variant="secondary" size="sm" onClick={refreshSongs}>
                {t('composition.refresh')}
              </Button>
            </div>
            {songs.length === 0 ? (
              <p className="text-sm text-[var(--color-text-tertiary)]">{t('composition.noSongs')}</p>
            ) : (
              <div className="space-y-2">
                {songs.map((song) => (
                  <div
                    key={song.song_id}
                    className="px-3 py-2 rounded-lg bg-[var(--color-bg-tertiary)] space-y-1.5"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-sm text-[var(--color-text-primary)] truncate">
                        {song.title}
                      </span>
                      <Badge variant={taskBadgeVariant(song.status)}>{song.status}</Badge>
                    </div>
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-xs text-[var(--color-text-tertiary)]">
                        {song.created_at}
                      </span>
                      <div className="flex items-center gap-2">
                        {song.audio_url && (
                          <Button
                            variant="secondary"
                            size="sm"
                            onClick={() => handlePlaySong(song.audio_url as string)}
                          >
                            {t('composition.play')}
                          </Button>
                        )}
                        <Button
                          variant="danger"
                          size="sm"
                          onClick={() => handleDeleteSong(song.song_id)}
                        >
                          {t('composition.deleteSong')}
                        </Button>
                      </div>
                    </div>
                    {song.error && <p className="text-xs text-red-500">{song.error}</p>}
                  </div>
                ))}
              </div>
            )}
            {playingUrl && (
              <audio ref={audioRef} controls className="w-full" src={playingUrl} />
            )}
          </CardBody>
        </Card>
      </div>
    </div>
  );
}
