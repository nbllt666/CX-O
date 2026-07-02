/**
 * 纯工具函数：从 ChatPage.tsx 提取，便于单元测试。
 *
 * H4 拆分第一步：把无 React 依赖的纯函数迁移到本文件，ChatPage 通过 import 使用。
 * 行为与原内联实现等价，无副作用。
 */
import type { IAvatarDriver } from '../../components/Avatar/AvatarDriver';
import type { AvatarTag, Segment } from '../../lib/avatarTagParser';

export function applyAvatarTags(driver: IAvatarDriver, tags: AvatarTag[]): void {
  for (const tag of tags) {
    switch (tag.type) {
      case 'emotion':
        driver.setEmotion(tag.name, 1.0);
        break;
      case 'blend':
        driver.setBlendShapes([{ name: tag.name, weight: tag.weight }]);
        break;
      case 'bone':
        driver.setBoneRotations([{ boneName: tag.boneName, rotation: tag.rotation, speed: tag.speed }]);
        break;
      case 'pose':
        driver.holdPose(tag.durationMs);
        break;
      case 'release':
        driver.releasePose();
        break;
      case 'wind':
        driver.setWind(tag);
        break;
      case 'sleep':
        console.log('[avatar] sleep tag:', tag.ms, 'ms');
        break;
    }
  }
}

export interface TtsGroup {
  text: string;
  sleepAfterMs?: number;
}

/**
 * 把 parseAvatarTags 输出的 segments 聚合为「文本组 + 后置 sleep」结构。
 *
 * 规则：
 * - 连续 text segment 累积到 textBuffer
 * - 遇到 sleep tag：
 *   - 若 textBuffer 非空 → 推入新 group，记录 sleepAfterMs，清空 textBuffer
 *   - 若 textBuffer 为空且已有 group → 累加 sleep 到最后一个 group 的 sleepAfterMs
 *   - 若 textBuffer 为空且无 group → 忽略（sleep 在最前面无意义）
 * - 末尾若 textBuffer 非空 → 推入最后一个 group（无 sleepAfterMs）
 */
export function groupTtsSegments(segments: Segment[]): TtsGroup[] {
  const groups: TtsGroup[] = [];
  let textBuffer = '';

  for (const segment of segments) {
    if (segment.type === 'text') {
      textBuffer += segment.content;
    } else if (segment.type === 'tag' && segment.tag.type === 'sleep') {
      if (textBuffer.trim()) {
        groups.push({ text: textBuffer, sleepAfterMs: segment.tag.ms });
        textBuffer = '';
      } else if (groups.length > 0) {
        const last = groups[groups.length - 1];
        last.sleepAfterMs = (last.sleepAfterMs || 0) + segment.tag.ms;
      }
    }
  }

  if (textBuffer.trim()) {
    groups.push({ text: textBuffer });
  }

  return groups;
}

/**
 * 按 group 顺序播放 TTS：tts → play → (sleep) → next group。
 *
 * - 最后一组的 isLastSegment 标记为 true
 * - sleep 只在非末尾组生效（末尾组即使有 sleepAfterMs 也不等待）
 * - tts/play 错误被吞掉，继续下一组
 */
export async function playTTSWithPauses(
  segments: Segment[],
  ttsFn: (text: string) => Promise<Blob>,
  playFn: (audioData: ArrayBuffer, isLastSegment?: boolean) => Promise<void>,
): Promise<void> {
  const groups = groupTtsSegments(segments);
  if (groups.length === 0) return;

  for (let i = 0; i < groups.length; i++) {
    const group = groups[i];
    if (!group.text.trim()) continue;

    try {
      const audioBlob = await ttsFn(group.text);
      const arrayBuffer = await audioBlob.arrayBuffer();
      await playFn(arrayBuffer, i === groups.length - 1);
    } catch (error) {
      console.error('语音合成失败:', error);
    }

    if (group.sleepAfterMs && i < groups.length - 1) {
      await new Promise(resolve => setTimeout(resolve, group.sleepAfterMs));
    }
  }
}
