/**
 * VRM 驱动骨骼白名单目录。
 *
 * 覆盖 VRM Humanoid 标准骨骼，每项提供基于人体运动学约束的 XYZ 旋转范围
 * （单位：弧度）与用途说明 prompt。数值口径保持与 config/hidden_prompt.yaml
 * avatar_prompts 冻结快照一致，供后续一致性测验校验。
 */

import { AvatarBoneControl } from '../types';

export const DEFAULT_BONE_CONTROLS: AvatarBoneControl[] = [
  {
    id: 'head',
    label: '头部',
    rotationRange: { x: [-0.6, 0.6], y: [-0.6, 0.6], z: [-0.6, 0.6] },
    prompt: '点头、摇头、歪头',
  },
  {
    id: 'neck',
    label: '颈部',
    rotationRange: { x: [-0.4, 0.4], y: [-0.6, 0.6], z: [-0.4, 0.4] },
    prompt: '点头、摇头、歪头',
  },
  {
    id: 'spine',
    label: '脊柱',
    rotationRange: { x: [-0.3, 0.3], y: [-0.3, 0.3], z: [-0.3, 0.3] },
    prompt: '躯干轻微前倾、扭转',
  },
  {
    id: 'chest',
    label: '胸部',
    rotationRange: { x: [-0.25, 0.25], y: [-0.25, 0.25], z: [-0.3, 0.3] },
    prompt: '躯干上部轻微扭动、侧倾',
  },
  {
    id: 'upperChest',
    label: '上胸部',
    rotationRange: { x: [-0.25, 0.25], y: [-0.25, 0.25], z: [-0.3, 0.3] },
    prompt: '躯干上部轻微扭动、侧倾',
  },
  {
    id: 'hips',
    label: '髋部',
    rotationRange: { x: [-0.25, 0.25], y: [-0.4, 0.4], z: [-0.25, 0.25] },
    prompt: '骨盆摆动、轻晃',
  },
  {
    id: 'leftUpperArm',
    label: '左上臂',
    rotationRange: { x: [-0.5, 0.5], y: [-0.5, 0.5], z: [-1.5, 1.5] },
    prompt: '抬臂、摆手、摇摆',
  },
  {
    id: 'rightUpperArm',
    label: '右上臂',
    rotationRange: { x: [-0.5, 0.5], y: [-0.5, 0.5], z: [-1.5, 1.5] },
    prompt: '抬臂、摆手、摇摆',
  },
  {
    id: 'leftLowerArm',
    label: '左前臂',
    rotationRange: { x: [-0.5, 0.5], y: [-0.5, 0.5], z: [-1.5, 1.5] },
    prompt: '屈肘、挥动、摆动',
  },
  {
    id: 'rightLowerArm',
    label: '右前臂',
    rotationRange: { x: [-0.5, 0.5], y: [-0.5, 0.5], z: [-1.5, 1.5] },
    prompt: '屈肘、挥动、摆动',
  },
  {
    id: 'leftHand',
    label: '左手',
    rotationRange: { x: [-0.4, 0.4], y: [-0.4, 0.4], z: [-0.8, 0.8] },
    prompt: '手腕转动、示意',
  },
  {
    id: 'rightHand',
    label: '右手',
    rotationRange: { x: [-0.4, 0.4], y: [-0.4, 0.4], z: [-0.8, 0.8] },
    prompt: '手腕转动、示意',
  },
  {
    id: 'leftUpperLeg',
    label: '左大腿',
    rotationRange: { x: [-0.6, 0.6], y: [-0.2, 0.2], z: [-0.3, 0.3] },
    prompt: '抬腿、迈步、摆动',
  },
  {
    id: 'rightUpperLeg',
    label: '右大腿',
    rotationRange: { x: [-0.6, 0.6], y: [-0.2, 0.2], z: [-0.3, 0.3] },
    prompt: '抬腿、迈步、摆动',
  },
  {
    id: 'leftLowerLeg',
    label: '左小腿',
    rotationRange: { x: [-0.6, 0.6], y: [-0.2, 0.2], z: [-0.3, 0.3] },
    prompt: '屈膝、踢腿、摆动',
  },
  {
    id: 'rightLowerLeg',
    label: '右小腿',
    rotationRange: { x: [-0.6, 0.6], y: [-0.2, 0.2], z: [-0.3, 0.3] },
    prompt: '屈膝、踢腿、摆动',
  },
  {
    id: 'leftShoulder',
    label: '左肩/锁骨',
    rotationRange: { x: [-0.4, 0.4], y: [-0.4, 0.4], z: [-0.8, 0.8] },
    prompt: '耸肩、抬肩、肩胛前送',
  },
  {
    id: 'rightShoulder',
    label: '右肩/锁骨',
    rotationRange: { x: [-0.4, 0.4], y: [-0.4, 0.4], z: [-0.8, 0.8] },
    prompt: '耸肩、抬肩、肩胛前送',
  },
  {
    id: 'leftFoot',
    label: '左脚',
    rotationRange: { x: [-0.5, 0.5], y: [-0.3, 0.3], z: [-0.4, 0.4] },
    prompt: '跺脚、垫脚、脚尖朝向',
  },
  {
    id: 'rightFoot',
    label: '右脚',
    rotationRange: { x: [-0.5, 0.5], y: [-0.3, 0.3], z: [-0.4, 0.4] },
    prompt: '跺脚、垫脚、脚尖朝向',
  },
  {
    id: 'leftEye',
    label: '左眼',
    rotationRange: { x: [-0.15, 0.15], y: [-0.15, 0.15], z: [-0.15, 0.15] },
    prompt: '眼球朝向、余光、转眼',
  },
  {
    id: 'rightEye',
    label: '右眼',
    rotationRange: { x: [-0.15, 0.15], y: [-0.15, 0.15], z: [-0.15, 0.15] },
    prompt: '眼球朝向、余光、转眼',
  },
  {
    id: 'leftThumb',
    label: '左拇指',
    rotationRange: { x: [-0.5, 0.5], y: [-0.5, 0.5], z: [-0.5, 0.5] },
    prompt: '拇指张开、竖起大拇指',
  },
  {
    id: 'rightThumb',
    label: '右拇指',
    rotationRange: { x: [-0.5, 0.5], y: [-0.5, 0.5], z: [-0.5, 0.5] },
    prompt: '拇指张开、竖起大拇指',
  },
  {
    id: 'leftIndex',
    label: '左食指',
    rotationRange: { x: [-0.6, 0.6], y: [-0.6, 0.6], z: [-0.6, 0.6] },
    prompt: '食指指向、轻戳、招手',
  },
  {
    id: 'rightIndex',
    label: '右食指',
    rotationRange: { x: [-0.6, 0.6], y: [-0.6, 0.6], z: [-0.6, 0.6] },
    prompt: '食指指向、轻戳、招手',
  },
];

const BONE_RANGE_MAP: Map<string, AvatarBoneControl['rotationRange']> = new Map(
  DEFAULT_BONE_CONTROLS.map((control) => [control.id.toLowerCase(), control.rotationRange]),
);

export function isControlledBone(name: string): boolean {
  return BONE_RANGE_MAP.has(name.toLowerCase());
}

export function getBoneRange(
  boneName: string,
): AvatarBoneControl['rotationRange'] | undefined {
  return BONE_RANGE_MAP.get(boneName.toLowerCase());
}