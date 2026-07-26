/**
 * anime-palette.ts — 二次元元素层配色板 token + 异常类 + 类型定义 + 工具函数
 *
 * 模块: 模块5 二次元元素层
 * 落点: src/components/anime/anime-palette.ts
 *
 * 契约对齐:
 *   - D4 anime_decoration.schema.json（配色板 7 色 + 玻璃着色 4 阶 + 角色情绪 8 色 OBS-B + 渐变 + 使用边界 + z-index OBS-H）
 *   - I4 frontend_anime.pyi（6 个异常类 + getEmotionColor/validateDecorationBoundary/getCharacterZIndex 函数签名）
 *   - E1 frontend_error_codes.schema.json ANI 段 6 个错误码（FE-ANI-001 ~ FE-ANI-006）
 *
 * 上游依赖:
 *   - 模块1 primitive.css（配色板 token，本文件导出对应 TS 常量供 JS 侧消费）
 *   - 模块3 springs.ts（bouncy spring，由 hooks/组件侧消费，本文件不直接引用）
 *
 * OBS-B 强约束: 角色情绪 8 色 useCase=character-emotion|decoration-accent，main-ui 场景调用即失败
 * OBS-H 强约束: z-index 定位（立绘=5 / 装饰=4 / 玻璃=2 / UI=3 / 模态=10），层叠冲突即失败
 *
 * @version 1.0.0
 */

import type { ComponentType, SVGProps } from 'react';

// =============================================================================
// E1 ANI 段错误码常量（FE-ANI-001 ~ FE-ANI-006）
// =============================================================================

/**
 * 模块5 二次元元素层错误码常量。
 *
 * 对齐 E1 frontend_error_codes.schema.json §errorCodes ANI 段（FE-ANI-001 ~ FE-ANI-006）。
 * 所有异常抛出时必须携带这些错误码之一。
 */
export const ANI_ERROR_CODES = {
  /** FE-ANI-001: 装饰动效越界（单页装饰动效占比 > 20% / 单屏 > 3 类 / alpha 总和 > 0.4） */
  DECORATION_OVERFLOW: 'FE-ANI-001',
  /** FE-ANI-002: 角色资产加载失败（Live2D/VRM/PNG/WebP 加载失败） */
  CHARACTER_ASSET_LOAD_FAILED: 'FE-ANI-002',
  /** FE-ANI-003: 粒子限制超限（单屏 alpha 总和 > 0.4） */
  PARTICLE_LIMIT_EXCEEDED: 'FE-ANI-003',
  /** FE-ANI-004: 装饰边界违规（核心交互元件加了装饰） */
  DECORATION_BOUNDARY_VIOLATION: 'FE-ANI-004',
  /** FE-ANI-005: 二次元元素 z-index 冲突（与玻璃层=2/UI=3/模态=10 冲突） */
  ZINDEX_CONFLICT: 'FE-ANI-005',
  /** FE-ANI-006: 情绪色误用（8 色用于 main-ui） */
  EMOTION_COLOR_MISUSE: 'FE-ANI-006',
} as const;

// =============================================================================
// 异常类定义（I4 接口契约 §异常类，6 个异常）
// =============================================================================

/**
 * 二次元元素异常基类——所有 ANI 异常继承此类，携带 errorCode 字段。
 *
 * 对齐 E1 §exceptionContract: "异常抛出时必须附带 errorCode 字段，调用方按 errorCode 路由处理"。
 * 设计模式对齐模块3 MotionBaseError（src/lib/motion/gsap-utils.ts）。
 */
export abstract class AnimeBaseError extends Error {
  constructor(
    message: string,
    public readonly errorCode: string,
  ) {
    super(message);
    this.name = this.constructor.name;
  }
}

/**
 * 装饰动效溢出异常。
 *
 * 对应 I4 frontend_anime.pyi §DecorationOverflowError。
 * 错误码: FE-ANI-001（装饰动效越界）。
 *
 * 抛出条件:
 *   - 单屏装饰元素超过 3 类
 *   - AnimeDecoration 实例化时检测到当前屏幕已有 3 类装饰
 */
export class DecorationOverflowError extends AnimeBaseError {
  constructor(message: string, errorCode: 'FE-ANI-001' = ANI_ERROR_CODES.DECORATION_OVERFLOW) {
    super(message, errorCode);
  }
}

