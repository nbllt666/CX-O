/**
 * index.ts — 二次元元素层统一导出入口
 *
 * 模块: 模块5 二次元元素层
 * 落点: src/components/anime/index.ts
 *
 * 导出内容:
 *   1. 配色板 token（anime-palette.ts）
 *   2. 异常类（anime-palette.ts，6 个 ANI 异常）
 *   3. 类型定义（anime-palette.ts）
 *   4. 装饰动效 hooks（5 个）
 *   5. 组件（AnimeDecoration / ParticleField / CharacterHost）
 *   6. useAnimeIcons hook（I4 §useAnimeIcons，返回 30+ 图标字典）
 *
 * @version 1.0.0
 */

// =============================================================================
// 配色板 + 异常类 + 类型 + 工具函数（anime-palette.ts）
// =============================================================================

export {
  // 配色板 7 色
  ANIME_PALETTE,
  ANIME_PALETTE_ROLES,
  // 玻璃着色 4 阶
  ANIME_GLASS_TINT,
  // 角色情绪 8 色
  ANIME_EMOTION_COLORS,
  EMOTION_USE_CASE_CONSTRAINT,
  EMOTION_USE_CASES,
  // 渐变
  ANIME_GRADIENTS,
  // 使用边界
  USAGE_BOUNDARIES,
  // z-index
  Z_INDEX_LAYERS,
  Z_INDEX_CONSTRAINT,
  // 错误码
  ANI_ERROR_CODES,
  // 工具函数
  getEmotionColor,
  getCharacterZIndex,
  validateDecorationBoundary,
} from './anime-palette';

// =============================================================================
// 异常类导出（6 个 ANI 异常）
// =============================================================================

export {
  AnimeBaseError,
  DecorationOverflowError,
  CharacterAssetError,
  ParticleLimitError,
  DecorationBoundaryViolationError,
  AnimeZIndexConflictError,
  EmotionColorMisuseError,
} from './anime-palette';

// =============================================================================
// 类型导出
// =============================================================================

export type {
  AnimeDecorationType,
  AnimeDecorationTrigger,
  CharacterPage,
  CharacterPosition,
  EmotionType,
  EmotionUseCase,
  ZIndexLayer,
  AnimeDecorationProps,
  CharacterHostProps,
  ParticleFieldProps,
  AnimeIcon,
  ValidationReport,
  ZIndexConfig,
} from './anime-palette';

// =============================================================================
// 装饰动效 hooks（5 个）
// =============================================================================

export { useStarlight } from './use-starlight';
export type { UseStarlightOptions, UseStarlightResult, StarlightParticle } from './use-starlight';

export { useFloatingNotes } from './use-floating-notes';
export type { UseFloatingNotesOptions, UseFloatingNotesResult, FloatingNoteParticle } from './use-floating-notes';

export { usePetalsFall } from './use-petals-fall';
export type { UsePetalsFallOptions, UsePetalsFallResult, PetalParticle } from './use-petals-fall';

export { useGlowPulse } from './use-glow-pulse';
export type { UseGlowPulseOptions, UseGlowPulseResult, GlowPulseConfig } from './use-glow-pulse';

export { useStarTrail } from './use-star-trail';
export type { UseStarTrailOptions, UseStarTrailResult, StarTrailPath } from './use-star-trail';

// =============================================================================
// 组件导出
// =============================================================================

export { AnimeDecoration, setTotalAnimationCount } from './anime-decoration';
export { ParticleField } from './particle-field';
export { CharacterHost, createCharacterAssetError } from './character-host';

// =============================================================================
// useAnimeIcons hook（I4 §useAnimeIcons，返回 30+ 图标字典）
// =============================================================================

export { useAnimeIcons } from './use-anime-icons';
