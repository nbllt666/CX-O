/**
 * useVexflow.ts — VexFlow 薄封装受控渲染 hook + 谱表工具函数
 *
 * 模块6_五线谱渲染层基础件（spec: redesign-composition-staff-editor，merged.md §6 冻结）。
 * - useVexflowRenderer：受控纯渲染 hook，props 变化（deps）全量重建 VexFlow SVG。
 * - pitchToVexKeys / beatsToDuration / drumKeyToVexKey：契约字段 → VexFlow 原语映射。
 *
 * 设计原则（AGENTS.md §3.2）：
 * - StaffScore 为受控纯渲染器，不持有歌谱状态；本 hook 不缓存歌谱，仅按 deps 重渲。
 * - 命中测试钩子：通过 VexFlow Element.setAttribute 给每个 StaveNote 打 data-track/data-noteid，
 *   上层（模块7）用 React 事件 + closest('[data-noteid]') 反解；本模块提供 setNoteHitAttrs 辅助。
 */
import { useEffect, useRef } from 'react';
import {
  Renderer,
  RenderContext,
  StaveNote,
  Accidental,
  Annotation,
  Clef,
} from 'vexflow';

// ---------------------------------------------------------------------------
// 受控渲染 hook
// ---------------------------------------------------------------------------

/**
 * 受控 VexFlow SVG 渲染 hook。
 *
 * @param draw 在 RenderContext 上绘制谱表的回调（每次 deps 变化时调用）
 * @param deps 触发重渲的依赖列表（受控：score/selection 等变化即重渲）
 * @param config 画布宽高
 * @returns containerRef 绑定到承载 SVG 的 div
 */
export function useVexflowRenderer(
  draw: (ctx: RenderContext) => void,
  deps: React.DependencyList,
  config: { width: number; height: number },
): React.RefObject<HTMLDivElement> {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    // 全量重建：清空旧 SVG，再渲染新快照（merged.md §6：首版简单可靠，全量重渲）
    el.innerHTML = '';
    try {
      const renderer = new Renderer(el, Renderer.Backends.SVG);
      renderer.resize(config.width, config.height);
      const ctx = renderer.getContext();
      draw(ctx);
    } catch (err) {
      // 受控渲染器不应因单次渲染异常崩溃宿主 UI；记录后留空容器
       
      console.error('[StaffScore] VexFlow render error:', err);
    }
    // deps 由调用方显式提供（受控重渲语义）；config.width/height 故意不并入 deps，
    // 调用方需把 width/height 作为deps 项传入以触发尺寸变化重渲。
     
  }, deps);

  return containerRef;
}

// ---------------------------------------------------------------------------
// 契约字段 → VexFlow 原语映射
// ---------------------------------------------------------------------------

