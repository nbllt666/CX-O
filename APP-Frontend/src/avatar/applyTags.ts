/**
 * 标签应用：把解析出的驱动标签逐个下发到 IAvatarDriver。
 *
 * 行为口径对齐 CX-O-Frontend src/pages/chat/utils.ts 的 applyAvatarTags。
 * sleep 标签不在此处消费（由 TTS 播放调度层处理分段停顿），仅日志留痕。
 */
import type { IAvatarDriver } from './types';
import type { AvatarTag } from './tagParser';

export function applyAvatarTags(driver: IAvatarDriver, tags: AvatarTag[]): void {
  for (const tag of tags) {
    switch (tag.type) {
      case 'emotion':
        driver.setEmotion(tag.emotion, 1.0);
        break;
      case 'blend':
        driver.setBlendShapes([{ name: tag.name, weight: tag.weight }]);
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
      case 'sleep':
        console.log('[avatar] sleep tag:', tag.duration_ms, 'ms');
        break;
    }
  }
}
