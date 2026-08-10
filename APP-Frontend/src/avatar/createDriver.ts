/**
 * 驱动工厂：按清单 avatarType 创建对应驱动实例。
 * 行为口径对齐 CX-O-Frontend avatar-driver.ts 的 createAvatarDriver。
 */
import type { AvatarManifest, IAvatarDriver } from './types';
import { VRMDriver } from './vrmDriver';
import { Live2DDriver } from './live2dDriver';

export function createAvatarDriver(avatar: AvatarManifest): IAvatarDriver {
  if (avatar.avatarType === 'vrm') {
    return new VRMDriver(avatar);
  }
  return new Live2DDriver(avatar);
}
