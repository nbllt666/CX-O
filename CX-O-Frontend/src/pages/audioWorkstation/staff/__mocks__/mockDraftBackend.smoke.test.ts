/**
 * mockDraftBackend.smoke.test.ts — s0202 预生成 Mock 冒烟测试
 *
 * 验证 MockDraftBackend 的 20 条命令在典型路径上的行为符合契约预期，
 * 覆盖：create_draft / get_draft / add_note / update_note / move_note /
 * delete_note / set_lyric / add_chord / update_chord / delete_chord /
 * add_track / remove_track / set_track_instrument / set_track_mode /
 * arrange_track / set_track_mix / undo / redo / validate_draft / submit_draft。
 */
import { describe, expect, it } from 'vitest';
import { createMockDraftBackend, MockDraftBackend, validateScore } from './mockDraftBackend';
import { getFixture } from './fixtures';
import { INVENTORY, resolveDrumKey } from './inventory';

// ---------------------------------------------------------------------------
// 基础工具
// ---------------------------------------------------------------------------

function assertSuccess(result: ReturnType<MockDraftBackend['execute']>) {
  expect(result.success).toBe(true);
  expect(result.error).toBeUndefined();
  expect(result.draft_id).toBeDefined();
  expect(result.version).toBeDefined();
  expect(result.snapshot).toBeDefined();
}

function assertFailure(result: ReturnType<MockDraftBackend['execute']>, code: string) {
  expect(result.success).toBe(false);
  expect(result.error).toBeDefined();
  expect(result.error?.code).toBe(code);
}

// ---------------------------------------------------------------------------
// 测试套件
// ---------------------------------------------------------------------------

