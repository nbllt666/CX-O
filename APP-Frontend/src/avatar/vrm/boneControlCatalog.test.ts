/**
 * VRM 驱动骨骼白名单目录单测 + 与 config/hidden_prompt.yaml 一致性断言。
 *
 * 覆盖：
 * - 目录完整性：数量、四字段、rotationRange 三轴 [min,max] 且 min<=max
 * - isControlledBone / getBoneRange 的命中、未命中与大小写不敏感
 * - GN-004 O1：catalog 骨骼 id 集合与 hidden_prompt.yaml avatar_prompts
 *   受控骨骼清单中的骨骼名一致（floating/bond 的冻结快照口径）
 *
 * ⚠ 待人工核对路径（spec 已声明）：范围数值的逐轴精确一致性（如 x/y/z 各自的确切
 * [min,max]）由 GN-004 交付前人工核对。hidden_prompt.yaml 的受控骨骼清单是人读散文
 * （如“x/y/z 均在 ±0.5 弧度”“x ±0.5 弧度，y ±0.3 弧度，z ±0.4 弧度”），无法可靠
 * 逐轴机器解析。单测在此仅保证：① catalog 每根骨骼 id 在 hidden_prompt 中“出现”；
 * ② 每根新增骨骼的“范围代表值字符串”在其所在行的 round-trip 子串匹配通过。两者均
 * 非逐轴精确校验，不得据此伪装自动化 PASS。
 */
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { DEFAULT_BONE_CONTROLS, getBoneRange, isControlledBone } from './boneControlCatalog';

// vite.config 编译期注入的仓库根绝对路径（统一正斜杠），由 Node 加载 vite.config 时用 __dirname 推导
declare const __CXO_PROJECT_ROOT__: string;

describe('DEFAULT_BONE_CONTROLS 目录完整性', () => {
  it('骨骼数量应等于 26 项（扩容后）', () => {
    expect(DEFAULT_BONE_CONTROLS).toHaveLength(26);
  });

  it('骨骼数量应至少 12 项（兼容旧阈值）', () => {
    expect(DEFAULT_BONE_CONTROLS.length).toBeGreaterThanOrEqual(12);
  });

  it('每项均应包含 id/label/rotationRange/prompt 四字段', () => {
    for (const control of DEFAULT_BONE_CONTROLS) {
      expect(control).toHaveProperty('id');
      expect(control).toHaveProperty('label');
      expect(control).toHaveProperty('rotationRange');
      expect(control).toHaveProperty('prompt');
      expect(typeof control.id).toBe('string');
      expect(typeof control.label).toBe('string');
      expect(typeof control.prompt).toBe('string');
    }
  });

  it('rotationRange 的 x/y/z 均为 [min,max] 且 min<=max', () => {
    for (const control of DEFAULT_BONE_CONTROLS) {
      const r = control.rotationRange;
      for (const axis of ['x', 'y', 'z'] as const) {
        const range = r[axis];
        expect(Array.isArray(range)).toBe(true);
        expect(range).toHaveLength(2);
        expect(range[0]).toBeLessThanOrEqual(range[1]);
      }
    }
  });
});

describe('isControlledBone', () => {
  it('head 命中 true', () => {
    expect(isControlledBone('head')).toBe(true);
  });

  it('leftUpperArm 命中 true', () => {
    expect(isControlledBone('leftUpperArm')).toBe(true);
  });

  it('leftPinky 返回 false（白名单外）', () => {
    expect(isControlledBone('leftPinky')).toBe(false);
  });

  it('新增骨骼 leftShoulder 命中 true', () => {
    expect(isControlledBone('leftShoulder')).toBe(true);
  });

  it('新增骨骼 leftFoot 命中 true', () => {
    expect(isControlledBone('leftFoot')).toBe(true);
  });

  it('新增骨骼 leftEye 命中 true', () => {
    expect(isControlledBone('leftEye')).toBe(true);
  });

  it('新增骨骼 leftThumb 命中 true', () => {
    expect(isControlledBone('leftThumb')).toBe(true);
  });

  it('新增骨骼 leftIndex 命中 true', () => {
    expect(isControlledBone('leftIndex')).toBe(true);
  });

  it('未开放手指 leftMiddle 返回 false（白名单外）', () => {
    expect(isControlledBone('leftMiddle')).toBe(false);
  });

  it('未开放手指 rightPinky 返回 false（白名单外）', () => {
    expect(isControlledBone('rightPinky')).toBe(false);
  });

  it('未开放脚趾 leftToes/rightToes 返回 false（白名单外）', () => {
    expect(isControlledBone('leftToes')).toBe(false);
    expect(isControlledBone('rightToes')).toBe(false);
  });

  it('大小写不敏感：HEAD 命中 true', () => {
    expect(isControlledBone('HEAD')).toBe(true);
  });
});

