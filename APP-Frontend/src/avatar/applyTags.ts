/**
 * 标签应用：把解析出的驱动标签逐个下发到 IAvatarDriver。
 *
 * 行为口径对齐 CX-O-Frontend src/pages/chat/utils.ts 的 applyAvatarTags。
 * sleep 标签不在此处消费（由 TTS 播放调度层处理分段停顿），仅日志留痕。
 */
import type { IAvatarDriver } from './types';
import type { AvatarTag } from './tagParser';

/** 挥手类动作：触发动作的同时追加一次交互风冲击 */
const WAVE_ACTIONS = new Set(['wave', 'hello', 'hi', 'bye', 'greet', 'handwave']);

export function applyAvatarTags(driver: IAvatarDriver, tags: AvatarTag[]): void {
  // [blend:] 标签聚合为当次消息的"活跃直接表情集"，循环结束后一次性下发。
  // blend 本就立即生效，聚合后当次消息的 blend 集合即视为活跃集，
  // 由 vrmEngine.setBlendShapes 内部的 fadeOutUnusedExpressions 让不在当次批次的旧表情平滑归零。
  const blendBatch: Array<{ name: string; weight: number }> = [];
  for (const tag of tags) {
    switch (tag.type) {
      case 'emotion':
        driver.setEmotion(tag.emotion, 1.0);
        break;
      case 'blend':
        blendBatch.push({ name: tag.name, weight: tag.weight });
        break;
      case 'bone':
        driver.setBoneRotations([
          { boneName: tag.boneName, rotation: tag.rotation, speed: tag.speed },
        ]);
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
      case 'action':
        driver.playAction(tag.action);
        if (WAVE_ACTIONS.has(tag.action)) {
          driver.triggerInteractionWind(0.6);
        }
        break;
      case 'sleep':
        console.log('[avatar] sleep tag:', tag.duration_ms, 'ms');
        break;
    }
  }

  if (blendBatch.length > 0) {
    driver.setBlendShapes(blendBatch);
  }
}
