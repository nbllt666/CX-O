/**
 * index.ts — 模块4 WebGL 玻璃层 统一导出入口
 * ============================================================================
 * 模块: 模块4 WebGL 玻璃层（核心创新层）
 * 落点: src/lib/glass/
 * 上游依赖: 模块1（Token，glass.css uniform 默认值）、模块2（主题，uGlassTintDark/uGlassTintLight）
 * 下游被依赖: 模块6（基础组件 data-glass 属性由 WebGL 层接管）、模块9（响应式性能，移动端降级影响玻璃层）
 *
 * 导出内容:
 *   - GlassTier 枚举/类型 + detectTier + getNextDowngradeTier（tier-detector.ts）
 *   - PerformanceMonitor + PerformanceMetrics（performance-monitor.ts）
 *   - GPUMemoryManager + GPUContextLossError + ContextLossStatus（gpu-memory-manager.ts）
 *   - FBOManager + FBOCreationError + FBOBundle（fbo-ping-pong.ts）
 *   - drawElement + DrawElementOptions + AccuracyLevel + instanced quad 辅助（draw-element.ts）
 *   - GlassRenderer + createGlassShader + 异常类（glass-renderer.ts）
 *   - useGlassTier + setGlassPointerEvents + assertNoConflict + GlassZIndex（use-glass-tier.ts）
 *   - GlassCanvas 组件 + GlassCanvasProps + GlassForm（glass-canvas.tsx）
 * ============================================================================
 */

// ============================================================================
// tier-detector.ts 导出
// ============================================================================

export {
  GlassTier,
  detectTier,
  getNextDowngradeTier,
} from './tier-detector';

export type {
  TierDetectionResult,
} from './tier-detector';

// ============================================================================
// performance-monitor.ts 导出
// ============================================================================

export {
  PerformanceMonitor,
} from './performance-monitor';

export type {
  PerformanceMetrics,
  FrameDropCallback,
} from './performance-monitor';

// ============================================================================
// gpu-memory-manager.ts 导出
// ============================================================================

export {
  GPUMemoryManager,
  GPUContextLossError,
} from './gpu-memory-manager';

export type {
  ContextLossStatus,
} from './gpu-memory-manager';

// ============================================================================
// fbo-ping-pong.ts 导出
// ============================================================================

export {
  FBOManager,
  FBOCreationError,
} from './fbo-ping-pong';

export type {
  FBOBundle,
} from './fbo-ping-pong';

// ============================================================================
// draw-element.ts 导出
// ============================================================================

export {
  drawElement,
  getNextAccuracyLevel,
  createInstancedQuadBuffer,
  drawInstancedQuads,
  getDrawCallLimit,
  getDefaultFps,
  getScrollFps,
} from './draw-element';

export type {
  AccuracyLevel,
  DrawElementOptions,
  GlassInstance,
} from './draw-element';

// ============================================================================
// glass-renderer.ts 导出
// ============================================================================

export {
  GlassRenderer,
  createGlassShader,
  DEFAULT_GLASS_UNIFORMS,
  GLSLCompileError,
  ShaderLinkError,
  TierDegradeError,
} from './glass-renderer';

export type {
  GlassRendererOptions,
  FrameData,
  GlassUniforms,
} from './glass-renderer';

// ============================================================================
// use-glass-tier.ts 导出
// ============================================================================

export {
  useGlassTier,
  setGlassPointerEvents,
  assertNoConflict,
  GlassZIndex,
  PointerEventConflictError,
  ZIndexConflictError,
  DEFAULT_Z_INDEX_MAP,
} from './use-glass-tier';

export type {
  GlassTierResult,
  UseGlassTierOptions,
  PointerEventsMode,
} from './use-glass-tier';

// ============================================================================
// glass-canvas.tsx 导出
// ============================================================================

export {
  GlassCanvas,
} from './glass-canvas';

export type {
  GlassCanvasProps,
  GlassForm,
} from './glass-canvas';