/**
 * 角色立绘资产异常。
 *
 * 对应 I4 frontend_anime.pyi §CharacterAssetError。
 * 错误码: FE-ANI-002（角色资产加载失败）。
 *
 * 抛出条件:
 *   - Live2D 模型加载失败
 *   - VRM 3D 角色加载失败
 *   - 静态立绘 PNG/WebP 资产 404
 *   - 1x/2x/3x srcset 全部加载失败
 *   - staticFallback 资产也不存在
 */
export class CharacterAssetError extends AnimeBaseError {
  constructor(
    message: string,
    errorCode: 'FE-ANI-002' = ANI_ERROR_CODES.CHARACTER_ASSET_LOAD_FAILED,
  ) {
    super(message, errorCode);
  }
}

/**
 * 装饰粒子超限异常。
 *
 * 对应 I4 frontend_anime.pyi §ParticleLimitError。
 * 错误码: FE-ANI-003（粒子限制超限）。
 *
 * 抛出条件:
 *   - 单屏 alpha 总和超过 0.4
 *   - ParticleField 实例化时检测到当前屏幕 alpha 总和已达上限
 */
export class ParticleLimitError extends AnimeBaseError {
  constructor(message: string, errorCode: 'FE-ANI-003' = ANI_ERROR_CODES.PARTICLE_LIMIT_EXCEEDED) {
    super(message, errorCode);
  }
}

/**
 * 装饰动效边界违规异常。
 *
 * 对应 I4 frontend_anime.pyi §DecorationBoundaryViolationError。
 * 错误码: FE-ANI-004（装饰边界违规）。
 *
 * 抛出条件:
 *   - 单屏装饰元素超过 3 类
 *   - 单元素 opacity 超过 0.4
 *   - 单屏 alpha 总和超过 0.4
 *   - 核心交互元件（表单/输入框/按钮）上加了二次元装饰（阻断式）
 */
export class DecorationBoundaryViolationError extends AnimeBaseError {
  constructor(
    message: string,
    errorCode: 'FE-ANI-004' = ANI_ERROR_CODES.DECORATION_BOUNDARY_VIOLATION,
  ) {
    super(message, errorCode);
  }
}

/**
 * 二次元元素 z-index 冲突异常（OBS-H 处置）。
 *
 * 对应 I4 frontend_anime.pyi §AnimeZIndexConflictError。
 * 错误码: FE-ANI-005（二次元元素 z-index 冲突）。
 *
 * 抛出条件:
 *   - 角色立绘 z-index 与玻璃层=2 / UI=3 / 模态层=10 冲突
 *   - 装饰条带 z-index 与上述层冲突
 *   - getCharacterZIndex 检测到传入 layer 值与标准分层不符
 */
export class AnimeZIndexConflictError extends AnimeBaseError {
  constructor(message: string, errorCode: 'FE-ANI-005' = ANI_ERROR_CODES.ZINDEX_CONFLICT) {
    super(message, errorCode);
  }
}

/**
 * 角色情绪色误用异常（OBS-B 处置）。
 *
 * 对应 I4 frontend_anime.pyi §EmotionColorMisuseError。
 * 错误码: FE-ANI-006（情绪色误用）。
 *
 * 抛出条件:
 *   - getEmotionColor 调用时 useCase='main-ui'（8 色禁止进入主 UI 配色）
 *   - 检测到角色情绪色被用于按钮/输入框/导航等主 UI 元素
 */
export class EmotionColorMisuseError extends AnimeBaseError {
  constructor(message: string, errorCode: 'FE-ANI-006' = ANI_ERROR_CODES.EMOTION_COLOR_MISUSE) {
    super(message, errorCode);
  }
}

// =============================================================================
// 字面量联合类型（I4 §TS 类型别名）
// =============================================================================

/**
 * 装饰动效类型枚举（D4 §decorationAnimations 5 类）。
 * - 'star': 星光闪烁
 * - 'music-note': 音符飘动
 * - 'petal': 花瓣飘落
 * - 'glow': 光晕脉动
 * - 'star-trail': 星轨流光
 */
export type AnimeDecorationType = 'star' | 'music-note' | 'petal' | 'glow' | 'star-trail';

