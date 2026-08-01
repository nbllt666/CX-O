/**
 * @file with-glass-data-attribute.tsx — data-glass 属性 HOC（由 WebGL 层接管玻璃渲染）
 * ============================================================================
 * 模块: 模块6 基础组件层（shadcn ui-v2）— 波1 基础设施
 * 落点: C:\CX-O\CX-O-Frontend\src\components\ui-v2\with-glass-data-attribute.tsx
 *
 * 契约对齐:
 *   - I5 frontend_components_uiv2.pyi §withGlassDataAttribute + §GlassComponentProps
 *   - I1 frontend_glass.pyi §GlassRenderer（扫描 data-glass 元素接管渲染）
 *   - D2 glass_tier_config.schema.json（data-glass-tier 属性值）
 *   - merged.md §4.2 定制策略（每个组件挂载 data-glass 属性）
 *
 * 核心职责（I5 §withGlassDataAttribute + merged.md §4.2）:
 *   - 为传入组件包装一层，自动挂载 data-glass="true" 属性
 *   - WebGL 层（I1 GlassRenderer）扫描 data-glass 元素并接管渲染
 *   - 不修改组件原有 props 接口（仅添加可选 dataGlass / glassTier prop）
 *   - 纯操作，运行时由 WebGL 层处理渲染（无异常抛出）
 *
 * 跨模块导入约束（rules-0 §四 + MODULE-6 AGENTS.md §4.3）:
 *   - 仅 import 模块4 GlassTier 类型（D2 唯一真相源）
 *   - 仅 import 本模块 buildGlassDataAttributes 辅助函数
 *   - 仅 import 第三方库 react
 *   - 禁止 import 模块5/7/8/9 内部实现
 *
 * 使用示例:
 *   ```tsx
 *   const GlassButton = withGlassDataAttribute(Button);
 *   // <GlassButton dataGlass={true} glassTier={3}>Click</GlassButton>
 *   // 渲染后: <button data-glass="true" data-glass-tier="tier3-css">Click</button>
 *   ```
 * ============================================================================
 */

import React from 'react';
import { buildGlassDataAttributes, isValidGlassTier, type GlassTier } from './inject-glass-style';

// =============================================================================
// HOC props 扩展类型（对应 I5 §GlassComponentProps 的 dataGlass + glassTier 字段）
// =============================================================================

/**
 * HOC 注入的额外 props（对应 I5 §GlassComponentProps.dataGlass + glassTier 字段）。
 *
 * 此接口仅包含 withGlassDataAttribute HOC 注入的字段，组件层可通过 GlassComponentProps 继承更多字段。
 */
export interface WithGlassDataAttributeProps {
  /** 是否挂载 data-glass 属性（默认 true，由 WebGL 层接管渲染） */
  readonly dataGlass?: boolean;
  /** 强制指定 glass tier（可选，默认不挂载 data-glass-tier，由 useGlassTier 自动检测） */
  readonly glassTier?: GlassTier;
}

// =============================================================================
// withGlassDataAttribute HOC（对应 I5 §withGlassDataAttribute）
// =============================================================================

/**
 * HOC: 为组件挂载 data-glass 属性，由 WebGL 层接管玻璃渲染（对应 I5 §withGlassDataAttribute）。
 *
 * 实现细节（merged.md §4.2 + I1 §GlassRenderer）:
 *   - 为传入组件包装一层，自动挂载 data-glass="true" 属性
 *   - WebGL 层（I1 GlassRenderer）扫描 data-glass 元素并接管渲染
 *   - 不修改组件原有 props 接口（仅添加可选 dataGlass / glassTier prop）
 *   - 当 dataGlass=false 时不挂载 data-glass 属性（用于显式禁用玻璃渲染）
 *   - 当 glassTier 提供且合法时挂载 data-glass-tier 属性（对齐 D2 §tiers.tier*.name）
 *
 * 泛型约束:
 *   - P extends object: 被包装组件的 props 类型必须是对象类型
 *   - 返回新组件类型: React.ComponentType<P & WithGlassDataAttributeProps>
 *
 * 纯操作约定（I5 §withGlassDataAttribute Raises）:
 *   无异常抛出——HOC 包装是纯操作，运行时由 WebGL 层处理渲染。
 *
 * @param Component 被包装的组件
 * @returns 包装后的新组件，自动挂载 data-glass 属性
 */
export function withGlassDataAttribute<P extends object>(
  Component: React.ComponentType<P>,
): React.ComponentType<P & WithGlassDataAttributeProps> {
  const WrappedComponent = React.forwardRef<HTMLElement, P & WithGlassDataAttributeProps>(
    function WithGlassDataAttributeWrapped(props, ref) {
      const { dataGlass = true, glassTier, ...restProps } = props;

      // 构建 data-glass + data-glass-tier 属性对象
      // 当 glassTier 提供且合法时挂载 data-glass-tier（对齐 D2 §tiers.tierId 1-4）
      const validTier = isValidGlassTier(glassTier) ? glassTier : undefined;
      const glassAttributes = buildGlassDataAttributes(dataGlass, validTier);

      // 将 glassAttributes 展开到组件 props（覆盖同名属性）
      // 注意: ref 透传由 forwardRef 处理，restProps 已剥离 dataGlass/glassTier
      const mergedProps = {
        ...restProps,
        ...glassAttributes,
        ref,
      } as unknown as P & React.RefAttributes<HTMLElement>;

      return React.createElement(Component, mergedProps);
    },
  );

  // 保留被包装组件的 displayName（便于 React DevTools 调试）
  const originalDisplayName =
    Component.displayName || Component.name || 'AnonymousComponent';
  WrappedComponent.displayName = `withGlassDataAttribute(${originalDisplayName})`;

  // 类型断言: ForwardRefExoticComponent → ComponentType
  // React.forwardRef 返回 ForwardRefExoticComponent，与 I5 契约要求的 ComponentType 在
  // propTypes 属性上存在类型不兼容（严格模式下 WeakValidationMap 索引签名差异）。
  // 两者在运行时行为一致，使用 as unknown as 断言绕过严格类型检查。
  return WrappedComponent as unknown as React.ComponentType<P & WithGlassDataAttributeProps>;
}

// =============================================================================
// 辅助: 显式启用/禁用 data-glass 属性的便捷函数
// =============================================================================

/**
 * 辅助: 构建启用 data-glass 属性的 props 对象（便捷函数）。
 *
 * 用于组件内部需要显式控制 data-glass 属性时调用，等价于:
 *   buildGlassDataAttributes(true, glassTier)
 *
 * @param glassTier 可选的目标 tier（提供则挂载 data-glass-tier）
 * @returns 包含 data-glass="true" 的属性对象
 */
export function enableGlassAttribute(glassTier?: GlassTier): Record<string, string> {
  return buildGlassDataAttributes(true, glassTier);
}

/**
 * 辅助: 构建禁用 data-glass 属性的空 props 对象（便捷函数）。
 *
 * 用于组件内部需要显式禁用玻璃渲染时调用（如 prefers-reduced-transparency 命中场景）。
 *
 * @returns 空属性对象（不挂载 data-glass 属性）
 */
export function disableGlassAttribute(): Record<string, string> {
  return buildGlassDataAttributes(false, undefined);
}