describe('s0202 预生成 Mock：mockDraftBackend 冒烟', () => {
  // ------------------------------------------------------------------
  // fixtures / inventory / validateScore 基础
  // ------------------------------------------------------------------

  it('fixtures 加载：5 组夹具可获取且深拷贝隔离', () => {
    const names = ['minimal_v2', 'melody_only_v2', 'full_multitrack_v2', 'v1_piano', 'v1_guitar'];
    for (const name of names) {
      const fixture = getFixture(name);
      expect(fixture).toBeDefined();
      expect(typeof fixture.title).toBe('string');
    }
    // 深拷贝隔离：修改返回值不影响源
    const a = getFixture('minimal_v2');
    (a as Record<string, unknown>).title = '篡改';
    const b = getFixture('minimal_v2');
    expect(b.title).toBe('最小样本');
  });

  it('inventory 形状：16 组 128 音色 + 4 节奏型 + 10 鼓键', () => {
    expect(INVENTORY.instrument_groups.length).toBe(16);
    const totalPrograms = INVENTORY.instrument_groups.reduce((sum, g) => sum + g.instruments.length, 0);
    expect(totalPrograms).toBe(128);
    expect(INVENTORY.styles.length).toBe(4);
    expect(INVENTORY.drum_keys.length).toBe(10);
    expect(resolveDrumKey('kick')).toBe(36);
    expect(resolveDrumKey('snare')).toBe(38);
  });

  it('validateScore：v2 夹具通过，v1 夹具迁移后通过', () => {
    // v2 夹具
    for (const name of ['minimal_v2', 'melody_only_v2', 'full_multitrack_v2']) {
      const outcome = validateScore(getFixture(name));
      expect(outcome.ok).toBe(true);
      expect(outcome.errors).toEqual([]);
      expect(outcome.normalized).toBeDefined();
    }
    // v1 夹具（含 accompaniment_style，迁移后校验）
    for (const name of ['v1_piano', 'v1_guitar']) {
      const outcome = validateScore(getFixture(name));
      expect(outcome.ok).toBe(true);
      expect(outcome.normalized?.accompaniment_tracks.length).toBe(1);
      expect(outcome.normalized?.accompaniment_tracks[0].mode).toBe('auto');
    }
  });

  it('validateScore：非法输入返回结构化错误', () => {
    const bad = validateScore({ title: '', bpm: -1, melody: [] });
    expect(bad.ok).toBe(false);
    expect(bad.errors.length).toBeGreaterThan(0);
    expect(bad.normalized).toBeUndefined();
  });

  // ------------------------------------------------------------------
  // 20 命令冒烟
  // ------------------------------------------------------------------

  describe('20 命令冒烟', () => {
    let backend: MockDraftBackend;
    let draftId: string;

    it('01 create_draft：空白草稿（含 C4 占位）', () => {
      backend = createMockDraftBackend();
      const result = backend.execute({ command: 'create_draft', args: {} });
      assertSuccess(result);
      expect(result.snapshot?.title).toBe('未命名');
      expect(result.snapshot?.bpm).toBe(120);
      expect(result.snapshot?.melody.length).toBe(1);
      expect(result.snapshot?.melody[0].pitch).toBe('C4');
      draftId = result.draft_id!;
    });

    it('02 get_draft：获取当前快照', () => {
      const result = backend.execute({ command: 'get_draft', args: { draft_id: draftId } });
      assertSuccess(result);
      expect(result.snapshot?.title).toBe('未命名');
    });

    it('03 add_note：melody 轨追加（首个替换占位符）', () => {
      const result = backend.execute({
        command: 'add_note',
        args: { draft_id: draftId, track: 'melody', pitch: 'D4', beats: 2, lyric: '你' },
      });
      assertSuccess(result);
      expect(result.snapshot?.melody.length).toBe(1); // 占位符被替换
      expect(result.snapshot?.melody[0].pitch).toBe('D4');
      expect(result.snapshot?.melody[0].lyric).toBe('你');
    });

    it('04 update_note：修改 melody 音符', () => {
      const result = backend.execute({
        command: 'update_note',
        args: { draft_id: draftId, track: 'melody', note_id: 0, patch: { pitch: 'E4', lyric: '好' } },
      });
      assertSuccess(result);
      expect(result.snapshot?.melody[0].pitch).toBe('E4');
      expect(result.snapshot?.melody[0].lyric).toBe('好');
    });

    it('05 move_note：melody 轨重排（越界钳制）', () => {
      // 先补一个音符
      backend.execute({
        command: 'add_note',
        args: { draft_id: draftId, track: 'melody', pitch: 'F4', beats: 1, lyric: '呀' },
      });
      const result = backend.execute({
        command: 'move_note',
        args: { draft_id: draftId, track: 'melody', note_id: 0, new_offset: 1 },
      });
      assertSuccess(result);
      expect(result.snapshot?.melody.length).toBe(2);
      expect(result.snapshot?.melody[1].pitch).toBe('E4'); // 原 0 号移到 1 号
    });

    it('06 delete_note：删除 melody 音符（越界幂等）', () => {
      const result = backend.execute({
        command: 'delete_note',
        args: { draft_id: draftId, track: 'melody', note_id: 0 },
      });
      assertSuccess(result);
      expect(result.snapshot?.melody.length).toBe(1);
      // 越界删除：幂等成功
      const again = backend.execute({
        command: 'delete_note',
        args: { draft_id: draftId, track: 'melody', note_id: 99 },
      });
      assertSuccess(again);
    });

    it('07 set_lyric：行内歌词编辑', () => {
      const result = backend.execute({
        command: 'set_lyric',
        args: { draft_id: draftId, note_id: 0, lyric: '听' },
      });
      assertSuccess(result);
      expect(result.snapshot?.melody[0].lyric).toBe('听');
    });

    it('08 add_chord：追加和弦', () => {
      const result = backend.execute({
        command: 'add_chord',
        args: { draft_id: draftId, chord: 'C', beats: 4 },
      });
      assertSuccess(result);
      expect(result.snapshot?.chords.length).toBe(1);
      expect(result.snapshot?.chords[0].chord).toBe('C');
    });

    it('09 update_chord：修改和弦', () => {
      const result = backend.execute({
        command: 'update_chord',
        args: { draft_id: draftId, index: 0, patch: { chord: 'G', beats: 2 } },
      });
      assertSuccess(result);
      expect(result.snapshot?.chords[0].chord).toBe('G');
      expect(result.snapshot?.chords[0].beats).toBe(2);
    });

    it('10 delete_chord：删除和弦（越界报错）', () => {
      const result = backend.execute({
        command: 'delete_chord',
        args: { draft_id: draftId, index: 0 },
      });
      assertSuccess(result);
      expect(result.snapshot?.chords.length).toBe(0);
      const bad = backend.execute({ command: 'delete_chord', args: { draft_id: draftId, index: 99 } });
      assertFailure(bad, 'CHORD_NOT_FOUND');
    });

    it('11 add_track：添加 auto 钢琴轨', () => {
      const result = backend.execute({
        command: 'add_track',
        args: { draft_id: draftId, name: '钢琴', program: 0, mode: 'auto', style: 'block_chords' },
      });
      assertSuccess(result);
      expect(result.snapshot?.accompaniment_tracks.length).toBe(1);
      expect(result.result?.track_id).toBe('trk_0');
    });

    it('12 remove_track：删除轨（不存在报错）', () => {
      const bad = backend.execute({ command: 'remove_track', args: { draft_id: draftId, track_id: 'trk_99' } });
      assertFailure(bad, 'TRACK_NOT_FOUND');
      const result = backend.execute({ command: 'remove_track', args: { draft_id: draftId, track_id: 'trk_0' } });
      assertSuccess(result);
      expect(result.snapshot?.accompaniment_tracks.length).toBe(0);
    });

    it('13 set_track_instrument：切换音色', () => {
      backend.execute({
        command: 'add_track',
        args: { draft_id: draftId, name: '贝斯', program: 33, mode: 'manual' },
      });
      const result = backend.execute({
        command: 'set_track_instrument',
        args: { draft_id: draftId, track_id: 'trk_0', program: 34 },
      });
      assertSuccess(result);
      expect(result.snapshot?.accompaniment_tracks[0].program).toBe(34);
    });

    it('14 set_track_mode：auto→manual 物化生成', () => {
      // 先加和弦和 auto 轨
      backend.execute({ command: 'add_chord', args: { draft_id: draftId, chord: 'C', beats: 4 } });
      backend.execute({
        command: 'add_track',
        args: { draft_id: draftId, name: '铺底', program: 0, mode: 'auto', style: 'block_chords' },
      });
      const result = backend.execute({
        command: 'set_track_mode',
        args: { draft_id: draftId, track_id: 'trk_1', mode: 'manual' },
      });
      assertSuccess(result);
      expect(result.snapshot?.accompaniment_tracks[1].mode).toBe('manual');
      expect(result.snapshot?.accompaniment_tracks[1].events.length).toBeGreaterThan(0); // 已物化
    });

    it('15 arrange_track：auto 轨编排（基于既有 chords 生成鼓点）', () => {
      backend.execute({
        command: 'add_track',
        args: { draft_id: draftId, name: '鼓组', program: -1, mode: 'auto', style: 'rock_4beat' },
      });
      // 当前 chords 含测试14 加入的 C 和弦（4 拍），arrange 应确定性生成鼓点：
      // 每 4 拍 = 8 个八分闭镲 + 2 底鼓（1/3 拍）+ 2 军鼓（2/4 拍），共 12 个事件
      const result = backend.execute({
        command: 'arrange_track',
        args: { draft_id: draftId, track_id: 'trk_2' },
      });
      assertSuccess(result);
      const events = result.result?.events as Array<Record<string, unknown>>;
      expect(events.length).toBe(12);
      expect(events.filter((e) => e.pitch === 'kick').length).toBe(2);
      expect(events.filter((e) => e.pitch === 'snare').length).toBe(2);
      expect(events.filter((e) => e.pitch === 'closed_hihat').length).toBe(8);
      // 幂等：再次 arrange 同输入同输出
      const again = backend.execute({
        command: 'arrange_track',
        args: { draft_id: draftId, track_id: 'trk_2' },
      });
      expect(again.result?.events).toEqual(events);
    });

    it('16 set_track_mix：调节音量与声像', () => {
      const result = backend.execute({
        command: 'set_track_mix',
        args: { draft_id: draftId, track_id: 'trk_1', volume: 80, pan: 32 },
      });
      assertSuccess(result);
      // trk_1 为铺底轨（accompaniment_tracks[1]，trk_0 为贝斯轨）
      const target = result.snapshot?.accompaniment_tracks.find((t) => t.id === 'trk_1');
      expect(target?.volume).toBe(80);
      expect(target?.pan).toBe(32);
    });

    it('17 undo：撤销最近编辑', () => {
      const before = backend.execute({ command: 'get_draft', args: { draft_id: draftId } });
      const beforeVersion = before.version!;
      const result = backend.execute({ command: 'undo', args: { draft_id: draftId } });
      assertSuccess(result);
      expect(result.version).toBe(beforeVersion + 1); // undo 也推进 version
    });

    it('18 redo：重做（空栈空操作）', () => {
      // 先 undo 再 redo
      backend.execute({ command: 'undo', args: { draft_id: draftId } });
      const result = backend.execute({ command: 'redo', args: { draft_id: draftId } });
      assertSuccess(result);
      // 连续 redo 到空栈：空操作成功
      const empty = backend.execute({ command: 'redo', args: { draft_id: draftId } });
      assertSuccess(empty);
    });

    it('19 validate_draft：返回 valid=true', () => {
      const result = backend.execute({ command: 'validate_draft', args: { draft_id: draftId } });
      assertSuccess(result);
      expect(result.result?.valid).toBe(true);
      expect(result.result?.errors).toEqual([]);
    });

    it('20 submit_draft：返回 task_id / song_id / status', () => {
      const result = backend.execute({ command: 'submit_draft', args: { draft_id: draftId } });
      assertSuccess(result);
      expect(result.result?.task_id).toMatch(/^mock_task_draft_\d+_v\d+$/);
      expect(result.result?.song_id).toMatch(/^mock_song_draft_\d+$/);
      expect(result.result?.status).toBe('pending');
    });

    // ------------------------------------------------------------------
    // 异常路径
    // ------------------------------------------------------------------

    it('异常：COMMAND_UNKNOWN', () => {
      const result = backend.execute({ command: 'not_a_command' as never, args: {} });
      assertFailure(result, 'COMMAND_UNKNOWN');
    });

    it('异常：DRAFT_NOT_FOUND', () => {
      const result = backend.execute({ command: 'get_draft', args: { draft_id: 'draft_999' } });
      assertFailure(result, 'DRAFT_NOT_FOUND');
    });

    it('异常：COMMAND_ARGS_INVALID（缺 draft_id）', () => {
      const result = backend.execute({ command: 'get_draft', args: {} as never });
      assertFailure(result, 'COMMAND_ARGS_INVALID');
    });

    it('异常：TRACK_NOT_FOUND', () => {
      const result = backend.execute({
        command: 'set_track_mix',
        args: { draft_id: draftId, track_id: 'trk_99', volume: 100 },
      });
      assertFailure(result, 'TRACK_NOT_FOUND');
    });

    it('异常：NOTE_NOT_FOUND（update_note 越界）', () => {
      const result = backend.execute({
        command: 'update_note',
        args: { draft_id: draftId, track: 'melody', note_id: 99, patch: { pitch: 'C4' } },
      });
      assertFailure(result, 'NOTE_NOT_FOUND');
    });

    it('异常：STYLE_UNKNOWN（arrange_track 非法节奏型）', () => {
      backend.execute({
        command: 'add_track',
        args: { draft_id: draftId, name: '测试', program: 0, mode: 'auto', style: 'block_chords' },
      });
      const result = backend.execute({
        command: 'arrange_track',
        args: { draft_id: draftId, track_id: 'trk_3', style: 'nonexistent_style' },
      });
      assertFailure(result, 'STYLE_UNKNOWN');
    });

    it('异常：TRACK_MODE_INVALID（manual 轨 arrange）', () => {
      backend.execute({
        command: 'add_track',
        args: { draft_id: draftId, name: '手动', program: 0, mode: 'manual' },
      });
      const result = backend.execute({
        command: 'arrange_track',
        args: { draft_id: draftId, track_id: 'trk_4' },
      });
      assertFailure(result, 'TRACK_MODE_INVALID');
    });
  });

  // ------------------------------------------------------------------
  // 版本与快照一致性
  // ------------------------------------------------------------------

  describe('版本与快照一致性', () => {
    it('version 单调递增（get_draft / validate_draft 不增）', () => {
      const backend = createMockDraftBackend();
      const create = backend.execute({ command: 'create_draft', args: {} });
      const draftId = create.draft_id!;
      expect(create.version).toBe(0);

      const get1 = backend.execute({ command: 'get_draft', args: { draft_id: draftId } });
      expect(get1.version).toBe(0); // get_draft 不增

      backend.execute({
        command: 'add_note',
        args: { draft_id: draftId, track: 'melody', pitch: 'D4', beats: 1, lyric: '' },
      });
      const get2 = backend.execute({ command: 'get_draft', args: { draft_id: draftId } });
      expect(get2.version).toBe(1); // add_note 增

      const validate = backend.execute({ command: 'validate_draft', args: { draft_id: draftId } });
      expect(validate.version).toBe(1); // validate_draft 不增
    });

    it('快照深拷贝隔离：修改返回值不影响内部状态', () => {
      const backend = createMockDraftBackend();
      const create = backend.execute({ command: 'create_draft', args: {} });
      const draftId = create.draft_id!;
      const snapshot = create.snapshot!;
      (snapshot as unknown as Record<string, unknown>).title = '外部篡改';
      const get = backend.execute({ command: 'get_draft', args: { draft_id: draftId } });
      expect(get.snapshot?.title).toBe('未命名');
    });
  });

  // ------------------------------------------------------------------
  // 夹具种子创建
  // ------------------------------------------------------------------

  describe('夹具种子创建', () => {
    it('seedFromFixture：v1_piano 迁移为 v2 含 auto 钢琴轨', () => {
      const backend = createMockDraftBackend();
      const result = backend.seedFromFixture('v1_piano');
      assertSuccess(result);
      expect(result.snapshot?.accompaniment_tracks.length).toBe(1);
      expect(result.snapshot?.accompaniment_tracks[0].style).toBe('block_chords');
      expect(result.snapshot?.accompaniment_tracks[0].mode).toBe('auto');
    });

    it('seedFromFixture：full_multitrack_v2 完整加载', () => {
      const backend = createMockDraftBackend();
      const result = backend.seedFromFixture('full_multitrack_v2');
      assertSuccess(result);
      expect(result.snapshot?.accompaniment_tracks.length).toBe(3);
      expect(result.snapshot?.chords.length).toBe(2);
      const drumTrack = result.snapshot?.accompaniment_tracks.find((t) => t.program === -1);
      expect(drumTrack).toBeDefined();
      expect(drumTrack?.style).toBe('rock_4beat');
    });
  });
});