/**
 * 装饰动效触发场景枚举。
 * - 'success': 重要操作成功反馈（星光）
 * - 'message-send': Chat 收发消息（音符）
 * - 'page-transition': 页面切换/主题切换（花瓣）
 * - 'hover': 玻璃组件 hover（光晕）
 * - 'active': 导航激活态（星轨）
 */
export type AnimeDecorationTrigger =
  | 'success'
  | 'message-send'
  | 'page-transition'
  | 'hover'
  | 'active';

/**
 * 角色立绘嵌入页面枚举（D4 §characterEmbedding.pages）。
 * Agents/Acp/Settings 页面不嵌入角色（保持工具属性）。
 */
export type CharacterPage = 'dashboard' | 'chat' | 'audiowstation' | 'live' | 'pet';

/**
 * 角色立绘嵌入位置枚举（D4 §characterEmbedding.pages.embedMethod）。
 * - 'sidebar': 侧边静态立绘（Dashboard）
 * - 'avatar': 角色头像（Chat，圆形 96px）
 * - 'topbar-deco': 顶部装饰条带（AudioWorkstation，半透明角色剪影）
 * - 'full-interactive': 完整交互（Live / Pet）
 */
export type CharacterPosition = 'sidebar' | 'avatar' | 'topbar-deco' | 'full-interactive';

/**
 * 角色情绪 8 色枚举（D4 §characterEmotions OBS-B）。
 */
export type EmotionType =
  | 'shy'
  | 'energetic'
  | 'thinking'
  | 'focused'
  | 'surprised'
  | 'relieved'
  | 'disappointed'
  | 'expectant';

/**
 * 角色情绪 8 色用途限定（OBS-B 处置）。
 * - 'character-emotion': 角色表情切换
 * - 'decoration-accent': 装饰动效配色
 * - 禁止 'main-ui': 8 色不进入主 UI 配色
 */
export type EmotionUseCase = 'character-emotion' | 'decoration-accent';

/**
 * z-index 分层枚举（OBS-H 处置）。
 * - 'glass': 玻璃层 z-index=2
 * - 'ui': UI 层 z-index=3
 * - 'decoration-band': 装饰条带 z-index=4
 * - 'character': 角色立绘 z-index=5
 * - 'modal': 模态层 z-index=10
 */
export type ZIndexLayer = 'glass' | 'ui' | 'decoration-band' | 'character' | 'modal';

// =============================================================================
// 结构化类型（I4 §TypedDict，TS 用 interface 实现）
// =============================================================================

/**
 * AnimeDecoration 组件 props。
 * 对应 I4 §AnimeDecorationProps。
 */
export interface AnimeDecorationProps {
  /** 装饰动效类型 */
  type: AnimeDecorationType;
  /** 触发场景 */
  trigger: AnimeDecorationTrigger;
  /** 粒子密度（个/m²）。移动端降至 0.1/m² */
  density: number;
  /** 单元素 opacity 上限 ≤ 0.4 */
  opacity: number;
}

/**
 * CharacterHost 组件 props。
 * 对应 I4 §CharacterHostProps。
 */
export interface CharacterHostProps {
  /** 嵌入页面 */
  page: CharacterPage;
  /** 嵌入位置 */
  position: CharacterPosition;
  /** 角色立绘 z-index。通过 getCharacterZIndex() 获取（OBS-H） */
  zIndex: number;
  /** 静态降级资产路径（SVG 占位立绘）。Live2D/VRM 加载失败时使用 */
  staticFallback?: string | null;
}

/**
 * ParticleField 组件 props。
 * 对应 I4 §ParticleFieldProps。
 */
export interface ParticleFieldProps {
  /** 粒子类型 */
  particleType: AnimeDecorationType;
  /** 粒子密度 */
  density: number;
  /** 单屏 alpha 总和上限 ≤ 0.4。超过时抛出 ParticleLimitError */
  maxAlpha: number;
  /** 触发场景 */
  trigger: AnimeDecorationTrigger;
}

/**
 * 单个二次元图标定义。
 * 对应 I4 §AnimeIcon。
 */
export interface AnimeIcon {
  /** 图标名 */
  name: string;
  /** 图标组件（React.lazy 懒加载） */
  component: ComponentType<SVGProps<SVGSVGElement>>;
  /** 关键词（用于搜索） */
  keywords: string[];
}

/**
 * 装饰动效边界校验报告。
 * 对应 I4 §ValidationReport。
 */
