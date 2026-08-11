/**
 * AccompanimentStaff.tsx — 伴奏轨谱表（受控纯渲染）
 *
 * 模块6_五线谱渲染层（spec: redesign-composition-staff-editor，merged.md §6 冻结）。
 * - 旋律类（program 0–127）：treble clef（贝斯/低音域 32–43 用 bass clef）。
 * - 打击乐轨（program === -1）：percussion clef，pitch 为 GM 鼓键名（kick/snare…）。
 * - events 按 offset 升序、按拍号分小节水平排列；auto 轨 events 为空时渲染空谱表。
 * - 左侧标签：track.name + GM 音色名（如「钢琴 - 大钢琴 Acoustic Grand Piano」）。
 * - 选中态：selectedNote 命中的音符红色高亮。
 * - 命中钩子：点击音符触发 onSelectNote(track.id, noteId)。
 *
 * 受控：不持有歌谱状态，score/track 变化即重渲。
 */
import { Stave, Formatter, Voice } from 'vexflow';
import type { AccompanimentTrack, ScoreV2 } from './types';
import { INVENTORY } from './__mocks__/inventory';
import {
  useVexflowRenderer,
  buildStaveNote,
  clefForTrack,
  parseTimeSignature,
  resolveHitFromEvent,
} from './useVexflow';
import type { NoteSelection } from './MelodyStaff';

export interface AccompanimentStaffProps {
  track: AccompanimentTrack;
  score: ScoreV2;
  selectedNote?: NoteSelection | null;
  onSelectNote?: (track: string, noteId: number) => void;
  width?: number;
}

const STAVE_Y = 40;
const STAVE_HEIGHT = 100;
const MEASURE_MIN_WIDTH = 200;

/** GM program → 音色显示名（前后端同源，INVENTORY 为生成副本） */
export function getInstrumentName(program: number): string {
  if (program === -1) return '打击乐';
  for (const group of INVENTORY.instrument_groups) {
    for (const inst of group.instruments) {
      if (inst.program === program) return inst.name;
    }
  }
  return `GM ${program}`;
}

interface MeasureEvent {
  event: AccompanimentTrack['events'][number];
  /** events 原数组序号（命令协议 note_id 语义：轨内序号寻址） */
  index: number;
}

interface Measure {
  events: MeasureEvent[];
}

/** 按 offset 把 events 分到小节（offset // numBeats = 小节号） */
function splitEventsIntoMeasures(
  events: AccompanimentTrack['events'],
  numBeats: number,
): Measure[] {
  const indexed: MeasureEvent[] = events.map((event, index) => ({ event, index }));
  const sorted = [...indexed].sort((a, b) => a.event.offset - b.event.offset);
  if (sorted.length === 0) return [{ events: [] }];
  const lastMeasure = Math.floor(sorted[sorted.length - 1].event.offset / numBeats);
  const measures: Measure[] = Array.from({ length: lastMeasure + 1 }, () => ({ events: [] }));
  for (const ev of sorted) {
    const m = Math.floor(ev.event.offset / numBeats);
    measures[m].events.push(ev);
  }
  return measures;
}

export function AccompanimentStaff({
  track,
  score,
  selectedNote,
  onSelectNote,
  width = 800,
}: AccompanimentStaffProps) {
  const { numBeats } = parseTimeSignature(score.time_signature || '4/4');
  const measures = splitEventsIntoMeasures(track.events, numBeats);
  const measureWidth = Math.max(MEASURE_MIN_WIDTH, Math.floor(width / Math.max(measures.length, 1)));
  const totalWidth = measures.length * measureWidth + 20;
  const containerHeight = STAVE_Y + STAVE_HEIGHT + 20;
  const clef = clefForTrack(track.program);
  const isPercussion = track.program === -1;
  const instrumentName = getInstrumentName(track.program);
  const label = `${track.name} - ${instrumentName}`;

  const containerRef = useVexflowRenderer(
    (ctx) => {
      measures.forEach((measure, mIdx) => {
        const x = 10 + mIdx * measureWidth;
        const stave = new Stave(x, STAVE_Y, measureWidth);
        stave.addClef(clef);
        if (mIdx === 0) {
          stave.addTimeSignature(score.time_signature || '4/4');
          if (score.key && !isPercussion) stave.setKeySignature(score.key);
        }
        stave.setContext(ctx).draw();

        if (measure.events.length === 0) return;

        const notes = measure.events.map(({ event, index }) => {
          const isSelected =
            selectedNote != null &&
            selectedNote.track === track.id &&
            selectedNote.noteId === index;
          return buildStaveNote({
            pitch: event.pitch,
            beats: event.beats,
            track: track.id,
            noteId: index,
            clef,
            percussion: isPercussion,
            selected: isSelected,
          });
        });

        const voice = new Voice({ numBeats, beatValue: 4 }).setMode(Voice.Mode.SOFT);
        voice.addTickables(notes);
        new Formatter().joinVoices([voice]).format([voice], measureWidth - 40);
        voice.draw(ctx, stave);
      });
    },
    [track, score, selectedNote, numBeats, measureWidth, totalWidth, clef, isPercussion],
    { width: totalWidth, height: containerHeight },
  );

  const handleClick = (e: React.MouseEvent<HTMLElement>) => {
    const hit = resolveHitFromEvent(e);
    if (hit && hit.track === track.id) {
      onSelectNote?.(hit.track, hit.noteId);
    }
  };

  return (
    <div className="accompaniment-staff">
      <div className="px-2 py-1 text-xs font-medium text-[var(--color-text-secondary)]">
        <span className="mr-2">{label}</span>
        <span className="text-[var(--color-text-tertiary)]">
          {track.mode === 'auto' ? `auto · ${track.style || '(默认节奏型)'}` : 'manual'}
        </span>
      </div>
      <div
        ref={containerRef}
        onClick={onSelectNote ? handleClick : undefined}
        className="overflow-x-auto"
        data-testid={`accompaniment-staff-${track.id}`}
        role="img"
        aria-label={`${label} 谱表`}
      />
    </div>
  );
}