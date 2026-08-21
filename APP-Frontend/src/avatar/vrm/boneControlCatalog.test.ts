/**
 * VRM 驱动骨骼白名单目录单测 + 与 config/hidden_prompt.yaml 一致性断言。
 *
 * 覆盖：
 * - 目录完整性：数量、四字段、rotationRange 三轴 [min,max] 且 min<=max
 * - isControlledBone / getBoneRange 的命中、未命中与大小写不敏感
 * - GN-004 O1：catalog 骨骼 id 集合与 hidden_prompt.yaml avatar_prompts
 *   受控骨骼清单中的骨骼名一致（floating/bond 的冻结快照口径）
 */
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { DEFAULT_BONE_CONTROLS, getBoneRange, isControlledBone } from './boneControlCatalog';

describe('DEFAULT_BONE_CONTROLS 目录完整性', () => {
  it('骨骼数量应至少 12 项', () => {
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

  it('大小写不敏感：Neck 命中 ok', () => {
    expect(getBoneRange('Neck')).toBeDefined();
  });
});

describe('GN-004 O1：catalog 与 hidden_prompt.yaml 受控骨骼清单一致', () => {
  it('catalog 全部骨骼 id 均应出现在 hidden_prompt.yaml 受控骨骼清单中', () => {
    // config/hidden_prompt.yaml 位于项目根 CX-O 的 config/ 下（APP-Frontend 的上一级）。
    // 注意：测试环境里 process 是被 process-polyfill 垫片（cwd='.'），import.meta.url 也不是
    // file: scheme，无法相对推导；node:fs 为真实 Node fs，直接以冻结快照的绝对路径读取即可。
    const yaml = readFileSync('C:/CX-O/config/hidden_prompt.yaml', 'utf-8');
    const lower = yaml.toLowerCase();

    // hidden_prompt.yaml 应包含受控骨骼清单小节
    expect(lower).toContain('受控骨骼清单');
    // 逐一判断：catalog 每根骨骼 id 均须命中（大小写不敏感）
    for (const control of DEFAULT_BONE_CONTROLS) {
      expect(lower).toContain(control.id.toLowerCase());
    }
  });
});