export interface ValidationReport {
  /** 是否通过 */
  passed: boolean;
  /** 违规详情列表 */
  violations: Array<{ rule: string; detail: string }>;
  /** 摘要 */
  summary: string;
}

/**
 * z-index 分层配置。
 * 对应 I4 §ZIndexConfig。
 */
export interface ZIndexConfig {
  layer: ZIndexLayer;
  value: number;
}

// =============================================================================
// 配色板 7 色（D4 §palette，对齐模块1 primitive.css）
// =============================================================================

/**
 * 配色板 7 色（粉紫青渐变体系）。
 *
 * 对齐 D4 anime_decoration.schema.json §palette。
 * 对齐模块1 primitive.css:
 *   - sakuraPink → --color-primary-300 (#FFB7E1)
 *   - dreamPurple → --color-secondary-500 (#9D7CFF)
 *   - starSeaCyan → --color-tertiary-500 (#7CD8FF)
 *   - dreamPinkPurple → glass-tint-dark-theme (#E0BBE4)
 *   - moonlightWhite → --color-foreground-dark (#F5F5FA)
 *   - nightSkyDeepPurple → --color-background-dark (#2D1B4E)
 *   - dawnCream → --color-background-light (#FAF6F0)
 */
export const ANIME_PALETTE = {
  /** 樱花粉 #FFB7E1：主强调色（按钮/激活态） */
  sakuraPink: '#FFB7E1',
  /** 梦境紫 #9D7CFF：次强调色（链接/图标） */
  dreamPurple: '#9D7CFF',
  /** 星海青 #7CD8FF：辅助色（信息提示） */
  starSeaCyan: '#7CD8FF',
  /** 梦境粉紫 #E0BBE4：玻璃着色层（暗色主题） */
  dreamPinkPurple: '#E0BBE4',
  /** 月光白 #F5F5FA：玻璃高光（亮色主题） */
  moonlightWhite: '#F5F5FA',
  /** 夜空深紫 #2D1B4E：暗色主题背景 */
  nightSkyDeepPurple: '#2D1B4E',
  /** 晨曦米白 #FAF6F0：亮色主题背景 */
  dawnCream: '#FAF6F0',
} as const;

/**
 * 配色板 7 色角色映射。
 * 对齐 D4 §palette.*.role。
 */
export const ANIME_PALETTE_ROLES = {
  sakuraPink: 'primary-accent',
  dreamPurple: 'secondary-accent',
  starSeaCyan: 'auxiliary-info',
  dreamPinkPurple: 'glass-tint-dark-theme',
  moonlightWhite: 'glass-highlight-light-theme',
  nightSkyDeepPurple: 'dark-theme-background',
  dawnCream: 'light-theme-background',
} as const;

// =============================================================================
// 玻璃着色 4 阶（D4 §glassTint，对齐模块1 primitive.css §1.4）
// =============================================================================

/**
 * 玻璃着色 4 阶：作为 Liquid Glass 着色层，由低到高透明度递减。
 *
 * 对齐 D4 §glassTint。
 * 对齐模块1 primitive.css:
 *   - tier1 → --color-glass-tint-sakura
 *   - tier2 → --color-glass-tint-lavender
 *   - tier3 → --color-glass-tint-azure
 *   - tier4 → --color-glass-tint-white
 */
export const ANIME_GLASS_TINT = {
  /** 第 1 阶（樱花粉系） */
  tier1: 'rgba(255,183,225,0.08)',
  /** 第 2 阶（梦境紫系） */
  tier2: 'rgba(157,124,255,0.06)',
  /** 第 3 阶（星海青系） */
  tier3: 'rgba(124,216,255,0.05)',
  /** 第 4 阶（月光白系） */
  tier4: 'rgba(255,255,255,0.03)',
} as const;

// =============================================================================
// 角色情绪 8 色（D4 §characterEmotions，OBS-B 用途收窄）
// =============================================================================

/**
 * 角色情绪 8 色映射（OBS-B 处置）。
 *
 * 对齐 D4 §characterEmotions。
 * 对齐模块1 primitive.css §1.5 --color-emotion-* 系列。
 *
 * OBS-B 用途限制: 仅用于 character-emotion（角色表情切换）和 decoration-accent（装饰动效配色），
 * 禁止用于 main-ui（主 UI 配色），违反时抛出 EmotionColorMisuseError。
 */