describe('getBoneRange', () => {
  it('head 返回含 ±0.6 的 range', () => {
    const range = getBoneRange('head');
    expect(range).toBeDefined();
    expect(range!.x[0]).toBe(-0.6);
    expect(range!.x[1]).toBe(0.6);
  });

  it('leftUpperArm 的 z 范围为 [-1.5,1.5]', () => {
    const range = getBoneRange('leftUpperArm');
    expect(range).toBeDefined();
    expect(range!.z[0]).toBe(-1.5);
    expect(range!.z[1]).toBe(1.5);
  });

  it('不存在的骨骼返回 undefined', () => {
    expect(getBoneRange('nonexistent')).toBeUndefined();
  });

  it('新增骨骼 leftShoulder 的 z 范围为 [-0.8,0.8]', () => {
    const range = getBoneRange('leftShoulder');
    expect(range).toBeDefined();
    expect(range!.z[0]).toBe(-0.8);
    expect(range!.z[1]).toBe(0.8);
  });

  it('新增骨骼 leftThumb 各轴均为 [-0.5,0.5]', () => {
    const range = getBoneRange('leftThumb');
    expect(range).toBeDefined();
    for (const axis of ['x', 'y', 'z'] as const) {
      expect(range![axis][0]).toBe(-0.5);
      expect(range![axis][1]).toBe(0.5);
    }
  });

  it('新增骨骼 leftIndex 各轴均为 [-0.6,0.6]', () => {
    const range = getBoneRange('leftIndex');
    expect(range).toBeDefined();
    for (const axis of ['x', 'y', 'z'] as const) {
      expect(range![axis][0]).toBe(-0.6);
      expect(range![axis][1]).toBe(0.6);
    }
  });

  it('新增骨骼 leftEye 各轴均为 [-0.15,0.15]', () => {
    const range = getBoneRange('leftEye');
    expect(range).toBeDefined();
    for (const axis of ['x', 'y', 'z'] as const) {
      expect(range![axis][0]).toBe(-0.15);
      expect(range![axis][1]).toBe(0.15);
    }
  });

  it('未开放脚趾 leftToes 返回 undefined', () => {
    expect(getBoneRange('leftToes')).toBeUndefined();
  });

  it('大小写不敏感：Neck 命中 ok', () => {
    expect(getBoneRange('Neck')).toBeDefined();
  });
});

