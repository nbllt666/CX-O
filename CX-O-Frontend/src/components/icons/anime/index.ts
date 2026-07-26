/**
 * index.ts — 二次元图标扩展包统一注册表
 *
 * 模块: 模块5 二次元元素层 → 图标库
 * 落点: src/components/icons/anime/index.ts
 *
 * 对应 D4 anime_decoration.schema.json §iconLibrary.animeIconPack:
 *   - location: components/icons/anime/
 *   - iconCount: 30+（当前 30 个）
 *   - format: SVG
 *   - features: [currentColor-support, lazy-load]
 *   - prohibition: no-emoji-substitution
 *
 * 使用边界（D4 §iconLibrary.useBoundary）:
 *   - 允许场景: 创作 / 聊天 / 角色页（灵感类）
 *   - 禁止场景: 设置 / 管理（工具类，用 Lucide）
 *
 * @version 1.0.0
 */

import type { ComponentType, SVGProps } from 'react';

/** 图标组件类型 */
export type AnimeIconComponent = ComponentType<SVGProps<SVGSVGElement>>;

/** 图标元数据（用于 useAnimeIcons 注册） */
export interface AnimeIconMeta {
  /** 图标名（kebab-case） */
  name: string;
  /** 动态加载器（React.lazy 用，Vite 自动代码分割） */
  loader: () => Promise<{ default: AnimeIconComponent }>;
  /** 关键词（用于搜索） */
  keywords: string[];
}

/**
 * 30 个二次元图标注册表。
 *
 * 每个图标通过动态 import() 实现按需加载（React.lazy）。
 * Vite 会自动将每个图标文件分割为独立 chunk，实现 tree-shakeable。
 *
 * 所有图标均使用 currentColor 继承颜色，禁用 emoji 替代。
 */
export const animeIconRegistry: AnimeIconMeta[] = [
  { name: 'music-note', loader: () => import('./music-note'), keywords: ['音符', '♪', 'music', 'note'] },
  { name: 'star', loader: () => import('./star'), keywords: ['星光', '✦', 'star', 'twinkle'] },
  { name: 'petal', loader: () => import('./petal'), keywords: ['花瓣', '❀', 'petal', 'flower'] },
  { name: 'crystal', loader: () => import('./crystal'), keywords: ['水晶', '♦', 'crystal', 'gem'] },
  { name: 'ribbon', loader: () => import('./ribbon'), keywords: ['丝带', '～', 'ribbon', 'bow'] },
  { name: 'bell', loader: () => import('./bell'), keywords: ['铃铛', 'bell', 'chime'] },
  { name: 'heart', loader: () => import('./heart'), keywords: ['爱心', 'heart', 'love'] },
  { name: 'moon', loader: () => import('./moon'), keywords: ['月亮', 'moon', 'crescent'] },
  { name: 'sparkle', loader: () => import('./sparkle'), keywords: ['闪烁', 'sparkle', 'shine'] },
  { name: 'flower', loader: () => import('./flower'), keywords: ['花朵', 'flower', 'bloom'] },
  { name: 'butterfly', loader: () => import('./butterfly'), keywords: ['蝴蝶', 'butterfly', 'wing'] },
  { name: 'feather', loader: () => import('./feather'), keywords: ['羽毛', 'feather', 'plume'] },
  { name: 'bubble', loader: () => import('./bubble'), keywords: ['气泡', 'bubble', 'foam'] },
  { name: 'cloud', loader: () => import('./cloud'), keywords: ['云朵', 'cloud', 'sky'] },
  { name: 'rainbow', loader: () => import('./rainbow'), keywords: ['彩虹', 'rainbow', 'arc'] },
  { name: 'shooting-star', loader: () => import('./shooting-star'), keywords: ['流星', 'shooting-star', 'meteor'] },
  { name: 'constellation', loader: () => import('./constellation'), keywords: ['星座', 'constellation', 'stars'] },
  { name: 'wing', loader: () => import('./wing'), keywords: ['翅膀', 'wing', 'angel'] },
  { name: 'crown', loader: () => import('./crown'), keywords: ['皇冠', 'crown', 'royal'] },
  { name: 'scepter', loader: () => import('./scepter'), keywords: ['权杖', 'scepter', 'staff'] },
  { name: 'gem', loader: () => import('./gem'), keywords: ['宝石', 'gem', 'jewel'] },
  { name: 'sakura', loader: () => import('./sakura'), keywords: ['樱花', 'sakura', 'cherry-blossom'] },
  { name: 'lily', loader: () => import('./lily'), keywords: ['百合', 'lily', 'flower'] },
  { name: 'rose', loader: () => import('./rose'), keywords: ['玫瑰', 'rose', 'flower'] },
  { name: 'sunflower', loader: () => import('./sunflower'), keywords: ['向日葵', 'sunflower', 'sun'] },
  { name: 'fish', loader: () => import('./fish'), keywords: ['鱼', 'fish', 'marine'] },
  { name: 'bird', loader: () => import('./bird'), keywords: ['鸟', 'bird', 'fly'] },
  { name: 'cat-paw', loader: () => import('./cat-paw'), keywords: ['猫爪', 'cat-paw', 'paw', 'cute'] },
  { name: 'fox', loader: () => import('./fox'), keywords: ['狐狸', 'fox', 'animal'] },
  { name: 'dragon', loader: () => import('./dragon'), keywords: ['龙', 'dragon', 'mythical'] },
];

/** 图标数量 */
export const ANIME_ICON_COUNT = animeIconRegistry.length;
