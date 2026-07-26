/**
 * use-anime-icons.ts — 二次元图标扩展包 hook
 *
 * 模块: 模块5 二次元元素层
 * 落点: src/components/anime/use-anime-icons.ts
 *
 * 对应 I4 frontend_anime.pyi §useAnimeIcons:
 *   def useAnimeIcons() -> Dict[str, AnimeIcon]
 *   "React hook: 返回二次元图标扩展包（30+ 专属图标），按需加载。"
 *
 * AnimeIcon 结构（I4 §AnimeIcon TypedDict）:
 *   { name: string; component: React.ComponentType<SVGProps<SVGSVGElement>>; keywords: string[] }
 *
 * 实现细节（I4 契约要求）:
 *   - SVG 格式，支持 currentColor
 *   - 按需加载（React.lazy + 动态 import）
 *   - 存放于 src/components/icons/anime/
 *   - tree-shakeable
 *
 * 使用边界（merged.md §3.2）:
 *   - 二次元图标仅在"灵感类"场景使用（创作/聊天/角色页）
 *   - 工具类场景（设置/管理）用 Lucide
 *   - 禁止 emoji 替代
 *
 * 异常处理（I4 §Raises）:
 *   - 无异常抛出——hook 始终返回图标字典
 *   - 单个图标渲染时加载失败由消费方 ErrorBoundary 捕获（hook 不负责渲染期错误）
 *
 * @version 1.0.0
 */

import { lazy, useMemo } from 'react';
import type { ComponentType, SVGProps } from 'react';
import { animeIconRegistry } from '../icons/anime';
import type { AnimeIcon } from './anime-palette';

/**
 * 构建懒加载图标字典。
 *
 * 遍历 animeIconRegistry，对每个 loader 调用 React.lazy 创建懒加载组件，
 * 组装为 Record<name, AnimeIcon> 字典。
 *
 * React.lazy 会自动配合 Vite 的代码分割，每个图标文件成为独立 chunk。
 * 消费方需用 <Suspense fallback={...}> 包裹图标渲染区域。
 *
 * @returns 图标名字典，key 为图标名（kebab-case），value 为 AnimeIcon 结构
 */
function buildIconDictionary(): Record<string, AnimeIcon> {
  const dict: Record<string, AnimeIcon> = {};

  for (const meta of animeIconRegistry) {
    // React.lazy 包装动态 import loader，实现按需加载
    // loader 签名: () => Promise<{ default: ComponentType<SVGProps<SVGSVGElement>> }>
    // 与 React.lazy 期望的签名完全匹配
    const LazyIcon = lazy(meta.loader);

    dict[meta.name] = {
      name: meta.name,
      component: LazyIcon as ComponentType<SVGProps<SVGSVGElement>>,
      keywords: meta.keywords,
    };
  }

  return dict;
}

/**
 * React hook: 返回二次元图标扩展包（30+ 专属图标），按需加载。
 *
 * 对应 I4 frontend_anime.pyi §useAnimeIcons:
 *   def useAnimeIcons() -> Dict[str, AnimeIcon]
 *   对应 TS: ``useAnimeIcons(): Record<string, AnimeIcon>``
 *
 * 返回值:
 *   图标名字典（Record<string, AnimeIcon>），key 为图标名（kebab-case），value 为 AnimeIcon
 *
 * 使用示例:
 *   ```tsx
 *   const icons = useAnimeIcons();
 *   const MusicNote = icons['music-note']?.component;
 *   return (
 *     <Suspense fallback={<span>...</span>}>
 *       {MusicNote && <MusicNote className="w-4 h-4" />}
 *     </Suspense>
 *   );
 *   ```
 *
 * @returns Record<string, AnimeIcon> 图标名字典
 */
export function useAnimeIcons(): Record<string, AnimeIcon> {
  // useMemo 缓存字典，避免每次渲染都重建（registry 是静态的）
  return useMemo(() => buildIconDictionary(), []);
}
