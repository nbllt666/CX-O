/**
 * @file index.ts — Liquid Glass 模块导出入口
 * ============================================================================
 * 用途: 统一导出 Liquid Glass 模块的公开 API
 *
 * 导出内容:
 *   - LiquidGlassHost: React 全局挂载组件（main.tsx 使用，新架构）
 *   - LiquidGlassRenderer: WebGL 渲染器类（新架构）
 *   - 类型: GlassElementRect, GlassUniforms
 *   - 异常: GPUContextLossError, GLSLCompileError
 * ============================================================================
 */

// 新架构导出
export { LiquidGlassHost } from './LiquidGlassHost';
export { LiquidGlassRenderer, GPUContextLossError, GLSLCompileError } from './liquid-glass-renderer';
export type { GlassElementRect, GlassUniforms } from './liquid-glass-renderer';