/** 科学音高 → VexFlow key（如 C4 → 'c/4'，A#3 → 'a#/3'，Bb5 → 'bb/5'） */
export function pitchToVexKey(pitch: string): { keys: string[]; accidental: string | null } {
  const m = /^([A-Ga-g])(#|b)?(-?\d+)$/.exec(pitch);
  if (!m) {
    throw new Error(`无效音高记谱: ${JSON.stringify(pitch)}（期望形如 C4、A#3、Bb5）`);
  }
  const [, letter, acc, oct] = m;
  const key = `${letter.toLowerCase()}${acc ?? ''}/${oct}`;
  return { keys: [key], accidental: acc ?? null };
}

/**
 * 节拍数 → VexFlow duration 字符串。
 * 支持常见时值（含附点）；非标准时值取最接近的标准时值（首版简化，模块7 可按 tie 精确化）。
 */
export function beatsToDuration(beats: number): string {
  if (!(beats > 0) || !Number.isFinite(beats)) return 'q';
  const TABLE: Array<[number, string]> = [
    [8, 'w'],
    [6, 'wd'],
    [4, 'w'],
    [3, 'hd'],
    [2, 'h'],
    [1.5, 'qd'],
    [1, 'q'],
    [0.75, '8d'],
    [0.5, '8'],
    [0.375, '16d'],
    [0.25, '16'],
    [0.125, '32'],
  ];
  let best = 'q';
  let bestDiff = Infinity;
  for (const [b, d] of TABLE) {
    const diff = Math.abs(b - beats);
    if (diff < bestDiff) {
      bestDiff = diff;
      best = d;
    }
  }
  return best;
}

/**
 * GM 鼓键名 → 打击乐谱表上的音高位置（percussion clef）。
 * 位置仅用于在五线谱上区分鼓件，不表达真实音高；映射参照 GM 标准打击乐谱位置。
 */
const DRUM_KEY_POSITION: Record<string, string> = {
  kick: 'c/5',
  snare: 'e/4',
  closed_hihat: 'g/5',
  open_hihat: 'a/5',
  crash: 'a/6',
  ride: 'f/6',
  tom_high: 'f/5',
  tom_mid: 'd/5',
  tom_low: 'b/4',
  clap: 'a/4',
};

/** 鼓键名 → VexFlow key（未命中回退到中线 'e/4'，保证渲染不中断） */
export function drumKeyToVexKey(drumKey: string): { keys: string[]; accidental: null } {
  const pos = DRUM_KEY_POSITION[drumKey] ?? 'e/4';
  return { keys: [pos], accidental: null };
}

// ---------------------------------------------------------------------------
// 谱表构建辅助
// ---------------------------------------------------------------------------

/** 构造一个 StaveNote（含临时记号与命中 data 属性） */
export interface BuildNoteOptions {
  pitch: string;
  beats: number;
  /** 谱号（影响 ledger line 计算），默认 'treble' */
  clef?: string;
  /** 命中测试：轨标识（'melody' 或伴奏轨 id） */
  track: string;
  /** 命中测试：轨内序号（melody=音符序号，伴奏=events 序号） */
  noteId: number;
  /** 是否打击乐轨（用鼓键名解析） */
  percussion?: boolean;
  /** 选中态高亮（红色 notehead） */
  selected?: boolean;
  /** 上方文本标注（和弦标记） */
  chordSymbol?: string;
  /** 下方文本标注（逐字歌词） */
  lyric?: string;
}

export interface BuiltNote {
  note: StaveNote;
  index: number;
}

/** 构造 StaveNote 并挂载临时记号/和弦标记/歌词/选中态/命中属性 */
export function buildStaveNote(opts: BuildNoteOptions): StaveNote {
  const { percussion = false } = opts;
  const { keys, accidental } = percussion
    ? drumKeyToVexKey(opts.pitch)
    : pitchToVexKey(opts.pitch);
  const duration = beatsToDuration(opts.beats);

  const note = new StaveNote({
    keys,
    duration,
    autoStem: true,
    clef: opts.clef ?? 'treble',
  });

  // 临时记号
  if (accidental) {
    note.addModifier(new Accidental(accidental), 0);
  }

  // 上方和弦标记（对齐到该拍位）
  if (opts.chordSymbol) {
    const ann = new Annotation(opts.chordSymbol);
    ann.setVerticalJustification(Annotation.VerticalJustify.TOP);
    ann.setFont('sans', 10, 'bold');
    note.addModifier(ann, 0);
  }

  // 下方逐字歌词
  if (opts.lyric) {
    const ann = new Annotation(opts.lyric);
    ann.setVerticalJustification(Annotation.VerticalJustify.BOTTOM);
    ann.setFont('sans', 10, 'normal');
    note.addModifier(ann, 0);
  }

  // 选中态高亮
  if (opts.selected) {
    note.setStyle({ fillStyle: '#dc2626', strokeStyle: '#dc2626' });
  }

  // 命中测试 data 属性（模块7 通过 closest('[data-noteid]') 反解）
  setNoteHitAttrs(note, opts.track, opts.noteId);

  return note;
}

/** 给 StaveNote 打命中测试 data 属性 */
export function setNoteHitAttrs(note: StaveNote, track: string, noteId: number): void {
  note.setAttribute('data-track', track);
  note.setAttribute('data-noteid', String(noteId));
}

// ---------------------------------------------------------------------------
// 谱号选择
// ---------------------------------------------------------------------------

/**
 * 按 program 选择伴奏谱号。
 * - program === -1（打击乐）→ 'percussion'
 * - 旋律类：贝斯/低音域（program 32–47）→ 'bass'；其余 → 'treble'
 * 返回 Clef.types 支持的谱号名。
 */
export function clefForTrack(program: number): string {
  if (program === -1) return 'percussion';
  // bass(32–39) / strings 低音域(40–43) 用 bass clef，其余 treble
  if (program >= 32 && program <= 43) return 'bass';
  return 'treble';
}

/** 拍号字符串 '4/4' → { numBeats: 4, beatValue: 4 } */
export function parseTimeSignature(timeSig: string): { numBeats: number; beatValue: number } {
  const m = /^(\d+)\/(\d+)$/.exec(timeSig);
  if (!m) return { numBeats: 4, beatValue: 4 };
  return { numBeats: Number(m[1]), beatValue: Number(m[2]) };
}

// ---------------------------------------------------------------------------
// 命中测试：从 React 事件反解 (track, noteId)
// ---------------------------------------------------------------------------

/**
 * 从点击事件反解命中的音符 (track, noteId)。
 * 基础命中：沿 DOM 向上找带 data-noteid 的元素（VexFlow 渲染的 SVG <g>）。
 * 模块7 可在此基础上叠加坐标→拍位反解（点击空白 add_note）。
 */
export function resolveHitFromEvent(
  event: React.MouseEvent<HTMLElement> | MouseEvent,
): { track: string; noteId: number } | null {
  let node: Element | null = event.target as Element | null;
  while (node && node !== (event.currentTarget as Element | null)) {
    const noteId = node.getAttribute?.('data-noteid');
    const track = node.getAttribute?.('data-track');
    if (noteId != null && track != null) {
      const id = Number(noteId);
      if (Number.isInteger(id)) return { track, noteId: id };
    }
    node = node.parentElement;
  }
  return null;
}

// 重导出常用 VexFlow 类型/类，供组件层使用
export { Renderer, StaveNote, Accidental, Annotation, Clef };