export const ANIME_EMOTION_COLORS: Record<EmotionType, string> = {
  /** 害羞 #FF9EC4 */
  shy: '#FF9EC4',
  /** 活力 #FFD580 */
  energetic: '#FFD580',
  /** 思考 #9D7CFF */
  thinking: '#9D7CFF',
  /** 专注 #7CD8FF */
  focused: '#7CD8FF',
  /** 惊讶 #FFE57C */
  surprised: '#FFE57C',
  /** 安心 #A8E6CF */
  relieved: '#A8E6CF',
  /** 失落 #B8A0C8 */
  disappointed: '#B8A0C8',
  /** 期待 #FFB7E1 */
  expectant: '#FFB7E1',
};

/**
 * OBS-B 全局约束：8 色用途收窄。
 * 对齐 D4 §characterEmotions.useCaseConstraint。
 */
export const EMOTION_USE_CASE_CONSTRAINT = {
  /** 允许用途：角色表情切换 / 装饰动效配色 */
  allowedUseCases: ['character-emotion', 'decoration-accent'] as const,
  /** 禁止用途：主 UI 配色 */
  prohibitedUseCase: 'main-ui',
} as const;

/**
 * 角色情绪色 useCase 限定映射（每色均限定为 character-emotion + decoration-accent）。
 * 对齐 D4 §characterEmotions.*.useCase。
 */
export const EMOTION_USE_CASES: Record<EmotionType, readonly EmotionUseCase[]> = {
  shy: ['character-emotion', 'decoration-accent'],
  energetic: ['character-emotion', 'decoration-accent'],
  thinking: ['character-emotion', 'decoration-accent'],
  focused: ['character-emotion', 'decoration-accent'],
  surprised: ['character-emotion', 'decoration-accent'],
  relieved: ['character-emotion', 'decoration-accent'],
  disappointed: ['character-emotion', 'decoration-accent'],
  expectant: ['character-emotion', 'decoration-accent'],
};

// =============================================================================
// 渐变定义（D4 §gradients，对齐模块1 primitive.css §1.9）
// =============================================================================

/**
 * 渐变定义：主渐变 + 玻璃内层 radial-gradient。
 * 对齐 D4 §gradients。
 * 对齐模块1 primitive.css: --gradient-sakura / --gradient-glass-inner。
 */
export const ANIME_GRADIENTS = {
  /** 主渐变 --gradient-sakura：樱花粉→梦境紫→星海青，135deg */
  mainGradient: {
    token: '--gradient-sakura',
    value: 'linear-gradient(135deg, #FFB7E1 0%, #9D7CFF 50%, #7CD8FF 100%)',
  },
  /** 玻璃内层渐变 radial-gradient，从中心向外 alpha 递减 */
  glassInnerGradient: {
    type: 'radial-gradient' as const,
    alphaRange: '0.04 → 0.01',
  },
} as const;

// =============================================================================
// 使用边界 5 项（D4 §usageBoundaries，克制原则）
// =============================================================================

/**
 * 使用边界 5 项常量（克制原则，Apple 简约底色）。
 *
 * 对齐 D4 §usageBoundaries。
 * 这 5 项在 validateDecorationBoundary + AnimeDecoration 组件中做运行时校验。
 */
export const USAGE_BOUNDARIES = {
  /** 装饰动效总量上限：单页同时运行的装饰动效 ≤ 页面总动效的 20% */
  decorationAnimationRatio: 0.2,
  /** 装饰元素 opacity 上限：单元素 ≤ 0.4 */
  singleElementOpacity: 0.4,
  /** 单屏 alpha 总和上限：≤ 0.4 */
  singleScreenAlphaSum: 0.4,
  /** 单屏装饰元素类别上限：不超过 3 类 */
  singleScreenCategories: 3,
  /** 核心交互元件禁装饰：严禁在表单/输入框/按钮等核心交互元件上加二次元装饰 */
  coreInteractionProhibition: true,
  /** prefers-reduced-motion 下装饰动效全部关闭 */
  prefersReducedMotion: 'all-decoration-closed' as const,
} as const;

// =============================================================================
// z-index 标准分层（D4 §characterEmbedding.zIndexPolicy，OBS-H 处置）
// =============================================================================

