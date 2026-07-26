/**
 * @file index.ts — business/ 业务组件重组层统一导出（模块7）
 * ============================================================================
 * 模块: 模块7 业务组件重组层 — 主线程统一拼装（A 组 + B 组完成后）
 * 落点: C:\CX-O\CX-O-Frontend\src\components\business\index.ts
 *
 * 职责（MODULE-7 AGENTS.md §2.7 输出文件清单）:
 *   - 17 根组件（A 组 11 + B 组 6）+ 6 子目录 re-export
 *   - 供模块8 页面应用层通过 '@/components/business' 消费
 *
 * 拼装策略（current-note.md 接续入口第 1 项）:
 *   - P5 A 组（agent id=88317c40）+ B 组（agent id=e0196487）完成后
 *   - 主线程统一创建，避免 A/B 组同时写入冲突
 *   - 主线程同时补建 B 组遗漏的 live/index.ts（与 4 个子目录 index.ts 风格一致）
 *
 * 跨模块导入约束（rules-0 §四 + MODULE-7 AGENTS.md §2.3）:
 *   - 仅做导出聚合，不包含实现逻辑
 *   - 禁止 import 模块8/9 内部实现
 *
 * 命名冲突处理:
 *   - live2d/StageTransform 与 vrm/StageTransform 同名
 *   - TypeScript `export *` 命名冲突会报 TS2308 错误（非自动 omit）
 *   - 解决方案: 对 vrm/ 用显式 re-export，omit StageTransform（保留 live2d/ 的 StageTransform 通过 `export *`）
 *   - 调用方需 vrm 版 StageTransform 时直接从 '@/components/business/vrm' 显式 import
 *   - 此为子目录引擎层的内部类型，模块8 页面层一般不直接消费
 * ============================================================================
 */

// =============================================================================
// A 组根组件（11 个，低耦合组件）
// =============================================================================

// 系统类（3）
export { ErrorBoundary } from './error-boundary';
export { LanguageSwitcher } from './language-switcher';
export { SystemMessageBanner } from './system-message-banner';

// 数据展示类（5）
export { AnimatedList } from './animated-list';
export { CountUp } from './count-up';
export { GraphVisualization } from './graph-visualization';
export { TimeAxis } from './time-axis';
export { VirtualList } from './virtual-list';

// 图管理类（2）
export { GraphManager } from './graph-manager';
export { ConnectionSetup } from './connection-setup';

// 布局类（1）
export { AppLayout } from './app-layout';

// =============================================================================
// B 组根组件（6 个，高耦合 + 二次元资产）
// =============================================================================

// 弹窗类（3）
export { CharacterCardModal } from './character-card-modal';
export { DistillationModal } from './distillation-modal';
export { SummaryModal } from './summary-modal';

// 宠物/二次元类（3）
export { PetAvatar } from './pet-avatar';
export type { PetAvatarHandle } from './pet-avatar';
export { PetAudioPanel } from './pet-audio-panel';
export { PetChat, applyAvatarTags } from './pet-chat';
export type { PetMessage, PetChatHandle } from './pet-chat';

// =============================================================================
// 6 子目录 re-export
// =============================================================================

// A 组子目录（2）— layout/ + ui/
export * from './layout';
export * from './ui';

// B 组子目录（4）— avatar/ + live/ + live2d/ + vrm/
// 注: live/index.ts 由主线程补建（B 组遗漏）
// 注: vrm/ 用显式 re-export，omit StageTransform（与 live2d/StageTransform 冲突，TS2308）
export * from './avatar';
export * from './live';
export * from './live2d';
export {
  VRMViewer,
  VRMPanel,
  VRMAudioLipSync,
  createVRMLipSync,
  VRMExpression,
  mapLLMEmotion,
  VRMMotionTrigger,
  createVRMRuntime,
  destroyRuntime,
  resizeRuntime,
  updateStageTransform,
  applyExpressionMix,
  setParameterOverrides,
} from './vrm';
export type {
  EmotionType,
  EmotionConfig,
  MotionTriggerConfig,
  VRMRuntimeState,
} from './vrm';
// vrm/StageTransform 不在顶层 re-export（与 live2d/StageTransform 冲突）
// 调用方需 vrm 版时直接 import from '@/components/business/vrm'
