/**
 * MelodyStaff.tsx — 主旋律谱表（受控纯渲染）
 *
 * 模块6_五线谱渲染层（spec: redesign-composition-staff-editor，merged.md §6 冻结）。
 * - treble clef + 拍号 + 调号；旋律音符按 beats 顺序累加，按拍号分小节水平排列。
 * - 上排：和弦标记（对齐到覆盖该音符起始拍位的和弦）。
 * - 下排：逐字歌词（每个音符的 lyric 字段）。
 * - 选中态：selectedNote 命中的音符红色高亮。
 * - 命中钩子：点击音符触发 onSelectNote('melody', noteId)；坐标→拍位反解由模块7 完善。
 *
 * 受控：不持有歌谱状态，score 变化即重渲（useVexflowRenderer deps=[score, selectedNote]）。
 */
import { Stave, Formatter, Voice } from 'vexflow';
import type { ScoreV2 } from './types';
import {
  useVexflowRenderer,
  buildStaveNote,
  parseTimeSignature,
  resolveHitFromEvent,
} from './useVexflow';

export interface NoteSelection {
  track: string;
  noteId: number;
}

export interface MelodyStaffProps {
  score: ScoreV2;
  selectedNote?: NoteSelection | null;
  onSelectNote?: (track: string, noteId: number) => void;
  width?: number;
}

const MELODY_TRACK = 'melody';
const STAVE_Y = 56; // 留出上排和弦标记空间
const STAVE_HEIGHT = 110;
const MEASURE_MIN_WIDTH = 200;

interface Measure {
  notes: Array<{ note: ScoreV2['melody'][number]; index: number }>;
}

/** 按拍号把旋律音符分到小节（单音符跨小节不拆分，归入起始小节；首版简化） */
function splitMelodyIntoMeasures(
  melody: ScoreV2['melody'],
  numBeats: number,
): Measure[] {
  const measures: Measure[] = [{ notes: [] }];
  let curBeats = 0;
  melody.forEach((note, index) => {
    if (curBeats + note.beats > numBeats && measures[measures.length - 1].notes.length > 0) {
      measures.push({ notes: [] });
      curBeats = 0;
    }
    measures[measures.length - 1].notes.push({ note, index });
    curBeats += note.beats;
  });
  return measures;
}

/** 计算每个旋律音符的起始拍位（顺序累加） */
function melodyStartPositions(melody: ScoreV2['melody']): number[] {
  const positions: number[] = [];
  let acc = 0;
  for (const n of melody) {
    positions.push(acc);
    acc += n.beats;
  }
  return positions;
}

/** 计算每个和弦的 [start, end) 区间 */
function chordRanges(score: ScoreV2): Array<{ chord: string; start: number; end: number }> {
  let acc = 0;
  return score.chords.map((c) => {
    const start = acc;
    const end = acc + c.beats;
    acc = end;
    return { chord: c.chord, start, end };
  });
}

/** 找覆盖给定拍位的和弦标记（无则 undefined） */
function chordCoveringAt(
  ranges: ReturnType<typeof chordRanges>,
  pos: number,
): string | undefined {
  const hit = ranges.find((r) => pos >= r.start && pos < r.end);
  return hit?.chord;
}

export function MelodyStaff({ score, selectedNote, onSelectNote, width = 800 }: MelodyStaffProps) {
  const { numBeats } = parseTimeSignature(score.time_signature || '4/4');
  const measures = splitMelodyIntoMeasures(score.melody, numBeats);
  const measureWidth = Math.max(MEASURE_MIN_WIDTH, Math.floor(width / Math.max(measures.length, 1)));
  const totalWidth = measures.length * measureWidth + 20;
  const containerHeight = STAVE_Y + STAVE_HEIGHT + 36; // 下方歌词空间

  const containerRef = useVexflowRenderer(
    (ctx) => {
      const ranges = chordRanges(score);
      const startPositions = melodyStartPositions(score.melody);

      measures.forEach((measure, mIdx) => {
        const x = 10 + mIdx * measureWidth;
        const stave = new Stave(x, STAVE_Y, measureWidth);
        stave.addClef('treble');
        if (mIdx === 0) {
          stave.addTimeSignature(score.time_signature || '4/4');
          if (score.key) stave.setKeySignature(score.key);
        }
        stave.setContext(ctx).draw();

        const notes = measure.notes.map(({ note, index }) => {
          const chordSymbol = chordCoveringAt(ranges, startPositions[index]);
          const isSelected =
            selectedNote != null &&
            selectedNote.track === MELODY_TRACK &&
            selectedNote.noteId === index;
          return buildStaveNote({
            pitch: note.pitch,
            beats: note.beats,
            track: MELODY_TRACK,
            noteId: index,
            clef: 'treble',
            chordSymbol,
            lyric: note.lyric || undefined,
            selected: isSelected,
          });
        });

        if (notes.length > 0) {
          const voice = new Voice({ numBeats, beatValue: 4 }).setMode(Voice.Mode.SOFT);
          voice.addTickables(notes);
          new Formatter().joinVoices([voice]).format([voice], measureWidth - 40);
          voice.draw(ctx, stave);
        }
      });
    },
    [score, selectedNote, numBeats, measureWidth, totalWidth],
    { width: totalWidth, height: containerHeight },
  );

  const handleClick = (e: React.MouseEvent<HTMLElement>) => {
    const hit = resolveHitFromEvent(e);
    if (hit && hit.track === MELODY_TRACK) {
      onSelectNote?.(hit.track, hit.noteId);
    }
  };

  return (
    <div className="melody-staff">
      <div className="px-2 py-1 text-xs font-medium text-[var(--color-text-secondary)]">
        主旋律{score.title ? ` · ${score.title}` : ''}
      </div>
      <div
        ref={containerRef}
        onClick={onSelectNote ? handleClick : undefined}
        className="overflow-x-auto"
        data-testid="melody-staff-svg"
        role="img"
        aria-label="主旋律谱表"
      />
    </div>
  );
}