describe('GN-004 O1：catalog 与 hidden_prompt.yaml 受控骨骼清单一致', () => {
  it('catalog 全部骨骼 id 均应出现在 hidden_prompt.yaml 受控骨骼清单中', () => {
    // hidden_prompt.yaml 位于仓库根 config/ 下（APP-Frontend 的上一级 CX-O/）。
    // 测试环境的 process 被 node-polyfills 垫片劫持（cwd='.'）、import.meta.url 非 file: scheme，
    // 无法相对推导；改用 vite.config 编译期注入的仓库根绝对路径 __CXO_PROJECT_ROOT__
    // （由 Node 加载 vite.config 时 __dirname 推导），兼容任意开发机/CI，无硬编码路径。
    const yaml = readFileSync(`${__CXO_PROJECT_ROOT__}/config/hidden_prompt.yaml`, 'utf-8');
    const lower = yaml.toLowerCase();

    // hidden_prompt.yaml 应包含受控骨骼清单小节
    expect(lower).toContain('受控骨骼清单');
    // 逐一判断：catalog 每根骨骼 id 均须命中（大小写不敏感）
    for (const control of DEFAULT_BONE_CONTROLS) {
      expect(lower).toContain(control.id.toLowerCase());
    }
  });

  it('catalog 每根新增骨骼的 id 及其范围代表值应出现在 hidden_prompt.yaml 对应骨骼所在行（round-trip 匹配）', () => {
    // hidden_prompt 受控骨骼清单是人读散文（如“x/y/z 均在 ±0.5 弧度”“x ±0.5 弧度，
    // y ±0.3 弧度，z ±0.4 弧度”），逐轴机器解析不可靠。此处采用诚实做法：
    // ① 先定位含骨骼 id 的行（规避全文同名范围值冲突）；
    // ② 断言该行包含该骨骼的“范围代表值”精确子串（含骨骼名语境，保证唯一）。
    // 逐轴精确数值一致性留待 GN-004 交付前人工核对，见测试文件头部声明。
    const yaml = readFileSync(`${__CXO_PROJECT_ROOT__}/config/hidden_prompt.yaml`, 'utf-8');
    const lines = yaml.split(/\r?\n/);

    const NEW_BONE_ASSERTIONS: Array<{ id: string; sub: string }> = [
      // leftEye/rightEye → 眼睛：x/y/z 均在 ±0.15
      { id: 'leftEye', sub: 'leftEye / rightEye（眼睛）：x/y/z 均在 ±0.15 弧度' },
      { id: 'rightEye', sub: 'leftEye / rightEye（眼睛）：x/y/z 均在 ±0.15 弧度' },
      // leftIndex/rightIndex → 食指：x/y/z 均在 ±0.6
      { id: 'leftIndex', sub: 'leftIndex / rightIndex（食指）：x/y/z 均在 ±0.6 弧度' },
      { id: 'rightIndex', sub: 'leftIndex / rightIndex（食指）：x/y/z 均在 ±0.6 弧度' },
      // leftShoulder/rightShoulder → 肩：x/y 均在 ±0.4，z ±0.8
      { id: 'leftShoulder', sub: 'leftShoulder / rightShoulder（肩）：x/y 均在 ±0.4 弧度，z ±0.8 弧度' },
      { id: 'rightShoulder', sub: 'leftShoulder / rightShoulder（肩）：x/y 均在 ±0.4 弧度，z ±0.8 弧度' },
      // leftThumb/rightThumb → 拇指：x/y/z 均在 ±0.5
      { id: 'leftThumb', sub: 'leftThumb / rightThumb（拇指）：x/y/z 均在 ±0.5 弧度' },
      { id: 'rightThumb', sub: 'leftThumb / rightThumb（拇指）：x/y/z 均在 ±0.5 弧度' },
      // leftFoot/rightFoot → 脚：x ±0.5，y ±0.3，z ±0.4
      { id: 'leftFoot', sub: 'leftFoot / rightFoot（脚）：x ±0.5 弧度，y ±0.3 弧度，z ±0.4 弧度' },
      { id: 'rightFoot', sub: 'leftFoot / rightFoot（脚）：x ±0.5 弧度，y ±0.3 弧度，z ±0.4 弧度' },
    ];

    for (const { id, sub } of NEW_BONE_ASSERTIONS) {
      // 行归一化：大小写不敏感，并去除 hidden_prompt 中包裹骨骼名的 `**` markdown 加粗符，
      // 使子串（含“（肩）：”等连续字符）可与正文精确匹配。
      const boneLinesLower = lines
        .filter((l) => l.toLowerCase().includes(id.toLowerCase()))
        .map((l) => l.toLowerCase().replace(/\*\*/g, ''));
      expect(
        boneLinesLower.length,
        `骨骼 ${id} 在 hidden_prompt.yaml 身体骨骼清单中应存在至少一行`,
      ).toBeGreaterThan(0);
      expect(
        boneLinesLower.some((l) => l.includes(sub.toLowerCase())),
        `骨骼 ${id} 所在行应包含其范围代表值子串 "${sub}"`,
      ).toBe(true);
    }
  });
});