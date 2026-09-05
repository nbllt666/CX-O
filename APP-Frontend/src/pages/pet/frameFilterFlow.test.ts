/**
 * 帧筛选分流纯逻辑单测（spec add-vlm-frame-filter-face-match Task 5.5）。
 *
 * 覆盖 PetPage sendFrame 分流决策表的全部路径（组件挂载依赖过重，按
 * pages/pet 纯函数测试惯例在此收口）：
 * - resolveFrameFilterPrompt：face_labels 提示拼接（无标签原样 / 有标签追加）；
 * - runFrameFilterFlow：forward→发起对话、summarize/discard→静默、请求异常→回退直通。
 * 「筛选关闭→不走筛选」为 PetPage 内联布尔门（frameFilterEnabled），不经过本模块。
 */
import { describe, expect, it, vi } from 'vitest';

import type { FrameFilterResponse } from '../../api/clients/vision';
import {
  resolveFrameFilterPrompt,
  runFrameFilterFlow,
  type FaceLabelsHintBuilder,
  type FrameFilterFlowIo,
} from './frameFilterFlow';

const BASE_PROMPT = '[摄像头画面] 看看我现在的画面';

/** 稳定的提示构造器 stub：模拟 i18n t('pet.capture.faceLabelsHint', { labels }) 插值结果 */
const buildLabelsHint: FaceLabelsHintBuilder = (labels) => `${labels} 在画面中`;

/** 构造完整 IO mock（四个口子全部 vi.fn，便于逐路径断言；overrides 按路径注入 mock 值） */
function createIo(overrides: Partial<FrameFilterFlowIo> = {}) {
  return {
    requestFilter: vi.fn(),
    startConversation: vi.fn(),
    settleSilent: vi.fn(),
    fallbackToConversation: vi.fn(),
    ...overrides,
  };
}

function forwardResponse(faceLabels?: string[]): FrameFilterResponse {
  return { action: 'forward', filter_active: true, face_labels: faceLabels };
}

describe('resolveFrameFilterPrompt（forward prompt 组装）', () => {
  it('face_labels 缺失时原样返回基础 prompt', () => {
    expect(resolveFrameFilterPrompt(BASE_PROMPT, undefined, buildLabelsHint)).toBe(BASE_PROMPT);
  });

  it('face_labels 为空数组时原样返回基础 prompt', () => {
    expect(resolveFrameFilterPrompt(BASE_PROMPT, [], buildLabelsHint)).toBe(BASE_PROMPT);
  });

  it('单标签时追加提示（标签经构造器插值）', () => {
    const prompt = resolveFrameFilterPrompt(BASE_PROMPT, ['小A'], buildLabelsHint);
    expect(prompt).toBe(`${BASE_PROMPT}\n小A 在画面中`);
  });

  it('多标签时以「、」连接后交给构造器', () => {
    const prompt = resolveFrameFilterPrompt(BASE_PROMPT, ['小A', '小B'], buildLabelsHint);
    expect(prompt).toBe(`${BASE_PROMPT}\n小A、小B 在画面中`);
  });
});

describe('runFrameFilterFlow（分流决策表）', () => {
  it('forward：发起对话，prompt 含 face_labels 提示，图片透传', async () => {
    const io = createIo({ requestFilter: vi.fn().mockResolvedValue(forwardResponse(['小A'])) });
    await runFrameFilterFlow('img-1', 'agent-1', 'camera', 'ts-1', BASE_PROMPT, buildLabelsHint, io);
    expect(io.requestFilter).toHaveBeenCalledWith('img-1', 'agent-1', 'camera', 'ts-1');
    expect(io.startConversation).toHaveBeenCalledTimes(1);
    expect(io.startConversation).toHaveBeenCalledWith(`${BASE_PROMPT}\n小A 在画面中`, 'img-1');
    expect(io.settleSilent).not.toHaveBeenCalled();
    expect(io.fallbackToConversation).not.toHaveBeenCalled();
  });

  it('forward 且无 face_labels：以基础 prompt 发起对话', async () => {
    const io = createIo({ requestFilter: vi.fn().mockResolvedValue(forwardResponse()) });
    await runFrameFilterFlow('img-2', 'agent-1', 'screen', 'ts-2', BASE_PROMPT, buildLabelsHint, io);
    expect(io.startConversation).toHaveBeenCalledWith(BASE_PROMPT, 'img-2');
  });

  it('summarize：静默结束——不发起对话，仅复位互斥', async () => {
    const io = createIo({
      requestFilter: vi.fn().mockResolvedValue({
        action: 'summarize',
        summary: '用户翻动了文档',
        filter_active: true,
      } satisfies FrameFilterResponse),
    });
    await runFrameFilterFlow('img-3', 'agent-1', 'screen', 'ts-3', BASE_PROMPT, buildLabelsHint, io);
    expect(io.settleSilent).toHaveBeenCalledTimes(1);
    expect(io.startConversation).not.toHaveBeenCalled();
    expect(io.fallbackToConversation).not.toHaveBeenCalled();
  });

  it('discard：静默结束——不发起对话，仅复位互斥', async () => {
    const io = createIo({
      requestFilter: vi.fn().mockResolvedValue({
        action: 'discard',
        filter_active: true,
      } satisfies FrameFilterResponse),
    });
    await runFrameFilterFlow('img-4', 'agent-1', 'camera', 'ts-4', BASE_PROMPT, buildLabelsHint, io);
    expect(io.settleSilent).toHaveBeenCalledTimes(1);
    expect(io.startConversation).not.toHaveBeenCalled();
    expect(io.fallbackToConversation).not.toHaveBeenCalled();
  });

  it('筛选请求失败（网络/5xx）：回退直通对话（以基础 prompt 发起），不静默', async () => {
    const error = new Error('请求失败: 502 Bad Gateway');
    const io = createIo({ requestFilter: vi.fn().mockRejectedValue(error) });
    await runFrameFilterFlow('img-5', 'agent-1', 'camera', 'ts-5', BASE_PROMPT, buildLabelsHint, io);
    expect(io.fallbackToConversation).toHaveBeenCalledTimes(1);
    expect(io.fallbackToConversation).toHaveBeenCalledWith(error);
    expect(io.startConversation).not.toHaveBeenCalled();
    expect(io.settleSilent).not.toHaveBeenCalled();
  });
});