/**
 * z-index 标准分层（OBS-H 处置）。
 *
 * 对齐 D4 §characterEmbedding.zIndexPolicy。
 * 对齐 C1 frontend_glass_config.schema.json 的 z-index 配置。
 *
 * 分层定义:
 *   - glass: 2（玻璃层）
 *   - ui: 3（UI 层）
 *   - decoration-band: 4（装饰条带）
 *   - character: 5（角色立绘）
 *   - modal: 10（模态层）
 */
export const Z_INDEX_LAYERS: Record<ZIndexLayer, number> = {
  glass: 2,
  ui: 3,
  'decoration-band': 4,
  character: 5,
  modal: 10,
};

/**
 * z-index 分层约束（OBS-H）。
 * 对齐 D4 §characterEmbedding.zIndexPolicy.constraint。
 */
export const Z_INDEX_CONSTRAINT =
  'character-standee > ui > glass, but < modal; no conflict with glass/ui layers';

// =============================================================================
// 核心交互元件标签黑名单（用于 validateDecorationBoundary 第 4 项校验）
// =============================================================================

/**
 * 核心交互元件 HTML 标签黑名单。
 *
 * 对齐 D4 §usageBoundaries.coreInteractionProhibition。
 * 这些标签上严禁加二次元装饰，违反时抛出 DecorationBoundaryViolationError（阻断式）。
 */
const CORE_INTERACTION_TAGS: ReadonlySet<string> = new Set([
  'INPUT',
  'TEXTAREA',
  'SELECT',
  'BUTTON',
  'FORM',
  'OPTION',
  'FIELDSET',
  'A',
  'LABEL',
]);

// =============================================================================
// 函数: getEmotionColor（I4 §getEmotionColor，OBS-B 处置）
// =============================================================================

/**
 * 8 色角色情绪映射（OBS-B 处置）。
 *
 * 对应 I4 frontend_anime.pyi §getEmotionColor。
 *
 * OBS-B 处置（用途范围收窄）:
 *   - useCase='character-emotion': 允许，用于角色表情切换
 *   - useCase='decoration-accent': 允许，用于装饰动效配色
 *   - useCase='main-ui': 禁止，抛出 EmotionColorMisuseError（8 色不进入主 UI 配色）
 *
 * @param emotion 角色情绪枚举
 * @param useCase 用途限定（character-emotion / decoration-accent）
 * @returns hex 色值
 * @throws {EmotionColorMisuseError} 当 useCase='main-ui' 时抛出（errorCode=FE-ANI-006）
 */
export function getEmotionColor(emotion: EmotionType, useCase: EmotionUseCase): string {
  // OBS-B 守护: useCase='main-ui' 即抛出异常
  // 注意: TS 类型已限制 useCase 为 'character-emotion' | 'decoration-accent'，
  // 但运行时可能传入非法值（如从动态配置加载），此处做运行时守护。
  const allowedUseCases = EMOTION_USE_CASE_CONSTRAINT.allowedUseCases;
  if (!allowedUseCases.includes(useCase as EmotionUseCase) || useCase === ('main-ui' as string)) {
    throw new EmotionColorMisuseError(
      `getEmotionColor: useCase='${useCase}' is prohibited for emotion colors. ` +
        `Allowed useCases: ${allowedUseCases.join(', ')}. Prohibited: main-ui (OBS-B).`,
    );
  }

  const color = ANIME_EMOTION_COLORS[emotion];
  if (!color) {
    throw new EmotionColorMisuseError(
      `getEmotionColor: unknown emotion '${emotion}'. Valid: ${Object.keys(ANIME_EMOTION_COLORS).join(', ')}.`,
    );
  }

  return color;
}

// =============================================================================
// 函数: getCharacterZIndex（I4 §getCharacterZIndex，OBS-H 处置）
// =============================================================================

/**
 * 返回角色立绘 z-index（OBS-H 处置）。
 *
 * 对应 I4 frontend_anime.pyi §getCharacterZIndex。
 *
 * z-index 标准分层（OBS-H）:
 *   - glass（玻璃层）= 2
 *   - ui（UI 层）= 3
 *   - decoration-band（装饰条带）= 4
 *   - character（角色立绘）= 5
 *   - modal（模态层）= 10
 *
 * @param layer z-index 分层枚举
 * @returns 对应层的 z-index 值
 * @throws {AnimeZIndexConflictError} 当传入 layer 值不在标准分层中时抛出（errorCode=FE-ANI-005）
 */
