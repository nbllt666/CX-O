/**
 * 头像清单合成：由设置项（modelPath / scale / 偏移）构造 AvatarManifest。
 *
 * 桌宠窗默认消费本地 public/models 下的模型资产，无服务端清单；
 * 合成清单的 transform 字段口径对齐 CX-O-Frontend 各查看器的 createSyntheticManifest。
 */
import type { AvatarManifest } from './types';

/** Live2D 合成清单（对齐参考查看器：modelTransform.scale 固定 8 倍基线） */
export function createSyntheticLive2DManifest(
  modelJson: string,
  scale: number,
  xOffset = 0,
  yOffset = 0,
): AvatarManifest {
  return {
    id: 'synthetic-live2d',
    name: 'Live2D Model',
    summary: '',
    persona: { tone: '', traits: [], styleRules: [] },
    modelJson,
    scaleMultiplier: scale,
    verticalOffset: 0.08,
    modelTransform: {
      scale: 8,
      offsetX: xOffset / 400,
      offsetY: yOffset / 400 + 1.3,
    },
    transformDefaults: { scale: 1, offsetX: 0, offsetY: 0 },
    expressions: [],
    parameterControls: [],
    avatarType: 'live2d',
  };
}

/** VRM 合成清单（scale 直接乘入模型缩放，position 前两位映射平面偏移） */
export function createSyntheticVRMManifest(
  modelPath: string,
  scale = 1,
  position: [number, number, number] = [0, 0, 0],
): AvatarManifest {
  return {
    id: 'synthetic-vrm',
    name: 'VRM Model',
    summary: '',
    persona: { tone: '', traits: [], styleRules: [] },
    modelJson: modelPath,
    scaleMultiplier: 1,
    verticalOffset: 0,
    modelTransform: {
      scale,
      offsetX: position[0],
      offsetY: position[1],
    },
    transformDefaults: { scale: 1, offsetX: 0, offsetY: 0 },
    expressions: [],
    parameterControls: [],
    avatarType: 'vrm',
  };
}
