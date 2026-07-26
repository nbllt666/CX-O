/**
 * StaffScore.tsx — 顶层总谱组件（受控纯渲染器）
 *
 * 模块6_五线谱渲染层入口（spec: redesign-composition-staff-editor，merged.md §6 冻结）。
 *
 * 受控语义（AGENTS.md §3.2）：
 * - props 驱动，不持有歌谱状态；score 变化 → 子谱表全量重建 VexFlow（useVexflowRenderer）。
 * - 所有编辑动作经 onSelectNote 回调上抛，由模块7 命令分发层转命令；本组件绝不直接改 score。
 *
 * 总谱纵向堆叠（merged.md §6）：
 * - 主旋律谱表置顶（MelodyStaff：歌词下排 + 和弦标记上排）。
 * - 各伴奏轨谱表依次向下堆叠（AccompanimentStaff：旋律类 treble/bass，打击乐 percussion clef）。
 */
import type { ScoreV2 } from './types';
import { MelodyStaff } from './MelodyStaff';
import { AccompanimentStaff } from './AccompanimentStaff';

export type { NoteSelection } from './MelodyStaff';

export interface StaffScoreProps {
  /** 服务端快照（v2 歌谱，经 validate_score 规范化：default 字段必然存在） */
  score: ScoreV2;
  /** 当前选中音符（track='melody' 或伴奏轨 id；noteId=轨内序号）；null=无选中 */
  selectedNote?: { track: string; noteId: number } | null;
  /** 命中回调：点击音符触发（坐标→拍位反解 add_note 由模块7 完善） */
  onSelectNote?: (track: string, noteId: number) => void;
  /** 渲染宽度（默认 800） */
  width?: number;
}

export function StaffScore({ score, selectedNote = null, onSelectNote, width = 800 }: StaffScoreProps) {
  return (
    <div className="staff-score space-y-3" data-testid="staff-score" role="group" aria-label="总谱">
      <MelodyStaff
        score={score}
        selectedNote={selectedNote}
        onSelectNote={onSelectNote}
        width={width}
      />
      {score.accompaniment_tracks.map((track) => (
        <AccompanimentStaff
          key={track.id}
          track={track}
          score={score}
          selectedNote={selectedNote}
          onSelectNote={onSelectNote}
          width={width}
        />
      ))}
    </div>
  );
}

export default StaffScore;