export function getCharacterZIndex(layer: ZIndexLayer): number {
  if (!(layer in Z_INDEX_LAYERS)) {
    throw new AnimeZIndexConflictError(
      `getCharacterZIndex: layer='${layer}' is not a valid z-index layer. ` +
        `Valid layers: ${Object.keys(Z_INDEX_LAYERS).join(', ')}.`,
    );
  }
  return Z_INDEX_LAYERS[layer];
}

// =============================================================================
// 函数: validateDecorationBoundary（I4 §validateDecorationBoundary）
// =============================================================================

/**
 * 校验装饰动效边界。
 *
 * 对应 I4 frontend_anime.pyi §validateDecorationBoundary。
 *
 * 校验项（D4 §usageBoundaries 使用边界）:
 *   1. 单屏 ≤ 3 类: 装饰元素类型数 ≤ 3
 *   2. 单元素 opacity ≤ 0.4: 每个装饰元素的 opacity 字段 ≤ 0.4
 *   3. 单屏 alpha 总和 ≤ 0.4: 所有装饰元素的 alpha 总和 ≤ 0.4
 *   4. 核心交互元件禁装饰: targetElement 如果是表单/输入框/按钮等核心交互元件，禁止加装饰
 *
 * @param decorations 当前屏幕所有装饰动效的 props 列表
 * @param targetElement 可选，要附加装饰的目标 DOM 元素
 * @returns ValidationReport 校验报告
 * @throws {DecorationBoundaryViolationError} 当核心交互元件装饰违规（阻断式）时抛出
 */
export function validateDecorationBoundary(
  decorations: AnimeDecorationProps[],
  targetElement?: HTMLElement | null,
): ValidationReport {
  const violations: Array<{ rule: string; detail: string }> = [];

  // 校验 1: 单屏 ≤ 3 类（D4 §usageBoundaries.singleScreenCategories = 3）
  const typeSet = new Set<AnimeDecorationType>(decorations.map((d) => d.type));
  if (typeSet.size > USAGE_BOUNDARIES.singleScreenCategories) {
    violations.push({
      rule: 'singleScreenCategories',
      detail: `装饰元素类型数 ${typeSet.size} 超过上限 ${USAGE_BOUNDARIES.singleScreenCategories}（类别: ${Array.from(typeSet).join(', ')}）`,
    });
  }

  // 校验 2: 单元素 opacity ≤ 0.4（D4 §usageBoundaries.singleElementOpacity = 0.4）
  for (const deco of decorations) {
    if (deco.opacity > USAGE_BOUNDARIES.singleElementOpacity) {
      violations.push({
        rule: 'singleElementOpacity',
        detail: `装饰元素 type='${deco.type}' opacity=${deco.opacity} 超过上限 ${USAGE_BOUNDARIES.singleElementOpacity}`,
      });
    }
  }

  // 校验 3: 单屏 alpha 总和 ≤ 0.4（D4 §usageBoundaries.singleScreenAlphaSum = 0.4）
  const alphaSum = decorations.reduce((sum, d) => sum + d.opacity, 0);
  if (alphaSum > USAGE_BOUNDARIES.singleScreenAlphaSum) {
    violations.push({
      rule: 'singleScreenAlphaSum',
      detail: `单屏 alpha 总和 ${alphaSum.toFixed(3)} 超过上限 ${USAGE_BOUNDARIES.singleScreenAlphaSum}`,
    });
  }

  // 校验 4: 核心交互元件禁装饰（D4 §usageBoundaries.coreInteractionProhibition = true）
  // 阻断式违规——直接抛出异常
  if (targetElement && targetElement.tagName && CORE_INTERACTION_TAGS.has(targetElement.tagName)) {
    throw new DecorationBoundaryViolationError(
      `validateDecorationBoundary: 核心交互元件 <${targetElement.tagName}> 上严禁加二次元装饰（coreInteractionProhibition=true）。`,
    );
  }

  const passed = violations.length === 0;
  return {
    passed,
    violations,
    summary: passed
      ? '所有装饰动效边界校验通过'
      : `发现 ${violations.length} 项违规: ${violations.map((v) => v.rule).join(', ')}`,
  };
}
