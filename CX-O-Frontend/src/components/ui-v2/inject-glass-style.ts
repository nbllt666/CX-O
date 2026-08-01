/**
 * @file inject-glass-style.ts — Liquid Glass 样式注入工具（v2 简化版）
 * ============================================================================
 * v2 改造要点:
 *   - ✂️ 删除 4 级 tier 系统（injectGlassClassName 不再区分 tier）
 *   - ✂️ 删除 GlassInjectionError / COM_ERROR_CODES / GlassInjectionConfig 等过度工程化代码
 *   - ✂️ 删除 SUPPORTED_COMPONENT_NAMES 白名单（不再需要校验）
 *   - ✨ 导出 glassPanelClass / glassPanelInteractiveClass 常量字符串
 *   - ✨ buildGlassDataAttributes 简化为仅返回 data-glass="true"
 *
 * 新架构中:
 *   - 玻璃样式由 .glass-panel CSS 类提供（glass-classes.css）
 *   - WebGL 主体由 .webgl-active class 切换（LiquidGlassHost 控制）
 *   - 组件不再感知 tier，只挂 data-glass 属性 + glass-panel 类
 *
 * 兼容性: 保留 injectGlassClassName / isValidGlassTier 旧签名作为 shim，
 *         内部忽略 tier 参数，波5清理后可删除。
 * ============================================================================
 */

/**
 * @deprecated v2 不再使用 tier 系统。保留类型以维持 GlassComponentProps.glassTier
 * 字段的类型兼容性。新架构由 LiquidGlassHost 自身处理降级，组件不应再读取此字段。
 * 原 @/lib/glass/tier-detector.ts 已于波5删除，此类型为本地兼容定义。
 */
export type GlassTier = 1 | 2 | 3 | 4;

/** 玻璃面板基础类（CSS 兜底 + WebGL 主体切换由 .webgl-active class 控制） */
export const glassPanelClass = 'glass-panel';

/** 交互玻璃面板类（hover/active Apple 风格微交互） */
export const glassPanelInteractiveClass = 'glass-panel-interactive';

/** 大尺寸玻璃面板类（dialog overlay / 大型卡片） */
export const glassPanelLgClass = 'glass-panel-lg';

/**
 * 构建 data-glass 属性对象（WebGL DOM 扫描需要）。
 *
 * 简化版：仅返回 data-glass="true"，不再需要 tier 参数。
 * WebGL LiquidGlassHost 扫描 [data-glass="true"] 元素并作为 uniform 传入 shader。
 *
 * @param dataGlass 是否挂载 data-glass 属性（默认 true）
 * @param _glassTier 已废弃，新架构不再使用 tier 概念（兼容性保留）
 * @returns 属性对象，可直接展开到组件 props
 */
export function buildGlassDataAttributes(
  dataGlass: boolean = true,
  _glassTier?: unknown,
): Record<string, string> {
  return dataGlass ? { 'data-glass': 'true' } : {};
}

// ============================================================================
// 兼容性导出（波3 迁移期使用，波5 清理后删除）
// ============================================================================

/**
 * @deprecated v2 简化版：不再区分 tier，直接拼接 glassPanelClass。
 * 保留旧签名以避免破坏未迁移组件，内部忽略 glassTier 参数。
 *
 * @param baseClassName 组件基础 className
 * @param _glassTier 已废弃，新架构不再使用 tier 概念
 * @returns 注入 glass-panel 类后的 className
 */
export function injectGlassClassName(
  baseClassName: string,
  _glassTier?: unknown,
): string {
  return [baseClassName, glassPanelClass].filter(Boolean).join(' ');
}

/**
 * @deprecated v2 简化版：新架构不再使用 tier 概念，始终返回 false。
 * 保留旧签名以避免破坏未迁移组件的类型守卫逻辑。
 *
 * @param _tier 待校验的 tier 值（已废弃）
 * @returns 始终返回 false
 */
export function isValidGlassTier(_tier: unknown): _tier is never {
  return false;
}
